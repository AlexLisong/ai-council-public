# Linux deployment example

Run AI Council on a Linux VM with systemd and nginx. The templates also work on AWS;
no specific account, machine, region, or domain is assumed. Configure DNS, network
access, and TLS for your own environment.

## Prepare the host

Install Python with `venv`, nginx, Certbot, and the tools used by
[`aws/install-release.sh`](aws/install-release.sh). Review that script before running
it as root: it creates a service account, installs a release, backs up SQLite, changes
the active symlink, and restarts the service.

Create `/etc/ai-council/app.env` as a regular root-owned file with mode 0600. Include:

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<your-unique-password>
ALLOW_SIGNUP=false
OPENAI_API_KEY=<your-api-key>
DB_PATH=/var/lib/ai-council/council.db
DATA_DIR=/var/lib/ai-council/legacy
SQLITE_JOURNAL_MODE=WAL
```

These are placeholders, not working credentials. Configure Azure or OpenRouter
instead if needed, following [.env.example](../.env.example). Private model
mappings remain in this environment file. Do not use shell commands that leave
secrets in shell history.

The supplied service runs as `ai-council`, with one worker at `127.0.0.1:8011`.
Code lives in `/opt/ai-council/releases/<release>`, with a `current` symlink. SQLite
lives in `/var/lib/ai-council`; use local storage supporting WAL.

## Package and activate

After the checks in [the deployment guide](README.md):

```bash
python3 deploy/aws-package.py
```

The packager writes a private archive under `.aws/` and its path to
`.aws/latest-release.txt`. An allowlist includes backend code, built assets, public
presets, pinned dependencies, and deployment templates. Credentials and databases
are excluded. Symlinked inputs are rejected. `release.json` records the revision,
working-tree status, and hashes of packaged files.

Privately upload the archive and `deploy/aws/install-release.sh` to your VM. Run the
installer as root with the archive path. It creates a release-specific environment,
backs up existing SQLite state under `/var/backups/ai-council`, activates the code,
and checks `/api/health`. Activation failure attempts to restore the previous code
and service unit. Keep an off-host backup: the local backup is lost with the disk.

## Configure HTTPS

Replace **every** `council.example.com` occurrence in
[`aws/ai-council.nginx.conf`](aws/ai-council.nginx.conf) and
[`aws/renew-cert.sh`](aws/renew-cert.sh) in a private copy with your domain.
Obtain its certificate using Certbot's webroot plugin and
`/var/www/ai-council-acme`. The nginx template assumes Certbot's certificate and
TLS configuration paths already exist. Install it as its own virtual host; check
`nginx -t` before reloading. Do not replace another application's configuration.

The template redirects HTTP to HTTPS, disables response buffering, and extends
stream timeouts. Install the adapted renewal hook under
`/etc/letsencrypt/renewal-hooks/deploy/` with mode 0755, and enable certificate renewal.

Useful checks on your host:

```bash
sudo systemctl status ai-council --no-pager
sudo journalctl -u ai-council -n 100 --no-pager
curl --fail http://127.0.0.1:8011/api/health
sudo nginx -t
```

Treat service logs as private. Verify the browser flows in [README.md](README.md)
after activation; a successful health check alone does not exercise model streaming.
