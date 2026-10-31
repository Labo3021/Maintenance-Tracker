// The frontend URL includes /api, for example http://127.0.0.1:8000/api.
const endpoint = (base, path) => `${base.replace(/\/+$/, '')}${path}`;

async function responseData(response) {
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* non-JSON error */ }
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`);
  }
  return response.status === 204 ? null : response.json();
}

async function jsonCall(base, path, {method = 'GET', body, signal, request = fetch} = {}) {
  if (!base) throw new Error('Connect the backend to use this feature.');
  return responseData(await request(endpoint(base, path), {
    method, signal, headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  }));
}

async function photoCall(base, path, image, fields = {}, {signal, request = fetch} = {}) {
  if (!base) throw new Error('Connect the backend to use this feature.');
  const form = new FormData();
  form.append('image', image, image.name);
  for (const [key, value] of Object.entries(fields)) if (value != null && value !== '') form.append(key, value);
  return responseData(await request(endpoint(base, path), {method: 'POST', body: form, signal}));
}

export const diagnosePhoto = (base, image, assetId, notes, options) =>
  photoCall(base, '/diagnose', image, {asset_id: assetId, notes}, options);
export const identifyPhoto = (base, image, notes, options) =>
  photoCall(base, '/assets/identify', image, {notes}, options);
export const saveIdentifiedAsset = (base, draft, options) =>
  jsonCall(base, '/assets', {...options, method: 'POST', body: draft});
export const snoozeTask = (base, id, days, options) =>
  jsonCall(base, `/tasks/${encodeURIComponent(id)}/snooze`, {...options, method: 'POST', body: {days}});
export const completeBackendTask = (base, task, options) =>
  task.completed_at
    ? jsonCall(base, `/assets/${encodeURIComponent(task.equipment_id)}/tasks/${encodeURIComponent(task.id)}`, {...options, method: 'PATCH', body: {status: 'open'}})
    : jsonCall(base, `/tasks/${encodeURIComponent(task.id)}/complete`, {...options, method: 'POST', body: {}});

export function toEquipment(asset, base) {
  return {
    id: asset.id, name: asset.name, category: asset.category || 'other',
    manufacturer: asset.manufacturer || '', model: asset.model || asset.code || '',
    location: asset.location || '', added_on: '', missing: asset.quantity_missing || 0,
    photo_url: asset.photo_url ? new URL(asset.photo_url, base).href : ''
  };
}
export function toTask(task) {
  return {
    id: task.id, equipment_id: task.asset_id, title: task.title, due_date: task.due_date,
    completed_at: task.status === 'done' ? task.completed_on || task.due_date : null,
    notes: [task.description, task.notes].filter(Boolean).join('\n\n'),
    priority: task.priority, kind: task.kind
  };
}
export async function loadWorkspace(base, options) {
  const [assets, tasks] = await Promise.all([
    jsonCall(base, '/assets', options), jsonCall(base, '/tasks?status=all', options)
  ]);
  return {schema_version: 1, equipment: assets.map(asset => toEquipment(asset, base)), tasks: tasks.map(toTask)};
}
export const addEquipment = (base, item, options) => jsonCall(base, '/assets', {
  ...options, method: 'POST', body: {
    name: item.name, category: item.category, manufacturer: item.manufacturer || null,
    model: item.model || null, location: item.location || null
  }
});
export const addTask = (base, task, options) => jsonCall(base,
  `/assets/${encodeURIComponent(task.equipment_id)}/tasks`, {
    ...options, method: 'POST', body: {title: task.title, due_date: task.due_date, description: task.notes}
  });

// Question targets come from the backend. Only write existing plain object/array paths.
export function answerDraftQuestion(draft, target, value) {
  const path = target.split('.');
  if (!path.length || path.some(part => !part || ['__proto__', 'prototype', 'constructor'].includes(part))) return draft;
  const next = structuredClone(draft);
  let node = next;
  for (const part of path.slice(0, -1)) {
    if (node == null || !Object.prototype.hasOwnProperty.call(node, part)) return draft;
    node = node[part];
  }
  const last = path.at(-1);
  if (node == null || !Object.prototype.hasOwnProperty.call(node, last)) return draft;
  node[last] = value === '' && last === 'last_done' ? null : value;
  return next;
}
