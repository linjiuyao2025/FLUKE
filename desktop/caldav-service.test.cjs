'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { CalDavService } = require('./caldav-service.cjs');
const WanxiangCalendar = require('./calendar-exchange.js');

const event = [
  'BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', 'UID:event-1', 'SUMMARY:Remote meeting',
  'DTSTART:20260929T100000Z', 'DTEND:20260929T110000Z', 'END:VEVENT', 'END:VCALENDAR', '',
].join('\r\n');
const eventXml = '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
  + '<d:response><d:href>/dav/work/event.ics</d:href><d:propstat><d:prop><d:getetag>"v1"</d:getetag>'
  + '<c:calendar-data>' + event.replace(/&/gu, '&amp;').replace(/</gu, '&lt;').replace(/>/gu, '&gt;')
  + '</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>';
const propfindXml = '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
  + '<d:response><d:href>/dav/work/</d:href><d:propstat><d:prop><d:displayname>Work</d:displayname>'
  + '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>'
  + '<c:supported-calendar-component-set><c:comp name="VEVENT"/><c:comp name="VTODO"/></c:supported-calendar-component-set>'
  + '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>';

async function fixture(t, handler) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return 'http://127.0.0.1:' + server.address().port + '/dav/work/';
}

async function makeService(t, url, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'wanxiang-caldav-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const storagePath = path.join(directory, 'caldav.json');
  const service = new CalDavService({
    storagePath,
    encrypt: async (value) => 'cipher:' + Buffer.from(value).toString('base64'),
    decrypt: async (value) => Buffer.from(value.slice(7), 'base64').toString('utf8'),
    combineIcs: WanxiangCalendar.combineIcsResources,
    todoResourceUids: WanxiangCalendar.todoResourceUids,
    updateVtodoCompletion: WanxiangCalendar.updateVtodoCompletion,
    ...options,
  });
  await service.load();
  return { service, storagePath, directory };
}

function send(res, status, body = '', headers = {}) {
  res.writeHead(status, { 'Content-Type': 'application/xml; charset=utf-8', ...headers });
  res.end(body);
}

test('CalDAV add encrypts URL and credentials and sync commits its token only after renderer acknowledgement', async (t) => {
  const requests = [];
  let serverToken = 'urn:sync:1';
  const url = await fixture(t, async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf8');
    requests.push({ method: req.method, path: req.url, auth: req.headers.authorization || '', body });
    if (req.method === 'PROPFIND') return send(res, 207, propfindXml);
    if (req.method === 'REPORT' && body.includes('sync-collection')) {
      if (body.includes(serverToken)) {
        return send(res, 207, '<d:multistatus xmlns:d="DAV:"><d:sync-token>' + serverToken + '</d:sync-token></d:multistatus>');
      }
      return send(res, 207, '<d:multistatus xmlns:d="DAV:"><d:sync-token>' + serverToken
        + '</d:sync-token><d:response><d:href>/dav/work/event.ics</d:href><d:propstat><d:prop>'
        + '<d:getetag>"v1"</d:getetag></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>');
    }
    if (req.method === 'REPORT' && body.includes('calendar-multiget')) return send(res, 207, eventXml);
    if (req.method === 'REPORT' && body.includes('calendar-query')) return send(res, 207, eventXml);
    send(res, 400, '');
  });
  const { service, storagePath } = await makeService(t, url);
  const added = await service.add({ url, name: 'Work', username: 'lin', password: 'secret' });
  assert.equal(added.name, 'Work');
  assert.equal('url' in added, false);
  const serialized = await fs.readFile(storagePath, 'utf8');
  assert.equal(serialized.includes('secret'), false);
  assert.equal(serialized.includes('/dav/work/'), false);
  assert.equal(serialized.includes('lin'), false);
  const first = await service.sync(added.id);
  assert.equal(first.kind, 'updated');
  assert.equal(first.eventCount, 1);
  assert.equal(first.todoCount, 0);
  assert.equal(first.account.resourceCount, 1);
  assert.equal(await service.commit(added.id, 'wrong-token'), false);
  assert.equal((await service.list())[0].resourceCount, 0);
  assert.equal(await service.commit(added.id, first.commitToken), true);
  assert.equal((await service.list())[0].resourceCount, 1);
  serverToken = 'urn:sync:2';
  const second = await service.sync(added.id);
  assert.equal(second.kind, 'updated');
  assert.equal(second.eventCount, 1);
  assert.equal(await service.commit(added.id, second.commitToken), true);
  const reload = new CalDavService({
    storagePath,
    encrypt: async (value) => 'cipher:' + Buffer.from(value).toString('base64'),
    decrypt: async (value) => Buffer.from(value.slice(7), 'base64').toString('utf8'),
    combineIcs: WanxiangCalendar.combineIcsResources,
    todoResourceUids: WanxiangCalendar.todoResourceUids,
    updateVtodoCompletion: WanxiangCalendar.updateVtodoCompletion,
  });
  assert.equal((await reload.load())[0].resourceCount, 1);
  assert.ok(requests.every((item) => item.auth === 'Basic ' + Buffer.from('lin:secret').toString('base64')));
  assert.equal(requests.some((item) => item.body.includes('urn:sync:1')), true);
});

test('CalDAV VTODO completion uses If-Match and updates its cached resource only after server confirmation', async (t) => {
  let currentEtag = '"todo-v1"';
  let currentCalendar = [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VTODO', 'UID:task-1', 'SUMMARY:Remote task',
    'STATUS:NEEDS-ACTION', 'SEQUENCE:4', 'END:VTODO', 'END:VCALENDAR', '',
  ].join('\r\n');
  let rejectPut = false;
  const puts = [];
  const calendarXml = () => '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    + '<d:response><d:href>/dav/work/task.ics</d:href><d:propstat><d:prop><d:getetag>' + currentEtag
    + '</d:getetag><c:calendar-data>' + currentCalendar.replace(/&/gu, '&amp;').replace(/</gu, '&lt;').replace(/>/gu, '&gt;')
    + '</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>';
  const url = await fixture(t, async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf8');
    if (req.method === 'PROPFIND') return send(res, 207, propfindXml);
    if (req.method === 'REPORT' && body.includes('sync-collection')) return send(res, 501);
    if (req.method === 'REPORT' && body.includes('calendar-query')) return send(res, 207, calendarXml());
    if (req.method === 'PUT') {
      puts.push({ ifMatch: req.headers['if-match'], contentType: req.headers['content-type'], body });
      if (rejectPut || req.headers['if-match'] !== currentEtag) return send(res, 412, '');
      currentCalendar = body;
      currentEtag = '"todo-v2"';
      res.writeHead(204, { ETag: currentEtag });
      return res.end();
    }
    return send(res, 400);
  });
  const { service, storagePath } = await makeService(t, url);
  const account = await service.add({ url });
  const initial = await service.sync(account.id);
  assert.equal(initial.todoCount, 1);
  assert.equal(await service.commit(account.id, initial.commitToken), true);

  const completed = await service.setTodoCompletion(account.id, 'task-1', true);
  assert.equal(completed.ok, true);
  assert.equal(puts.length, 1);
  assert.equal(puts[0].ifMatch, '"todo-v1"');
  assert.match(puts[0].contentType, /^text\/calendar/u);
  const parsed = WanxiangCalendar.parseIcs(puts[0].body);
  assert.equal(parsed.todos[0].done, true);
  assert.match(puts[0].body, /SEQUENCE:5\r\n/u);
  const persisted = JSON.parse(await fs.readFile(storagePath, 'utf8'));
  assert.equal(persisted.accounts[0].resources[0].etag, '"todo-v2"');
  assert.equal(WanxiangCalendar.parseIcs(persisted.accounts[0].resources[0].calendarData).todos[0].done, true);

  rejectPut = true;
  const conflict = await service.setTodoCompletion(account.id, 'task-1', false);
  assert.equal(conflict.ok, false);
  assert.match(conflict.error, /先同步/u);
  assert.equal(puts[1].ifMatch, '"todo-v2"');
  const afterConflict = JSON.parse(await fs.readFile(storagePath, 'utf8'));
  assert.equal(WanxiangCalendar.parseIcs(afterConflict.accounts[0].resources[0].calendarData).todos[0].done, true);
});

test('CalDAV falls back to full query when the server rejects sync-collection', async (t) => {
  let fullQueries = 0;
  const url = await fixture(t, async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf8');
    if (req.method === 'PROPFIND') return send(res, 207, propfindXml);
    if (body.includes('sync-collection')) return send(res, 501);
    if (body.includes('calendar-query')) { fullQueries++; return send(res, 207, eventXml); }
    send(res, 400);
  });
  const { service } = await makeService(t, url);
  const account = await service.add({ url });
  const result = await service.sync(account.id);
  assert.equal(result.kind, 'updated');
  assert.equal(fullQueries, 1);
  assert.equal(await service.commit(account.id, result.commitToken), true);
});

test('CalDAV sync does not forward credentials across redirects', async (t) => {
  let redirected = false;
  const url = await fixture(t, (req, res) => {
    if (req.method === 'PROPFIND') {
      res.writeHead(302, { Location: 'http://127.0.0.1:1/steal' });
      res.end();
      return;
    }
    redirected = Boolean(req.headers.authorization);
    send(res, 500);
  });
  const { service } = await makeService(t, url);
  await assert.rejects(service.add({ url, username: 'u', password: 'p' }), /重定向跳到其他来源/u);
  assert.equal(redirected, false);
  assert.equal(service.list().length, 0);
});

test('CalDAV leaves the saved resource snapshot untouched when a sync fails', async (t) => {
  let fail = false;
  const url = await fixture(t, async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf8');
    if (req.method === 'PROPFIND') return send(res, 207, propfindXml);
    if (fail) return send(res, 500);
    if (body.includes('sync-collection')) return send(res, 207,
      '<d:multistatus xmlns:d="DAV:"><d:sync-token>urn:sync:1</d:sync-token>'
      + '<d:response><d:href>/dav/work/event.ics</d:href><d:propstat><d:prop><d:getetag>"v1"</d:getetag></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>');
    if (body.includes('calendar-multiget')) return send(res, 207, eventXml);
    send(res, 400);
  });
  const { service } = await makeService(t, url);
  const account = await service.add({ url });
  const result = await service.sync(account.id);
  assert.equal(await service.commit(account.id, result.commitToken), true);
  fail = true;
  const failed = await service.sync(account.id);
  assert.equal(failed.kind, 'error');
  assert.equal((await service.list())[0].resourceCount, 1);
  assert.match((await service.list())[0].lastError, /HTTP 500/u);
});
