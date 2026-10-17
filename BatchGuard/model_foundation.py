"""Prepare versioned training inputs and untouched held-out splits; never fit a model."""
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import random
import platform
import tempfile
import shutil

import pandas as pd

from batchguard_engine import historical_priorities, load_dataset
from inspection_stream import ScanEvent, digest
from scan_features import OBSERVATION_SECONDS, SCAN_FEATURES, extract_scan_features, scan_rule_baseline
from snapshot_store import ROOT, active_snapshot, file_hash

HISTORY_FEATURES = ["prior_records", "prior_months", "prior_products", "records_last_month",
                    "records_last_3_months", "months_since_last_report", "unresolved_failure_records"]
HISTORY_TASK = "next_month_report_recurrence"
SCAN_TASK = "simulated_clone_episode"
FOUNDATION_VERSION = "training-foundation-v1"
CITIES = [("Chennai", "Tamil Nadu", 13.08, 80.27), ("Delhi", "Delhi", 28.61, 77.21),
          ("Bengaluru", "Karnataka", 12.97, 77.59), ("Coimbatore", "Tamil Nadu", 11.02, 76.96)]
SEEN_SCENARIOS = ["benign_repeat", "legitimate_distribution", "legitimate_travel", "clone_copy", "clone_burst"]
HELDOUT_SCENARIOS = ["delayed_sync", "slow_copy"]


def history_examples(df):
    nsq = df[df["source_category"].isin(["central_nsq", "state_nsq"])].copy()
    months = sorted(nsq["collection_month"].unique())
    if len(months) < 6:
        raise ValueError("Need at least six collection months for chronological training/validation/test splits.")
    target_months = months[2:]
    split_for = {month: "test" if month in target_months[-2:] else
                 "validation" if month == target_months[-3] else "train" for month in target_months}
    rows = []
    for target in target_months:
        cutoff = str(pd.Period(target, freq="M")-1)
        past = nsq[nsq["collection_month"].le(cutoff)]
        future_counts = nsq[nsq["collection_month"].eq(target)]["manufacturer_name_normalized"].value_counts()
        priorities = historical_priorities(past).set_index("manufacturer_key")["priority_index"].to_dict()
        for manufacturer, group in past.groupby("manufacturer_name_normalized", sort=True):
            if not str(manufacturer).strip():
                continue
            recent_start = str(pd.Period(cutoff, freq="M")-2)
            last = group["collection_month"].max()
            rows.append({
                "example_id": digest([manufacturer, target])[:24], "manufacturer_key": manufacturer,
                "split": split_for[target], "feature_cutoff_month": cutoff, "target_month": target,
                "prior_records": len(group), "prior_months": group["collection_month"].nunique(),
                "prior_products": group["product"].str.strip().replace("", pd.NA).nunique(),
                "records_last_month": int(group["collection_month"].eq(cutoff).sum()),
                "records_last_3_months": int(group["collection_month"].ge(recent_start).sum()),
                "months_since_last_report": pd.Period(cutoff, freq="M").ordinal-pd.Period(last, freq="M").ordinal,
                "unresolved_failure_records": int(group["failure_mapping_status"].isin(["missing", "manual_review_required"]).sum()),
                "baseline_priority_index": float(priorities.get(manufacturer, 0)),
                "target_report_count": int(future_counts.get(manufacturer, 0)),
                "label": int(future_counts.get(manufacturer, 0) > 0),
            })
    return pd.DataFrame(rows)


def recurrence_finding(df, cutoff="2026-01"):
    nsq = df[df["source_category"].isin(["central_nsq", "state_nsq"])]
    prior = nsq[nsq["collection_month"].le(cutoff)]
    later = nsq[nsq["collection_month"].gt(cutoff)]
    known = set(prior.loc[prior["manufacturer_name_normalized"].ne(""), "manufacturer_name_normalized"])
    observed = int(later["manufacturer_name_normalized"].isin(known).sum())
    return {"training_through": cutoff, "later_records": len(later), "previously_seen_text_records": observed,
            "previously_seen_pct": 100*observed/len(later) if len(later) else None,
            "interpretation": "Exact manufacturer-text recurrence among later NSQ reports, not a universal prediction ceiling."}


def make_scan_corpus(df, episodes_per_scenario=30, seed=2026):
    if isinstance(episodes_per_scenario, bool) or not isinstance(episodes_per_scenario, int) or episodes_per_scenario < 2:
        raise ValueError("episodes_per_scenario must be an integer of at least two.")
    reference = df[df["product"].str.strip().ne("") & df["batch_no"].str.strip().ne("")]
    if reference.empty:
        raise ValueError("No product/batch reference pairs available.")
    references = reference.drop_duplicates(["product", "batch_no", "manufacturer_name_normalized"]).to_dict("records")
    rng = random.Random(seed)
    episodes = []
    features = []
    for split in ["train", "validation", "test"]:
        scenarios = SEEN_SCENARIOS + (HELDOUT_SCENARIOS if split == "test" else [])
        count = episodes_per_scenario if split == "train" else max(2, episodes_per_scenario//3)
        for scenario in scenarios:
            for index in range(count):
                eid = f"{split}-{scenario}-{index}"
                ref = rng.choice(references)
                start = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=len(episodes))
                city_a, city_b = rng.sample(CITIES, 2)
                if scenario == "legitimate_travel":
                    city_a, city_b = rng.sample([city for city in CITIES if city[0] != "Delhi"], 2)
                source_count = rng.choice([1, 2, 3])
                label = int(scenario in {"clone_copy", "clone_burst", "slow_copy"})
                count_events = rng.randint(2, 5)
                if scenario in {"legitimate_distribution", "clone_burst"}:
                    count_events = rng.randint(12, 30)
                payloads, districts = [], {}
                for k in range(count_events):
                    city = city_a
                    pack = f"PACK-{eid}"
                    seconds = k*rng.randint(60, 240)
                    if scenario == "legitimate_distribution":
                        pack = f"PACK-{eid}-{k}"
                        city = rng.choice(CITIES)
                    elif scenario in {"clone_copy", "slow_copy", "legitimate_travel"}:
                        city = city_a if k == 0 else city_b
                        # Slow copies and legitimate travel overlap; labels describe the generator's scenario, not proof from geometry.
                        seconds = k * (rng.randint(30, 240) if scenario == "clone_copy" else rng.randint(3600, 7200))
                    elif scenario == "clone_burst":
                        seconds = k*rng.randint(1, 5)
                    when = start+timedelta(seconds=seconds)
                    event = dict(event_id=f"EVENT-{eid}-{k}", pack_id=pack, product=ref["product"],
                                 batch_no=ref["batch_no"], manufacturer_key=ref["manufacturer_name_normalized"],
                                 event_time=when.isoformat(), source_id=f"SOURCE-{eid}-{k % source_count}",
                                 latitude=city[2], longitude=city[3], simulated=True)
                    payloads.append(event)
                    districts[event["event_id"]] = {"district": city[0], "state": city[1], "location_status": "synthetic_city_centroid"}
                    if scenario in {"benign_repeat", "delayed_sync"} and k == 0:
                        payloads.append(dict(event))
                    if scenario == "legitimate_travel" and k == 1:
                        break
                if scenario == "delayed_sync":
                    payloads.reverse()  # Arrival order differs; feature construction uses observation time.
                end = max(ScanEvent.parse(event).timestamp for event in payloads)
                # Do not add detector outcomes or scenario identity to model inputs.
                values = extract_scan_features(payloads, end)
                features.append({"example_id": digest([seed, eid])[:24], "episode_id": eid,
                                 "split": split, "scenario": scenario, "label": label,
                                 "baseline_rule_prediction": scan_rule_baseline(values), **values})
                episodes.append({"episode_id": eid, "split": split, "scenario": scenario,
                                 "label": label, "events": payloads, "districts": districts,
                                 "observation_end": end, "simulated": True})
    return pd.DataFrame(features), episodes


def validate_examples(history, scans, episodes):
    for frame, names in [(history, HISTORY_FEATURES), (scans, SCAN_FEATURES)]:
        if frame["example_id"].duplicated().any():
            raise ValueError("Duplicate training example identities.")
        for split in ["train", "validation", "test"]:
            subset = frame[frame["split"].eq(split)]
            if subset.empty or set(subset["label"]) != {0, 1}:
                raise ValueError(f"Both labels are required in {split}.")
        numeric = frame[names].apply(pd.to_numeric, errors="coerce")
        if numeric.isna().any().any() or not numeric.apply(lambda s: s.map(lambda x: float('-inf') < x < float('inf'))).all().all():
            raise ValueError("Features contain missing or non-finite values.")
    if not history["feature_cutoff_month"].lt(history["target_month"]).all():
        raise ValueError("Historical feature leakage across target month.")
    ranges = {split: history.loc[history["split"].eq(split), "target_month"] for split in ["train", "validation", "test"]}
    if not (ranges["train"].max() < ranges["validation"].min() and ranges["validation"].max() < ranges["test"].min()):
        raise ValueError("Historical time splits overlap.")
    identities = {split: set() for split in ["train", "validation", "test"]}
    for episode in episodes:
        identities[episode["split"]].update(event["pack_id"] for event in episode["events"])
        if episode["scenario"] in HELDOUT_SCENARIOS and episode["split"] != "test":
            raise ValueError("Held-out scan scenario leaked into training or validation.")
    if identities["train"] & identities["validation"] or identities["train"] & identities["test"] or identities["validation"] & identities["test"]:
        raise ValueError("Pack identities overlap scan splits.")


def prepare(output, episodes_per_scenario=30, seed=2026):
    location, snapshot = active_snapshot()
    df = load_dataset((location, snapshot))
    provenance_path = location / "data" / "processed" / "all_months_provenance.csv"
    if not provenance_path.exists():
        raise ValueError("Run refresh_data.py first to build workbook-row provenance.")
    provenance = pd.read_csv(provenance_path, dtype=str, keep_default_na=False)
    if provenance["build_record_id"].duplicated().any() or not set(df["build_record_id"]).issubset(set(provenance["build_record_id"])):
        raise ValueError("Training inputs do not have unique source-row provenance.")
    history = history_examples(df)
    scans, episodes = make_scan_corpus(df, episodes_per_scenario, seed)
    validate_examples(history, scans, episodes)
    output = Path(output)
    if output.exists():
        raise FileExistsError("Use a fresh foundation output directory to preserve held-out artifacts.")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".foundation-", dir=output.parent))
    try:
        tasks = {}
        for name, frame, columns in [(HISTORY_TASK, history, HISTORY_FEATURES), (SCAN_TASK, scans, SCAN_FEATURES)]:
            directory = stage / name
            directory.mkdir()
            splits = {}
            for split in ["train", "validation", "test"]:
                part = frame[frame["split"].eq(split)].reset_index(drop=True)
                # Features, labels and identifying metadata are separate files.
                part[columns].to_csv(directory / f"{split}_X.csv", index=False)
                part[["label"]].to_csv(directory / f"{split}_y.csv", index=False)
                part.drop(columns=columns+["label"]).to_csv(directory / f"{split}_metadata.csv", index=False)
                splits[split] = {"rows": len(part), "labels": {str(k): int(v) for k, v in part.label.value_counts().items()}}
            tasks[name] = {"feature_columns": columns, "splits": splits}
        with (stage / "scan_episodes.jsonl").open("w") as stream:
            for episode in episodes:
                stream.write(json.dumps(episode, sort_keys=True) + "\n")
        manifest = {"foundation_version": FOUNDATION_VERSION, "snapshot_id": snapshot,
                    "readiness": "ready_for_baseline_training_with_stated_limits",
                    "source_row_provenance_sha256": file_hash(provenance_path),
                    "seed": seed, "tasks": tasks, "recurrence_finding": recurrence_finding(df),
                    "heldout_scan_families": HELDOUT_SCENARIOS,
                    "scan_observation_seconds": OBSERVATION_SECONDS,
                    "features_sha256": file_hash(ROOT / "scan_features.py"),
                    "builder_sha256": file_hash(ROOT / "model_foundation.py"),
                    "dependency_code": {name: file_hash(ROOT / name) for name in
                                        ["batchguard_engine.py", "inspection_stream.py", "decision_core.py", "scan_features.py"]},
                    "environment": {"python": platform.python_version(), "pandas": pd.__version__, "machine": platform.machine()},
                    "training_performed": False,
                    "limitations": ["Layer A predicts next-month reported recurrence among previously observed manufacturer text signatures.",
                                    "A zero recurrence label means no next-month report, not a safe medicine.",
                                    "Collection months are proxies, not verified publication dates.",
                                    "Layer B labels and all pack/source/location behavior are synthetic.",
                                    "Some legitimate travel and slow-copy observations are indistinguishable; perfect detection is not expected.",
                                    "Scenario prevalence is a design choice, not real market prevalence.",
                                    "Manufacturer identities and source independence are not verified."]}
        manifest["files"] = {p.relative_to(stage).as_posix(): file_hash(p) for p in sorted(stage.rglob("*")) if p.is_file()}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n")
        stage.rename(output)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def load_model_inputs(directory, task, split="train", final_evaluation=False):
    """Load only whitelisted features; require an explicit final-test decision."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if task not in manifest["tasks"] or split not in {"train", "validation", "test"}:
        raise ValueError("Unknown training task or split.")
    if split == "test" and not final_evaluation:
        raise ValueError("Reserve test data until model/threshold selection is complete.")
    for name, expected in manifest["files"].items():
        path = directory / name
        if not path.is_file() or file_hash(path) != expected:
            raise ValueError(f"Prepared training artifact changed: {name}")
    location = directory / task
    features = pd.read_csv(location / f"{split}_X.csv")
    labels = pd.read_csv(location / f"{split}_y.csv")
    metadata = pd.read_csv(location / f"{split}_metadata.csv")
    if list(features.columns) != manifest["tasks"][task]["feature_columns"]:
        raise ValueError("Feature contract mismatch.")
    if not len(features) == len(labels) == len(metadata):
        raise ValueError("Prepared rows are misaligned.")
    return features, labels["label"], metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--episodes-per-scenario", type=int, default=30)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    manifest = prepare(args.output, args.episodes_per_scenario, args.seed)
    print(json.dumps({"output": str(args.output), "snapshot_id": manifest["snapshot_id"],
                      "tasks": manifest["tasks"], "recurrence_finding": manifest["recurrence_finding"],
                      "training_performed": False}, indent=2))


if __name__ == "__main__":
    main()
