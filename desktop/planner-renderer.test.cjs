const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const { TextEncoder, TextDecoder } = require('node:util');
const WanxiangCalendar = require('./calendar-exchange.js');

const html = fs.readFileSync(path.join(__dirname, '..', 'life-workspace.html'), 'utf8');
const renderer = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].find(([, attributes, body]) => !/\bsrc\s*=/.test(attributes) && body.includes('plannerTimeMinutes'))?.[2];
assert.ok(renderer, 'life-workspace.html must contain the renderer script');

const plannerStart = renderer.indexOf('function plannerTimeMinutes(');
const plannerEnd = renderer.indexOf('function renderPlanner(){', plannerStart);
const toggleStart = renderer.indexOf('function toggleTask(');
const toggleEnd = renderer.indexOf('function bindEvents(', toggleStart);
const deleteStart = renderer.indexOf('function deleteRecord(');
const deleteEnd = renderer.indexOf('function switchView(', deleteStart);
const editStart = renderer.indexOf('function editPlannerTask(');
const cancelEditStart = renderer.indexOf('function cancelPlannerEdit(', editStart);
const cancelEditEnd = renderer.indexOf('function reschedulePlannerTask(', cancelEditStart);
const rescheduleStart = renderer.indexOf('function reschedulePlannerTask(');
const rescheduleEnd = renderer.indexOf('function scheduleNextPlannerTask(', rescheduleStart);
const mergeStart = renderer.indexOf('function mergePlan(');
const mergeEnd = renderer.indexOf('function mergeFitness(', mergeStart);
const reminderStart = renderer.indexOf('  function checkDueReminders()');
const reminderEnd = renderer.indexOf('function compressCover(', reminderStart);
const organizationStart = renderer.indexOf('  function plannerNormalizeProject(');
const organizationEnd = renderer.indexOf('  function setPlannerSelectedDate(', organizationStart);
const taskRowStart = renderer.indexOf('  function taskRow(');
const taskRowEnd = renderer.indexOf('  function recordRow(', taskRowStart);
const syncQueueStart = renderer.indexOf('  function plannerSyncSnapshot(');
const syncQueueEnd = renderer.indexOf('  var SAMPLES_CLEARED_KEY', syncQueueStart);
const todoTombstoneStart = renderer.indexOf('function normalizeCalendarTodoTombstones(');
const todoTombstoneEnd = renderer.indexOf('function normalizeState(', todoTombstoneStart);
const todoHelpersStart = renderer.indexOf('async function plannerCalendarTodoRecordId(');
const todoHelpersEnd = renderer.indexOf('function renderPlannerCalendarSources(', todoHelpersStart);
const todoMergeHelpersEnd = renderer.indexOf('const plannerCalendarRefreshes=new Set();', todoHelpersStart);
const calendarSourcesStart = renderer.indexOf('function normalizeCalendarSources(');
const calendarSourcesEnd = renderer.indexOf('function normalizeCalendarTodoTombstones(', calendarSourcesStart);
const calendarSourceIdStart = renderer.indexOf('function plannerCalendarSourceId(');
const calendarSourceIdEnd = renderer.indexOf('async function importPlannerCalendarFile(', calendarSourceIdStart);
const calendarImportStart = calendarSourceIdEnd;
const calendarImportEnd = renderer.indexOf('async function removePlannerCalendarSource(', calendarImportStart);
const calendarSubscriptionsStart = renderer.indexOf('const plannerCalendarRefreshes=new Set();');
const calendarSubscriptionsEnd = renderer.indexOf('function exportPlannerCalendar(', calendarSubscriptionsStart);
const calendarCalDavSourceStart = renderer.indexOf('function normalizeCalendarSources(');
const calendarCalDavSourceEnd = renderer.indexOf('function normalizeState(', calendarCalDavSourceStart);
const backupCryptoStart = renderer.indexOf('const ENCRYPTED_BACKUP_ITERATIONS=');
const backupCryptoEnd = renderer.indexOf('function requestBackupPassphrase(', backupCryptoStart);
const backupRollbackStart = renderer.indexOf('function rollbackBackupExportCounters(');
const backupRollbackEnd = renderer.indexOf('function exportFullBackup(', backupRollbackStart);
assert.ok(plannerStart >= 0 && plannerEnd > plannerStart, 'planner helpers and timeline must exist');
assert.ok(toggleStart >= 0 && toggleEnd > toggleStart, 'planner completion handler must exist');
assert.ok(deleteStart >= 0 && deleteEnd > deleteStart, 'record deletion handler must exist');
assert.ok(editStart >= 0 && cancelEditStart > editStart && cancelEditEnd > cancelEditStart, 'planner edit handlers must exist');
assert.ok(rescheduleStart >= 0 && rescheduleEnd > rescheduleStart, 'planner reschedule handler must exist');
assert.ok(mergeStart >= 0 && mergeEnd > mergeStart, 'cloud planner merge must exist');
assert.ok(reminderStart >= 0 && reminderEnd > reminderStart, 'planner reminder handler must exist');
assert.ok(organizationStart >= 0 && organizationEnd > organizationStart, 'planner project/tag helpers must exist');
assert.ok(taskRowStart >= 0 && taskRowEnd > taskRowStart, 'planner task row renderer must exist');
assert.ok(syncQueueStart >= 0 && syncQueueEnd > syncQueueStart, 'persistent planner sync queue must exist');
assert.ok(todoTombstoneStart >= 0 && todoTombstoneEnd > todoTombstoneStart, 'calendar task tombstones must be normalized');
assert.ok(todoHelpersStart >= 0 && todoHelpersEnd > todoHelpersStart, 'calendar task merge helpers must exist');
assert.ok(todoMergeHelpersEnd > todoHelpersStart, 'calendar task merge helpers must end before calendar UI state');
assert.ok(calendarSourcesStart >= 0 && calendarSourcesEnd > calendarSourcesStart, 'calendar sources must be normalized');
assert.ok(calendarSourceIdStart >= 0 && calendarSourceIdEnd > calendarSourceIdStart, 'calendar sources need stable names');
assert.ok(calendarImportStart >= 0 && calendarImportEnd > calendarImportStart, 'calendar import must exist');
assert.ok(calendarSubscriptionsStart >= 0 && calendarSubscriptionsEnd > calendarSubscriptionsStart, 'online calendar subscriptions must exist');
assert.ok(calendarCalDavSourceStart >= 0 && calendarCalDavSourceEnd > calendarCalDavSourceStart, 'CalDAV sources must be normalized');
assert.ok(backupCryptoStart >= 0 && backupCryptoEnd > backupCryptoStart, 'portable backup encryption helpers must exist');

class ElementStub {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.className = '';
    this.textContent = '';
  }

  appendChild(node) { this.children.push(node); return node; }
  append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}

function createPlannerHarness(records = [], calendarSources = []) {
  let nextId = 0;
  let saveResult = true;
  const pushed = [];
  const elements = {
    plannerTimeline: new ElementStub('div'),
    plannerDayLoad: new ElementStub('span'),
    plannerConflictNotice: new ElementStub('div'),
    plannerFreeSlots: new ElementStub('div'),
    plannerBoard: new ElementStub('div'),
    plannerMatrix: new ElementStub('div'),
    plannerCalendarSources: new ElementStub('div'),
    plannerCalendarStatus: new ElementStub('span'),
  };
  const context = {
    state: { records, calendarSources, settings: { plannerBoardOrder: { todo: [], inprogress: [], done: [] }, plannerCustomBoards: [], plannerCustomBoardOrders: {}, calendarTodoTombstones: [] } },
    WanxiangCalendar: { eventOccurrencesForDay: () => [] },
    SEED_REMOTE: false,
    uid: () => `planner-test-${++nextId}`,
    LANG: 'zh',
    normalizeCalendarTodoTombstones: value => [...new Set(Array.isArray(value) ? value.filter(id => typeof id === 'string' && /^(?:ical|caldav)-todo:[a-f0-9]{64}$/.test(id)) : [])].slice(-12000),
    plannerSelectedDate: '2026-09-28',
    plannerWeekStart: '2026-09-28',
    completionPulses: { task: '' },
    plannerCalDavWrites: new Set(),
    window: { wanxiangDesktop: {} },
    document: {
      getElementById: id => elements[id],
      createElement: tagName => new ElementStub(tagName),
    },
    t: value => value,
    titleFor: record => record.data.title,
    recordTitleHtml: record => record.data.title,
    copyState: () => JSON.parse(JSON.stringify(context.state)),
    restoreState: previous => { context.state = previous; },
    saveState: () => saveResult,
    confirm: () => true,
    enqueuePlannerUpsert: () => {},
    enqueuePlannerDelete: () => {},
    flushPlannerSyncQueue: () => {},
    renderPlannerSyncState: () => {},
    updateRemotePlan: () => {},
    pushPlan: record => pushed.push(record.id),
    pulseCompletion: () => {},
    renderAll: () => {},
    announceCompletion: () => {},
    toast: () => {},
    syncCustomSelect: () => {},
    isoDate: () => '2026-09-28',
    shiftPlannerDate: () => '2026-10-04',
  };
  vm.runInNewContext(
    renderer.slice(plannerStart, plannerEnd) + '\n'
      + renderer.slice(toggleStart, toggleEnd) + '\n'
      + renderer.slice(deleteStart, deleteEnd) + '\n'
      + renderer.slice(rescheduleStart, rescheduleEnd) + '\n'
      + renderer.slice(mergeStart, mergeEnd),
    context,
    { timeout: 1500 },
  );
  return {
    context,
    elements,
    pushed,
    setSaveResult: value => { saveResult = value; },
  };
}

function createPlannerSyncHarness({ queue = [], records = [], addRecord, updateRecord, deleteRecord, query } = {}) {
  let nextId = 0;
  const calls = [];
  const context = {
    state: { records, settings: { plannerSyncQueue: queue } },
    ONLINE: true, LOCAL_ONLY: false, PLANNER_SYNC_RUNNING: false, PLANNER_SYNC_FAILED: false,
    PLANNER_SYNC_WAITERS: [], DB_PLAN: 'planner-db', LANG: 'zh',
    uid: () => `sync-test-${++nextId}`,
    document: { getElementById: () => null },
    renderPlannerSyncState: () => {}, saveState: () => true,
    goLocalOnly: () => { context.LOCAL_ONLY = true; context.PLANNER_SYNC_FAILED = true; },
    db: {
      addRecord: args => { calls.push({ kind: 'add', ...args }); return addRecord ? addRecord(args) : Promise.resolve({ id: 'remote-created' }); },
      updateRecord: args => { calls.push({ kind: 'update', ...args }); return updateRecord ? updateRecord(args) : Promise.resolve({}); },
      deleteRecord: args => { calls.push({ kind: 'delete', ...args }); return deleteRecord ? deleteRecord(args) : Promise.resolve({}); },
      query: args => { calls.push({ kind: 'query', ...args }); return query ? query(args) : Promise.resolve({ results: [], hasMore: false }); },
    },
  };
  vm.runInNewContext(renderer.slice(syncQueueStart, syncQueueEnd), context, { timeout: 1500 });
  return { context, calls };
}

function createCalendarTodoHarness() {
  const context = { crypto: webcrypto, TextEncoder, Uint8Array, LANG: 'zh' };
  vm.runInNewContext(
    renderer.slice(todoTombstoneStart, todoTombstoneEnd) + '\n'
      + renderer.slice(todoHelpersStart, todoHelpersEnd),
    context,
    { timeout: 1500 },
  );
  return context;
}

function createCalDavRendererHarness(records = []) {
  let saveResult = true;
  const context = {
    state: { records, calendarSources: [], settings: { calendarTodoTombstones: [] } },
    crypto: webcrypto, TextEncoder, Uint8Array, WanxiangCalendar, LANG: 'zh',
    window: { wanxiangDesktop: { commitCalDavSync: async () => true } },
    normalizeCalendarSources: value => value,
    copyState: () => JSON.parse(JSON.stringify(context.state)),
    restoreState: previous => { context.state = previous; },
    saveState: () => saveResult,
    renderAll: () => {},
    renderPlannerCalendarSources: () => {},
    isoDate: () => '2026-09-29',
    toast: () => {},
    syncCustomSelect: () => {},
    console,
  };
  vm.runInNewContext(
    renderer.slice(calendarCalDavSourceStart, calendarCalDavSourceEnd) + '\n'
      + renderer.slice(todoHelpersStart, todoMergeHelpersEnd) + '\n'
      + renderer.slice(calendarSubscriptionsStart, calendarSubscriptionsEnd),
    context,
    { timeout: 1500 },
  );
  return { context, setSaveResult: value => { saveResult = value; } };
}

function createCalendarImportHarness() {
  let saveResult = true;
  const status = { textContent: '' }, messages = [];
  const context = {
    state: { records: [], calendarSources: [], settings: { calendarTodoTombstones: [] } },
    crypto: webcrypto, TextEncoder, Uint8Array, WanxiangCalendar, LANG: 'zh',
    document: { getElementById: () => status },
    normalizeCalendarTodoTombstones: value => [...new Set(Array.isArray(value) ? value.filter(id => typeof id === 'string' && /^ical-todo:[a-f0-9]{64}$/.test(id)) : [])].slice(-12000),
    copyState: () => JSON.parse(JSON.stringify(context.state)),
    restoreState: previous => { context.state = previous; },
    saveState: () => saveResult,
    renderAll: () => {},
    isoDate: () => '2026-09-29',
    toast: message => messages.push(message),
    confirm: () => true,
  };
  vm.runInNewContext(
    renderer.slice(calendarSourcesStart, calendarSourcesEnd) + '\n'
      + renderer.slice(todoTombstoneStart, todoTombstoneEnd) + '\n'
      + renderer.slice(todoHelpersStart, todoHelpersEnd) + '\n'
      + renderer.slice(calendarSourceIdStart, calendarSourceIdEnd) + '\n'
      + renderer.slice(calendarImportStart, calendarImportEnd),
    context,
    { timeout: 1500 },
  );
  return { context, status, messages, setSaveResult: value => { saveResult = value; } };
}

function createCalendarSubscriptionRendererHarness({ sources = [], api = {}, saveResult = true } = {}) {
  let canSave = saveResult;
  const messages = [], commits = [];
  const context = {
    state: { records: [], calendarSources: sources, settings: { calendarTodoTombstones: [] } },
    crypto: webcrypto, TextEncoder, Uint8Array, WanxiangCalendar, LANG: 'zh',
    window: { wanxiangDesktop: {
      commitCalendarSubscription: async (id, token) => { commits.push({ id, token }); return true; },
      ...api,
    } },
    document: { getElementById: () => ({ textContent: '' }), createElement: tagName => new ElementStub(tagName) },
    copyState: () => JSON.parse(JSON.stringify(context.state)),
    restoreState: previous => { context.state = previous; },
    normalizeCalendarSources: undefined,
    saveState: () => canSave,
    renderAll: () => {},
    renderPlannerCalendarSources: () => {},
    confirm: () => true,
    toast: message => messages.push(message),
    console,
  };
  vm.runInNewContext(
    renderer.slice(calendarSourcesStart, calendarSourcesEnd) + '\n'
      + renderer.slice(calendarSubscriptionsStart, calendarSubscriptionsEnd),
    context,
    { timeout: 1500 },
  );
  return { context, messages, commits, setSaveResult: value => { canSave = value; } };
}

test('calendar file import adds VTODOs, replaces by source UID, and rolls back a failed save', async () => {
  const harness = createCalendarImportHarness();
  const makeIcs = title => [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'X-WR-CALNAME:Local tasks',
    'BEGIN:VTODO', 'UID:todo-1@example.test', 'SUMMARY:' + title, 'DTSTART;TZID=Asia/Shanghai:20260930T093000',
    'DUE;VALUE=DATE:20260930', 'STATUS:IN-PROCESS', 'PERCENT-COMPLETE:25', 'PRIORITY:1', 'END:VTODO',
    'END:VCALENDAR',
  ].join('\r\n');
  const file = text => ({ name: 'tasks.ics', size: Buffer.byteLength(text, 'utf8'), text: async () => text });
  await harness.context.importPlannerCalendarFile(file(makeIcs('First title')));
  assert.equal(harness.context.state.records.length, 1);
  assert.equal(harness.context.state.calendarSources.length, 1);
  assert.equal(harness.context.state.calendarSources[0].todoCount, 1);
  assert.equal(harness.context.state.records[0].data.title, 'First title');
  assert.equal(harness.context.state.records[0].data.time, '09:30');
  await harness.context.importPlannerCalendarFile(file(makeIcs('First title')));
  assert.equal(harness.context.state.records.length, 1);
  harness.context.state.records[0].data.estimateMin = 90;
  await harness.context.importPlannerCalendarFile(file(makeIcs('Updated title')));
  assert.equal(harness.context.state.records.length, 1);
  assert.equal(harness.context.state.records[0].data.title, 'Updated title');
  assert.equal(harness.context.state.records[0].data.estimateMin, 90);
  const savedTitle = harness.context.state.records[0].data.title;
  const savedSource = harness.context.state.calendarSources[0].icsText;
  harness.setSaveResult(false);
  await harness.context.importPlannerCalendarFile(file(makeIcs('Should roll back')));
  assert.equal(harness.context.state.records[0].data.title, savedTitle);
  assert.equal(harness.context.state.calendarSources[0].icsText, savedSource);
  assert.ok(harness.messages.some(message => message === '这个日历文件已是最新，无需重复导入。'));
});

test('calendar subscription refresh replaces only its cached events and commits validators after local save', async () => {
  const harness = createCalendarSubscriptionRendererHarness();
  const id = '12345678-1234-4234-8234-123456789abc';
  const result = {
    kind: 'updated', id, name: 'Team calendar', host: 'calendar.example.test',
    eventCount: 1, lastAttemptAt: '2026-09-29T09:00:00.000Z', lastSuccessAt: '2026-09-29T09:00:00.000Z',
    icsText: [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', 'UID:meeting@example.test',
      'DTSTART:20260929T090000Z', 'DTEND:20260929T100000Z', 'SUMMARY:Planning meeting',
      'END:VEVENT', 'END:VCALENDAR', '',
    ].join('\r\n'), commitToken: 'one-time-token',
  };
  assert.equal(await harness.context.applyPlannerCalendarSubscriptionResult(result), true);
  const source = harness.context.state.calendarSources[0];
  assert.equal(source.id, `ics-subscription:${id}`);
  assert.equal(source.type, 'ics-subscription');
  assert.equal(source.subscriptionId, id);
  assert.equal(source.eventCount, 1);
  assert.match(source.icsText, /SUMMARY:Planning meeting/);
  assert.equal(JSON.stringify(source).includes('calendar.example.test/feed'), false);
  assert.deepEqual(harness.commits.map(item => ({ ...item })), [{ id, token: 'one-time-token' }]);
});

test('not-modified refresh preserves local calendar bytes and save failure does not acknowledge the server token', async () => {
  const id = '22345678-1234-4234-8234-123456789abc';
  const cached = {
    id: `ics-subscription:${id}`, subscriptionId: id, type: 'ics-subscription', name: 'Team', host: 'calendar.example.test',
    icsText: 'cached calendar content', eventCount: 3, todoCount: 0, lastError: 'old error',
  };
  const harness = createCalendarSubscriptionRendererHarness({ sources: [cached] });
  const result = { kind: 'not-modified', id, name: 'Team', host: cached.host, eventCount: 3, lastSuccessAt: '2026-09-29T10:00:00.000Z', commitToken: '304-token' };
  assert.equal(await harness.context.applyPlannerCalendarSubscriptionResult(result), true);
  assert.equal(harness.context.state.calendarSources[0].icsText, cached.icsText);
  assert.equal(harness.context.state.calendarSources[0].lastError, '');
  assert.equal(harness.commits.length, 1);

  const failed = createCalendarSubscriptionRendererHarness({ sources: [cached], saveResult: false });
  assert.equal(await failed.context.applyPlannerCalendarSubscriptionResult(result), false);
  assert.equal(failed.context.state.calendarSources[0].icsText, cached.icsText);
  assert.equal(failed.commits.length, 0);
});

test('subscription failures retain prior events and surface a bounded status message', async () => {
  const id = '32345678-1234-4234-8234-123456789abc';
  const cached = { id: `ics-subscription:${id}`, subscriptionId: id, type: 'ics-subscription', name: 'Team', host: 'calendar.example.test', icsText: 'old feed', eventCount: 2, todoCount: 0 };
  const harness = createCalendarSubscriptionRendererHarness({ sources: [cached] });
  const result = { kind: 'error', id, error: 'HTTP 503; cached calendar retained.', subscription: { id, name: 'Team', host: cached.host, eventCount: 2, lastAttemptAt: '2026-09-29T11:00:00.000Z', lastSuccessAt: '', lastError: 'HTTP 503; cached calendar retained.' } };
  assert.equal(await harness.context.applyPlannerCalendarSubscriptionResult(result), true);
  assert.equal(harness.context.state.calendarSources[0].icsText, 'old feed');
  assert.match(harness.context.state.calendarSources[0].lastError, /HTTP 503/);
  assert.equal(harness.commits.length, 0);
});

test('startup recovers missing subscription cache with an unconditional refresh', async () => {
  const id = '42345678-1234-4234-8234-123456789abc';
  const calls = [];
  const harness = createCalendarSubscriptionRendererHarness({ api: {
    listCalendarSubscriptions: async () => [{ id, name: 'Team', host: 'calendar.example.test', eventCount: 0 }],
    refreshCalendarSubscription: async (subscriptionId, force) => {
      calls.push({ subscriptionId, force });
      return {
        kind: 'updated', id, name: 'Team', host: 'calendar.example.test', eventCount: 1,
        icsText: ['BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', 'UID:restored', 'DTSTART:20260929T090000Z', 'DTEND:20260929T100000Z', 'SUMMARY:Recovered', 'END:VEVENT', 'END:VCALENDAR'].join('\r\n'),
      };
    },
  } });
  await harness.context.initializePlannerCalendarSubscriptions();
  assert.deepEqual(calls.map(item => ({ ...item })), [{ subscriptionId: id, force: true }]);
  assert.equal(harness.context.state.calendarSources[0].eventCount, 1);
  assert.match(harness.context.state.calendarSources[0].icsText, /SUMMARY:Recovered/);
});

test('removing a subscription ignores an in-flight result instead of recreating its cached source', async () => {
  const id = '52345678-1234-4234-8234-123456789abc';
  const source = { id: `ics-subscription:${id}`, subscriptionId: id, type: 'ics-subscription', name: 'Team', host: 'calendar.example.test', icsText: 'cached calendar', eventCount: 1, todoCount: 0 };
  const harness = createCalendarSubscriptionRendererHarness({ sources: [source], api: { removeCalendarSubscription: async () => true } });
  await harness.context.removePlannerCalendarSource(source.id);
  assert.equal(harness.context.state.calendarSources.length, 0);
  const stale = { kind: 'updated', id, name: 'Team', host: source.host, icsText: source.icsText, eventCount: 1, commitToken: 'late-token' };
  assert.equal(await harness.context.applyPlannerCalendarSubscriptionResult(stale), false);
  assert.equal(harness.context.state.calendarSources.length, 0);
  assert.equal(harness.commits.length, 0);
});

test('imported calendar tasks use stable source-scoped IDs', async () => {
  const context = createCalendarTodoHarness();
  const first = await context.plannerCalendarTodoRecordId('ics-file:work', 'task@example.test');
  const repeated = await context.plannerCalendarTodoRecordId('ics-file:work', 'task@example.test');
  const otherSource = await context.plannerCalendarTodoRecordId('ics-file:home', 'task@example.test');
  assert.match(first, /^ical-todo:[a-f0-9]{64}$/);
  assert.equal(first, repeated);
  assert.notEqual(first, otherSource);
});

test('calendar task re-import updates source fields and preserves local work', async () => {
  const context = createCalendarTodoHarness();
  const sourceId = 'ics-file:work';
  const original = {
    uid: 'task-1', title: 'Draft', description: 'Initial note', url: '', date: '2026-09-30', time: '09:00',
    priority: 'normal', status: 'todo', done: false, cancelled: false, percentComplete: 0, completedAt: '',
  };
  const imported = await context.mergePlannerCalendarTodos([], sourceId, [original], [], '2026-09-29', 'first-import');
  assert.equal(imported.length, 1);
  const record = imported[0];
  Object.assign(record.data, { estimateMin: 75, trackedSeconds: 1800, sessions: [{ seconds: 1800 }], project: '毕业设计', tags: ['写作'], list: '工作', remind: true });
  const updatedTodo = { ...original, title: 'Draft v2', description: 'Updated source note', time: '10:30', priority: 'high', status: 'inprogress', percentComplete: 40 };
  const updated = await context.mergePlannerCalendarTodos([record], sourceId, [updatedTodo], [], '2026-09-29', 'second-import');
  assert.equal(updated.length, 1);
  assert.equal(updated[0].id, record.id);
  assert.equal(updated[0].data.title, 'Draft v2');
  assert.equal(updated[0].data.note, 'Updated source note');
  assert.equal(updated[0].data.time, '10:30');
  assert.equal(updated[0].data.status, 'inprogress');
  assert.equal(updated[0].data.estimateMin, 75);
  assert.equal(updated[0].data.trackedSeconds, 1800);
  assert.deepEqual(Array.from(updated[0].data.sessions, item => ({ ...item })), [{ seconds: 1800 }]);
  assert.equal(updated[0].data.project, '毕业设计');
  assert.deepEqual(Array.from(updated[0].data.tags), ['写作']);
  assert.equal(updated[0].data.list, '工作');
  assert.equal(updated[0].data.remind, true);
  assert.equal(updated[0].data.externalTodo.sourceMissing, false);
  assert.equal(record.data.title, 'Draft', 'the previous state remains untouched until the caller saves');
});

test('missing and deleted source tasks are retained or tombstoned without resurrection', async () => {
  const context = createCalendarTodoHarness();
  const sourceId = 'ics-file:work';
  const task = (uid, title) => ({ uid, title, description: '', url: '', date: '2026-09-30', time: '', priority: 'normal', status: 'todo', done: false, cancelled: false, percentComplete: 0, completedAt: '' });
  const initial = await context.mergePlannerCalendarTodos([], sourceId, [task('keep', 'Keep'), task('delete', 'Delete')], [], '2026-09-29', 'import');
  const deletedId = await context.plannerCalendarTodoRecordId(sourceId, 'delete');
  const partial = await context.mergePlannerCalendarTodos(initial, sourceId, [task('keep', 'Keep')], [deletedId], '2026-09-29', 'refresh');
  assert.equal(partial.length, 1);
  assert.equal(partial[0].data.externalTodo.sourceMissing, false);
  const removedSnapshot = await context.mergePlannerCalendarTodos(partial, sourceId, [], [], '2026-09-29', 'replacement');
  assert.equal(removedSnapshot.length, 1);
  assert.equal(removedSnapshot[0].data.externalTodo.sourceMissing, true);
  const sameUidFromOtherSource = await context.mergePlannerCalendarTodos([], 'ics-file:home', [task('keep', 'Other copy')], [], '2026-09-29', 'import');
  assert.notEqual(sameUidFromOtherSource[0].id, initial[0].id);
  const deletedAgain = await context.mergePlannerCalendarTodos(initial, sourceId, [task('delete', 'Delete again')], [deletedId], '2026-09-29', 'refresh');
  assert.equal(deletedAgain.some(record => record.id === deletedId), false);
});

test('cancelled calendar tasks cannot be completed and are not treated as done', async () => {
  const cancelled = {
    uid: 'cancelled', title: 'Cancelled', description: '', url: '', date: '2026-09-30', time: '09:00',
    priority: 'normal', status: 'cancelled', done: false, cancelled: true, percentComplete: 0, completedAt: '',
  };
  const imported = await createCalendarTodoHarness().mergePlannerCalendarTodos([], 'ics-file:work', [cancelled], [], '2026-09-29', 'import');
  assert.equal(imported[0].data.done, false);
  assert.equal(imported[0].data.externalTodo.cancelled, true);
  const planner = createPlannerHarness(imported);
  assert.equal(planner.context.toggleTask(imported[0].id), false);
  assert.equal(planner.context.state.records[0].data.done, false);
});

test('planner sync queue coalesces repeated edits for the same local task', () => {
  const { context } = createPlannerSyncHarness();
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'First', list: '生活', done: false } };
  context.enqueuePlannerUpsert(task);
  const operationId = context.state.settings.plannerSyncQueue[0].id;
  task.data.title = 'Latest';
  context.enqueuePlannerUpsert(task);
  assert.equal(context.state.settings.plannerSyncQueue.length, 1);
  assert.equal(context.state.settings.plannerSyncQueue[0].id, operationId);
  assert.equal(context.state.settings.plannerSyncQueue[0].kind, 'upsert');
});

test('planner sync queue reload sanitizes entries and keeps only the newest intent per task', () => {
  const { context } = createPlannerSyncHarness();
  const normalized = context.normalizePlannerSyncQueue([
    { id: 'old', kind: 'upsert', localId: 'task-a', remoteId: '' },
    { id: 'bad', kind: 'rename', localId: 'task-b' },
    { id: 'new', kind: 'delete', localId: 'task-a', remoteId: 'remote-a' },
    null,
  ]);
  assert.deepEqual(Array.from(normalized, item => ({ ...item })), [
    { id: 'new', kind: 'delete', localId: 'task-a', remoteId: 'remote-a', attempted: false, snapshot: null },
  ]);
});

test('planner sync assigns the remote id and uploads an edit made during an in-flight create', async () => {
  let resolveCreate;
  const creating = new Promise(resolve => { resolveCreate = resolve; });
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Original', list: '生活', done: false } };
  const { context, calls } = createPlannerSyncHarness({ records: [task], addRecord: () => creating });
  context.enqueuePlannerUpsert(task);
  const finished = new Promise(resolve => context.flushPlannerSyncQueue(resolve));
  await Promise.resolve();
  task.data.title = 'Edited while sending';
  context.enqueuePlannerUpsert(task);
  resolveCreate({ id: 'remote-created' });
  const result = await finished;
  assert.equal(result.ok, true);
  assert.equal(task.remoteId, 'remote-created');
  assert.deepEqual(calls.map(call => call.kind), ['add', 'update']);
  assert.equal(calls[1].recordId, 'remote-created');
  assert.equal(calls[1].properties['内容'].text, 'Edited while sending');
  assert.equal(context.state.settings.plannerSyncQueue.length, 0);
});

test('deleting a task while its create is in flight turns the same queue entry into a cloud tombstone', async () => {
  let resolveCreate;
  const creating = new Promise(resolve => { resolveCreate = resolve; });
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Delete me', list: '生活', done: false } };
  const { context, calls } = createPlannerSyncHarness({ records: [task], addRecord: () => creating });
  context.enqueuePlannerUpsert(task);
  const finished = new Promise(resolve => context.flushPlannerSyncQueue(resolve));
  await Promise.resolve();
  context.enqueuePlannerDelete(task);
  context.state.records = [];
  resolveCreate({ id: 'remote-created' });
  const result = await finished;
  assert.equal(result.ok, true);
  assert.deepEqual(calls.map(call => call.kind), ['add', 'delete']);
  assert.equal(calls[1].recordId, 'remote-created');
  assert.equal(context.state.settings.plannerSyncQueue.length, 0);
});

test('an interrupted create is reconciled before retry and its tombstone deletes the matched remote task', async () => {
  const snapshot = { date: '2026-09-28', title: 'Delete after interrupted upload', list: '生活', status: '待完成' };
  const cloudRow = { record_id: 'remote-created-before-crash', 日期: snapshot.date, 内容: snapshot.title, 类型: snapshot.list, 状态: snapshot.status };
  const { context, calls } = createPlannerSyncHarness({
    queue: [{ id: 'op-a', kind: 'delete', localId: 'task-a', remoteId: '', attempted: true, snapshot }],
    query: () => Promise.resolve({ results: [cloudRow], hasMore: false }),
  });
  const result = await new Promise(resolve => context.flushPlannerSyncQueue(resolve));
  assert.equal(result.ok, true);
  assert.deepEqual(calls.map(call => call.kind), ['query', 'delete']);
  assert.equal(calls[1].recordId, cloudRow.record_id);
  assert.equal(context.state.settings.plannerSyncQueue.length, 0);
});

test('an interrupted create with one exact remote match adopts its id instead of duplicating the task', async () => {
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Keep one copy', list: '工作', done: false } };
  const row = { record_id: 'remote-existing', 日期: task.date, 内容: task.data.title, 类型: task.data.list, 状态: '待完成' };
  const snapshot = { date: task.date, title: task.data.title, list: task.data.list, status: '待完成' };
  const { context, calls } = createPlannerSyncHarness({
    queue: [{ id: 'op-a', kind: 'upsert', localId: task.id, remoteId: '', attempted: true, snapshot }],
    records: [task], query: () => Promise.resolve({ results: [row], hasMore: false }),
  });
  const result = await new Promise(resolve => context.flushPlannerSyncQueue(resolve));
  assert.equal(result.ok, true);
  assert.equal(task.remoteId, row.record_id);
  assert.deepEqual(calls.map(call => call.kind), ['query', 'update']);
  assert.equal(calls[1].recordId, row.record_id);
});

test('ambiguous interrupted creates stay queued and block cloud pull instead of risking the wrong task', async () => {
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Repeated title', list: '生活', done: false } };
  const snapshot = { date: task.date, title: task.data.title, list: task.data.list, status: '待完成' };
  const { context } = createPlannerSyncHarness({
    queue: [{ id: 'op-a', kind: 'upsert', localId: task.id, remoteId: '', attempted: true, snapshot }],
    records: [task],
    query: () => Promise.resolve({ results: [
      { record_id: 'remote-one', 日期: snapshot.date, 内容: snapshot.title, 类型: snapshot.list, 状态: snapshot.status },
      { record_id: 'remote-two', 日期: snapshot.date, 内容: snapshot.title, 类型: snapshot.list, 状态: snapshot.status },
    ], hasMore: false }),
  });
  let pulls = 0;
  context.pullAllRemote = callback => { pulls++; callback({ changed: false, failed: 0 }); };
  const result = await new Promise(resolve => context.syncPlannerAndPull(resolve));
  assert.equal(result.failed, 1);
  assert.equal(result.pending, 1);
  assert.equal(context.PLANNER_SYNC_AMBIGUOUS, true);
  assert.equal(pulls, 0);
  assert.equal(context.state.settings.plannerSyncQueue.length, 1);
});

test('failed planner sync keeps its queue and skips cloud pull until retry succeeds', async () => {
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Offline change', list: '生活', done: false } };
  const { context } = createPlannerSyncHarness({
    records: [task], addRecord: () => Promise.reject(new Error('offline')),
  });
  let pulls = 0;
  context.pullAllRemote = callback => { pulls++; callback({ changed: false, failed: 0, local: false }); };
  context.enqueuePlannerUpsert(task);
  const result = await new Promise(resolve => context.syncPlannerAndPull(resolve));
  assert.equal(result.failed, 1);
  assert.equal(pulls, 0);
  assert.equal(context.state.settings.plannerSyncQueue.length, 1);
  assert.equal(context.state.settings.plannerSyncQueue[0].kind, 'upsert');
});

test('daily, weekdays, weekly, and invalid date recurrence boundaries', () => {
  const { context } = createPlannerHarness();
  assert.equal(context.plannerNextRepeatDate({ date: '2026-09-28', data: { repeat: 'daily' } }), '2026-09-29');
  assert.equal(context.plannerNextRepeatDate({ date: '2026-09-25', data: { repeat: 'weekdays' } }), '2026-09-28');
  assert.equal(context.plannerNextRepeatDate({ date: '2026-12-31', data: { repeat: 'weekly' } }), '2027-01-07');
  assert.equal(context.plannerNextRepeatDate({ date: '2026-02-30', data: { repeat: 'daily' } }), null);
  assert.equal(context.plannerNextRepeatDate({ date: '2026-09-28', data: { repeat: 'yearly' } }), null);
});

test('monthly recurrence keeps its day through short months and leap years', () => {
  const { context } = createPlannerHarness();
  assert.equal(context.plannerNextRepeatDate({ date: '2026-01-31', data: { repeat: 'monthly', repeatDayOfMonth: 31 } }), '2026-02-28');
  assert.equal(context.plannerNextRepeatDate({ date: '2028-01-31', data: { repeat: 'monthly', repeatDayOfMonth: 31 } }), '2028-02-29');
  assert.equal(context.plannerNextRepeatDate({ date: '2026-02-28', data: { repeat: 'monthly', repeatDayOfMonth: 31 } }), '2026-03-31');
});

test('editing a monthly task resets the anchor only when its date changes', () => {
  const { context } = createPlannerHarness();
  const original = { repeat: 'monthly', repeatDayOfMonth: 31, repeatSeriesId: 'series-a' };
  assert.deepEqual(
    { ...context.plannerRepeatFields('monthly', '2026-01-31', original, '2026-01-31') },
    { repeat: 'monthly', repeatDayOfMonth: 31, repeatSeriesId: 'series-a' },
  );
  assert.deepEqual(
    { ...context.plannerRepeatFields('monthly', '2026-02-15', original, '2026-01-31') },
    { repeat: 'monthly', repeatDayOfMonth: 15, repeatSeriesId: 'series-a' },
  );
  assert.equal(context.plannerRepeatFields('none', '2026-02-15', original, '2026-01-31').repeatSeriesId, '');
});

test('a generated occurrence keeps task details and clears completion and tracking state', () => {
  const source = {
    id: 'task-a', type: 'planner', date: '2026-01-31', sample: false,
    data: {
      title: 'Monthly review', time: '09:15', estimateMin: 60,
      repeat: 'monthly', repeatDayOfMonth: 31, repeatSeriesId: 'series-a',
      done: true, status: 'done', completedAt: 'finished', remindedAt: 'sent',
      trackedSeconds: 900, sessions: [{ seconds: 900 }], plannedDate: '2026-01-31',
    },
    remoteId: 'remote-source',
  };
  const { context } = createPlannerHarness([source]);
  const next = context.plannerNextOccurrence(source);
  assert.equal(next.date, '2026-02-28');
  assert.equal(next.data.repeatDayOfMonth, 31);
  assert.equal(next.data.time, '09:15');
  assert.equal(next.data.estimateMin, 60);
  assert.equal(next.data.plannedDate, '2026-02-28');
  assert.equal(next.data.done, false);
  assert.equal(next.data.status, 'todo');
  assert.equal(next.data.completedAt, '');
  assert.equal(next.data.remindedAt, '');
  assert.equal(next.data.trackedSeconds, 0);
  assert.deepEqual(Array.from(next.data.sessions), []);
  assert.equal(Object.hasOwn(next, 'remoteId'), false);
  context.state.records.push(next);
  assert.equal(context.plannerNextOccurrence(source), null, 'the same series and date must not be generated twice');
});

test('local repeats spawned from an imported calendar task become ordinary local tasks', () => {
  const source = {
    id: 'ical-todo:' + 'c'.repeat(64), type: 'planner', date: '2026-09-28', sample: false,
    data: { title: 'Repeat locally', repeat: 'daily', done: true, externalTodo: { provider: 'ical-file', sourceId: 'ics-file:work', uid: 'one-off' } },
  };
  const { context } = createPlannerHarness([source]);
  const next = context.plannerNextOccurrence(source);
  assert.ok(next);
  assert.equal(next.date, '2026-09-29');
  assert.equal(next.data.externalTodo, undefined);
});

test('completion creates one next occurrence and survives uncomplete and re-complete', () => {
  const task = {
    id: 'task-a', type: 'planner', date: '2026-09-28', createdAt: 1, sample: false,
    data: { title: 'Daily review', repeat: 'daily', repeatSeriesId: 'series-daily', done: false },
  };
  const { context, pushed } = createPlannerHarness([task]);
  context.toggleTask('task-a');
  assert.equal(context.state.records.length, 2);
  assert.equal(context.state.records[1].date, '2026-09-29');
  assert.equal(context.state.records[1].data.done, false);
  context.toggleTask('task-a');
  context.toggleTask('task-a');
  assert.equal(context.state.records.length, 2);
  assert.equal(pushed.length, 1);
});

test('failed local save rolls back completion and the generated occurrence', () => {
  const task = {
    id: 'task-a', type: 'planner', date: '2026-09-28', sample: false,
    data: { title: 'Daily review', repeat: 'daily', done: false },
  };
  const harness = createPlannerHarness([task]);
  harness.setSaveResult(false);
  harness.context.toggleTask('task-a');
  assert.equal(harness.context.state.records.length, 1);
  assert.equal(harness.context.state.records[0].data.done, false);
  assert.equal(harness.context.state.records[0].data.repeatSeriesId, undefined);
});

test('manual drag rescheduling respects midnight and rearms a previously delivered reminder', () => {
  const task = {
    id: 'task-a', type: 'planner', date: '2026-09-28', sample: false,
    data: { title: 'Long task', time: '09:00', estimateMin: 60, done: false, remindedAt: '2026-09-28T09:00:00.000Z' },
  };
  const harness = createPlannerHarness([task]);
  const { context } = harness;
  assert.equal(context.plannerReminderScheduleChanged({ date: '2026-09-28', time: '09:00', remind: true }, { date: '2026-09-28', time: '09:00', remind: true }), false);
  assert.equal(context.plannerReminderScheduleChanged({ date: '2026-09-28', time: '09:00', remind: true }, { date: '2026-09-28', time: '09:00', remind: false }), true);
  assert.equal(context.plannerTimeFitsDay('23:30', 60), false);
  assert.equal(context.plannerTimeFitsDay('23:30', 30), true);
  assert.equal(context.reschedulePlannerTask('task-a', '2026-09-28', '23:30'), false);
  assert.equal(context.state.records[0].data.time, '09:00');
  harness.setSaveResult(false);
  assert.equal(context.reschedulePlannerTask('task-a', '2026-09-28', '23:00'), false);
  assert.equal(context.state.records[0].data.remindedAt, '2026-09-28T09:00:00.000Z');
  harness.setSaveResult(true);
  assert.equal(context.reschedulePlannerTask('task-a', '2026-09-28', '23:00'), true);
  assert.equal(context.state.records[0].data.time, '23:00');
  assert.equal(context.state.records[0].data.remindedAt, undefined);
});

test('editing and cancelling a scheduled task keep their input helpers in scope', () => {
  const task = {
    id: 'task-edit', type: 'planner', date: '2026-09-30', sample: false,
    data: { title: 'Edit this task', time: '09:45', estimateMin: 75, repeat: 'weekly', list: '工作', priority: 'high', note: 'Bring notes', remind: true, project: '毕业设计', tags: ['紧急', '写作'] },
  };
  const input = value => ({ value, dataset: {}, focus() {} });
  const elements = {
    editingId: input(''), title: input(''), date: input(''), time: input(''), project: input(''), tags: input(''),
    estimateMin: input('30'), repeat: input('none'), list: input('生活'), priority: input('normal'),
    note: input(''), remind: { checked: false },
  };
  const submit = { textContent: '加入日程' };
  const form = { elements, querySelector: () => submit, scrollIntoView() {} };
  const heading = { textContent: '' };
  const cancel = { hidden: true };
  let defaultsApplied = 0;
  const context = {
    state: { records: [task] }, LANG: 'zh', plannerSelectedDate: '2026-09-28', plannerWeekStart: '2026-09-28',
    document: { getElementById: id => ({ plannerForm: form, plannerFormHeading: heading, plannerCancelEdit: cancel })[id] },
    clearDraft() {}, renderPlanner() {}, shiftPlannerDate: () => '2026-10-04',
    setPlannerDefaultTime: () => { defaultsApplied++; }, toast() {}, confirm: () => true,
  };
  vm.runInNewContext(
    renderer.slice(plannerStart, plannerEnd) + '\n'
      + renderer.slice(editStart, cancelEditStart) + '\n'
      + renderer.slice(cancelEditStart, cancelEditEnd),
    context,
    { timeout: 1500 },
  );

  context.editPlannerTask('task-edit');
  assert.equal(elements.editingId.value, 'task-edit');
  assert.equal(elements.title.value, 'Edit this task');
  assert.equal(elements.time.value, '09:45');
  assert.equal(elements.project.value, '毕业设计');
  assert.equal(elements.tags.value, '紧急, 写作');
  assert.equal(elements.estimateMin.value, 75);
  assert.equal(elements.repeat.value, 'weekly');
  assert.equal(heading.textContent, '编辑待办');
  assert.equal(cancel.hidden, false);
  context.cancelPlannerEdit();
  assert.equal(elements.editingId.value, '');
  assert.equal(elements.project.value, '');
  assert.equal(elements.tags.value, '');
  assert.equal(elements.repeat.value, 'none');
  assert.equal(heading.textContent, '添加待办');
  assert.equal(cancel.hidden, true);
  assert.equal(defaultsApplied, 1);
});

test('editing the scheduled time, date, or reminder opt-in clears the old reminder receipt', () => {
  assert.ok(renderer.includes("plannerReminderScheduleChanged({date:previousDate,time:previousTime,remind:previousRemind},{date:editing.date,time:editing.data.time,remind:data.remind==='1'}))delete editing.data.remindedAt;"));
});

test('cloud refresh updates remote fields without erasing local schedule metadata', () => {
  const record = {
    id: 'local-a', type: 'planner', date: '2026-01-31', createdAt: 10,
    sample: false, remoteId: 'remote-a',
    data: {
      title: 'Old title', list: '工作', done: false, time: '09:15', note: 'Local note',
      estimateMin: 90, priority: 'high', remind: true, project: '毕业设计', tags: ['紧急', '写作'], repeat: 'monthly',
      repeatDayOfMonth: 31, repeatSeriesId: 'series-a', trackedSeconds: 1800,
    },
  };
  const { context } = createPlannerHarness([record]);
  context.mergePlan([{
    '日期': '2026-02-28', '内容': 'Remote title', '类型': '家庭', '状态': '已完成', record_id: 'remote-a',
  }]);
  const refreshed = context.state.records[0];
  assert.equal(refreshed.date, '2026-02-28');
  assert.equal(refreshed.data.title, 'Remote title');
  assert.equal(refreshed.data.list, '家庭');
  assert.equal(refreshed.data.done, true);
  assert.equal(refreshed.data.time, '09:15');
  assert.equal(refreshed.data.note, 'Local note');
  assert.equal(refreshed.data.estimateMin, 90);
  assert.equal(refreshed.data.priority, 'high');
  assert.equal(refreshed.data.remind, true);
  assert.equal(refreshed.data.project, '毕业设计');
  assert.deepEqual(refreshed.data.tags, ['紧急', '写作']);
  assert.equal(refreshed.data.repeat, 'monthly');
  assert.equal(refreshed.data.repeatDayOfMonth, 31);
  assert.equal(refreshed.data.repeatSeriesId, 'series-a');
  assert.equal(refreshed.data.trackedSeconds, 1800);
});

test('the timeline scales task height by estimated work time and detects estimate overlaps', () => {
  const { context, elements } = createPlannerHarness();
  context.renderPlannerTimeline([
    { id: 'one-hour', type: 'planner', date: '2026-09-28', createdAt: 1, data: { title: 'One hour', time: '09:00', estimateMin: 60, done: false } },
    { id: 'two-hours', type: 'planner', date: '2026-09-28', createdAt: 2, data: { title: 'Two hours', time: '11:00', estimateMin: 120, done: false } },
  ]);
  const plane = elements.plannerTimeline.children[0].children[1];
  const blocks = plane.children.filter(node => node.className.indexOf('planner-event') === 0);
  const heights = Object.fromEntries(blocks.map(node => [node.dataset.id, Number.parseFloat(node.style.height)]));
  assert.equal(heights['one-hour'] + 3, 36);
  assert.equal(heights['two-hours'] + 3, 72);

  context.renderPlannerTimeline([
    { id: 'overlap-a', type: 'planner', date: '2026-09-28', createdAt: 1, data: { title: 'A', time: '09:00', estimateMin: 60, done: false } },
    { id: 'overlap-b', type: 'planner', date: '2026-09-28', createdAt: 2, data: { title: 'B', time: '09:30', estimateMin: 30, done: false } },
  ]);
  assert.match(elements.plannerConflictNotice.textContent, /1 处时间冲突/);
});

test('calendar file tasks never enter the ordinary cloud planner queue', () => {
  const { context } = createPlannerSyncHarness();
  const task = { id: 'ical-todo:' + 'a'.repeat(64), type: 'planner', date: '2026-09-28', sample: false, data: { title: 'External task', list: '生活', done: false, externalTodo: { provider: 'ical-file', sourceId: 'ics-file:work', uid: 'todo-1' } } };
  assert.equal(context.enqueuePlannerUpsert(task), null);
  assert.equal(context.enqueuePlannerDelete(task), null);
  assert.equal(context.state.settings.plannerSyncQueue.length, 0);
});

test('CalDAV tasks stay local, keep stable identities, and respect deletion tombstones', async () => {
  const accountId = '12345678-1234-4234-8234-123456789abc';
  const { context } = createCalDavRendererHarness();
  const id = await context.plannerCalendarTodoRecordId('caldav:' + accountId, 'remote-1', 'caldav');
  const task = { id, type: 'planner', date: '2026-09-28', sample: false, data: { title: 'External task', done: false, externalTodo: { provider: 'caldav', sourceId: 'caldav:' + accountId, uid: 'remote-1' } } };
  const { context: sync } = createPlannerSyncHarness({ records: [task] });
  assert.equal(sync.enqueuePlannerUpsert(task), null);
  assert.equal(sync.enqueuePlannerDelete(task), null);
  assert.equal(sync.state.settings.plannerSyncQueue.length, 0);

  const todo = ['BEGIN:VCALENDAR','VERSION:2.0','BEGIN:VTODO','UID:remote-1','SUMMARY:External task','DTSTART;VALUE=DATE:20260929','STATUS:NEEDS-ACTION','END:VTODO','END:VCALENDAR'].join('\r\n');
  const response = { kind: 'updated', id: accountId, account: { id: accountId, name: 'Work', host: 'dav.example.test', lastSuccessAt: '2026-09-29T00:00:00.000Z' }, icsText: todo, commitToken: 'checkpoint-1', eventCount: 0, todoCount: 1, todos: WanxiangCalendar.parseIcs(todo).todos };
  assert.equal(await context.applyPlannerCalDavResult(response), true);
  const imported = context.state.records[0];
  assert.equal(imported.id, id);
  assert.equal(imported.data.externalTodo.provider, 'caldav');
  imported.data.estimateMin = 75;
  imported.data.trackedSeconds = 900;
  assert.equal(await context.applyPlannerCalDavResult({ ...response, commitToken: 'checkpoint-2' }), true);
  assert.equal(context.state.records[0].id, id);
  assert.equal(context.state.records[0].data.estimateMin, 75);
  assert.equal(context.state.records[0].data.trackedSeconds, 900);
  context.state.settings.calendarTodoTombstones = [id];
  context.state.records = [];
  assert.equal(await context.applyPlannerCalDavResult({ ...response, commitToken: 'checkpoint-3' }), true);
  assert.equal(context.state.records.length, 0);
});

test('CalDAV source normalization keeps account identity and calendar task tombstones', () => {
  const accountId = '11111111-2222-4333-8444-555555555555';
  const { context } = createCalDavRendererHarness();
  const normalized = context.normalizeCalendarSources([{ id: 'caldav:' + accountId, name: 'Work', type: 'caldav', caldavAccountId: accountId, host: 'dav.example.test', icsText: 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n', eventCount: 1, todoCount: 2 }]);
  assert.equal(normalized.length, 1);
  assert.equal(normalized[0].type, 'caldav');
  assert.equal(normalized[0].caldavAccountId, accountId);
  assert.ok(context.normalizeCalendarTodoTombstones(['caldav-todo:' + 'd'.repeat(64)]).length === 1);
});

test('CalDAV backup caches without a saved account become detached local tasks on this device', async () => {
  const accountId = '12345678-1234-4234-8234-123456789abc';
  const sourceId = 'caldav:' + accountId;
  const source = { id: sourceId, name: 'Work', type: 'caldav', caldavAccountId: accountId, icsText: 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n', eventCount: 1, todoCount: 1 };
  const task = { id: 'caldav-todo:' + 'b'.repeat(64), type: 'planner', date: '2026-09-29', sample: false, data: { title: 'Cached task', done: false, externalTodo: { provider: 'caldav', sourceId, uid: 'remote-1', sourceMissing: false } } };
  const { context } = createCalDavRendererHarness([task]);
  context.state.calendarSources = [source];
  context.window.wanxiangDesktop.listCalDavCalendars = async () => [];
  await context.initializePlannerCalDav();
  assert.equal(context.state.calendarSources[0].accountMissing, true);
  assert.match(context.state.calendarSources[0].lastError, /此设备没有保存/u);
  assert.equal(context.state.records[0].data.externalTodo.sourceMissing, true);
});

test('CalDAV task completion is confirmed by the server before the local status changes', async () => {
  const accountId = '12345678-1234-4234-8234-123456789abc';
  const sourceId = 'caldav:' + accountId;
  const task = {
    id: 'caldav-todo:' + 'f'.repeat(64), type: 'planner', date: '2026-09-29', sample: false,
    data: { title: 'Remote task', done: false, status: 'todo', externalTodo: { provider: 'caldav', sourceId, uid: 'remote-1' } },
  };
  const source = { id: sourceId, type: 'caldav', caldavAccountId: accountId };
  const { context } = createPlannerHarness([task], [source]);
  const calls = [];
  context.window.wanxiangDesktop.setCalDavTodoCompletion = async (...args) => { calls.push(args); return { ok: true }; };

  assert.equal(context.plannerMoveBoardTask(task.id, 'done'), false, 'board moves cannot bypass the remote write');
  assert.equal(task.data.done, false);
  assert.equal(await context.toggleTask(task.id), true);
  assert.equal(task.data.done, true);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [[accountId, 'remote-1', true]]);
  assert.equal(await context.toggleTask(task.id), true);
  assert.equal(task.data.done, false);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [[accountId, 'remote-1', true], [accountId, 'remote-1', false]]);

  context.window.wanxiangDesktop.setCalDavTodoCompletion = async () => ({ ok: false, error: '服务器已变化，请先同步。' });
  assert.equal(await context.toggleTask(task.id), false);
  assert.equal(task.data.done, false, 'a rejected server update must leave local state unchanged');
});

test('CalDAV board status controls route completion remotely and reject unsupported local status changes', async () => {
  const accountId = '12345678-1234-4234-8234-123456789abc';
  const sourceId = 'caldav:' + accountId;
  const task = {
    id: 'caldav-todo:' + 'a'.repeat(64), type: 'planner', date: '2026-09-29', sample: false,
    data: { title: 'Remote task', done: false, status: 'inprogress', externalTodo: { provider: 'caldav', sourceId, uid: 'remote-1' } },
  };
  const { context } = createPlannerHarness([task], [{ id: sourceId, type: 'caldav', caldavAccountId: accountId }]);
  const calls = [];
  context.window.wanxiangDesktop.setCalDavTodoCompletion = async (...args) => { calls.push(args); return { ok: true }; };
  const select = { value: 'todo' };
  assert.equal(context.plannerHandleCalDavStatusChange(task, 'todo', select), true);
  assert.equal(select.value, 'inprogress');
  assert.equal(task.data.status, 'inprogress');
  assert.equal(calls.length, 0);

  select.value = 'done';
  assert.equal(context.plannerHandleCalDavStatusChange(task, 'done', select), true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(task.data.done, true);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [[accountId, 'remote-1', true]]);
});

test('portable encrypted backups use authenticated AES-GCM, reject wrong passwords, and preserve the JSON backup format', async () => {
  const context = { crypto: webcrypto, TextEncoder, TextDecoder, Uint8Array, btoa, atob };
  vm.runInNewContext(renderer.slice(backupCryptoStart, backupCryptoEnd), context, { timeout: 1500 });
  const payload = { format: 'daily-atlas-backup', version: 1, state: { records: [{ title: 'private task' }] } };
  const first = await context.encryptBackupPayload(payload, 'a long passphrase 123');
  const second = await context.encryptBackupPayload(payload, 'a long passphrase 123');
  assert.equal(first.kdf, 'PBKDF2-HMAC-SHA256');
  assert.equal(first.iterations, 600000);
  assert.equal(first.cipher, 'AES-256-GCM');
  assert.notEqual(first.salt, second.salt);
  assert.notEqual(first.iv, second.iv);
  assert.doesNotMatch(JSON.stringify(first), /private task/u);
  assert.deepEqual(JSON.parse(JSON.stringify(await context.decryptBackupPayload(first, 'a long passphrase 123'))), payload);
  await assert.rejects(context.decryptBackupPayload(first, 'a different passphrase'), /备份密码错误或文件已损坏/u);
  const tampered = { ...first, ciphertext: (first.ciphertext[0] === 'A' ? 'B' : 'A') + first.ciphertext.slice(1) };
  await assert.rejects(context.decryptBackupPayload(tampered, 'a long passphrase 123'), /备份密码错误或文件已损坏/u);
  await assert.rejects(context.decryptBackupPayload({ ...first, iv: 'AA==' }, 'a long passphrase 123'), /备份密码错误或文件已损坏/u);
  await assert.rejects(context.decryptBackupPayload({ ...first, iterations: 1 }, 'a long passphrase 123'), /格式不受支持/u);
  await assert.rejects(context.decryptBackupPayload(first, 'short'), /备份密码错误或文件已损坏/u);
  await assert.rejects(context.encryptBackupPayload(payload, 'short'), /12 至/u);
  await assert.rejects(context.encryptBackupPayload(payload, '界'.repeat(86)), /12 至/u);
  assert.match(renderer, /payload\?\.format!=='daily-atlas-backup'/u, 'the existing plain JSON backup restore path remains available');
  assert.match(html, /id="exportEncryptedBackupBtn"/);
  assert.match(html, /id="backupPasswordDialog"/);
  assert.match(html, /id="backupPasswordEyebrow"/);
  assert.match(html, /accept="application\/json,\.json,\.wxbackup"/);
});

test('WebDAV snapshot controls use the desktop bridge and keep the remote snapshot separate from tasks', () => {
  assert.match(html, /id="webdavBackupSetupBtn"/);
  assert.match(html, /id="webdavBackupPushBtn"/);
  assert.match(html, /id="webdavBackupFetchBtn"/);
  assert.match(html, /id="webdavBackupDialog"/);
  assert.match(renderer, /api\.configureWebDavBackup/u);
  assert.match(renderer, /api\.pushWebDavBackup/u);
  assert.match(renderer, /api\.fetchWebDavBackup/u);
  assert.match(renderer, /importFullBackup\(\{size,text:async\(\)=>result\.content\}\)/u);
  assert.match(html, /自动合并/u);
  assert.match(html, /id="webdavPlannerConflictsDialog"/u);
  assert.match(renderer, /api\.fetchWebDavPlannerSnapshot/u);
  assert.match(renderer, /api\.pushWebDavPlannerSnapshot/u);
  assert.match(renderer, /sync\.mergeSnapshots\(local,remote\)/u);
});

test('a failed asynchronous backup restores only old export counters and keeps edits made meanwhile', () => {
  const context = {
    state: { settings: { recordsSinceExport: 2, moneySinceExport: 1, lastExportAt: 'prepared' } },
    saveState: () => true,
    renderAll: () => {},
    toast: () => {},
  };
  vm.runInNewContext(renderer.slice(backupRollbackStart, backupRollbackEnd), context, { timeout: 1500 });
  context.rollbackBackupExportCounters({ recordsSinceExport: 3, moneySinceExport: 4, lastExportAt: 'previous', preparedAt: 'prepared' });
  assert.equal(context.state.settings.recordsSinceExport, 5);
  assert.equal(context.state.settings.moneySinceExport, 5);
  assert.equal(context.state.settings.lastExportAt, 'previous');

  context.state.settings.lastExportAt = 'newer-export';
  context.rollbackBackupExportCounters({ recordsSinceExport: 0, moneySinceExport: 0, lastExportAt: 'prepared', preparedAt: 'prepared' });
  assert.equal(context.state.settings.lastExportAt, 'newer-export');
});

test('deleting a calendar file task persists a tombstone', () => {
  const id = 'ical-todo:' + 'b'.repeat(64);
  const task = { id, type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Delete external task', done: false, externalTodo: { provider: 'ical-file', sourceId: 'ics-file:work', uid: 'todo-delete' } } };
  const { context } = createPlannerHarness([task]);
  context.deleteRecord(id);
  assert.deepEqual(context.state.records, []);
  assert.deepEqual(Array.from(context.state.settings.calendarTodoTombstones), [id]);
});

test('deleting a CalDAV task persists its source tombstone', () => {
  const id = 'caldav-todo:' + 'e'.repeat(64);
  const task = { id, type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Delete remote task', done: false, externalTodo: { provider: 'caldav', sourceId: 'caldav:12345678-1234-4234-8234-123456789abc', uid: 'todo-delete' } } };
  const { context } = createPlannerHarness([task]);
  context.deleteRecord(id);
  assert.equal(context.state.records.length, 0);
  assert.deepEqual(Array.from(context.state.settings.calendarTodoTombstones), [id]);
});

test('opaque calendar events mark task conflicts and reduce suggested free slots while transparent events do not', () => {
  const source = { id: 'calendar-a', name: 'Work', icsText: 'calendar', eventCount: 3 };
  const { context, elements } = createPlannerHarness([
    { id: 'scheduled', type: 'planner', date: '2026-09-28', createdAt: 1, data: { title: 'Write', time: '09:00', estimateMin: 60, done: false } },
    { id: 'backlog', type: 'planner', date: '2026-09-28', createdAt: 2, data: { title: 'Review', time: '', estimateMin: 30, done: false, priority: 'high' } },
  ], [source]);
  context.WanxiangCalendar.eventOccurrencesForDay = () => [
    { uid: 'meeting-a', title: 'Meeting', sourceCalendar: 'Work', transparency: 'OPAQUE', allDay: false, startMinute: 570, endMinute: 630, startAt: 0, endAt: 0 },
    { uid: 'meeting-b', title: 'Planning', sourceCalendar: 'Work', transparency: 'OPAQUE', allDay: false, startMinute: 720, endMinute: 780, startAt: 0, endAt: 0 },
    { uid: 'optional', title: 'Optional', sourceCalendar: 'Work', transparency: 'TRANSPARENT', allDay: false, startMinute: 840, endMinute: 900, startAt: 0, endAt: 0 },
  ];
  context.renderPlannerTimeline(context.state.records);
  assert.match(elements.plannerConflictNotice.textContent, /1 处时间冲突/);
  const scroll = elements.plannerTimeline.children[0];
  const plane = scroll.children[1];
  const blocks = plane.children.filter(node => node.className.startsWith('planner-event'));
  assert.equal(blocks.find(node => node.dataset.id === 'scheduled').className.includes('conflict'), true);
  assert.equal(blocks.find(node => node.children[0]?.textContent === 'Meeting').className.includes('conflict'), true);
  assert.equal(blocks.find(node => node.children[0]?.textContent === 'Optional').className.includes('conflict'), false);
  const slots = elements.plannerFreeSlots.children.filter(node => node.className === 'planner-free-slot').map(node => node.textContent);
  assert.ok(slots.some(text => text.startsWith('08:00–09:00')));
  assert.ok(slots.some(text => text.startsWith('10:30–12:00')));
  assert.ok(slots.some(text => text.startsWith('13:00–18:00')));
  assert.equal(elements.plannerCalendarSources.children.length, 1);
});

test('opaque all-day calendar events reserve the visible workday', () => {
  const source = { id: 'calendar-a', name: 'Work', icsText: 'calendar', eventCount: 1 };
  const { context, elements } = createPlannerHarness([
    { id: 'backlog', type: 'planner', date: '2026-09-28', createdAt: 1, data: { title: 'Review', time: '', estimateMin: 30, done: false } },
  ], [source]);
  context.WanxiangCalendar.eventOccurrencesForDay = () => [
    { uid: 'holiday', title: 'Holiday', sourceCalendar: 'Work', transparency: 'OPAQUE', allDay: true, startMinute: 0, endMinute: 1440, startAt: 0, endAt: 0 },
  ];
  context.renderPlannerTimeline(context.state.records);
  assert.match(elements.plannerTimeline.children[0].className, /planner-all-day-list/);
  assert.match(elements.plannerFreeSlots.innerHTML, /没有能容纳下一项任务的空档/);
});

test('the planner form offers repeat choices and task rows show the chosen cadence', () => {
  assert.match(html, /<select name="repeat" id="plannerRepeatInput">/);
  for (const cadence of ['不重复', '每天', '每个工作日', '每周', '每月']) assert.ok(html.includes(cadence));
  assert.ok(html.includes('plannerRepeatLabel(d.repeat)'));
});

test('the hidden cancel-edit control stays hidden under full-width button styles', () => {
  assert.match(html, /\.btn\.full\[hidden\]\{display:none\}/);
  assert.match(html, /id="plannerCancelEdit" type="button" hidden/);
});

function createReminderHarness(visibilityState) {
  const now = new Date(2026, 8, 28, 12).getTime();
  class TestDate extends Date {
    constructor(...values) { super(...(values.length ? values : [now])); }
    static now() { return now; }
  }
  const task = {
    id: 'due-task', type: 'planner', date: '2026-09-28', sample: false,
    data: { title: '提交材料', note: '', time: '10:00', remind: true, done: false },
  };
  const calls = { toasts: [], saves: 0 };
  const context = {
    state: { records: [task] }, Date: TestDate, window: {},
    document: { visibilityState }, isoDate: () => '2026-09-28',
    toast: message => calls.toasts.push(message),
    saveState: () => { calls.saves += 1; return true; },
  };
  vm.runInNewContext(renderer.slice(reminderStart, reminderEnd), context, { timeout: 1500 });
  return { context, calls };
}

test('a due reminder stays pending while the workbench is hidden', () => {
  const { context, calls } = createReminderHarness('hidden');
  context.checkDueReminders();
  assert.equal(context.state.records[0].data.remindedAt, undefined);
  assert.equal(calls.toasts.length, 0);
  assert.equal(calls.saves, 0);
});

test('a pending due reminder appears once when the workbench becomes visible', () => {
  const { context, calls } = createReminderHarness('visible');
  context.checkDueReminders();
  assert.match(context.state.records[0].data.remindedAt, /^2026-09-28T/);
  assert.deepEqual(calls.toasts, ['日程提醒：提交材料']);
  assert.equal(calls.saves, 1);
  context.checkDueReminders();
  assert.equal(calls.toasts.length, 1);
  assert.equal(calls.saves, 1);
});

test('desktop reminder scheduling continues while hidden and sends each changed schedule once', () => {
  const now = new Date(2026, 8, 28, 12).getTime();
  class TestDate extends Date { static now() { return now; } }
  const task = {
    id: 'desktop-due-task', type: 'planner', date: '2026-10-05', sample: false,
    data: { title: '提交材料', note: '检查附件', time: '10:00', remind: true, done: false },
  };
  const calls = { schedules: [], toasts: [], saves: 0 };
  const context = {
    state: { records: [task] }, Date: TestDate, plannerReminderSyncSignature: null,
    window: { wanxiangDesktop: { syncPlannerReminders: items => { calls.schedules.push(items); return Promise.resolve({ pendingCount: items.length }); } } },
    document: { visibilityState: 'hidden' }, isoDate: () => '2026-09-28',
    toast: message => calls.toasts.push(message),
    saveState: () => { calls.saves += 1; return true; },
  };
  vm.runInNewContext(renderer.slice(reminderStart, reminderEnd), context, { timeout: 1500 });
  context.checkDueReminders();
  context.checkDueReminders();
  assert.equal(calls.schedules.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls.schedules[0])), [{
    id: 'desktop-due-task', date: '2026-10-05', time: '10:00', title: '提交材料', body: '检查附件',
  }]);
  assert.equal(task.data.remindedAt, undefined);
  assert.deepEqual(calls.toasts, []);

  context.applyPlannerReminderReceipts([{ id: task.id, date: task.date, time: task.data.time, firedAt: '2026-09-28T04:00:00.000Z' }]);
  assert.equal(task.data.remindedAt, '2026-09-28T04:00:00.000Z');
  assert.equal(calls.saves, 1);
});

test('the Electron shell exposes narrow reminder and calendar IPC and guards the main frame', () => {
  const preload = fs.readFileSync(path.join(__dirname, 'preload.cjs'), 'utf8');
  const main = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8');
  assert.match(preload, /syncPlannerReminders/);
  assert.match(preload, /onPlannerRemindersFired/);
  assert.match(preload, /listCalendarSubscriptions/);
  assert.match(preload, /addCalendarSubscription/);
  assert.match(preload, /commitCalendarSubscription/);
  assert.match(preload, /onCalendarSubscriptionsUpdated/);
  assert.match(preload, /listCalDavCalendars/);
  assert.match(preload, /addCalDavCalendar/);
  assert.match(preload, /commitCalDavSync/);
  assert.match(preload, /setCalDavTodoCompletion/);
  assert.match(preload, /configureWebDavBackup/);
  assert.match(preload, /fetchWebDavBackup/);
  assert.match(preload, /pushWebDavBackup/);
  assert.match(preload, /getWebDavPlannerPassphrase/);
  assert.match(preload, /fetchWebDavPlannerSnapshot/);
  assert.match(preload, /pushWebDavPlannerSnapshot/);
  assert.match(preload, /onCalDavUpdated/);
  assert.doesNotMatch(preload, /require\(['"]node:|process\.|ipcRenderer\.sendSync/);
  assert.match(main, /function isTrustedAppEvent\(event\)/);
  assert.match(main, /planner:caldav-sync/);
  assert.match(main, /planner:caldav-todo-completion/);
  assert.match(main, /planner:webdav-backup-configure/);
  assert.match(main, /planner:webdav-backup-fetch/);
  assert.match(main, /planner:webdav-backup-push/);
  assert.match(main, /planner:webdav-planner-key/);
  assert.match(main, /planner:webdav-planner-fetch/);
  assert.match(main, /planner:webdav-planner-push/);
  assert.match(main, /frame && frame\.isMainFrame/);
  assert.match(main, /safeStorage\.encryptString/);
  assert.match(main, /safeStorage\.decryptString/);
  assert.match(main, /permission === 'notifications' && details\.isMainFrame && isAppOrigin\(details\.requestingUrl\)/);
  assert.match(main, /permission === 'notifications' && isAppOrigin\(requestingOrigin\)/);
  assert.match(main, /app\.setToastActivatorCLSID\(APP_TOAST_ACTIVATOR_CLSID\)/);
  assert.match(main, /const APP_TOAST_ACTIVATOR_CLSID = '[0-9a-f-]{36}'/);
  assert.match(main, /app\.commandLine\.hasSwitch\('user-data-dir'\)/);
  assert.match(main, /app\.commandLine\.getSwitchValue\('user-data-dir'\)/);
  assert.match(main, /path\.isAbsolute\(requestedUserDataDir\)/);
  assert.ok(main.indexOf('app.setToastActivatorCLSID') < main.indexOf('app.whenReady()'));
  assert.match(main, /event\.preventDefault\(\);\s*closeToTrayRequested = true;\s*window\.hide\(\);\s*ensureTray\(\);/);
  assert.match(main, /退出万象来信/);
});

test('project and tag normalization is bounded, trimmed, and case-insensitively unique', () => {
  const context = {};
  vm.runInNewContext(renderer.slice(organizationStart, organizationEnd), context, { timeout: 1500 });
  assert.equal(context.plannerNormalizeProject('  毕业设计  '), '毕业设计');
  assert.equal(context.plannerNormalizeProject('甲'.repeat(70)).length, 60);
  assert.deepEqual(Array.from(context.plannerNormalizeTags('紧急, 写作，紧急; Review; review')), ['紧急', '写作', 'Review']);
  assert.equal(context.plannerNormalizeTags(['超长'.repeat(20)])[0].length, 30);
  assert.equal(context.plannerNormalizeTags(Array.from({ length: 15 }, (_, index) => `tag${index}`)).length, 12);
});

test('project and tag filters combine and tolerate legacy tasks without organization fields', () => {
  const context = {};
  vm.runInNewContext(renderer.slice(organizationStart, organizationEnd), context, { timeout: 1500 });
  const task = { data: { project: '毕业设计', tags: ['紧急', '写作'] } };
  const legacyTask = { data: { title: '旧任务' } };
  assert.equal(context.plannerMatchesOrganization(task, '毕业设计', '写作'), true);
  assert.equal(context.plannerMatchesOrganization(task, '毕业设计', '缺席'), false);
  assert.equal(context.plannerMatchesOrganization(task, '另一个项目', ''), false);
  assert.equal(context.plannerMatchesOrganization(legacyTask, '', ''), true);
  assert.equal(context.plannerMatchesOrganization(legacyTask, '毕业设计', ''), false);
});

test('adding a subtask inherits its parent organization and parent progress updates', () => {
  const parent = {
    id: 'parent', type: 'planner', date: '2026-09-28', createdAt: 1, sample: false,
    data: { title: '项目交付', priority: 'high', list: '工作', project: '毕业设计', tags: ['紧急', '写作'], done: false },
  };
  const { context } = createPlannerHarness([parent]);
  assert.equal(context.plannerCreateSubtask('parent', '整理资料'), true);
  const child = context.state.records.find(record => record.data.parentTaskId === 'parent');
  assert.equal(child.date, parent.date);
  assert.equal(child.data.title, '整理资料');
  assert.equal(child.data.time, '');
  assert.equal(child.data.estimateMin, 15);
  assert.equal(child.data.priority, 'high');
  assert.equal(child.data.list, '工作');
  assert.equal(child.data.project, '毕业设计');
  assert.deepEqual(Array.from(child.data.tags), ['紧急', '写作']);
  assert.equal(context.plannerSubtaskProgress(parent), '子任务 0/1');
  child.data.done = true;
  assert.equal(context.plannerSubtaskProgress(parent), '子任务 1/1');
});

test('parents cannot finish before every subtask and can finish after children are complete', () => {
  const parent = {
    id: 'parent', type: 'planner', date: '2026-09-28', sample: false,
    data: { title: '项目交付', done: false },
  };
  const child = {
    id: 'child', type: 'planner', date: '2026-09-28', sample: false,
    data: { title: '整理资料', parentTaskId: 'parent', done: false },
  };
  const { context } = createPlannerHarness([parent, child]);
  context.toggleTask('parent');
  assert.equal(parent.data.done, false);
  child.data.done = true;
  context.toggleTask('parent');
  assert.equal(parent.data.done, true);
});

test('adding subtasks rejects empty titles, nested parents, completed parents, and more than 50 children', () => {
  const parent = { id: 'parent', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Parent', done: false } };
  const children = Array.from({ length: 50 }, (_, index) => ({
    id: `child-${index}`, type: 'planner', date: '2026-09-28', sample: false,
    data: { title: `Child ${index}`, parentTaskId: 'parent', done: false },
  }));
  const { context } = createPlannerHarness([parent, ...children]);
  assert.equal(context.plannerCreateSubtask('parent', '   '), false);
  assert.equal(context.plannerCreateSubtask('child-0', 'Nested'), false);
  parent.data.done = true;
  assert.equal(context.plannerCreateSubtask('parent', 'Completed'), false);
  parent.data.done = false;
  assert.equal(context.plannerCreateSubtask('parent', 'Too many'), false);
  assert.equal(context.state.records.length, 51);
});

test('subtask creation rolls back when the local save fails', () => {
  const parent = { id: 'parent', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Parent', done: false } };
  const harness = createPlannerHarness([parent]);
  harness.setSaveResult(false);
  assert.equal(harness.context.plannerCreateSubtask('parent', 'Child'), false);
  assert.equal(harness.context.state.records.length, 1);
});

test('deleting a parent removes its subtasks together and rolls back when saving fails', () => {
  const parent = { id: 'parent', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Parent' } };
  const child = { id: 'child', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Child', parentTaskId: 'parent' } };
  const harness = createPlannerHarness([parent, child]);
  harness.context.deleteRecord('parent');
  assert.equal(harness.context.state.records.length, 0);
  const rollback = createPlannerHarness([parent, child]);
  rollback.setSaveResult(false);
  rollback.context.deleteRecord('parent');
  assert.equal(rollback.context.state.records.length, 2);
});

test('parent task rows render progress without empty note separators', () => {
  const parent = {
    id: 'parent', type: 'planner', date: '2026-09-28', sample: false,
    data: { title: 'Parent', list: '工作', project: 'Project A', tags: ['urgent'], done: false, estimateMin: 30, note: '' },
  };
  const child = {
    id: 'child', type: 'planner', date: '2026-09-28', sample: false,
    data: { title: 'Child', parentTaskId: 'parent', done: false },
  };
  const { context } = createPlannerHarness([parent, child]);
  Object.assign(context, {
    plannerEstimate: () => 30,
    escapeHtml: value => String(value ?? ''),
    userHtml: value => `<span>${String(value ?? '')}</span>`,
    localizedHtml: value => String(value ?? ''),
    icon: () => '',
  });
  vm.runInNewContext(renderer.slice(taskRowStart, taskRowEnd), context, { timeout: 1500 });
  const html = context.taskRow(parent, true);
  const small = html.match(/<small>(.*?)<\/small>/)?.[1] || '';
  assert.match(small, /子任务 0\/1/);
  assert.equal((small.match(/·/g) || []).length, 1);
  assert.match(html, /class="task-subtask-btn"/);
});


test('legacy planner records enter the correct board column from their saved completion value', () => {
  const { context } = createPlannerHarness();
  assert.equal(context.plannerBoardStatus({ data: { done: false } }), 'todo');
  assert.equal(context.plannerBoardStatus({ data: { done: false, status: 'inprogress' } }), 'inprogress');
  assert.equal(context.plannerBoardStatus({ data: { done: true, status: 'inprogress' } }), 'done');
});

test('board status moves and within-column order persist without moving same-status no-ops', () => {
  const records = ['a', 'b', 'c'].map((id, index) => ({ id, type: 'planner', date: '2026-09-28', createdAt: index, sample: false, data: { title: id, done: false, status: 'todo' } }));
  const { context } = createPlannerHarness(records);
  context.state.settings = { plannerBoardOrder: { todo: ['a', 'b', 'c'], inprogress: [], done: [] } };
  assert.equal(context.plannerMoveBoardTask('b', 'todo'), true);
  assert.deepEqual(Array.from(context.state.settings.plannerBoardOrder.todo), ['a', 'b', 'c']);
  assert.equal(context.plannerMoveBoardTask('c', 'inprogress'), true);
  assert.equal(records[2].data.status, 'inprogress');
  assert.equal(records[2].data.done, false);
  assert.deepEqual(Array.from(context.state.settings.plannerBoardOrder.todo), ['a', 'b']);
  assert.deepEqual(Array.from(context.state.settings.plannerBoardOrder.inprogress), ['c']);
  assert.equal(context.plannerMoveBoardTask('c', 'todo', 'a', 'before'), true);
  assert.deepEqual(Array.from(context.state.settings.plannerBoardOrder.todo), ['c', 'a', 'b']);
});

test('board completion guards parents, preserves completion time on reorder, and clears reminder receipt on reopen', () => {
  const parent = { id: 'parent', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Parent', done: false, status: 'todo', remindedAt: 'sent' } };
  const child = { id: 'child', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Child', parentTaskId: 'parent', done: false, status: 'todo' } };
  const done = { id: 'done-task', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Done task', done: true, status: 'done', completedAt: 'original-time' } };
  const { context } = createPlannerHarness([parent, child, done]);
  context.state.settings = { plannerBoardOrder: { todo: ['parent', 'child'], inprogress: [], done: ['done-task'] } };
  assert.equal(context.plannerMoveBoardTask('parent', 'done'), false);
  assert.equal(parent.data.status, 'todo');
  child.data.done = true;
  child.data.status = 'done';
  assert.equal(context.plannerMoveBoardTask('parent', 'done'), true);
  assert.equal(parent.data.status, 'done');
  assert.ok(parent.data.completedAt);
  const originalCompletion = done.data.completedAt;
  assert.equal(context.plannerMoveBoardTask('done-task', 'done', 'parent', 'before'), true);
  assert.equal(done.data.completedAt, originalCompletion);
  assert.equal(context.plannerMoveBoardTask('parent', 'todo'), true);
  assert.equal(parent.data.status, 'todo');
  assert.equal(parent.data.remindedAt, undefined);
});

test('failed board saves roll back both the task state and its persisted column order', () => {
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'A', done: false, status: 'todo' } };
  const harness = createPlannerHarness([task]);
  harness.context.state.settings = { plannerBoardOrder: { todo: ['task-a'], inprogress: [], done: [] } };
  harness.setSaveResult(false);
  assert.equal(harness.context.plannerMoveBoardTask('task-a', 'inprogress'), false);
  assert.equal(harness.context.state.records[0].data.status, 'todo');
  assert.deepEqual(Array.from(harness.context.state.settings.plannerBoardOrder.todo), ['task-a']);
  assert.deepEqual(Array.from(harness.context.state.settings.plannerBoardOrder.inprogress), []);
});

test('board cards escape task metadata and expose keyboard reordering controls', () => {
  const task = { id: 'task-a', type: 'planner', date: '2026-09-28', sample: false, data: { title: '<img src=x onerror=alert(1)>', project: '<script>x</script>', tags: ['<svg>'], done: false } };
  const { context, elements } = createPlannerHarness([task]);
  context.escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  context.titleFor = record => record.data.title;
  context.recordTitleHtml = record => context.escapeHtml(context.titleFor(record));
  context.renderPlannerBoard([task]);
  assert.ok(elements.plannerBoard.innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.doesNotMatch(elements.plannerBoard.innerHTML, /<img src=x/);
  assert.ok(elements.plannerBoard.innerHTML.includes('&lt;script&gt;x&lt;/script&gt;'));
  assert.match(elements.plannerBoard.innerHTML, /data-planner-board-shift/);
});

test('custom board lanes filter by status and tag, add the lane tag, and persist card order', () => {
  const first = { id: 'task-a', type: 'planner', date: '2026-09-28', createdAt: 1, sample: false, data: { title: 'A', done: false, status: 'inprogress', tags: ['复核'] } };
  const second = { id: 'task-b', type: 'planner', date: '2026-09-28', createdAt: 2, sample: false, data: { title: 'B', done: false, status: 'todo', tags: [] } };
  const { context } = createPlannerHarness([first, second]);
  const board = { id: 'board-a', name: '发布流程', columns: [
    { id: 'review', title: '待复核', status: 'inprogress', tag: '复核' },
    { id: 'done', title: '完成', status: 'done', tag: '' },
  ] };
  context.state.settings.plannerCustomBoards = [board];
  assert.deepEqual(Array.from(context.plannerCustomColumnTasks(context.state.records, board, board.columns[0]), task => task.id), ['task-a']);
  assert.equal(context.plannerMoveCustomBoardTask('task-b', board.id, 'review', 'task-a', 'before', 'inprogress'), true);
  assert.equal(context.state.records[1].data.status, 'inprogress');
  assert.deepEqual(Array.from(context.state.records[1].data.tags), ['复核']);
  assert.deepEqual(Array.from(context.plannerCustomColumnTasks(context.state.records, board, board.columns[0]), task => task.id), ['task-b', 'task-a']);
  assert.deepEqual(Array.from(context.state.settings.plannerCustomBoardOrders[board.id].review), ['task-b', 'task-a']);
});

test('custom board completion keeps the subtask guard and rolls back failed saves', () => {
  const parent = { id: 'parent', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Parent', done: false, status: 'todo' } };
  const child = { id: 'child', type: 'planner', date: '2026-09-28', sample: false, data: { title: 'Child', parentTaskId: 'parent', done: false, status: 'todo' } };
  const { context, setSaveResult } = createPlannerHarness([parent, child]);
  context.state.settings.plannerCustomBoards = [{ id: 'board-a', name: '流程', columns: [{ id: 'done', title: '已完成', status: 'done', tag: '' }, { id: 'todo', title: '待办', status: 'todo', tag: '' }] }];
  assert.equal(context.plannerMoveCustomBoardTask('parent', 'board-a', 'done', '', 'append', 'done'), false);
  assert.equal(context.state.records[0].data.done, false);
  child.data.done = true;
  child.data.status = 'done';
  setSaveResult(false);
  assert.equal(context.plannerMoveCustomBoardTask('parent', 'board-a', 'done', '', 'append', 'done'), false);
  assert.equal(context.state.records[0].data.status, 'todo');
  assert.deepEqual(Object.keys(context.state.settings.plannerCustomBoardOrders), []);
});

test('matrix view groups tasks by priority and date urgency without making cards draggable', () => {
  const records = [
    { id: 'urgent-important', type: 'planner', date: '2026-09-27', data: { title: 'Urgent important', priority: 'high', done: false } },
    { id: 'important', type: 'planner', date: '2026-09-30', data: { title: 'Important', priority: 'high', done: false } },
    { id: 'urgent', type: 'planner', date: '2026-09-27', data: { title: 'Urgent', priority: 'normal', done: false } },
    { id: 'later', type: 'planner', date: '2026-09-30', data: { title: 'Later', priority: 'normal', done: false } },
    { id: 'completed', type: 'planner', date: '2026-09-27', data: { title: 'Completed', priority: 'high', done: true } },
  ];
  const { context, elements } = createPlannerHarness(records);
  context.escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  context.recordTitleHtml = record => context.escapeHtml(record.data.title);
  context.plannerRenderMatrix(records);
  assert.match(elements.plannerMatrix.innerHTML, /data-quadrant="important-urgent"[\s\S]*?data-id="urgent-important"/);
  assert.match(elements.plannerMatrix.innerHTML, /data-quadrant="important-not-urgent"[\s\S]*?data-id="completed"/);
  assert.match(elements.plannerMatrix.innerHTML, /data-quadrant="not-important-urgent"[\s\S]*?data-id="urgent"/);
  assert.match(elements.plannerMatrix.innerHTML, /data-quadrant="not-important-not-urgent"[\s\S]*?data-id="later"/);
  assert.doesNotMatch(elements.plannerMatrix.innerHTML, /data-id="urgent-important"[^>]*draggable="true"/);
});

test('planner display synchronization only updates the view switch buttons', () => {
  assert.match(renderer, /querySelectorAll\('.planner-view-switch \[data-planner-display\]'\)/);
  assert.match(renderer, /layout\.dataset\.plannerDisplay=display/);
});

test('the planner board uses the full desktop layout width', () => {
  assert.match(html, /planner-layout\[data-planner-display="board"\]>\.planner-entry-stack,.planner-layout\[data-planner-display="board"\]>\.module-main\{grid-column:1\/-1;width:100%\}/);
});

test('sync status stays outside the panels hidden by board mode', () => {
  const dayPanelStart = html.indexOf('class="panel planner-day-panel"');
  const dayPanelEnd = html.indexOf('</article>', dayPanelStart);
  const notice = html.indexOf('id="plannerSyncNotice"');
  const board = html.indexOf('id="plannerBoard"');
  assert.ok(dayPanelStart >= 0 && dayPanelEnd > dayPanelStart && notice > dayPanelEnd && notice < board);
  assert.equal((html.match(/id="plannerSyncNotice"/g) || []).length, 1);
});

test('media remote IDs survive local state normalization and reload', () => {
  const normalizeStart = renderer.indexOf('function normalizeState(candidate) {');
  const normalizeEnd = renderer.indexOf('  let dataCorrupted=false;', normalizeStart);
  assert.ok(normalizeStart >= 0 && normalizeEnd > normalizeStart, 'state normalizer must exist');
  const boardNormalizeStart = renderer.indexOf('function normalizePlannerCustomBoards(');
  const boardNormalizeEnd = renderer.indexOf('function normalizeHabit(', boardNormalizeStart);
  assert.ok(boardNormalizeStart >= 0 && boardNormalizeEnd > boardNormalizeStart);
  const calendarNormalizeStart = renderer.indexOf('function normalizeCalendarSources(');
  const calendarNormalizeEnd = renderer.indexOf('function normalizeState(candidate)', calendarNormalizeStart);
  assert.ok(calendarNormalizeStart >= 0 && calendarNormalizeEnd > calendarNormalizeStart);
  const context = {
    BRAND_DEFAULT: { name: '万象来信', avatar: '万', tagline: '把远方与日常，折进今天', theme: 'plum' },
    DEFAULT_PLAN: [], HABIT_DEFS: [], TYPE_META: { money: {}, planner: {}, fitness: {}, home: {} },
    clamp: (value, min, max) => Math.max(min, Math.min(max, value)),
    isoDate: () => '2026-09-29', uid: () => 'generated-id',
    normalizePlannerSyncQueue: value => Array.isArray(value) ? value : [],
    plannerNormalizeTags: value => Array.isArray(value) ? value.filter(Boolean).map(String).slice(0, 12) : [],
    makeInitialState: () => ({ records: [], habits: [], mediaItems: [], settings: { brand: {}, fitnessProfile: {} } }),
    normalizeHabit: () => {},
  };
  vm.runInNewContext(renderer.slice(boardNormalizeStart, boardNormalizeEnd) + '\n' + renderer.slice(calendarNormalizeStart, calendarNormalizeEnd) + '\n' + renderer.slice(normalizeStart, normalizeEnd), context, { timeout: 1500 });
  const normalized = context.normalizeState({
    records: [], habits: [], settings: {
      plannerDisplay: 'custom-board:board-a',
      plannerCustomBoards: [{ id: 'board-a', name: '发布流程', columns: [
        { id: 'todo', title: '待复核', status: 'todo', tag: '复核' },
        { id: 'done', title: '完成', status: 'done', tag: '' },
      ] }],
      plannerCustomBoardOrders: { 'board-a': { todo: ['task-a', 'task-a', 'task-b'], removed: ['task-x'] }, orphan: { todo: ['task-y'] } },
    },
    mediaItems: [{ id: 'local-media', name: '一部电影', type: '电影', date: '2026-09-29', remoteId: 'remote-media-42' }],
    calendarSources: [{ id: 'ics-file:work', name: 'Work calendar', type: 'ics-file', icsText: 'BEGIN:VCALENDAR', eventCount: 3, importedAt: '2026-09-29T00:00:00.000Z' }],
  });
  assert.equal(normalized.mediaItems[0].remoteId, 'remote-media-42');
  assert.equal(normalized.calendarSources[0].name, 'Work calendar');
  assert.equal(normalized.calendarSources[0].eventCount, 3);
  assert.equal(normalized.settings.plannerDisplay, 'custom-board:board-a');
  assert.equal(normalized.settings.plannerCustomBoards[0].columns.length, 2);
  assert.deepEqual(Array.from(normalized.settings.plannerCustomBoardOrders['board-a'].todo), ['task-a', 'task-b']);
  assert.equal(normalized.settings.plannerCustomBoardOrders.orphan, undefined);
});

test('the planner form and list expose project and tag organization controls', () => {
  assert.match(html, /name="project" maxlength="60"/);
  assert.match(html, /name="tags" maxlength="360"/);
  assert.match(html, /id="plannerProjectFilter"/);
  assert.match(html, /id="plannerTagFilter"/);
  assert.match(html, /id="plannerSubtaskDialog"/);
  assert.match(html, /data-action="add-subtask"/);
});

test('the calendar source panel exposes encrypted CalDAV collection setup', () => {
  assert.match(html, /id="plannerCalDavForm"/);
  assert.match(html, /HTTPS CalDAV 日历集地址/);
  assert.match(html, /name="username"/);
  assert.match(html, /name="password" type="password"/);
  assert.match(html, /地址和凭据由 Windows 加密保存/);
});
