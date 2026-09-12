# Self-hosting AI Council

These are reusable deployment examples. Choose your own host, domain, resource names,
and credentials. No running installation or shared account is provided.

## Runtime requirements

- Python 3.10 or newer, a built React frontend, and persistent SQLite storage.
- Exactly **one Uvicorn worker and one application instance**. Active conversations,
  input windows, and auth throttles are process-local. Horizontal scaling requires
  shared coordination and a server database first.
- HTTPS outside localhost. Serve the API and frontend on one origin, and disable
  proxy buffering for server-sent events. Use `/api/health` for health checks.
- A private environment file or secret manager containing provider credentials,
  an explicit `ADMIN_PASSWORD`, and `ALLOW_SIGNUP=false` unless registration is desired.
- Private filesystem permissions and backups outside the deployed code directory.

All prompts and relevant conversation history go to the configured model provider.
Operators can read stored data, and administrators can read every account's history.
Review [SECURITY.md](../SECURITY.md) before inviting users.

## Deployment options

- [Linux with systemd and nginx](AWS.md): works on a Linux VM, including an AWS VM.
- [Azure App Service](AZURE.md): optional App Service startup and packaging examples.

The directory names preserve the existing packaging interfaces; they do not indicate
where this project is hosted. Neither approach includes infrastructure provisioning.

## Verify before release

```bash
uv run python -m unittest discover -s tests
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

Use synthetic data to verify login, account isolation, a streamed Chat and follow-up,
a Council response, direct route reloads, and history after a service restart.
Provider-backed checks incur usage charges and should use your own account.

## Preserve state during updates

Keep the database and private configuration outside versioned releases. Use SQLite's
backup API for a consistent snapshot; copying a live database file alone can lose
WAL changes. Keep backups private and test restore procedures before destructive
maintenance. Code rollback does not automatically reverse database migrations.

Public presets use canonical model IDs. If an existing installation used private
Azure deployment names as model IDs, configure `FOUNDRY_DEPLOYMENT_MAP` and update
private panel/config selections before upgrading. Select a configured replacement
model for stale snapshots. Historical response text is preserved. Do not publish
private aliases, saved discussions, or migration copies.
