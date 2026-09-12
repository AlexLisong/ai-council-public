import { useState, useEffect, useRef } from 'react';
import { ArrowDown, ArrowRight, ArrowUp, Check, ChevronDown, Clock3, MessageCircle, MessageSquare, Square, UserRound, UsersRound } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import PanelSetup from './PanelSetup';
import Round from './Round';
import Final from './Final';
import Avatar from './Avatar';
import Brand from './Brand';
import CopyButton from './CopyButton';
import { modelLabel, panelLabel } from '../presentation';
import { STARTERS } from '../starters';
import './ChatInterface.css';

export default function ChatInterface({ conversation, user, config, configError, onSendMessage, onModeChange, onStop, initialPreset, returnTo, routeKey, settingsOverrides: overrides, setSettingsOverrides: setOverrides, onInput, isLoading, isCurrentRun, inputBusy, composerError, input, setInput, notice }) {
  const [submitting, setSubmitting] = useState(false);
  const [showJump, setShowJump] = useState(false);
  const messagesRef = useRef(null);
  const inputRef = useRef(null);
  const followLatest = useRef(true);
  const isChat = conversation?.mode === 'chat';
  const lastMessage = conversation?.messages?.at(-1);
  const previousConfig = conversation?.messages?.findLast((message) => message.config)?.config;
  const routeSelection = Boolean(initialPreset) && overrides.routeKey !== routeKey;
  const model = overrides.model ? overrides : previousConfig?.model ? previousConfig : config?.chat_default;
  const settings = isChat ? { provider: model?.provider, model: model?.model } : {
    preset: routeSelection ? initialPreset : overrides.preset ?? initialPreset ?? previousConfig?.preset ?? config?.default_preset ?? null,
    maxRounds: overrides.maxRounds ?? previousConfig?.max_rounds ?? config?.defaults?.max_rounds ?? 3,
    consensus: overrides.consensus ?? previousConfig?.consensus ?? config?.defaults?.consensus ?? 'all',
    pauseForInput: overrides.pauseForInput ?? previousConfig?.pause_for_input ?? true,
    useLatestPanel: routeSelection || overrides.useLatestPanel,
  };
  const panelSnapshot = !isChat && !settings.useLatestPanel && previousConfig?.preset === settings.preset ? previousConfig : null;
  // Stored Council snapshots are normalized on the server before the next turn.
  // In particular, a retired model must not make an old conversation unusable.
  const snapshotNeedsMigration = panelSnapshot && config?.model_options
    ? [...panelSnapshot.seats, panelSnapshot.chairman].some((member) => !config.model_options.some((option) => option.provider === member.provider && option.model === member.model)) : false;
  const panelUnavailable = !isChat && !panelSnapshot && config
    ? config.presets.find((preset) => preset.key === settings.preset || preset.aliases?.includes(settings.preset))?.available !== true : false;
  const modelUnavailable = isChat && !config?.model_options?.some((option) => option.provider === settings.provider && option.model === settings.model);
  const waiting = !isChat && lastMessage?.waiting_for_input;
  const currentRunning = isCurrentRun || conversation?.is_running;
  const running = isLoading || currentRunning;
  const blocked = submitting || inputBusy || !config || (running && !waiting) || (!waiting && (panelUnavailable || modelUnavailable));
  const isNew = conversation?.messages.length === 0;
  const isDraft = conversation?.id === 'new';
  const isOwner = !user || conversation?.owner_id === user.id;

  useEffect(() => {
    const container = messagesRef.current;
    if (container && followLatest.current) container.scrollTop = container.scrollHeight;
  }, [conversation?.id, conversation?.messages?.length, lastMessage?.rounds?.length,
    lastMessage?.human_inputs?.length, lastMessage?.content, lastMessage?.final?.response, lastMessage?.error,
    lastMessage?.loading?.round, lastMessage?.loading?.final, lastMessage?.waiting_for_input?.deadline]);

  useEffect(() => {
    const textarea = inputRef.current;
    if (textarea) { textarea.style.height = 'auto'; textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`; }
  }, [input, isNew]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!input.trim() || blocked || !isOwner) return;
    const draft = input;
    setSubmitting(true);
    try {
      const accepted = waiting ? await onInput(draft) : await onSendMessage(draft, settings);
      if (accepted) {
        setInput((current) => current === draft ? '' : current);
        if (!waiting) setOverrides(isChat ? settings : { ...settings, useLatestPanel: false });
      }
    } finally { setSubmitting(false); }
  };
  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); handleSubmit(event); }
  };
  const jumpToLatest = () => {
    followLatest.current = true; setShowJump(false);
    const container = messagesRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  };
  const applyStarter = (prompt) => { setInput(prompt); inputRef.current?.focus(); };

  if (!conversation) return <main className="chat-interface"><div className="discussion-loading" role="status"><div className="spinner" /> Opening conversation…</div></main>;
  const title = conversation.title && conversation.title !== 'New Conversation' ? conversation.title : conversation.messages[0]?.content || (isChat ? 'New chat' : 'New council conversation');
  const modeControls = <div className="mode-controls">
    <div className="mode-switch" role="group" aria-label="Conversation mode">
      {[{ mode: 'chat', label: 'Chat', Icon: MessageSquare }, { mode: 'council', label: 'Council', Icon: UsersRound }].map((choice) => { const { mode, label, Icon } = choice; return <button key={mode} type="button" aria-pressed={conversation.mode === mode || (!conversation.mode && mode === 'council')} disabled={submitting} title={isDraft ? (mode === 'chat' ? 'Talk directly with one AI model' : 'Explore perspectives with your AI council') : `Start a new ${label.toLowerCase()} conversation`} onClick={() => { if (mode !== (conversation.mode || 'council')) onModeChange(mode); }}><Icon size={15} /><span>{label}</span></button>; })}
    </div>
    {isChat && <ModelPicker config={config} settings={settings} onChange={setOverrides} disabled={currentRunning || submitting || !isOwner} />}
  </div>;
  const composerForm = <form className={`input-form ${isNew ? 'question-form' : ''}`} onSubmit={handleSubmit}>
    <textarea ref={inputRef} autoFocus={isNew} id="discussion-input" className="message-input" aria-label={isChat ? 'Message' : isNew ? 'Question' : 'Your thoughts'}
      placeholder={isChat ? 'Message AI Council' : waiting ? 'What should the council consider next?' : isNew ? 'Ask your council a question…' : 'Ask a follow-up or share your perspective…'}
      value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleKeyDown}
      disabled={submitting || inputBusy || !config} maxLength={20000} rows={1} />
    <div className="composer-actions"><span className="input-hint">{waiting ? 'Your thought will shape the next round' : isChat ? 'Enter to send · Shift + Enter for a new line' : 'Multiple perspectives. One conversation.'}</span>
      {isChat && isCurrentRun && onStop ? <button type="button" className="send-button stop-button" onClick={onStop} aria-label="Stop generating" title="Stop generating"><Square size={15} fill="currentColor" /></button>
        : <button type="submit" className={`send-button ${waiting ? 'send-thoughts' : ''}`} aria-label={waiting ? 'Send thoughts and continue' : isChat ? 'Send message' : isNew ? 'Start discussion' : 'Continue discussion'} title={waiting ? 'Send thoughts and continue' : 'Send message'} disabled={!input.trim() || blocked}>{waiting && <span>Send & continue</span>}{submitting ? <span className="button-spinner" /> : <ArrowUp size={19} strokeWidth={2.2} />}</button>}
    </div>
  </form>;

  return <main className={`chat-interface ${isChat ? 'chat-mode' : 'council-mode'} ${isNew ? 'new-discussion' : ''}`}>
    <header className="discussion-header">{modeControls}<div className="discussion-header-actions">{!isNew && <><h1 className="thread-title" title={title}>{title}</h1><CopyButton text={window.location.href} label="Copy link" /></>}</div></header>
    {!isOwner && <div className="viewing-banner">Viewing {conversation.owner_username}’s conversation · Admin access · Read only</div>}
    {isNew && !isOwner ? <section className="new-discussion-content"><div className="new-discussion-inner"><div className="new-question-intro"><h2>No messages yet</h2><p>{conversation.owner_username} has not started this conversation.</p></div></div></section> : isNew ? <section className="new-discussion-content"><div className="new-discussion-inner">
      <div className="new-question-intro"><h2>{isChat ? 'What can I help with?' : 'What should we think through?'}</h2>{!isChat && <p>Bring a question. Get perspectives from your OpenAI council.</p>}</div>
      {notice && <p className="new-conversation-notice" role="status">{notice}</p>}
      {composerError && <p className="composer-error" role="alert">{composerError}</p>}
      {composerForm}
      {modelUnavailable && config && <p className="composer-error model-unavailable" role="alert">{config.model_options?.length ? 'Choose an available OpenAI model above to continue.' : 'No OpenAI models are available. Check your workspace configuration.'}</p>}
      {!isChat && <details className="new-panel-wrap" open><summary>Council settings <ChevronDown size={14} /></summary><PanelSetup config={config} configError={configError} settings={settings} onChange={setOverrides} returnTo={returnTo} /></details>}
      <div className="question-starters" aria-label="Prompt suggestions">{STARTERS.map((starter) => <button key={starter.tag} type="button" onClick={() => applyStarter(starter.prompt)}><starter.icon size={15} />{starter.tag}</button>)}</div>
      {running && !isCurrentRun && <p className="another-run-note">Another conversation is running. Your draft is saved here while it finishes.</p>}
      <p className="mode-explainer">{isChat ? 'One model. A conversation that follows your lead.' : 'Each perspective is powered by OpenAI. You can join between rounds.'}</p>
    </div></section> : <>
      <div className="messages-container" ref={messagesRef} onScroll={(event) => {
        const { scrollHeight, scrollTop, clientHeight } = event.currentTarget;
        followLatest.current = scrollHeight - scrollTop - clientHeight < 100;
        setShowJump(!followLatest.current);
      }}><div className="message-column">{conversation.messages.map((message, index) => <div key={index} className={`message-group ${message.role === 'user' ? 'human-message-group' : ''}`}>{message.role === 'user' ? <div className="user-message"><span className="sr-only">{isOwner ? 'You' : conversation.owner_username}</span><div className="message-content markdown-content"><ReactMarkdown>{message.content}</ReactMarkdown></div></div> : message.mode === 'chat' ? <ChatMessage msg={message} running={currentRunning && index === conversation.messages.length - 1} /> : <AssistantMessage msg={message} />}</div>)}</div></div>
      {showJump && <button type="button" className="jump-latest" onClick={jumpToLatest}><ArrowDown size={16} /> Latest response</button>}
      {isOwner && <div className={`composer ${waiting ? 'composer-your-turn' : ''}`}>
        <div className="composer-inner">
          {waiting && <div className="human-turn"><div className="human-turn-heading"><span className="your-turn-icon"><MessageCircle size={16} /></span><strong>Your turn</strong><InputCountdown key={waiting.deadline} deadline={waiting.deadline} /></div><p>Send a thought or continue without a comment. The council resumes when the timer ends.</p></div>}
          {composerError && <div className="composer-error" role="alert">{composerError}</div>}
          {snapshotNeedsMigration && !currentRunning && <p className="model-migration-note">Your council will use available OpenAI models for the next turn.</p>}
          {modelUnavailable && config && <p className="composer-error" role="alert">Choose an available OpenAI model above to continue.</p>}
          {composerForm}
          {!isChat && <div className="composer-options">{waiting ? <button type="button" className="skip-input-button" disabled={submitting || inputBusy} onClick={() => onInput('', true)}>Continue without a comment <ArrowRight size={12} /></button> : !running && <><label className="pause-option"><input type="checkbox" checked={settings.pauseForInput} onChange={(event) => setOverrides({ ...settings, pauseForInput: event.target.checked })} />Wait for me between rounds</label><details className="followup-panel"><summary><span>Panel settings for the next turn</span><ChevronDown size={12} /></summary><PanelSetup config={config} configError={configError} settings={settings} onChange={setOverrides} returnTo={returnTo} snapshot={panelSnapshot} /></details></>}</div>}
          {running && !currentRunning && <p className="another-run-note">Another conversation is running. You can send this draft when it finishes.</p>}
          {isChat && currentRunning && !isCurrentRun && <p className="another-run-note">This response is running in another tab. Updates appear here automatically.</p>}
          <p className="composer-footnote">AI can make mistakes. Check important information.</p>
        </div>
      </div>}
    </>}
  </main>;
}

function ModelPicker({ config, settings, onChange, disabled }) {
  const options = config?.model_options || [];
  const value = settings.model ? JSON.stringify([settings.provider, settings.model]) : '';
  const available = options.some((option) => option.provider === settings.provider && option.model === settings.model);
  return <label className="chat-model-picker"><span className="sr-only">Chat model</span><select aria-label="Chat model" value={value} disabled={disabled || !options.length} onChange={(event) => { const [provider, model] = JSON.parse(event.target.value); onChange({ provider, model }); }}>
    {!available && <option value={value} disabled>{settings.model ? `${modelLabel(settings.model)} · unavailable` : config ? 'No model available' : 'Loading models…'}</option>}
    {options.map((option) => <option key={`${option.provider}:${option.model}`} value={JSON.stringify([option.provider, option.model])}>{modelLabel(option.model)}{options.some((other) => other.model === option.model && other.provider !== option.provider) ? ` · ${option.provider}` : ''}</option>)}
  </select><ChevronDown size={13} aria-hidden="true" /></label>;
}

function ChatMessage({ msg, running }) {
  const response = msg.final?.response || msg.content || '';
  return <article className="assistant-message direct-response" aria-label="AI response">
    <div className="direct-response-heading"><Brand compact /><span>{modelLabel(msg.config?.model || msg.final?.model) || 'AI Council'}</span></div>
    {response && <div className="markdown-content chat-response"><ReactMarkdown>{response}</ReactMarkdown></div>}
    {running && !response && !msg.error && <div className="chat-thinking" role="status"><span className="spinner" /> Thinking…</div>}
    {running && response && <span className="response-streaming" role="status">Responding…</span>}
    {msg.stopped && <p className="response-note" role="status">Response stopped.</p>}
    {msg.error && <div className="stage-error" role="alert"><strong>Response interrupted</strong><p>{msg.error}</p>{response && <span>Your partial response is saved above.</span>}</div>}
    {response && !running && <div className="response-actions"><CopyButton text={response} /></div>}
  </article>;
}

function AssistantMessage({ msg }) {
  const [startedLive] = useState(!msg.final);
  const [evidenceOpen, setEvidenceOpen] = useState(!msg.final);
  const cfg = msg.config;
  const seatNames = Object.fromEntries((cfg?.seats || []).map((seat) => [seat.id, seat.name]));
  const rounds = msg.rounds || [];
  const stage = msg.waiting_for_input ? 'Waiting for your perspective' : msg.loading?.final ? 'Bringing the perspectives together' : msg.loading?.round === 0 ? 'Forming independent perspectives' : msg.loading?.round > 0 ? `Working through round ${msg.loading.round}` : null;
  const roundContent = <>{rounds.map((round) => <div key={round.round}><Round round={round} seatNames={seatNames} members={cfg?.seats || []} />{(msg.human_inputs || []).filter((thought) => thought.after_round === round.round).map((thought, index) => <div className="human-contribution user-message" key={`${thought.created_at}-${index}`}><div className="message-label"><span className="human-avatar"><UserRound size={13} /></span>You<span className="message-context">Added after {round.round === 0 ? 'opening perspectives' : `round ${round.round}`}</span></div><div className="message-content markdown-content"><ReactMarkdown>{thought.content}</ReactMarkdown></div></div>)}</div>)}</>;
  const completed = Boolean(msg.final);
  return <div className="assistant-message">
    <div className="council-message-heading"><div className="avatar-stack">{(cfg?.seats || []).slice(0, 4).map((seat, index) => <Avatar key={seat.id} member={seat} index={index} size={23} />)}</div><span><strong>{cfg ? panelLabel(cfg) : 'Your council'}</strong><small>{cfg?.is_followup ? 'Considering your new perspective' : 'Different minds, a fuller picture'}</small></span>{completed && <span className="turn-complete"><Check size={12} /> Complete</span>}</div>
    {stage && <div className={`stage-loading ${msg.waiting_for_input ? 'awaiting' : ''}`} role="status">{msg.waiting_for_input ? <MessageCircle size={18} /> : <div className="spinner" />}<div><strong>{stage}</strong><span>{msg.waiting_for_input ? 'Add a thought below to shape the next round.' : 'Some models take a few minutes. You can keep reading or draft your thoughts.'}</span></div></div>}
    {completed && !startedLive && <Final final={msg.final} chairman={cfg?.chairman} labelToSeat={rounds.at(-1)?.label_to_seat} seatNames={seatNames} />}
    <section className="debate-evidence"><button className="evidence-toggle" type="button" aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen(!evidenceOpen)} disabled={!rounds.length}><span><MessageSquare size={15} /><strong>Explore the discussion</strong><small>{rounds.length} round{rounds.length === 1 ? '' : 's'} · {cfg?.seats.length || 0} perspectives{msg.human_inputs?.length ? ` · ${msg.human_inputs.length} of your thoughts` : ''}</small></span><ChevronDown size={16} /></button>{evidenceOpen && roundContent}</section>
    {completed && startedLive && <Final final={msg.final} chairman={cfg?.chairman} labelToSeat={rounds.at(-1)?.label_to_seat} seatNames={seatNames} />}
    {msg.error && <div className="stage-error" role="alert"><strong>The discussion needs attention</strong><p>{msg.error}</p><span>Your saved responses are still here. You can add a follow-up below.</span></div>}
  </div>;
}

function InputCountdown({ deadline }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const seconds = Math.max(0, Math.ceil((Date.parse(deadline) - now) / 1000));
  return <span className="input-countdown"><Clock3 size={12} />{seconds > 0 ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} left` : 'Continuing…'}</span>;
}
