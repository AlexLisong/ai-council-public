"""Build a private, allowlisted Linux release without credentials or user data."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True)
    requirements = subprocess.check_output(
        ["uv", "export", "--frozen", "--format", "requirements-txt", "--no-dev", "--no-hashes", "--no-emit-project"],
        cwd=ROOT,
    )
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release = f"{stamp}-{commit}"
    output_dir = ROOT / ".aws"
    output_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(output_dir, 0o700)
    files = [ROOT / "council.config.json"]
    files.extend((ROOT / "backend").rglob("*.py"))
    files.extend(path for path in (ROOT / "frontend/dist").rglob("*") if path.is_file())
    files.extend(path for path in (ROOT / "deploy/aws").rglob("*") if path.is_file())
    for path in files:
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"Release input is outside the project: {path}")
        cursor = ROOT
        for part in path.relative_to(ROOT).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError(f"Symlinks are not allowed in release inputs: {cursor}")
    contents = {str(path.relative_to(ROOT)): path.read_bytes() for path in sorted(files)}
    contents["requirements.txt"] = requirements
    manifest = {
        "release": release,
        "source_commit": commit,
        "working_tree_changes": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
    }
    contents["release.json"] = json.dumps(manifest, indent=2).encode() + b"\n"
    archive = output_dir / f"{release}.tar.gz"
    descriptor = os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        with tarfile.open(fileobj=destination, mode="w:gz") as bundle:
            for name, data in contents.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                entry.mode = 0o644
                bundle.addfile(entry, io.BytesIO(data))
    (output_dir / "latest-release.txt").write_text(str(archive) + "\n")
    print(f"AWS package: {archive} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
