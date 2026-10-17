"""Read published snapshots while preserving the original CSV layout as fallback."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parent
DATASETS = ("all_months_analytical.csv", "all_months_manufacturer_normalized.csv",
            "all_months_failure_normalized.csv")


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def active_snapshot(root=ROOT):
    root = Path(root)
    pointer = root / "data" / "CURRENT"
    if not pointer.exists():
        return root, "legacy-local-files"
    identity = pointer.read_text().strip()
    if not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValueError("Invalid data/CURRENT snapshot pointer.")
    location = root / "data" / "snapshots" / identity
    manifest = json.loads((location / "manifest.json").read_text())
    if manifest["snapshot_id"] != identity:
        raise ValueError("Snapshot manifest identity differs from data/CURRENT.")
    return location, identity


def validate_snapshot(location):
    location = Path(location)
    manifest = json.loads((location / "manifest.json").read_text())
    required = {f"data/processed/{name}" for name in DATASETS}
    if not required.issubset(manifest["outputs"]):
        raise ValueError("Snapshot manifest lacks required dataset hashes.")
    identity = hashlib.sha256(json.dumps({name: manifest[name] for name in ["sources", "outputs", "builder"]},
                                        sort_keys=True).encode()).hexdigest()
    if identity != manifest["snapshot_id"]:
        raise ValueError("Snapshot manifest content does not match its identity.")
    for name, expected in manifest["outputs"].items():
        path = location / name
        if not path.resolve().is_relative_to(location.resolve()):
            raise ValueError("Snapshot file path escapes snapshot directory.")
        if not path.is_file() or file_hash(path) != expected:
            raise ValueError(f"Snapshot file missing or changed: {name}")
    return manifest


def publish_pointer(root, identity):
    """The only reader-visible mutation; existing snapshots remain available."""
    root = Path(root)
    if not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValueError("Invalid snapshot identity.")
    location = root / "data" / "snapshots" / identity
    manifest = validate_snapshot(location)
    if manifest["snapshot_id"] != identity:
        raise ValueError("Snapshot identity mismatch.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=root / "data", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(identity + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / "data" / "CURRENT")
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def refresh_lock(root):
    path = Path(root) / "data" / ".refresh.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Refresh already locked. Check for a running refresh before removing a stale lock.") from exc
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)
