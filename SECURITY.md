# Security policy

## Reporting a vulnerability

Do not disclose an exploitable vulnerability, credentials, or another person's data
in a public issue or pull request. If this repository's **Security → Advisories →
Report a vulnerability** button is available, use GitHub's private reporting flow.
Its availability depends on repository settings; this document does not imply that
it is enabled.

If that button is unavailable, open an issue titled **Private security contact
requested** containing only a request for a private channel. Include no technical
details, affected identities, logs, or proof of concept. A maintainer can arrange a
private channel before you share the report. Do not send sensitive material until
that channel is established.

Privately include the affected revision, impact, minimal reproduction with synthetic
data, and any proposed mitigation. Remove keys, tokens, personal details, and private
hostnames. Coordinate disclosure after a fix is available. There is no guaranteed
response time or bug bounty.

## Supported versions

Security fixes target the current development branch. No older release has a
promised support window. Check recent changes before reporting an already fixed bug.

## Deployment and data boundaries

- Provider credentials and deployment mappings belong in server-side configuration.
  Presets and model IDs are visible to signed-in users; they must not contain secrets.
- Prompts and prior conversation context are sent to the selected provider. Uploaded
  portraits are display-only and are not included in model prompts.
- SQLite stores conversations and account data. Passwords use scrypt; session tokens
  are stored hashed on the server and held in browser localStorage. Protect against
  script injection and serve the application over HTTPS outside localhost.
- The administrator can read all users' conversations. Only owners can run or delete
  a conversation or edit their personal panels. Storage is not end-to-end encrypted.
- Configure an explicit, unique `ADMIN_PASSWORD` for first startup. Registration
  defaults to enabled in code; `.env.example` sets `ALLOW_SIGNUP=false`. Choose the
  appropriate policy deliberately before exposing an instance.
- Run one process and one instance. Active-run coordination and authentication
  throttles are not distributed. Use private filesystem permissions and consistent
  database backups; do not publish exports, support bundles, or deployment archives.
- Model outputs are untrusted and can be wrong. Convergence is not factual verification.

See [self-hosting](deploy/README.md) for storage and reverse-proxy requirements.
