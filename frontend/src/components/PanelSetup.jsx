import { Link } from 'react-router-dom';
import { ChevronDown, SlidersHorizontal, UserRoundPlus } from 'lucide-react';
import { panelHref } from '../routes';
import { modelLabel, panelLabel } from '../presentation';
import Avatar from './Avatar';
import './PanelSetup.css';

const CONSENSUS_OPTIONS = [{ value: 'all', label: 'Everyone agrees' }, { value: 'majority', label: 'A majority agrees' }, { value: '2/3', label: 'Two thirds agree' }];
function clampRounds(raw) { const n = parseInt(raw, 10); return Number.isNaN(n) ? 1 : Math.min(10, Math.max(0, n)); }
function panelSignature(panel) {
  const member = (seat) => [seat.name || 'Chairman', seat.provider, seat.model, seat.persona || '', seat.avatar || null];
  return JSON.stringify([panel.title, panel.seats.map(member), member(panel.chairman)]);
}

export default function PanelSetup({ config, configError, settings, onChange, returnTo, snapshot }) {
  if (configError) return <div className="panel-setup error" role="alert">Panel settings are unavailable. Use Retry below to reconnect.</div>;
  if (!config) return <div className="panel-setup" role="status">Getting your council ready…</div>;
  const selected = config.presets.find((preset) => preset.key === settings.preset || preset.aliases?.includes(settings.preset));
  if (!selected) return <div className="panel-setup error">This panel is unavailable. <Link to="/panels">Choose a panel</Link>.</div>;
  const preset = snapshot ? { ...selected, title: snapshot.preset_title, seats: snapshot.seats, chairman: snapshot.chairman } : selected;
  const destination = new URL(returnTo, window.location.origin);
  if (destination.searchParams.has('panel')) destination.searchParams.set('panel', settings.preset);
  const editorReturnTo = `${destination.pathname}${destination.search}`;
  const hasSavedUpdates = snapshot && panelSignature(preset) !== panelSignature(selected);
  return <section className="panel-setup" aria-label="Discussion panel">
    <div className="setup-toolbar">
      <div className="setup-panel-choice"><span className="eyebrow">At your table</span><label><span className="sr-only">Panel</span><select value={preset.key} onChange={(event) => onChange({ ...settings, preset: event.target.value, useLatestPanel: true })}>{config.presets.map((item) => <option key={item.key} value={item.key} disabled={!item.available && !item.is_personal}>{panelLabel(item)}{item.available ? '' : ' · unavailable'}</option>)}</select></label></div>
      <Link className="panel-edit-button" to={panelHref(selected, { returnTo: editorReturnTo })}><SlidersHorizontal size={13} />{preset.is_personal ? 'Edit panel' : 'Customize panel'}</Link>
    </div>
    <div className="panel-roster" aria-label="Panel members">{[...preset.seats.map((member, index) => ({ member, index, seat: String(index) })), { member: preset.chairman, index: 0, seat: 'chairman' }].map(({ member, index, seat }) => <Link key={seat} className={seat === 'chairman' ? 'chairman-chip' : ''} to={panelHref(selected, { returnTo: editorReturnTo, seat })} title={`${member.name || 'Chairman'} · ${modelLabel(member.model)}`}><Avatar member={member} index={index} chairman={seat === 'chairman'} size={37} /><span><strong>{member.name || 'Chairman'}</strong><small>{seat === 'chairman' ? 'Brings it all together' : modelLabel(member.model)}{member.replaced_model && <em className="replaced-note" title={`Originally ${member.replaced_model}; that model is no longer offered`}> · replaces {modelLabel(member.replaced_model)}</em>}</small></span></Link>)}</div>
    {hasSavedUpdates && <div className="panel-update-notice"><span>Your saved panel has updates.</span><button type="button" className="panel-edit-button" onClick={() => onChange({ ...settings, useLatestPanel: true })}>Use saved updates</button></div>}
    {!selected.available && selected.is_personal && <p className="panel-unavailable-notice">A model is unavailable. Edit this panel to choose a replacement.</p>}
    <div className="setup-preferences">
      <label className="pause-option setup-pause-option"><input type="checkbox" checked={settings.pauseForInput} onChange={(event) => onChange({ ...settings, pauseForInput: event.target.checked })} /><UserRoundPlus size={14} /><span>Let me join between rounds <small>5-minute window</small></span></label>
      <details className="discussion-settings"><summary><SlidersHorizontal size={13} /> Discussion settings <ChevronDown size={12} /></summary><div className="setup-advanced"><label>Max debate rounds<input type="number" aria-label="Max debate rounds" min={0} max={10} value={settings.maxRounds} onChange={(event) => onChange({ ...settings, maxRounds: clampRounds(event.target.value) })} /><small>0 = opening perspectives only</small></label><label>Stop when<select aria-label="Stop when" value={settings.consensus} onChange={(event) => onChange({ ...settings, consensus: event.target.value })}>{CONSENSUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select><small>Or when the round limit is reached</small></label></div></details>
    </div>
  </section>;
}
