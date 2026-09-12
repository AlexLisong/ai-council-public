import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Check, CheckCircle2, ChevronRight, Crown, ImagePlus, LoaderCircle, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import Avatar from './Avatar';
import { AVATAR_OPTIONS, resolveAvatar } from '../avatars';
import { modelLabel } from '../presentation';
import './PanelEditor.css';

const MAX_SEATS = 8;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_AVATAR_BYTES = 100 * 1024;

function modelKey(member) {
  return JSON.stringify([member.provider, member.model]);
}

function normalizeMember(member, index = 0, chairman = false) {
  return {
    name: (member.name || '').trim(), provider: member.provider, model: member.model,
    persona: (member.persona || '').trim(), avatar: resolveAvatar(member, index, chairman),
  };
}

function validatePanel(panel, options) {
  if (!panel.title?.trim() || panel.title.length > 100) {
    return { member: 'panel', field: 'title', message: 'Give the panel a name of 1–100 characters.' };
  }
  if (!panel.seats.length || panel.seats.length > MAX_SEATS) {
    return { member: 'panel', field: 'seats', message: `Keep between 1 and ${MAX_SEATS} debate seats, plus the Chairman.` };
  }
  const members = [...panel.seats.map((seat, index) => ({ member: seat, key: String(index), label: `Seat ${index + 1}` })),
    { member: panel.chairman, key: 'chairman', label: 'Chairman' }];
  for (const { member, key, label } of members) {
    if (!member.name?.trim() || member.name.length > 80) {
      return { member: key, field: 'name', message: `${label}: enter a name of 1–80 characters.` };
    }
    if (!options.some((option) => modelKey(option) === modelKey(member))) {
      return { member: key, field: 'model', message: `${label}: choose an available model.` };
    }
    if ((key !== 'chairman' && !member.persona?.trim()) || (member.persona || '').length > 4000) {
      return { member: key, field: 'persona', message: key === 'chairman'
        ? 'Chairman: keep the optional persona within 4,000 characters.'
        : `${label}: enter a persona of 1–4,000 characters.` };
    }
  }
  return null;
}

async function prepareAvatar(file) {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    throw new Error('Choose a JPG, PNG or WebP image.');
  }
  if (file.size > MAX_IMAGE_BYTES) throw new Error('Choose an image smaller than 5 MB.');
  const url = URL.createObjectURL(file);
  try {
    const photo = new Image();
    await new Promise((resolve, reject) => {
      photo.onload = resolve;
      photo.onerror = () => reject(new Error('This image could not be opened. Try another JPG, PNG or WebP.'));
      photo.src = url;
    });
    if (!photo.naturalWidth || !photo.naturalHeight) throw new Error('This image is empty. Choose another image.');
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 256;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Image editing is unavailable in this browser. Choose a portrait below instead.');
    const side = Math.min(photo.naturalWidth, photo.naturalHeight);
    context.drawImage(photo, (photo.naturalWidth - side) / 2, (photo.naturalHeight - side) / 2, side, side, 0, 0, 256, 256);
    const avatar = canvas.toDataURL('image/webp', 0.85);
    const payload = avatar.split(',')[1] || '';
    const bytes = Math.floor(payload.length * 3 / 4) - (payload.match(/=+$/)?.[0].length || 0);
    if (!payload || bytes > MAX_AVATAR_BYTES) throw new Error('This image is still too large after resizing. Try a simpler image.');
    return avatar;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function MemberFields({ member, label, index, options, onChange, onUpload, chairman, disabled, processingAvatar, invalidField }) {
  const fileInput = useRef(null);
  const known = options.some((option) => modelKey(option) === modelKey(member));
  const portrait = resolveAvatar(member, index, chairman);
  const errorProps = (field) => ({
    'aria-invalid': invalidField === field || undefined,
    'aria-describedby': invalidField === field ? 'panel-editor-error' : undefined,
  });
  return (
    <fieldset className="member-editor" disabled={disabled}>
      <legend className="panel-editor-visually-hidden">{label} settings</legend>
      <section className="member-avatar-section" aria-label={`${label} portrait`}>
        <div className="member-avatar-current">
          <Avatar member={member} index={index} chairman={chairman} size={80} decorative={false} />
          <div className="member-avatar-copy">
            <span className="member-field-label">A face for this perspective</span>
            <p>Choose a portrait or make it personal.</p>
            <div className="member-avatar-actions">
              <button name="member-avatar" type="button" className="avatar-upload-button" {...errorProps('avatar')}
                onClick={() => fileInput.current?.click()}>
                {processingAvatar ? <LoaderCircle size={15} className="panel-icon-spin" aria-hidden="true" /> : <ImagePlus size={15} aria-hidden="true" />}
                {processingAvatar ? 'Preparing image…' : 'Upload photo'}
              </button>
              <button type="button" className="avatar-reset-button" onClick={() => onChange({ ...member, avatar: resolveAvatar({ ...member, avatar: null }, index, chairman) })}>
                <RotateCcw size={13} aria-hidden="true" /> Use default
              </button>
            </div>
            <input ref={fileInput} type="file" className="panel-editor-file-input" tabIndex={-1} aria-label={`Upload ${label} portrait`}
              accept="image/png,image/jpeg,image/webp" onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) onUpload(file);
              }} />
          </div>
        </div>
        <div className="avatar-presets" role="group" aria-label="Choose a portrait">
          {AVATAR_OPTIONS.map((option) => <button type="button" key={option.id} className={`avatar-preset${portrait === option.id ? ' selected' : ''}`}
            aria-label={`Use ${option.label} portrait`} title={option.label} aria-pressed={portrait === option.id}
            onClick={() => onChange({ ...member, avatar: option.id })}>
            <Avatar member={{ ...member, name: option.label, avatar: option.id }} index={index} chairman={chairman} size={38} />
            {portrait === option.id && <span className="avatar-preset-check"><Check size={9} strokeWidth={3} aria-hidden="true" /></span>}
          </button>)}
        </div>
        <p className="avatar-upload-hint">JPG, PNG or WebP · Up to 5 MB · Cropped to a square</p>
      </section>
      <div className="member-identity-fields">
        <label><span>Display name</span>
          <input name="member-name" aria-label={`${label} name`} value={member.name || ''} maxLength={80} required
            {...errorProps('name')} onChange={(event) => onChange({ ...member, name: event.target.value })} />
          <span className="member-field-hint">How this member appears in discussions.</span>
        </label>
        <label><span>AI model</span>
          <select name="member-model" aria-label={`${label} model`} value={modelKey(member)} {...errorProps('model')}
            onChange={(event) => {
              const choice = options.find((option) => modelKey(option) === event.target.value);
              if (choice) onChange({ ...member, provider: choice.provider, model: choice.model });
            }}>
            {!known && <option value={modelKey(member)} disabled>{member.model ? `${modelLabel(member.model)} (unavailable)` : 'Choose a model'}</option>}
            {options.map((option) => <option key={modelKey(option)} value={modelKey(option)}>{modelLabel(option.model)}{options.filter((item) => item.model === option.model).length > 1 ? ` · ${option.provider}` : ''}</option>)}
          </select>
          <span className="member-field-hint">The model behind this perspective.</span>
        </label>
      </div>
      <label><span className="persona-label">{chairman ? 'Synthesis guidance' : 'Perspective & expertise'}{chairman && <span>Optional</span>}</span>
        <span className="member-field-hint persona-hint">{chairman ? 'Shape how the Chairman brings the discussion together.' : 'Describe what this member should notice, question, and bring to the discussion.'}</span>
        <textarea name="member-persona" aria-label={`${label} persona`} value={member.persona || ''} maxLength={4000}
          required={!chairman} rows={7} {...errorProps('persona')}
          placeholder={chairman ? 'For example: Favor clear, practical conclusions. Explain the tradeoffs and preserve meaningful disagreement.' : 'For example: You are a thoughtful skeptic. Challenge assumptions, look for missing evidence, and explain what would change your mind.'}
          onChange={(event) => onChange({ ...member, persona: event.target.value })} />
      </label>
      <div className="member-editor-notes">
        <p>{chairman ? 'The Chairman always writes the final synthesis.' : 'A distinct point of view makes the whole panel more useful.'}</p>
        <span>{(member.persona || '').length.toLocaleString()} / 4,000</span>
      </div>
    </fieldset>
  );
}

export default function PanelEditor({ preset, modelOptions = [], panel, onChange, selectedMember = '0', onSelectMember, onSave, onClose }) {
  const form = useRef(null);
  const uploadGeneration = useRef(0);
  const [saving, setSaving] = useState(false);
  const [processingAvatar, setProcessingAvatar] = useState(false);
  const [error, setError] = useState(null);
  const chairman = { name: 'Chairman', persona: '', ...preset.chairman, ...panel.chairman };
  const requestedIndex = /^\d+$/.test(selectedMember) ? Number(selectedMember) : -1;
  const memberKey = selectedMember === 'chairman' || !panel.seats.length
    ? 'chairman' : String(requestedIndex >= 0 && requestedIndex < panel.seats.length ? requestedIndex : 0);
  const isChairman = memberKey === 'chairman';
  const seatIndex = isChairman ? -1 : Number(memberKey);
  const member = isChairman ? chairman : panel.seats[seatIndex];
  const label = isChairman ? 'Chairman' : `Seat ${seatIndex + 1}`;
  const busy = saving || processingAvatar;
  const baseline = {
    title: preset.title,
    seats: preset.seats.map((seat, index) => normalizeMember(seat, index)),
    chairman: normalizeMember({ name: 'Chairman', persona: '', ...preset.chairman }, 0, true),
  };
  const definition = { title: panel.title.trim(), seats: panel.seats.map((seat, index) => normalizeMember(seat, index)), chairman: normalizeMember(chairman, 0, true) };
  const hasChanges = !preset.is_personal || JSON.stringify(baseline) !== JSON.stringify(definition);

  useEffect(() => () => { uploadGeneration.current += 1; }, []);

  useEffect(() => {
    if (!error?.field || (error.member !== 'panel' && error.member !== memberKey)) return;
    const selector = error.member === 'panel'
      ? error.field === 'seats' ? '[name="add-seat"]' : '[name="panel-title"]'
      : `[name="member-${error.field}"]`;
    form.current?.querySelector(selector)?.focus();
  }, [error, memberKey, processingAvatar]);

  const change = (update) => {
    setError(null);
    onChange(update);
  };

  const updateMember = (updated) => change((current) => isChairman
    ? { ...current, chairman: updated }
    : { ...current, seats: current.seats.map((seat, index) => index === seatIndex ? updated : seat) });

  const uploadAvatar = async (file) => {
    const generation = ++uploadGeneration.current;
    setProcessingAvatar(true);
    setError(null);
    try {
      const avatar = await prepareAvatar(file);
      if (generation === uploadGeneration.current) updateMember({ ...member, avatar });
    } catch (failure) {
      if (generation === uploadGeneration.current) setError({ member: memberKey, field: 'avatar', message: failure.message || 'The image could not be prepared. Please try another image.' });
    } finally {
      if (generation === uploadGeneration.current) setProcessingAvatar(false);
    }
  };

  const addSeat = () => {
    if (busy || panel.seats.length >= MAX_SEATS) return;
    const selectedModel = modelOptions.find((option) => modelKey(option) === modelKey(member)) || modelOptions[0] || member;
    const index = panel.seats.length;
    const seat = { name: `Seat ${index + 1}`, provider: selectedModel.provider, model: selectedModel.model, persona: '' };
    change((current) => ({ ...current, seats: [...current.seats, { ...seat, avatar: resolveAvatar(seat, index) }] }));
    onSelectMember(String(index));
  };

  const removeSeat = () => {
    if (busy || isChairman || panel.seats.length <= 1) return;
    change((current) => ({ ...current, seats: current.seats.filter((_, index) => index !== seatIndex) }));
    onSelectMember(String(Math.min(seatIndex, panel.seats.length - 2)));
  };

  const save = async (event) => {
    event.preventDefault();
    if (busy) return;
    const invalid = validatePanel({ ...panel, chairman }, modelOptions);
    if (invalid) {
      setError(invalid);
      if (invalid.member !== 'panel') onSelectMember(invalid.member);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(preset.is_personal ? preset.id : null, definition);
    } catch (failure) {
      setError({ message: failure.message || 'Could not save the panel. Your changes are still here.' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="panel-editor-page" aria-labelledby="panel-editor-title">
      <div className="panel-editor-shell">
        <header className="panel-editor-header">
          <button type="button" className="panel-editor-back" disabled={busy} onClick={onClose}><ArrowLeft size={16} aria-hidden="true" /> Back</button>
          <div className="panel-editor-heading-row">
            <div><p className="panel-editor-eyebrow">MAKE ROOM FOR DIFFERENT THINKING</p><h1 id="panel-editor-title">{preset.is_personal ? 'Edit your panel' : 'Create your panel'}</h1></div>
            <span className="panel-editor-member-count"><span>{panel.seats.length + 1}</span> members</span>
          </div>
          <p>Give every voice a point of view. Choose a member to make it their own.</p>
        </header>
        <form ref={form} className="panel-editor" onSubmit={save} noValidate aria-busy={busy}>
          <div className="panel-title-section">
            <label><span>Panel name</span>
              <input name="panel-title" value={panel.title} maxLength={100} required disabled={busy} placeholder="Give your council a name"
                aria-invalid={error?.member === 'panel' && error.field === 'title' || undefined}
                aria-describedby={error?.member === 'panel' && error.field === 'title' ? 'panel-editor-error' : undefined}
                onChange={(event) => change((current) => ({ ...current, title: event.target.value }))} />
            </label>
            <p>A name to find it by. Your panels are saved to your account.</p>
          </div>
          <div className="panel-editor-body">
            <nav className="panel-member-nav" aria-label="Panel members">
              <div className="panel-member-nav-heading"><strong>Your council</strong><span>{panel.seats.length} seat{panel.seats.length === 1 ? '' : 's'} + Chairman</span></div>
              <div className="panel-member-list">
                {[...panel.seats.map((seat, index) => ({ key: String(index), member: seat, label: `Seat ${index + 1}`, index })),
                  { key: 'chairman', member: chairman, label: 'Chairman · Required', index: 0 }].map((item) => (
                  <button type="button" key={item.key} className={`panel-member-button${item.key === memberKey ? ' active' : ''}${item.key === 'chairman' ? ' chairman-member' : ''}`}
                    aria-pressed={item.key === memberKey} disabled={busy} onClick={() => onSelectMember(item.key)}>
                    <Avatar member={item.member} index={item.index} chairman={item.key === 'chairman'} size={42} />
                    <span className="panel-member-summary"><span className="panel-member-name">{item.member.name || 'Unnamed seat'}</span><span className="panel-member-role">{item.label}</span></span>
                    <ChevronRight className="panel-member-chevron" size={15} aria-hidden="true" />
                  </button>
                ))}
              </div>
              <button name="add-seat" type="button" className="panel-add-seat" disabled={busy || panel.seats.length >= MAX_SEATS} onClick={addSeat}><Plus size={16} aria-hidden="true" /> Add seat</button>
              <p className="panel-seat-limit">{panel.seats.length >= MAX_SEATS ? 'Your council is full.' : `Room for ${MAX_SEATS - panel.seats.length} more perspective${MAX_SEATS - panel.seats.length === 1 ? '' : 's'}.`}</p>
              <div className="panel-chairman-note"><Crown size={17} aria-hidden="true" /><p>The Chairman brings every perspective together into a clear final answer.</p></div>
            </nav>
            <div className="panel-member-content">
              <div className="panel-member-heading">
                <div><p>{isChairman ? 'THE FINAL PERSPECTIVE' : `DISCUSSION ${label.toUpperCase()}`}</p><h2>{member.name || 'Unnamed seat'}</h2></div>
                {isChairman ? <span className="panel-required-label"><Crown size={12} aria-hidden="true" /> Always included</span> : (
                  <button type="button" className="panel-remove-seat" disabled={busy || panel.seats.length <= 1}
                    title={panel.seats.length <= 1 ? 'Keep at least one debate seat.' : `Remove ${member.name || label} from this panel`}
                    onClick={removeSeat}><Trash2 size={14} aria-hidden="true" /> Remove seat</button>
                )}
              </div>
              <MemberFields key={memberKey} member={member} label={label} index={isChairman ? 0 : seatIndex} options={modelOptions}
                onChange={updateMember} onUpload={uploadAvatar} chairman={isChairman} disabled={busy} processingAvatar={processingAvatar}
                invalidField={error?.member === memberKey ? error.field : null} />
            </div>
          </div>
          <footer className="panel-editor-footer">
            <div className="panel-editor-feedback">
              {error ? <p role="alert" id="panel-editor-error" className="panel-editor-error">{error.message}</p> :
                <p role="status" className={`panel-save-status${!hasChanges ? ' is-saved' : ''}`}>
                  {busy ? <LoaderCircle size={15} className="panel-icon-spin" aria-hidden="true" /> : !hasChanges ? <CheckCircle2 size={15} aria-hidden="true" /> : <span className="panel-unsaved-dot" />}
                  {processingAvatar ? 'Preparing portrait…' : saving ? 'Saving your panel…' : !hasChanges ? 'All changes saved' : preset.is_personal ? 'Unsaved changes' : 'Not saved yet'}
                </p>}
            </div>
            <div className="panel-editor-actions">
              <button type="button" className="panel-cancel" disabled={busy} onClick={onClose}>Cancel</button>
              <button type="submit" className="panel-save" disabled={busy}>{saving ? <LoaderCircle size={16} className="panel-icon-spin" aria-hidden="true" /> : <Save size={16} aria-hidden="true" />}{saving ? 'Saving…' : preset.is_personal ? 'Save changes' : 'Save panel'}</button>
            </div>
          </footer>
        </form>
      </div>
    </section>
  );
}
