export default function Brand({ compact = false, light = false }) {
  return <span className={`brand${light ? ' brand-light' : ''}`}>
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M16 4.5a11.5 11.5 0 1 0 11.5 11.5" stroke="currentColor" strokeWidth="2" />
      <circle cx="16" cy="16" r="5" fill="currentColor" />
      <circle cx="25.5" cy="6.5" r="4" fill="currentColor" />
      <path d="M5.5 21.5 8 25l-3 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
    {!compact && <span>council<span className="brand-ai">AI</span></span>}
  </span>;
}
