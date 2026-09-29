'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Dav = require('./caldav-protocol.cjs');

const collection = 'https://cal.example.test/calendars/user/work/';
const oneEvent = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:e1\r\nSUMMARY:Work\r\nDTSTART:20260929T100000Z\r\nDTEND:20260929T110000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n';
const eventXml = (href = '/calendars/user/work/event.ics', data = oneEvent, etag = '"v1"') =>
  '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>' + href
  + '</d:href><d:propstat><d:prop><d:getetag>' + etag + '</d:getetag><c:calendar-data>'
  + data.replace(/&/gu, '&amp;').replace(/</gu, '&lt;').replace(/>/gu, '&gt;')
  + '</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>';

test('CalDAV accepts HTTPS and only loopback HTTP', () => {
  assert.equal(Dav.normalizeUrl('https://dav.example.test/path').url, 'https://dav.example.test/path');
  assert.match(Dav.normalizeUrl('http://127.0.0.1:8080/calendar').url, /^http:/u);
  assert.match(Dav.normalizeUrl('http://[::1]:8080/calendar').url, /^http:/u);
  assert.throws(() => Dav.normalizeUrl('http://dav.example.test/calendar'), /必须使用 HTTPS/u);
  assert.throws(() => Dav.normalizeUrl('https://user:pass@dav.example.test/calendar'), /账号密码/u);
  assert.throws(() => Dav.normalizeUrl('https://@dav.example.test/calendar'), /账号密码/u);
  assert.throws(() => Dav.normalizeUrl('https://dav.example.test/calendar?token=x'), /查询参数/u);
});

test('credentials are validated and Basic auth encodes UTF-8', () => {
  assert.equal(Dav.authorizationHeader('user', 'pass'), 'Basic ' + Buffer.from('user:pass').toString('base64'));
  assert.throws(() => Dav.validateCredentials('user:', ''), /同时填写/u);
  assert.throws(() => Dav.validateCredentials('bad:user', 'pass'), /无效/u);
});

test('DAV XML request builders escape sync tokens and hrefs', () => {
  assert.match(Dav.propfindBody(), /supported-calendar-component-set/u);
  assert.match(Dav.syncCollectionBody('urn:sync?a&b'), /urn:sync\?a&amp;b/u);
  assert.match(Dav.multigetBody(['/cal/a.ics?x&y']), /a\.ics\?x&amp;y/u);
  assert.throws(() => Dav.syncCollectionBody('not a uri'), /令牌/u);
  assert.throws(() => Dav.multigetBody(['/a', '/a']), /重复/u);
});

test('PROPFIND identifies calendar collection and components', () => {
  const xml = '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    + '<d:response><d:href>/calendars/user/work/</d:href><d:propstat><d:prop>'
    + '<d:displayname>Work</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype>'
    + '<c:supported-calendar-component-set><c:comp name="VEVENT"/><c:comp name="VTODO"/></c:supported-calendar-component-set>'
    + '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>';
  assert.deepEqual(Dav.parsePropfind(xml, collection), [{
    href: collection, name: 'Work', components: ['VEVENT', 'VTODO'],
  }]);
  assert.throws(() => Dav.parsePropfind('<d:multistatus xmlns:d="DAV:"/>', collection), /没有返回 CalDAV/u);
});

test('XML parser rejects DTDs, entities, malformed XML and oversized content', () => {
  assert.throws(() => Dav.parsePropfind('<!DOCTYPE a [<!ENTITY x "x">]><a/>', collection), /DTD/u);
  assert.throws(() => Dav.parsePropfind('<d:multistatus xmlns:d="DAV:"><d:response></d:multistatus>', collection), /XML/u);
  assert.throws(() => Dav.parsePropfind('<a>' + 'x'.repeat(2 * 1024 * 1024) + '</a>', collection), /过大/u);
});

test('resource URLs stay same-origin and under the collection', () => {
  assert.equal(Dav.resolveResourceUrl(collection, '/calendars/user/work/task.ics'), 'https://cal.example.test/calendars/user/work/task.ics');
  assert.throws(() => Dav.resolveResourceUrl(collection, 'https://evil.test/cal/task.ics'), /其他服务器/u);
  assert.throws(() => Dav.resolveResourceUrl(collection, '/calendars/user/private/task.ics'), /不属于/u);
  assert.throws(() => Dav.resolveResourceUrl(collection, '../private/task.ics'), /不属于/u);
  assert.throws(() => Dav.resolveResourceUrl(collection, '/calendars/user/work/task.ics?x=1'), /其他服务器/u);
});

test('sync-collection parses changes, removals, token and 507 paging', () => {
  const xml = '<d:multistatus xmlns:d="DAV:"><d:sync-token>urn:sync:2</d:sync-token>'
    + '<d:response><d:href>/calendars/user/work/a.ics</d:href><d:propstat><d:prop><d:getetag>"a"</d:getetag></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
    + '<d:response><d:href>/calendars/user/work/b.ics</d:href><d:status>HTTP/1.1 404 Not Found</d:status></d:response>'
    + '<d:response><d:href>/calendars/user/work/</d:href><d:status>HTTP/1.1 507 Insufficient Storage</d:status></d:response></d:multistatus>';
  assert.deepEqual(Dav.parseSyncCollection(xml, collection), {
    tokenRejected: false, syncToken: 'urn:sync:2',
    changes: [
      { href: 'https://cal.example.test/calendars/user/work/a.ics', removed: false, etag: '"a"' },
      { href: 'https://cal.example.test/calendars/user/work/b.ics', removed: true, etag: '' },
    ], truncated: true,
  });
});

test('sync-collection recognizes invalid token reports without accepting token advancement', () => {
  assert.deepEqual(Dav.parseSyncCollection('<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>', collection),
    { tokenRejected: true, changes: [], syncToken: '' });
  assert.throws(() => Dav.parseSyncCollection('<d:multistatus xmlns:d="DAV:"><d:sync-token>x</d:sync-token></d:multistatus>', collection), /令牌/u);
});

test('multiget parses calendar resources and verifies every requested href', () => {
  const href = '/calendars/user/work/event.ics';
  const parsed = Dav.parseCalendarResources(eventXml(href), collection, [href]);
  assert.equal(parsed.resources.length, 1);
  assert.equal(parsed.resources[0].href, 'https://cal.example.test/calendars/user/work/event.ics');
  assert.equal(parsed.resources[0].etag, '"v1"');
  assert.match(parsed.resources[0].calendarData, /UID:e1/u);
  assert.deepEqual(Dav.parseCalendarResources(
    '<d:multistatus xmlns:d="DAV:"><d:response><d:href>' + href + '</d:href><d:status>HTTP/1.1 404 Not Found</d:status></d:response></d:multistatus>',
    collection, [href],
  ).removedHrefs, ['https://cal.example.test/calendars/user/work/event.ics']);
});

test('multiget rejects missing and unrequested resources atomically', () => {
  assert.throws(() => Dav.parseCalendarResources(
    '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"/>', collection, ['/calendars/user/work/a.ics'],
  ), /缺少请求/u);
  assert.throws(() => Dav.parseCalendarResources(eventXml('/calendars/user/work/a.ics'), collection, ['/calendars/user/work/b.ics']), /不匹配/u);
  const weak = Dav.parseCalendarResources(eventXml('/calendars/user/work/a.ics', oneEvent, 'W/"weak"'), collection, ['/calendars/user/work/a.ics']);
  assert.equal(weak.resources[0].etag, 'W/"weak"');
});

test('strong ETag check excludes weak validators', () => {
  assert.equal(Dav.isStrongEtag('"v1"'), true);
  assert.equal(Dav.isStrongEtag('W/"v1"'), false);
  assert.equal(Dav.isStrongEtag('*'), false);
  assert.equal(Dav.isStrongEtag('"bad\u0001etag"'), false);
});
