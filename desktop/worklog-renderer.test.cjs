const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'life-workspace.html'), 'utf8');
const renderer = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].find(([, attributes, body]) => !/\bsrc\s*=/.test(attributes) && body.includes('plannerTimeMinutes'))?.[2];
assert.ok(renderer, 'life-workspace.html must contain the renderer script');
const start = renderer.indexOf('  function collectFocusSessions()');
const end = renderer.indexOf('  function renderPlannerWorklog()', start);
assert.ok(start >= 0 && end > start, 'worklog helpers must exist');

function worklog(records = [], focusSessions = []) {
  const context = { state: { records, settings: { focusSessions } } };
  vm.runInNewContext(renderer.slice(start, end), context, { timeout: 1500 });
  return context;
}

test('task-linked and standalone sessions become one chronological report', () => {
  const context = worklog([
    { id: 'task-a', type: 'planner', sample: false, data: { title: '写方案', list: '工作', sessions: [
      { id: 'session-a', date: '2026-09-28', seconds: 75, mode: 'pomodoro', startedAt: '2026-09-28T09:00:00.000Z', endedAt: '2026-09-28T09:01:15.000Z' },
    ] } },
  ], [
    { id: 'session-b', date: '2026-09-27', seconds: 120, mode: 'flowtime', taskTitle: '阅读', startedAt: '2026-09-27T08:00:00.000Z' },
  ]);
  const sessions = context.collectFocusSessions();
  assert.equal(sessions.length, 2);
  assert.equal(sessions[0].date, '2026-09-27');
  assert.equal(sessions[0].standalone, true);
  assert.equal(sessions[1].taskId, 'task-a');
  assert.equal(sessions[1].list, '工作');
  assert.equal(sessions[1].seconds, 75);
});

test('invalid dates, zero-length sessions, and sample tasks are excluded', () => {
  const context = worklog([
    { id: 'sample', type: 'planner', sample: true, data: { title: '示例', sessions: [{ id: 's1', date: '2026-09-28', seconds: 99 }] } },
    { id: 'bad-date', type: 'planner', sample: false, data: { title: '坏日期', sessions: [{ id: 's2', date: 'not-a-date', seconds: 10 }] } },
    { id: 'zero', type: 'planner', sample: false, data: { title: '零时长', sessions: [{ id: 's3', date: '2026-09-28', seconds: 0 }] } },
  ], [{ id: 'negative', date: '2026-09-28', seconds: -10 }]);
  assert.equal(context.collectFocusSessions().length, 0);
});

test('CSV keeps a UTF-8 BOM, quotes values, and protects formula-like task names', () => {
  const context = worklog();
  const csv = context.focusWorklogCsv([{
    date: '2026-09-28', startedAt: '2026-09-28T09:00:00.000Z', endedAt: '2026-09-28T09:01:00.000Z',
    taskTitle: '=HYPERLINK("https://example.invalid","x")', list: '工作,项目', mode: 'flowtime', seconds: 60,
  }]);
  assert.ok(csv.startsWith('\uFEFF'));
  assert.ok(csv.includes('"\'=HYPERLINK(""https://example.invalid"",""x"")"'));
  assert.ok(csv.includes('"工作,项目"'));
  assert.ok(csv.includes('"Flowtime"'));
});
