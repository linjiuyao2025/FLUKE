'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const Dav = require('./caldav-protocol.cjs');

const MAX_ACCOUNTS = 12;
const MAX_RESOURCES = 500;
const MAX_ERROR_LENGTH = 300;
const MAX_BODY_BYTES = 2 * 1024 * 1024;
const REFRESH_INTERVAL_MS = 60 * 60 * 1000;
const NO_CHANGE = Symbol('no-change');

function timestamp(value) {
  return new Date(value).toISOString();
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function origin(url) {
  const parsed = new URL(url);
  return parsed.protocol.toLowerCase() + '//' + parsed.host.toLowerCase();
}

function publicAccount(entry, syncing = false) {
  return {
    id: entry.id,
    name: entry.name,
    host: entry.host,
    components: entry.components,
    lastAttemptAt: entry.lastAttemptAt,
    lastSuccessAt: entry.lastSuccessAt,
    lastError: entry.lastError,
    resourceCount: entry.resources.length,
    syncing: Boolean(syncing),
  };
}

function escapeXml(value) {
  return String(value).replace(/&/gu, '&amp;').replace(/</gu, '&lt;')
    .replace(/>/gu, '&gt;').replace(/"/gu, '&quot;').replace(/'/gu, '&apos;');
}

class CalDavService {
  constructor(options = {}) {
    if (typeof options.encrypt !== 'function' || typeof options.decrypt !== 'function') {
      throw new TypeError('CalDAV credential encryption is required.');
    }
    if (typeof options.combineIcs !== 'function') throw new TypeError('An iCalendar combiner is required.');
    if (typeof options.todoResourceUids !== 'function' || typeof options.updateVtodoCompletion !== 'function') {
      throw new TypeError('CalDAV VTODO identity and completion handlers are required.');
    }
    if (typeof options.storagePath !== 'string' || !options.storagePath) throw new TypeError('A CalDAV storage path is required.');
    this.storagePath = options.storagePath;
    this.encrypt = options.encrypt;
    this.decrypt = options.decrypt;
    this.combineIcs = options.combineIcs;
    this.todoResourceUids = options.todoResourceUids;
    this.updateVtodoCompletion = options.updateVtodoCompletion;
    this.fetchImpl = options.fetchImpl || globalThis.fetch;
    if (typeof this.fetchImpl !== 'function') throw new TypeError('A fetch implementation is required.');
    this.now = options.now || (() => new Date());
    this.timeoutMs = Math.max(1000, Math.min(60_000, Number(options.timeoutMs) || 15_000));
    this.maxBodyBytes = Math.max(1024, Math.min(MAX_BODY_BYTES, Number(options.maxBodyBytes) || MAX_BODY_BYTES));
    this.accounts = new Map();
    this.inFlight = new Map();
    this.pendingCommits = new Map();
    this.writeChain = Promise.resolve();
    this.ready = false;
  }

  async load() {
    let raw;
    try { raw = await fs.readFile(this.storagePath, 'utf8'); }
    catch (error) {
      if (error && error.code === 'ENOENT') { this.ready = true; return []; }
      throw error;
    }
    let payload;
    try { payload = JSON.parse(raw); }
    catch { throw new Dav.CalDavError('CalDAV 账户数据已损坏，暂未覆盖原文件。'); }
    if (!payload || payload.format !== 1 || !Array.isArray(payload.accounts) || payload.accounts.length > MAX_ACCOUNTS) {
      throw new Dav.CalDavError('CalDAV 账户数据格式无效，暂未覆盖原文件。');
    }
    const loaded = new Map();
    for (const entry of payload.accounts) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Dav.CalDavError('CalDAV 账户字段无效。');
      const account = this.#validateStoredAccount(entry);
      if (loaded.has(account.id)) throw new Dav.CalDavError('CalDAV 账户标识重复。');
      loaded.set(account.id, account);
    }
    this.accounts = loaded;
    this.ready = true;
    return this.list();
  }

  list() {
    this.#assertReady();
    return [...this.accounts.values()].map((entry) => publicAccount(entry, this.inFlight.has(entry.id)));
  }

  async add(input) {
    this.#assertReady();
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Dav.CalDavError('CalDAV 账户信息无效。');
    const normalized = Dav.normalizeUrl(input.url);
    const credentials = Dav.validateCredentials(input.username || '', input.password || '');
    const requestedName = typeof input.name === 'string' ? input.name.replace(/[\u0000-\u001f\u007f]/gu, '').trim() : '';
    if (requestedName.length > 80) throw new Dav.CalDavError('CalDAV 名称不能超过 80 个字符。');
    const probe = await this.#probe(normalized.url, credentials.username, credentials.password);
    const target = new URL(normalized.url);
    const collection = probe.find((item) => {
      const candidate = new URL(item.href);
      return candidate.pathname.replace(/\/+$/u, '') === target.pathname.replace(/\/+$/u, '');
    });
    if (!collection) throw new Dav.CalDavError('此地址没有返回对应的日历集；请填写具体日历集地址。');
    const endpoint = Dav.normalizeUrl(collection.href).url;
    const encryptedSecret = await this.encrypt(JSON.stringify({
      url: endpoint, username: credentials.username, password: credentials.password,
    }));
    if (typeof encryptedSecret !== 'string' || !encryptedSecret || encryptedSecret.length > 16_384) {
      throw new Dav.CalDavError('无法加密保存 CalDAV 登录信息，账户尚未添加。');
    }
    const entry = {
      id: randomUUID(),
      name: requestedName || collection.name || normalized.host,
      host: normalized.host,
      encryptedSecret,
      components: collection.components,
      syncToken: '',
      syncCollectionUnsupported: false,
      resources: [],
      lastAttemptAt: '',
      lastSuccessAt: '',
      lastError: '',
    };
    await this.#mutate(async (accounts) => {
      if (accounts.size >= MAX_ACCOUNTS) throw new Dav.CalDavError('最多只能保存 12 个 CalDAV 日历。');
      for (const existing of accounts.values()) {
        try {
          const current = await this.#readSecret(existing.encryptedSecret);
          if (current.url === endpoint) throw new Dav.CalDavError('这个 CalDAV 日历已经添加。');
        } catch (error) {
          if (error instanceof Dav.CalDavError && error.message === '这个 CalDAV 日历已经添加。') throw error;
        }
      }
      accounts.set(entry.id, entry);
      return publicAccount(entry);
    });
    return publicAccount(entry);
  }

  async remove(id) {
    this.#assertReady();
    const key = String(id || '');
    this.pendingCommits.forEach((item, token) => { if (item.id === key) this.pendingCommits.delete(token); });
    return this.#mutate((accounts) => accounts.has(key) ? (accounts.delete(key), true) : NO_CHANGE);
  }

  async sync(id, options = {}) {
    this.#assertReady();
    const key = String(id || '');
    const account = this.accounts.get(key);
    if (!account) return { kind: 'error', id: key, error: '找不到这个 CalDAV 日历。' };
    if (this.inFlight.has(key)) {
      return { kind: 'busy', id: key, account: publicAccount(account, true) };
    }
    const pending = [...this.pendingCommits.values()].find((item) => item.id === key);
    if (pending) return clone(pending.result);
    const operation = this.#sync(account, Boolean(options.force));
    this.inFlight.set(key, operation);
    try { return await operation; }
    finally { if (this.inFlight.get(key) === operation) this.inFlight.delete(key); }
  }

  async syncDue(force = false, now = this.now()) {
    this.#assertReady();
    const nowValue = new Date(now).getTime();
    const due = [...this.accounts.values()].filter((entry) => {
      if (this.inFlight.has(entry.id) || [...this.pendingCommits.values()].some((item) => item.id === entry.id)) return false;
      const attempted = Date.parse(entry.lastAttemptAt || '');
      return force || !Number.isFinite(attempted) || nowValue - attempted >= REFRESH_INTERVAL_MS;
    });
    return Promise.all(due.map((entry) => this.sync(entry.id)));
  }

  async setTodoCompletion(id, uid, done) {
    this.#assertReady();
    const key = String(id || '');
    const account = this.accounts.get(key);
    if (!account) return { ok: false, error: '找不到这个 CalDAV 日历。' };
    if (typeof uid !== 'string' || !uid || uid.length > 255 || /[\u0000-\u001f\u007f]/u.test(uid)
      || typeof done !== 'boolean') return { ok: false, error: 'CalDAV 待办状态无效。' };
    if (this.inFlight.has(key) || [...this.pendingCommits.values()].some((item) => item.id === key)) {
      return { ok: false, error: 'CalDAV 日历正在同步，请稍后再改完成状态。' };
    }
    const operation = this.#writeTodoCompletion(account, uid, done);
    this.inFlight.set(key, operation);
    try { return await operation; }
    finally { if (this.inFlight.get(key) === operation) this.inFlight.delete(key); }
  }

  async commit(id, token) {
    this.#assertReady();
    const key = String(token || '');
    const pending = this.pendingCommits.get(key);
    if (!pending || pending.id !== String(id || '')) return false;
    const committed = await this.#mutate((accounts) => {
      if (!accounts.has(pending.id) || this.pendingCommits.get(key) !== pending) return NO_CHANGE;
      accounts.set(pending.id, pending.account);
      return true;
    });
    if (!committed) return false;
    this.pendingCommits.delete(key);
    return true;
  }

  async #sync(current, force) {
    const id = current.id;
    await this.#mutate((accounts) => {
      const entry = accounts.get(id);
      if (!entry) return NO_CHANGE;
      entry.lastAttemptAt = this.#timestamp();
      entry.lastError = '';
    });
    let account = this.accounts.get(id);
    if (!account) return { kind: 'removed', id };
    try {
      const secret = await this.#readSecret(account.encryptedSecret);
      const collectionUrl = secret.url;
      let resources = new Map(account.resources.map((item) => {
        const href = Dav.resolveResourceUrl(collectionUrl, item.href);
        return [href, { ...item, href }];
      }));
      let syncToken = account.syncToken;
      let unsupported = account.syncCollectionUnsupported;
      let skippedRecurringTodos = 0;
      let usedFullSnapshot = force || unsupported;

      if (!usedFullSnapshot) {
        try {
          let pageToken = syncToken;
          const changes = new Map();
          let finalToken = syncToken;
          for (let page = 0; page < 50; page++) {
            const response = await this.#request(secret.url, secret.username, secret.password, 'REPORT', Dav.syncCollectionBody(pageToken), '1');
            if ([403, 405, 501].includes(response.status)) {
              const invalidToken = response.status === 403 && response.text.includes('valid-sync-token');
              if (!invalidToken) unsupported = true;
              usedFullSnapshot = true;
              break;
            }
            if (response.status !== 207) throw this.#httpError(response.status);
            const report = Dav.parseSyncCollection(response.text, collectionUrl);
            if (report.tokenRejected) {
              usedFullSnapshot = true;
              break;
            }
            report.changes.forEach((item) => changes.set(item.href, item));
            finalToken = report.syncToken;
            if (!report.truncated) {
              syncToken = finalToken;
              for (const [href, change] of changes) {
                if (change.removed) resources.delete(href);
              }
              const changed = [...changes.values()].filter((item) => !item.removed
                && resources.get(item.href)?.etag !== item.etag).map((item) => item.href);
              if (changed.length) {
                const fetched = await this.#multiget(secret, collectionUrl, changed);
                fetched.resources.forEach((item) => resources.set(item.href, item));
                fetched.removedHrefs.forEach((href) => resources.delete(href));
              }
              break;
            }
            if (page === 49) throw new Dav.CalDavError('CalDAV 分页过多，已停止本次同步。');
            pageToken = report.syncToken;
          }
          if (changes.size > MAX_RESOURCES) throw new Dav.CalDavError('CalDAV 单次变更超过 500 个资源。');
        } catch (error) {
          if (error && error.status === 403 && String(error.message).includes('valid-sync-token')) usedFullSnapshot = true;
          else throw error;
        }
      }

      if (usedFullSnapshot) {
        const response = await this.#request(secret.url, secret.username, secret.password, 'REPORT', Dav.fullQueryBody(), '1');
        if (response.status !== 207) throw this.#httpError(response.status);
        const full = Dav.parseCalendarResources(response.text, collectionUrl);
        if (full.resources.length > MAX_RESOURCES) throw new Dav.CalDavError('CalDAV 日历超过 500 个资源。');
        resources = new Map(full.resources.map((item) => [item.href, item]));
        syncToken = '';
      }

      const combined = this.combineIcs([...resources.values()], account.name);
      skippedRecurringTodos = Number(combined.skippedRecurringTodos) || 0;
      account = this.accounts.get(id);
      if (!account) return { kind: 'removed', id };
      const nextAccount = {
        ...clone(account),
        syncToken,
        syncCollectionUnsupported: unsupported,
        resources: [...resources.values()],
        lastError: '',
        lastSuccessAt: this.#timestamp(),
      };
      const commitToken = randomUUID();
      const result = {
        kind: 'updated',
        id,
        account: publicAccount(nextAccount),
        icsText: combined.icsText,
        eventCount: combined.info.eventCount,
        todoCount: combined.info.todoCount,
        todos: combined.info.todos,
        skippedRecurringTodos,
        commitToken,
      };
      this.pendingCommits.set(commitToken, { id, account: nextAccount, result });
      return result;
    } catch (error) {
      const message = String(error && error.message || 'CalDAV 同步失败。').slice(0, MAX_ERROR_LENGTH);
      await this.#mutate((accounts) => {
        const entry = accounts.get(id);
        if (entry) entry.lastError = message;
      }).catch(() => {});
      return { kind: 'error', id, error: message, account: publicAccount(this.accounts.get(id) || current) };
    }
  }

  async #probe(url, username, password) {
    const response = await this.#request(url, username, password, 'PROPFIND', Dav.propfindBody(), '0');
    if (response.status !== 207 && response.status !== 200) throw this.#httpError(response.status);
    return Dav.parsePropfind(response.text, url);
  }

  async #multiget(secret, collectionUrl, hrefs) {
    const response = await this.#request(secret.url, secret.username, secret.password, 'REPORT', Dav.multigetBody(hrefs), '1');
    if (response.status !== 207) throw this.#httpError(response.status);
    return Dav.parseCalendarResources(response.text, collectionUrl, hrefs);
  }

  async #writeTodoCompletion(current, uid, done) {
    const id = current.id;
    try {
      const secret = await this.#readSecret(current.encryptedSecret);
      const matches = [];
      for (const resource of current.resources) {
        const uids = this.todoResourceUids(resource.calendarData);
        if (uids.includes(uid)) matches.push({ resource, uids });
      }
      if (matches.length !== 1 || matches[0].uids.length !== 1) {
        throw new Dav.CalDavError('CalDAV 待办没有唯一对应的日历资源，未执行回写。');
      }
      const { resource, uids } = matches[0];
      if (uids[0] !== uid) throw new Dav.CalDavError('CalDAV 待办 UID 与资源不匹配，未执行回写。');
      if (!Dav.isStrongEtag(resource.etag)) {
        throw new Dav.CalDavError('服务器没有为此待办提供强 ETag，已保留原完成状态。');
      }
      const calendarData = this.updateVtodoCompletion(resource.calendarData, uid, done, this.now());
      const href = Dav.resolveResourceUrl(secret.url, resource.href);
      const response = await this.#request(
        href, secret.username, secret.password, 'PUT', calendarData, undefined,
        { 'Content-Type': 'text/calendar; charset=utf-8', 'If-Match': resource.etag },
      );
      if (![200, 201, 204].includes(response.status)) throw this.#httpError(response.status);
      const etag = response.etag && response.etag.length <= 1024
        && !/[\u0000-\u001f\u007f]/u.test(response.etag) ? response.etag : '';
      await this.#mutate((accounts) => {
        const entry = accounts.get(id);
        if (!entry) return NO_CHANGE;
        const stored = entry.resources.find((item) => item.href === resource.href);
        if (!stored || stored.etag !== resource.etag) throw new Dav.CalDavError('CalDAV 本机资源已变化，请先同步后重试。');
        stored.calendarData = calendarData;
        stored.etag = etag;
        entry.lastError = '';
        entry.lastSuccessAt = this.#timestamp();
        return true;
      });
      return { ok: true, id, uid, done, etag };
    } catch (error) {
      const message = String(error && error.message || 'CalDAV 完成状态回写失败。').slice(0, MAX_ERROR_LENGTH);
      await this.#mutate((accounts) => {
        const entry = accounts.get(id);
        if (!entry) return NO_CHANGE;
        entry.lastError = message;
        return true;
      }).catch(() => {});
      return { ok: false, id, uid, error: message };
    }
  }

  async #request(url, username, password, method, body, depth, extraHeaders = {}) {
    const normalized = Dav.normalizeUrl(url).url;
    const headers = {
      Accept: 'application/xml, text/xml',
      'Content-Type': 'application/xml; charset=utf-8',
      ...extraHeaders,
    };
    if (depth !== undefined && depth !== null) headers.Depth = String(depth);
    const authorization = Dav.authorizationHeader(username, password);
    if (authorization) headers.Authorization = authorization;
    let target = normalized;
    for (let redirects = 0; redirects <= 3; redirects++) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
      let response;
      try {
        response = await this.fetchImpl(target, {
          method, headers, body, redirect: 'manual', signal: controller.signal,
        });
        if ([301, 302, 303, 307, 308].includes(response.status)) {
          const location = response.headers.get('location');
          if (response.body) await response.body.cancel().catch(() => {});
          if (!location || redirects === 3) throw new Dav.CalDavError('CalDAV 重定向过多或缺少地址。');
          const redirected = new URL(location, target);
          if (origin(redirected.href) !== origin(normalized) || redirected.protocol !== new URL(normalized).protocol
            || redirected.username || redirected.password || redirected.search || redirected.hash) {
            throw new Dav.CalDavError('CalDAV 重定向跳到其他来源，已阻止转发登录信息。');
          }
          target = redirected.href;
          continue;
        }
        const bytes = await this.#readBody(response);
        return { status: response.status, text: bytes.toString('utf8'), etag: response.headers.get('etag') || '' };
      } catch (error) {
        if (error instanceof Dav.CalDavError) throw error;
        throw new Dav.CalDavError(error && error.name === 'AbortError' ? 'CalDAV 连接超时。' : '无法连接 CalDAV 服务器。');
      } finally {
        clearTimeout(timeout);
      }
    }
    throw new Dav.CalDavError('CalDAV 重定向过多。');
  }

  async #readBody(response) {
    if (!response.body || typeof response.body.getReader !== 'function') {
      const bytes = Buffer.from(await response.arrayBuffer());
      if (bytes.length > this.maxBodyBytes) throw new Dav.CalDavError('CalDAV 响应超过 2 MB。');
      return bytes;
    }
    const reader = response.body.getReader();
    const chunks = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > this.maxBodyBytes) {
          await reader.cancel().catch(() => {});
          throw new Dav.CalDavError('CalDAV 响应超过 2 MB。');
        }
        chunks.push(Buffer.from(value));
      }
    } finally {
      reader.releaseLock();
    }
    return Buffer.concat(chunks, total);
  }

  #httpError(status) {
    const messages = {
      401: 'CalDAV 账号或密码错误。',
      403: 'CalDAV 服务器拒绝访问。',
      404: '找不到 CalDAV 日历集。',
      412: 'CalDAV 数据已在服务器上变化，请先同步。',
      429: 'CalDAV 服务器请求过于频繁，请稍后重试。',
    };
    const error = new Dav.CalDavError(messages[status] || ('CalDAV 服务器返回 HTTP ' + status + '。'));
    error.status = status;
    return error;
  }

  async #readSecret(encryptedSecret) {
    let value;
    try { value = await this.decrypt(encryptedSecret); }
    catch { throw new Dav.CalDavError('CalDAV 登录信息无法解密，请移除并重新添加日历。'); }
    if (typeof value !== 'string' || Buffer.byteLength(value, 'utf8') > 3072) {
      throw new Dav.CalDavError('CalDAV 登录信息无效。');
    }
    let secret;
    try { secret = JSON.parse(value); }
    catch { throw new Dav.CalDavError('CalDAV 登录信息结构无效。'); }
    const normalized = Dav.normalizeUrl(secret.url);
    const credentials = Dav.validateCredentials(secret.username, secret.password);
    return { url: normalized.url, username: credentials.username, password: credentials.password };
  }

  #validateStoredAccount(entry) {
    const id = typeof entry.id === 'string' ? entry.id : '';
    const name = typeof entry.name === 'string' ? entry.name.trim() : '';
    const host = typeof entry.host === 'string' ? entry.host : '';
    const encryptedSecret = typeof entry.encryptedSecret === 'string' ? entry.encryptedSecret : '';
    const syncToken = typeof entry.syncToken === 'string' ? entry.syncToken : '';
    const resources = Array.isArray(entry.resources) ? entry.resources : null;
    const components = Array.isArray(entry.components) ? [...new Set(entry.components.filter((item) => ['VEVENT', 'VTODO'].includes(item)))] : null;
    const lastError = typeof entry.lastError === 'string' ? entry.lastError : '';
    if (!id || id.length > 80 || !name || name.length > 80 || !host || host.length > 255
      || !encryptedSecret || encryptedSecret.length > 16_384
      || !components || components.length === 0 || !resources || resources.length > MAX_RESOURCES
      || syncToken.length > 4096 || /[\u0000-\u001f\u007f]/u.test(syncToken)
      || lastError.length > MAX_ERROR_LENGTH) throw new Dav.CalDavError('已保存的 CalDAV 账户字段无效。');
    if (!Array.isArray(entry.resources)) throw new Dav.CalDavError('已保存的 CalDAV 资源格式无效。');
    let totalBytes = 0;
    const seen = new Set();
    const checkedResources = resources.map((resource) => {
      if (!resource || typeof resource !== 'object' || typeof resource.href !== 'string'
        || typeof resource.etag !== 'string' || typeof resource.calendarData !== 'string') {
        throw new Dav.CalDavError('已保存的 CalDAV 资源格式无效。');
      }
      let parsedHref;
      try { parsedHref = new URL(resource.href); } catch { throw new Dav.CalDavError('已保存的 CalDAV 资源地址无效。'); }
      if (!['https:', 'http:'].includes(parsedHref.protocol) || parsedHref.username || parsedHref.password
        || parsedHref.search || parsedHref.hash) {
        throw new Dav.CalDavError('已保存的 CalDAV 资源地址无效。');
      }
      const href = parsedHref.href;
      const bytes = Buffer.byteLength(resource.calendarData, 'utf8');
      totalBytes += bytes;
      if (seen.has(href) || resource.etag.length > 1024 || /[\u0000-\u001f\u007f]/u.test(resource.etag)
        || bytes > MAX_BODY_BYTES || totalBytes > 10 * MAX_BODY_BYTES) throw new Dav.CalDavError('已保存的 CalDAV 资源超出限制。');
      seen.add(href);
      return { href, etag: resource.etag, calendarData: resource.calendarData };
    });
    return {
      id, name, host, encryptedSecret, components, syncToken,
      syncCollectionUnsupported: Boolean(entry.syncCollectionUnsupported),
      resources: checkedResources,
      lastAttemptAt: typeof entry.lastAttemptAt === 'string' ? entry.lastAttemptAt : '',
      lastSuccessAt: typeof entry.lastSuccessAt === 'string' ? entry.lastSuccessAt : '',
      lastError,
    };
  }

  async #mutate(mutator) {
    let result;
    const operation = this.writeChain.then(async () => {
      const candidate = new Map([...this.accounts].map(([id, entry]) => [id, clone(entry)]));
      result = await mutator(candidate);
      if (result === NO_CHANGE) return;
      if (candidate.size > MAX_ACCOUNTS) throw new Dav.CalDavError('最多只能保存 12 个 CalDAV 日历。');
      const payload = JSON.stringify({ format: 1, accounts: [...candidate.values()] });
      await fs.mkdir(path.dirname(this.storagePath), { recursive: true });
      const temporary = this.storagePath + '.' + randomUUID() + '.tmp';
      try {
        await fs.writeFile(temporary, payload, { encoding: 'utf8', flag: 'wx' });
        await fs.rename(temporary, this.storagePath);
      } catch (error) {
        await fs.rm(temporary, { force: true }).catch(() => {});
        throw error;
      }
      this.accounts = candidate;
    });
    this.writeChain = operation.catch(() => {});
    await operation;
    return result;
  }

  #timestamp() {
    return timestamp(this.now());
  }

  #assertReady() {
    if (!this.ready) throw new Dav.CalDavError('CalDAV 服务尚未准备好。');
  }
}

module.exports = { CalDavService, MAX_ACCOUNTS, MAX_RESOURCES };
