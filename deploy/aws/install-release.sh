#!/usr/bin/env bash
# Run as root on the host: bash install-release.sh /path/to/release.tar.gz
set -euo pipefail
archive="$(realpath "${1:?Provide the release archive}")"
release="$(basename "$archive" .tar.gz)"
[[ "$release" =~ ^[0-9]{8}T[0-9]{6}Z-[a-f0-9]+$ ]] || { echo 'Invalid release filename' >&2; exit 1; }
target="/opt/ai-council/releases/$release"
[[ ! -e "$target" ]] || { echo 'Release already installed' >&2; exit 1; }
test -s /etc/ai-council/app.env
python3 - <<'PY'
from pathlib import Path
import stat
path = Path('/etc/ai-council/app.env')
metadata = path.stat()
if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o077:
    raise SystemExit('app.env must be a regular root-owned private file (mode 600 or 400).')
PY
id ai-council >/dev/null 2>&1 || useradd --system --home-dir /var/lib/ai-council --shell /usr/sbin/nologin ai-council
install -d -m 0755 /opt/ai-council/releases "$target"
install -d -o ai-council -g ai-council -m 0700 /var/lib/ai-council
tar --extract --gzip --file "$archive" --directory "$target" --no-same-owner
python3 -m venv "$target/.venv"
"$target/.venv/bin/pip" install --disable-pip-version-check -r "$target/requirements.txt"
"$target/.venv/bin/python" - <<'PY'
from dotenv import dotenv_values
settings = dotenv_values('/etc/ai-council/app.env')
for key, expected in {
    'DB_PATH': '/var/lib/ai-council/council.db',
    'DATA_DIR': '/var/lib/ai-council/legacy',
}.items():
    if settings.get(key) != expected:
        raise SystemExit(f'Invalid or missing durable storage setting: {key}')
if not settings.get('ADMIN_PASSWORD'):
    raise SystemExit('ADMIN_PASSWORD is required before initial startup.')
PY
chown -R root:root "$target"
chmod -R go-w "$target"
previous="$(readlink -f /opt/ai-council/current || true)"
if [[ -f /var/lib/ai-council/council.db ]]; then
    install -d -m 0700 /var/backups/ai-council
    python3 - "$release" <<'PY'
import sqlite3
import sys
from pathlib import Path
backup = Path('/var/backups/ai-council') / f'before-{sys.argv[1]}.db'
with sqlite3.connect('file:/var/lib/ai-council/council.db?mode=ro', uri=True) as source:
    with sqlite3.connect(backup) as destination:
        source.backup(destination)
backup.chmod(0o600)
PY
fi
unit_backup="$(mktemp)"
had_unit=false
if [[ -f /etc/systemd/system/ai-council.service ]]; then
    cp /etc/systemd/system/ai-council.service "$unit_backup"
    had_unit=true
fi
finish() {
    status=$?
    trap - EXIT
    set +e
    if [[ "$status" -ne 0 ]]; then
        echo 'Activation failed; restoring the previous code and service unit.' >&2
        systemctl stop ai-council.service || true
        if [[ "$had_unit" == true ]]; then
            install -m 0644 "$unit_backup" /etc/systemd/system/ai-council.service
        else
            systemctl disable ai-council.service || true
            rm -f /etc/systemd/system/ai-council.service
        fi
        systemctl daemon-reload
        rm -f /opt/ai-council/current.next /opt/ai-council/current.rollback
        if [[ -n "$previous" && -d "$previous" ]]; then
            ln -s "$previous" /opt/ai-council/current.rollback
            mv -Tf /opt/ai-council/current.rollback /opt/ai-council/current
            systemctl restart ai-council.service
            if curl --fail --silent --retry 5 --retry-connrefused --retry-delay 1 --connect-timeout 2 --max-time 5 http://127.0.0.1:8011/api/health; then
                echo 'Previous release restored.' >&2
            else
                echo 'Previous release also failed its health check; inspect the service log.' >&2
            fi
        else
            rm -f /opt/ai-council/current
        fi
    fi
    rm -f "$unit_backup"
    exit "$status"
}
trap finish EXIT
install -m 0644 "$target/deploy/aws/ai-council.service" /etc/systemd/system/ai-council.service
ln -s "$target" /opt/ai-council/current.next
mv -Tf /opt/ai-council/current.next /opt/ai-council/current
systemctl daemon-reload
systemctl enable ai-council.service
systemctl restart ai-council.service
for attempt in $(seq 1 30); do
    if curl --fail --silent --connect-timeout 2 --max-time 3 http://127.0.0.1:8011/api/health; then
        printf '\nHealthy release: %s\n' "$release"
        exit 0
    fi
    sleep 1
done
echo 'New release failed its health check.' >&2
exit 1
