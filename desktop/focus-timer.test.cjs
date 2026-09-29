const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'life-workspace.html'), 'utf8');
const renderer = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].find(([, attributes, body]) => !/\bsrc\s*=/.test(attributes) && body.includes('plannerTimeMinutes'))?.[2];
assert.ok(renderer, 'life-workspace.html must contain the renderer script');
const timerStart = renderer.indexOf('  function flowTimerState()');
const timerEnd = renderer.indexOf('  function initDailyFlow()', timerStart);
assert.ok(timerStart >= 0 && timerEnd > timerStart, 'focus timer helpers must exist');

function localDate(timestamp) {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function createFocusHarness({ mode = 'pomodoro', startAt = new Date(2026, 8, 28, 9).getTime(), records = [], savedState = null } = {}) {
  let now = startAt;
  let nextId = 0;
  let nextInterval = 0;
  let saveResult = true;
  const elements = {
    flowTimer: { textContent: '' },
    flowTimerProgress: { style: {} },
    flowTimerMode: { value: mode },
    flowTimerMinutes: { value: '25', disabled: false },
    flowFocusTask: { value: '', disabled: false },
    flowTimerStatus: { textContent: '' },
    flowTimerStart: { textContent: '' },
    flowTimerReset: { textContent: '' },
  };
  const state = savedState || {
    records,
    settings: {
      dailyFlowFocusTask: '',
      focusSessions: [],
      flowTimer: {
        mode, durationSeconds: mode === 'countdown' ? 300 : mode === 'flowtime' ? 0 : 1500,
        remainingSeconds: mode === 'countdown' ? 300 : mode === 'flowtime' ? 0 : 1500,
        elapsedSeconds: 0, running: false, checkpointAt: null, sessionId: '', taskId: '', taskTitle: '',
      },
    },
  };
  class TestDate extends Date {
    static now() { return now; }
  }
  const context = {
    state,
    flowTimerInterval: null,
    Date: TestDate,
    document: { getElementById: id => elements[id] || null },
    syncCustomSelect: () => {},
    uid: () => `focus-${++nextId}`,
    isoDate: () => localDate(now),
    plannerTrackedDurationText: seconds => `${Math.floor(Number(seconds) || 0)}秒`,
    copyState: () => JSON.parse(JSON.stringify(context.state)),
    restoreState: previous => { context.state = previous; },
    saveState: () => saveResult,
    toast: () => {},
    setInterval: () => ++nextInterval,
    clearInterval: () => {},
    LANG: 'zh',
  };
  vm.runInNewContext(renderer.slice(timerStart, timerEnd), context, { timeout: 1500 });
  return {
    context, elements, getNow: () => now,
    advance: seconds => { now += seconds * 1000; },
    setSaveResult: value => { saveResult = value; },
  };
}

function taskRecord(id = 'task-a', title = '写方案', date = '2026-09-28') {
  return { id, type: 'planner', date, sample: false, data: { title, done: false } };
}

test('task-linked focus time is saved in task sessions and pause/resume keeps the total', () => {
  const task = taskRecord();
  const { context, elements, advance } = createFocusHarness({ records: [task] });
  elements.flowFocusTask.value = '写方案';
  context.flowTimerStartOrPause();
  advance(20);
  context.flowTimerStartOrPause();
  assert.equal(context.state.records[0].data.trackedSeconds, 20);
  assert.equal(context.state.records[0].data.sessions[0].seconds, 20);
  assert.equal(context.flowTimerState().running, false);
  context.flowTimerStartOrPause();
  advance(15);
  context.flowTimerStartOrPause();
  assert.equal(context.state.records[0].data.trackedSeconds, 35);
  assert.equal(context.state.records[0].data.sessions.length, 2);
  assert.equal(context.flowTimerState().elapsedSeconds, 35);
});

test('ambiguous task names are stored as standalone focus instead of linking the wrong task', () => {
  const { context, elements, advance } = createFocusHarness({ records: [taskRecord('task-a'), taskRecord('task-b')] });
  elements.flowFocusTask.value = '写方案';
  context.flowTimerStartOrPause();
  advance(17);
  context.flowTimerStartOrPause();
  assert.equal(context.state.records[0].data.trackedSeconds, undefined);
  assert.equal(context.state.settings.focusSessions[0].seconds, 17);
  assert.equal(context.state.settings.focusSessions[0].taskId, '');
});

test('cancelled imported calendar tasks are not linked to new focus sessions', () => {
  const task = taskRecord('ical-todo:' + 'd'.repeat(64), '已取消的工作');
  task.data.externalTodo = { provider: 'ical-file', sourceId: 'ics-file:work', uid: 'cancelled', cancelled: true };
  const { context, elements, advance } = createFocusHarness({ records: [task] });
  elements.flowFocusTask.value = '已取消的工作';
  context.flowTimerStartOrPause();
  advance(12);
  context.flowTimerStartOrPause();
  assert.equal(context.state.records[0].data.trackedSeconds, undefined);
  assert.equal(context.state.settings.focusSessions[0].taskId, '');
  assert.equal(context.state.settings.focusSessions[0].seconds, 12);
});

test('a task cancelled during focus stops receiving new time while the timer keeps logging', () => {
  const task = taskRecord('ical-todo:' + 'e'.repeat(64), 'Cancel during focus');
  task.data.externalTodo = { provider: 'ical-file', sourceId: 'ics-file:work', uid: 'cancel-during-focus', cancelled: false };
  const { context, elements, advance, getNow } = createFocusHarness({ records: [task] });
  elements.flowFocusTask.value = task.data.title;
  context.flowTimerStartOrPause();
  advance(5);
  context.flowTimerApplyCheckpoint(getNow());
  task.data.externalTodo.cancelled = true;
  advance(7);
  context.flowTimerApplyCheckpoint(getNow());
  assert.equal(task.data.trackedSeconds, 5);
  assert.equal(context.state.settings.focusSessions[0].seconds, 7);
  assert.equal(context.state.settings.focusSessions[0].taskId, '');
  assert.equal(context.state.settings.flowTimer.taskId, '');
});

test('focus sessions are split at local midnight', () => {
  const startAt = new Date(2026, 8, 28, 23, 59, 50).getTime();
  const task = taskRecord('task-a', '写方案', localDate(startAt));
  const { context, elements, advance, getNow } = createFocusHarness({ startAt, records: [task] });
  elements.flowFocusTask.value = '写方案';
  context.flowTimerStartOrPause();
  advance(25);
  context.flowTimerApplyCheckpoint(getNow());
  const sessions = context.state.records[0].data.sessions;
  assert.equal(sessions.length, 2);
  assert.equal(sessions[0].seconds + sessions[1].seconds, 25);
  assert.notEqual(sessions[0].date, sessions[1].date);
  assert.equal(context.state.records[0].data.trackedSeconds, 25);
});

test('a running timer resumes from its saved checkpoint after a reload or crash', () => {
  const task = taskRecord();
  const first = createFocusHarness({ records: [task] });
  first.elements.flowFocusTask.value = '写方案';
  first.context.flowTimerStartOrPause();
  first.advance(20);
  first.context.flowTimerApplyCheckpoint(first.getNow());
  const persisted = JSON.parse(JSON.stringify(first.context.state));
  const second = createFocusHarness({ startAt: first.getNow() + 22_000, savedState: persisted });
  second.context.flowTimerRestore();
  assert.equal(second.context.state.records[0].data.trackedSeconds, 42);
  assert.equal(second.context.flowTimerState().elapsedSeconds, 42);
  assert.equal(second.context.flowTimerState().running, true);
});

test('a countdown that wakes late records only its remaining duration and completes once', () => {
  const { context, elements, advance } = createFocusHarness({ mode: 'countdown' });
  context.flowTimerStartOrPause();
  advance(400);
  context.flowTimerTick();
  const timer = context.flowTimerState();
  assert.equal(timer.elapsedSeconds, 300);
  assert.equal(timer.remainingSeconds, 0);
  assert.equal(timer.running, false);
  assert.equal(context.state.settings.focusSessions[0].seconds, 300);
});

test('Flowtime records elapsed time without a countdown cap', () => {
  const { context, elements, advance } = createFocusHarness({ mode: 'pomodoro' });
  elements.flowTimerMode.value = 'flowtime';
  context.flowTimerChangeMode();
  context.flowTimerStartOrPause();
  advance(508);
  context.flowTimerStartOrPause();
  assert.equal(context.flowTimerState().elapsedSeconds, 508);
  assert.equal(context.state.settings.focusSessions[0].seconds, 508);
  assert.equal(context.flowTimerState().remainingSeconds, 0);
});

test('failed local save rolls back both worklog changes and the timer checkpoint', () => {
  const task = taskRecord();
  const harness = createFocusHarness({ records: [task] });
  const { context, elements, advance, getNow } = harness;
  elements.flowFocusTask.value = '写方案';
  context.flowTimerStartOrPause();
  const checkpointAt = context.flowTimerState().checkpointAt;
  harness.setSaveResult(false);
  advance(18);
  const result = context.flowTimerApplyCheckpoint(getNow());
  assert.equal(result.ok, false);
  assert.equal(context.state.records[0].data.trackedSeconds, undefined);
  assert.equal(context.flowTimerState().checkpointAt, checkpointAt);
  assert.equal(context.flowTimerState().running, true);
});

test('reset commits the partial session before resetting the timer face', () => {
  const { context, elements, advance } = createFocusHarness();
  elements.flowFocusTask.value = '临时整理';
  context.flowTimerStartOrPause();
  advance(31);
  context.flowTimerReset();
  assert.equal(context.state.settings.focusSessions[0].seconds, 31);
  assert.equal(context.flowTimerState().elapsedSeconds, 0);
  assert.equal(context.flowTimerState().remainingSeconds, 1500);
  assert.equal(context.flowTimerState().running, false);
});
