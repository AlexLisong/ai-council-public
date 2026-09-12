# Azure App Service example

Use a Linux App Service with a supported Python runtime, one instance, and startup
command `bash deploy/azure-startup.sh`. Create resources in your own Azure account.
The application serves the React build and API on one HTTPS origin.

## Settings

Use App Service configuration for credentials and storage settings. Never put them
in the deployment archive or frontend environment variables.

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<your-unique-password>
ALLOW_SIGNUP=false
OPENAI_API_KEY=<your-api-key>
DB_PATH=/home/data/council.db
DATA_DIR=/home/data/legacy
SQLITE_JOURNAL_MODE=DELETE
PORT=8000
SCM_DO_BUILD_DURING_DEPLOYMENT=true
ENABLE_ORYX_BUILD=true
WEBSITES_CONTAINER_START_TIME_LIMIT=600
```

Use `DELETE` journal mode on App Service's persistent network share; WAL shared memory
is not supported there. Provider settings can instead use Azure OpenAI or OpenRouter.
Set your own server-only deployment mapping if needed; see [.env.example](../.env.example).

Enable HTTPS only, a minimum TLS version of 1.2, Always On where supported, and the
`/api/health` health check. Disable FTP and publishing basic authentication. Retain
one instance and one Uvicorn worker because SQLite and coordination are not distributed.

## Package and deploy

After verification, from the repository root:

```bash
python3 deploy/package.py
az webapp deploy --resource-group YOUR_RESOURCE_GROUP --name YOUR_APP_NAME \
  --src-path .azure/release.zip --type zip --track-status false
```

The resource and application names are placeholders. `package.py` builds the frontend
and exports pinned dependencies from `uv.lock`; Azure's build process installs Linux
Python dependencies. Its allowlist excludes `.env` and live data.

For an initial migration only, `--seed-db /private/path/seed.db` includes a database
snapshot. Such an archive contains private user data and must never be shared as a
public release. Take a consistent SQLite backup, remove sessions, and handle account
credentials privately. Startup restores the seed only when persistent storage has no
database. Normal updates must omit `--seed-db`.

Restarts and code updates preserve `/home/data/council.db`; deleting the app can remove
its storage. Keep a tested, consistent backup elsewhere before destructive operations.
Verify browser behavior and persistence as described in [README.md](README.md).
