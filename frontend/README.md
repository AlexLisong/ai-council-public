# AI Council frontend

React 19 and Vite power the Chat/Council workspace, saved discussion routes, and
personal panel editor. Start from the [root README](../README.md) for account and
provider setup.

From the repository root:

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
npm --prefix frontend run lint
npm --prefix frontend run build
```

The development server runs on port 5173 and proxies `/api` to the backend on port
8001. Built files go to `frontend/dist`; FastAPI serves them for same-origin hosting.
Never expose credentials through Vite environment variables: model requests run on
the backend.

`src/App.jsx` manages auth, conversations, and streaming state. `src/routes.js` and
`src/main.jsx` define direct routes. `src/components/` contains the workspace and
panel editor; `src/api.js` handles authenticated requests and streamed events.
Read [architecture](../docs/architecture.md) before changing navigation, cancellation,
or stale-response handling. For UI changes, test keyboard use and narrow layouts in
a browser in addition to lint/build. See [CONTRIBUTING.md](../CONTRIBUTING.md).
