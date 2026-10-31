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

export async function askAssistant(baseUrl, equipmentId, message, {signal, request = fetch} = {}) {
  if (!baseUrl) throw new Error('The AI assistant is not connected yet.');
  const response = await request(endpoint(baseUrl, '/assistant'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({equipment_id: equipmentId, message}),
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
    missing: asset.quantity_missing || 0
  };
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
    kind: task.kind
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
  const {name, category, manufacturer, model, location} = item;
  return call(baseUrl, '/assets', {...options, method: 'POST', body: {
    name, category, manufacturer: manufacturer || null, model: model || null, location: location || null
  }});
}

export function addTask(baseUrl, task, options) {
  return call(baseUrl, `/assets/${task.equipment_id}/tasks`, {...options, method: 'POST', body: {
    title: task.title, due_date: task.due_date, description: task.notes
  }});
}
