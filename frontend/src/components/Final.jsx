import { Check, GitBranch } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import Avatar from './Avatar';
import CopyButton from './CopyButton';
import { modelLabel } from '../presentation';
import './Final.css';

function deAnonymize(text, labelToSeat, seatNames) {
  let result = text;
  for (const [label, seatId] of Object.entries(labelToSeat || {})) if (seatNames[seatId]) result = result.split(label).join(seatNames[seatId]);
  return result;
}
export default function Final({ final, chairman, labelToSeat, seatNames = {} }) {
  if (!final) return null;
  const noDebate = final.rounds_run === 0;
  return <section className={`stage final ${final.converged ? 'converged' : 'open'}`} aria-label="Council synthesis">
    <header className="final-heading"><Avatar member={chairman || { name: final.chairman_name }} chairman size={43} /><div><span className="eyebrow">The big picture</span><h3>Council synthesis</h3></div><CopyButton text={final.response} label="Copy answer" /></header>
    <div className="final-response"><div className="chairman-label"><strong>{final.chairman_name || 'Chairman'}</strong><span>·</span><span>{modelLabel(final.model)}</span></div><div className="final-text markdown-content"><ReactMarkdown>{final.response}</ReactMarkdown></div>
      {final.never_answered?.length > 0 && <div className="unresolved"><strong>Missing perspectives</strong><p>These members did not respond and are absent from this synthesis: {final.never_answered.join(', ')}.</p></div>}
      {final.unresolved?.length > 0 && <div className="unresolved"><strong><GitBranch size={13} /> Where views still differ</strong><ul>{final.unresolved.map((disagreement, index) => <li key={index}>{deAnonymize(disagreement, labelToSeat, seatNames)}</li>)}</ul></div>}
    </div>
    <footer className="final-footer"><span className={`status-pill ${final.converged ? 'converged' : 'open'}`}>{final.converged ? <Check size={12} /> : <GitBranch size={12} />}{final.converged ? 'Common ground reached' : noDebate ? 'Independent perspectives' : 'Different views remain'}</span><span>{noDebate ? 'Opening perspectives only' : `${final.rounds_run} discussion round${final.rounds_run === 1 ? '' : 's'}`}</span></footer>
  </section>;
}
