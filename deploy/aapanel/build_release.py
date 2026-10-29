"""Build a deterministic, allowlisted release; no environment or local runtime files."""

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

SINGLE = ("backend/pyproject.toml", "backend/uv.lock", "backend/alembic.ini", "deploy/aapanel/runtime.py")
TREES = ("backend/app", "frontend/dist")


def build(root: Path, commit: str, target: Path) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("A full commit SHA is required")
    files = {name: root / name for name in SINGLE}
    for tree in TREES:
        for file in (root / tree).rglob("*"):
            if file.is_symlink():
                raise ValueError("Release source cannot contain symlinks")
            if file.is_file() and "__pycache__" not in file.parts and file.suffix not in {".pyc", ".pyo"}:
                files[file.relative_to(root).as_posix()] = file
    if "frontend/dist/index.html" not in files or "backend/app/main.py" not in files:
        raise ValueError("Backend source and built frontend are required")
    payloads = {}
    for name, file in files.items():
        if (file.is_symlink() or not file.is_file() or any(part.startswith(".") for part in Path(name).parts)
                or file.suffix.lower() in {".env", ".key", ".pem", ".log", ".db", ".sqlite", ".sqlite3"}):
            raise ValueError("Unexpected release input")
        payloads[name] = file.read_bytes()
    manifest = {"format": 1, "commit": commit,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payloads.items())}}
    payloads["release.json"] = (json.dumps(manifest, sort_keys=True)+"\n").encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as output, gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, data in sorted(payloads.items()):
                item = tarfile.TarInfo(name)
                item.size, item.mode, item.mtime = len(data), 0o644, 0
                archive.addfile(item, io.BytesIO(data))
    return hashlib.sha256(target.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.root.resolve(), args.commit, args.output))
