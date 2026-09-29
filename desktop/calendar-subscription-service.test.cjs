'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  CalendarSubscriptionError,
  CalendarSubscriptionService,
  MAX_FEED_BYTES,
  normalizeSubscriptionUrl,
} = require('./calendar-subscription-service.cjs');
const WanxiangCalendar = require('./calendar-exchange.js');

function eventFeed(summary = 'Team review') {
  return [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//FLUKE//Calendar Subscription Test//EN',
    'BEGIN:VEVENT', 'UID:review@example.test', 'DTSTART:20260929T090000Z',
    'DTEND:20260929T100000Z', `SUMMARY:${summary}`, 'END:VEVENT', 'END:VCALENDAR', '',
  ].join('\r\n');
}

function emptyFeed() {
  return ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//FLUKE//Calendar Subscription Test//EN', 'END:VCALENDAR', ''].join('\r\n');
}

async function startFeedServer(t, initial = {}) {
  const state = {
    status: 200,
    etag: '"v1"',
    lastModified: 'Tue, 29 Sep 2026 00:00:00 GMT',
    body: eventFeed(),
    requests: [],
    ...initial,
  };
  const server = http.createServer((request, response) => {
    state.requests.push({ url: request.url, headers: request.headers });
    if (request.headers['if-none-match'] === state.etag && state.status === 200) {
      response.writeHead(304, { ETag: state.etag, 'Last-Modified': state.lastModified });
      response.end();
      return;
    }
    response.writeHead(state.status, {
      'Content-Type': 'text/calendar; charset=utf-8',
      ETag: state.etag,
      'Last-Modified': state.lastModified,
    });
    response.end(state.body);
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return { state, url: `http://127.0.0.1:${server.address().port}/team.ics?token=secret-calendar-token` };
}

async function createService(t, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'wanxiang-calendar-subscriptions-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const service = new CalendarSubscriptionService({
    storagePath: path.join(directory, 'calendar-subscriptions.json'),
    encrypt: async (value) => Buffer.from(`test-key:${value}`, 'utf8').toString('base64'),
    decrypt: async (value) => Buffer.from(value, 'base64').toString('utf8').replace(/^test-key:/, ''),
    parseIcs: WanxiangCalendar.parseIcs,
    ...options,
  });
  await service.load();
  return { service, directory, storagePath: service.storagePath };
}

test('subscription URL normalization upgrades webcal, strips fragments, and rejects credentials and unsafe schemes', () => {
  assert.deepEqual(normalizeSubscriptionUrl('webcal://Calendar.Example.test/feed?id=abc#week'), {
    url: 'https://calendar.example.test/feed?id=abc',
    host: 'calendar.example.test',
  });
  assert.equal(normalizeSubscriptionUrl('webcals://calendar.example.test/a').url, 'https://calendar.example.test/a');
  for (const value of [
    '', 'file:///C:/calendar.ics', 'ftp://calendar.example.test/feed',
    'https://user:pass@calendar.example.test/feed', 'https:///missing-host',
    'https://calendar.example.test/with space', `https://calendar.example.test/${'x'.repeat(2100)}`,
  ]) {
    assert.throws(() => normalizeSubscriptionUrl(value), CalendarSubscriptionError, value);
  }
});

test('subscription URLs stay encrypted outside the renderer and survive a service restart', async (t) => {
  const { service, storagePath } = await createService(t);
  const { url } = await startFeedServer(t);
  const metadata = await service.add({ name: 'Team meetings', url });
  assert.equal(metadata.name, 'Team meetings');
  assert.equal(metadata.host, '127.0.0.1');
  assert.equal(JSON.stringify(service.list()).includes('secret-calendar-token'), false);
  const persisted = await fs.readFile(storagePath, 'utf8');
  assert.equal(persisted.includes('secret-calendar-token'), false);
  assert.equal(persisted.includes(url), false);

  const restarted = new CalendarSubscriptionService({
    storagePath,
    encrypt: async (value) => value,
    decrypt: async (value) => Buffer.from(value, 'base64').toString('utf8').replace(/^test-key:/, ''),
    parseIcs: WanxiangCalendar.parseIcs,
  });
  await restarted.load();
  assert.equal(restarted.list()[0].id, metadata.id);
  assert.equal(restarted.list()[0].name, 'Team meetings');
});

test('the same normalized feed cannot be added twice', async (t) => {
  const { service } = await createService(t);
  const { url } = await startFeedServer(t);
  await service.add({ name: 'Team', url });
  await assert.rejects(service.add({ name: 'Same feed', url: `${url}#another-view` }), /已经添加/);
  assert.equal(service.list().length, 1);
});

test('an unnamed subscription with a long host stores a bounded display name', async (t) => {
  const { service, storagePath } = await createService(t);
  const host = `${'a'.repeat(60)}.${'b'.repeat(30)}.test`;
  const added = await service.add({ name: '', url: `https://${host}/feed.ics` });
  assert.equal(added.name.length, 80);
  const restarted = new CalendarSubscriptionService({
    storagePath,
    encrypt: async value => value,
    decrypt: async value => Buffer.from(value, 'base64').toString('utf8').replace(/^test-key:/, ''),
    parseIcs: WanxiangCalendar.parseIcs,
  });
  await restarted.load();
  assert.equal(restarted.list()[0].name.length, 80);
});

test('refresh conditionally downloads, atomically commits validators, and reuses the cached calendar on 304', async (t) => {
  const { service } = await createService(t);
  const server = await startFeedServer(t);
  const subscription = await service.add({ name: 'Team', url: server.url });

  const first = await service.refresh(subscription.id);
  assert.equal(first.kind, 'updated');
  assert.equal(first.eventCount, 1);
  assert.match(first.icsText, /SUMMARY:Team review/);
  assert.equal(service.list()[0].lastSuccessAt, '');
  assert.equal(await service.commit(subscription.id, first.commitToken), true);
  assert.equal(service.list()[0].eventCount, 1);
  assert.ok(service.list()[0].lastSuccessAt);

  const second = await service.refresh(subscription.id);
  assert.equal(second.kind, 'not-modified');
  assert.equal('icsText' in second, false);
  assert.equal(server.state.requests[1].headers['if-none-match'], '"v1"');
  assert.equal(await service.commit(subscription.id, second.commitToken), true);
  assert.equal(service.list()[0].lastError, '');
});

test('parallel refreshes and commits do not overwrite another calendar subscription', async (t) => {
  const { service, storagePath } = await createService(t);
  const server = await startFeedServer(t);
  const first = await service.add({ name: 'Team', url: server.url });
  const second = await service.add({ name: 'Family', url: server.url.replace('/team.ics', '/family.ics') });
  const results = await service.refreshAll();
  assert.deepEqual(results.map(result => result.kind), ['updated', 'updated']);
  assert.deepEqual(await Promise.all(results.map(result => service.commit(result.id, result.commitToken))), [true, true]);
  assert.equal(service.list().length, 2);
  assert.equal(service.list().find(item => item.id === first.id).eventCount, 1);
  assert.equal(service.list().find(item => item.id === second.id).eventCount, 1);
  const persisted = JSON.parse(await fs.readFile(storagePath, 'utf8'));
  assert.equal(persisted.subscriptions.length, 2);
  assert.deepEqual(persisted.subscriptions.map(item => item.etag), ['"v1"', '"v1"']);
});

test('network errors and invalid feeds keep the previous success and validators', async (t) => {
  const { service } = await createService(t);
  const server = await startFeedServer(t);
  const subscription = await service.add({ name: 'Team', url: server.url });
  const initial = await service.refresh(subscription.id);
  await service.commit(subscription.id, initial.commitToken);

  server.state.status = 503;
  const failed = await service.refresh(subscription.id);
  assert.equal(failed.kind, 'error');
  assert.match(failed.error, /HTTP 503/);
  assert.equal(service.list()[0].eventCount, 1);
  assert.equal(service.list()[0].lastSuccessAt, initial.lastSuccessAt);
  assert.equal(service.list()[0].lastError, failed.error);

  server.state.status = 200;
  server.state.etag = '"invalid"';
  server.state.body = 'This is not an iCalendar feed';
  const invalid = await service.refresh(subscription.id);
  assert.equal(invalid.kind, 'error');
  assert.equal(service.list()[0].eventCount, 1);
  const persisted = JSON.parse(await fs.readFile(service.storagePath, 'utf8'));
  assert.equal(persisted.subscriptions[0].etag, '"v1"');
});

test('a valid empty calendar clears a feed only after the renderer commits it', async (t) => {
  const { service } = await createService(t);
  const server = await startFeedServer(t, { body: emptyFeed(), etag: '"empty"' });
  const subscription = await service.add({ name: 'Empty calendar', url: server.url });
  const result = await service.refresh(subscription.id);
  assert.equal(result.kind, 'updated');
  assert.equal(result.eventCount, 0);
  assert.match(result.icsText, /END:VCALENDAR/);
  assert.equal(await service.commit(subscription.id, result.commitToken), true);
  assert.equal(service.list()[0].eventCount, 0);
});

test('a 304 without an existing validator or a forced full fetch is not accepted as a cached calendar', async (t) => {
  const { service } = await createService(t, {
    fetchImpl: async () => new Response(null, { status: 304 }),
  });
  const subscription = await service.add({ name: 'Team', url: 'https://calendar.example.test/feed.ics' });
  const result = await service.refresh(subscription.id, { force: true });
  assert.equal(result.kind, 'error');
  assert.match(result.error, /没有本机缓存/);
  assert.equal(service.list()[0].eventCount, 0);
});

test('oversized responses, unsafe redirects, and stale commits are rejected', async (t) => {
  const oversized = 'X'.repeat(MAX_FEED_BYTES + 1);
  const { service } = await createService(t);
  const server = await startFeedServer(t, { body: oversized });
  const subscription = await service.add({ name: 'Team', url: server.url });
  const tooLarge = await service.refresh(subscription.id);
  assert.equal(tooLarge.kind, 'error');
  assert.match(tooLarge.error, /超过 1 MB/);

  const redirecting = new CalendarSubscriptionService({
    storagePath: service.storagePath,
    encrypt: async (value) => value,
    decrypt: async () => 'https://calendar.example.test/feed.ics',
    parseIcs: WanxiangCalendar.parseIcs,
    fetchImpl: async () => new Response(null, { status: 302, headers: { Location: 'http://127.0.0.1/private.ics' } }),
  });
  await redirecting.load();
  const downgrade = await redirecting.refresh(subscription.id);
  assert.equal(downgrade.kind, 'error');
  assert.match(downgrade.error, /降级连接/);

  assert.equal(await service.commit(subscription.id, 'stale-token'), false);
});

test('automatic refresh waits one hour after an attempt and removal deletes stored credentials', async (t) => {
  const now = () => new Date('2026-09-29T00:00:00.000Z');
  const { service, storagePath } = await createService(t, { now });
  const server = await startFeedServer(t);
  const subscription = await service.add({ name: 'Team', url: server.url });
  const first = await service.refresh(subscription.id);
  await service.commit(subscription.id, first.commitToken);
  assert.equal((await service.refreshDue(new Date('2026-09-29T00:30:00.000Z'))).length, 0);
  assert.equal((await service.refreshDue(new Date('2026-09-29T01:00:01.000Z'))).length, 1);
  assert.equal(await service.remove(subscription.id), true);
  assert.equal(service.list().length, 0);
  assert.equal(JSON.parse(await fs.readFile(storagePath, 'utf8')).subscriptions.length, 0);
});

test('the request timeout also covers a server that stalls while streaming its calendar', async (t) => {
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/calendar' });
    response.flushHeaders();
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const { service } = await createService(t, { timeoutMs: 1000 });
  const subscription = await service.add({ name: 'Slow calendar', url: `http://127.0.0.1:${server.address().port}/slow.ics` });
  const result = await service.refresh(subscription.id);
  assert.equal(result.kind, 'error');
  assert.match(result.error, /超时/);
});
