// Backend client. VITE_API_BASE_URL points at the backend's API root, e.g. http://127.0.0.1:8000/api.
// API keys belong on the backend; VITE_ values are public browser configuration.
function endpoint(baseUrl, path) {
  return `${baseUrl.replace(/\/+$/, '')}${path}`;
}

async function call(baseUrl, path, {method = 'GET', body, signal, request = fetch} = {}) {
  if (!baseUrl) throw new Error('The backend is not connected yet.');
  const response = await request(endpoint(baseUrl, path), {
    method,
    headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
    signal
  });
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json())?.detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `The backend could not respond (${response.status}). Please try again.`);
  }
  return response.status === 204 ? null : response.json();
}

export async function askAssistant(baseUrl, equipmentId, message, {image, signal, request = fetch} = {}) {
  if (!baseUrl) throw new Error('The AI assistant is not connected yet.');
  // Text uses JSON. A photo uses multipart/form-data with fields equipment_id, message and image;
  // the browser sets the multipart Content-Type (with its boundary) itself.
  const body = image ? new FormData() : JSON.stringify({equipment_id: equipmentId, message});
  if (image) {
    body.append('equipment_id', equipmentId);
    body.append('message', message);
    body.append('image', image, image.name);
  }
  const response = await request(endpoint(baseUrl, '/assistant'), {
    method: 'POST',
    ...(image ? {} : {headers: {'Content-Type': 'application/json'}}),
    body,
    signal
  });
  if (!response.ok) throw new Error(`The assistant could not respond (${response.status}). Please try again.`);
  const result = await response.json();
  if (!result || typeof result.answer !== 'string' || !result.answer.trim()) {
    throw new Error('The assistant returned an unexpected response.');
  }
  return result.answer;
}

// --- Backend records -> the frontend's equipment/task shapes (see model.mjs) ---

export function toEquipment(asset, baseUrl) {
  return {
    id: asset.id,
    name: asset.name,
    category: asset.category || 'other',
    manufacturer: asset.manufacturer || '',
    model: asset.model || asset.code || '',
    location: asset.location || '',
    added_on: '',
    photo_url: asset.photo_url ? new URL(asset.photo_url, baseUrl).href : '',
    missing: asset.quantity_missing || 0,
    source: asset.source || 'other',
    manual_name: asset.manual_name || (asset.manual_id ? 'Manual' : '')
  };
}

// Upload a PDF manual and link it to one piece of equipment; the assistant then answers from it.
export async function uploadManual(baseUrl, equipmentId, file, {signal, request = fetch} = {}) {
  if (!baseUrl) throw new Error('The backend is not connected yet.');
  const body = new FormData();
  body.append('file', file, file.name);
  const response = await request(endpoint(baseUrl, `/assets/${equipmentId}/manual`), {method: 'POST', body, signal});
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof result.detail === 'string' ? result.detail : `The manual could not be uploaded (${response.status}).`);
  }
  return result;
}

// Friendly names for the backend's inventory sources; anything else shows as typed.
const SOURCE_LABELS = {home: 'Home', 'lab-demo': 'Lab demo', uda: 'UDA', other: 'Other'};

export function sourceLabel(source) {
  return SOURCE_LABELS[source] ?? source;
}

export function listSources(equipment) {
  const counts = new Map();
  for (const item of equipment) counts.set(item.source, (counts.get(item.source) || 0) + 1);
  return [...counts].map(([source, count]) => ({source, count, label: sourceLabel(source)}))
    .sort((a, b) => a.label.localeCompare(b.label));
}

// Spreadsheet import (.csv / .xlsx). dryRun previews without saving.
export function importInventory(baseUrl, file, {source = '', dryRun = false, signal, request = fetch} = {}) {
  if (!baseUrl) throw new Error('The backend is not connected yet.');
  const body = new FormData();
  body.append('file', file, file.name);
  const params = new URLSearchParams({dry_run: String(dryRun)});
  if (source.trim()) params.set('source', source.trim());
  return request(endpoint(baseUrl, `/assets/import?${params}`), {method: 'POST', body, signal}).then(async response => {
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof result.detail === 'string' ? result.detail : `The import failed (${response.status}).`;
      throw new Error(detail);
    }
    return result;
  });
}

// The UI's reminder choices, in days, as the backend's repeat interval.
export const RECURRENCE_DAYS = {weekly: 7, monthly: 30, quarterly: 91};

function recurrenceLabel(days) {
  if (!days) return 'none';
  const named = Object.entries(RECURRENCE_DAYS).find(([, value]) => value === days);
  return named ? named[0] : `every ${days} days`;
}

export function toTask(task) {
  return {
    id: task.id,
    equipment_id: task.asset_id,
    title: task.title,
    due_date: task.due_date,
    completed_at: task.status === 'done' ? (task.completed_on || task.due_date) : null,
    notes: [task.description, task.notes].filter(Boolean).join('\n\n'),
    priority: task.priority,
    kind: task.kind,
    recurrence: recurrenceLabel(task.interval_days),
    // The backend already scheduled the next occurrence, so a finished recurring task stays finished.
    reopen_locked: task.status === 'done' && Boolean(task.schedule_id)
  };
}

export async function loadWorkspace(baseUrl, options) {
  const [assets, tasks] = await Promise.all([
    call(baseUrl, '/assets', options),
    call(baseUrl, '/tasks?status=all', options)
  ]);
  return {schema_version: 1, equipment: assets.map(asset => toEquipment(asset, baseUrl)), tasks: tasks.map(toTask)};
}

export function completeTask(baseUrl, task, options) {
  return task.completed_at
    ? call(baseUrl, `/assets/${task.equipment_id}/tasks/${task.id}`, {...options, method: 'PATCH', body: {status: 'open'}})
    : call(baseUrl, `/tasks/${task.id}/complete`, {...options, method: 'POST', body: {}});
}

export function addEquipment(baseUrl, item, options) {
  const {name, category, manufacturer, model, location, source} = item;
  return call(baseUrl, '/assets', {...options, method: 'POST', body: {
    name, category, manufacturer: manufacturer || null, model: model || null, location: location || null,
    source: source || null
  }});
}

export function addTask(baseUrl, task, options) {
  return call(baseUrl, `/assets/${task.equipment_id}/tasks`, {...options, method: 'POST', body: {
    title: task.title, due_date: task.due_date, description: task.notes,
    repeat_every_days: RECURRENCE_DAYS[task.recurrence] ?? null
  }});
}
