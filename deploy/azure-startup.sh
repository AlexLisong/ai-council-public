#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# App Service keeps /home across deployments and restarts. Seed once, never replace
# an existing database with the snapshot included in the first deployment.
python - <<'PY'
import os
import sqlite3
from pathlib import Path

target = Path(os.environ['DB_PATH'])
target.parent.mkdir(parents=True, exist_ok=True)
seed = Path('deploy/seed.db')
if not target.exists() and seed.is_file():
    temporary = target.with_suffix('.initializing')
    with sqlite3.connect(f'file:{seed.resolve()}?mode=ro', uri=True) as source:
        with sqlite3.connect(temporary) as destination:
            source.backup(destination)
            destination.execute('PRAGMA journal_mode = DELETE')
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    print('Restored initial AI Council database to persistent storage.', flush=True)
PY

# SQLite and the in-memory auth limiter require one process and one app instance.
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --no-proxy-headers
