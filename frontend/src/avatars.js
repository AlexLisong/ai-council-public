export const AVATAR_OPTIONS = [
  { id: 'skeptic', label: 'Skeptic' }, { id: 'builder', label: 'Builder' },
  { id: 'historian', label: 'Historian' }, { id: 'systems', label: 'Systems thinker' },
  { id: 'chairman', label: 'Chairman' }, { id: 'analyst', label: 'Analyst' },
  { id: 'visionary', label: 'Visionary' }, { id: 'mediator', label: 'Mediator' },
];

export function resolveAvatar(member = {}, index = 0, chairman = false) {
  const value = member?.avatar;
  if (AVATAR_OPTIONS.some((option) => option.id === value) || /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+=*$/.test(value || '')) return value;
  if (chairman) return 'chairman';
  const name = (member?.name || '').toLowerCase();
  if (name.includes('skeptic')) return 'skeptic';
  if (name.includes('builder')) return 'builder';
  if (name.includes('historian')) return 'historian';
  if (name.includes('systems')) return 'systems';
  return AVATAR_OPTIONS[Math.abs(index) % AVATAR_OPTIONS.length].id;
}
