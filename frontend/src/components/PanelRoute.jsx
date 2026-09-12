import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, CircleAlert, LoaderCircle, RotateCcw } from 'lucide-react';
import { api, getToken } from '../api';
import { internalDestination } from '../routes';
import { panelLabel } from '../presentation';
import { resolveAvatar } from '../avatars';
import PanelEditor from './PanelEditor';

function draftFrom(preset) {
  return {
    title: preset.is_personal ? preset.title : `My ${panelLabel(preset).replace(/^The /i, '')}`.slice(0, 100),
    seats: preset.seats.map((seat, index) => ({ name: seat.name, provider: seat.provider, model: seat.model, persona: seat.persona, avatar: resolveAvatar(seat, index) })),
    chairman: { name: 'Chairman', persona: '', ...preset.chairman, avatar: resolveAvatar(preset.chairman, 0, true) },
  };
}

export default function PanelRoute({ config, configError, drafts, setDrafts, onSavePanel, onPanelLoaded }) {
  const { panelId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);
  const isNew = panelId === 'new';
  const templateKey = params.get('template') || config?.default_preset;
  const draftKey = isNew ? `new:${templateKey}` : panelId;
  const [loaded, setLoaded] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [retry, setRetry] = useState(0);
  const routeGeneration = useRef(0);
  const savedPreset = config?.presets.find((candidate) => candidate.is_personal && candidate.id === panelId);
  const source = isNew ? config?.presets.find((preset) => preset.key === templateKey) : loaded?.id === panelId ? savedPreset || loaded : null;
  const preset = source && isNew ? { ...source, is_personal: false, id: undefined } : source;
  const returnTo = params.has('returnTo') ? internalDestination(params.get('returnTo'), '/panels') : '/panels';

  useEffect(() => {
    routeGeneration.current += 1;
    return () => { routeGeneration.current += 1; };
  }, [draftKey]);

  useEffect(() => {
    if (isNew) return;
    let cancelled = false;
    api.getPanel(panelId).then((panel) => {
      if (cancelled) return;
      setLoaded(panel);
      setLoadError(null);
      onPanelLoaded(panel);
    }).catch((error) => {
      if (!cancelled) setLoadError({ id: panelId, message: error.status === 404 ? 'This panel was not found or is not available to your account.' : error.message });
    });
    return () => { cancelled = true; };
  }, [panelId, isNew, onPanelLoaded, retry]);

  if (loadError?.id === panelId || configError || (config && isNew && !preset)) return <main className="view-page panel-route-state"><div className="panel-state-card"><CircleAlert size={30} aria-hidden="true" /><h1>Panel unavailable</h1><p role="alert">{(loadError?.id === panelId ? loadError.message : null) || configError || 'The selected template was not found.'}</p><div className="panel-state-actions">{loadError?.id === panelId && <button type="button" onClick={() => setRetry((value) => value + 1)}><RotateCcw size={14} aria-hidden="true" />Retry panel</button>}<Link to="/panels"><ArrowLeft size={14} aria-hidden="true" />Back to panels</Link></div></div></main>;
  if (!config || !preset) return <main className="view-page panel-route-state"><div className="panel-state-card"><LoaderCircle size={25} className="panel-icon-spin" aria-hidden="true" /><p role="status">Loading your panel…</p></div></main>;
  const panel = drafts[draftKey] || draftFrom(preset);
  const changeDraft = (update) => setDrafts((previous) => {
    const current = previous[draftKey] || draftFrom(preset);
    return { ...previous, [draftKey]: typeof update === 'function' ? update(current) : update };
  });
  const selectMember = (value) => {
    const next = new URLSearchParams(location.search);
    next.set('seat', value);
    navigate(`${location.pathname}?${next}`);
  };
  const save = async (id, definition) => {
    const originRoute = routeGeneration.current;
    const originToken = getToken();
    const submittedDraft = drafts[draftKey];
    const saved = await onSavePanel(id, definition);
    if (getToken() !== originToken) return;
    setDrafts((previous) => {
      const unchanged = previous[draftKey] === submittedDraft;
      if (draftKey === saved.id) return unchanged ? { ...previous, [saved.id]: draftFrom(saved) } : previous;
      const next = { ...previous };
      if (!previous[saved.id]) next[saved.id] = draftFrom(saved);
      if (unchanged) delete next[draftKey];
      return next;
    });
    if (originRoute !== routeGeneration.current) return;
    if (/^\/debates(?:[/?]|$)/.test(returnTo)) {
      const destination = new URL(returnTo, window.location.origin);
      destination.searchParams.set('panel', saved.key);
      navigate(`${destination.pathname}${destination.search}`);
    } else {
      const next = new URLSearchParams({ seat: params.get('seat') || '0' });
      navigate(`/panels/${saved.id}?${next}`, { replace: isNew, state: { saved: true } });
      setLoaded(saved);
    }
  };
  return <div className="panel-route">
    <PanelEditor key={draftKey} preset={preset} modelOptions={config.model_options || []} panel={panel} onChange={changeDraft}
      selectedMember={params.get('seat') || '0'} onSelectMember={selectMember} onSave={save} onClose={() => navigate(returnTo)} />
  </div>;
}
