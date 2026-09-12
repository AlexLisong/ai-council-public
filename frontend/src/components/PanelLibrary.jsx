import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ArrowUpRight, Check, CircleAlert, Crown, Layers3, Plus, Search, SlidersHorizontal, UsersRound, X } from 'lucide-react';
import { panelHref } from '../routes';
import { panelLabel } from '../presentation';
import Avatar from './Avatar';
import { resolveAvatar } from '../avatars';
import './PanelLibrary.css';

const PERSPECTIVES = {
  skeptic: 'Challenge assumptions', builder: 'Make it practical', historian: 'Learn from the past',
  systems: 'Connect the dots', chairman: 'Bring it together', analyst: 'Follow the evidence',
  visionary: 'Explore possibilities', mediator: 'Find common ground',
};

function description(preset) {
  if (preset.key === 'foundry-mixed') return 'Two OpenAI models, four ways of thinking. A balanced council for your most considered questions.';
  if (preset.key === 'single-model-personas') return 'One model, three distinct lenses. Explore how a different perspective changes the answer.';
  if (preset.key === 'openai-direct') return 'The same council on the public OpenAI API. Available once an OpenAI API key is configured.';
  return preset.description || 'Distinct perspectives, working through one question together.';
}

function PanelAvatars({ preset, size = 36 }) {
  const members = [...preset.seats.map((member, index) => ({ member, index })), { member: preset.chairman, chairman: true, index: 0 }];
  return <div className="library-avatar-stack" aria-label={`${members.length} panel members`}>
    {members.slice(0, 5).map((item, index) => <Avatar key={index} {...item} size={size} />)}
    {members.length > 5 && <span className="library-avatar-extra">+{members.length - 5}</span>}
  </div>;
}

function PanelCard({ preset, busy, onUsePanel }) {
  return <article className={`library-panel${preset.is_personal ? ' is-personal' : ''}`}>
    <div className="library-panel-top"><PanelAvatars preset={preset} /><span className="library-panel-kind">{preset.is_personal ? 'Personal panel' : 'Template'}</span></div>
    <h3>{panelLabel(preset)}</h3>
    {preset.is_personal
      ? <p className="library-seat-names">{preset.seats.map((seat) => seat.name).join(' · ')}</p>
      : <p className="library-panel-description">{description(preset)}</p>}
    <div className="library-panel-details"><UsersRound size={13} aria-hidden="true" /><span>{preset.seats.length} discussion seat{preset.seats.length === 1 ? '' : 's'}</span><span className="library-detail-divider" /><Crown size={12} aria-hidden="true" /><span>Chairman included</span></div>
    {!preset.available && <p className="panel-unavailable-notice"><CircleAlert size={14} aria-hidden="true" />{preset.is_personal ? 'A model needs attention. Edit this panel before using it.' : 'Some models are unavailable. Customize to choose alternatives.'}</p>}
    <div className="library-panel-actions">
      <Link to={panelHref(preset)} className="panel-edit-button"><SlidersHorizontal size={14} aria-hidden="true" />{preset.is_personal ? 'Edit panel' : 'Customize panel'}</Link>
      <button type="button" disabled={busy || !preset.available} onClick={() => onUsePanel(preset.key)}>Start discussion <ArrowUpRight size={15} aria-hidden="true" /></button>
    </div>
  </article>;
}

export default function PanelLibrary({ config, error, onUsePanel, busy }) {
  const [search, setSearch] = useState('');
  if (!config) return <main className="view-page panel-library"><div className="panel-library-shell"><p className="library-eyebrow">YOUR COUNCIL LIBRARY</p><h1>Panels</h1><div className="library-loading"><Layers3 size={28} aria-hidden="true" /><p role={error ? 'alert' : 'status'}>{error || 'Loading your panels…'}</p></div></div></main>;
  const personal = config.presets.filter((preset) => preset.is_personal);
  const templates = config.presets.filter((preset) => !preset.is_personal);
  const featured = templates.find((preset) => preset.key === config.default_preset) || templates[0];
  const otherTemplates = templates.filter((preset) => preset.key !== featured?.key);
  const createHref = `/panels/new?${new URLSearchParams({ template: featured?.key || config.default_preset, seat: '0' })}`;
  const query = search.trim().toLowerCase();
  const filtered = personal.filter((preset) => `${preset.title} ${preset.seats.map((seat) => seat.name).join(' ')}`.toLowerCase().includes(query));
  const cards = (presets) => <div className="panel-library-grid">{presets.map((preset) => <PanelCard key={preset.key} preset={preset} busy={busy} onUsePanel={onUsePanel} />)}</div>;
  return <main className="view-page panel-library">
    <div className="panel-library-shell">
      <header className="library-page-header">
        <div><p className="library-eyebrow">YOUR COUNCIL LIBRARY</p><h1>Panels</h1><p>Different minds. A more considered answer.<br className="library-intro-break" /> Find your council, or make one your own.</p></div>
        <Link className="library-create-button" to={createHref}><Plus size={17} aria-hidden="true" /> Create panel</Link>
      </header>
      {error && <p className="library-error" role="alert"><CircleAlert size={16} aria-hidden="true" />{error}</p>}
      {featured && <section className="library-featured" aria-labelledby="featured-panel-title">
        <div className="library-featured-header"><div><span className="library-featured-label"><span /> A THOUGHTFUL PLACE TO START</span><h2 id="featured-panel-title">{panelLabel(featured)}</h2><p>{description(featured)}</p></div><span className="library-included-label"><Check size={13} aria-hidden="true" /> Ready to customize</span></div>
        <div className="library-featured-members">
          {[...featured.seats.map((member, index) => ({ member, index })), { member: featured.chairman, index: 0, chairman: true }].map((item, index) => <figure className={`library-featured-member${item.chairman ? ' is-chairman' : ''}`} key={index}>
            <Avatar {...item} size={68} />
            <figcaption><strong>{item.member.name || (item.chairman ? 'Chairman' : `Seat ${index + 1}`)}</strong><span>{PERSPECTIVES[resolveAvatar(item.member, item.index, item.chairman)] || 'A distinct perspective'}</span></figcaption>
          </figure>)}
        </div>
        <div className="library-featured-footer"><p><Crown size={14} aria-hidden="true" /> Every voice is heard. The Chairman brings it together.</p><div className="library-featured-actions"><Link to={panelHref(featured)}>Customize panel <SlidersHorizontal size={14} aria-hidden="true" /></Link><button type="button" disabled={busy || !featured.available} onClick={() => onUsePanel(featured.key)}>Start discussion <ArrowRight size={16} aria-hidden="true" /></button></div></div>
        {!featured.available && <p className="panel-unavailable-notice featured-unavailable"><CircleAlert size={14} aria-hidden="true" />Some models are unavailable. Customize this panel to choose alternatives.</p>}
      </section>}
      <section className="library-personal-section" aria-labelledby="my-panels-title">
        <div className="library-section-heading"><div><h2 id="my-panels-title">My panels <span>{personal.length}</span></h2><p>Your perspectives, saved for the next question.</p></div>{personal.length > 2 && <div className="library-search"><Search size={15} aria-hidden="true" /><input aria-label="Search your panels" placeholder="Find a panel…" value={search} onChange={(event) => setSearch(event.target.value)} />{search && <button type="button" aria-label="Clear panel search" onClick={() => setSearch('')}><X size={14} aria-hidden="true" /></button>}</div>}</div>
        {!personal.length ? <div className="library-empty">
          <div className="library-empty-portraits">{featured ? <PanelAvatars preset={featured} size={32} /> : <UsersRound size={30} aria-hidden="true" />}</div>
          <div><h3>Make the council your own.</h3><p>Choose the voices, shape their perspectives, and save a panel you can return to.</p></div>
          <Link to={createHref}>Create your first panel <ArrowRight size={15} aria-hidden="true" /></Link>
        </div> : filtered.length ? cards(filtered) : <div className="library-search-empty"><Search size={22} aria-hidden="true" /><p>No panels match “{search}”.</p><button type="button" onClick={() => setSearch('')}>Show all my panels</button></div>}
      </section>
      {otherTemplates.length > 0 && <section className="library-template-section" aria-labelledby="template-panels-title"><div className="library-section-heading"><div><h2 id="template-panels-title">More ways to think</h2><p>Start with a template. Give it your own point of view.</p></div><span className="library-template-label"><Layers3 size={13} aria-hidden="true" /> TEMPLATES</span></div>{cards(otherTemplates)}</section>}
    </div>
  </main>;
}
