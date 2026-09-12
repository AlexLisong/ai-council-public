# Using AI Council

## How a debate runs

1. **Round 0, opening positions.** Every seat answers the question from its persona,
   without seeing anyone else. Ends with a one-line `POSITION SUMMARY`.
2. **Rounds 1..N, debate.** Every seat receives the other seats' latest positions as
   `Position A`, `Position B`, ... (anonymized so no seat can play favorites), critiques
   them, updates its own position, adds something new, and ends with
   `VERDICT: CONVERGED` or `VERDICT: OPEN` plus a `DISAGREEMENTS` line.
3. **Stop rule.** The debate stops when the number of `CONVERGED` verdicts reaches the
   quorum (`all`, `majority`, `2/3`, or a fraction) or when `max_rounds` is reached.
   Consensus is never forced.
4. **Final answer.** The Chairman writes Conclusion, Reasoning, Where the panel
   disagreed (only if something stayed open), and Confidence.

With **Let me join between rounds** checked (the default), the panel pauses before
each remaining debate round. **Your turn** shows a five-minute countdown. Send your
thoughts to continue immediately, choose **Continue without a comment**, or let the
timer expire. There is no pause once the panel has reached its stopping condition.

After the final answer, enter a thought, objection, or new constraint and choose
**Continue discussion**. The next turn keeps the original question, all human
contributions, the previous final answers, and each seat's latest prior position in
context. This also works with older saved debates. The panel evaluates your argument
and can disagree with reasons. New turns inherit the previous panel settings.

Saved discussions open with **Council synthesis**. Expand **Explore the discussion**
to inspect every round, compare the members' position summaries and full responses,
and revisit your contributions. Use the arrow keys to switch between speaker tabs.
Copy the answer or discussion link from its header. Seat names are shown in bold
where a seat wrote `Position X`, for readability only.

Cost: seats x (1 + rounds run) model calls, plus one Chairman call and one title call.
Rounds run in parallel across seats, so wall-clock time is roughly (rounds + 2) x the
slowest model's latency.

## Accounts

The app is multi-user. Everyone creates their own account and sees only their own
debates. One **master account** (role `admin`) sees every user's debates, read-only,
via the "All users" toggle in the sidebar.

- The administrator is created on first start from `ADMIN_USERNAME` (default `admin`)
  and the required `ADMIN_PASSWORD`. Passwords are never printed during bootstrap.
- Sign-up is open by default. Set `ALLOW_SIGNUP=false` to close it after your users exist.
- Passwords are hashed with scrypt; sessions are random bearer tokens stored hashed in
  SQLite and expire after `SESSION_DAYS` (default 30).
- Data lives in `data/council.db` (SQLite). Conversations from the pre-accounts JSON
  format in `data/conversations/` are imported once, owned by the master account.

The API is loopback-only by default (`HOST=127.0.0.1`). To let other people reach it,
set `HOST=0.0.0.0` and put it behind TLS (a reverse proxy); the tokens are bearer
tokens, so plain HTTP over a network exposes them.


## Configure the panel

Open **Panels** in the sidebar, or choose a preset in a debate and follow
**Customize panel**. Select one member at a time to edit its name, model, persona,
and portrait. Choose one of eight illustrated portraits or **Upload photo** (JPG,
PNG or WebP, up to 5 MB). Photos are center-cropped and resized to a 256px square.
Portraits stay with the saved panel and each historical turn; renaming an AI does
not change its portrait. Images are for display and are never sent to the models.
Use **Add seat** or **Remove seat** to keep 1–8 discussion members. Every panel
includes a Chairman; its name, model, and optional guidance are editable, and it
cannot be removed. The default template retains the original four members plus
Chairman. **Save panel** stores your version in your account for future debates.
Models are selected from the server's available configured choices.

The **Discussions** home provides searchable history and editable starting prompts
for engineering, business, and personal decisions. **New discussion** puts your
question and selected panel together. Open **Discussion settings** for the round
limit and stop rule; the original five-role council remains the default.

Use **Edit panel** to update a personal panel. After a final answer, expand **Panel
settings for the next turn** to choose or edit a panel. Earlier turns retain their
recorded settings. If a saved panel has changed, **Use saved updates** applies the
new version to the next turn. Changes to a saved panel do not change an active round.

Each view has a direct URL: `/debates`, `/debates/<id>`, `/panels`, and
`/panels/<id>?seat=0` (or `seat=chairman`). You can bookmark or reload these pages;
sign-in returns to the requested view. Unsaved panel edits, discussion text, and
discussion settings survive navigation within the app until logout or page reload.
Saving a panel opened from a debate returns to that debate with the panel selected.


## API

All API routes except `/api/health`, `/api/auth/settings`, `/api/auth/register` and `/api/auth/login`
need `Authorization: Bearer <token>`.

- `POST /api/auth/register`, `POST /api/auth/login` body `{"username", "password"}`, return `{token, user}`
- `GET  /api/auth/me`, `POST /api/auth/logout`
- `GET  /api/config` presets, available providers, defaults
- `GET /api/panels/{id}` returns an owned personal panel for direct editor links
- `POST /api/panels`, `PUT /api/panels/{id}` save or update an owned personal panel:
  `{title, seats: [{name, provider, model, persona, avatar}], chairman: {name, provider, model, persona, avatar}}`.
  The response is a selectable preset with a `personal:<uuid>` key. Config includes
  only the signed-in user's personal panels and the available `model_options`.
  Optional `avatar` is null, a built-in portrait ID, or a PNG/JPEG/WebP base64 data
  URL of at most 100 KiB decoded. External URLs and uploaded SVGs are rejected.
- `GET  /api/conversations` (own), `GET /api/conversations?scope=all` (master only, includes `owner_username`)
- `POST /api/conversations`, `GET /api/conversations/{id}` (owner or master), `DELETE /api/conversations/{id}` (owner only)
- `GET  /api/admin/users` (master only)
- `POST /api/conversations/{id}/message/stream` (owner only) body
  `{"content": "...", "preset": "openai-direct", "max_rounds": 3, "consensus": "all", "pause_for_input": true}`.
  Omitted settings inherit the last turn's config. Follow-up turns append to the
  same conversation. `use_latest_panel: true` selects the current saved definition;
  otherwise an unchanged panel key inherits the last turn's snapshot.
  Context is limited to 20 human turns and 120,000 characters;
  requests exceeding the limit are rejected before any model calls.
  Server-sent events: `config`, `round_start`, `round_complete`, `awaiting_input`,
  `input_received`, `round_resumed`, `final_start`, `final_complete`, `title_complete`,
  `complete`, `error`.
- `POST /api/conversations/{id}/input` (owner only, while waiting):
  `{"content": "My thought"}` or `{"skip": true}`. Concurrent runs and deletion of
  an active conversation return 409. Conversation GET includes `is_running`.

Users, sessions and conversations are stored in `data/council.db`.
