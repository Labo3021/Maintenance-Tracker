import React, {useEffect, useRef, useState} from 'react';
import {createEquipment, createTask, demoData, loadState, localDate, saveState, selectTasks, taskStatus, toggleTask} from './model.mjs';
import {askAssistant} from './api.mjs';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').trim();
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
  undo: 'M4 10h10a6 6 0 0 1 0 12 M4 10l5-5 M4 10l5 5'
};
function Icon({name, size = 20}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.box}/></svg>;
}

function EquipmentArt({item, index}) {
  if (item.category === 'bicycle') return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="139" rx="104" ry="8" fill="#cbd7ce"/><g fill="none" stroke="#344e42" strokeWidth="5"><circle cx="64" cy="104" r="36"/><circle cx="216" cy="104" r="36"/><path d="m64 104 38-65 38 65H64l47-48h78l27 48 M140 104l-29-64 M94 39h31 M182 27h18l-11 29" strokeLinejoin="round"/><circle cx="140" cy="104" r="5" fill="#344e42"/></g></svg>;
  if (index === 2 && item.id === 'eq-003') return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="145" rx="60" ry="7" fill="#d8d1c6"/><path d="M134 96h12v39h-12z" fill="#a79e90"/><path d="M110 135q30-12 60 0v9h-60z" fill="#bfb5a5"/><circle cx="140" cy="61" r="48" fill="#eee9df" stroke="#b1a796" strokeWidth="3"/><g fill="none" stroke="#bdb3a3"><circle cx="140" cy="61" r="38"/><circle cx="140" cy="61" r="28"/><path d="M92 61h96 M140 13v96 M106 27l68 68 M106 95l68-68"/></g><g fill="#c5bbab"><path d="M140 61q-31-5-20-27t20 27 M140 61q18-26 33-7t-33 7 M140 61q15 28-10 31t10-31"/></g><circle cx="140" cy="61" r="8" fill="#b1a796"/></svg>;
  if (item.category === 'appliance') return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="144" rx="65" ry="8" fill="#d7dbd5"/><rect x="94" y="18" width="92" height="124" rx="20" fill="#fafbf7" stroke="#bdc6bc" strokeWidth="2"/><ellipse cx="140" cy="32" rx="32" ry="7" fill="#dfe5dc"/><ellipse cx="140" cy="32" rx="23" ry="3" fill="#b4c1b0"/><circle cx="140" cy="56" r="4" fill="#98b38d"/>{Array.from({length: 8}, (_, i) => <path key={i} d={`M109 ${75 + i * 6}h62`} stroke="#d7ded3" strokeWidth="2"/>)}<path d="M104 136h72" stroke="#cbd4c6" strokeWidth="2"/></svg>;
  return <svg viewBox="0 0 280 160" aria-hidden="true"><ellipse cx="140" cy="143" rx="65" ry="8" fill="#d0d9ce"/><path d="m140 25 57 32v60l-57 30-57-30V57z" fill="#e6eddf" stroke="#879b80" strokeWidth="2"/><path d="m83 57 57 32 57-32 M140 89v58 M112 41l57 32" fill="none" stroke="#879b80" strokeWidth="2"/></svg>;
}

function Modal({type, equipment, selectedId, onClose, onSave}) {
  const dialog = useRef(null);
  const [error, setError] = useState('');
  useEffect(() => {dialog.current.showModal();}, []);
  const isEquipment = type === 'equipment';
  function submit(event) {
    event.preventDefault();
    const fields = Object.fromEntries(new FormData(event.currentTarget));
    try {
      onSave(isEquipment ? createEquipment(fields) : createTask(fields, equipment));
      onClose();
    } catch (issue) {setError(issue.message);}
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
        <label>Notes<textarea name="notes" rows={3} maxLength={1000} placeholder="Any details you want to remember"/></label>
      </>}
      {error && <p role="alert" className="form-error">{error}</p>}
      <p className="form-hint">Saved in this browser. Shared team storage is not connected yet.</p>
      <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary">{isEquipment ? 'Add equipment' : 'Create task'}<Icon name="plus" size={16}/></button></div>
    </form>
  </dialog>;
}

function Assistant({equipment}) {
  const [equipmentId, setEquipmentId] = useState(equipment[0]?.id || '');
  const [message, setMessage] = useState('');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const controller = useRef(null);
  useEffect(() => {
    if (!equipment.some(item => item.id === equipmentId)) setEquipmentId(equipment[0]?.id || '');
  }, [equipment, equipmentId]);
  useEffect(() => {
    controller.current?.abort(); controller.current = null; setAnswer(''); setError(''); setPending(false);
    return () => controller.current?.abort();
  }, [equipmentId]);
  async function submit(event) {
    event.preventDefault();
    if (pending || !API_BASE || !message.trim() || !equipmentId) return;
    const active = new AbortController(); controller.current = active;
    const timeout = setTimeout(() => active.abort(), 30000);
    setPending(true); setError(''); setAnswer('');
    try {
      const response = await askAssistant(API_BASE, equipmentId, message.trim(), {signal: active.signal});
      if (controller.current === active && !active.signal.aborted) setAnswer(response);
    }
    catch (issue) {if (controller.current === active) setError(issue.name === 'AbortError' ? 'The request timed out. Please try again.' : issue.message);}
    finally {clearTimeout(timeout); if (controller.current === active) setPending(false);}
  }
  return <aside className="assistant panel" aria-labelledby="assistant-title">
    <div className="assistant-symbol"><Icon name="sparkle" size={25}/></div>
    <p className="eyebrow">A LITTLE HELP, WHEN YOU NEED IT</p><h2 id="assistant-title">Care made clearer.</h2>
    <p className="assistant-copy">Have a question about your equipment? Your maintenance assistant will help you find the next step.</p>
    <span className={`connection ${API_BASE ? 'ready' : ''}`}><span/>{API_BASE ? 'Backend configured' : 'AI connection pending'}</span>
    <form onSubmit={submit}>
      <label>Equipment<select value={equipmentId} onChange={event => setEquipmentId(event.target.value)} disabled={!equipment.length}>{equipment.length ? equipment.map(item => <option key={item.id} value={item.id}>{item.name}</option>) : <option value="">Add equipment first</option>}</select></label>
      <label>Your question<textarea value={message} onChange={event => setMessage(event.target.value)} rows={3} maxLength={2000} placeholder="What should I check before using this?"/></label>
      <button type="submit" className="button primary full" disabled={!API_BASE || pending || !message.trim() || !equipmentId}>{pending ? 'Asking assistant…' : 'Ask assistant'}<Icon name="arrow" size={17}/></button>
    </form>
    {!API_BASE && <p className="form-hint">Your question stays here until the AI service is connected.</p>}
    <div aria-live="polite" aria-busy={pending}>{error && <p className="form-error" role="alert">{error}</p>}{answer && <div className="answer"><strong>Assistant response</strong><p>{answer}</p><small>AI suggestions may be inaccurate. Check the actual product manual.</small></div>}</div>
  </aside>;
}

export default function App() {
  const [initial] = useState(() => loadState(storage));
  const [data, setData] = useState(initial.data);
  const [storageWarning, setStorageWarning] = useState(initial.warning);
  const [today, setToday] = useState(localDate());
  const [view, setView] = useState('Overview');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('open');
  const [selectedId, setSelectedId] = useState('');
  const [modal, setModal] = useState('');
  const [announcement, setAnnouncement] = useState('');
  useEffect(() => {const warning = saveState(storage, data); if (warning) setStorageWarning(warning);}, [data]);
  useEffect(() => {
    const refresh = () => setToday(localDate());
    const interval = setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
    return () => {clearInterval(interval); document.removeEventListener('visibilitychange', refresh);};
  }, []);
  const statuses = data.tasks.map(task => taskStatus(task, today));
  const overdue = statuses.filter(status => status === 'overdue').length;
  const dueToday = statuses.filter(status => status === 'due_today').length;
  const completed = statuses.filter(status => status === 'completed').length;
  const visibleTasks = selectTasks(data, {query, filter: view === 'History' ? 'completed' : filter, equipmentId: selectedId, today});
  const visibleEquipment = data.equipment.filter(item => `${item.name} ${item.model} ${item.location}`.toLowerCase().includes(query.trim().toLowerCase()));
  const equipmentById = new Map(data.equipment.map(item => [item.id, item]));
  const selected = equipmentById.get(selectedId);
  const dateLabel = new Date(`${today}T12:00:00`).toLocaleDateString(undefined, {weekday: 'long', month: 'long', day: 'numeric'});
  function navigate(next) {setView(next); setSelectedId(''); setQuery(''); setFilter('open');}
  function complete(task) {
    setData(previous => toggleTask(previous, task.id, today));
    setAnnouncement(`${task.title}: ${task.completed_at ? 'reopened' : 'completed'}.`);
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
      <header className="page-header"><div><p className="eyebrow">A LITTLE CARE GOES A LONG WAY</p><h1>{view === 'Overview' ? 'Keep good things going.' : view === 'Equipment' ? 'A home for your equipment.' : view === 'History' ? 'Good work, remembered.' : 'Make time for maintenance.'}</h1><p>{view === 'Overview' ? 'Your equipment, your to-dos, and a little peace of mind.' : view === 'Equipment' ? 'Know what you have. Keep it working well.' : view === 'History' ? 'A record of the care you have already put in.' : 'One small task today. Fewer surprises tomorrow.'}</p></div><button className="button primary" onClick={() => setModal('equipment')}><Icon name="plus" size={17}/>Add equipment</button></header>
      <div className="demo-banner"><span className="demo-dot"/><p><strong>Your demo workspace.</strong> Sample products and reminders are fictional. Changes stay in this browser.</p><button onClick={reset}>Reset demo</button></div>
      {storageWarning && <div className="storage-warning" role="alert">{storageWarning}<button className="icon-button" onClick={() => setStorageWarning('')} aria-label="Dismiss storage notice"><Icon name="close" size={16}/></button></div>}
      <section className="stats" aria-label="Maintenance summary">{[
        {label: 'Equipment tracked', value: data.equipment.length, detail: 'All in one place', icon: 'box', action: () => navigate('Equipment')},
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
          return <li key={task.id} className={status === 'completed' ? 'task-row is-complete' : 'task-row'}><button className="task-check" aria-label={`${task.completed_at ? 'Reopen' : 'Complete'} ${task.title}`} aria-pressed={Boolean(task.completed_at)} onClick={() => complete(task)}>{task.completed_at && <Icon name="check" size={15}/>}</button><div className="task-content"><h3>{task.title}</h3><p>{item?.name}</p>{task.notes && <details><summary>Notes</summary><p>{task.notes}</p></details>}</div><div className="task-date"><span className={`status ${status}`}>{labels[status]}</span><time dateTime={task.due_date}>{due}</time></div></li>;
        })}</ul>
        {!visibleTasks.length && <div className="empty"><span className="empty-icon"><Icon name="check" size={25}/></span><h3>{query ? 'No matching tasks' : view === 'History' ? 'Your history starts here' : 'Nothing in this view'}</h3><p>{query ? 'Try a different search.' : view === 'History' ? 'Complete a task to see it here.' : 'Try another filter, or add your next task.'}</p></div>}
        <div className="task-footer"><Icon name="check" size={15}/><span>One task at a time. You’ve got this.</span></div>
      </section><Assistant equipment={data.equipment}/></div>
      <footer className="page-footer"><span>Built to keep good things going.</span><span>Maintenance Tracker · Team demo</span></footer>
      <span className="sr-only" role="status">{announcement}</span>
    </main>
    {modal && <Modal key={modal} type={modal} equipment={data.equipment} selectedId={selectedId} onClose={() => setModal('')} onSave={item => {setData(previous => modal === 'equipment' ? {...previous, equipment: [...previous.equipment, item]} : {...previous, tasks: [...previous.tasks, item]}); setAnnouncement(`${modal === 'equipment' ? item.name : item.title} added.`);}}/>}
  </div>;
}
