import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ArrowUpRight, LayoutGrid, LogOut, Menu, Search, SquarePen, Trash2, Users, UsersRound, X } from 'lucide-react';
import { debateHref } from '../routes';
import Brand from './Brand';
import './Sidebar.css';

export default function Sidebar({ user, scope, onLogout, conversations, currentConversationId, onNewConversation, onDeleteConversation, busy, runningConversationId, open, onToggle, onNavigate }) {
  const isAdmin = user.role === 'admin';
  const location = useLocation();
  const isPanels = location.pathname.startsWith('/panels');
  const isHistory = new URLSearchParams(location.search).get('view') === 'history';
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 700px)').matches);
  const drawerRef = useRef(null);
  const toggleRef = useRef(null);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 700px)');
    const change = () => setMobile(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (!mobile || !open) return;
    // The drawer is transitioning in from offscreen. Normal focus can scroll the
    // document sideways to its old position and leave the entire app clipped.
    const frame = requestAnimationFrame(() => {
      drawerRef.current?.querySelector('button')?.focus({ preventScroll: true });
    });
    const trigger = toggleRef.current;
    return () => {
      cancelAnimationFrame(frame);
      trigger?.focus({ preventScroll: true });
    };
  }, [mobile, open]);
  useEffect(() => {
    if (!mobile || !open) return;
    const escape = (event) => {
      if (event.key === 'Escape') { event.preventDefault(); onToggle(); }
    };
    document.addEventListener('keydown', escape);
    return () => document.removeEventListener('keydown', escape);
  }, [mobile, open, onToggle]);
  const recent = conversations.slice(0, 30);
  for (const id of [currentConversationId, runningConversationId]) {
    const active = conversations.find((conversation) => conversation.id === id);
    if (active && !recent.some((conversation) => conversation.id === id)) recent.unshift(active);
  }
  const drawerKeys = (event) => {
    if (!mobile || !open) return;
    if (event.key !== 'Tab') return;
    const items = [...drawerRef.current.querySelectorAll('a[href], button:not(:disabled)')].filter((item) => item.getClientRects().length);
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
    else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus(); }
  };
  return <>
    <div className="mobile-toolbar"><button ref={toggleRef} className="icon-button" aria-label="Open sidebar" aria-expanded={open} aria-controls="app-sidebar" onClick={onToggle}><Menu size={21} /></button><Link to="/debates" aria-label="AI Council home" onClick={onNavigate}><Brand /></Link><button className="icon-button" aria-label="New chat" onClick={onNewConversation} disabled={busy}><SquarePen size={20} /></button></div>
    {open && mobile && <div className="sidebar-backdrop" onClick={onToggle} aria-hidden="true" />}
    <aside id="app-sidebar" ref={drawerRef} className="sidebar" inert={mobile && !open ? true : undefined} role={mobile && open ? 'dialog' : undefined} aria-modal={mobile && open ? true : undefined} aria-label={mobile && open ? 'Navigation' : 'Sidebar'} onKeyDown={drawerKeys} onTransitionEnd={(event) => {
      if (mobile && open && event.target === event.currentTarget && !event.currentTarget.contains(document.activeElement)) {
        event.currentTarget.querySelector('button')?.focus({ preventScroll: true });
      }
    }}>
      <div className="sidebar-header">
        <div className="sidebar-brand-row"><Link to="/debates" className="brand-link" aria-label="AI Council home" onClick={onNavigate}><Brand /></Link><button className="icon-button sidebar-close" aria-label="Close sidebar" onClick={onToggle}><X size={20} /></button></div>
        <button className="new-conversation-btn" onClick={onNewConversation} disabled={busy}><SquarePen size={18} /> <span>New chat</span></button>
        <nav className="main-navigation" aria-label="Main navigation">
          <Link to="/debates?view=history" aria-current={isHistory && scope === 'mine' ? 'page' : undefined} onClick={onNavigate}><Search size={18} /><span>Search chats</span></Link>
          <Link to="/panels" aria-current={isPanels ? 'page' : undefined} onClick={onNavigate}><LayoutGrid size={18} /><span>Council panels</span></Link>
          {isAdmin && <Link to="/debates?scope=all" aria-current={!isPanels && scope === 'all' ? 'page' : undefined} onClick={onNavigate}><Users size={18} /><span>All users</span></Link>}
        </nav>
        {runningConversationId && <Link className="active-discussion-link" to={debateHref(runningConversationId)} onClick={onNavigate}><span className="live-dot" /><span>Response in progress</span><ArrowUpRight size={14} /></Link>}
      </div>
      <div className="conversation-list">
        <div className="sidebar-section-label">{scope === 'all' ? 'Workspace chats' : 'Your chats'}</div>
        {conversations.length === 0 ? <p className="no-conversations">Your conversations will appear here.</p> : recent.map((conversation) => (
          <div key={conversation.id} className={'conversation-item ' + (conversation.id === currentConversationId ? 'active' : '')}>
            <Link to={debateHref(conversation.id, { scope })} onClick={onNavigate} className="conversation-title" aria-current={conversation.id === currentConversationId ? 'page' : undefined} title={`${conversation.title} · ${conversation.mode === 'chat' ? 'Chat' : 'Council'}`}>
              {runningConversationId === conversation.id && <span className="live-dot" aria-label="Running" />}
              {conversation.mode !== 'chat' && <UsersRound size={13} aria-label="Council" className="history-mode-icon" />}
              <span>{conversation.title === 'New Conversation' ? conversation.mode === 'chat' ? 'New chat' : 'New council conversation' : conversation.title}</span>
              {scope === 'all' && <small>{conversation.owner_username}</small>}
            </Link>
            {conversation.owner_id === user.id && <button className="delete-btn" aria-label={'Delete ' + conversation.title} title="Delete conversation" onClick={() => {
              if (window.confirm('Delete this conversation? This cannot be undone.')) onDeleteConversation(conversation.id);
            }}><Trash2 size={14} /></button>}
          </div>
        ))}
        {conversations.length > 30 && <Link className="all-discussions-link" to={scope === 'all' ? '/debates?scope=all' : '/debates?view=history'} onClick={onNavigate}>View all chats <ArrowUpRight size={13} /></Link>}
      </div>
      <div className="sidebar-footer">
        <span className="account-avatar" aria-hidden="true">{user.username.slice(0, 2).toUpperCase()}</span>
        <div className="account-details"><strong>{user.username}</strong><small>{isAdmin ? 'Admin workspace' : 'Personal workspace'}</small></div>
        <button className="logout-btn" onClick={onLogout} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
      </div>
    </aside>
  </>;
}
