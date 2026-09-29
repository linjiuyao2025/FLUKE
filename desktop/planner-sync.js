'use strict';

(function attachPlannerSync(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.WanxiangPlannerSync = api;
})(typeof globalThis === 'object' ? globalThis : this, function createPlannerSync() {
  const FORMAT = 'wanxiang-planner-sync';
  const VERSION = 1;

  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  function normalizeDeviceId(value) {
    return typeof value === 'string' && /^[A-Za-z0-9-]{8,80}$/u.test(value) ? value : '';
  }

  function normalizeVector(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const vector = {};
    Object.keys(value).sort().slice(0, 1000).forEach((key) => {
      const counter = Number(value[key]);
      if (normalizeDeviceId(key) && Number.isSafeInteger(counter) && counter >= 0) vector[key] = counter;
    });
    return vector;
  }

  function hasValidVector(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const entries = Object.entries(value);
    return entries.length <= 1000 && entries.every(([device, counter]) => normalizeDeviceId(device)
      && Number.isSafeInteger(counter) && counter >= 0);
  }

  function mergeVectors(...values) {
    const result = {};
    values.forEach((value) => Object.entries(normalizeVector(value)).forEach(([device, counter]) => {
      result[device] = Math.max(result[device] || 0, counter);
    }));
    return Object.fromEntries(Object.entries(result).sort(([left], [right]) => left.localeCompare(right)));
  }

  function compareVectors(leftValue, rightValue) {
    const left = normalizeVector(leftValue), right = normalizeVector(rightValue);
    let leftHigher = false, rightHigher = false;
    for (const device of new Set([...Object.keys(left), ...Object.keys(right)])) {
      const a = left[device] || 0, b = right[device] || 0;
      if (a > b) leftHigher = true;
      else if (b > a) rightHigher = true;
    }
    if (leftHigher && rightHigher) return 'concurrent';
    if (leftHigher) return 'dominates';
    if (rightHigher) return 'dominated';
    return 'equal';
  }

  function isSyncableTask(record) {
    return Boolean(record && record.type === 'planner' && !record.sample && record.data
      && typeof record.data === 'object' && !record.data.externalTodo?.provider);
  }

  function taskContent(record) {
    const value = clone(record);
    delete value.remoteId;
    delete value.webdavSyncVersion;
    value.sample = false;
    return value;
  }

  function taskCore(record) {
    const value = taskContent(record);
    if (value.data) {
      delete value.data.sessions;
      delete value.data.trackedSeconds;
    }
    return JSON.stringify(value);
  }

  function taskVersion(record, fallback) {
    const version = normalizeVector(record && record.webdavSyncVersion);
    return Object.keys(version).length ? version : normalizeVector(fallback);
  }

  function normalizeTask(raw, fallbackVector) {
    if (!isSyncableTask(raw) || typeof raw.id !== 'string' || !raw.id || raw.id.length > 180
      || !/^\d{4}-\d{2}-\d{2}$/u.test(raw.date) || Array.isArray(raw.data)
      || (raw.webdavSyncVersion != null && !hasValidVector(raw.webdavSyncVersion))) return null;
    const record = taskContent(raw);
    record.webdavSyncVersion = taskVersion(raw, fallbackVector);
    return record;
  }

  function normalizeTombstones(value) {
    if (!Array.isArray(value)) return [];
    const result = new Map();
    value.slice(-100_000).forEach((item) => {
      const id = typeof item?.id === 'string' ? item.id : '';
      const version = normalizeVector(item?.version);
      if (!id || id.length > 180 || !Object.keys(version).length) return;
      result.set(id, { id, version: mergeVectors(result.get(id)?.version, version) });
    });
    return [...result.values()].sort((left, right) => left.id.localeCompare(right.id));
  }

  function normalizeVariant(value, fallbackVector) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const id = typeof value.id === 'string' ? value.id : '';
    if ((value.version != null && !hasValidVector(value.version)) || !hasValidVector(value.version || fallbackVector)) return null;
    const version = normalizeVector(value.version || fallbackVector);
    if (!id || id.length > 180 || !Object.keys(version).length) return null;
    if (value.deleted === true) return { id, deleted: true, version };
    const record = normalizeTask(value.record, version);
    return record && record.id === id ? { id, deleted: false, version, record } : null;
  }

  function normalizeConflict(value, fallbackVector) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.id !== 'string') return null;
    const variants = Array.isArray(value.variants)
      ? value.variants.map((item) => normalizeVariant(item, fallbackVector)).filter((item) => item && item.id === value.id)
      : [];
    const unique = new Map(variants.map((item) => [JSON.stringify(item), item]));
    return unique.size > 1 ? { id: value.id, variants: [...unique.values()] } : null;
  }

  function normalizeConflicts(value, fallbackVector = {}) {
    return Array.isArray(value)
      ? value.slice(0, 20_000).map((item) => normalizeConflict(item, fallbackVector)).filter(Boolean)
      : [];
  }

  function normalizeSnapshot(value) {
    if (!value || value.format !== FORMAT || value.version !== VERSION) return null;
    const deviceId = normalizeDeviceId(value.deviceId);
    if (!deviceId || !hasValidVector(value.vector)) return null;
    const vector = normalizeVector(value.vector);
    if (!Array.isArray(value.tasks) || value.tasks.length > 50_000) return null;
    const tasks = value.tasks.map((item) => normalizeTask(item, vector));
    if (tasks.some((item) => !item || !Object.keys(item.webdavSyncVersion).length)) return null;
    const rawTombstones = value.tombstones === undefined ? [] : value.tombstones;
    if (!Array.isArray(rawTombstones) || rawTombstones.length > 100_000
      || rawTombstones.some((item) => typeof item?.id !== 'string' || !item.id || item.id.length > 180 || !hasValidVector(item.version) || !Object.keys(item.version).length)) return null;
    const tombstones = normalizeTombstones(rawTombstones);
    const rawConflicts = value.conflicts === undefined ? [] : value.conflicts;
    if (!Array.isArray(rawConflicts) || rawConflicts.length > 20_000) return null;
    const conflicts = normalizeConflicts(rawConflicts, vector);
    if (conflicts.length !== rawConflicts.length) return null;
    return { format: FORMAT, version: VERSION, deviceId, vector, tasks, tombstones, conflicts };
  }

  function changedPlannerRecords(previous, current) {
    const before = new Map((Array.isArray(previous?.records) ? previous.records : []).filter(isSyncableTask).map((record) => [record.id, taskContent(record)]));
    const after = new Map((Array.isArray(current?.records) ? current.records : []).filter(isSyncableTask).map((record) => [record.id, record]));
    const changed = [];
    after.forEach((record, id) => {
      const old = before.get(id);
      if (!old || JSON.stringify(taskContent(old)) !== JSON.stringify(taskContent(record))) changed.push(record);
    });
    const deleted = [...before.keys()].filter((id) => !after.has(id));
    return { changed, deleted };
  }

  function stampLocalChanges(previous, current, deviceId) {
    const id = normalizeDeviceId(deviceId);
    if (!id || !current || !Array.isArray(current.records)) return false;
    current.settings = current.settings || {};
    const { changed, deleted } = changedPlannerRecords(previous, current);
    if (!changed.length && !deleted.length) return false;
    const vector = normalizeVector(current.settings.webdavPlannerVector);
    const maxSeen = Math.max(0, ...Object.values(vector));
    vector[id] = Math.max(vector[id] || 0, maxSeen) + 1;
    current.settings.webdavPlannerVector = vector;
    const existing = new Map(normalizeTombstones(current.settings.webdavPlannerTombstones).map((item) => [item.id, item]));
    changed.forEach((record) => {
      record.webdavSyncVersion = { ...vector };
      existing.delete(record.id);
    });
    deleted.forEach((recordId) => existing.set(recordId, { id: recordId, version: { ...vector } }));
    current.settings.webdavPlannerTombstones = [...existing.values()];
    return true;
  }

  function snapshotFromState(state, deviceId) {
    const id = normalizeDeviceId(deviceId);
    if (!id) throw new TypeError('A stable planner sync device ID is required.');
    const settings = state?.settings || {};
    const vector = normalizeVector(settings.webdavPlannerVector);
    const tasks = (Array.isArray(state?.records) ? state.records : []).filter(isSyncableTask)
      .map((record) => normalizeTask(record, Object.keys(normalizeVector(record.webdavSyncVersion)).length ? record.webdavSyncVersion : { [id]: 0 }))
      .filter(Boolean);
    const conflicts = normalizeConflicts(settings.webdavPlannerConflicts, vector);
    return {
      format: FORMAT, version: VERSION, deviceId: id, vector,
      tasks, tombstones: normalizeTombstones(settings.webdavPlannerTombstones), conflicts,
    };
  }

  function mergeSessions(left, right) {
    const sessions = new Map();
    [...(Array.isArray(left) ? left : []), ...(Array.isArray(right) ? right : [])].forEach((session) => {
      if (!session || typeof session !== 'object' || typeof session.id !== 'string' || !session.id) return;
      const key = `${session.id}\u0000${String(session.date || '')}`;
      const previous = sessions.get(key);
      if (!previous) sessions.set(key, clone(session));
      else sessions.set(key, {
        ...previous,
        ...session,
        seconds: Math.max(Number(previous.seconds) || 0, Number(session.seconds) || 0),
        startedAt: [previous.startedAt, session.startedAt].filter(Boolean).sort()[0] || '',
        endedAt: [previous.endedAt, session.endedAt].filter(Boolean).sort().at(-1) || '',
      });
    });
    return [...sessions.values()].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')) || String(a.startedAt || '').localeCompare(String(b.startedAt || '')) || a.id.localeCompare(b.id));
  }

  function stableVariantKey(variant) { return JSON.stringify({ version: normalizeVector(variant.version), record: variant.record || null, deleted: Boolean(variant.deleted) }); }

  function mergeVariantsForId(id, candidates) {
    const unique = new Map(candidates.map((item) => [stableVariantKey(item), item]));
    let variants = [...unique.values()];
    const tasks = variants.filter((item) => !item.deleted);
    for (let i = 0; i < tasks.length; i += 1) {
      for (let j = i + 1; j < tasks.length; j += 1) {
        const left = tasks[i], right = tasks[j];
        if (taskCore(left.record) !== taskCore(right.record)) continue;
        const relation = compareVectors(left.version, right.version);
        if (!['concurrent', 'equal'].includes(relation)) continue;
        const record = clone(relation === 'dominated' ? right.record : left.record);
        record.data = record.data || {};
        record.data.sessions = mergeSessions(left.record.data?.sessions, right.record.data?.sessions);
        record.data.trackedSeconds = Math.max(
          Number(left.record.data?.trackedSeconds) || 0,
          Number(right.record.data?.trackedSeconds) || 0,
          record.data.sessions.reduce((sum, session) => sum + (Number(session.seconds) || 0), 0),
        );
        const version = mergeVectors(left.version, right.version);
        record.webdavSyncVersion = version;
        variants = variants.filter((item) => item !== left && item !== right);
        variants.push({ id, deleted: false, version, record });
        i = -1;
        break;
      }
      if (i < 0) break;
    }
    const deletes = variants.filter((item) => item.deleted);
    if (deletes.length > 1) {
      const version = mergeVectors(...deletes.map((item) => item.version));
      variants = variants.filter((item) => !item.deleted);
      variants.push({ id, deleted: true, version });
    }
    variants = variants.filter((candidate, index) => !variants.some((other, otherIndex) => {
      if (index === otherIndex) return false;
      const relation = compareVectors(other.version, candidate.version);
      if (relation === 'dominates') return true;
      return false;
    }));

    const tombstone = variants.find((item) => item.deleted);
    let live = variants.filter((item) => !item.deleted);
    if (tombstone) {
      const relations = live.map((item) => compareVectors(item.version, tombstone.version));
      if (relations.includes('concurrent')) variants = [...live.filter((_item, index) => relations[index] !== 'dominated'), tombstone];
      else if (relations.includes('dominates')) variants = live.filter((_item, index) => relations[index] === 'dominates');
      else variants = [tombstone];
    } else variants = live;

    const taskVariants = variants.filter((item) => !item.deleted);
    const selected = taskVariants.slice().sort((a, b) => stableVariantKey(a).localeCompare(stableVariantKey(b)))[0] || null;
    const conflict = variants.length > 1 ? { id, variants: variants.map((item) => ({ ...item, version: normalizeVector(item.version) })) } : null;
    return { selected, tombstone: variants.find((item) => item.deleted) || null, conflict };
  }

  function mergeSnapshots(...inputValues) {
    const snapshots = inputValues.map(normalizeSnapshot).filter(Boolean);
    const grouped = new Map();
    const add = (variant) => {
      const list = grouped.get(variant.id) || [];
      list.push(variant);
      grouped.set(variant.id, list);
    };
    snapshots.forEach((snapshot) => {
      snapshot.tasks.forEach((record) => add({ id: record.id, deleted: false, version: record.webdavSyncVersion, record }));
      snapshot.tombstones.forEach((item) => add({ id: item.id, deleted: true, version: item.version }));
      snapshot.conflicts.forEach((item) => item.variants.forEach(add));
    });
    const tasks = [], tombstones = [], conflicts = [];
    grouped.forEach((candidates, id) => {
      const result = mergeVariantsForId(id, candidates);
      if (result.selected) tasks.push(result.selected.record);
      if (result.tombstone) tombstones.push({ id, version: result.tombstone.version });
      if (result.conflict) conflicts.push(result.conflict);
    });
    const vector = mergeVectors(...snapshots.map((item) => item.vector), ...tasks.map((item) => item.webdavSyncVersion), ...tombstones.map((item) => item.version));
    tasks.sort((a, b) => a.date.localeCompare(b.date) || String(a.data.title || '').localeCompare(String(b.data.title || '')) || a.id.localeCompare(b.id));
    tombstones.sort((a, b) => a.id.localeCompare(b.id));
    conflicts.sort((a, b) => a.id.localeCompare(b.id));
    return { format: FORMAT, version: VERSION, deviceId: snapshots[0]?.deviceId || '', vector, tasks, tombstones, conflicts };
  }

  function applyMergedSnapshot(state, mergedValue) {
    const merged = normalizeSnapshot(mergedValue);
    if (!merged || !state || !Array.isArray(state.records)) return false;
    const previousById = new Map(state.records.filter(isSyncableTask).map((record) => [record.id, record]));
    const keep = state.records.filter((record) => !isSyncableTask(record));
    const tasks = merged.tasks.map((record) => {
      const local = previousById.get(record.id);
      return local?.remoteId ? { ...record, remoteId: local.remoteId } : record;
    });
    state.records = [...keep, ...tasks];
    state.settings = state.settings || {};
    state.settings.webdavPlannerVector = merged.vector;
    state.settings.webdavPlannerTombstones = merged.tombstones;
    state.settings.webdavPlannerConflicts = merged.conflicts;
    return true;
  }

  function resolveConflict(state, id, variantIndex, deviceId, keepBoth = false) {
    const key = String(id || ''), device = normalizeDeviceId(deviceId);
    const conflicts = Array.isArray(state?.settings?.webdavPlannerConflicts) ? state.settings.webdavPlannerConflicts : [];
    const conflict = conflicts.find((item) => item.id === key);
    const selected = conflict?.variants?.[variantIndex];
    if (!conflict || !selected || !device) return false;
    const version = mergeVectors(state.settings.webdavPlannerVector, ...conflict.variants.map((item) => item.version));
    const nextVersion = { ...version, [device]: Math.max(0, ...Object.values(version)) + 1 };
    const existing = state.records.find((record) => record.id === key && isSyncableTask(record));
    state.records = state.records.filter((record) => record.id !== key || !isSyncableTask(record));
    let seenSessions = new Set();
    if (!selected.deleted) {
      const chosen = clone(selected.record);
      chosen.webdavSyncVersion = nextVersion;
      if (existing?.remoteId) chosen.remoteId = existing.remoteId;
      if (keepBoth) {
        seenSessions = new Set((chosen.data?.sessions || []).map((session) => `${session.id}\u0000${String(session.date || '')}`));
      } else {
        chosen.data = chosen.data || {};
        chosen.data.sessions = mergeSessions(...conflict.variants.filter((item) => !item.deleted).map((item) => item.record.data?.sessions));
        chosen.data.trackedSeconds = Math.max(
          ...conflict.variants.filter((item) => !item.deleted).map((item) => Number(item.record.data?.trackedSeconds) || 0),
          chosen.data.sessions.reduce((sum, session) => sum + (Number(session.seconds) || 0), 0),
        );
      }
      state.records.push(chosen);
    }
    if (keepBoth) {
      conflict.variants.forEach((alternative, index) => {
        if (index === variantIndex || alternative.deleted) return;
        const copy = clone(alternative.record);
        copy.id = `${key}:copy:${device}:${nextVersion[device]}:${index}`.slice(0, 180);
        copy.remoteId = '';
        copy.webdavSyncVersion = nextVersion;
        const sessions = Array.isArray(copy.data?.sessions) ? copy.data.sessions : [];
        const kept = sessions.filter((session) => {
          const sessionKey = `${session.id}\u0000${String(session.date || '')}`;
          if (seenSessions.has(sessionKey)) return false;
          seenSessions.add(sessionKey);
          return true;
        });
        const removedSeconds = sessions.filter((session) => !kept.includes(session)).reduce((sum, session) => sum + (Number(session.seconds) || 0), 0);
        copy.data = {
          ...copy.data, sessions: kept,
          trackedSeconds: Math.max(kept.reduce((sum, session) => sum + (Number(session.seconds) || 0), 0), (Number(copy.data?.trackedSeconds) || 0) - removedSeconds),
          title: `${copy.data.title || '未命名任务'}（并发副本）`, webdavConflictOf: key,
        };
        state.records.push(copy);
      });
    }
    state.settings.webdavPlannerVector = nextVersion;
    const tombstones = new Map(normalizeTombstones(state.settings.webdavPlannerTombstones).map((item) => [item.id, item]));
    if (selected.deleted) tombstones.set(key, { id: key, version: nextVersion });
    else tombstones.delete(key);
    state.settings.webdavPlannerTombstones = [...tombstones.values()];
    state.settings.webdavPlannerConflicts = conflicts.filter((item) => item.id !== key);
    return true;
  }

  return Object.freeze({
    FORMAT, VERSION, normalizeVector, normalizeTombstones, normalizeConflicts, mergeVectors, compareVectors, normalizeSnapshot,
    stampLocalChanges, snapshotFromState, mergeSnapshots, applyMergedSnapshot, resolveConflict,
    isSyncableTask, normalizeTombstones,
  });
});
