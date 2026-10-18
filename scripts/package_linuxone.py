"""Build and verify a public-data-only LinuxONE deployment bundle (no local state)."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = ("README.md", "requirements.txt", "src/*.py", "app/*.py", "app/*.html",
            "app/maps/*.json", "app/maps/*.txt", "app/fonts/*.woff2", "app/fonts/*.txt",
            "scripts/preflight_linuxone.py", "scripts/launch_linuxone.sh", "data/raw/*.xlsx",
            "data/demo/*.csv", "data/processed/*.csv", "data/processed/*.json", "data/processed/review/*.csv", "data/official/manifest.json",
            "data/official/responses/*.json", "outputs/*.json", "outputs/*.html", "outputs/*.csv",
            "outputs/models/*/*.json", "outputs/models/*/*.pkl", "outputs/models/*/*.csv", "outputs/charts/*.png")


def members(root):
    files = {}
    for pattern in PATTERNS:
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink() and not any(p.is_symlink() for p in path.parents):
                relative = path.relative_to(root).as_posix()
                files[relative] = path.read_bytes()
    return dict(sorted(files.items()))


def verify(path):
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if any(item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000 for item in entries):
                raise ValueError("Unsafe archive member")
            names = [item.filename for item in entries]
            values = [archive.read(item) for item in entries]
    else:
        with tarfile.open(path, "r:gz") as archive:
            entries = archive.getmembers()
            if any(not item.isfile() for item in entries):
                raise ValueError("Unsafe archive member")
            names = [item.name for item in entries]
            values = [archive.extractfile(item).read() for item in entries]
    if any(not name.startswith("BatchGuard/") or ".." in Path(name).parts or "\\" in name for name in names):
        raise ValueError("Unsafe archive member")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate archive member")
    contents = {name.removeprefix("BatchGuard/"): value for name, value in zip(names, values)}
    manifest = json.loads(contents.pop("BUNDLE_MANIFEST.json"))
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}
    if hashes != manifest["sha256"]:
        raise ValueError("Bundle content differs from manifest")
    return {"files_verified": len(hashes), "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    output = Path(output or root.parent / "IBM_UPLOAD" / "BatchGuard.zip")
    files = members(root)
    manifest = {"format": 1, "purpose": "Public source, reference data and model artifacts; excludes private state",
                "sha256": {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
    files["BUNDLE_MANIFEST.json"] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".zip":
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                item = zipfile.ZipInfo("BatchGuard/" + name, date_time=(1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
                archive.writestr(item, content, compress_type=zipfile.ZIP_DEFLATED)
    else:
        with output.open("wb") as target, gzip.GzipFile(fileobj=target, mode="wb", mtime=0, filename="") as compressed, tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, content in sorted(files.items()):
                item = tarfile.TarInfo("BatchGuard/" + name)
                item.size = len(content)
                item.mode = 0o755 if name.endswith(".sh") else 0o644
                archive.addfile(item, io.BytesIO(content))
    result = verify(output)
    output.with_suffix(output.suffix + ".sha256").write_text(result["archive_sha256"] + "  " + output.name + "\n")
    return {"path": str(output), **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.verify) if args.verify else build(output=args.output), indent=2))


if __name__ == "__main__":
    main()
