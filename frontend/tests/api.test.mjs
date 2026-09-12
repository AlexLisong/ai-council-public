import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { api, getToken, setToken, setUnauthorizedHandler } from '../src/api.js';

const originalFetch = globalThis.fetch;
const originalStorage = globalThis.localStorage;
const utf8 = new TextEncoder();
let values;

beforeEach(() => {
  values = new Map();
  globalThis.localStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
  setUnauthorizedHandler(null);
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalStorage === undefined) delete globalThis.localStorage;
  else globalThis.localStorage = originalStorage;
});

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const frame = (event, ending = '\n') => `data: ${JSON.stringify(event)}${ending}${ending}`;
function streaming(chunks = [], { close = true } = {}) {
  let controller;
  let cancellations = 0;
  const body = new ReadableStream({
    start(source) {
      controller = source;
      for (const chunk of chunks) source.enqueue(typeof chunk === 'string' ? utf8.encode(chunk) : chunk);
      if (close) source.close();
    },
    cancel() { cancellations += 1; },
  });
  const response = new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
  globalThis.fetch = async () => response;
  return { response, controller, get cancellations() { return cancellations; } };
}

test('tokens use the public storage key and can be cleared', () => {
  assert.equal(getToken(), null);
  setToken('session-a');
  assert.equal(values.get('ai_council_token'), 'session-a');
  values.set('ai_council_token', 'other-tab');
  assert.equal(getToken(), 'other-tab');
  setToken(null);
  assert.equal(values.has('ai_council_token'), false);
});

test('all HTTP methods, defaults, bodies, and URL components match the contract', async () => {
  setToken('session-a');
  const panel = { name: 'Panel', members: [] };
  const routes = [
    [() => api.authSettings(), 'GET', '/api/auth/settings'],
    [() => api.register('test', 'secret'), 'POST', '/api/auth/register', { username: 'test', password: 'secret' }],
    [() => api.login('test', 'secret'), 'POST', '/api/auth/login', { username: 'test', password: 'secret' }],
    [() => api.logout(), 'POST', '/api/auth/logout'],
    [() => api.me(), 'GET', '/api/auth/me'],
    [() => api.adminUsers(), 'GET', '/api/admin/users'],
    [() => api.getConfig(), 'GET', '/api/config'],
    [() => api.getPanel('x/y ?'), 'GET', '/api/panels/x%2Fy%20%3F'],
    [() => api.savePanel(null, panel), 'POST', '/api/panels', panel],
    [() => api.savePanel('a/b', panel), 'PUT', '/api/panels/a%2Fb', panel],
    [() => api.listConversations(), 'GET', '/api/conversations?scope=mine'],
    [() => api.listConversations('all&owner=x'), 'GET', '/api/conversations?scope=all%26owner%3Dx'],
    [() => api.createConversation(), 'POST', '/api/conversations', { mode: 'chat' }],
    [() => api.createConversation('council'), 'POST', '/api/conversations', { mode: 'council' }],
    [() => api.getConversation('a/b'), 'GET', '/api/conversations/a%2Fb'],
    [() => api.deleteConversation('a/b'), 'DELETE', '/api/conversations/a%2Fb'],
    [() => api.submitInput('a/b', { content: 'A thought' }), 'POST', '/api/conversations/a%2Fb/input', { content: 'A thought' }],
  ];
  for (const [invoke, method, path, body] of routes) {
    let called = 0;
    globalThis.fetch = async (url, init) => {
      called += 1;
      assert.equal(url, path);
      assert.equal(init.method, method);
      assert.equal(init.headers.Authorization, 'Bearer session-a');
      assert.equal(init.headers['Content-Type'], body === undefined ? undefined : 'application/json');
      assert.deepEqual(init.body === undefined ? undefined : JSON.parse(init.body), body);
      return json({ ok: true });
    };
    assert.deepEqual(await invoke(), { ok: true });
    assert.equal(called, 1);
  }
});

test('anonymous requests omit bearer credentials and HTTP 204 returns null', async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(init.headers.Authorization, undefined);
    return new Response(null, { status: 204 });
  };
  assert.equal(await api.logout(), null);
});

test('FastAPI errors expose status and readable string or location-based details', async () => {
  globalThis.fetch = async () => json({ detail: 'That name is taken.' }, 409);
  await assert.rejects(api.register('taken', 'password'), { status: 409, message: 'That name is taken.' });
  globalThis.fetch = async () => json({ detail: [
    { loc: ['body', 'members', 0, 'model'], msg: 'Field required' },
    { loc: ['body', 'name'], msg: 'Too short' },
  ] }, 422);
  await assert.rejects(api.savePanel(null, {}), {
    status: 422, message: 'body.members.0.model: Field required; body.name: Too short',
  });
});

test('non-JSON HTTP failures and malformed success responses do not expose raw body text', async () => {
  globalThis.fetch = async () => new Response('private provider body', { status: 502 });
  await assert.rejects(api.me(), (error) => error.status === 502 && !error.message.includes('private'));
  globalThis.fetch = async () => new Response('private provider body');
  await assert.rejects(api.me(), (error) => /invalid JSON/.test(error.message) && !error.message.includes('private'));
});

test('a current 401 invokes the registered handler once and preserves HTTP status', async () => {
  setToken('session-a');
  let unauthorized = 0;
  setUnauthorizedHandler(() => { unauthorized += 1; setToken(null); });
  globalThis.fetch = async () => json({ detail: 'Please log in.' }, 401);
  await assert.rejects(api.me(), { status: 401, message: 'Please log in.' });
  assert.equal(unauthorized, 1);
});

test('a stale 401 cannot sign out a newer session', async () => {
  setToken('session-a');
  let unauthorized = 0;
  setUnauthorizedHandler(() => { unauthorized += 1; });
  const reply = deferred();
  globalThis.fetch = () => reply.promise;
  const result = api.me();
  setToken('session-b');
  reply.resolve(json({ detail: 'Expired' }, 401));
  await assert.rejects(result, { name: 'SessionChangedError' });
  assert.equal(unauthorized, 0);
  assert.equal(getToken(), 'session-b');
});

test('a session switch while reading JSON rejects success and HTTP error responses', async () => {
  for (const status of [200, 401]) {
    setToken('session-a');
    const body = deferred();
    const reading = deferred();
    let unauthorized = false;
    setUnauthorizedHandler(() => { unauthorized = true; });
    globalThis.fetch = async () => ({
      ok: status === 200, status,
      json() { reading.resolve(); return body.promise; },
    });
    const result = api.me();
    await reading.promise;
    values.set('ai_council_token', 'other-tab');
    body.resolve(status === 200 ? { id: 'a' } : { detail: 'Expired' });
    await assert.rejects(result, { name: 'SessionChangedError' });
    assert.equal(unauthorized, false);
  }
});

test('signing out and back in with the same token still invalidates an earlier request', async () => {
  setToken('session-a');
  const reply = deferred();
  globalThis.fetch = () => reply.promise;
  const result = api.me();
  setToken(null);
  setToken('session-a');
  reply.resolve(json({ id: 'old-user' }));
  await assert.rejects(result, { name: 'SessionChangedError' });
});

test('stream POST forwards JSON, credentials and signal; acceptance precedes ordered events', async () => {
  setToken('session-a');
  const stop = new AbortController();
  const source = streaming([frame({ type: 'chat_delta', data: { content: 'Hi' } }) + frame({ type: 'complete' })]);
  const order = [];
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/conversations/a%2Fb/message/stream');
    assert.equal(init.method, 'POST');
    assert.equal(init.headers.Authorization, 'Bearer session-a');
    assert.equal(init.headers.Accept, 'text/event-stream');
    assert.equal(init.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(init.body), { content: 'Hello' });
    assert.equal(init.signal, stop.signal);
    return source.response;
  };
  await api.sendMessageStream('a/b', { content: 'Hello' }, async (type, event) => {
    await Promise.resolve();
    assert.equal(type, event.type);
    order.push(type);
  }, { signal: stop.signal, onAccepted: () => { order.push('accepted'); } });
  assert.deepEqual(order, ['accepted', 'chat_delta', 'complete']);
  assert.equal(source.response.body.locked, false);
});

test('incremental UTF-8, split CRLF, multiline data, comments and unrelated SSE fields work', async () => {
  const text = ': heartbeat\r\nevent: ignored\r\nid: 7\r\nretry: 20\r\ndata: {"type":"chat_delta",\r\ndata: "data":{"content":"你好 🌎"}}\r\n\r\n' + frame({ type: 'complete' }, '\r\n');
  const source = streaming(Array.from(utf8.encode(text), (byte) => new Uint8Array([byte])));
  const events = [];
  await api.sendMessageStream('x', {}, (type, event) => events.push([type, event.data?.content]));
  assert.deepEqual(events, [['chat_delta', '你好 🌎'], ['complete', undefined]]);
  assert.equal(source.response.body.locked, false);
});

test('terminal complete and error events each stop delivery and release an open stream', async () => {
  for (const type of ['complete', 'error']) {
    const terminal = { type, message: 'A handled server error' };
    const source = streaming([frame(terminal) + frame({ type: 'chat_delta', data: { content: 'late' } })], { close: false });
    const events = [];
    await api.sendMessageStream('x', {}, (eventType, event) => events.push([eventType, event]));
    assert.deepEqual(events, [[type, terminal]]);
    assert.equal(source.cancellations, 1);
    assert.equal(source.response.body.locked, false);
  }
});

test('a final terminal event without a trailing blank line is accepted', async () => {
  streaming(['data:{"type":"complete"}']);
  const events = [];
  await api.sendMessageStream('x', {}, (type) => events.push(type));
  assert.deepEqual(events, ['complete']);
});

test('empty or nonterminal EOF explains that saved progress can be reloaded', async () => {
  for (const chunks of [[], [frame({ type: 'chat_delta', data: { content: 'partial' } })]]) {
    const source = streaming(chunks);
    await assert.rejects(api.sendMessageStream('x', {}, () => {}), /ended before.*progress may have been saved.*Reload/);
    assert.equal(source.response.body.locked, false);
  }
});

test('invalid event JSON or shape rejects without exposing event content', async () => {
  for (const payload of ['private prompt text', 'null', '[]', '{"data":"private prompt text"}']) {
    const source = streaming([`data: ${payload}\n\n`], { close: false });
    await assert.rejects(api.sendMessageStream('x', {}, () => {}), (error) => /event/.test(error.message) && !error.message.includes('private'));
    assert.equal(source.cancellations, 1);
    assert.equal(source.response.body.locked, false);
  }
});

test('rejected streaming headers never call acceptance or event callbacks', async () => {
  let calls = 0;
  globalThis.fetch = async () => json({ detail: 'Busy' }, 409);
  await assert.rejects(api.sendMessageStream('x', {}, () => { calls += 1; }, {
    onAccepted: () => { calls += 1; },
  }), { status: 409, message: 'Busy' });
  assert.equal(calls, 0);
});

test('stream callbacks fail once, retain their errors, and clean up readers', async () => {
  for (const failAt of ['accepted', 'event']) {
    const source = streaming([frame({ type: 'chat_delta' }) + frame({ type: 'complete' })], { close: false });
    const failure = new Error(`callback failed at ${failAt}`);
    let accepted = 0;
    let events = 0;
    await assert.rejects(api.sendMessageStream('x', {}, () => {
      events += 1;
      if (failAt === 'event') throw failure;
    }, { onAccepted: async () => {
      accepted += 1;
      if (failAt === 'accepted') throw failure;
    } }), (error) => error === failure);
    assert.equal(accepted, 1);
    assert.equal(events, failAt === 'event' ? 1 : 0);
    assert.equal(source.cancellations, 1);
    assert.equal(source.response.body.locked, false);
  }
});

test('an already aborted signal does not start a request', async () => {
  const stop = new AbortController();
  stop.abort();
  globalThis.fetch = () => { assert.fail('fetch should not run'); };
  await assert.rejects(api.sendMessageStream('x', {}, () => {}, { signal: stop.signal }), { name: 'AbortError' });
});

test('abort interrupts a pending stream read and releases the reader', async () => {
  const stop = new AbortController();
  const accepted = deferred();
  const source = streaming([], { close: false });
  const result = api.sendMessageStream('x', {}, () => assert.fail('unexpected event'), {
    signal: stop.signal, onAccepted: accepted.resolve,
  });
  await accepted.promise;
  await new Promise((resolve) => setImmediate(resolve));
  stop.abort();
  await assert.rejects(result, { name: 'AbortError' });
  assert.equal(source.cancellations, 1);
  assert.equal(source.response.body.locked, false);
});

test('a token switch during a stream read prevents further event delivery', async () => {
  setToken('session-a');
  const accepted = deferred();
  const source = streaming([], { close: false });
  const result = api.sendMessageStream('x', {}, () => assert.fail('stale event delivered'), { onAccepted: accepted.resolve });
  await accepted.promise;
  await new Promise((resolve) => setImmediate(resolve));
  setToken('session-b');
  source.controller.enqueue(utf8.encode(frame({ type: 'complete' })));
  await assert.rejects(result, { name: 'SessionChangedError' });
  assert.equal(source.cancellations, 1);
  assert.equal(source.response.body.locked, false);
});

test('a callback that switches sessions prevents remaining buffered events', async () => {
  setToken('session-a');
  const source = streaming([frame({ type: 'chat_delta' }) + frame({ type: 'complete' })], { close: false });
  const events = [];
  await assert.rejects(api.sendMessageStream('x', {}, (type) => {
    events.push(type);
    setToken('session-b');
  }), { name: 'SessionChangedError' });
  assert.deepEqual(events, ['chat_delta']);
  assert.equal(source.cancellations, 1);
});

test('a stale streaming response is canceled before acceptance or reader acquisition', async () => {
  setToken('session-a');
  const source = streaming([], { close: false });
  const headers = deferred();
  globalThis.fetch = () => headers.promise;
  const result = api.sendMessageStream('x', {}, () => assert.fail('stale event'), {
    onAccepted: () => assert.fail('stale acceptance'),
  });
  setToken('session-b');
  headers.resolve(source.response);
  await assert.rejects(result, { name: 'SessionChangedError' });
  assert.equal(source.cancellations, 1);
  assert.equal(source.response.body.locked, false);
});

test('abort while waiting for headers rejects promptly and cancels a late response', async () => {
  const stop = new AbortController();
  const source = streaming([], { close: false });
  const headers = deferred();
  globalThis.fetch = () => headers.promise;
  const result = api.sendMessageStream('x', {}, () => assert.fail('late event'), {
    signal: stop.signal, onAccepted: () => assert.fail('late acceptance'),
  });
  stop.abort();
  await assert.rejects(result, { name: 'AbortError' });
  headers.resolve(source.response);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(source.cancellations, 1);
  assert.equal(source.response.body.locked, false);
});
