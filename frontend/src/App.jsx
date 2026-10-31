import React, {useEffect, useRef, useState} from 'react';
import {canReopenTask, createEquipment, createTask, demoData, loadState, localDate, saveState, selectTasks, taskStatus, toggleTask} from './model.mjs';
import {addEquipment, addTask, askAssistant, completeTask, importInventory, listSources, loadWorkspace, sourceLabel, uploadManual} from './api.mjs';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').trim();
const EMPTY = {schema_version: 1, equipment: [], tasks: []};
const storage = {getItem: key => window.localStorage.getItem(key), setItem: (key, value) => window.localStorage.setItem(key, value)};
const labels = {overdue: 'Overdue', due_today: 'Due today', upcoming: 'Upcoming', completed: 'Completed'};
const paths = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  box: 'm12 3 9 5v8l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v8 M7 5.8l9 5',
  check: 'm5 12 4 4L19 6',
  list: 'M9 6h12 M9 12h12 M9 18h12 M3 6h.01 M3 12h.01 M3 18h.01',
  clock: 'M12 8v4l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  plus: 'M12 5v14 M5 12h14',
  arrow: 'M5 12h14 m-5-5 5 5-5 5',
  search: 'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  sparkle: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z',
  close: 'm6 6 12 12 M6 18 18 6',
  pin: 'M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0 M14 10a2 2 0 1 1-4 0 2 2 0 0 1 4 0',
  undo: 'M4 10h10a6 6 0 0 1 0 12 M4 10l5-5 M4 10l5 5',
  camera: 'M4 7h3l2-3h6l2 3h3v12H4z M12 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  image: 'M3 4h18v16H3z M8 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M3 17l5-5 4 4 3-3 6 6'
};
function Icon({name, size = 20}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.box}/></svg>;
}

function EquipmentArt({item, index}) {
  if (item.photo_url) return <img className="equipment-photo" src={item.photo_url} alt="" loading="lazy"/>;
  if (item.category === 'bicycle') return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="139" rx="104" ry="8" fill="#cbd7ce"/><g fill="none" stroke="#344e42" strokeWidth="5"><circle cx="64" cy="104" r="36"/><circle cx="216" cy="104" r="36"/><path d="m64 104 38-65 38 65H64l47-48h78l27 48 M140 104l-29-64 M94 39h31 M182 27h18l-11 29" strokeLinejoin="round"/><circle cx="140" cy="104" r="5" fill="#344e42"/></g></svg>;
  if (index === 2 && item.id === 'eq-003') return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="145" rx="60" ry="7" fill="#d8d1c6"/><path d="M134 96h12v39h-12z" fill="#a79e90"/><path d="M110 135q30-12 60 0v9h-60z" fill="#bfb5a5"/><circle cx="140" cy="61" r="48" fill="#eee9df" stroke="#b1a796" strokeWidth="3"/><g fill="none" stroke="#bdb3a3"><circle cx="140" cy="61" r="38"/><circle cx="140" cy="61" r="28"/><path d="M92 61h96 M140 13v96 M106 27l68 68 M106 95l68-68"/></g><g fill="#c5bbab"><path d="M140 61q-31-5-20-27t20 27 M140 61q18-26 33-7t-33 7 M140 61q15 28-10 31t10-31"/></g><circle cx="140" cy="61" r="8" fill="#b1a796"/></svg>;
  if (item.category === 'appliance') return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="144" rx="65" ry="8" fill="#d7dbd5"/><rect x="94" y="18" width="92" height="124" rx="20" fill="#fafbf7" stroke="#bdc6bc" strokeWidth="2"/><ellipse cx="140" cy="32" rx="32" ry="7" fill="#dfe5dc"/><ellipse cx="140" cy="32" rx="23" ry="3" fill="#b4c1b0"/><circle cx="140" cy="56" r="4" fill="#98b38d"/>{Array.from({length: 8}, (_, i) => <path key={i} d={`M109 ${75 + i * 6}h62`} stroke="#d7ded3" strokeWidth="2"/>)}<path d="M104 136h72" stroke="#cbd4c6" strokeWidth="2"/></svg>;
  return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="143" rx="65" ry="8" fill="#d0d9ce"/><path d="m140 25 57 32v60l-57 30-57-30V57z" fill="#e6eddf" stroke="#879b80" strokeWidth="2"/><path d="m83 57 57 32 57-32 M140 89v58 M112 41l57 32" fill="none" stroke="#879b80" strokeWidth="2"/></svg>;
}

function Modal({type, equipment, selectedId, onClose, onSave}) {
  const dialog = useRef(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {dialog.current.showModal();}, []);
  const isEquipment = type === 'equipment';
  async function submit(event) {
    event.preventDefault();
    const fields = Object.fromEntries(new FormData(event.currentTarget));
    setSaving(true);
    try {
      await onSave(isEquipment ? createEquipment(fields) : createTask(fields, equipment));
      onClose();
    } catch (issue) {setError(issue.message);}
    finally {setSaving(false);}
  }
  return <dialog ref={dialog} className="modal" onClose={onClose} aria-labelledby="modal-title">
    <div className="modal-head"><div><p className="eyebrow">MAKE ROOM FOR WHAT MATTERS</p><h2 id="modal-title">{isEquipment ? 'Add equipment' : 'Add a maintenance task'}</h2></div><button className="icon-button" aria-label="Close dialog" onClick={onClose}><Icon name="close"/></button></div>
    <form onSubmit={submit}>
      {isEquipment ? <>
        <label>Equipment name<input autoFocus name="name" required maxLength={100} placeholder="e.g. Workshop drill"/></label>
        <div className="form-grid"><label>Category<select name="category" defaultValue="appliance"><option value="appliance">Appliance</option><option value="bicycle">Bicycle</option><option value="tool">Tool</option><option value="other">Other</option></select></label><label>Location<input name="location" maxLength={100} placeholder="e.g. Garage"/></label></div>
        <div className="form-grid"><label>Manufacturer<input name="manufacturer" maxLength={100} placeholder="Optional"/></label><label>Model<input name="model" maxLength={100} placeholder="Optional"/></label></div>
      </> : <>
        <label>Task title<input autoFocus name="title" required maxLength={140} placeholder="e.g. Check the product manual"/></label>
        <div className="form-grid"><label>Equipment<select name="equipment_id" defaultValue={selectedId || equipment[0]?.id} required>{equipment.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Due date<input type="date" name="due_date" required defaultValue={localDate()}/></label></div>
        <label>Repeat reminder<select name="recurrence" defaultValue="none"><option value="none">One time</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="quarterly">Every 3 months</option></select></label>
        <label>Notes<textarea name="notes" rows={3} maxLength={1000} placeholder="Any details you want to remember"/></label>
      </>}
      {error && <p role="alert" className="form-error">{error}</p>}
      <p className="form-hint">{API_BASE ? 'Saved to the shared backend.' : 'Saved in this browser. Shared team storage is not connected yet.'}</p>
      <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary" disabled={saving}>{isEquipment ? 'Add equipment' : 'Create task'}<Icon name="plus" size={16}/></button></div>
    </form>
  </dialog>;
}

function ImportModal({onClose, onImported}) {
  const dialog = useRef(null);
  const [file, setFile] = useState(null);
  const [source, setSource] = useState('');
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState('');
  useEffect(() => {dialog.current.showModal();}, []);
  function choose(event) {
    const chosen = event.target.files?.[0] || null;
    setFile(chosen); setPreview(null); setError('');
    if (chosen && !source) setSource(chosen.name.replace(/\.[^.]+$/, ''));
  }
  async function run(dryRun) {
    if (!file || pending) return;
    setPending(dryRun ? 'preview' : 'import'); setError('');
    try {
      const result = await importInventory(API_BASE, file, {source, dryRun});
      if (dryRun) setPreview(result);
      else {await onImported(result, source.trim() || file.name.replace(/\.[^.]+$/, '')); onClose();}
    } catch (issue) {setError(issue.message);}
    finally {setPending('');}
  }
  const issues = preview ? [...preview.skipped.map(i => `Row ${i.row} skipped: ${i.message}`), ...preview.warnings.map(i => `Row ${i.row}: ${i.message}`)] : [];
  return <dialog ref={dialog} className="modal" onClose={onClose} aria-labelledby="import-title">
    <div className="modal-head"><div><p className="eyebrow">BRING YOUR OLD SPREADSHEET</p><h2 id="import-title">Import inventory</h2></div><button className="icon-button" aria-label="Close dialog" onClick={onClose}><Icon name="close"/></button></div>
    <form onSubmit={event => {event.preventDefault(); run(!preview);}}>
      <label>Spreadsheet (.csv or .xlsx)<input type="file" accept=".csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={choose} required/></label>
      <label>Inventory name<input value={source} onChange={event => {setSource(event.target.value); setPreview(null);}} maxLength={60} placeholder="e.g. Chemistry lab, My apartment"/></label>
      <p className="form-hint">Columns are matched automatically (English or Spanish headers). Preview first; nothing is saved until you import.</p>
      {preview && <div className="import-preview" aria-live="polite">
        <p><strong>{preview.created}</strong> new · <strong>{preview.updated}</strong> updated{preview.kits_created ? ` · ${preview.kits_created} kits` : ''}{preview.stock_mismatches ? ` · ${preview.stock_mismatches} with missing units` : ''} · {preview.skipped.length} skipped</p>
        <ul className="import-columns">{preview.columns.filter(c => c.header).map(c => <li key={c.header}><span>{c.header}</span><span>{c.field ? `→ ${c.field.replaceAll('_', ' ')}${c.method === 'ai' ? ' (AI)' : ''}` : 'ignored'}</span></li>)}</ul>
        {issues.length > 0 && <details><summary>{issues.length} {issues.length === 1 ? 'note' : 'notes'}</summary><ul>{issues.slice(0, 50).map(text => <li key={text}>{text}</li>)}</ul></details>}
      </div>}
      {error && <p role="alert" className="form-error">{error}</p>}
      <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary" disabled={!file || Boolean(pending)}>{pending === 'preview' ? 'Reading file…' : pending === 'import' ? 'Importing…' : preview ? `Import ${preview.created + preview.updated} items` : 'Preview'}<Icon name={preview ? 'check' : 'arrow'} size={16}/></button></div>
    </form>
  </dialog>;
}

function Assistant({equipment, onManualUploaded}) {
  const [equipmentId, setEquipmentId] = useState(equipment[0]?.id || '');
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([]);
  const [photo, setPhoto] = useState(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [manualNote, setManualNote] = useState('');
  const selected = equipment.find(item => item.id === equipmentId);
  async function attachManual(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !equipmentId) return;
    if (!(file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) || file.size > 50 * 1024 * 1024) {
      setError('Choose a PDF manual under 50 MB.');
      return;
    }
    setUploading(true); setError(''); setManualNote('');
    try {
      const {manual} = await uploadManual(API_BASE, equipmentId, file);
      setManualNote(`Manual linked: ${manual.pages} pages.${manual.truncated ? ' It is long, so only the first part is used for answers.' : ''} Answers for this item now come from it.`);
      await onManualUploaded?.();
    } catch (issue) {setError(issue.message);}
    finally {setUploading(false);}
  }
  const controller = useRef(null);
  const photoUrls = useRef(new Set());
  useEffect(() => () => { for (const url of photoUrls.current) URL.revokeObjectURL(url); }, []);
  useEffect(() => {
    if (!equipment.some(item => item.id === equipmentId)) setEquipmentId(equipment[0]?.id || '');
  }, [equipment, equipmentId]);
  useEffect(() => {
    controller.current?.abort(); controller.current = null; setMessages([]); setError(''); setPending(false); setManualNote('');
    return () => controller.current?.abort();
  }, [equipmentId]);
  function attachPhoto(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) {
      setError('Choose a JPG, PNG, or WebP photo under 10 MB.');
      return;
    }
    if (photo && !messages.some(entry => entry.photoUrl === photo.url)) {
      URL.revokeObjectURL(photo.url); photoUrls.current.delete(photo.url);
    }
    const url = URL.createObjectURL(file);
    photoUrls.current.add(url);
    setPhoto({file, url}); setError('');
  }
  function removePhoto() {
    if (photo && !messages.some(entry => entry.photoUrl === photo.url)) {
      URL.revokeObjectURL(photo.url); photoUrls.current.delete(photo.url);
    }
    setPhoto(null);
  }
  async function submit(event) {
    event.preventDefault();
    if (pending || !API_BASE || (!message.trim() && !photo) || !equipmentId) return;
    const active = new AbortController(); controller.current = active;
    const timeout = setTimeout(() => active.abort(), photo ? 90000 : 30000); // looking at a photo takes the model longer
    const sentMessage = message.trim() || 'What should I check in this photo?';
    const sentPhoto = photo;
    setMessages(previous => [...previous, {role: 'user', text: sentMessage, photoUrl: sentPhoto?.url}]);
    setMessage(''); setPhoto(null); setPending(true); setError('');
    try {
      const response = await askAssistant(API_BASE, equipmentId, sentMessage, {image: sentPhoto?.file, signal: active.signal});
      if (controller.current === active && !active.signal.aborted) setMessages(previous => [...previous, {role: 'assistant', text: response}]);
    }
    catch (issue) {if (controller.current === active) setError(issue.name === 'AbortError' ? 'The request timed out. Please try again.' : issue.message);}
    finally {clearTimeout(timeout); if (controller.current === active) setPending(false);}
  }
  return <aside className="assistant panel" aria-labelledby="assistant-title">
    <div className="assistant-symbol"><Icon name="sparkle" size={25}/></div>
    <p className="eyebrow">A LITTLE HELP, WHEN YOU NEED IT</p><h2 id="assistant-title">Care made clearer.</h2>
    <p className="assistant-copy">Share a photo and describe what you notice. Your maintenance assistant can help you find the next step.</p>
    <span className={`connection ${API_BASE ? 'ready' : ''}`}><span/>{API_BASE ? 'Backend configured' : 'AI connection pending'}</span>
    <div className="chat-log" role="log" aria-label="Diagnostic conversation" aria-live="polite">
      {messages.length ? messages.map((entry, index) => <div className={`chat-message ${entry.role}`} key={index}><strong>{entry.role === 'user' ? 'You' : 'Maintenance assistant'}</strong>{entry.photoUrl && <img src={entry.photoUrl} alt="Photo attached to your question"/>}{entry.text && <p>{entry.text}</p>}</div>)
        : <p className="chat-empty">Your diagnostic conversation will appear here. A photo is optional.</p>}
      {pending && <p className="chat-pending">Thinking about your question...</p>}
    </div>
    <form onSubmit={submit}>
      <label>Equipment<select value={equipmentId} onChange={event => setEquipmentId(event.target.value)} disabled={!equipment.length}>{equipment.length ? equipment.map(item => <option key={item.id} value={item.id}>{item.name}</option>) : <option value="">Add equipment first</option>}</select></label>
      {API_BASE && selected && <div className="manual-row"><Icon name="list" size={15}/><span className="manual-name">{selected.manual_name ? <>Manual: <strong>{selected.manual_name}</strong></> : 'No manual linked'}</span><label className="photo-button">{uploading ? 'Uploading…' : selected.manual_name ? 'Replace PDF' : 'Upload manual'}<input type="file" accept="application/pdf,.pdf" onChange={attachManual} disabled={uploading} aria-label={`Upload a PDF manual for ${selected.name}`}/></label></div>}
      {manualNote && <p className="form-hint" role="status">{manualNote}</p>}
      <label>Your question<textarea value={message} onChange={event => setMessage(event.target.value)} rows={3} maxLength={2000} placeholder="What should I check before using this?"/></label>
      <div className="photo-actions"><label className="photo-button"><Icon name="image" size={15}/>Upload photo<input type="file" accept="image/jpeg,image/png,image/webp" onChange={attachPhoto} aria-label="Upload a photo"/></label><label className="photo-button"><Icon name="camera" size={15}/>Take photo<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={attachPhoto} aria-label="Take a photo"/></label></div>
      {photo && <div className="photo-preview"><img src={photo.url} alt="Selected attachment preview"/><span>{photo.file.name}</span><button type="button" onClick={removePhoto} aria-label="Remove selected photo"><Icon name="close" size={16}/></button></div>}
      <button type="submit" className="button primary full" disabled={!API_BASE || pending || (!message.trim() && !photo) || !equipmentId}>{pending ? 'Asking assistant...' : 'Ask assistant'}<Icon name="arrow" size={17}/></button>
    </form>
    {!API_BASE && <p className="form-hint">Photo preview works locally. Sending a diagnosis becomes available when the backend is connected.</p>}
    <div aria-live="polite" aria-busy={pending}>{error && <p className="form-error" role="alert">{error}</p>}{messages.some(entry => entry.role === 'assistant') && <p className="form-hint">AI suggestions may be inaccurate. Check the actual product manual.</p>}</div>
  </aside>;
}

export default function App() {
  const [initial] = useState(() => API_BASE ? {data: EMPTY, warning: ''} : loadState(storage));
  const [data, setData] = useState(initial.data);
  const [storageWarning, setStorageWarning] = useState(initial.warning);
  const [loading, setLoading] = useState(Boolean(API_BASE));
  const [today, setToday] = useState(localDate());
  const [view, setView] = useState('Overview');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('open');
  const [selectedId, setSelectedId] = useState('');
  const [modal, setModal] = useState('');
  const [announcement, setAnnouncement] = useState('');
  const [source, setSource] = useState('');
  useEffect(() => {
    if (API_BASE) return;
    const warning = saveState(storage, data); if (warning) setStorageWarning(warning);
  }, [data]);
  async function refresh() {
    try {setData(await loadWorkspace(API_BASE)); setStorageWarning('');}
    catch (issue) {setStorageWarning(`Could not load data from the backend: ${issue.message}`);}
    finally {setLoading(false);}
  }
  useEffect(() => {if (API_BASE) refresh();}, []);
  useEffect(() => {
    const refresh = () => setToday(localDate());
    const interval = setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
    return () => {clearInterval(interval); document.removeEventListener('visibilitychange', refresh);};
  }, []);
  // Inventory source filter (Home, UDA, …): everything below works on the chosen inventory only.
  const sources = API_BASE ? listSources(data.equipment) : [];
  const scopedIds = source ? new Set(data.equipment.filter(item => item.source === source).map(item => item.id)) : null;
  const scoped = scopedIds ? {...data, equipment: data.equipment.filter(item => scopedIds.has(item.id)), tasks: data.tasks.filter(task => scopedIds.has(task.equipment_id))} : data;
  const statuses = scoped.tasks.map(task => taskStatus(task, today));
  const overdue = statuses.filter(status => status === 'overdue').length;
  const dueToday = statuses.filter(status => status === 'due_today').length;
  const completed = statuses.filter(status => status === 'completed').length;
  const visibleTasks = selectTasks(scoped, {query, filter: view === 'History' ? 'completed' : filter, equipmentId: selectedId, today});
  const visibleEquipment = scoped.equipment.filter(item => `${item.name} ${item.model} ${item.location}`.toLowerCase().includes(query.trim().toLowerCase()));
  const equipmentById = new Map(data.equipment.map(item => [item.id, item]));
  const selected = equipmentById.get(selectedId);
  const dateLabel = new Date(`${today}T12:00:00`).toLocaleDateString(undefined, {weekday: 'long', month: 'long', day: 'numeric'});
  function navigate(next) {setView(next); setSelectedId(''); setQuery(''); setFilter('open');}
  async function complete(task) {
    if (API_BASE) {
      try {await completeTask(API_BASE, task); await refresh();}
      catch (issue) {setStorageWarning(issue.message); return;}
    } else setData(previous => toggleTask(previous, task.id, today));
    setAnnouncement(`${task.title}: ${task.completed_at ? 'reopened' : 'completed'}.`);
  }
  async function save(item) {
    if (API_BASE) {
      await (modal === 'equipment' ? addEquipment(API_BASE, {...item, source}) : addTask(API_BASE, item));
      await refresh();
    } else setData(previous => modal === 'equipment' ? {...previous, equipment: [...previous.equipment, item]} : {...previous, tasks: [...previous.tasks, item]});
    setAnnouncement(`${modal === 'equipment' ? item.name : item.title} added.`);
  }
  async function imported(result, name) {
    await refresh();
    setSource(name); setSelectedId('');
    setAnnouncement(`${result.created + result.updated} items imported into ${name}.`);
  }
  function reset() {
    if (window.confirm('Replace your equipment and tasks with fresh sample data? This clears changes saved in this browser.')) {
      setData(demoData(today)); setSelectedId(''); setAnnouncement('Sample equipment restored.');
    }
  }
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={event => {event.preventDefault(); navigate('Overview');}}><span className="brand-mark"><Icon name="check" size={26}/></span><span>Maintenance<span className="brand-sub">TRACKER</span></span></a>
      <p className="nav-label">YOUR WORKSPACE</p>
      <nav aria-label="Main navigation">{[['Overview', 'grid'], ['Equipment', 'box'], ['Maintenance', 'list'], ['History', 'clock']].map(([label, icon]) => <button key={label} className={`nav-item ${view === label ? 'active' : ''}`} aria-current={view === label ? 'page' : undefined} onClick={() => navigate(label)}><Icon name={icon}/>{label}{label === 'Maintenance' && overdue + dueToday > 0 && <span className="nav-count">{overdue + dueToday}</span>}</button>)}</nav>
      <div className="sidebar-note"><span className="little-leaf">↗</span><h3>Small care.<br/>Longer life.</h3><p>A little maintenance goes a long way.</p></div>
      <div className="sidebar-bottom"><span className="avatar">MT</span><div><strong>My workspace</strong><span>Local demo</span></div></div>
    </aside>
    <main>
      <div className="topline"><span className="breadcrumb">My workspace <span>/</span> {view}</span><span className="today">{dateLabel}</span></div>
      <header className="page-header"><div><p className="eyebrow">A LITTLE CARE GOES A LONG WAY</p><h1>{view === 'Overview' ? 'Keep good things going.' : view === 'Equipment' ? 'A home for your equipment.' : view === 'History' ? 'Good work, remembered.' : 'Make time for maintenance.'}</h1><p>{view === 'Overview' ? 'Your equipment, your to-dos, and a little peace of mind.' : view === 'Equipment' ? 'Know what you have. Keep it working well.' : view === 'History' ? 'A record of the care you have already put in.' : 'One small task today. Fewer surprises tomorrow.'}</p></div><div className="header-actions">{API_BASE && <button className="button secondary" onClick={() => setModal('import')}><Icon name="list" size={17}/>Import inventory</button>}<button className="button primary" onClick={() => setModal('equipment')}><Icon name="plus" size={17}/>Add equipment</button></div></header>
      {API_BASE
        ? <div className="demo-banner"><span className="demo-dot"/><p><strong>{loading ? 'Loading from the backend…' : 'Connected to the backend.'}</strong> Equipment, tasks and reminders are shared and powered by Gemma.</p><button onClick={() => {setLoading(true); refresh();}}>Refresh</button></div>
        : <div className="demo-banner"><span className="demo-dot"/><p><strong>Your demo workspace.</strong> Sample products and reminders are fictional. Changes stay in this browser.</p><button onClick={reset}>Reset demo</button></div>}
      {sources.length > 1 && <div className="source-filter" role="group" aria-label="Choose an inventory">{[{source: '', label: 'All inventories', count: data.equipment.length}, ...sources].map(entry => <button key={entry.source || 'all'} aria-pressed={source === entry.source} className={source === entry.source ? 'active' : ''} onClick={() => {setSource(entry.source); setSelectedId('');}}>{entry.label}<span>{entry.count}</span></button>)}</div>}
      {storageWarning && <div className="storage-warning" role="alert">{storageWarning}<button className="icon-button" onClick={() => setStorageWarning('')} aria-label="Dismiss storage notice"><Icon name="close" size={16}/></button></div>}
      <section className="stats" aria-label="Maintenance summary">{[
        {label: 'Equipment tracked', value: scoped.equipment.length, detail: source ? sourceLabel(source) : 'All in one place', icon: 'box', action: () => navigate('Equipment')},
        {label: 'Needs attention', value: overdue + dueToday, detail: `${overdue} overdue · ${dueToday} due today`, icon: 'clock', action: () => {navigate('Maintenance'); setFilter(overdue ? 'overdue' : 'due_today');}},
        {label: 'Tasks completed', value: completed, detail: 'A little progress adds up', icon: 'check', action: () => navigate('History')}
      ].map((stat, index) => <button className={`stat panel stat-${index}`} key={stat.label} onClick={stat.action}><span><span className="stat-label">{stat.label}</span><strong>{String(stat.value).padStart(2, '0')}</strong><span className="stat-detail">{stat.detail}</span></span><span className="stat-icon"><Icon name={stat.icon} size={22}/></span></button>)}</section>
      <div className="section-toolbar"><div><p className="eyebrow">LESS GUESSWORK. MORE GETTING ON.</p><h2>{view === 'History' ? 'Maintenance history' : view === 'Maintenance' ? 'Your maintenance plan' : 'Your equipment'}</h2></div><label className="search"><Icon name="search" size={17}/><input type="search" aria-label="Search equipment and tasks" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search equipment or tasks"/></label></div>
      {(view === 'Overview' || view === 'Equipment') && <section className="equipment-grid" aria-label="Equipment">{visibleEquipment.map((item, index) => {
        const tasks = data.tasks.filter(task => task.equipment_id === item.id && !task.completed_at);
        const needsAttention = tasks.some(task => taskStatus(task, today) === 'overdue');
        return <button key={item.id} className={`equipment-card panel art-${index % 3} ${selectedId === item.id ? 'selected' : ''}`} aria-pressed={selectedId === item.id} onClick={() => {setSelectedId(selectedId === item.id ? '' : item.id); setFilter('open');}}><div className="equipment-art"><span className="category">{item.category}</span><EquipmentArt item={item} index={index}/></div><div className="equipment-body"><h3>{item.name}</h3><p>{[item.manufacturer, item.model].filter(Boolean).join(' · ') || 'Model not specified'}</p><div className="equipment-meta"><span><Icon name="pin" size={13}/>{item.location || 'No location'}</span><span className={`small-status ${needsAttention ? 'attention' : ''}`}>{needsAttention ? 'Needs attention' : `${tasks.length} open ${tasks.length === 1 ? 'task' : 'tasks'}`}</span></div></div></button>;
      })}{!visibleEquipment.length && <div className="empty panel"><Icon name="box" size={30}/><h3>{query ? 'No matching equipment' : 'Start with one piece of equipment'}</h3><p>{query ? 'Try another name, model, or location.' : 'Add something you want to keep in good shape.'}</p>{!query && <button className="button primary" onClick={() => setModal('equipment')}>Add equipment</button>}</div>}</section>}
      <div className="workspace-columns"><section className="task-panel panel" aria-labelledby="tasks-title">
        <div className="task-heading"><div><h2 id="tasks-title">{view === 'History' ? 'Completed tasks' : selected ? selected.name : 'Coming up next'}<span className="count">{visibleTasks.length}</span></h2><p>{view === 'History' ? 'Every completed task is a little win.' : 'The small things that keep everything running.'}</p></div><button className="text-button" onClick={() => setModal('task')} disabled={!data.equipment.length}><Icon name="plus" size={16}/>Add task</button></div>
        <div className="task-tools">{view !== 'History' && <div className="tabs" aria-label="Filter tasks">{[['open', 'Open'], ['overdue', 'Overdue'], ['due_today', 'Today'], ['all', 'All']].map(([value, label]) => <button key={value} aria-pressed={filter === value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>)}</div>}{selected && <button className="selection-chip" onClick={() => setSelectedId('')}>Clear equipment filter<Icon name="close" size={13}/></button>}</div>
        <ul className="task-list">{visibleTasks.map(task => {
          const status = taskStatus(task, today);
          const item = equipmentById.get(task.equipment_id);
          const due = new Date(`${task.due_date}T12:00:00`).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'});
          const locked = Boolean(task.completed_at) && (task.reopen_locked || !canReopenTask(data, task.id));
          return <li key={task.id} className={status === 'completed' ? 'task-row is-complete' : 'task-row'}><button className="task-check" aria-label={`${task.completed_at ? 'Reopen' : 'Complete'} ${task.title}`} aria-pressed={Boolean(task.completed_at)} disabled={locked} title={locked ? 'A later occurrence is already complete' : undefined} onClick={() => complete(task)}>{task.completed_at && <Icon name="check" size={15}/>}</button>{item?.photo_url && <img className="task-thumb" src={item.photo_url} alt="" loading="lazy"/>}<div className="task-content"><h3>{task.title}</h3><p>{item?.name}{task.recurrence && task.recurrence !== 'none' && <span className="repeat-label">Repeats {task.recurrence === 'quarterly' ? 'every 3 months' : task.recurrence}</span>}</p>{task.notes && <details><summary>Notes</summary><p>{task.notes}</p></details>}</div><div className="task-date"><span className={`status ${status}`}>{labels[status]}</span><time dateTime={task.due_date}>{due}</time></div></li>;
        })}</ul>
        {!visibleTasks.length && <div className="empty"><span className="empty-icon"><Icon name="check" size={25}/></span><h3>{query ? 'No matching tasks' : view === 'History' ? 'Your history starts here' : 'Nothing in this view'}</h3><p>{query ? 'Try a different search.' : view === 'History' ? 'Complete a task to see it here.' : 'Try another filter, or add your next task.'}</p></div>}
        <div className="task-footer"><Icon name="check" size={15}/><span>One task at a time. You’ve got this.</span></div>
      </section><Assistant equipment={scoped.equipment} onManualUploaded={refresh}/></div>
      <footer className="page-footer"><span>Built to keep good things going.</span><span>Maintenance Tracker · Team demo</span></footer>
      <span className="sr-only" role="status">{announcement}</span>
    </main>
    {modal === 'import'
      ? <ImportModal onClose={() => setModal('')} onImported={imported}/>
      : modal && <Modal key={modal} type={modal} equipment={scoped.equipment} selectedId={selectedId} onClose={() => setModal('')} onSave={save}/>}
  </div>;
}
