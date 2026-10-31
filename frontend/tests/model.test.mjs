import test from 'node:test';
import assert from 'node:assert/strict';
import {canReopenTask, createEquipment, createTask, demoData, loadState, localDate, nextRecurringDate, saveState, selectTasks, shiftDate, STORAGE_KEY, taskStatus, toggleTask, validDate, validateState} from '../src/model.mjs';
import {addTask, askAssistant, completeTask, loadWorkspace, toEquipment, toTask} from '../src/api.mjs';

const today = '2026-10-31';

test('demo data covers overdue, today, upcoming, and history', () => {
  const data = demoData(today);
  assert.ok(validateState(data));
  assert.deepEqual(data.tasks.map(task => taskStatus(task, today)), ['overdue', 'due_today', 'upcoming', 'completed']);
});

test('calendar arithmetic crosses months and leap days', () => {
  assert.equal(shiftDate('2026-10-31', 1), '2026-11-01');
  assert.equal(shiftDate('2024-03-01', -1), '2024-02-29');
  assert.equal(shiftDate('2026-01-01', -1), '2025-12-31');
  assert.equal(localDate(new Date(2026, 9, 31, 23)), today);
  assert.equal(validDate('2026-02-30'), false);
  assert.equal(validDate('2026-13-01'), false);
});

test('completing and reopening a task preserves original state', () => {
  const original = demoData(today);
  const changed = toggleTask(original, 'task-001', today);
  assert.equal(changed.tasks[0].completed_at, today);
  assert.equal(original.tasks[0].completed_at, null);
  assert.equal(toggleTask(changed, 'task-001', today).tasks[0].completed_at, null);
  assert.equal(selectTasks(changed, {filter: 'completed', today}).length, 2);
});

test('recurring completion keeps history and schedules the next future occurrence', () => {
  assert.equal(nextRecurringDate('2026-01-31', 'monthly', '2026-02-28'), '2026-03-31');
  assert.equal(nextRecurringDate('2024-02-29', 'quarterly', '2024-05-29'), '2024-08-29');
  assert.equal(nextRecurringDate('2026-10-01', 'weekly', today), '2026-11-05');
  const original = demoData(today);
  const changed = toggleTask(original, 'task-002', today, () => 'task-next');
  assert.ok(validateState(changed));
  assert.equal(changed.tasks.find(task => task.id === 'task-002').completed_at, today);
  assert.equal(changed.tasks.find(task => task.id === 'task-next').due_date, '2026-11-30');
  assert.equal(selectTasks(changed, {filter: 'completed', today}).length, 2);
  assert.equal(selectTasks(changed, {filter: 'open', today}).length, 3);
  assert.deepEqual(toggleTask(changed, 'task-002', today).tasks, original.tasks);
  const later = toggleTask(changed, 'task-next', '2026-11-30', () => 'task-after');
  assert.equal(canReopenTask(later, 'task-002'), false);
  assert.equal(toggleTask(later, 'task-002', today), later);
  const january = createTask({title: 'Check filter', equipment_id: original.equipment[0].id, due_date: '2026-01-31', recurrence: 'monthly'}, original.equipment, 'jan');
  const february = toggleTask({...original, tasks: [...original.tasks, january]}, 'jan', '2026-01-31', () => 'feb').tasks.at(-1);
  assert.equal(february.due_date, '2026-02-28');
  const march = toggleTask({...original, tasks: [january, february]}, 'feb', '2026-02-28', () => 'mar').tasks.at(-1);
  assert.equal(march.due_date, '2026-03-31');
});

test('search and task filters compose with equipment selection', () => {
  const data = demoData(today);
  assert.deepEqual(selectTasks(data, {filter: 'open', today}).map(task => task.id), ['task-001', 'task-002', 'task-003']);
  assert.equal(selectTasks(data, {query: ' BICYCLE ', today}).length, 1);
  assert.equal(selectTasks(data, {filter: 'due_today', equipmentId: 'eq-001', today}).length, 0);
  assert.equal(selectTasks(data, {filter: 'overdue', today})[0].id, 'task-001');
});

test('new equipment and tasks use stable IDs and validate user input', () => {
  const item = createEquipment({name: ' Workshop drill ', category: 'tool'}, today, 'new-equipment');
  assert.equal(item.name, 'Workshop drill');
  assert.equal(item.location, '');
  const task = createTask({title: ' Find manual ', equipment_id: item.id, due_date: today}, [item], 'new-task');
  assert.equal(task.title, 'Find manual');
  assert.equal(task.completed_at, null);
  assert.equal(task.recurrence, 'none');
  assert.ok(validateState({schema_version: 1, equipment: [item], tasks: [task]}));
  assert.throws(() => createEquipment({name: ' ', category: 'tool'}, today, 'bad'), /equipment name/);
  assert.throws(() => createTask({title: 'Task', equipment_id: 'missing', due_date: today}, [item], 'bad'), /existing equipment/);
  assert.throws(() => createTask({title: 'Task', equipment_id: item.id, due_date: '2026-02-30'}, [item], 'bad'), /valid due date/);
  assert.throws(() => createTask({title: 'Task', equipment_id: item.id, due_date: today, recurrence: 'daily'}, [item], 'bad'), /reminder schedule/);
});

test('saved state survives a round trip', () => {
  const memory = new Map();
  const storage = {getItem: key => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value)};
  const data = toggleTask(demoData(today), 'task-001', today);
  assert.equal(saveState(storage, data), '');
  assert.ok(memory.has(STORAGE_KEY));
  assert.deepEqual(loadState(storage, today).data, data);
});

test('corrupt or unavailable browser storage falls back with a notice', () => {
  for (const getItem of [() => '{oops', () => '{"schema_version":1}', () => {throw new Error('denied');}]) {
    const result = loadState({getItem}, today);
    assert.ok(validateState(result.data));
    assert.match(result.warning, /could not be loaded/);
  }
  assert.match(saveState({setItem: () => {throw new Error('quota');}}, demoData(today)), /session only/);
});

test('saved data rejects broken references, invalid dates, and duplicate IDs', () => {
  for (const mutate of [
    d => { d.tasks[0].equipment_id = 'missing'; },
    d => { d.equipment[1].id = d.equipment[0].id; },
    d => { d.tasks[1].id = d.tasks[0].id; },
    d => { d.tasks[0].due_date = 'tomorrow'; },
    d => { delete d.tasks[0].completed_at; },
    d => { d.equipment[0].name = ' '; }
  ]) {
    const data = demoData(today); mutate(data); assert.equal(validateState(data), false);
  }
});

test('AI adapter sends the proposed backend payload and accepts text', async () => {
  let captured;
  const answer = await askAssistant('https://backend.example/', 'eq-001', 'Where is the manual?', {
    request: async (url, options) => {captured = {url, options}; return {ok: true, json: async () => ({answer: 'Check the exact model number.'})};}
  });
  assert.equal(captured.url, 'https://backend.example/assistant');
  assert.equal(captured.options.method, 'POST');
  assert.deepEqual(JSON.parse(captured.options.body), {equipment_id: 'eq-001', message: 'Where is the manual?'});
  assert.equal(answer, 'Check the exact model number.');
});

test('AI adapter handles disconnected, failed, malformed, and aborted requests', async () => {
  await assert.rejects(askAssistant('', 'eq-001', 'Question'), /not connected/);
  await assert.rejects(askAssistant('/api', 'eq-001', 'Question', {request: async () => ({ok: false, status: 503})}), /503/);
  await assert.rejects(askAssistant('/api', 'eq-001', 'Question', {request: async () => ({ok: true, json: async () => ({answer: 42})})}), /unexpected response/);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(askAssistant('/api', 'eq-001', 'Question', {signal: controller.signal, request: async (_url, options) => {options.signal.throwIfAborted();}}), {name: 'AbortError'});
});

test('backend assets and tasks map to the frontend shapes', () => {
  const item = toEquipment({id: 'a1', name: 'Polea', category: 'general', code: '02360.00', manufacturer: null,
    model: null, location: 'Estante 1', photo_url: '/api/assets/a1/photo', quantity_missing: 7}, 'http://127.0.0.1:8000/api');
  assert.deepEqual(item, {id: 'a1', name: 'Polea', category: 'general', manufacturer: '', model: '02360.00',
    location: 'Estante 1', added_on: '', photo_url: 'http://127.0.0.1:8000/api/assets/a1/photo', missing: 7});
  const open = toTask({id: 't1', asset_id: 'a1', title: 'Missing 7 units: Polea', due_date: '2026-10-31', status: 'open',
    description: 'Counted 5 of 12.', notes: '', priority: 'medium', kind: 'stock'});
  assert.equal(open.equipment_id, 'a1');
  assert.equal(open.completed_at, null);
  assert.equal(open.notes, 'Counted 5 of 12.');
  assert.equal(toTask({...open, asset_id: 'a1', status: 'done', completed_on: '2026-10-30'}).completed_at, '2026-10-30');
});

test('backend calls use the right routes and surface error details', async () => {
  const calls = [];
  const request = async (url, options) => {
    calls.push([options.method, url, options.body && JSON.parse(options.body)]);
    return {ok: true, status: 200, json: async () => (url.endsWith('/assets') ? [{id: 'a1', name: 'X'}] : [])};
  };
  const data = await loadWorkspace('http://h/api/', {request});
  assert.equal(data.equipment[0].id, 'a1');
  await completeTask('http://h/api', {id: 't1', equipment_id: 'a1', completed_at: null}, {request});
  await completeTask('http://h/api', {id: 't1', equipment_id: 'a1', completed_at: '2026-10-30'}, {request});
  await addTask('http://h/api', {equipment_id: 'a1', title: 'Oil', due_date: '2026-11-01', notes: 'n'}, {request});
  assert.deepEqual(calls.slice(2), [
    ['POST', 'http://h/api/tasks/t1/complete', {}],
    ['PATCH', 'http://h/api/assets/a1/tasks/t1', {status: 'open'}],
    ['POST', 'http://h/api/assets/a1/tasks', {title: 'Oil', due_date: '2026-11-01', description: 'n', repeat_every_days: null}]
  ]);
  const failing = async () => ({ok: false, status: 404, json: async () => ({detail: "Asset 'x' not found"})});
  await assert.rejects(addTask('http://h/api', {equipment_id: 'x'}, {request: failing}), /Asset 'x' not found/);
});

test('assistant sends a photo as multipart form data', async () => {
  let captured;
  const image = new File([new Uint8Array([137, 80, 78, 71])], 'seal.png', {type: 'image/png'});
  const answer = await askAssistant('http://h/api', 'a1', 'Is this OK?', {image, request: async (url, options) => {
    captured = {url, options};
    return {ok: true, json: async () => ({answer: 'The seal is cracked.'})};
  }});
  assert.equal(answer, 'The seal is cracked.');
  assert.equal(captured.url, 'http://h/api/assistant');
  assert.equal(captured.options.headers, undefined); // the browser adds the multipart boundary
  assert.ok(captured.options.body instanceof FormData);
  assert.equal(captured.options.body.get('equipment_id'), 'a1');
  assert.equal(captured.options.body.get('message'), 'Is this OK?');
  assert.equal(captured.options.body.get('image').name, 'seal.png');
});

test('recurring tasks map to and from the backend', async () => {
  const base = {id: 't', asset_id: 'a', title: 'Oil', due_date: '2026-11-01', description: '', notes: ''};
  assert.equal(toTask({...base, status: 'open', interval_days: 30, schedule_id: 'schedule:s1'}).recurrence, 'monthly');
  assert.equal(toTask({...base, status: 'open', interval_days: 180, schedule_id: 'service'}).recurrence, 'every 180 days');
  assert.equal(toTask({...base, status: 'open', interval_days: null, schedule_id: null}).recurrence, 'none');
  assert.equal(toTask({...base, status: 'done', schedule_id: 'schedule:s1'}).reopen_locked, true);
  assert.equal(toTask({...base, status: 'done', schedule_id: null}).reopen_locked, false);
  const sent = [];
  const request = async (url, options) => { sent.push(JSON.parse(options.body)); return {ok: true, status: 201, json: async () => ({})}; };
  await addTask('http://h/api', {equipment_id: 'a', title: 'Oil', due_date: '2026-11-01', notes: '', recurrence: 'quarterly'}, {request});
  await addTask('http://h/api', {equipment_id: 'a', title: 'Once', due_date: '2026-11-01', notes: '', recurrence: 'none'}, {request});
  assert.equal(sent[0].repeat_every_days, 91);
  assert.equal(sent[1].repeat_every_days, null);
});
