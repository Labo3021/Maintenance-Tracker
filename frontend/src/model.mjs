export const STORAGE_KEY = 'maintenance-tracker.frontend.v1';

export function localDate(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function shiftDate(iso, days) {
  const [year, month, day] = iso.split('-').map(Number);
  return localDate(new Date(year, month - 1, day + days, 12));
}

export const RECURRENCES = ['none', 'weekly', 'monthly', 'quarterly'];

export function nextRecurringDate(dueDate, recurrence, today = localDate()) {
  if (!RECURRENCES.includes(recurrence) || recurrence === 'none') return null;
  let next = dueDate;
  let occurrence = 0;
  do {
    occurrence += 1;
    if (recurrence === 'weekly') next = shiftDate(dueDate, 7 * occurrence);
    else {
      const [year, month, day] = dueDate.split('-').map(Number);
      const months = (recurrence === 'monthly' ? 1 : 3) * occurrence;
      const target = new Date(year, month - 1 + months, 1, 12);
      const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
      next = localDate(new Date(target.getFullYear(), target.getMonth(), Math.min(day, lastDay), 12));
    }
  } while (next <= today);
  return next;
}

export function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function taskStatus(task, today = localDate()) {
  if (task.completed_at) return 'completed';
  if (task.due_date < today) return 'overdue';
  if (task.due_date === today) return 'due_today';
  return 'upcoming';
}

export function demoData(today = localDate()) {
  return {
    schema_version: 1,
    equipment: [
      {id: 'eq-001', name: 'Living room air purifier', category: 'appliance', manufacturer: 'Demo Home', model: 'Air 100', location: 'Living room', added_on: shiftDate(today, -30)},
      {id: 'eq-002', name: 'Commuter bicycle', category: 'bicycle', manufacturer: 'Demo Cycle', model: 'City 200', location: 'Garage', added_on: shiftDate(today, -24)},
      {id: 'eq-003', name: 'Desk fan', category: 'appliance', manufacturer: 'Demo Home', model: 'Breeze 300', location: 'Home office', added_on: shiftDate(today, -12)}
    ],
    tasks: [
      {id: 'task-001', equipment_id: 'eq-001', title: 'Review filter condition', due_date: shiftDate(today, -6), completed_at: null, notes: 'Fictional reminder. Follow the actual product manual for maintenance.'},
      {id: 'task-002', equipment_id: 'eq-002', title: 'Review maintenance log', due_date: today, completed_at: null, recurrence: 'monthly', recurrence_anchor: today, notes: 'Fictional reminder; no repair procedure is implied.'},
      {id: 'task-003', equipment_id: 'eq-003', title: 'Find the product manual', due_date: shiftDate(today, 7), completed_at: null, notes: 'Look up the manual for the exact product model.'},
      {id: 'task-004', equipment_id: 'eq-001', title: 'Record product model', due_date: shiftDate(today, -12), completed_at: shiftDate(today, -12), notes: 'Fictional example for maintenance history.'}
    ]
  };
}

function nonempty(value) { return typeof value === 'string' && value.trim().length > 0; }

export function validateState(data) {
  if (!data || data.schema_version !== 1 || !Array.isArray(data.equipment) || !Array.isArray(data.tasks)) return false;
  const ids = new Set();
  for (const item of data.equipment) {
    if (!item || !nonempty(item.id) || ids.has(item.id) || !nonempty(item.name)) return false;
    if (!['appliance', 'bicycle', 'tool', 'other'].includes(item.category)) return false;
    if (!['model', 'manufacturer', 'location'].every(key => typeof item[key] === 'string')) return false;
    if (!validDate(item.added_on)) return false;
    ids.add(item.id);
  }
  const taskIds = new Set();
  for (const task of data.tasks) {
    if (!task || !nonempty(task.id) || taskIds.has(task.id) || !ids.has(task.equipment_id)) return false;
    if (!nonempty(task.title) || typeof task.notes !== 'string' || !validDate(task.due_date)) return false;
    if (task.completed_at !== null && !validDate(task.completed_at)) return false;
    if (task.recurrence !== undefined && !RECURRENCES.includes(task.recurrence)) return false;
    if (task.recurrence_anchor !== undefined && !validDate(task.recurrence_anchor)) return false;
    if (task.source_task_id !== undefined && !nonempty(task.source_task_id)) return false;
    taskIds.add(task.id);
  }
  for (const task of data.tasks) if (task.source_task_id && !taskIds.has(task.source_task_id)) return false;
  return true;
}

export function loadState(storage, today = localDate()) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (raw === null) return {data: demoData(today), warning: ''};
    const parsed = JSON.parse(raw);
    if (!validateState(parsed)) throw new Error('Invalid saved data');
    return {data: parsed, warning: ''};
  } catch {
    return {data: demoData(today), warning: 'Saved data could not be loaded. Showing sample equipment.'};
  }
}

export function saveState(storage, data) {
  try { storage.setItem(STORAGE_KEY, JSON.stringify(data)); return ''; }
  catch { return 'Browser storage is unavailable. Your changes will last for this session only.'; }
}

export function canReopenTask(data, id) {
  const successor = data.tasks.find(task => task.source_task_id === id);
  return !successor || !successor.completed_at;
}

export function toggleTask(data, id, today = localDate(), makeId = () => crypto.randomUUID()) {
  const selected = data.tasks.find(task => task.id === id);
  if (!selected) return data;
  if (selected.completed_at) {
    if (!canReopenTask(data, id)) return data;
    return {...data, tasks: data.tasks.filter(task => task.source_task_id !== id)
      .map(task => task.id === id ? {...task, completed_at: null} : task)};
  }
  const tasks = data.tasks.map(task => task.id === id ? {...task, completed_at: today} : task);
  const nextDate = nextRecurringDate(selected.recurrence_anchor ?? selected.due_date, selected.recurrence ?? 'none', today);
  if (nextDate) tasks.push({...selected, id: makeId(), due_date: nextDate, completed_at: null, source_task_id: selected.id});
  return {...data, tasks};
}

export function selectTasks(data, {query = '', filter = 'all', equipmentId = '', today = localDate()} = {}) {
  const search = query.trim().toLowerCase();
  const equipment = new Map(data.equipment.map(item => [item.id, item]));
  return data.tasks.filter(task => {
    const status = taskStatus(task, today);
    const item = equipment.get(task.equipment_id);
    return (!equipmentId || task.equipment_id === equipmentId)
      && (filter === 'all' || (filter === 'open' ? status !== 'completed' : status === filter))
      && (!search || `${task.title} ${item?.name ?? ''} ${item?.model ?? ''}`.toLowerCase().includes(search));
  }).sort((a, b) => Number(Boolean(a.completed_at)) - Number(Boolean(b.completed_at))
    || a.due_date.localeCompare(b.due_date));
}

export function createEquipment(fields, today = localDate(), id = crypto.randomUUID()) {
  const name = fields.name?.trim();
  if (!name || name.length > 100) throw new Error('Enter an equipment name (1–100 characters).');
  const category = fields.category;
  if (!['appliance', 'bicycle', 'tool', 'other'].includes(category)) throw new Error('Choose a category.');
  return {id, name, category, manufacturer: fields.manufacturer?.trim() ?? '', model: fields.model?.trim() ?? '', location: fields.location?.trim() ?? '', added_on: today};
}

export function createTask(fields, equipment, id = crypto.randomUUID()) {
  if (!equipment.some(item => item.id === fields.equipment_id)) throw new Error('Choose existing equipment.');
  const title = fields.title?.trim();
  if (!title || title.length > 140) throw new Error('Enter a task title (1–140 characters).');
  if (!validDate(fields.due_date)) throw new Error('Enter a valid due date.');
  const recurrence = fields.recurrence || 'none';
  if (!RECURRENCES.includes(recurrence)) throw new Error('Choose a reminder schedule.');
  return {id, equipment_id: fields.equipment_id, title, due_date: fields.due_date, completed_at: null, recurrence, ...(recurrence === 'none' ? {} : {recurrence_anchor: fields.due_date}), notes: fields.notes?.trim() ?? ''};
}
