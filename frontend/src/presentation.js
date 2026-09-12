export function modelLabel(model = '') {
  const names = { 'gpt-6-astra': 'GPT-6 Astra', 'gpt-5.6-sol': 'GPT-5.6 Sol', 'gpt-5.1': 'GPT-5.1' };
  return names[model] || model.split('/').pop();
}

export function panelLabel(panel) {
  if (!panel) return 'Your council';
  if (panel.is_personal || panel.key?.startsWith('personal:')) return panel.title || panel.preset_title;
  if (panel.key === 'foundry-mixed' || panel.preset === 'foundry-mixed') return 'The original council';
  if (panel.key === 'single-model-personas' || panel.preset === 'single-model-personas') return 'Three perspectives';
  if (panel.key === 'openai-direct' || panel.preset === 'openai-direct') return 'OpenAI API council';
  return panel.title || panel.preset_title || 'Your council';
}

export function relativeDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return '';
  const days = Math.floor((Date.now() - date.valueOf()) / 86400000);
  if (days < 1) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
