'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { ReminderService, normalizeReminder, reminderKey } = require('./reminder-service.cjs');

function fakeTimers() {
  let sequence = 0;
  const timers = new Map();
  return {
    timers,
    setTimer(callback, delay) {
      const timer = { id: ++sequence, callback, delay, unref() {} };
      timers.set(timer.id, timer);
      return timer;
    },
    clearTimer(timer) { timers.delete(timer.id); },
  };
}

async function createService(t, options = {}) {
  const directory = options.directory || await fs.mkdtemp(path.join(os.tmpdir(), 'wanxiang-reminder-'));
  if (!options.directory) t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const timers = fakeTimers();
  const service = new ReminderService({
    storagePath: path.join(directory, 'planner-reminders.json'),
    notify: options.notify || (() => {}),
    onFired: options.onFired,
    onPendingChanged: options.onPendingChanged,
    onError: options.onError,
    now: options.now,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  await service.load();
  return { service, timers, directory };
}

function dateAt(hour, minute = 0, day = 28) {
  return new Date(2026, 8, day, hour, minute).getTime();
}

function reminder(id, time, overrides = {}) {
  return {
    id,
    date: '2026-09-28',
    time,
    title: '整理日程',
    body: '查看今天的计划',
    ...overrides,
  };
}

test('reminder normalization rejects invalid identifiers, dates, and times and bounds notification text', () => {
  assert.equal(normalizeReminder({ id: 'x', date: '2026-02-30', time: '09:00' }), null);
  assert.equal(normalizeReminder({ id: 'x', date: '2026-09-28', time: '24:00' }), null);
  assert.equal(normalizeReminder({ id: ' ', date: '2026-09-28', time: '09:00' }), null);
  const normalized = normalizeReminder(reminder('x', '09:00', { title: '标'.repeat(200), body: '注'.repeat(400) }));
  assert.equal(normalized.title.length, 160);
  assert.equal(normalized.body.length, 300);
});

test('sync schedules one reminder and repeated identical sync keeps its existing timer', async t => {
  const { service, timers } = await createService(t, { now: () => dateAt(8) });
  const item = reminder('task-a', '09:00');
  const first = await service.sync([item]);
  const firstTimer = [...timers.timers.values()][0];
  const second = await service.sync([item]);
  assert.equal(first.pendingCount, 1);
  assert.equal(second.pendingCount, 1);
  assert.equal(timers.timers.size, 1);
  assert.equal([...timers.timers.values()][0], firstTimer);
  assert.equal(firstTimer.delay, 60 * 60 * 1000);
});

test('sync removes timers when reminders are completed, disabled, or deleted', async t => {
  const { service, timers } = await createService(t, { now: () => dateAt(8) });
  await service.sync([reminder('task-a', '09:00'), reminder('task-b', '10:00')]);
  assert.equal(service.pendingCount, 2);
  const result = await service.sync([reminder('task-b', '10:00')]);
  assert.equal(result.pendingCount, 1);
  assert.equal(timers.timers.size, 1);
  assert.equal([...service.pending.values()][0].id, 'task-b');
  await service.sync([]);
  assert.equal(service.pendingCount, 0);
  assert.equal(timers.timers.size, 0);
});

test('a due reminder notifies once and persists a fired receipt before acknowledging the renderer', async t => {
  const notifications = [];
  const fired = [];
  const changes = [];
  const { service } = await createService(t, {
    now: () => dateAt(8),
    notify: value => notifications.push(value.id),
    onFired: value => fired.push(value),
    onPendingChanged: value => changes.push(value),
  });
  await service.sync([reminder('task-a', '09:00')]);
  const key = reminderKey(normalizeReminder(reminder('task-a', '09:00')));
  const before = JSON.parse(await fs.readFile(service.storagePath, 'utf8'));
  assert.equal(before.pending.length, 1);
  assert.equal(await service.fire(key), true);
  assert.equal(await service.fire(key), false);
  const persisted = JSON.parse(await fs.readFile(service.storagePath, 'utf8'));
  assert.equal(persisted.pending.length, 0);
  assert.equal(persisted.fired.length, 1);
  assert.deepEqual(notifications, ['task-a']);
  assert.equal(fired.length, 1);
  assert.equal(changes.at(-1), 0);
});

test('pending reminders restore after restart and fired reminders are returned for local acknowledgement', async t => {
  const now = () => dateAt(8);
  const first = await createService(t, { now });
  const item = reminder('task-a', '09:00');
  await first.service.sync([item]);
  const key = reminderKey(normalizeReminder(item));
  await first.service.fire(key);

  const notified = [];
  const restarted = await createService(t, { directory: first.directory, now, notify: value => notified.push(value.id) });
  assert.equal(restarted.service.pendingCount, 0);
  const receipt = await restarted.service.sync([item]);
  assert.equal(receipt.fired.length, 1);
  assert.equal(receipt.fired[0].id, 'task-a');
  assert.deepEqual(notified, []);
});

test('startup drops reminders from a previous day rather than replaying stale notifications', async t => {
  const first = await createService(t, { now: () => dateAt(8) });
  await first.service.sync([reminder('task-a', '23:00')]);

  const nextDay = new Date(2026, 8, 29, 8).getTime();
  const restarted = await createService(t, { now: () => nextDay });
  await restarted.service.load();
  assert.equal(restarted.service.pendingCount, 0);
  assert.equal(restarted.timers.timers.size, 0);
});

test('startup discards a corrupt fired timestamp instead of crashing receipt synchronization', async t => {
  const initial = await createService(t, { now: () => dateAt(8) });
  await fs.writeFile(initial.service.storagePath, JSON.stringify({
    version: 1,
    pending: [],
    fired: [{ ...reminder('bad-receipt', '09:00'), firedAt: Number.MAX_VALUE }],
  }));
  const restarted = await createService(t, { directory: initial.directory, now: () => dateAt(8) });
  const result = await restarted.service.sync([reminder('bad-receipt', '09:00')]);
  assert.equal(result.fired.length, 0);
  assert.equal(result.pendingCount, 1);
});

test('sync retains future-day reminders and safely ignores malformed payloads', async t => {
  const { service, timers } = await createService(t, { now: () => dateAt(8) });
  const result = await service.sync([
    reminder('tomorrow', '09:00', { date: '2026-09-29' }),
    { id: {}, date: '2026-09-28', time: '09:00' },
    reminder('invalid-time', '99:99'),
  ]);
  assert.equal(result.pendingCount, 1);
  assert.equal(timers.timers.size, 1);
  assert.equal([...service.pending.values()][0].id, 'tomorrow');
});
