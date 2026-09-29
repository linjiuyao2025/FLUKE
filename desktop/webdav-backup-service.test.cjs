'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  normalizeWebDavBackupUrl,
  WebDavBackupError,
  WebDavBackupService,
} = require('./webdav-backup-service.cjs');

const endpoint = 'https://cloud.example.test/remote.php/dav/files/lin/wanxiang.wxbackup';
const encryptedBackup = JSON.stringify({
  format: 'wanxiang-encrypted-backup', version: 1, kdf: 'PBKDF2-HMAC-SHA256', iterations: 600000,
  cipher: 'AES-256-GCM', salt: Buffer.alloc(16, 1).toString('base64'), iv: Buffer.alloc(12, 2).toString('base64'),
  ciphertext: Buffer.alloc(32, 3).toString('base64'),
});

async function makeService(fetchImpl, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'wanxiang-webdav-'));
  const service = new WebDavBackupService({
    storagePath: path.join(directory, 'webdav-backup.json'),
    encrypt: async (value) => Buffer.from(value).toString('base64'),
    decrypt: async (value) => Buffer.from(value, 'base64').toString(),
    fetchImpl,
    allowLoopbackHttp: options.allowLoopbackHttp,
    maxBackupBytes: options.maxBackupBytes,
    timeoutMs: options.timeoutMs,
  });
  await service.load();
  return { service, directory };
}

function memoryServer(initial = null) {
  const state = { content: initial, etag: initial ? '"v1"' : '', plannerContent: null, plannerEtag: '', requests: [] };
  const fetchImpl = async (url, options) => {
    state.requests.push({ url, options, headers: new Headers(options.headers) });
    assert.equal(options.redirect, 'manual');
    const planner = new URL(url).pathname.endsWith('.planner-sync.wxbackup');
    const getContent = () => planner ? state.plannerContent : state.content;
    const getEtag = () => planner ? state.plannerEtag : state.etag;
    const setResource = (content, etag) => {
      if (planner) { state.plannerContent = content; state.plannerEtag = etag; }
      else { state.content = content; state.etag = etag; }
    };
    if (options.method === 'GET') {
      if (getContent() === null) return new Response('', { status: 404 });
      return new Response(getContent(), { status: 200, headers: getEtag() ? { etag: getEtag() } : {} });
    }
    if (options.method !== 'PUT') return new Response('', { status: 405 });
    const headers = new Headers(options.headers);
    if (headers.has('if-none-match') && getContent() !== null) return new Response('', { status: 412 });
    if (headers.has('if-match') && headers.get('if-match') !== getEtag()) return new Response('', { status: 412 });
    const etag = `"v${Number(getEtag()?.match(/\d+/u)?.[0] || 0) + 1}"`;
    setResource(options.body, etag);
    return new Response('', { status: 201, headers: { etag } });
  };
  return { state, fetchImpl };
}

test('WebDAV backup URL requires HTTPS, an explicit file path, and no embedded credentials', () => {
  assert.equal(normalizeWebDavBackupUrl(endpoint).host, 'cloud.example.test');
  assert.equal(normalizeWebDavBackupUrl('http://localhost:8080/dav/backup.wxbackup', { allowLoopbackHttp: true }).host, 'localhost');
  assert.throws(() => normalizeWebDavBackupUrl('http://cloud.example.test/dav/backup.wxbackup'), WebDavBackupError);
  assert.throws(() => normalizeWebDavBackupUrl('https://user:pass@cloud.example.test/dav/backup.wxbackup'), /地址中不要包含账号/u);
  assert.throws(() => normalizeWebDavBackupUrl('https://cloud.example.test/dav/'), /具体的备份文件路径/u);
  assert.throws(() => normalizeWebDavBackupUrl('https://cloud.example.test/dav/notes.txt'), /以 \.wxbackup 结尾/u);
  assert.throws(() => normalizeWebDavBackupUrl('https://cloud.example.test/dav/backup.wxbackup#fragment'), /地址中不要包含/u);
});

test('WebDAV stores credentials encrypted and conditionally creates the first encrypted snapshot', async (t) => {
  const server = memoryServer();
  const { service, directory } = await makeService(server.fetchImpl);
  t.after(() => fs.rm(directory, { recursive: true, force: true }));

  const configured = await service.configure({ url: endpoint, username: 'lin', password: 'app-password' });
  assert.equal(configured.ok, true);
  assert.equal(configured.remote, 'missing');
  const first = await service.pushSnapshot(encryptedBackup);
  assert.equal(first.kind, 'uploaded');
  assert.equal(server.state.content, encryptedBackup);
  assert.equal(server.state.requests.at(-1).headers.get('if-none-match'), '*');
  assert.equal(server.state.requests.at(-1).headers.has('if-match'), false);
  assert.match(server.state.requests.at(-1).headers.get('authorization'), /^Basic /u);
  assert.equal(service.list().canSafelyReplace, true);

  const persisted = await fs.readFile(path.join(directory, 'webdav-backup.json'), 'utf8');
  assert.doesNotMatch(persisted, /app-password/u);
  assert.doesNotMatch(persisted, /remote\.php/u);
  const restarted = new WebDavBackupService({
    storagePath: path.join(directory, 'webdav-backup.json'),
    encrypt: async (value) => Buffer.from(value).toString('base64'),
    decrypt: async (value) => Buffer.from(value, 'base64').toString(),
    fetchImpl: server.fetchImpl,
  });
  await restarted.load();
  assert.equal(restarted.list().canSafelyReplace, true);
  assert.equal((await restarted.pushSnapshot(encryptedBackup)).kind, 'uploaded');
  assert.equal(server.state.requests.at(-1).headers.get('if-match'), '"v1"');
});

test('WebDAV rejects a stale upload with 412 and keeps the other device snapshot', async (t) => {
  const server = memoryServer();
  const { service, directory } = await makeService(server.fetchImpl);
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  await service.configure({ url: endpoint, username: 'lin', password: 'app-password' });
  assert.equal((await service.pushSnapshot(encryptedBackup)).kind, 'uploaded');

  server.state.content = encryptedBackup.replace('"v1"', '"new"');
  server.state.etag = '"v2"';
  const stale = await service.pushSnapshot(encryptedBackup);
  assert.equal(stale.kind, 'conflict');
  assert.match(stale.error, /本机内容未覆盖/u);
  assert.equal(server.state.content, encryptedBackup.replace('"v1"', '"new"'));
  assert.equal(server.state.requests.at(-1).headers.get('if-match'), '"v1"');
});

test('WebDAV fetch updates its strong validator and refuses overwrite without one', async (t) => {
  const server = memoryServer(encryptedBackup);
  const { service, directory } = await makeService(server.fetchImpl);
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const configured = await service.configure({ url: endpoint, username: 'lin', password: 'app-password' });
  assert.equal(configured.account.canSafelyReplace, true);
  const snapshot = await service.fetchSnapshot();
  assert.equal(snapshot.kind, 'available');
  assert.equal(snapshot.content, encryptedBackup);

  server.state.etag = 'W/"weak"';
  const refreshed = await service.fetchSnapshot();
  assert.equal(refreshed.kind, 'available');
  assert.equal(refreshed.account.canSafelyReplace, false);
  assert.equal((await service.pushSnapshot(encryptedBackup)).kind, 'unsafe');
  assert.equal(server.state.content, encryptedBackup);
});

test('WebDAV missing snapshots are distinct from request errors, and redirects are refused', async (t) => {
  const missing = memoryServer();
  const first = await makeService(missing.fetchImpl);
  t.after(() => fs.rm(first.directory, { recursive: true, force: true }));
  await first.service.configure({ url: endpoint, username: 'lin', password: 'app-password' });
  assert.equal((await first.service.fetchSnapshot()).kind, 'missing');

  let request;
  const redirectService = await makeService(async (url, options) => {
    request = { url, headers: new Headers(options.headers), redirect: options.redirect };
    return new Response('', { status: 302, headers: { location: 'https://other.example.test/steal' } });
  });
  t.after(() => fs.rm(redirectService.directory, { recursive: true, force: true }));
  await assert.rejects(redirectService.service.configure({ url: endpoint, username: 'lin', password: 'app-password' }), /重定向/u);
  assert.equal(request.redirect, 'manual');
  assert.equal(request.url, endpoint);
  assert.match(request.headers.get('authorization'), /^Basic /u);
});

test('WebDAV rejects malformed snapshots and oversized remote bodies before restore', async (t) => {
  const server = memoryServer();
  const { service, directory } = await makeService(server.fetchImpl);
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  await service.configure({ url: endpoint, username: 'lin', password: 'app-password' });
  assert.equal((await service.pushSnapshot('{"format":"daily-atlas-backup"}')).kind, 'error');

  const oversizedService = await makeService(async () => new Response('x'.repeat(1025), { status: 200, headers: { etag: '"v1"' } }), { maxBackupBytes: 1024 });
  t.after(() => fs.rm(oversizedService.directory, { recursive: true, force: true }));
  await oversizedService.service.configure({ url: endpoint, username: 'lin', password: 'app-password' }).catch(() => {});
  assert.equal(oversizedService.service.list(), null);
});

test('planner auto-sync uses an encrypted separate sidecar and its own conditional ETag', async (t) => {
  const server = memoryServer();
  const { service, directory } = await makeService(server.fetchImpl);
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const configured = await service.configure({
    url: endpoint, username: 'lin', password: 'app-password', plannerSyncPassphrase: 'separate sync password',
  });
  assert.equal(configured.account.plannerSyncEnabled, true);
  assert.equal(configured.remote, 'missing');
  assert.equal(configured.account.plannerRemoteExists, false);
  assert.equal((await service.getPlannerSyncPassphrase()).passphrase, 'separate sync password');
  assert.equal((await service.fetchPlannerSnapshot()).kind, 'missing');

  assert.equal((await service.pushPlannerSnapshot(encryptedBackup)).kind, 'uploaded');
  assert.equal(server.state.content, null, 'planner data does not replace the full-backup file');
  assert.equal(server.state.plannerContent, encryptedBackup);
  const request = server.state.requests.at(-1);
  assert.equal(new URL(request.url).pathname.endsWith('/wanxiang.planner-sync.wxbackup'), true);
  assert.equal(request.headers.get('if-none-match'), '*');

  const persisted = await fs.readFile(path.join(directory, 'webdav-backup.json'), 'utf8');
  assert.doesNotMatch(persisted, /separate sync password/u);
  assert.equal(service.list().remoteExists, false);
  assert.equal(service.list().canSafelyReplace, true);
  assert.equal(service.list().plannerRemoteExists, true);
  assert.equal(service.list().lastPlannerSyncAt.length > 0, true);
});

test('planner auto-sync rejects stale writes and reloads its independent ETag and key', async (t) => {
  const server = memoryServer(encryptedBackup);
  const { service, directory } = await makeService(server.fetchImpl);
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  await service.configure({ url: endpoint, username: 'lin', password: 'app-password', plannerSyncPassphrase: 'separate sync password' });
  assert.equal(service.list().remoteExists, true);
  assert.equal(service.list().plannerRemoteExists, false);
  const created = await service.pushPlannerSnapshot(encryptedBackup);
  assert.equal(created.kind, 'uploaded');
  server.state.plannerContent = encryptedBackup.replace('ciphertext', 'ciphertext changed remotely');
  server.state.plannerEtag = '"planner-v2"';
  const stale = await service.pushPlannerSnapshot(encryptedBackup);
  assert.equal(stale.kind, 'conflict');
  assert.equal(server.state.plannerContent, encryptedBackup.replace('ciphertext', 'ciphertext changed remotely'));

  const restarted = new WebDavBackupService({
    storagePath: path.join(directory, 'webdav-backup.json'),
    encrypt: async (value) => Buffer.from(value).toString('base64'),
    decrypt: async (value) => Buffer.from(value, 'base64').toString(),
    fetchImpl: server.fetchImpl,
  });
  await restarted.load();
  assert.equal(restarted.list().plannerSyncEnabled, true);
  assert.equal((await restarted.getPlannerSyncPassphrase()).passphrase, 'separate sync password');
  const remote = await restarted.fetchPlannerSnapshot();
  assert.equal(remote.kind, 'available');
  assert.equal(restarted.list().plannerCanSafelyReplace, true);
});
