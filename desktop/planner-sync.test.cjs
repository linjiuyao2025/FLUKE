'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const Sync = require('./planner-sync.js');

const deviceA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const deviceB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

function task(id, title, version, extra = {}) {
  return {
    id, type: 'planner', date: '2026-09-29', createdAt: 10, webdavSyncVersion: version,
    data: { title, done: false, list: '生活', note: '', ...extra },
  };
}

function snapshot(deviceId, tasks = [], tombstones = [], conflicts = [], vector = {}) {
  return { format: Sync.FORMAT, version: Sync.VERSION, deviceId, vector, tasks, tombstones, conflicts };
}

test('version vectors distinguish causal updates from concurrent edits', () => {
  assert.equal(Sync.compareVectors({ [deviceA]: 2 }, { [deviceA]: 1 }), 'dominates');
  assert.equal(Sync.compareVectors({ [deviceA]: 1, [deviceB]: 2 }, { [deviceA]: 2 }), 'concurrent');
  assert.equal(Sync.compareVectors({ [deviceA]: 1 }, { [deviceA]: 1 }), 'equal');
  assert.deepEqual(Sync.mergeVectors({ [deviceA]: 1 }, { [deviceB]: 3 }), { [deviceA]: 1, [deviceB]: 3 });
});

test('local planner edits receive a new causal version and deleted tasks leave tombstones', () => {
  const previous = { records: [task('task-a', 'Old title', { [deviceA]: 1 })], settings: { webdavPlannerVector: { [deviceA]: 1 } } };
  const current = structuredClone(previous);
  current.records[0].data.title = 'Changed title';
  current.records.push(task('task-b', 'New task', {}));
  current.records.push({ ...task('external', 'CalDAV task', {}), data: { title: 'CalDAV task', externalTodo: { provider: 'caldav' } } });
  assert.equal(Sync.stampLocalChanges(previous, current, deviceA), true);
  assert.deepEqual(current.records[0].webdavSyncVersion, { [deviceA]: 2 });
  assert.deepEqual(current.records[1].webdavSyncVersion, { [deviceA]: 2 });
  assert.deepEqual(current.records[2].webdavSyncVersion, {});

  const afterDelete = structuredClone(current);
  afterDelete.records = afterDelete.records.filter((item) => item.id !== 'task-a');
  assert.equal(Sync.stampLocalChanges(current, afterDelete, deviceA), true);
  assert.deepEqual(afterDelete.settings.webdavPlannerTombstones, [{ id: 'task-a', version: { [deviceA]: 3 } }]);
});

test('duplicate deletion tombstones merge their version vectors instead of dropping newer history', () => {
  assert.deepEqual(Sync.normalizeTombstones([
    { id: 'task-a', version: { [deviceA]: 1 } },
    { id: 'task-a', version: { [deviceB]: 2 } },
  ]), [{ id: 'task-a', version: { [deviceA]: 1, [deviceB]: 2 } }]);
});

test('malformed remote task and version entries reject the whole snapshot instead of being silently dropped', () => {
  assert.equal(Sync.normalizeSnapshot(snapshot(deviceA, [
    task('valid', 'Keep me', { [deviceA]: 1 }),
    { ...task('broken', 'Invalid date', { [deviceA]: 1 }), date: 'not-a-date' },
  ])), null);
  assert.equal(Sync.normalizeSnapshot(snapshot(deviceA, [task('unversioned', 'Unversioned task', {})])), null);
  assert.equal(Sync.normalizeSnapshot(snapshot(deviceA, [task('valid', 'Keep me', { [deviceA]: 1 })], [
    { id: 'deleted', version: { 'bad device id': 2 } },
  ])), null);
  assert.equal(Sync.normalizeSnapshot({ ...snapshot(deviceA), vector: { [deviceA]: -1 } }), null);
});

test('sync combines disjoint task changes and keeps the causally newer version', () => {
  const older = task('shared', 'Old', { [deviceA]: 1 });
  const newer = task('shared', 'New', { [deviceA]: 2 });
  const merged = Sync.mergeSnapshots(
    snapshot(deviceA, [older, task('a-only', 'A', { [deviceA]: 1 })], [], [], { [deviceA]: 1 }),
    snapshot(deviceB, [newer, task('b-only', 'B', { [deviceB]: 1 })], [], [], { [deviceB]: 1 }),
  );
  assert.deepEqual(merged.tasks.map((item) => item.id), ['a-only', 'b-only', 'shared']);
  assert.equal(merged.tasks.find((item) => item.id === 'shared').data.title, 'New');
  assert.equal(merged.conflicts.length, 0);
});

test('concurrent edits to the same task stay visible as a conflict instead of disappearing', () => {
  const merged = Sync.mergeSnapshots(
    snapshot(deviceA, [task('shared', 'Title from A', { [deviceA]: 2 })], [], [], { [deviceA]: 2 }),
    snapshot(deviceB, [task('shared', 'Title from B', { [deviceB]: 3 })], [], [], { [deviceB]: 3 }),
  );
  assert.equal(merged.tasks.length, 1);
  assert.ok(['Title from A', 'Title from B'].includes(merged.tasks[0].data.title));
  assert.equal(merged.conflicts.length, 1);
  assert.deepEqual(new Set(merged.conflicts[0].variants.map((item) => item.record.data.title)), new Set(['Title from A', 'Title from B']));
});

test('concurrent focus sessions on an otherwise unchanged task merge by stable session ID', () => {
  const left = task('shared', 'Same task', { [deviceA]: 4 }, { sessions: [{ id: 'focus-a', date: '2026-09-29', seconds: 300 }] });
  const right = task('shared', 'Same task', { [deviceB]: 2 }, { sessions: [{ id: 'focus-b', date: '2026-09-29', seconds: 600 }] });
  const merged = Sync.mergeSnapshots(snapshot(deviceA, [left]), snapshot(deviceB, [right]));
  assert.equal(merged.conflicts.length, 0);
  assert.equal(merged.tasks[0].data.sessions.length, 2);
  assert.equal(merged.tasks[0].data.trackedSeconds, 900);
  assert.deepEqual(merged.tasks[0].webdavSyncVersion, { [deviceA]: 4, [deviceB]: 2 });
});

test('a causally later deletion removes a task, while a concurrent delete remains reviewable', () => {
  const deleted = Sync.mergeSnapshots(
    snapshot(deviceA, [task('gone', 'Task', { [deviceA]: 1 })]),
    snapshot(deviceB, [], [{ id: 'gone', version: { [deviceA]: 2 } }]),
  );
  assert.equal(deleted.tasks.length, 0);
  assert.equal(deleted.tombstones[0].id, 'gone');
  assert.equal(deleted.conflicts.length, 0);

  const concurrent = Sync.mergeSnapshots(
    snapshot(deviceA, [task('maybe', 'Edited task', { [deviceA]: 3 })]),
    snapshot(deviceB, [], [{ id: 'maybe', version: { [deviceB]: 1 } }]),
  );
  assert.equal(concurrent.tasks.length, 1);
  assert.equal(concurrent.tombstones.length, 1);
  assert.equal(concurrent.conflicts.length, 1);
  assert.equal(concurrent.conflicts[0].variants.some((item) => item.deleted), true);
});

test('a conflict can be resolved to one task or preserved as a separate copy', () => {
  const merged = Sync.mergeSnapshots(
    snapshot(deviceA, [task('shared', 'One', { [deviceA]: 1 })]),
    snapshot(deviceB, [task('shared', 'Two', { [deviceB]: 1 })]),
  );
  const state = { records: structuredClone(merged.tasks), settings: { webdavPlannerVector: merged.vector, webdavPlannerTombstones: merged.tombstones, webdavPlannerConflicts: merged.conflicts } };
  assert.equal(Sync.resolveConflict(state, 'shared', 0, deviceA, true), true);
  assert.equal(state.settings.webdavPlannerConflicts.length, 0);
  assert.equal(state.records.length, 2);
  assert.ok(state.records.some((item) => item.data.webdavConflictOf === 'shared'));
  assert.deepEqual(Sync.snapshotFromState(state, deviceA).tasks.map((item) => item.id).sort(), state.records.map((item) => item.id).sort());
});

test('choosing a concurrent deletion can still preserve the edited task as a separate copy', () => {
  const merged = Sync.mergeSnapshots(
    snapshot(deviceA, [task('shared', 'Edited on A', { [deviceA]: 2 })]),
    snapshot(deviceB, [], [{ id: 'shared', version: { [deviceB]: 1 } }]),
  );
  const state = { records: structuredClone(merged.tasks), settings: { webdavPlannerVector: merged.vector, webdavPlannerTombstones: merged.tombstones, webdavPlannerConflicts: merged.conflicts } };
  const deleteIndex = merged.conflicts[0].variants.findIndex(item => item.deleted);
  assert.equal(Sync.resolveConflict(state, 'shared', deleteIndex, deviceA, true), true);
  assert.equal(state.records.length, 1);
  assert.match(state.records[0].id, /^shared:copy:/u);
  assert.equal(state.records[0].data.webdavConflictOf, 'shared');
  assert.equal(state.settings.webdavPlannerTombstones.some(item => item.id === 'shared'), true);
});

test('resolving a task-content conflict keeps every focus session and can save all live variants', () => {
  const merged = Sync.mergeSnapshots(
    snapshot(deviceA, [task('shared', 'Version A', { [deviceA]: 1 }, { sessions: [{ id: 'focus-a', date: '2026-09-29', seconds: 300 }] })]),
    snapshot(deviceB, [task('shared', 'Version B', { [deviceB]: 1 }, { sessions: [{ id: 'focus-b', date: '2026-09-29', seconds: 600 }] })]),
  );
  const state = { records: structuredClone(merged.tasks), settings: { webdavPlannerVector: merged.vector, webdavPlannerTombstones: merged.tombstones, webdavPlannerConflicts: merged.conflicts } };
  assert.equal(Sync.resolveConflict(state, 'shared', 0, deviceA), true);
  assert.equal(state.records.length, 1);
  assert.deepEqual(new Set(state.records[0].data.sessions.map(session => session.id)), new Set(['focus-a', 'focus-b']));
  assert.equal(state.records[0].data.trackedSeconds, 900);

  const thirdDevice = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  const three = Sync.mergeSnapshots(
    snapshot(deviceA, [task('multi', 'A', { [deviceA]: 1 })]),
    snapshot(deviceB, [task('multi', 'B', { [deviceB]: 1 })]),
    snapshot(thirdDevice, [task('multi', 'C', { [thirdDevice]: 1 })]),
  );
  const keepState = { records: structuredClone(three.tasks), settings: { webdavPlannerVector: three.vector, webdavPlannerTombstones: three.tombstones, webdavPlannerConflicts: three.conflicts } };
  assert.equal(three.conflicts[0].variants.length, 3);
  assert.equal(Sync.resolveConflict(keepState, 'multi', 0, deviceA, true), true);
  assert.equal(keepState.records.length, 3);
  assert.equal(new Set(keepState.records.map(item => item.id)).size, 3);
});

test('applying a merged snapshot preserves device-local remote IDs and unrelated records', () => {
  const local = task('shared', 'Local stale', { [deviceA]: 1 });
  local.remoteId = 'notion-row';
  const remote = task('shared', 'Remote new', { [deviceA]: 2 });
  const state = { records: [local, { id: 'money', type: 'money', date: '2026-09-29', data: {} }], settings: {} };
  const merged = Sync.mergeSnapshots(snapshot(deviceB, [remote]));
  assert.equal(Sync.applyMergedSnapshot(state, merged), true);
  assert.equal(state.records.find((item) => item.id === 'shared').data.title, 'Remote new');
  assert.equal(state.records.find((item) => item.id === 'shared').remoteId, 'notion-row');
  assert.ok(state.records.some((item) => item.id === 'money'));
});
