# Architecture and design decisions

AI Council pairs a FastAPI API with a React/Vite workspace and SQLite persistence.
Its council protocol uses repeated rounds of peer critique, optional human input,
and a final synthesis. [Karpathy's LLM Council](https://github.com/karpathy/llm-council)
inspired the multi-model approach; see [NOTICE.md](../NOTICE.md) for provenance.

Conversation `mode` is immutable: `chat` for normal streamed multi-turn answers,
`council` for debates. Existing SQLite records migrate to `council` without changing
their messages. Both modes retain the `/debates/:id` route and account isolation.

## Backend (`backend/`)

- `config.py`: builds `PROVIDERS` from env vars (a provider exists only if its key is
  set); loads `council.config.json` on every call so edits apply live; `public_config()`
  is what `GET /api/config` returns.
- `providers.py`: `chat(provider, model, system, user)` against OpenAI-compatible
  `/chat/completions` only (OpenAI, Azure Foundry, approved OpenRouter models). This project is
  OpenAI-models-only; there is no Anthropic route. Returns `None` on any failure and logs it;
  the debate continues with the seats that answered. `chat_many` fans out with
  `asyncio.gather`.
- `model_policy.py`: positive model IDs and trusted HTTPS endpoint policy. All
  offered choices and outgoing requests must pass it; protocol compatibility or
  an arbitrary model name does not establish OpenAI provenance.
- `chat.py`: normal role-based multi-turn history and configured Chat model
  selection. `providers.stream_chat` yields actual provider SSE text fragments.
  Chat uses `config`, `chat_delta`, `final_complete`, and `complete` events; partial
  text is persisted on cancellation, and no Council rounds run in this mode.
- `debate.py`: the protocol. `run_debate()` is an async generator yielding SSE-shaped
  events. Prompts are module constants (`SEAT_SYSTEM`, `ROUND0_USER`, `ROUND_N_USER`,
  `CHAIRMAN_*`). `parse_footer()` extracts `POSITION SUMMARY`, `VERDICT`, `DISAGREEMENTS`
  from the tail of each reply; `parse_quorum()` maps `all|majority|2/3|0.75` to a vote count.
- `main.py`: routes. The stream endpoint appends a discussion turn and saves progress
  after rounds, accepted human input, and completion. Lifespan clears orphaned waits
  and marks unfinished turns interrupted after restart.
- `discussion.py`: bounded follow-up context (20 human turns / 120,000 characters),
  preserving all human contributions, prior syntheses, and latest seat positions.
- `interaction.py`: single-worker run leases and five-minute input windows. Only
  owners can send thoughts/skip while waiting; input is saved before resuming.
- `panels.py`: validated personal-panel definitions and owner-only resolution.
  `POST /api/panels` / `PUT /api/panels/{id}` store definitions in SQLite `panels`;
  owner-only `GET /api/panels/{id}` supports direct editor links.
  config appends only the signed-in user's presets and available model choices.
  Unchanged follow-ups inherit the prior snapshot unless `use_latest_panel` is true.
- `db.py`: SQLite (`data/council.db`) with `users`, `sessions`, `conversations`. A
  conversation's messages are one JSON column; owner/title/timestamps are columns.
  `import_legacy_json()` migrates pre-accounts JSON files once (renames them `.imported`).
- `auth.py`: scrypt password hashes (`hashlib.scrypt`, stdlib), bearer tokens stored as
  sha256 in `sessions`, FastAPI dependencies `current_user` / `current_admin`,
  `can_access()` (owner or admin). `bootstrap_admin()` runs in the app lifespan
  and requires an explicit `ADMIN_PASSWORD` when creating the first administrator.
- Access rule: every conversation route loads via `_load_for(user, id)`, which 404s for
  both "missing" and "not yours" so existence is never leaked. Running a debate is
  owner-only even for the admin (admin view is read-only).
- Assistant messages include `{role, config, rounds[], final, error, human_inputs[],
  waiting_for_input}`. Conversation GET also returns the live `is_running` state.

Run as `uv run python -m backend.main` from the repo root (relative imports).

## Frontend (`frontend/src/`)

- `api.js`: bearer token in localStorage (`ai_council_token`); a 401 for the current
  session signs the user out locally. Stale authenticated responses are rejected.
- `App.jsx`: auth bootstrap (`/api/auth/me`), then `/api/config` and the conversation
  list for the current `scope` (`mine` or, for admins, `all`). Maps SSE events onto the
  last assistant message, guarded by the conversation id the stream belongs to.
  Per-run snapshots/revisions protect navigation from stale GET responses. Drafts
  and settings are kept per conversation until logout/reload; other-tab active runs
  poll with retries. App stays mounted across routes, preserving attached streams.
- `routes.js`, `main.jsx`: BrowserRouter, debate/panel links and safe login return URLs.
  Production SPA fallback only handles known view paths, retaining API/asset 404s.
- `components/Login.jsx`: sign in / create account, then return to the requested URL.
- `components/DiscussionsHome.jsx`: searchable history, editable starter prompts,
  and the default council preview. The sidebar keeps an active-run link visible.
- `avatars.js`, `Avatar.jsx`, `public/avatars/`: eight original vector profiles and
  shared identity resolution. Panel drafts materialize identity before editing;
  uploads are 256px WebP, validated raster data URLs of at most 100 KiB server-side.
  Avatar data stays out of seat, chairman, and title prompts.
- `components/PanelSetup.jsx`: preset / max rounds / quorum controls plus member links.
  Shown before the first turn and in collapsed follow-up settings. Personal panels
  are editable even when models become unavailable; invalid selections block start.
- `components/PanelLibrary.jsx`: account panels and shared templates at `/panels`.
- `components/PanelRoute.jsx`: owner-scoped loads, retained drafts and save-return flow.
- `components/PanelEditor.jsx`: full-page editor with one selected member form,
  1–8 discussion seats and required Chairman. Selection uses `?seat=0` or
  `?seat=chairman`; server save errors retain edits; model choices come from config.
- `components/Round.jsx`: one tab per seat; verdict dot on the tab; de-anonymizes
  `Position X` to the seat name in bold using `round.label_to_seat`.
- `components/Final.jsx`: chairman answer with a converged / open status pill and the
  unresolved list.
- `components/ChatInterface.jsx`: persistent owner composer, input countdown and
  skip action, contextual follow-ups, saved interjections, and draft retention on
  rejected requests. A submitted thought clears only after server acceptance.
  Archived turns show synthesis before collapsed evidence; live turns retain round
  instances and reading position when the final answer arrives. `Round.jsx` supports
  keyboard speaker selection and position summaries; answers/links can be copied.
- `index.css`: paper/evergreen visual tokens, DM Sans/Instrument Serif typography,
  visible keyboard focus and reduced motion. Avatars and fonts are self-hosted.

## Protocol decisions

- Seats see peers as `Position A..` only; their own previous position is passed
  separately. Labels are per round and stored in `label_to_seat` for the UI.
- Convergence is judged by the seats themselves (`VERDICT`) and aggregated by quorum.
  Cheaper than a separate mediator call per round and runs in parallel.
- Reaching the round cap is reported as "no full consensus", never smoothed over. The
  chairman prompt gets the explicit status plus the union of flagged disagreements.
- Footer labels stay in English even for non-English questions so parsing is stable.
- Human input is optional between actual rounds (300 seconds by default), with
  immediate resume on send/skip. No pause after quorum/cap/final. Follow-up turns
  inherit settings and ask every model to assess new human arguments with reasons.

## Gotchas

- Azure Foundry OpenAI route wants the *deployment* name as `model`
  through `FOUNDRY_DEPLOYMENT_MAP`; public presets use canonical OpenAI IDs.
  Verify each deployment serves the mapped model. A wrong name causes a 404.
- `MAX_OUTPUT_TOKENS` (default 8192) is sent as `max_completion_tokens`.
- Reasoning models (gpt-6-astra) can take 1 to 3 minutes per round.
- Retired models: two rules in `config.retire_models()`. Durable data (the startup
  `db.migrate_retired_models()` over the `panels` table) only rewrites the explicit
  denylist (`RETIRED_PROVIDERS`, `RETIRED_MODEL_PREFIXES`, case-insensitive). Run time
  (`normalize_panel`, `panels.select_panel`) uses `offered_only=True`: anything not in
  `model_options()` is replaced, so only configured OpenAI models reach `chat()`. Both
  refuse to rewrite when `REPLACEMENT_MODEL` is not itself a configured choice. The old
  pair stays on the member as `replaced_model` (accepted by `PanelMember`, stripped on
  save by `_saved_definition`, shown in PanelSetup and round entry titles). Renamed
  preset keys live in `PRESET_ALIASES` and are exposed as `aliases` in `/api/config`.
  `REQUEST_TIMEOUT` defaults to 360s; transient errors and timeouts retry up to 3 times.
- SSE parsing in `api.js` buffers on blank-line boundaries; events can span chunks.

## Contributor checks

Read `CONTRIBUTING.md` before changing code and `SECURITY.md` for trust boundaries.
Run `uv run python -m unittest discover -s tests`, then `npm --prefix frontend test`, frontend lint, and build.
Use temporary databases and mocked providers; never use private user data or paid
provider calls in tests. Hosting coordinates and credentials belong in private
operator configuration, not in this repository.
