import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, Navigate, Route, Routes, matchPath, useLocation, useNavigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import Login from './components/Login';
import PanelLibrary from './components/PanelLibrary';
import PanelRoute from './components/PanelRoute';
import DiscussionsHome from './components/DiscussionsHome';
import Brand from './components/Brand';
import { debateHref, internalDestination } from './routes';
import { api, getToken, setToken, setUnauthorizedHandler } from './api';
import './App.css';

/** Update the last message of `prev`, but only if `prev` is still the conversation the stream belongs to. */
function updateLast(prev, convId, fn) {
  if (!prev || prev.id !== convId || prev.messages.length === 0) return prev;
  const messages = [...prev.messages];
  const last = { ...messages[messages.length - 1] };
  fn(last);
  messages[messages.length - 1] = last;
  return { ...prev, messages };
}

function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [authSettings, setAuthSettings] = useState({ allow_signup: true });
  const [authError, setAuthError] = useState(null);
  const [authBusy, setAuthBusy] = useState(false);

  const [config, setConfig] = useState(null);
  const [configError, setConfigError] = useState(null);
  const params = new URLSearchParams(location.search);
  const scope = params.get('scope') === 'all' && user?.role === 'admin' ? 'all' : 'mine';
  const [conversations, setConversations] = useState([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState(null);
  const currentConversationId = matchPath('/debates/:id', location.pathname)?.params.id || null;
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [runningConversationId, setRunningConversationId] = useState(null);
  const [inputBusy, setInputBusy] = useState(false);
  const [composerError, setComposerError] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [panelDrafts, setPanelDrafts] = useState({});
  const [conversationSettings, setConversationSettings] = useState({});
  const [conversationError, setConversationError] = useState(null);
  const [navigationError, setNavigationError] = useState(null);
  const [creating, setCreating] = useState(false);
  const homeMode = params.get('panel') || params.get('mode') === 'council' ? 'council' : 'chat';
  const [navigationNotice, setNavigationNotice] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const listRequest = useRef(0);
  const configRequest = useRef(0);
  const createRequest = useRef(0);
  const pendingCreate = useRef(false);
  const panelPatches = useRef(new Map());
  const activeRun = useRef(null);
  const runSnapshots = useRef(new Map());

  const signOutLocally = useCallback(() => {
    activeRun.current?.controller.abort();
    activeRun.current = null;
    runSnapshots.current.clear();
    setIsLoading(false);
    setRunningConversationId(null);
    setComposerError(null);
    setDrafts({});
    setPanelDrafts({});
    setConversationSettings({});
    setConversationError(null);
    setNavigationError(null);
    setNavigationNotice(null);
    setSidebarOpen(false);
    createRequest.current += 1;
    pendingCreate.current = false;
    setCreating(false);
    listRequest.current += 1;
    configRequest.current += 1;
    panelPatches.current.clear();
    setToken(null);
    setUser(null);
    setConversations([]);
    setListLoading(false);
    setListError(null);
    setCurrentConversation(null);
    setConfig(null);
    setConfigError(null);
  }, []);

  // Session bootstrap: validate a stored token, load auth settings.
  useEffect(() => {
    setUnauthorizedHandler(signOutLocally);
    api.authSettings().then(setAuthSettings).catch(() => {});
    if (!getToken()) {
      setAuthChecked(true);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => signOutLocally())
      .finally(() => setAuthChecked(true));
  }, [signOutLocally]);

  const loadConversations = useCallback(async () => {
    const request = ++listRequest.current;
    setListLoading(true);
    try {
      const items = await api.listConversations(scope);
      if (request === listRequest.current && getToken()) { setConversations(items); setListError(null); }
    } catch (error) {
      console.error('Failed to load conversations:', error);
      if (request === listRequest.current && getToken()) setListError('Your discussions could not load. Please try again.');
    } finally {
      if (request === listRequest.current) setListLoading(false);
    }
  }, [scope]);

  // Listing scope changes do not replace the user's panel configuration.
  useEffect(() => {
    if (!user) return;
    loadConversations();
  }, [user, loadConversations]);

  const loadConfig = useCallback(async () => {
    if (!user) return;
    const request = ++configRequest.current;
    try {
      const next = await api.getConfig();
      if (request !== configRequest.current || !getToken()) return;
      const presets = new Map(next.presets.map((preset) => [preset.key, preset]));
      for (const [key, panel] of panelPatches.current) {
        if (!presets.get(key)?.updated_at || presets.get(key).updated_at <= panel.updated_at) presets.set(key, panel);
      }
      setConfig({ ...next, presets: [...presets.values()] });
      setConfigError(null);
    } catch (error) {
      if (request === configRequest.current && getToken()) setConfigError(error.message);
    }
  }, [user]);

  useEffect(() => {
    loadConfig();
    return () => { configRequest.current += 1; };
  }, [loadConfig]);

  useEffect(() => {
    if (!user || !currentConversationId) return;
    let cancelled = false;
    let timer;
    let failures = 0;
    const refresh = async () => {
      const before = runSnapshots.current.get(currentConversationId);
      const revision = before?.revision;
      const wasRunning = activeRun.current?.conversationId === currentConversationId;
      try {
        const conversation = await api.getConversation(currentConversationId);
        if (cancelled) return;
        failures = 0;
        const latest = runSnapshots.current.get(currentConversationId);
        const hasNewEvents = latest && (wasRunning || latest !== before || latest.revision !== revision);
        setCurrentConversation(hasNewEvents ? latest.conversation : conversation);
        setConversationError(null);
        if (conversation.is_running && activeRun.current?.conversationId !== currentConversationId) {
          timer = setTimeout(refresh, 2000);
        }
      } catch (error) {
        if (cancelled) return;
        console.error('Failed to load conversation:', error);
        setConversationError({ id: currentConversationId, message: error.status === 404 ? 'This debate was not found or is not available to your account.' : error.message });
        if (![401, 403, 404].includes(error.status)) {
          failures += 1;
          timer = setTimeout(refresh, Math.min(2000 * failures, 10000));
        }
      }
    };
    refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [currentConversationId, user]);

  const handleAuth = async (mode, username, password) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      const result = mode === 'register' ? await api.register(username, password) : await api.login(username, password);
      setToken(result.token);
      setUser(result.user);
      navigate(internalDestination(new URLSearchParams(location.search).get('next')), { replace: true });
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      /* token may already be dead */
    }
    signOutLocally();
    navigate('/login', { replace: true });
  };

  const mergePanel = useCallback((saved) => {
    const patched = panelPatches.current.get(saved.key);
    if (patched?.updated_at > saved.updated_at) return;
    panelPatches.current.set(saved.key, saved);
    setConfig((previous) => {
      if (!previous) return previous;
      const existing = previous.presets?.find((preset) => preset.key === saved.key);
      if (existing?.updated_at > saved.updated_at) return previous;
      return {
      ...previous,
      presets: previous?.presets?.some((preset) => preset.key === saved.key)
        ? previous.presets.map((preset) => preset.key === saved.key ? saved : preset)
        : [...(previous?.presets || []), saved],
      };
    });
  }, []);

  const handleSavePanel = async (id, panel) => {
    const requestToken = getToken();
    const saved = await api.savePanel(id, panel);
    if (requestToken !== getToken()) throw new Error('Your session changed. Please try again.');
    mergePanel(saved);
    return saved;
  };

  const openNewDraft = (mode = 'chat', fresh = false) => {
    setSidebarOpen(false);
    setNavigationNotice(currentConversationId ? `New ${mode === 'chat' ? 'chat' : 'council conversation'}. Your previous conversation is saved.` : null);
    if (fresh) setDrafts((previous) => ({ ...previous, new: '' }));
    navigate(mode === 'council' ? '/debates?mode=council' : '/debates');
  };

  const handleNewConversation = async (panel, prompt, mode = 'council') => {
    if (pendingCreate.current) return;
    const request = ++createRequest.current;
    pendingCreate.current = true;
    const originLocation = `${window.location.pathname}${window.location.search}`;
    setCreating(true);
    setNavigationError(null);
    try {
      const conv = await api.createConversation(mode);
      if (request !== createRequest.current) return;
      listRequest.current += 1;
      setListLoading(false);
      setConversations((prev) => [{ ...conv, owner_username: user.username, message_count: 0 }, ...prev]);
      if (prompt) setDrafts((previous) => ({ ...previous, [conv.id]: prompt }));
      if (`${window.location.pathname}${window.location.search}` === originLocation) {
        setCurrentConversation(conv);
        setSidebarOpen(false);
        navigate(debateHref(conv.id, { panel }));
      }
      return conv;
    } catch (error) {
      if (request !== createRequest.current) return;
      console.error('Failed to create conversation:', error);
      setNavigationError(error.message);
    } finally {
      if (request === createRequest.current) {
        pendingCreate.current = false;
        setCreating(false);
      }
    }
  };

  const handleDeleteConversation = async (id) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (id === currentConversationId) {
        setCurrentConversation(null);
        navigate(debateHref(null, { scope }));
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      setNavigationError(error.message);
    }
  };

  const handleSendMessage = (content, settings, conversation = currentConversation) => {
    if (!conversation || activeRun.current || (conversation === currentConversation && conversation.id !== currentConversationId)) return Promise.resolve(false);
    const convId = conversation.id;
    const previous = conversation;
    const isChat = conversation.mode === 'chat';
    const acceptedLocation = currentConversationId === convId ? `${location.pathname}${location.search}` : debateHref(convId);
    const run = {
      conversationId: convId, controller: new AbortController(), revision: 0,
      conversation: {
        ...previous, is_running: true,
        messages: [...previous.messages, { role: 'user', content }, {
          role: 'assistant', mode: isChat ? 'chat' : 'council', content: '', config: null, rounds: [], final: null, human_inputs: [],
          waiting_for_input: null, loading: { round: null, final: false }, error: null,
        }],
      },
    };
    activeRun.current = run;
    runSnapshots.current.set(convId, run);
    if (runSnapshots.current.size > 8) runSnapshots.current.delete(runSnapshots.current.keys().next().value);
    setIsLoading(true);
    setRunningConversationId(convId);
    setComposerError(null);

    if (matchPath('/debates/:id', window.location.pathname)?.params.id === convId) {
      setCurrentConversation(run.conversation);
    }
    const updateRun = (update) => {
      run.conversation = updateLast(run.conversation, convId, update);
      run.revision += 1;
      const snapshot = run.conversation;
      setCurrentConversation((prev) => prev?.id === convId ? snapshot : prev);
    };

    // Resolve when the server accepts the request, so a rejected request keeps
    // the draft while an accepted run frees the composer for the next thought.
    return new Promise((resolve) => {
      let accepted = false;
      const execute = async () => {
        try {
          await api.sendMessageStream(
            convId,
            isChat ? { content, provider: settings.provider, model: settings.model }
              : { content, preset: settings.preset, max_rounds: settings.maxRounds, consensus: settings.consensus, pause_for_input: settings.pauseForInput, use_latest_panel: settings.useLatestPanel },
            (type, event) => {
              if (activeRun.current !== run) return;
              switch (type) {
                case 'config':
                  updateRun((m) => { m.config = event.data; });
                  break;
                case 'chat_delta':
                  updateRun((m) => { m.content = (m.content || '') + event.data.content; });
                  break;
                case 'round_start':
                  updateRun((m) => {
                    m.waiting_for_input = null;
                    m.loading = { ...m.loading, round: event.round };
                  });
                  break;
                case 'round_complete':
                  updateRun((m) => {
                    m.rounds = [...m.rounds.filter((round) => round.round !== event.data.round), event.data].sort((a, b) => a.round - b.round);
                    m.loading = { ...m.loading, round: null };
                  });
                  break;
                case 'awaiting_input':
                  updateRun((m) => {
                    m.waiting_for_input = event.data;
                    m.loading = { round: null, final: false };
                  });
                  break;
                case 'input_received':
                  updateRun((m) => {
                    m.human_inputs = [...(m.human_inputs || []).filter((thought) => thought.created_at !== event.data.created_at || thought.after_round !== event.data.after_round), event.data];
                  });
                  break;
                case 'round_resumed':
                  updateRun((m) => { m.waiting_for_input = null; });
                  break;
                case 'final_start':
                  updateRun((m) => { m.loading = { ...m.loading, final: true }; });
                  break;
                case 'final_complete':
                  updateRun((m) => {
                    m.final = event.data;
                    if (isChat) m.content = event.data.response;
                    m.loading = { ...m.loading, final: false };
                  });
                  break;
                case 'title_complete':
                  run.conversation = { ...run.conversation, title: event.data.title };
                  setCurrentConversation((previous) => previous?.id === convId ? { ...previous, title: event.data.title } : previous);
                  setConversations((previous) => previous.map((item) => item.id === convId ? { ...item, title: event.data.title } : item));
                  break;
                case 'complete':
                  setConversations((previous) => previous.map((item) => item.id === convId ? { ...item, message_count: run.conversation.messages.length } : item));
                  break;
                case 'error':
                  updateRun((m) => {
                    m.error = event.message;
                    m.waiting_for_input = null;
                    m.loading = { round: null, final: false };
                  });
                  break;
                default:
                  console.log('Unknown event type:', type);
              }
            },
            { signal: run.controller.signal, onAccepted: () => {
              accepted = true;
              resolve(true);
              if (`${window.location.pathname}${window.location.search}` === acceptedLocation) {
                const search = new URLSearchParams(window.location.search);
                if (search.has('panel')) {
                  search.delete('panel');
                  navigate(`${window.location.pathname}${search.size ? `?${search}` : ''}`, { replace: true });
                }
              }
            } }
          );
        } catch (error) {
          if (activeRun.current !== run) return;
          if (!accepted) {
            run.conversation = previous;
            setCurrentConversation((prev) => prev?.id === convId ? previous : prev);
            setComposerError({ conversationId: convId, message: run.stopped ? 'Request stopped. Your draft is ready to send again.' : error.message });
          } else if (run.stopped && error.name === 'AbortError') {
            updateRun((m) => { m.stopped = true; });
          } else {
            updateRun((m) => {
              m.error = error.message;
              m.waiting_for_input = null;
              m.loading = { round: null, final: false };
            });
          }
        } finally {
          if (activeRun.current === run) {
            run.conversation = { ...run.conversation, is_running: false };
            updateRun((message) => { message.waiting_for_input = null; });
            activeRun.current = null;
            setIsLoading(false);
            setRunningConversationId(null);
          }
          if (!accepted) resolve(false);
        }
      };
      execute();
    });
  };

  const handleStartConversation = async (content, settings) => {
    if (creating || activeRun.current) return false;
    const conversation = await handleNewConversation(undefined, content, homeMode);
    if (!conversation) return false;
    setConversationSettings((previous) => ({ ...previous, [conversation.id]: settings }));
    const accepted = await handleSendMessage(content, settings, conversation);
    if (accepted) setDrafts((previous) => ({ ...previous, [conversation.id]: previous[conversation.id] === content ? '' : previous[conversation.id] }));
    return accepted;
  };

  const handleStop = () => {
    const run = activeRun.current;
    if (!run || run.conversationId !== currentConversationId || run.conversation.mode !== 'chat') return;
    run.stopped = true;
    run.controller.abort();
  };

  const handleInput = async (content, skip = false) => {
    const convId = currentConversationId;
    const deadline = currentConversation?.messages?.at(-1)?.waiting_for_input?.deadline;
    setInputBusy(true);
    setComposerError(null);
    try {
      await api.submitInput(convId, skip ? { skip: true } : { content });
      setCurrentConversation((prev) => updateLast(prev, convId, (m) => {
        if (m.waiting_for_input?.deadline === deadline) m.waiting_for_input = null;
      }));
      return true;
    } catch (error) {
      setComposerError({ conversationId: convId, message: error.message });
      try {
        const fresh = await api.getConversation(convId);
        const live = activeRun.current;
        setCurrentConversation((prev) => prev?.id === convId
          ? live?.conversationId === convId ? live.conversation : fresh
          : prev);
      } catch { /* Preserve the draft and original error if refreshing fails. */ }
      return false;
    } finally {
      setInputBusy(false);
    }
  };

  if (!authChecked) {
    return <div className="app"><div className="app-loading" role="status"><Brand /><span>Opening your workspace…</span></div></div>;
  }

  if (!user) {
    if (location.pathname !== '/login') return <Navigate replace to={`/login?${new URLSearchParams({ next: internalDestination(`${location.pathname}${location.search}`) })}`} />;
    return <Login allowSignup={authSettings.allow_signup} onSubmit={handleAuth} error={authError} busy={authBusy} />;
  }

  return (
    <div className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar
        user={user}
        scope={scope}
        onLogout={handleLogout}
        conversations={conversations}
        currentConversationId={currentConversationId}
        onNewConversation={() => openNewDraft('chat', true)}
        onDeleteConversation={handleDeleteConversation}
        busy={creating}
        runningConversationId={runningConversationId}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        onNavigate={() => setSidebarOpen(false)}
      />
      {navigationError && <div className="navigation-error" role="alert">{navigationError}<button onClick={() => setNavigationError(null)} aria-label="Dismiss error">×</button></div>}
      {configError && <div className="config-retry" role="alert">Settings could not load: {configError} <button onClick={loadConfig}>Retry</button></div>}
      <Routes>
        <Route path="/" element={<Navigate replace to="/debates" />} />
        <Route path="/login" element={<Navigate replace to={internalDestination(params.get('next'))} />} />
        <Route path="/debates" element={scope === 'all' || params.get('view') === 'history'
          ? <DiscussionsHome conversations={conversations} scope={scope} onNew={() => openNewDraft('chat', true)} busy={creating} loading={listLoading} error={listError} onRetry={loadConversations} />
          : <ChatInterface
            key={`new:${homeMode}:${params.get('panel') || ''}`}
            conversation={{ id: 'new', mode: homeMode, owner_id: user.id, messages: [] }}
            user={user} config={config} configError={configError}
            onSendMessage={handleStartConversation} onModeChange={openNewDraft}
            initialPreset={params.get('panel')} returnTo={`${location.pathname}${location.search}`} routeKey={location.key}
            settingsOverrides={conversationSettings[`new:${homeMode}`] || {}}
            setSettingsOverrides={(update) => setConversationSettings((previous) => ({ ...previous, [`new:${homeMode}`]: { ...(typeof update === 'function' ? update(previous[`new:${homeMode}`] || {}) : update), routeKey: location.key } }))}
            isLoading={isLoading || creating} isCurrentRun={false}
            input={drafts.new || ''} setInput={(update) => setDrafts((previous) => ({ ...previous, new: typeof update === 'function' ? update(previous.new || '') : update }))}
            notice={navigationNotice}
          />} />
        <Route path="/panels" element={<PanelLibrary config={config} error={configError} onUsePanel={handleNewConversation} busy={creating} />} />
        <Route path="/panels/:panelId" element={<PanelRoute config={config} configError={configError} drafts={panelDrafts} setDrafts={setPanelDrafts} onSavePanel={handleSavePanel} onPanelLoaded={mergePanel} />} />
        <Route path="/debates/:id" element={conversationError?.id === currentConversationId ? <main className="view-page"><h1>Debate unavailable</h1><p role="alert">{conversationError.message}</p><Link to={debateHref(null, { scope })}>Back to debates</Link></main> :
      <ChatInterface
        key={`${currentConversationId}:${params.get('panel') || ''}`}
        conversation={currentConversation?.id === currentConversationId ? currentConversation : null}
        user={user}
        config={config}
        configError={configError}
        onSendMessage={handleSendMessage}
        onModeChange={openNewDraft}
        onStop={handleStop}
        initialPreset={params.get('panel')}
        returnTo={`${location.pathname}${location.search}`}
        routeKey={location.key}
        settingsOverrides={conversationSettings[currentConversationId] || { preset: null, maxRounds: null, consensus: null, pauseForInput: null, useLatestPanel: false }}
        setSettingsOverrides={(update) => setConversationSettings((previous) => {
          const current = previous[currentConversationId] || { preset: null, maxRounds: null, consensus: null, pauseForInput: null, useLatestPanel: false };
          return { ...previous, [currentConversationId]: { ...(typeof update === 'function' ? update(current) : update), routeKey: location.key } };
        })}
        onInput={handleInput}
        isLoading={isLoading}
        isCurrentRun={isLoading && runningConversationId === currentConversationId}
        inputBusy={inputBusy}
        composerError={composerError?.conversationId === currentConversationId ? composerError.message : null}
        input={drafts[currentConversationId] || ''}
        setInput={(update) => setDrafts((previous) => ({
          ...previous,
          [currentConversationId]: typeof update === 'function' ? update(previous[currentConversationId] || '') : update,
        }))}
      />
        } />
        <Route path="*" element={<main className="view-page"><h1>Page not found</h1><Link to="/debates">Back to debates</Link></main>} />
      </Routes>
    </div>
  );
}

export default App;
