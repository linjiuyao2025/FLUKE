'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');

const MAX_REMINDERS = 2000;
const MAX_FIRED = 500;
const MAX_TIMEOUT = 0x7fffffff;

function localDate(timestamp) {
  const date = new Date(timestamp);
  const year = String(date.getFullYear()).padStart(4, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function normalizeReminder(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  if (typeof value.id !== 'string' || !value.id.trim()) return null;
  if (typeof value.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value.date)) return null;
  if (typeof value.time !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value.time)) return null;

  const [year, month, day] = value.date.split('-').map(Number);
  const calendarDate = new Date(year, month - 1, day);
  if (calendarDate.getFullYear() !== year || calendarDate.getMonth() !== month - 1 || calendarDate.getDate() !== day) return null;

  const [hour, minute] = value.time.split(':').map(Number);
  const fireAt = new Date(year, month - 1, day, hour, minute, 0, 0).getTime();
  if (!Number.isFinite(fireAt)) return null;

  return {
    id: value.id.trim().slice(0, 120),
    date: value.date,
    time: value.time,
    title: typeof value.title === 'string' ? value.title.trim().slice(0, 160) || '日程提醒' : '日程提醒',
    body: typeof value.body === 'string' ? value.body.trim().slice(0, 300) : '',
    fireAt,
  };
}

function reminderKey(reminder) {
  return JSON.stringify([reminder.id, reminder.date, reminder.time]);
}

class ReminderService {
  constructor({ storagePath, notify, onFired = () => {}, onPendingChanged = () => {}, onError = () => {}, now = Date.now, setTimer = setTimeout, clearTimer = clearTimeout }) {
    if (typeof storagePath !== 'string' || !storagePath) throw new TypeError('storagePath is required');
    if (typeof notify !== 'function') throw new TypeError('notify must be a function');
    this.storagePath = storagePath;
    this.notify = notify;
    this.onFired = onFired;
    this.onPendingChanged = onPendingChanged;
    this.onError = onError;
    this.now = now;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.pending = new Map();
    this.timers = new Map();
    this.fired = new Map();
    this.persistChain = Promise.resolve();
  }

  get pendingCount() {
    return this.pending.size;
  }

  async load() {
    let needsSave = false;
    try {
      const payload = JSON.parse(await fs.readFile(this.storagePath, 'utf8'));
      if (payload?.version !== 1 || !Array.isArray(payload.pending) || !Array.isArray(payload.fired)) throw new Error('Invalid reminder data');
      const today = localDate(this.now());
      for (const item of payload.fired.slice(-MAX_FIRED)) {
        const reminder = normalizeReminder(item);
        const firedAt = Number(item.firedAt);
        if (!reminder || !Number.isFinite(firedAt) || Math.abs(firedAt) > 8.64e15 || this.now() - firedAt > 7 * 24 * 60 * 60 * 1000) {
          needsSave = true;
          continue;
        }
        this.fired.set(reminderKey(reminder), { ...reminder, firedAt });
      }
      for (const item of payload.pending.slice(-MAX_REMINDERS)) {
        const reminder = normalizeReminder(item);
        if (!reminder || reminder.date < today || this.fired.has(reminderKey(reminder))) {
          needsSave = true;
          continue;
        }
        this.pending.set(reminderKey(reminder), reminder);
      }
      if (payload.pending.length > MAX_REMINDERS || payload.fired.length > MAX_FIRED) needsSave = true;
    } catch (error) {
      if (error?.code !== 'ENOENT') {
        needsSave = true;
        this.onError(error);
      }
    }

    for (const [key, reminder] of this.pending) this.#schedule(key, reminder);
    if (needsSave) await this.#persist();
    this.onPendingChanged(this.pending.size);
  }

  async sync(values) {
    const source = Array.isArray(values) ? values.slice(0, MAX_REMINDERS) : [];
    const today = localDate(this.now());
    const next = new Map();
    const fired = [];
    for (const value of source) {
      const reminder = normalizeReminder(value);
      if (!reminder || reminder.date < today) continue;
      const key = reminderKey(reminder);
      if (this.fired.has(key)) {
        fired.push(this.#firedPayload(this.fired.get(key)));
        continue;
      }
      next.set(key, reminder);
    }

    let changed = false;
    for (const key of this.pending.keys()) {
      if (next.has(key)) continue;
      this.#cancel(key);
      this.pending.delete(key);
      changed = true;
    }
    for (const [key, reminder] of next) {
      const existing = this.pending.get(key);
      if (existing) {
        if (existing.title !== reminder.title || existing.body !== reminder.body) {
          this.pending.set(key, reminder);
          changed = true;
        }
        continue;
      }
      this.pending.set(key, reminder);
      this.#schedule(key, reminder);
      changed = true;
    }

    if (changed) await this.#persist();
    if (changed) this.onPendingChanged(this.pending.size);
    return { fired, pendingCount: this.pending.size };
  }

  async fire(key) {
    const reminder = this.pending.get(key);
    if (!reminder) return false;
    this.#cancel(key);
    this.pending.delete(key);
    const firedAt = this.now();
    const firedReminder = { ...reminder, firedAt };
    this.fired.set(key, firedReminder);
    this.#trimFired();
    await this.#persist();

    try {
      this.notify(reminder);
    } catch (error) {
      this.onError(error);
    }
    try {
      this.onFired(this.#firedPayload(firedReminder));
    } catch (error) {
      this.onError(error);
    }
    this.onPendingChanged(this.pending.size);
    return true;
  }

  #firedPayload(reminder) {
    return {
      id: reminder.id,
      date: reminder.date,
      time: reminder.time,
      firedAt: new Date(reminder.firedAt || this.now()).toISOString(),
    };
  }

  #schedule(key, reminder) {
    this.#cancel(key);
    const delay = Math.max(0, reminder.fireAt - this.now());
    const timer = this.setTimer(() => {
      this.timers.delete(key);
      const current = this.pending.get(key);
      if (!current) return;
      if (current.fireAt > this.now()) {
        this.#schedule(key, current);
        return;
      }
      void this.fire(key).catch(this.onError);
    }, Math.min(delay, MAX_TIMEOUT));
    if (timer && typeof timer.unref === 'function') timer.unref();
    this.timers.set(key, timer);
  }

  #cancel(key) {
    const timer = this.timers.get(key);
    if (timer !== undefined) this.clearTimer(timer);
    this.timers.delete(key);
  }

  #trimFired() {
    const cutoff = this.now() - 7 * 24 * 60 * 60 * 1000;
    for (const [key, reminder] of this.fired) {
      if (reminder.firedAt < cutoff) this.fired.delete(key);
    }
    while (this.fired.size > MAX_FIRED) this.fired.delete(this.fired.keys().next().value);
  }

  #persist() {
    const operation = this.persistChain.catch(() => {}).then(async () => {
      const directory = path.dirname(this.storagePath);
      await fs.mkdir(directory, { recursive: true });
      const payload = JSON.stringify({
        version: 1,
        pending: [...this.pending.values()].map(({ id, date, time, title, body }) => ({ id, date, time, title, body })),
        fired: [...this.fired.values()].map(({ id, date, time, title, body, firedAt }) => ({ id, date, time, title, body, firedAt })),
      });
      const temporaryPath = `${this.storagePath}.${process.pid}.tmp`;
      await fs.writeFile(temporaryPath, payload, 'utf8');
      await fs.rename(temporaryPath, this.storagePath);
    });
    this.persistChain = operation;
    return operation.catch((error) => {
      this.onError(error);
      throw error;
    });
  }
}

module.exports = { ReminderService, localDate, normalizeReminder, reminderKey };
