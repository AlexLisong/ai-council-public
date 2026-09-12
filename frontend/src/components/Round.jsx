import { useId, useRef, useState } from 'react';
import { ChevronDown, Info } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import Avatar from './Avatar';
import CopyButton from './CopyButton';
import { modelLabel } from '../presentation';
import './Round.css';

function stripFooter(text) { return text.split('\n').filter((line) => !/^\s*\**\s*(POSITION SUMMARY|VERDICT|DISAGREEMENTS)\s*\**\s*:/i.test(line)).join('\n').trimEnd(); }
function deAnonymize(text, labelToSeat, seatNames) {
  let result = text;
  for (const [label, seatId] of Object.entries(labelToSeat || {})) if (seatNames[seatId]) result = result.split(label).join(`**${seatNames[seatId]}**`);
  return result;
}
export default function Round({ round, seatNames, members = [] }) {
  const [activeTab, setActiveTab] = useState(0);
  const id = useId();
  const tabs = useRef(null);
  if (!round || !round.entries?.length) return null;
  const opening = round.round === 0;
  const selected = Math.min(activeTab, round.entries.length - 1);
  const entry = round.entries[selected];
  const convergence = round.convergence;
  const memberFor = (item) => members.find((member) => member.id === item.seat_id) || item;
  const indexFor = (item) => Math.max(0, members.findIndex((member) => member.id === item.seat_id));
  const moveTab = (event) => {
    let next;
    if (event.key === 'ArrowRight') next = (selected + 1) % round.entries.length;
    if (event.key === 'ArrowLeft') next = (selected + round.entries.length - 1) % round.entries.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = round.entries.length - 1;
    if (next !== undefined) { event.preventDefault(); setActiveTab(next); tabs.current?.children[next]?.focus(); }
  };
  return <section className={`stage round ${opening ? 'opening' : ''}`} aria-label={opening ? 'Opening perspectives' : `Discussion round ${round.round}`}>
    <div className="round-header"><div className="round-heading-title"><span className="round-number">{opening ? '01' : String(round.round + 1).padStart(2, '0')}</span><h3 className="stage-title">{opening ? 'Opening perspectives' : `Discussion · Round ${round.round}`}</h3></div>{convergence && <span className={`convergence-pill ${convergence.reached ? 'reached' : ''}`} title={`${convergence.needed} members needed to finish`}>{convergence.converged} of {convergence.total} aligned</span>}</div>
    {round.missing?.length > 0 && <p className="stage-warning">No response this round: {round.missing.join(', ')}. Their previous position is retained.</p>}
    {convergence?.no_verdict?.length > 0 && <p className="stage-warning">No agreement verdict received from {convergence.no_verdict.join(', ')}.</p>}
    <div className="tabs" ref={tabs} role="tablist" aria-label={opening ? 'Opening speakers' : `Round ${round.round} speakers`} onKeyDown={moveTab}>{round.entries.map((item, index) => <button key={item.seat_id} id={`${id}-tab-${index}`} role="tab" tabIndex={index === selected ? 0 : -1} aria-selected={index === selected} aria-controls={`${id}-content`} className={`tab ${index === selected ? 'active' : ''}`} onClick={() => setActiveTab(index)}><Avatar member={memberFor(item)} index={indexFor(item)} size={30} /><span>{item.name}</span>{item.verdict && <span className={`verdict-dot ${item.verdict.toLowerCase()}`} title={item.verdict === 'CONVERGED' ? 'Aligned' : 'Still open'} />}</button>)}</div>
    <div className="tab-content" role="tabpanel" id={`${id}-content`} aria-labelledby={`${id}-tab-${selected}`} tabIndex={0}>
      <div className="entry-meta"><div><span className="entry-model" title={`${entry.provider} · ${entry.model}${entry.replaced_model ? ` (replaces ${entry.replaced_model})` : ''}`}>{modelLabel(entry.model)}</span>{entry.verdict && <span className={`verdict-badge ${entry.verdict.toLowerCase()}`}>{entry.verdict === 'CONVERGED' ? 'Aligned' : 'Still open'}</span>}</div><CopyButton text={deAnonymize(stripFooter(entry.response), round.label_to_seat, seatNames)} label="Copy response" /></div>
      {entry.summary && <div className="entry-summary"><span className="eyebrow">The position</span><p>{entry.summary}</p></div>}
      {entry.disagreements?.length > 0 && <div className="entry-disagreements"><strong>Still open</strong><span>{entry.disagreements.join('; ')}</span></div>}
      <div className="response-text markdown-content"><ReactMarkdown>{deAnonymize(stripFooter(entry.response), round.label_to_seat, seatNames)}</ReactMarkdown></div>
    </div>
    {!opening && <details className="round-method"><summary><Info size={12} /> How this round works <ChevronDown size={12} /></summary><p>Each AI reviews the other perspectives anonymously, then challenges or revises its position. Names are added here for readability.</p></details>}
  </section>;
}
