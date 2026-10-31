import test from 'node:test';
import assert from 'node:assert/strict';
import {canReopenTask, createEquipment, createTask, demoData, loadState, localDate, nextRecurringDate, saveState, selectTasks, shiftDate, STORAGE_KEY, taskStatus, toggleTask, validDate, validateState} from '../src/model.mjs';
import {askAssistant} from '../src/api.mjs';

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

test('photo diagnosis sends multipart data without setting Content-Type', async () => {
  const image = new File(['photo'], 'fan.png', {type: 'image/png'});
  let captured;
  await askAssistant('/api', 'eq-003', 'Does this look damaged?', {
    image,
    request: async (_url, options) => {captured = options; return {ok: true, json: async () => ({answer: 'Check the manual.'})};}
  });
  assert.equal(captured.headers, undefined);
  assert.equal(captured.body.get('equipment_id'), 'eq-003');
  assert.equal(captured.body.get('message'), 'Does this look damaged?');
  assert.equal(captured.body.get('image').name, 'fan.png');
});
