"""Build an allowlisted Azure ZIP; secrets and live data are excluded by default."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-db', type=Path, help='Initial database snapshot; omit after first deployment')
    args = parser.parse_args()
    subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'frontend', check=True)
    requirements = subprocess.check_output(
        ['uv', 'export', '--frozen', '--format', 'requirements-txt', '--no-dev', '--no-hashes', '--no-emit-project'],
        cwd=ROOT,
    )
    output_dir = ROOT / '.azure'
    output_dir.mkdir(mode=0o700, exist_ok=True)
    archive = output_dir / 'release.zip'
    # Create the file privately before writing, including when it contains a seed.
    descriptor = os.open(archive, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.close(descriptor)
    os.chmod(archive, 0o600)
    files = [ROOT / 'council.config.json', ROOT / 'deploy/azure-startup.sh']
    files.extend((ROOT / 'backend').rglob('*.py'))
    files.extend(path for path in (ROOT / 'frontend/dist').rglob('*') if path.is_file())
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            bundle.write(path, path.relative_to(ROOT))
        bundle.writestr('requirements.txt', requirements)
        if args.seed_db:
            bundle.write(args.seed_db.resolve(strict=True), 'deploy/seed.db')
    print(f'Azure package: {archive} ({archive.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
