import React, {useEffect, useState} from 'react';
import {answerDraftQuestion, diagnosePhoto, identifyPhoto, saveIdentifiedAsset} from './demoApi.mjs';

const MAX_PHOTO = 10 * 1024 * 1024;
const formatDate = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'}) : '';
const confidence = value => `${Math.round(Number(value || 0) * 100)}%`;

function PhotoPicker({file, onFile}) {
  const [preview, setPreview] = useState('');
  useEffect(() => {
    if (!file) {setPreview(''); return;}
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  function choose(event) {
    const next = event.target.files?.[0];
    event.target.value = '';
    if (!next) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(next.type) || next.size > MAX_PHOTO) {
      onFile(null, 'Choose a JPG, PNG or WebP image under 10 MB.');
      return;
    }
    onFile(next, '');
  }
  return <div className="flow-photo">
    <div className="flow-photo-preview">{preview ? <img src={preview} alt="Selected equipment preview"/> : <div><span aria-hidden="true">▧</span><strong>Your photo goes here</strong><small>JPG, PNG or WebP · up to 10 MB</small></div>}</div>
    <div className="photo-actions">
      <label className="photo-button">Upload photo<input type="file" accept="image/jpeg,image/png,image/webp" onChange={choose} aria-label="Upload equipment photo"/></label>
      <label className="photo-button">Take photo<input type="file" accept="image/*" capture="environment" onChange={choose} aria-label="Take equipment photo"/></label>
      {file && <button type="button" className="photo-button" onClick={() => onFile(null, '')}>Remove</button>}
    </div>
  </div>;
}

function usePhotoRequest() {
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  useEffect(() => () => { /* AbortController belongs to each request below. */ }, []);
  async function run(action) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000);
    setPending(true); setError('');
    try { return await action(controller.signal); }
    catch (issue) {
      setError(issue.name === 'AbortError' ? 'This AI request timed out after 90 seconds. Please try again.' : issue.message);
      return null;
    } finally {clearTimeout(timeout); setPending(false);}
  }
  return {file, setFile, error, setError, pending, run};
}

export function DiagnoseScreen({base, equipment, onTaskAdded}) {
  const {file, setFile, error, setError, pending, run} = usePhotoRequest();
  const [assetId, setAssetId] = useState('');
  const [notes, setNotes] = useState('');
  const [result, setResult] = useState(null);
  async function submit(event) {
    event.preventDefault();
    if (!file || pending) return;
    setResult(null);
    const reply = await run(signal => diagnosePhoto(base, file, assetId, notes.trim(), {signal}));
    if (reply) {setResult(reply); if (reply.task) await onTaskAdded();}
  }
  const diagnosis = result?.diagnosis;
  return <section className="flow-page" aria-labelledby="diagnose-title">
    <div className="flow-intro"><p className="eyebrow">PHOTO → GUIDANCE → SCHEDULE</p><h2 id="diagnose-title">Diagnose from a photo</h2><p>Show what you see, then review the suggested next steps and any task added to your schedule.</p></div>
    <form className="flow-form panel" onSubmit={submit}>
      <PhotoPicker file={file} onFile={(next, issue) => {setFile(next); setError(issue); setResult(null);}}/>
      <div className="form-grid"><label>Equipment<select value={assetId} onChange={event => setAssetId(event.target.value)}><option value="">No equipment selected</option>{equipment.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>Symptoms or context<textarea value={notes} onChange={event => setNotes(event.target.value)} rows={3} placeholder="e.g. loud grinding, unusual smell"/></label></div>
      <p className="form-hint">Choose an existing item to add the diagnosis task to its schedule.</p>
      <button className="button primary" disabled={!base || !file || pending}>{pending ? <><span className="spinner"/>Analyzing photo…</> : 'Diagnose photo'}</button>
      {pending && <p role="status" className="form-hint">This can take 10–20 seconds, or longer on a cold start.</p>}
      {!base && <p className="form-hint">Set VITE_API_BASE_URL to the running backend’s /api URL to diagnose.</p>}
      {error && <p role="alert" className="form-error">{error}</p>}
    </form>
    {diagnosis && <section className="diagnosis-result panel" aria-live="polite" aria-labelledby="result-title">
      <div className="result-header"><div><p className="eyebrow">DIAGNOSIS</p><h3 id="result-title">{diagnosis.issue}</h3><p>{diagnosis.component}</p></div><div className="result-tags"><span className={`severity ${diagnosis.severity}`}>{diagnosis.severity}</span><span>Confidence {confidence(diagnosis.confidence)}</span></div></div>
      {result.source === 'fallback' && <div className="safety-warning" role="alert">The AI was unavailable. This is generic fallback advice; no task was scheduled.</div>}
      {diagnosis.hazards?.length > 0 && <div className="safety-warning"><strong>Safety hazards</strong><ul>{diagnosis.hazards.map((hazard, i) => <li key={i}><strong>{hazard.type.replaceAll('_', ' ')}:</strong> {hazard.description}</li>)}</ul></div>}
      {diagnosis.requires_technician && <p className="technician-flag">A qualified technician is recommended.</p>}
      <div className="result-columns"><div><h4>Tools</h4><ul>{diagnosis.tools?.length ? diagnosis.tools.map((tool, i) => <li key={i}>{tool}</li>) : <li>None listed</li>}</ul></div><div><h4>Parts needed</h4><ul>{diagnosis.parts_needed?.length ? diagnosis.parts_needed.map((part, i) => <li key={i}>{part}</li>) : <li>None listed</li>}</ul></div></div>
      <h4>Suggested steps</h4><ol className="repair-steps">{diagnosis.steps?.map((step, i) => <li key={i}>{step.instruction}{step.caution && <small> Caution: {step.caution}</small>}</li>)}</ol>
      {result.task && <div className="scheduled-notice" role="status">Added to schedule, due {formatDate(result.task.due_date)}.</div>}
      <p className="form-hint">Check the equipment manual and follow your organization’s safety procedures before acting.</p>
    </section>}
  </section>;
}

export function IdentifyScreen({base, onSaved}) {
  const {file, setFile, error, setError, pending, run} = usePhotoRequest();
  const [notes, setNotes] = useState('');
  const [identified, setIdentified] = useState(null);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState('');
  async function identify(event) {
    event.preventDefault();
    if (!file || pending) return;
    setIdentified(null); setDraft(null); setSaved('');
    const reply = await run(signal => identifyPhoto(base, file, notes.trim(), {signal}));
    if (reply) {setIdentified(reply); setDraft(reply.draft);}
  }
  async function save(event) {
    event.preventDefault();
    if (!draft?.name?.trim() || saving) return;
    setSaving(true); setError('');
    try {
      const asset = await saveIdentifiedAsset(base, draft);
      setSaved(`${asset.name} added. Its maintenance schedule is ready.`);
      await onSaved();
    } catch (issue) {setError(issue.message);}
    finally {setSaving(false);}
  }
  function setField(key, value) {setDraft(previous => ({...previous, [key]: value}));}
  function setSchedule(index, key, value) {
    setDraft(previous => ({...previous, schedules: previous.schedules.map((item, i) =>
      i === index ? {...item, [key]: value} : item)}));
  }
  function removeSchedule(index) {
    setDraft(previous => ({...previous, schedules: previous.schedules.filter((_, i) => i !== index)}));
    setIdentified(previous => ({...previous, questions: previous.questions.flatMap(question => {
      const match = /^schedules\.(\d+)\.(.+)$/.exec(question.target);
      if (!match) return [question];
      const number = Number(match[1]);
      if (number === index) return [];
      return [{...question, target: number > index ? `schedules.${number - 1}.${match[2]}` : question.target}];
    })}));
  }
  return <section className="flow-page" aria-labelledby="identify-title">
    <div className="flow-intro"><p className="eyebrow">A FASTER START</p><h2 id="identify-title">Add equipment from a photo</h2><p>Review the identification and maintenance plan before anything is saved.</p></div>
    <form className="flow-form panel" onSubmit={identify}>
      <PhotoPicker file={file} onFile={(next, issue) => {setFile(next); setError(issue); setIdentified(null); setDraft(null);}}/>
      <label>Helpful context<textarea value={notes} onChange={event => setNotes(event.target.value)} rows={2} placeholder="e.g. bought in 2021, label on the back"/></label>
      <button className="button primary" disabled={!base || !file || pending}>{pending ? <><span className="spinner"/>Identifying…</> : 'Identify equipment'}</button>
      {pending && <p role="status" className="form-hint">The AI may take 10–20 seconds or longer on a cold start.</p>}
      {!base && <p className="form-hint">Connect the backend to identify an item from a photo.</p>}
    </form>
    {draft && <form className="identified-draft panel" onSubmit={save}>
      <div className="result-header"><div><p className="eyebrow">REVIEW BEFORE SAVING</p><h3>{draft.name}</h3></div><span className="confidence-tag">Confidence {confidence(identified.confidence)}</span></div>
      {identified.source === 'fallback' && <div className="safety-warning">The AI was unavailable. Review this generic draft carefully.</div>}
      <div className="form-grid"><label>Name<input required value={draft.name || ''} onChange={event => setField('name', event.target.value)}/></label><label>Category<input value={draft.category || ''} onChange={event => setField('category', event.target.value)}/></label></div>
      <div className="form-grid"><label>Brand / manufacturer<input value={draft.manufacturer || ''} onChange={event => setField('manufacturer', event.target.value)}/></label><label>Model<input value={draft.model || ''} onChange={event => setField('model', event.target.value)}/></label></div>
      {identified.questions?.length > 0 && <div className="questions"><h4>A few details to confirm</h4>{identified.questions.map((question, i) => {
        const value = question.target.split('.').reduce((node, part) => node?.[part], draft);
        return <label key={i}>{question.prompt}<input type={question.type} value={value || ''} required={question.required} placeholder={question.hint || ''} onChange={event => setDraft(previous => answerDraftQuestion(previous, question.target, event.target.value))}/>{question.hint && <small>{question.hint}</small>}</label>;
      })}</div>}
      <div className="schedule-editor"><h4>Suggested maintenance schedule</h4>{draft.schedules?.map((schedule, i) => <div className="schedule-row" key={schedule.id || i}><label>Task<input value={schedule.title} onChange={event => setSchedule(i, 'title', event.target.value)} required/></label><label>Every (days)<input type="number" min="1" max="3650" value={schedule.interval_days} onChange={event => setSchedule(i, 'interval_days', Number(event.target.value))} required/></label><button type="button" className="text-button" onClick={() => removeSchedule(i)}>Remove</button></div>)}</div>
      <p className="form-hint">An unknown last-done date is okay; the first task will be due today.</p>
      <button className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save equipment and schedule'}</button>
    </form>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {saved && <div className="scheduled-notice" role="status">{saved}</div>}
  </section>;
}
