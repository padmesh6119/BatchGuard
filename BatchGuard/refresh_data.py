"""Build a clean historical snapshot and publish it only after validation."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import pandas as pd

from src.process_month import process_month
from src.build_dataset import build_dataset
from src.normalize_manufacturers import main as normalize_manufacturers
from src.normalize_failure_types import main as normalize_failure_types
from snapshot_store import DATASETS, file_hash, publish_pointer, refresh_lock, validate_snapshot

ROOT = Path(__file__).resolve().parent


def validate_outputs(directory, months):
    frames = [pd.read_csv(directory / name, dtype=str, keep_default_na=False) for name in DATASETS]
    if len({len(df) for df in frames}) != 1 or frames[0].empty:
        raise ValueError("Analytical and derived outputs must be nonempty and have matching counts.")
    identifiers = []
    for frame in frames:
        if "build_record_id" not in frame or frame["build_record_id"].duplicated().any():
            raise ValueError("Missing or duplicated record IDs.")
        identifiers.append(set(frame["build_record_id"]))
    if not all(ids == identifiers[0] for ids in identifiers):
        raise ValueError("Derived output IDs differ from analytical IDs.")
    if set(frames[0]["collection_month"]) != set(months):
        raise ValueError("Output months do not match the current workbook manifest.")
    provenance = pd.read_csv(directory / "all_months_provenance.csv", dtype=str, keep_default_na=False)
    if provenance["build_record_id"].duplicated().any() or not identifiers[0].issubset(set(provenance["build_record_id"])):
        raise ValueError("Analytical records lack unique workbook-row provenance.")
    return {"analytical_records": len(frames[0]), "months": months,
            "categories": frames[0]["source_category"].value_counts().to_dict()}


def run_pipeline(stage, months):
    previous_directory = Path.cwd()
    try:
        os.chdir(stage)
        for month in months:
            process_month(month)
        build_dataset()
        normalize_manufacturers()
        normalize_failure_types()
    finally:
        os.chdir(previous_directory)


def main(root=ROOT):
    root = Path(root).resolve()
    with refresh_lock(root):
        workbooks = sorted((root / "data" / "raw").glob("*_all.xlsx"))
        if not workbooks:
            raise FileNotFoundError("Place monthly YYYY-MM_all.xlsx workbooks in data/raw/.")
        for workbook in workbooks:
            if not re.fullmatch(r"\d{4}-\d{2}_all\.xlsx", workbook.name):
                raise ValueError(f"Invalid monthly filename: {workbook.name}")
            pd.Period(workbook.name[:7], freq="M")
        months = [path.name[:7] for path in workbooks]
        snapshots = root / "data" / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".build-", dir=snapshots))
        try:
            (stage / "data" / "raw").mkdir(parents=True)
            sources = []
            for workbook in workbooks:
                destination = stage / "data" / "raw" / workbook.name
                shutil.copy2(workbook, destination)
                sources.append({"file": workbook.name, "sha256": file_hash(destination),
                                "provenance_status": "local_workbook_origin_not_independently_verified"})
            print(f"Building {len(months)} monthly workbooks in an isolated staging directory.")
            run_pipeline(stage, months)
            summary = validate_outputs(stage / "data" / "processed", months)
            outputs = {p.relative_to(stage).as_posix(): file_hash(p)
                       for p in sorted(stage.rglob("*")) if p.is_file()}
            code_files = sorted((ROOT / "src").glob("*.py")) + [ROOT / "refresh_data.py", ROOT / "snapshot_store.py"]
            builder = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in code_files}
            identity = hashlib.sha256(json.dumps({"sources": sources, "outputs": outputs,
                                                   "builder": builder}, sort_keys=True).encode()).hexdigest()
            manifest = {"snapshot_id": identity, "created_at": datetime.now(timezone.utc).isoformat(),
                        "sources": sources, "outputs": outputs, "builder": builder, "summary": summary}
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            destination = snapshots / identity
            if destination.exists():
                existing = validate_snapshot(destination)
                if existing["snapshot_id"] != identity:
                    raise ValueError("Existing snapshot identity mismatch.")
            else:
                stage.rename(destination)
            publish_pointer(root, identity)
            print(f"Published snapshot: {identity}")
            print(f"Analytical records: {summary['analytical_records']}; months: {len(months)}")
            return manifest
        finally:
            if stage.exists():
                shutil.rmtree(stage)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"REFRESH FAILED; previous published snapshot retained: {exc}", file=sys.stderr)
        raise
