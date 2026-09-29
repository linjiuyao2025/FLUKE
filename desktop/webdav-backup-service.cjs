'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

const FORMAT = 'wanxiang-encrypted-backup';
const VERSION = 1;
const MAX_URL_BYTES = 4096;
const MAX_BACKUP_BYTES = 70 * 1024 * 1024;
const MAX_TIMEOUT_MS = 60_000;
const MAX_ERROR_LENGTH = 240;

class WebDavBackupError extends Error {
  constructor(message) {
    super(message);
    this.name = 'WebDavBackupError';
  }
}

function normalizeWebDavBackupUrl(value, options = {}) {
  if (typeof value !== 'string') throw new WebDavBackupError('WebDAV 文件地址必须是文本。');
  const source = value.trim();
  if (!source || Buffer.byteLength(source, 'utf8') > MAX_URL_BYTES || /[\s\u0000-\u001f\u007f]/u.test(source)) {
    throw new WebDavBackupError('WebDAV 文件地址不能为空、不能含空白字符，且不能超过 4096 字节。');
  }
  let url;
  try { url = new URL(source); }
  catch { throw new WebDavBackupError('WebDAV 文件地址无效。'); }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname.toLowerCase());
  if (url.protocol !== 'https:' && !(options.allowLoopbackHttp && loopback && url.protocol === 'http:')) {
    throw new WebDavBackupError('WebDAV 远程地址必须使用 HTTPS。');
  }
  if (!url.hostname || url.username || url.password || url.hash) {
    throw new WebDavBackupError('请在账号栏填写登录信息，地址中不要包含账号、密码或片段。');
  }
  if (url.pathname === '/' || url.pathname.endsWith('/')) {
    throw new WebDavBackupError('请填写 WebDAV 上具体的备份文件路径，例如 wanxiang.wxbackup。');
  }
  if (!url.pathname.toLowerCase().endsWith('.wxbackup')) throw new WebDavBackupError('远端文件名须以 .wxbackup 结尾。');
  if (Buffer.byteLength(url.href, 'utf8') > MAX_URL_BYTES) throw new WebDavBackupError('WebDAV 文件地址不能超过 4096 字节。');
  return { url: url.href, host: url.hostname.toLowerCase() };
}

function validateCredentials(input) {
  const username = typeof input.username === 'string' ? input.username : '';
  const password = typeof input.password === 'string' ? input.password : '';
  if (!username || !password || Buffer.byteLength(username, 'utf8') > 512 || Buffer.byteLength(password, 'utf8') > 1024
    || /[\u0000-\u001f\u007f:]/u.test(username) || /[\u0000-\u001f\u007f]/u.test(password)) {
    throw new WebDavBackupError('请输入有效的 WebDAV 用户名和密码；用户名不能包含冒号。');
  }
  return { username, password };
}

function validatePlannerSyncPassphrase(value) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value !== 'string' || Array.from(value).length < 12 || Buffer.byteLength(value, 'utf8') > 256) {
    throw new WebDavBackupError('自动日程同步密码须至少 12 个字符，且不超过 256 字节。');
  }
  return value;
}

function strongEtag(value) {
  return typeof value === 'string' && value.length <= 1024 && /^"[\x21\x23-\x7e]*"$/u.test(value) ? value : '';
}

function publicAccount(entry, busy = false) {
  return entry ? {
    id: entry.id,
    host: entry.host,
    fileName: entry.fileName,
    remoteExists: entry.remoteExists,
    canSafelyReplace: !entry.remoteExists || Boolean(strongEtag(entry.etag)),
    lastCheckedAt: entry.lastCheckedAt,
    lastSuccessAt: entry.lastSuccessAt,
    lastError: entry.lastError,
    plannerSyncEnabled: entry.plannerSyncEnabled === true,
    plannerRemoteExists: entry.plannerRemoteExists === true,
    plannerCanSafelyReplace: !entry.plannerRemoteExists || Boolean(strongEtag(entry.plannerEtag)),
    lastPlannerSyncAt: entry.lastPlannerSyncAt || '',
    lastPlannerError: entry.lastPlannerError || '',
    busy: Boolean(busy),
  } : null;
}

class WebDavBackupService {
  constructor(options = {}) {
    if (typeof options.encrypt !== 'function' || typeof options.decrypt !== 'function') {
      throw new TypeError('WebDAV credentials must be encrypted.');
    }
    if (typeof options.storagePath !== 'string' || !options.storagePath) throw new TypeError('A WebDAV backup storage path is required.');
    this.storagePath = options.storagePath;
    this.encrypt = options.encrypt;
    this.decrypt = options.decrypt;
    this.fetchImpl = options.fetchImpl || globalThis.fetch;
    if (typeof this.fetchImpl !== 'function') throw new TypeError('A fetch implementation is required.');
    this.now = options.now || (() => new Date());
    this.timeoutMs = Math.max(1000, Math.min(MAX_TIMEOUT_MS, Number(options.timeoutMs) || 15_000));
    this.maxBackupBytes = Math.max(1024, Math.min(MAX_BACKUP_BYTES, Number(options.maxBackupBytes) || MAX_BACKUP_BYTES));
    this.allowLoopbackHttp = Boolean(options.allowLoopbackHttp);
    this.account = null;
    this.busy = false;
    this.writeChain = Promise.resolve();
    this.ready = false;
  }

  async load() {
    let raw;
    try { raw = await fs.readFile(this.storagePath, 'utf8'); }
    catch (error) {
      if (error && error.code === 'ENOENT') { this.ready = true; return null; }
      throw error;
    }
    let payload;
    try { payload = JSON.parse(raw); }
    catch { throw new WebDavBackupError('WebDAV 备份设置已损坏，暂未覆盖原文件。'); }
    if (!payload || payload.format !== 1 || (payload.account !== null && (!payload.account || typeof payload.account !== 'object' || Array.isArray(payload.account)))) {
      throw new WebDavBackupError('WebDAV 备份设置格式无效，暂未覆盖原文件。');
    }
    if (payload.account) this.account = this.#normalizeStored(payload.account);
    this.ready = true;
    return this.list();
  }

  list() {
    this.#assertReady();
    return publicAccount(this.account, this.busy);
  }

  async configure(input) {
    this.#assertReady();
    if (this.busy) return { ok: false, error: 'WebDAV 正在处理请求，请稍后再试。' };
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new WebDavBackupError('WebDAV 账户信息无效。');
    const normalized = normalizeWebDavBackupUrl(input.url, { allowLoopbackHttp: this.allowLoopbackHttp });
    const credentials = validateCredentials(input);
    const plannerSyncPassphrase = validatePlannerSyncPassphrase(input.plannerSyncPassphrase);
    const secret = { ...normalized, ...credentials, ...(plannerSyncPassphrase ? { plannerSyncPassphrase } : {}) };
    this.busy = true;
    try {
      const remote = await this.#get(secret);
      const plannerRemote = plannerSyncPassphrase ? await this.#get(secret, this.#plannerUrl(secret.url)) : { kind: 'missing', etag: '' };
      const encryptedSecret = await this.encrypt(JSON.stringify(secret));
      if (typeof encryptedSecret !== 'string' || !encryptedSecret || encryptedSecret.length > 16_384) {
        throw new WebDavBackupError('无法加密保存 WebDAV 登录信息，设置未保存。');
      }
      const url = new URL(normalized.url);
      const previous = this.account;
      this.account = {
        id: randomUUID(), host: normalized.host,
        fileName: url.pathname.split('/').pop().slice(0, 180),
        encryptedSecret, remoteExists: remote.kind === 'available', etag: remote.etag || '',
        plannerSyncEnabled: Boolean(plannerSyncPassphrase),
        plannerRemoteExists: plannerRemote.kind === 'available', plannerEtag: plannerRemote.etag || '',
        lastPlannerSyncAt: '', lastPlannerError: '',
        lastCheckedAt: this.#timestamp(), lastSuccessAt: remote.kind === 'available' ? this.#timestamp() : '', lastError: '',
      };
      try { await this.#persist(); }
      catch (error) { this.account = previous; throw error; }
      return { ok: true, account: this.list(), remote: remote.kind };
    } catch (error) {
      throw error instanceof WebDavBackupError ? error : new WebDavBackupError(this.#safeError(error));
    } finally { this.busy = false; }
  }

  async remove() {
    this.#assertReady();
    if (this.busy) return false;
    const previous = this.account;
    this.account = null;
    try { await this.#persist(); }
    catch (error) { this.account = previous; throw error; }
    return true;
  }

  async fetchSnapshot() {
    this.#assertReady();
    if (this.busy) return { kind: 'busy' };
    if (!this.account) return { kind: 'error', error: '请先设置 WebDAV 备份位置。' };
    this.busy = true;
    try {
      const secret = await this.#readSecret(this.account);
      const remote = await this.#get(secret);
      const updated = { ...this.account, remoteExists: remote.kind === 'available', etag: remote.etag || '', lastCheckedAt: this.#timestamp(), lastError: '' };
      if (remote.kind === 'available') updated.lastSuccessAt = this.#timestamp();
      this.account = updated;
      await this.#persist();
      return remote.kind === 'available'
        ? { kind: 'available', content: remote.content, account: this.list() }
        : { kind: 'missing', account: this.list() };
    } catch (error) {
      const message = this.#safeError(error);
      if (this.account) {
        this.account = { ...this.account, lastError: message };
        await this.#persist().catch(() => {});
      }
      return { kind: 'error', error: message, account: this.list() };
    } finally { this.busy = false; }
  }

  async pushSnapshot(content) {
    this.#assertReady();
    if (this.busy) return { kind: 'busy' };
    if (!this.account) return { kind: 'error', error: '请先设置 WebDAV 备份位置。' };
    const bytes = Buffer.byteLength(typeof content === 'string' ? content : '', 'utf8');
    if (typeof content !== 'string' || bytes < 1 || bytes > this.maxBackupBytes || !this.#isEncryptedBackup(content)) {
      return { kind: 'error', error: '只允许上传有效且未超过 70 MB 的万象来信加密备份。' };
    }
    this.busy = true;
    try {
      const secret = await this.#readSecret(this.account);
      let current = this.account;
      if (current.remoteExists && !strongEtag(current.etag)) {
        return { kind: 'unsafe', error: '服务器没有提供可用于防覆盖的强版本标记；可以恢复备份，但不能安全覆盖。' };
      }
      const headers = this.#headers(secret);
      headers['Content-Type'] = 'application/json; charset=utf-8';
      if (current.remoteExists) headers['If-Match'] = strongEtag(current.etag);
      else headers['If-None-Match'] = '*';
      const result = await this.#request(secret.url, { method: 'PUT', headers, body: content });
      if (result.status === 412) {
        this.account = { ...current, lastCheckedAt: this.#timestamp(), lastError: '云端备份已在其他设备更改；本机内容未覆盖。请先读取云端备份。' };
        await this.#persist();
        return { kind: 'conflict', error: this.account.lastError, account: this.list() };
      }
      if (![200, 201, 204].includes(result.status)) throw new WebDavBackupError(this.#httpError(result.status));
      const etag = strongEtag(result.etag);
      this.account = { ...current, remoteExists: true, etag, lastCheckedAt: this.#timestamp(), lastSuccessAt: this.#timestamp(), lastError: '' };
      await this.#persist();
      return { kind: 'uploaded', account: this.list() };
    } catch (error) {
      const message = this.#safeError(error);
      if (this.account) {
        this.account = { ...this.account, lastError: message };
        await this.#persist().catch(() => {});
      }
      return { kind: 'error', error: message, account: this.list() };
    } finally { this.busy = false; }
  }

  async getPlannerSyncPassphrase() {
    this.#assertReady();
    if (!this.account) return { ok: false, error: '请先设置 WebDAV 位置。' };
    try {
      const secret = await this.#readSecret(this.account);
      if (!secret.plannerSyncPassphrase) return { ok: false, error: '请在 WebDAV 设置中启用自动日程同步。' };
      return { ok: true, passphrase: secret.plannerSyncPassphrase };
    } catch (error) {
      return { ok: false, error: this.#safeError(error) };
    }
  }

  async fetchPlannerSnapshot() {
    this.#assertReady();
    if (this.busy) return { kind: 'busy' };
    if (!this.account?.plannerSyncEnabled) return { kind: 'error', error: '请在 WebDAV 设置中启用自动日程同步。' };
    this.busy = true;
    try {
      const secret = await this.#readSecret(this.account);
      const remote = await this.#get(secret, this.#plannerUrl(secret.url));
      this.account = {
        ...this.account, plannerRemoteExists: remote.kind === 'available', plannerEtag: remote.etag || '',
        lastCheckedAt: this.#timestamp(), lastPlannerError: '',
        ...(remote.kind === 'available' ? { lastPlannerSyncAt: this.#timestamp() } : {}),
      };
      await this.#persist();
      return remote.kind === 'available'
        ? { kind: 'available', content: remote.content, account: this.list() }
        : { kind: 'missing', account: this.list() };
    } catch (error) {
      const message = this.#safeError(error);
      this.account = { ...this.account, lastPlannerError: message };
      await this.#persist().catch(() => {});
      return { kind: 'error', error: message, account: this.list() };
    } finally { this.busy = false; }
  }

  async pushPlannerSnapshot(content) {
    this.#assertReady();
    if (this.busy) return { kind: 'busy' };
    if (!this.account?.plannerSyncEnabled) return { kind: 'error', error: '请在 WebDAV 设置中启用自动日程同步。' };
    const bytes = Buffer.byteLength(typeof content === 'string' ? content : '', 'utf8');
    if (typeof content !== 'string' || bytes < 1 || bytes > this.maxBackupBytes || !this.#isEncryptedBackup(content)) {
      return { kind: 'error', error: '只允许上传有效且未超过 70 MB 的加密日程快照。' };
    }
    this.busy = true;
    try {
      const secret = await this.#readSecret(this.account);
      const current = this.account;
      if (current.plannerRemoteExists && !strongEtag(current.plannerEtag)) {
        return { kind: 'unsafe', error: '日程同步文件没有可用于防覆盖的强版本标记；已保留两端数据。' };
      }
      const headers = this.#headers(secret);
      headers['Content-Type'] = 'application/json; charset=utf-8';
      if (current.plannerRemoteExists) headers['If-Match'] = strongEtag(current.plannerEtag);
      else headers['If-None-Match'] = '*';
      const result = await this.#request(this.#plannerUrl(secret.url), { method: 'PUT', headers, body: content });
      if (result.status === 412) {
        this.account = { ...current, lastCheckedAt: this.#timestamp(), lastPlannerError: '云端日程在读取后有变化，正在重新合并；本机内容未覆盖。' };
        await this.#persist();
        return { kind: 'conflict', error: this.account.lastPlannerError, account: this.list() };
      }
      if (![200, 201, 204].includes(result.status)) throw new WebDavBackupError(this.#httpError(result.status));
      this.account = {
        ...current, plannerRemoteExists: true, plannerEtag: strongEtag(result.etag),
        lastCheckedAt: this.#timestamp(), lastPlannerSyncAt: this.#timestamp(), lastPlannerError: '',
      };
      await this.#persist();
      return { kind: 'uploaded', account: this.list() };
    } catch (error) {
      const message = this.#safeError(error);
      this.account = { ...this.account, lastPlannerError: message };
      await this.#persist().catch(() => {});
      return { kind: 'error', error: message, account: this.list() };
    } finally { this.busy = false; }
  }

  async #get(secret, url = secret.url) {
    const result = await this.#request(url, { method: 'GET', headers: this.#headers(secret) });
    if (result.status === 404 || result.status === 410) return { kind: 'missing', etag: '' };
    if (result.status !== 200) throw new WebDavBackupError(this.#httpError(result.status));
    return { kind: 'available', content: result.body.toString('utf8'), etag: strongEtag(result.etag) };
  }

  async #request(url, options) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(url, { ...options, redirect: 'manual', signal: controller.signal });
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        if (response.body && typeof response.body.cancel === 'function') await response.body.cancel().catch(() => {});
        throw new WebDavBackupError('WebDAV 服务器返回了重定向。为保护账号密码，请使用最终的 HTTPS 文件地址。');
      }
      const etag = response.headers?.get?.('etag') || '';
      let body = Buffer.alloc(0);
      if (options.method === 'GET' && response.status === 200) {
        const announced = Number(response.headers?.get?.('content-length'));
        if (Number.isFinite(announced) && announced > this.maxBackupBytes) throw new WebDavBackupError('云端备份超过 70 MB，已停止读取。');
        const chunks = [];
        let total = 0;
        if (response.body && typeof response.body[Symbol.asyncIterator] === 'function') {
          for await (const part of response.body) {
            const chunk = Buffer.from(part);
            total += chunk.length;
            if (total > this.maxBackupBytes) throw new WebDavBackupError('云端备份超过 70 MB，已停止读取。');
            chunks.push(chunk);
          }
          body = Buffer.concat(chunks, total);
        } else {
          body = Buffer.from(await response.arrayBuffer());
          if (body.length > this.maxBackupBytes) throw new WebDavBackupError('云端备份超过 70 MB，已停止读取。');
        }
      } else if (response.body && typeof response.body.cancel === 'function') await response.body.cancel().catch(() => {});
      return { status: response.status, etag, body };
    } catch (error) {
      if (error instanceof WebDavBackupError) throw error;
      if (controller.signal.aborted) throw new WebDavBackupError('连接 WebDAV 服务器超时。');
      throw new WebDavBackupError('无法连接 WebDAV 服务器，请检查地址、账号和网络。');
    } finally { clearTimeout(timeout); }
  }

  #headers(secret) {
    return {
      Authorization: `Basic ${Buffer.from(`${secret.username}:${secret.password}`, 'utf8').toString('base64')}`,
      Accept: 'application/json, application/octet-stream;q=0.9, */*;q=0.1',
      'User-Agent': 'FLUKE Portable Backup/1.0',
    };
  }

  #plannerUrl(value) {
    const url = new URL(value);
    const fileName = url.pathname.slice(url.pathname.lastIndexOf('/') + 1);
    url.pathname = `${url.pathname.slice(0, url.pathname.lastIndexOf('/') + 1)}${fileName.replace(/\.wxbackup$/iu, '.planner-sync.wxbackup')}`;
    return url.href;
  }

  #isEncryptedBackup(content) {
    try {
      const value = JSON.parse(content);
      const base64 = (input) => typeof input === 'string' && input.length % 4 === 0 && /^[A-Za-z0-9+/]+={0,2}$/u.test(input);
      return value && value.format === FORMAT && value.version === VERSION
        && value.kdf === 'PBKDF2-HMAC-SHA256' && value.iterations === 600000
        && value.cipher === 'AES-256-GCM' && typeof value.salt === 'string'
        && value.salt.length === 24 && base64(value.salt)
        && typeof value.iv === 'string' && value.iv.length === 16 && base64(value.iv)
        && typeof value.ciphertext === 'string' && value.ciphertext.length >= 24 && base64(value.ciphertext);
    } catch { return false; }
  }

  async #readSecret(account) {
    let value;
    try { value = JSON.parse(await this.decrypt(account.encryptedSecret)); }
    catch { throw new WebDavBackupError('当前 Windows 用户无法解密 WebDAV 登录信息，请重新设置账号。'); }
    const normalized = normalizeWebDavBackupUrl(value?.url, { allowLoopbackHttp: this.allowLoopbackHttp });
    const credentials = validateCredentials(value || {});
    const plannerSyncPassphrase = validatePlannerSyncPassphrase(value?.plannerSyncPassphrase);
    if (normalized.host !== account.host) throw new WebDavBackupError('保存的 WebDAV 主机信息不匹配。');
    return { ...normalized, ...credentials, ...(plannerSyncPassphrase ? { plannerSyncPassphrase } : {}) };
  }

  #normalizeStored(value) {
    const id = typeof value.id === 'string' ? value.id : '';
    const host = typeof value.host === 'string' ? value.host : '';
    const fileName = typeof value.fileName === 'string' ? value.fileName : '';
    const encryptedSecret = typeof value.encryptedSecret === 'string' ? value.encryptedSecret : '';
    const etag = typeof value.etag === 'string' ? value.etag : '';
    const lastCheckedAt = typeof value.lastCheckedAt === 'string' ? value.lastCheckedAt : '';
    const lastSuccessAt = typeof value.lastSuccessAt === 'string' ? value.lastSuccessAt : '';
    const lastError = typeof value.lastError === 'string' ? value.lastError : '';
    const plannerEtag = typeof value.plannerEtag === 'string' ? value.plannerEtag : '';
    const lastPlannerSyncAt = typeof value.lastPlannerSyncAt === 'string' ? value.lastPlannerSyncAt : '';
    const lastPlannerError = typeof value.lastPlannerError === 'string' ? value.lastPlannerError : '';
    if (!id || id.length > 80 || !host || host.length > 255 || !fileName || fileName.length > 180
      || !encryptedSecret || encryptedSecret.length > 16_384 || etag.length > 1024 || plannerEtag.length > 1024
      || lastError.length > MAX_ERROR_LENGTH || lastPlannerError.length > MAX_ERROR_LENGTH
      || typeof value.remoteExists !== 'boolean' || (lastCheckedAt && !Number.isFinite(Date.parse(lastCheckedAt)))
      || (lastSuccessAt && !Number.isFinite(Date.parse(lastSuccessAt)))
      || (lastPlannerSyncAt && !Number.isFinite(Date.parse(lastPlannerSyncAt)))) {
      throw new WebDavBackupError('已保存的 WebDAV 备份字段无效，暂未覆盖原文件。');
    }
    return {
      id, host, fileName, encryptedSecret, remoteExists: value.remoteExists, etag, lastCheckedAt, lastSuccessAt, lastError,
      plannerSyncEnabled: value.plannerSyncEnabled === true, plannerRemoteExists: value.plannerRemoteExists === true,
      plannerEtag, lastPlannerSyncAt, lastPlannerError,
    };
  }

  #httpError(status) {
    if (status === 401 || status === 403) return 'WebDAV 登录失败或没有此文件的权限。';
    if (status === 412) return '云端备份版本已变化；本机内容未覆盖。请先读取云端备份。';
    if (status === 404) return '找不到 WebDAV 文件路径；请确认文件夹已存在。';
    return `WebDAV 服务器返回错误（HTTP ${status}）。`;
  }

  #safeError(error) {
    return String(error instanceof Error ? error.message : error || 'WebDAV 操作失败。').replace(/[\u0000-\u001f\u007f]/gu, ' ').slice(0, MAX_ERROR_LENGTH);
  }

  #timestamp() { const value = this.now(); return (value instanceof Date ? value : new Date(value)).toISOString(); }

  #assertReady() { if (!this.ready) throw new WebDavBackupError('WebDAV 备份服务尚未就绪。'); }

  #persist() {
    const operation = this.writeChain.catch(() => {}).then(async () => {
      const directory = path.dirname(this.storagePath);
      await fs.mkdir(directory, { recursive: true });
      const payload = JSON.stringify({ format: 1, account: this.account });
      const temporaryPath = `${this.storagePath}.${process.pid}.${randomUUID()}.tmp`;
      await fs.writeFile(temporaryPath, payload, { encoding: 'utf8', mode: 0o600 });
      try { await fs.rename(temporaryPath, this.storagePath); }
      catch (error) { await fs.rm(temporaryPath, { force: true }).catch(() => {}); throw error; }
    });
    this.writeChain = operation.catch(() => {});
    return operation;
  }
}

module.exports = {
  WebDavBackupError,
  WebDavBackupService,
  MAX_BACKUP_BYTES,
  normalizeWebDavBackupUrl,
  strongEtag,
};
