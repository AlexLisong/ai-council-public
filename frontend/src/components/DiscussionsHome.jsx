import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, MessageSquare, Search, SquarePen, UsersRound, X } from 'lucide-react';
import { debateHref } from '../routes';
import { relativeDate } from '../presentation';
import './DiscussionsHome.css';

export default function DiscussionsHome({ conversations, scope, onNew, busy, loading, error, onRetry }) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const visible = conversations.filter((item) => (filter === 'all' || (item.mode || 'council') === filter) && `${item.title} ${scope === 'all' ? item.owner_username : ''}`.toLowerCase().includes(search.toLowerCase()));
  return <main className="view-page discussions-home">
    <section className="discussion-history">
      <header className="history-heading"><div><h1>{scope === 'all' ? 'Workspace conversations' : 'Your conversations'}</h1><p>Find a chat or pick up a council discussion.</p></div><button className="secondary-button" onClick={onNew} disabled={busy}><SquarePen size={16} /> New chat</button></header>
      <label className="search-field"><Search size={18} /><input aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={(event) => setSearch(event.target.value)} />{search && <button onClick={() => setSearch('')} aria-label="Clear search"><X size={16} /></button>}</label>
      <div className="history-filters" role="group" aria-label="Filter conversations">{[{ id: 'all', label: 'All' }, { id: 'chat', label: 'Chat' }, { id: 'council', label: 'Council' }].map(({ id, label }) => <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}</div>
      {error ? <div className="history-empty" role="alert"><p>{error}</p><button className="secondary-button" onClick={onRetry}>Try again</button></div> : loading ? <div className="history-empty" role="status">Loading your conversations…</div> : visible.length ? <ul className="debate-home-list">{visible.map((item) => <li key={item.id}><Link to={debateHref(item.id, { scope })}><span className="history-row-icon">{item.mode === 'chat' ? <MessageSquare size={19} /> : <UsersRound size={19} />}</span><span className="history-row-copy"><strong>{item.title === 'New Conversation' ? item.mode === 'chat' ? 'New chat' : 'New council conversation' : item.title}</strong><small>{scope === 'all' ? `${item.owner_username} · ` : ''}{item.mode === 'chat' ? 'Chat' : 'Council'} · {item.message_count === 0 ? 'Draft' : `${Math.floor(item.message_count / 2)} turn${item.message_count > 2 ? 's' : ''}`}</small></span><span className="history-row-date">{relativeDate(item.created_at)}</span><ArrowUpRight size={17} className="history-row-arrow" /></Link></li>)}</ul> : <div className="history-empty"><MessageSquare size={24} /><h2>{search ? 'No matching conversations' : 'No conversations yet'}</h2><p>{search ? 'Try another title or clear your search.' : 'Your chats and council discussions will appear here.'}</p>{!search && <button className="secondary-button" onClick={onNew} disabled={busy}>Start a chat</button>}</div>}
    </section>
  </main>;
}
