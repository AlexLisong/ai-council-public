import { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';

export default function CopyButton({ text, label = 'Copy answer', className = '' }) {
  const [status, setStatus] = useState('');
  const timer = useRef();
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setStatus('Copied');
    } catch { setStatus('Copy unavailable'); }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus(''), 2500);
  };
  return <button type="button" className={`quiet-button ${className}`} onClick={copy} aria-label={status || label} title={status || label}>
    {status === 'Copied' ? <Check size={16} /> : <Copy size={16} />}<span aria-live="polite">{status || label}</span>
  </button>;
}
