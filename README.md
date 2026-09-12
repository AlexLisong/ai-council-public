# AI Council

Explore difficult questions through a structured conversation with AI. Chat with one
model, or assemble a council of distinct personas that challenge each other's
reasoning before a chairman summarizes the conclusion and remaining disagreements.

Built with React, FastAPI, and SQLite. Inspired by
[Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council), with AI
Council's own implementation of iterative debates, human participation, reusable
panels, and account-scoped history. See [acknowledgments](NOTICE.md).

Available under the [MIT License](LICENSE); third-party licenses remain separate.

## What you can do

- **Chat:** stream replies, continue a saved thread, select a model, or stop a response.
- **Compare perspectives:** give each council seat its own persona and approved OpenAI
  model; stop on a chosen quorum or round limit without forcing agreement.
- **Join the debate:** add context between rounds or continue after the synthesis.
- **Build personal panels:** save 1–8 members and a chairman, with names and portraits.
- **Inspect the reasoning:** revisit rounds, position summaries, disagreements, and
  human contributions in persistent discussion history.

Council agreement is a model-generated signal, not proof that an answer is correct.
The application sends conversation content to the configured model providers. Each
round uses additional model calls and can incur usage charges.

## Run locally

You need Python 3.10 or newer, [uv](https://docs.astral.sh/uv/), Node.js 22, npm, and
credentials for a supported model provider. Provider access is not included.

```bash
git clone https://github.com/AlexLisong/ai-council-public.git
cd ai-council-public
uv sync --frozen
npm --prefix frontend ci
cp .env.example .env
```

In `.env`, set a unique `ADMIN_PASSWORD` of at least eight characters and your
`OPENAI_API_KEY`. The example disables public account registration. Credentials stay
on the server; never put them in `VITE_*` variables or commit your `.env`.

Start the two processes in separate terminals:

```bash
uv run python -m backend.main
```

```bash
npm --prefix frontend run dev
```

On macOS or Linux, `./start.sh` starts both processes and stops them together.

Open **http://localhost:5173** and sign in as `admin` with the password you configured.
Use **Chat** for a direct answer. In **Council**, choose **OpenAI API council** when
using an OpenAI API key. Azure presets require the matching Azure configuration.
The API runs at **http://localhost:8001**; interactive API documentation is at `/docs`.

The database is created in the ignored `data/` directory. Changing `ADMIN_PASSWORD`
after the administrator exists does not reset that account's password.

## Model and panel configuration

Supported routes are the OpenAI API, Azure OpenAI, and approved OpenAI models through
OpenRouter. Models and trusted HTTPS endpoints are allowlisted at selection and
request time; arbitrary compatible proxies are not supported.

Edit `council.config.json` to change shared templates. It is reloaded per request.
For private overrides, copy it to the ignored `council.local.json` and set
`COUNCIL_CONFIG=council.local.json`. Restart after changing environment variables.

| Provider | Required environment variables | Public model IDs |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | For example `gpt-5.1` |
| Azure OpenAI | `FOUNDRY_RESOURCE`, `FOUNDRY_API_KEY` | Canonical OpenAI IDs; optional private deployment mapping |
| OpenRouter | `OPENROUTER_API_KEY` | Approved IDs prefixed with `openai/` |

Azure operators can set `FOUNDRY_DEPLOYMENT_MAP` to a JSON object mapping a public
model ID to their deployment name. The mapping is server-only and is not returned
by `/api/config`. Verify that each deployment actually serves the named OpenAI model.
See [.env.example](.env.example) for the format and optional tuning.

Models must appear in a preset or `EXTRA_MODELS` and pass
[`backend/model_policy.py`](backend/model_policy.py). Missing providers disable the
associated templates. Set `REPLACEMENT_PROVIDER` and `REPLACEMENT_MODEL` to an
available choice when migrating retired panel models; historical responses remain
intact. See [architecture](docs/architecture.md) for migration rules.

## Learn the codebase

| Area | Responsibility |
| --- | --- |
| `backend/main.py` | Authenticated API, streaming, application lifecycle |
| `backend/debate.py`, `backend/chat.py` | Council protocol and normal chat |
| `backend/providers.py`, `backend/model_policy.py` | Provider transport and model restrictions |
| `backend/db.py`, `backend/panels.py` | SQLite persistence and account-owned panels |
| `frontend/src/` | React workspace, routes, editor, and streamed responses |
| `tests/` | Backend regressions with temporary storage and mocked providers |
| `deploy/` | Optional self-hosting examples and release packaging |

Read the [usage and API guide](docs/usage.md), [architecture](docs/architecture.md),
and [self-hosting guide](deploy/README.md). Self-hosting currently requires **one
application process and one instance** because run coordination and rate limiting
are in memory. The administrator can read other users' conversations; this is not
end-to-end encrypted storage.

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md) for setup, useful contribution areas,
review expectations, and contribution terms. For ordinary questions or
bugs, open a GitHub issue using a reproducible example without private data.
Report vulnerabilities through [SECURITY.md](SECURITY.md).

Run the same checks used by CI:

```bash
uv run python -m unittest discover -s tests
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

Backend and browser-client tests use mocked model responses; real provider calls are not needed. CI checks the
backend on Python 3.10 and 3.12, and tests, lints, and builds the frontend on Node.js 22. There is
not yet an automated browser test suite; UI changes also need a manual browser check.
