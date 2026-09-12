export function debateHref(id, { scope = 'mine', panel } = {}) {
  const params = new URLSearchParams();
  if (scope === 'all') params.set('scope', 'all');
  if (panel) params.set('panel', panel);
  return `/debates${id ? `/${encodeURIComponent(id)}` : ''}${params.size ? `?${params}` : ''}`;
}

export function panelHref(preset, { returnTo, seat = '0' } = {}) {
  const params = new URLSearchParams({ seat });
  if (!preset.is_personal) params.set('template', preset.key);
  if (returnTo) params.set('returnTo', returnTo);
  return `/panels/${preset.is_personal ? encodeURIComponent(preset.id) : 'new'}?${params}`;
}

export function internalDestination(value, fallback = '/debates') {
  if (!value?.startsWith('/') || value.startsWith('//')) return fallback;
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin || !/^\/(debates|panels)(\/|$)/.test(url.pathname)) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}
