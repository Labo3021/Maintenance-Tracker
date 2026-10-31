import test from 'node:test';
import assert from 'node:assert/strict';
import {answerDraftQuestion, completeBackendTask, diagnosePhoto, identifyPhoto, saveIdentifiedAsset, snoozeTask, toTask} from '../src/demoApi.mjs';

const photo = new File(['image bytes'], 'item.jpg', {type: 'image/jpeg'});
const okay = data => ({ok: true, status: 200, json: async () => data});

test('diagnosis sends image, optional asset and symptoms to /api/diagnose', async () => {
  let seen;
  const result = await diagnosePhoto('http://localhost:8000/api/', photo, 'asset-1', 'noisy', {
    request: async (url, options) => {seen = {url, options}; return okay({diagnosis: {severity: 'high'}, task: {due_date: '2026-11-02'}, source: 'mock'});}
  });
  assert.equal(seen.url, 'http://localhost:8000/api/diagnose');
  assert.equal(seen.options.method, 'POST');
  assert.equal(seen.options.headers, undefined);
  assert.equal(seen.options.body.get('image').name, 'item.jpg');
  assert.equal(seen.options.body.get('asset_id'), 'asset-1');
  assert.equal(seen.options.body.get('notes'), 'noisy');
  assert.equal(result.task.due_date, '2026-11-02');
});

test('identification leaves equipment unsaved until edited draft is posted', async () => {
  let seen;
  const request = async (url, options) => {
    seen = {url, options};
    return okay(url.endsWith('/identify')
      ? {draft: {name: 'Fan', model: null, schedules: [{title: 'Clean', last_done: null, interval_days: 30}]}, questions: [{target: 'schedules.0.last_done', type: 'date'}]}
      : {name: JSON.parse(options.body).name});
  };
  const identified = await identifyPhoto('http://localhost:8000/api', photo, '', {request});
  assert.equal(seen.options.body.get('notes'), null);
  let draft = answerDraftQuestion(identified.draft, 'schedules.0.last_done', '2026-10-31');
  draft = answerDraftQuestion(draft, 'model', 'Breeze 300');
  assert.equal(identified.draft.schedules[0].last_done, null);
  await saveIdentifiedAsset('http://localhost:8000/api', draft, {request});
  assert.equal(seen.url, 'http://localhost:8000/api/assets');
  assert.equal(JSON.parse(seen.options.body).schedules[0].last_done, '2026-10-31');
  assert.equal(JSON.parse(seen.options.body).model, 'Breeze 300');
  assert.equal(answerDraftQuestion(draft, '__proto__.polluted', 'yes'), draft);
});

test('task actions use the backend routes and preserve next-task reply', async () => {
  const calls = [];
  const request = async (url, options) => {calls.push({url, options}); return okay({next_task: {due_date: '2026-11-30'}});};
  const task = toTask({id: 't-1', asset_id: 'a-1', title: 'Service', due_date: '2026-10-31', status: 'open', priority: 'high', kind: 'service'});
  assert.equal(task.kind, 'service');
  const done = await completeBackendTask('http://localhost:8000/api', task, {request});
  assert.equal(done.next_task.due_date, '2026-11-30');
  assert.equal(calls[0].url, 'http://localhost:8000/api/tasks/t-1/complete');
  await snoozeTask('http://localhost:8000/api', 't-1', 3, {request});
  assert.equal(calls[1].url, 'http://localhost:8000/api/tasks/t-1/snooze');
  assert.deepEqual(JSON.parse(calls[1].options.body), {days: 3});
});
