'use strict';

const { isIP } = require('node:net');
const { DOMParser } = require('@xmldom/xmldom');

const DAV = 'DAV:';
const CALDAV = 'urn:ietf:params:xml:ns:caldav';
const MAX_URL_BYTES = 2048;
const MAX_XML_BYTES = 2 * 1024 * 1024;
const MAX_RESOURCES = 500;

class CalDavError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CalDavError';
  }
}

function normalizeUrl(value) {
  if (typeof value !== 'string' || !value.trim() || Buffer.byteLength(value.trim(), 'utf8') > MAX_URL_BYTES) {
    throw new CalDavError('CalDAV 地址不能为空，且不能超过 2048 字节。');
  }
  const source = value.trim();
  if (/[\s\u0000-\u001f\u007f]/u.test(source)) throw new CalDavError('CalDAV 地址不能包含空格或控制字符。');
  let url;
  try { url = new URL(source); } catch { throw new CalDavError('CalDAV 地址格式无效。'); }
  if (!['https:', 'http:'].includes(url.protocol) || !url.hostname || url.username || url.password
    || /^[a-z][a-z0-9+.-]*:\/\/[^/?#]*@/iu.test(source)) {
    throw new CalDavError('CalDAV 地址须为 HTTPS，并且不能把账号密码写在地址中。');
  }
  url.hash = '';
  if (url.search) throw new CalDavError('CalDAV 日历集地址不能包含查询参数。');
  const host = url.hostname.toLowerCase().replace(/\.$/u, '');
  const loopback = host === 'localhost' || host.endsWith('.localhost') || host === '[::1]'
    || (isIP(host) === 4 && Number(host.split('.')[0]) === 127)
    || (isIP(host) === 6 && host === '::1');
  if (url.protocol !== 'https:' && !loopback) {
    throw new CalDavError('远程 CalDAV 地址必须使用 HTTPS。');
  }
  const normalized = url.href;
  if (Buffer.byteLength(normalized, 'utf8') > MAX_URL_BYTES) throw new CalDavError('CalDAV 地址不能超过 2048 字节。');
  return { url: normalized, host };
}

function validateCredentials(username, password) {
  if (typeof username !== 'string' || typeof password !== 'string'
    || Buffer.byteLength(username, 'utf8') > 256 || Buffer.byteLength(password, 'utf8') > 1024
    || /[:\r\n\u0000-\u001f\u007f]/u.test(username)
    || /[\u0000-\u001f\u007f]/u.test(password)
    || Boolean(username) !== Boolean(password)) {
    throw new CalDavError('CalDAV 账号或密码无效；如服务器需要登录，请同时填写。');
  }
  return { username, password };
}

function authorizationHeader(username, password) {
  const credentials = validateCredentials(username, password);
  return credentials.username ? 'Basic ' + Buffer.from(credentials.username + ':' + credentials.password, 'utf8').toString('base64') : '';
}

function propfindBody() {
  return '<?xml version="1.0" encoding="utf-8"?>'
    + '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    + '<d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/></d:prop>'
    + '</d:propfind>';
}

function syncCollectionBody(token = '') {
  if (typeof token !== 'string' || Buffer.byteLength(token, 'utf8') > 4096
    || /[\u0000-\u001f\u007f]/u.test(token) || (token && !/^[a-z][a-z0-9+.-]*:/iu.test(token))) {
    throw new CalDavError('CalDAV 同步令牌无效。');
  }
  return '<?xml version="1.0" encoding="utf-8"?>'
    + '<d:sync-collection xmlns:d="DAV:"><d:sync-token>'
    + escapeXml(token) + '</d:sync-token><d:sync-level>1</d:sync-level>'
    + '<d:prop><d:getetag/></d:prop></d:sync-collection>';
}

function fullQueryBody() {
  return '<?xml version="1.0" encoding="utf-8"?>'
    + '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    + '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
    + '<c:filter><c:comp-filter name="VCALENDAR"/></c:filter></c:calendar-query>';
}

function multigetBody(hrefs) {
  if (!Array.isArray(hrefs) || hrefs.length < 1 || hrefs.length > MAX_RESOURCES) {
    throw new CalDavError('CalDAV 多资源请求无效或超过 500 项。');
  }
  const unique = new Set();
  const elements = hrefs.map((href) => {
    if (typeof href !== 'string' || !href || href.length > 4096 || unique.has(href)) {
      throw new CalDavError('CalDAV 多资源请求包含无效或重复地址。');
    }
    unique.add(href);
    return '<d:href>' + escapeXml(href) + '</d:href>';
  });
  return '<?xml version="1.0" encoding="utf-8"?>'
    + '<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    + '<d:prop><d:getetag/><c:calendar-data/></d:prop>' + elements.join('') + '</c:calendar-multiget>';
}

function escapeXml(value) {
  return String(value).replace(/&/gu, '&amp;').replace(/</gu, '&lt;')
    .replace(/>/gu, '&gt;').replace(/"/gu, '&quot;').replace(/'/gu, '&apos;');
}

function parseXml(xml) {
  if (typeof xml !== 'string' || !xml.trim() || Buffer.byteLength(xml, 'utf8') > MAX_XML_BYTES
    || /<!DOCTYPE|<!ENTITY/iu.test(xml)) {
    throw new CalDavError('CalDAV XML 为空、过大或包含禁止的 DTD/实体声明。');
  }
  let parseError = false;
  let doc;
  try {
    doc = new DOMParser({ onError: () => { parseError = true; } })
      .parseFromString(xml, 'application/xml');
  } catch {
    throw new CalDavError('CalDAV 服务器返回了无效 XML。');
  }
  if (parseError || !doc.documentElement || doc.doctype || doc.documentElement.localName === 'parsererror') {
    throw new CalDavError('CalDAV 服务器返回了无效或不安全的 XML。');
  }
  return doc;
}

function directChildren(node, namespace, name) {
  const result = [];
  for (let child = node && node.firstChild; child; child = child.nextSibling) {
    if (child.nodeType === 1 && child.namespaceURI === namespace && child.localName === name) result.push(child);
  }
  return result;
}

function child(node, namespace, name) {
  return directChildren(node, namespace, name)[0] || null;
}

function text(node, namespace, name) {
  const found = child(node, namespace, name);
  return found ? String(found.textContent || '').trim() : '';
}

function statusCode(value) {
  const match = String(value || '').match(/\s(\d{3})(?:\s|$)/u);
  return match ? Number(match[1]) : 0;
}

function responseNodes(doc) {
  const root = doc.documentElement;
  if (root.namespaceURI === DAV && root.localName === 'response') return [root];
  if (root.namespaceURI !== DAV || root.localName !== 'multistatus') {
    throw new CalDavError('CalDAV 服务器没有返回 DAV Multi-Status 响应。');
  }
  return directChildren(root, DAV, 'response');
}

function parsePropfind(xml, collectionUrl) {
  const doc = parseXml(xml);
  const base = new URL(normalizeUrl(collectionUrl).url);
  const calendars = [];
  for (const response of responseNodes(doc).slice(0, 100)) {
    const href = text(response, DAV, 'href');
    const url = resolveResourceUrl(base.href, href, { allowCollection: true });
    const status = statusCode(text(response, DAV, 'status'));
    if (status && status !== 200) continue;
    for (const propstat of directChildren(response, DAV, 'propstat')) {
      if (statusCode(text(propstat, DAV, 'status')) !== 200) continue;
      const props = child(propstat, DAV, 'prop');
      if (!props) continue;
      const resourceType = child(props, DAV, 'resourcetype');
      const isCalendar = Boolean(resourceType && child(resourceType, CALDAV, 'calendar'));
      if (!isCalendar) continue;
      const componentSet = child(props, CALDAV, 'supported-calendar-component-set');
      const components = componentSet
        ? directChildren(componentSet, CALDAV, 'comp').map((item) => String(item.getAttribute('name') || '').toUpperCase())
          .filter((item) => item === 'VEVENT' || item === 'VTODO')
        : ['VEVENT', 'VTODO'];
      calendars.push({
        href: url,
        name: text(props, DAV, 'displayname').slice(0, 160) || 'CalDAV 日历',
        components: [...new Set(components)].sort(),
      });
    }
  }
  if (!calendars.length) throw new CalDavError('该地址没有返回 CalDAV 日历集；请填写日历集专属地址。');
  return calendars;
}

function sameOrigin(left, right) {
  return left.protocol.toLowerCase() === right.protocol.toLowerCase()
    && left.hostname.toLowerCase() === right.hostname.toLowerCase()
    && (left.port || defaultPort(left.protocol)) === (right.port || defaultPort(right.protocol));
}

function defaultPort(protocol) {
  return protocol === 'https:' ? '443' : '80';
}

function resolveResourceUrl(collectionUrl, href, options = {}) {
  if (typeof href !== 'string' || !href.trim() || href.length > 4096) {
    throw new CalDavError('CalDAV 服务器返回了无效资源地址。');
  }
  const collection = new URL(normalizeUrl(collectionUrl).url);
  const base = new URL(collection.href.endsWith('/') ? collection.href : collection.href + '/');
  let target;
  try { target = new URL(href.trim(), base); } catch { throw new CalDavError('CalDAV 资源地址无效。'); }
  if (!sameOrigin(collection, target) || target.username || target.password || target.search || target.hash) {
    throw new CalDavError('CalDAV 资源地址跳到其他服务器或包含不允许的参数。');
  }
  let targetPath;
  let collectionPath;
  try { targetPath = decodeURIComponent(target.pathname); collectionPath = decodeURIComponent(collection.pathname); }
  catch { throw new CalDavError('CalDAV 资源路径编码无效。'); }
  if (/[\\\u0000-\u001f\u007f]/u.test(targetPath)) throw new CalDavError('CalDAV 资源路径包含不允许的字符。');
  const normalizePath = (value) => {
    const parts = [];
    value.split('/').forEach((part) => {
      if (!part || part === '.') return;
      if (part === '..') parts.pop();
      else parts.push(part);
    });
    return '/' + parts.join('/') + (value.endsWith('/') ? '/' : '');
  };
  const normalizedTarget = normalizePath(targetPath);
  const normalizedCollection = normalizePath(collectionPath);
  const inCollection = options.allowCollection && normalizedTarget.replace(/\/+$/u, '') === normalizedCollection.replace(/\/+$/u, '');
  if (!inCollection && !normalizedTarget.startsWith(normalizedCollection.endsWith('/') ? normalizedCollection : normalizedCollection + '/')) {
    throw new CalDavError('CalDAV 资源不属于当前日历集。');
  }
  return target.href;
}

function parseSyncCollection(xml, collectionUrl) {
  const doc = parseXml(xml);
  const root = doc.documentElement;
  if (root.namespaceURI === DAV && root.localName === 'error'
    && root.getElementsByTagNameNS(DAV, 'valid-sync-token').length) {
    return { tokenRejected: true, changes: [], syncToken: '' };
  }
  if (root.namespaceURI !== DAV || root.localName !== 'multistatus') {
    throw new CalDavError('CalDAV 服务器没有返回 Multi-Status 增量结果。');
  }
  const tokens = directChildren(root, DAV, 'sync-token');
  if (tokens.length !== 1) throw new CalDavError('CalDAV 增量结果缺少唯一同步令牌。');
  const syncToken = String(tokens[0].textContent || '').trim();
  if (!syncToken || Buffer.byteLength(syncToken, 'utf8') > 4096 || /[\u0000-\u001f\u007f]/u.test(syncToken)
    || !/^[a-z][a-z0-9+.-]*:/iu.test(syncToken)) throw new CalDavError('CalDAV 同步令牌无效。');
  const collection = normalizeUrl(collectionUrl).url;
  const changes = [];
  let truncated = false;
  const seen = new Set();
  for (const response of directChildren(root, DAV, 'response')) {
    const hrefText = text(response, DAV, 'href');
    const responseStatus = statusCode(text(response, DAV, 'status'));
    if (responseStatus === 507) {
      const target = resolveResourceUrl(collection, hrefText, { allowCollection: true });
      const url = new URL(target);
      const base = new URL(collection);
      if (!sameOrigin(url, base) || url.pathname.replace(/\/+$/u, '') !== base.pathname.replace(/\/+$/u, '')) {
        throw new CalDavError('CalDAV 分页地址无效。');
      }
      truncated = true;
      continue;
    }
    const href = resolveResourceUrl(collection, hrefText);
    if (seen.has(href)) throw new CalDavError('CalDAV 增量结果包含重复资源。');
    seen.add(href);
    if (responseStatus === 404) {
      changes.push({ href, removed: true, etag: '' });
      continue;
    }
    if (responseStatus && responseStatus !== 200) throw new CalDavError('CalDAV 增量资源返回 HTTP ' + responseStatus + '。');
    let etag = '';
    for (const propstat of directChildren(response, DAV, 'propstat')) {
      const code = statusCode(text(propstat, DAV, 'status'));
      const props = child(propstat, DAV, 'prop');
      if (code === 200 && props) etag = etag || text(props, DAV, 'getetag');
      else if (code && code !== 403 && code !== 404) throw new CalDavError('CalDAV 增量属性返回 HTTP ' + code + '。');
    }
    if (etag.length > 1024 || /[\u0000-\u001f\u007f]/u.test(etag)) throw new CalDavError('CalDAV ETag 无效。');
    changes.push({ href, removed: false, etag });
    if (changes.length > MAX_RESOURCES) throw new CalDavError('一次最多处理 500 个 CalDAV 资源变更。');
  }
  return { tokenRejected: false, syncToken, changes, truncated };
}

function parseCalendarResources(xml, collectionUrl, requestedHrefs = null) {
  const doc = parseXml(xml);
  const collection = normalizeUrl(collectionUrl).url;
  const requested = requestedHrefs ? new Set(requestedHrefs.map((href) => resolveResourceUrl(collection, href))) : null;
  if (requested && requested.size !== requestedHrefs.length) throw new CalDavError('CalDAV 请求资源地址重复。');
  const resources = new Map();
  const removed = new Set();
  let totalBytes = 0;
  for (const response of responseNodes(doc)) {
    const href = resolveResourceUrl(collection, text(response, DAV, 'href'));
    if (requested && !requested.has(href)) throw new CalDavError('CalDAV 响应地址与请求不匹配。');
    if (resources.has(href) || removed.has(href)) throw new CalDavError('CalDAV 响应包含重复资源。');
    const status = statusCode(text(response, DAV, 'status'));
    if (status === 404) { removed.add(href); continue; }
    if (status && status !== 200) throw new CalDavError('CalDAV 资源返回 HTTP ' + status + '。');
    let etag = '';
    let calendarData = '';
    for (const propstat of directChildren(response, DAV, 'propstat')) {
      const code = statusCode(text(propstat, DAV, 'status'));
      const props = child(propstat, DAV, 'prop');
      if (code === 200 && props) {
        etag = etag || text(props, DAV, 'getetag');
        const data = child(props, CALDAV, 'calendar-data');
        if (data) {
          for (let node = data.firstChild; node; node = node.nextSibling) {
            if (node.nodeType !== 3) throw new CalDavError('CalDAV 日历数据包含不支持的嵌套内容。');
          }
          calendarData = String(data.textContent || '');
        }
      } else if (code && code !== 403 && code !== 404) throw new CalDavError('CalDAV 资源属性返回 HTTP ' + code + '。');
    }
    const bytes = Buffer.byteLength(calendarData, 'utf8');
    totalBytes += bytes;
    if (!calendarData.trim() || bytes > MAX_XML_BYTES || totalBytes > MAX_XML_BYTES
      || etag.length > 1024 || /[\u0000-\u001f\u007f]/u.test(etag)) {
      throw new CalDavError('CalDAV 资源数据为空、过大或 ETag 无效。');
    }
    resources.set(href, { href, etag, calendarData });
  }
  if (requested && (resources.size + removed.size !== requested.size
    || [...requested].some((href) => !resources.has(href) && !removed.has(href)))) {
    throw new CalDavError('CalDAV 响应缺少请求资源，未应用同步。');
  }
  return { resources: [...resources.values()], removedHrefs: [...removed] };
}

function isStrongEtag(value) {
  return typeof value === 'string' && value.length <= 1024 && /^"[^"\r\n]*"$/u.test(value)
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

module.exports = {
  CalDavError,
  MAX_RESOURCES,
  normalizeUrl,
  validateCredentials,
  authorizationHeader,
  propfindBody,
  syncCollectionBody,
  fullQueryBody,
  multigetBody,
  parsePropfind,
  resolveResourceUrl,
  parseSyncCollection,
  parseCalendarResources,
  isStrongEtag,
};
