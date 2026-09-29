'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

const MAX_SUBSCRIPTIONS = 12;
const MAX_URL_BYTES = 2048;
const MAX_FEED_BYTES = 1024 * 1024;
const MAX_REDIRECTS = 5;
const MAX_ERROR_LENGTH = 300;
const REFRESH_INTERVAL_MS = 60 * 60 * 1000;
const NO_CHANGE = Symbol('no-change');

class CalendarSubscriptionError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CalendarSubscriptionError';
  }
}

function normalizeSubscriptionUrl(value) {
  if (typeof value !== 'string') throw new CalendarSubscriptionError('订阅地址必须是文本。');
  const source = value.trim();
  if (!source || Buffer.byteLength(source, 'utf8') > MAX_URL_BYTES) {
    throw new CalendarSubscriptionError('订阅地址不能为空，且不能超过 2048 字节。');
  }
  if (/[\s\u0000-\u001f\u007f]/u.test(source)) {
    throw new CalendarSubscriptionError('订阅地址不能包含空格或控制字符。');
  }
  if (!/^(?:https?|webcals?):\/\/[^/\\?#]+/iu.test(source)) {
    throw new CalendarSubscriptionError('订阅地址格式无效。');
  }

  let parsed;
  try {
    const httpsSource = source.replace(/^webcals?:/iu, 'https:');
    parsed = new URL(httpsSource);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new CalendarSubscriptionError('订阅地址须使用 HTTP、HTTPS 或 webcal。');
    }
    if (parsed.username || parsed.password) {
      throw new CalendarSubscriptionError('请移除地址中的账号密码，再使用日历订阅。');
    }
    if (!parsed.hostname) throw new CalendarSubscriptionError('订阅地址缺少服务器名称。');
    parsed.hash = '';
  } catch (error) {
    if (error instanceof CalendarSubscriptionError) throw error;
    throw new CalendarSubscriptionError('订阅地址格式无效。');
  }

  const normalized = parsed.href;
  if (Buffer.byteLength(normalized, 'utf8') > MAX_URL_BYTES) {
    throw new CalendarSubscriptionError('订阅地址不能超过 2048 字节。');
  }
  return { url: normalized, host: parsed.hostname.toLowerCase() };
}

function cleanHeader(value, label, maxLength) {
  if (value == null || value === '') return '';
  const text = String(value);
  if (text.length > maxLength || /[\u0000-\u001f\u007f]/u.test(text) || [...text].some((character) => character.codePointAt(0) > 255)) {
    throw new CalendarSubscriptionError(`日历服务器返回了无效的${label}。`);
  }
  return text;
}

function publicSubscription(entry, refreshing = false) {
  return {
    id: entry.id,
    name: entry.name,
    host: entry.host,
    lastAttemptAt: entry.lastAttemptAt,
    lastSuccessAt: entry.lastSuccessAt,
    lastError: entry.lastError,
    eventCount: entry.eventCount,
    refreshing: Boolean(refreshing),
  };
}

function validTimestamp(value) {
  return typeof value === 'string' && (!value || (value.length <= 40 && Number.isFinite(Date.parse(value))));
}

class CalendarSubscriptionService {
  constructor(options = {}) {
    if (typeof options.encrypt !== 'function' || typeof options.decrypt !== 'function') {
      throw new TypeError('Calendar subscription encryption is required.');
    }
    if (typeof options.parseIcs !== 'function') throw new TypeError('An iCalendar parser is required.');
    this.storagePath = options.storagePath;
    if (typeof this.storagePath !== 'string' || !this.storagePath) throw new TypeError('A storage path is required.');
    this.encrypt = options.encrypt;
    this.decrypt = options.decrypt;
    this.parseIcs = options.parseIcs;
    this.fetchImpl = options.fetchImpl || globalThis.fetch;
    if (typeof this.fetchImpl !== 'function') throw new TypeError('A fetch implementation is required.');
    this.now = options.now || (() => new Date());
    this.timeoutMs = Math.max(1000, Math.min(60_000, Number(options.timeoutMs) || 15_000));
    this.maxFeedBytes = Math.max(1024, Math.min(2 * 1024 * 1024, Number(options.maxFeedBytes) || MAX_FEED_BYTES));
    this.entries = new Map();
    this.inFlight = new Map();
    this.pendingCommits = new Map();
    this.writeChain = Promise.resolve();
    this.ready = false;
  }

  async load() {
    let raw;
    try {
      raw = await fs.readFile(this.storagePath, 'utf8');
    } catch (error) {
      if (error && error.code === 'ENOENT') {
        this.ready = true;
        return [];
      }
      throw error;
    }

    let payload;
    try { payload = JSON.parse(raw); } catch { throw new CalendarSubscriptionError('已保存的日历订阅数据损坏，暂未覆盖原文件。'); }
    if (!payload || payload.format !== 1 || !Array.isArray(payload.subscriptions) || payload.subscriptions.length > MAX_SUBSCRIPTIONS) {
      throw new CalendarSubscriptionError('已保存的日历订阅数据格式无效，暂未覆盖原文件。');
    }

    const loaded = new Map();
    for (const entry of payload.subscriptions) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
        throw new CalendarSubscriptionError('已保存的日历订阅数据格式无效，暂未覆盖原文件。');
      }
      const id = typeof entry.id === 'string' ? entry.id : '';
      const name = typeof entry.name === 'string' ? entry.name.trim() : '';
      const host = typeof entry.host === 'string' ? entry.host : '';
      const encryptedUrl = typeof entry.encryptedUrl === 'string' ? entry.encryptedUrl : '';
      const etag = typeof entry.etag === 'string' ? entry.etag : '';
      const lastModified = typeof entry.lastModified === 'string' ? entry.lastModified : '';
      const lastAttemptAt = entry.lastAttemptAt || '';
      const lastSuccessAt = entry.lastSuccessAt || '';
      const lastError = typeof entry.lastError === 'string' ? entry.lastError : '';
      const eventCount = Number(entry.eventCount);
      if (!id || id.length > 80 || loaded.has(id) || !name || name.length > 80 || !host || host.length > 255
        || !encryptedUrl || encryptedUrl.length > 16_384 || etag.length > 1024 || lastModified.length > 128
        || lastError.length > MAX_ERROR_LENGTH || !validTimestamp(lastAttemptAt) || !validTimestamp(lastSuccessAt)
        || !Number.isInteger(eventCount) || eventCount < 0 || eventCount > 500) {
        throw new CalendarSubscriptionError('已保存的日历订阅字段无效，暂未覆盖原文件。');
      }
      cleanHeader(etag, '缓存验证信息', 1024);
      cleanHeader(lastModified, '缓存验证信息', 128);
      loaded.set(id, { id, name, host, encryptedUrl, etag, lastModified, lastAttemptAt, lastSuccessAt, lastError, eventCount });
    }
    this.entries = loaded;
    this.ready = true;
    return this.list();
  }

  list() {
    this.#assertReady();
    return [...this.entries.values()].map((entry) => publicSubscription(entry, this.inFlight.has(entry.id)));
  }

  async add(input) {
    this.#assertReady();
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new CalendarSubscriptionError('订阅信息无效。');
    const normalized = normalizeSubscriptionUrl(input.url);
    const requestedName = typeof input.name === 'string' ? input.name.replace(/[\u0000-\u001f\u007f]/gu, '').trim() : '';
    if (requestedName.length > 80) throw new CalendarSubscriptionError('订阅名称不能超过 80 个字符。');
    const name = requestedName || normalized.host.slice(0, 80);
    const encryptedUrl = await this.encrypt(normalized.url);
    if (typeof encryptedUrl !== 'string' || !encryptedUrl || encryptedUrl.length > 16_384) {
      throw new CalendarSubscriptionError('无法加密保存订阅地址，尚未添加订阅。');
    }
    const entry = {
      id: randomUUID(),
      name: name || normalized.host,
      host: normalized.host,
      encryptedUrl,
      etag: '',
      lastModified: '',
      lastAttemptAt: '',
      lastSuccessAt: '',
      lastError: '',
      eventCount: 0,
    };
    await this.#changeEntries(async (candidate) => {
      if (candidate.size >= MAX_SUBSCRIPTIONS) throw new CalendarSubscriptionError(`最多只能保存 ${MAX_SUBSCRIPTIONS} 个日历订阅。`);
      for (const existing of candidate.values()) {
        try {
          if (normalizeSubscriptionUrl(await this.decrypt(existing.encryptedUrl)).url === normalized.url) {
            throw new CalendarSubscriptionError('这个日历订阅已经添加。');
          }
        } catch (error) {
          if (error instanceof CalendarSubscriptionError && error.message === '这个日历订阅已经添加。') throw error;
          // An unreadable older credential remains visible so the user can remove it.
        }
      }
      candidate.set(entry.id, entry);
      return entry;
    });
    return publicSubscription(entry);
  }

  async remove(id) {
    this.#assertReady();
    const key = String(id || '');
    const removed = await this.#changeEntries((candidate) => {
      if (!candidate.has(key)) return NO_CHANGE;
      candidate.delete(key);
      return true;
    });
    if (!removed) return false;
    this.pendingCommits.forEach((item, token) => { if (item.id === key) this.pendingCommits.delete(token); });
    return true;
  }

  async refresh(id, options = {}) {
    this.#assertReady();
    const key = String(id || '');
    const current = this.entries.get(key);
    if (!current) return { kind: 'error', id: key, error: '找不到这个日历订阅。' };
    if (this.inFlight.has(key)) return { kind: 'busy', id: key, subscription: publicSubscription(current, true) };
    this.pendingCommits.forEach((item, token) => { if (item.id === key) this.pendingCommits.delete(token); });
    const operation = this.#refresh(current, Boolean(options && options.force));
    this.inFlight.set(key, operation);
    try { return await operation; }
    finally { if (this.inFlight.get(key) === operation) this.inFlight.delete(key); }
  }

  async refreshAll() {
    this.#assertReady();
    return Promise.all([...this.entries.keys()].map((id) => this.refresh(id)));
  }

  async refreshDue(now = this.now()) {
    this.#assertReady();
    const nowTime = new Date(now).getTime();
    const due = [...this.entries.values()].filter((entry) => {
      if (this.inFlight.has(entry.id)) return false;
      const attempted = Date.parse(entry.lastAttemptAt || '');
      return !Number.isFinite(attempted) || nowTime - attempted >= REFRESH_INTERVAL_MS;
    });
    return Promise.all(due.map((entry) => this.refresh(entry.id)));
  }

  async commit(id, token) {
    this.#assertReady();
    const key = String(token || ''), candidateUpdate = this.pendingCommits.get(key);
    if (!candidateUpdate || candidateUpdate.id !== String(id || '')) return false;
    const result = await this.#changeEntries((candidate) => {
      if (!candidate.has(candidateUpdate.id) || this.pendingCommits.get(key) !== candidateUpdate) return NO_CHANGE;
      candidate.set(candidateUpdate.id, candidateUpdate.entry);
      return true;
    });
    if (!result) return false;
    this.pendingCommits.delete(key);
    return true;
  }

  async #refresh(current, force = false) {
    const attemptedAt = this.#timestamp();
    const attempted = await this.#updateEntry(current.id, (latest) => ({ ...latest, lastAttemptAt: attemptedAt }));
    if (!attempted) return { kind: 'removed', id: current.id };

    let requestContext = null;
    try {
      const url = await this.decrypt(current.encryptedUrl);
      const normalized = normalizeSubscriptionUrl(url);
      requestContext = await this.#request(normalized.url, current, force);
      const response = requestContext.response;
      if (!this.entries.has(current.id)) return { kind: 'removed', id: current.id };
      const etag = cleanHeader(response.headers.get('etag'), '缓存验证信息', 1024) || current.etag;
      const lastModified = cleanHeader(response.headers.get('last-modified'), '缓存验证信息', 128) || current.lastModified;
      if (response.status === 304) {
        if (force || (!attempted.etag && !attempted.lastModified)) {
          return await this.#recordError(attempted, '日历服务器返回了没有本机缓存可匹配的更新结果；旧日程保持不变。');
        }
        const latest = this.entries.get(current.id);
        if (!latest) return { kind: 'removed', id: current.id };
        const updated = { ...latest, etag, lastModified, lastSuccessAt: this.#timestamp(), lastError: '' };
        return this.#pendingResult(current.id, updated, { kind: 'not-modified' });
      }
      if (response.status !== 200) {
        return await this.#recordError(attempted, `日历服务器返回 HTTP ${response.status}，已保留上次成功同步的日程。`);
      }

      const bytes = await this.#readBody(response);
      let text;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
      catch { return await this.#recordError(attempted, '订阅内容不是有效的 UTF-8 iCalendar 文件，已保留旧日程。'); }
      let parsed;
      try { parsed = this.parseIcs(text, current.name, { allowEmpty: true }); }
      catch (error) {
        const detail = error instanceof Error ? error.message : '';
        return await this.#recordError(attempted, detail ? `${detail} 已保留旧日程。` : '订阅内容无效，已保留旧日程。');
      }
      if (parsed.todoCount > 0 && parsed.eventCount === 0) {
        return await this.#recordError(attempted, '此订阅只包含待办任务；请使用日历文件导入或 CalDAV 账户。旧日程已保留。');
      }
      if (!this.entries.has(current.id)) return { kind: 'removed', id: current.id };
      const latest = this.entries.get(current.id);
      if (!latest) return { kind: 'removed', id: current.id };
      const updated = {
        ...latest,
        etag,
        lastModified,
        lastSuccessAt: this.#timestamp(),
        lastError: '',
        eventCount: Math.max(0, Math.min(500, Math.floor(Number(parsed.eventCount) || 0))),
      };
      return this.#pendingResult(current.id, updated, { kind: 'updated', icsText: text, eventCount: updated.eventCount });
    } catch (error) {
      if (error instanceof CalendarSubscriptionError) return await this.#recordError(attempted, error.message);
      if (requestContext?.controller.signal.aborted) {
        return await this.#recordError(attempted, '连接日历服务器超时，已保留旧日程。');
      }
      return await this.#recordError(attempted, '无法连接日历服务器，已保留上次成功同步的日程。');
    } finally {
      if (requestContext) clearTimeout(requestContext.timeout);
    }
  }

  async #request(initialUrl, entry, force = false) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    let keepTimeout = false;
    let url = initialUrl;
    let originalOrigin = new URL(initialUrl).origin;
    let headers = { 'User-Agent': 'FLUKE Calendar/1.0', Accept: 'text/calendar, text/plain;q=0.9, */*;q=0.1' };
    if (!force && entry.etag) headers['If-None-Match'] = entry.etag;
    if (!force && entry.lastModified) headers['If-Modified-Since'] = entry.lastModified;
    try {
      for (let redirects = 0; ; redirects += 1) {
        const response = await this.fetchImpl(url, { method: 'GET', headers, redirect: 'manual', signal: controller.signal });
        if (![301, 302, 303, 307, 308].includes(response.status)) {
          keepTimeout = true;
          return { response, controller, timeout };
        }
        if (redirects >= MAX_REDIRECTS) throw new CalendarSubscriptionError('日历服务器重定向次数过多，已保留旧日程。');
        const location = response.headers.get('location');
        if (!location) throw new CalendarSubscriptionError('日历服务器重定向地址无效，已保留旧日程。');
        const next = normalizeSubscriptionUrl(new URL(location, url).href).url;
        const currentUrl = new URL(url);
        const nextUrl = new URL(next);
        if (currentUrl.protocol === 'https:' && nextUrl.protocol !== 'https:') {
          throw new CalendarSubscriptionError('日历服务器试图从 HTTPS 降级连接，已保留旧日程。');
        }
        if (nextUrl.origin !== originalOrigin) {
          headers = { 'User-Agent': 'FLUKE Calendar/1.0', Accept: 'text/calendar, text/plain;q=0.9, */*;q=0.1' };
          originalOrigin = nextUrl.origin;
        }
        url = next;
      }
    } catch (error) {
      if (error instanceof CalendarSubscriptionError) throw error;
      if (controller.signal.aborted) throw new CalendarSubscriptionError('连接日历服务器超时，已保留旧日程。');
      throw error;
    } finally {
      if (!keepTimeout) clearTimeout(timeout);
    }
  }

  async #readBody(response) {
    const chunks = [];
    let total = 0;
    if (response.body && typeof response.body[Symbol.asyncIterator] === 'function') {
      for await (const part of response.body) {
        const chunk = Buffer.from(part);
        total += chunk.byteLength;
        if (total > this.maxFeedBytes) throw new CalendarSubscriptionError('订阅内容超过 1 MB，已保留上次成功同步的日程。');
        chunks.push(chunk);
      }
    } else {
      const chunk = Buffer.from(await response.arrayBuffer());
      if (chunk.byteLength > this.maxFeedBytes) throw new CalendarSubscriptionError('订阅内容超过 1 MB，已保留上次成功同步的日程。');
      chunks.push(chunk);
    }
    return Buffer.concat(chunks, total);
  }

  async #recordError(entry, message) {
    if (!this.entries.has(entry.id)) return { kind: 'removed', id: entry.id };
    const safeMessage = String(message || '日历订阅刷新失败，已保留上次成功同步的日程。').slice(0, MAX_ERROR_LENGTH);
    const updated = await this.#updateEntry(entry.id, (latest) => ({ ...latest, lastError: safeMessage }));
    if (!updated) return { kind: 'removed', id: entry.id };
    return { kind: 'error', id: entry.id, error: safeMessage, subscription: publicSubscription(updated) };
  }

  #pendingResult(id, entry, fields) {
    const commitToken = randomUUID();
    this.pendingCommits.set(commitToken, { id, entry });
    return { ...fields, id, name: entry.name, host: entry.host, eventCount: entry.eventCount, lastAttemptAt: entry.lastAttemptAt, lastSuccessAt: entry.lastSuccessAt, lastError: entry.lastError, commitToken };
  }

  #timestamp() {
    const value = this.now();
    return (value instanceof Date ? value : new Date(value)).toISOString();
  }

  #assertReady() {
    if (!this.ready) throw new CalendarSubscriptionError('日历订阅服务尚未就绪。');
  }

  #updateEntry(id, updater) {
    return this.#changeEntries((candidate) => {
      const current = candidate.get(id);
      if (!current) return NO_CHANGE;
      const updated = updater(current);
      if (!updated) return NO_CHANGE;
      candidate.set(id, updated);
      return updated;
    });
  }

  #changeEntries(mutator) {
    const operation = this.writeChain.catch(() => {}).then(async () => {
      const candidate = new Map(this.entries);
      const result = await mutator(candidate);
      if (result === NO_CHANGE) return null;
      await this.#persist(candidate);
      this.entries = candidate;
      return result;
    });
    this.writeChain = operation.catch(() => {});
    return operation;
  }

  async #persist(entries) {
    const directory = path.dirname(this.storagePath);
    await fs.mkdir(directory, { recursive: true });
    const payload = JSON.stringify({ format: 1, subscriptions: [...entries.values()] });
    const temporaryPath = `${this.storagePath}.${process.pid}.${randomUUID()}.tmp`;
    await fs.writeFile(temporaryPath, payload, { encoding: 'utf8', mode: 0o600 });
    try { await fs.rename(temporaryPath, this.storagePath); }
    catch (error) {
      await fs.rm(temporaryPath, { force: true }).catch(() => {});
      throw error;
    }
  }
}

module.exports = {
  CalendarSubscriptionError,
  CalendarSubscriptionService,
  MAX_FEED_BYTES,
  MAX_SUBSCRIPTIONS,
  REFRESH_INTERVAL_MS,
  normalizeSubscriptionUrl,
};
