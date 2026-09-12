# Contributing to AI Council

Thank you for helping make model-assisted discussions easier to understand and
inspect. Bug reports, documentation feedback, accessibility reviews, and focused
improvements are useful contributions.

## Contribution terms

By submitting a contribution, you agree to license your original contribution
under this project's [MIT License](LICENSE). Only submit work you have the right
to contribute. Preserve third-party copyright and license notices, and explain
any new dependency or borrowed material in your pull request. See
[NOTICE.md](NOTICE.md) for project inspiration and third-party attribution.

## Find a useful task

Check existing issues before starting. For a substantial change, describe the user
problem, a small proposed solution, and relevant tradeoffs in an issue first.
Smaller fixes can go directly to a pull request without a separate planning issue.
Useful areas include keyboard and screen-reader access, deterministic streaming
regressions, clearer model-error states, and documentation of the debate protocol.
No response-time or release schedule is promised; maintainers prioritize focused,
reproducible work.

## Development setup

Follow [the README](README.md#run-locally). Use your own local database and provider
credentials. Backend tests need neither credentials nor a running server.
Use `uv sync --frozen` and `npm --prefix frontend ci` to install locked dependencies.
Run the backend and Vite in separate terminals while working on the UI.

- Backend code uses Python typing, async HTTP via httpx, and standard-library SQLite.
- Frontend code uses React function components, plain CSS, and ESLint.
- Keep public model IDs separate from private provider deployment names.
- Keep authorization checks on the server. Administrator read access must not grant
  write access to another account's conversations or panels.
- Preserve saved conversation snapshots; do not rewrite historical model responses.
- Avoid unrelated refactors. Explain schema and public API changes before implementing them.

## Verify your change

```bash
uv run python -m unittest discover -s tests
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

Use temporary SQLite databases and `httpx.MockTransport` or the existing provider
fixtures for regression tests. Never run paid model calls in CI. Add a test when
changing behavior that can regress, especially auth, cancellation, model dispatch,
or persistence. Documentation-only changes need checked commands and links.

For UI changes, also check a narrow viewport, keyboard navigation, reload of a direct
route, and the relevant Chat or Council flow. Capture screenshots with synthetic
content. There is currently no automated browser suite; do not describe a build as
browser coverage.

## Pull requests

Explain the problem, the resulting behavior, and exactly how you tested it. Link the
related issue and include screenshots for visible changes. Call out migrations,
compatibility effects, or remaining limitations. CI must pass before review.
Maintainers may request a smaller scope or a follow-up issue.

Check the complete diff before submitting. Exclude `.env` files, API keys, access
tokens, SQLite files, account records, private conversations, host inventories,
cloud account/resource IDs, local paths, and deployment artifacts. Use reserved
example domains and invented data in fixtures. Follow [SECURITY.md](SECURITY.md) for
vulnerability reports and [the code of conduct](CODE_OF_CONDUCT.md) in all project spaces.
