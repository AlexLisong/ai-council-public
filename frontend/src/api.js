// Independently implemented from the application's HTTP and event contracts.
const TOKEN_KEY = 'ai_council_token';
let sessionRevision = 0;
let unauthorizedHandler = null;

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  const next = token ? String(token) : null;
  if (next !== getToken()) sessionRevision += 1;
  if (next === null) localStorage.removeItem(TOKEN_KEY);
  else localStorage.setItem(TOKEN_KEY, next);
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = typeof handler === 'function' ? handler : null;
}

function requestContext(signal) {
  const token = getToken();
  const revision = sessionRevision;
  const check = () => {
    if (token !== getToken() || revision !== sessionRevision) {
      const error = new Error('Your session changed. Please try again.');
      error.name = 'SessionChangedError';
      throw error;
    }
    if (signal?.aborted) {
      throw signal.reason ?? new DOMException('The request was stopped.', 'AbortError');
    }
  };
  const wait = async (operation) => {
    let onAbort;
    try {
      check();
      const result = signal ? await Promise.race([
        operation,
        new Promise((resolve, reject) => {
          onAbort = () => reject(signal.reason ?? new DOMException('The request was stopped.', 'AbortError'));
          signal.addEventListener('abort', onAbort, { once: true });
          if (signal.aborted) onAbort();
        }),
      ]) : await operation;
      check();
      return result;
    } catch (error) {
      check();
      throw error;
    } finally {
      if (onAbort) signal.removeEventListener('abort', onAbort);
    }
  };
  return { token, check, wait };
}

async function receive(path, init, context) {
  const pending = fetch(path, init).then(async (response) => {
    try {
      context.check();
      return response;
    } catch (error) {
      // A late response still owns a body even when no reader was acquired.
      if (response.body && !response.body.locked) {
        try { await response.body.cancel(); } catch { /* Preserve cancellation. */ }
      }
      throw error;
    }
  });
  return context.wait(pending);
}

function options(context, method, body, signal) {
  const headers = { Accept: 'application/json' };
  if (context.token) headers.Authorization = `Bearer ${context.token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  return { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }), ...(signal ? { signal } : {}) };
}

function detailMessage(detail) {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (!Array.isArray(detail)) return null;
  const messages = detail.flatMap((item) => {
    if (!item || typeof item.msg !== 'string') return [];
    const location = Array.isArray(item.loc) ? item.loc.map(String).join('.') : '';
    return [location ? `${location}: ${item.msg}` : item.msg];
  });
  return messages.length ? messages.join('; ') : null;
}

async function ensureSuccess(response, context) {
  if (response.ok) return;
  let payload;
  try {
    payload = await context.wait(response.json());
  } catch {
    context.check();
  }
  const error = new Error(detailMessage(payload?.detail) ?? `Request failed (HTTP ${response.status}). Please try again.`);
  error.status = response.status;
  context.check();
  if (response.status === 401 && unauthorizedHandler) {
    // Authentication failure remains the caller's error even if UI cleanup fails.
    try { unauthorizedHandler(); } catch { /* Preserve the HTTP error. */ }
  }
  throw error;
}

async function request(path, method = 'GET', body) {
  const context = requestContext();
  const response = await receive(path, options(context, method, body), context);
  await ensureSuccess(response, context);
  context.check();
  if (response.status === 204) return null;
  try {
    return await context.wait(response.json());
  } catch (error) {
    context.check();
    if (error instanceof SyntaxError) throw new Error('The server returned an invalid JSON response. Please try again.');
    throw error;
  }
}

const progressHint = 'Your progress may have been saved. Reload the discussion to check before trying again.';

// SSE lines can span network chunks, including between CR and LF or UTF-8 bytes.
function eventDecoder(onEvent, check) {
  let pending = '';
  let data = [];
  let terminal = false;
  const dispatch = async () => {
    if (!data.length) return;
    const payload = data.join('\n');
    data = [];
    let event;
    try { event = JSON.parse(payload); } catch {
      throw new Error(`The server sent an unreadable event. ${progressHint}`);
    }
    if (!event || typeof event !== 'object' || Array.isArray(event) || typeof event.type !== 'string' || !event.type) {
      throw new Error(`The server sent an invalid event. ${progressHint}`);
    }
    check();
    await onEvent(event.type, event);
    check();
    terminal = event.type === 'complete' || event.type === 'error';
  };
  const line = async (value) => {
    if (value === '') return dispatch();
    const colon = value.indexOf(':');
    const field = colon < 0 ? value : value.slice(0, colon);
    if (field !== 'data') return;
    const content = colon < 0 ? '' : value.slice(colon + 1);
    data.push(content.startsWith(' ') ? content.slice(1) : content);
  };
  return async (text, eof = false) => {
    pending += text;
    while (!terminal) {
      const end = pending.search(/[\r\n]/);
      if (end < 0 || (!eof && end === pending.length - 1 && pending[end] === '\r')) break;
      const value = pending.slice(0, end);
      const width = pending[end] === '\r' && pending[end + 1] === '\n' ? 2 : 1;
      pending = pending.slice(end + width);
      await line(value);
    }
    if (eof && !terminal) {
      if (pending) await line(pending);
      pending = '';
      await dispatch();
    }
    return terminal;
  };
}

async function sendMessageStream(conversationId, body, onEvent, { onAccepted, signal } = {}) {
  const context = requestContext(signal);
  let response;
  let reader;
  try {
    context.check();
    const init = options(context, 'POST', body, signal);
    init.headers.Accept = 'text/event-stream';
    response = await receive(`${conversationPath(conversationId)}/message/stream`, init, context);
    await ensureSuccess(response, context);
    context.check();
    if (onAccepted) await context.wait(Promise.resolve().then(() => {
      context.check();
      return onAccepted();
    }));
    if (!response.body) throw new Error(`The server did not provide a response stream. ${progressHint}`);
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    const accept = eventDecoder(onEvent, context.check);
    while (true) {
      const { done, value } = await context.wait(reader.read());
      const terminal = await context.wait(accept(done ? decoder.decode() : decoder.decode(value, { stream: true }), done));
      if (terminal) return;
      if (done) throw new Error(`The response stream ended before the discussion finished. ${progressHint}`);
    }
  } finally {
    if (reader) {
      try { await reader.cancel(); } catch { /* Keep the original stream outcome. */ }
      reader.releaseLock();
    } else if (response?.body && !response.body.locked) {
      try { await response.body.cancel(); } catch { /* Keep the original request outcome. */ }
    }
  }
}

const segment = (value) => encodeURIComponent(String(value));
const conversationPath = (id) => `/api/conversations/${segment(id)}`;

export const api = {
  authSettings: () => request('/api/auth/settings'),
  register: (username, password) => request('/api/auth/register', 'POST', { username, password }),
  login: (username, password) => request('/api/auth/login', 'POST', { username, password }),
  logout: () => request('/api/auth/logout', 'POST'),
  me: () => request('/api/auth/me'),
  adminUsers: () => request('/api/admin/users'),
  getConfig: () => request('/api/config'),
  getPanel: (id) => request(`/api/panels/${segment(id)}`),
  savePanel: (id, panel) => id == null ? request('/api/panels', 'POST', panel) : request(`/api/panels/${segment(id)}`, 'PUT', panel),
  listConversations: (scope = 'mine') => request(`/api/conversations?scope=${segment(scope)}`),
  createConversation: (mode = 'chat') => request('/api/conversations', 'POST', { mode }),
  getConversation: (id) => request(conversationPath(id)),
  deleteConversation: (id) => request(conversationPath(id), 'DELETE'),
  submitInput: (id, body) => request(`${conversationPath(id)}/input`, 'POST', body),
  sendMessageStream,
};
