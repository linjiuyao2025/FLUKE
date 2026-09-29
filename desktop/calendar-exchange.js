(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('ical.js'), require('rrule'));
  else root.WanxiangCalendar = factory(root.ICAL, root.rrule);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (ICAL, RRuleLib) {
  'use strict';

  const { RRule, RRuleSet } = RRuleLib;

  const MAX_ICS_BYTES = 1024 * 1024;
  const MAX_COMPONENTS = 500;
  const MAX_EVENT_DAYS = 31;
  const MAX_EXPANSIONS_PER_DAY = 5000;
  const MIN_SUPPORTED_YEAR = 1900;
  const MAX_SUPPORTED_YEAR = 2100;
  const occurrenceCache = new Map();

  class CalendarExchangeError extends Error {
    constructor(message) { super(message); this.name = 'CalendarExchangeError'; }
  }

  function utf8Length(value) {
    if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(value).length;
    return Buffer.byteLength(value, 'utf8');
  }

  function dateKey(year, month, day) {
    return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }

  function parseDay(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) throw new CalendarExchangeError('日历日期格式无效。');
    const [year, month, day] = value.split('-').map(Number);
    const check = new Date(year, month - 1, day);
    if (check.getFullYear() !== year || check.getMonth() !== month - 1 || check.getDate() !== day) {
      throw new CalendarExchangeError('日历日期无效。');
    }
    return { year, month, day };
  }

  function parseCalendarRoot(text, maxBytes = MAX_ICS_BYTES) {
    if (typeof text !== 'string' || !text.trim()) throw new CalendarExchangeError('ICS 文件为空。');
    if (utf8Length(text) > maxBytes) throw new CalendarExchangeError(
      maxBytes === MAX_ICS_BYTES ? 'ICS 文件不能超过 1 MB。' : 'CalDAV 日历数据超过允许的大小。',
    );
    let raw;
    try { raw = ICAL.parse(text); } catch { throw new CalendarExchangeError('ICS 文件格式无法解析。'); }
    const root = new ICAL.Component(raw);
    if (root.name !== 'vcalendar' || root.getFirstPropertyValue('version') !== '2.0') {
      throw new CalendarExchangeError('请选择有效的 iCalendar 2.0 文件。');
    }
    return root;
  }

  function timezoneOffsetSeconds(epochSeconds, formatter) {
    const date = new Date(epochSeconds * 1000);
    const values = {};
    formatter.formatToParts(date).forEach(part => { if (part.type !== 'literal') values[part.type] = Number(part.value); });
    let hour = values.hour;
    if (hour === 24) hour = 0;
    const wallAsUtc = Date.UTC(values.year, values.month - 1, values.day, hour, values.minute, values.second);
    return Math.round(wallAsUtc / 1000) - epochSeconds;
  }

  function localFields(epochSeconds, formatter) {
    const values = {};
    formatter.formatToParts(new Date(epochSeconds * 1000)).forEach(part => { if (part.type !== 'literal') values[part.type] = Number(part.value); });
    return { year: values.year, month: values.month, day: values.day, hour: values.hour === 24 ? 0 : values.hour, minute: values.minute, second: values.second };
  }

  function formatIcsDateTime(value) {
    return `${String(value.year).padStart(4, '0')}${String(value.month).padStart(2, '0')}${String(value.day).padStart(2, '0')}T${String(value.hour).padStart(2, '0')}${String(value.minute).padStart(2, '0')}${String(value.second).padStart(2, '0')}`;
  }

  function formatUtcOffset(seconds) {
    const sign = seconds < 0 ? '-' : '+';
    let value = Math.abs(seconds);
    const hours = Math.floor(value / 3600); value -= hours * 3600;
    const minutes = Math.floor(value / 60); value -= minutes * 60;
    return `${sign}${String(hours).padStart(2, '0')}${String(minutes).padStart(2, '0')}${value ? String(value).padStart(2, '0') : ''}`;
  }

  function timezoneYears(root, tzid) {
    let first = MAX_SUPPORTED_YEAR;
    let last = MIN_SUPPORTED_YEAR;
    let recurringWithoutUntil = false;
    ['vevent', 'vtodo'].forEach(componentName => root.getAllSubcomponents(componentName).forEach(component => {
      component.getAllProperties().forEach(property => {
        if (property.getParameter('tzid') !== tzid) return;
        const firstValue = property.getFirstValue();
        if (firstValue && Number.isInteger(firstValue.year)) {
          first = Math.min(first, firstValue.year);
          last = Math.max(last, firstValue.year);
        }
      });
      const rule = component.getFirstPropertyValue('rrule');
      if (rule) {
        if (rule.until && Number.isInteger(rule.until.year)) last = Math.max(last, rule.until.year);
        else recurringWithoutUntil = true;
      }
    }));
    if (first === MAX_SUPPORTED_YEAR) first = new Date().getFullYear();
    if (recurringWithoutUntil) last = MAX_SUPPORTED_YEAR;
    return {
      first: Math.max(MIN_SUPPORTED_YEAR, first - 1),
      last: Math.min(MAX_SUPPORTED_YEAR, Math.max(first, last) + 1),
    };
  }

  function makeIanaTimezoneComponent(tzid, years) {
    if (/[\r\n\u0000-\u001f\u007f]/.test(tzid)) throw new CalendarExchangeError('ICS 时区标识无效。');
    let formatter;
    try {
      formatter = new Intl.DateTimeFormat('en-US-u-ca-gregory-nu-latn', {
        timeZone: tzid, year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
      });
      formatter.format(new Date(0));
    } catch { throw new CalendarExchangeError(`ICS 使用了本机无法识别的时区：${tzid}`); }

    const firstEpoch = Math.floor(Date.UTC(years.first, 0, 1) / 1000);
    const afterLastEpoch = Math.floor(Date.UTC(years.last + 1, 0, 1) / 1000);
    let previousEpoch = firstEpoch;
    let previousOffset = timezoneOffsetSeconds(previousEpoch, formatter);
    const baseline = localFields(previousEpoch, formatter);
    const observances = [`BEGIN:STANDARD\r\nDTSTART:${formatIcsDateTime(baseline)}\r\nTZOFFSETFROM:${formatUtcOffset(previousOffset)}\r\nTZOFFSETTO:${formatUtcOffset(previousOffset)}\r\nEND:STANDARD`];
    const stepSeconds = 24 * 60 * 60;

    for (let sampleEpoch = Math.min(afterLastEpoch, previousEpoch + stepSeconds); sampleEpoch <= afterLastEpoch; sampleEpoch = Math.min(afterLastEpoch, sampleEpoch + stepSeconds)) {
      const sampleOffset = timezoneOffsetSeconds(sampleEpoch, formatter);
      if (sampleOffset !== previousOffset) {
        let low = previousEpoch;
        let high = sampleEpoch;
        while (high - low > 1) {
          const middle = Math.floor((low + high) / 2);
          if (timezoneOffsetSeconds(middle, formatter) === previousOffset) low = middle;
          else high = middle;
        }
        const nextOffset = timezoneOffsetSeconds(high, formatter);
        const localAfter = localFields(high, formatter);
        const kind = nextOffset > previousOffset ? 'DAYLIGHT' : 'STANDARD';
        observances.push(`BEGIN:${kind}\r\nDTSTART:${formatIcsDateTime(localAfter)}\r\nTZOFFSETFROM:${formatUtcOffset(previousOffset)}\r\nTZOFFSETTO:${formatUtcOffset(nextOffset)}\r\nEND:${kind}`);
        previousOffset = nextOffset;
      }
      previousEpoch = sampleEpoch;
      if (sampleEpoch === afterLastEpoch) break;
    }

    const source = `BEGIN:VTIMEZONE\r\nTZID:${tzid}\r\n${observances.join('\r\n')}\r\nEND:VTIMEZONE`;
    try { return new ICAL.Component(ICAL.parse(source)); }
    catch { throw new CalendarExchangeError(`无法准备 ICS 时区：${tzid}`); }
  }

  function registerCalendarTimezones(root) {
    const timezoneComponents = root.getAllSubcomponents('vtimezone');
    const registered = new Set();
    timezoneComponents.forEach(component => {
      const tzid = component.getFirstPropertyValue('tzid');
      if (typeof tzid !== 'string' || !tzid || registered.has(tzid)) return;
      try { ICAL.TimezoneService.register(component); }
      catch { throw new CalendarExchangeError(`ICS 时区定义无效：${tzid}`); }
      registered.add(tzid);
    });
    const needed = new Map();
    ['vevent', 'vtodo'].forEach(componentName => root.getAllSubcomponents(componentName).forEach(component => {
      component.getAllProperties().forEach(property => {
        const tzid = property.getParameter('tzid');
        if (typeof tzid !== 'string' || !tzid || registered.has(tzid)) return;
        const bounds = timezoneYears(root, tzid);
        const prior = needed.get(tzid);
        needed.set(tzid, prior ? { first: Math.min(prior.first, bounds.first), last: Math.max(prior.last, bounds.last) } : bounds);
      });
    }));
    needed.forEach((years, tzid) => {
      const component = makeIanaTimezoneComponent(tzid, years);
      root.addSubcomponent(component);
      try { ICAL.TimezoneService.register(component); }
      catch { throw new CalendarExchangeError(`无法载入 ICS 时区：${tzid}`); }
    });
  }

  function calendarName(root, fallback = '外部日历') {
    const name = root.getFirstPropertyValue('x-wr-calname');
    return typeof name === 'string' && name.trim() ? name.trim().slice(0, 80) : fallback;
  }

  function checkedEvents(root) {
    const components = root.getAllSubcomponents('vevent');
    if (components.length > MAX_COMPONENTS) throw new CalendarExchangeError('一个日历最多导入 500 个事件（含重复例外）。');
    const byUid = new Map();
    components.forEach(component => {
      const uid = component.getFirstPropertyValue('uid');
      if (typeof uid !== 'string' || !uid.trim() || uid.length > 512) throw new CalendarExchangeError('ICS 事件缺少有效 UID。');
      const group = byUid.get(uid) || [];
      group.push(component);
      byUid.set(uid, group);
    });
    const events = [];
    byUid.forEach((group, uid) => {
      const masters = group.filter(component => !component.hasProperty('recurrence-id'));
      if (masters.length !== 1) throw new CalendarExchangeError(`ICS 中 UID ${uid} 的主事件缺失或重复。`);
      const master = masters[0];
      if (master.hasProperty('exrule')) throw new CalendarExchangeError('此日历使用了不支持的 EXRULE 重复排除规则。');
      const start = master.getFirstPropertyValue('dtstart');
      if (!(start instanceof ICAL.Time)) throw new CalendarExchangeError(`ICS 事件 ${uid} 缺少有效开始时间。`);
      const rule = master.getFirstPropertyValue('rrule');
      if (rule && !['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'].includes(String(rule.freq || '').toUpperCase())) {
        throw new CalendarExchangeError('日历仅支持按天、周、月或年重复的事件。');
      }
      const recurrenceValueCount = ['rdate', 'exdate'].reduce((total, propertyName) => total + master.getAllProperties(propertyName).reduce((subtotal, property) => subtotal + property.getValues().length, 0), 0);
      if (recurrenceValueCount > 2000) throw new CalendarExchangeError(`ICS 事件 ${uid} 的重复日期数量过多。`);
      const event = new ICAL.Event(master, { exceptions: group.filter(component => component !== master) });
      const duration = event.endDate.toJSDate().getTime() - event.startDate.toJSDate().getTime();
      if (!Number.isFinite(duration) || duration < 0 || duration > MAX_EVENT_DAYS * 24 * 60 * 60 * 1000) {
        throw new CalendarExchangeError(`ICS 事件 ${uid} 的持续时间无效或超过 31 天。`);
      }
      events.push({ uid, component: master, event });
    });
    return events;
  }

  function todoDateTime(value, uid, propertyName) {
    if (value === undefined || value === null) return null;
    if (!(value instanceof ICAL.Time)) throw new CalendarExchangeError(`ICS 待办 ${uid} 的 ${propertyName} 日期无效。`);
    let date;
    let time = '';
    let instant;
    if (value.isDate) {
      date = dateKey(value.year, value.month, value.day);
      instant = new Date(value.year, value.month - 1, value.day).getTime();
    } else {
      const jsDate = value.toJSDate();
      if (!Number.isFinite(jsDate.getTime())) throw new CalendarExchangeError(`ICS 待办 ${uid} 的 ${propertyName} 日期无效。`);
      date = dateKey(jsDate.getFullYear(), jsDate.getMonth() + 1, jsDate.getDate());
      time = `${String(jsDate.getHours()).padStart(2, '0')}:${String(jsDate.getMinutes()).padStart(2, '0')}`;
      instant = jsDate.getTime();
    }
    return { date, time, instant };
  }

  function checkedTodos(root) {
    const components = root.getAllSubcomponents('vtodo');
    if (components.length > MAX_COMPONENTS) throw new CalendarExchangeError('一个日历最多导入 500 个事件和待办。');
    const seen = new Set();
    return components.map(component => {
      const uid = component.getFirstPropertyValue('uid');
      if (typeof uid !== 'string' || !uid.trim() || uid.length > 512 || seen.has(uid)) {
        throw new CalendarExchangeError('ICS 待办缺少有效 UID 或 UID 重复。');
      }
      seen.add(uid);
      if (['rrule', 'rdate', 'exdate', 'exrule', 'recurrence-id'].some(name => component.hasProperty(name))) {
        throw new CalendarExchangeError(`ICS 待办 ${uid} 使用了暂不支持的重复规则。`);
      }

      const titleValue = component.getFirstPropertyValue('summary');
      const title = typeof titleValue === 'string' ? titleValue.trim() : '';
      if (!title) throw new CalendarExchangeError(`ICS 待办 ${uid} 缺少标题。`);
      const status = String(component.getFirstPropertyValue('status') || 'NEEDS-ACTION').toUpperCase();
      if (!['NEEDS-ACTION', 'IN-PROCESS', 'COMPLETED', 'CANCELLED'].includes(status)) {
        throw new CalendarExchangeError(`ICS 待办 ${uid} 的状态无效。`);
      }
      const rawPriority = component.getFirstPropertyValue('priority');
      const priorityNumber = rawPriority === undefined || rawPriority === null || rawPriority === '' ? 0 : Number(rawPriority);
      if (!Number.isInteger(priorityNumber) || priorityNumber < 0 || priorityNumber > 9) {
        throw new CalendarExchangeError(`ICS 待办 ${uid} 的优先级无效。`);
      }
      const rawPercent = component.getFirstPropertyValue('percent-complete');
      const percentComplete = rawPercent === undefined || rawPercent === null || rawPercent === '' ? 0 : Number(rawPercent);
      if (!Number.isInteger(percentComplete) || percentComplete < 0 || percentComplete > 100) {
        throw new CalendarExchangeError(`ICS 待办 ${uid} 的完成百分比无效。`);
      }
      const start = todoDateTime(component.getFirstPropertyValue('dtstart'), uid, 'DTSTART');
      const due = todoDateTime(component.getFirstPropertyValue('due'), uid, 'DUE');
      const completed = todoDateTime(component.getFirstPropertyValue('completed'), uid, 'COMPLETED');
      const rawUrl = component.getFirstPropertyValue('url');
      let url = '';
      if (rawUrl !== undefined && rawUrl !== null && String(rawUrl).trim()) {
        url = String(rawUrl).trim();
        try {
          const parsed = new URL(url);
          if (!['http:', 'https:'].includes(parsed.protocol) || url.length > 2048) throw new Error('unsafe URL');
        } catch { throw new CalendarExchangeError(`ICS 待办 ${uid} 的链接无效。`); }
      }
      const descriptionValue = component.getFirstPropertyValue('description');
      const cancelled = status === 'CANCELLED';
      const done = !cancelled && (status === 'COMPLETED' || percentComplete === 100);
      return {
        uid,
        title: title.slice(0, 160),
        description: typeof descriptionValue === 'string' ? descriptionValue.slice(0, 2000) : '',
        url,
        date: (due || start)?.date || '',
        time: start?.time || '',
        priority: priorityNumber >= 1 && priorityNumber <= 3 ? 'high' : priorityNumber >= 7 ? 'low' : 'normal',
        status: cancelled ? 'cancelled' : done ? 'done' : status === 'IN-PROCESS' || percentComplete > 0 ? 'inprogress' : 'todo',
        done,
        cancelled,
        percentComplete,
        completedAt: completed ? new Date(completed.instant).toISOString() : '',
      };
    });
  }

  function parseIcs(text, fallbackName, options = {}) {
    const allowEmpty = Boolean(options && options.allowEmpty === true);
    let root = parseCalendarRoot(text);
    const eventComponentCount = root.getAllSubcomponents('vevent').length;
    const todoComponentCount = root.getAllSubcomponents('vtodo').length;
    const count = eventComponentCount + todoComponentCount;
    if (count > MAX_COMPONENTS) throw new CalendarExchangeError('一个日历最多导入 500 个事件和待办。');
    if (!count && !allowEmpty) throw new CalendarExchangeError('文件中没有可导入的 VEVENT 事件或 VTODO 待办。');
    registerCalendarTimezones(root);
    // ICAL.Property caches its first parsed date value. Parse again after IANA
    // zones have been registered so the cached values do not keep the local zone.
    root = parseCalendarRoot(text);
    const events = checkedEvents(root);
    const todos = checkedTodos(root);
    if (!events.length && !todos.length && !allowEmpty) throw new CalendarExchangeError('文件中没有可导入的 VEVENT 事件或 VTODO 待办。');
    return { name: calendarName(root, fallbackName), eventCount: events.length, todoCount: todos.length, componentCount: count, todos };
  }

  function todoResourceUids(text) {
    const root = parseCalendarRoot(text, 2 * 1024 * 1024);
    return root.getAllSubcomponents('vtodo').map(component => String(component.getFirstPropertyValue('uid') || ''));
  }

  function unfoldedLines(text) {
    const logical = [];
    text.replace(/\r\n/gu, '\n').replace(/\r/gu, '\n').split('\n').forEach(line => {
      if (/^[ \t]/u.test(line) && logical.length) logical[logical.length - 1] += line.slice(1);
      else if (line) logical.push(line);
    });
    return logical;
  }

  function contentLineName(line) {
    let quoted = false, escaped = false;
    for (let index = 0; index < line.length; index++) {
      const character = line[index];
      if (escaped) escaped = false;
      else if (character === '\\') escaped = true;
      else if (character === '"') quoted = !quoted;
      else if (character === ':' && !quoted) {
        const name = line.slice(0, index).split(';', 1)[0];
        return /^[A-Z0-9-]+$/iu.test(name) ? name.toUpperCase() : '';
      }
    }
    return '';
  }

  function foldContentLine(line, maxOctets = 75) {
    const folded = [];
    let part = '', size = 0, limit = maxOctets;
    for (const character of line) {
      const bytes = utf8Length(character);
      if (part && size + bytes > limit) {
        folded.push(part);
        part = ' ';
        size = 1;
        limit = maxOctets;
      }
      part += character;
      size += bytes;
    }
    folded.push(part);
    return folded;
  }

  function updateVtodoCompletion(calendarData, uid, done, now = new Date()) {
    if (typeof calendarData !== 'string' || utf8Length(calendarData) > 2 * 1024 * 1024
      || typeof uid !== 'string' || !uid || uid.length > 255 || /[\u0000-\u001f\u007f]/u.test(uid)
      || typeof done !== 'boolean') {
      throw new CalendarExchangeError('CalDAV 待办回写信息无效或超过限制。');
    }
    const root = parseCalendarRoot(calendarData, 2 * 1024 * 1024);
    const todos = root.getAllSubcomponents('vtodo');
    if (todos.length !== 1 || String(todos[0].getFirstPropertyValue('uid') || '') !== uid) {
      throw new CalendarExchangeError('CalDAV 待办 UID 与资源不匹配，无法安全回写。');
    }
    if (['rrule', 'rdate', 'exdate', 'exrule', 'recurrence-id'].some(name => todos[0].hasProperty(name))) {
      throw new CalendarExchangeError('循环 CalDAV 待办暂不支持完成状态回写。');
    }
    const instant = new Date(now);
    if (!Number.isFinite(instant.getTime())) throw new CalendarExchangeError('CalDAV 完成时间无效。');
    const stamp = instant.toISOString().replace(/[-:]/gu, '').replace(/\.\d{3}Z$/u, 'Z');
    const lines = unfoldedLines(calendarData.replace(/^\uFEFF/u, ''));
    let start = -1, end = -1, depth = 0;
    const blocks = [];
    for (let index = 0; index < lines.length; index++) {
      const upper = lines[index].toUpperCase();
      if (depth === 0 && upper === 'BEGIN:VTODO') {
        start = index;
        depth = 1;
      } else if (depth > 0 && upper.startsWith('BEGIN:')) depth++;
      else if (depth > 0 && upper.startsWith('END:')) {
        depth--;
        if (depth === 0) {
          end = index;
          blocks.push([start, end]);
          start = end = -1;
        }
      }
    }
    if (depth !== 0 || blocks.length !== 1) throw new CalendarExchangeError('CalDAV 待办组件无法唯一定位，未执行回写。');
    const [blockStart, blockEnd] = blocks[0];
    const kept = [];
    let nested = 0, sequence = 0;
    for (const line of lines.slice(blockStart + 1, blockEnd)) {
      const upper = line.toUpperCase();
      if (upper.startsWith('BEGIN:')) { nested++; kept.push(line); continue; }
      if (upper.startsWith('END:') && nested) { nested--; kept.push(line); continue; }
      if (nested) { kept.push(line); continue; }
      const name = contentLineName(line);
      if (name === 'SEQUENCE') {
        const value = line.slice(line.indexOf(':') + 1);
        if (!/^\d+$/u.test(value) || !Number.isSafeInteger(Number(value))) {
          throw new CalendarExchangeError('CalDAV VTODO 的 SEQUENCE 无效，拒绝回写。');
        }
        sequence = Math.max(sequence, Number(value));
      }
      if (['STATUS', 'PERCENT-COMPLETE', 'COMPLETED', 'DTSTAMP', 'LAST-MODIFIED', 'SEQUENCE'].includes(name)) continue;
      kept.push(line);
    }
    const completion = [
      `STATUS:${done ? 'COMPLETED' : 'NEEDS-ACTION'}`,
      `PERCENT-COMPLETE:${done ? 100 : 0}`,
    ];
    if (done) completion.push(`COMPLETED:${stamp}`);
    completion.push(`DTSTAMP:${stamp}`, `LAST-MODIFIED:${stamp}`, `SEQUENCE:${sequence + 1}`);
    const updated = [...lines.slice(0, blockStart + 1), ...kept, ...completion, ...lines.slice(blockEnd)];
    const result = updated.flatMap(line => foldContentLine(line)).join('\r\n') + '\r\n';
    if (utf8Length(result) > 2 * 1024 * 1024) throw new CalendarExchangeError('回写后的 CalDAV 待办超过 2 MB。');
    const checked = parseCalendarRoot(result, 2 * 1024 * 1024).getAllSubcomponents('vtodo');
    if (checked.length !== 1 || String(checked[0].getFirstPropertyValue('uid') || '') !== uid) {
      throw new CalendarExchangeError('CalDAV 待办回写校验失败。');
    }
    return result;
  }

  function combineIcsResources(resources, fallbackName = 'CalDAV 日历') {
    if (!Array.isArray(resources) || resources.length > MAX_COMPONENTS) throw new CalendarExchangeError('CalDAV 日历资源数量无效。');
    const root = new ICAL.Component(['vcalendar', [], []]);
    root.addPropertyWithValue('version', '2.0');
    root.addPropertyWithValue('prodid', '-//Wanxiang Life Workspace//CalDAV Cache//ZH');
    root.addPropertyWithValue('x-wr-calname', String(fallbackName || 'CalDAV 日历').slice(0, 80));
    const timezones = new Set();
    let componentCount = 0;
    let skippedRecurringTodos = 0;
    for (const resource of resources) {
      if (!resource || typeof resource.calendarData !== 'string') throw new CalendarExchangeError('CalDAV 资源内容无效。');
      const source = parseCalendarRoot(resource.calendarData);
      for (const timezone of source.getAllSubcomponents('vtimezone')) {
        const tzid = String(timezone.getFirstPropertyValue('tzid') || '');
        if (!tzid || timezones.has(tzid)) continue;
        timezones.add(tzid);
        root.addSubcomponent(new ICAL.Component(timezone.toJSON()));
      }
      for (const component of source.getAllSubcomponents()) {
        if (!['vevent', 'vtodo'].includes(component.name)) continue;
        if (component.name === 'vtodo'
          && ['rrule', 'rdate', 'exdate', 'exrule', 'recurrence-id'].some(name => component.hasProperty(name))) {
          skippedRecurringTodos++;
          continue;
        }
        componentCount++;
        if (componentCount > MAX_COMPONENTS) throw new CalendarExchangeError('一次最多同步 500 个 CalDAV 事件和待办。');
        root.addSubcomponent(new ICAL.Component(component.toJSON()));
      }
    }
    const icsText = root.toString();
    if (utf8Length(icsText) > MAX_ICS_BYTES) throw new CalendarExchangeError('CalDAV 日历缓存不能超过 1 MB。');
    const info = parseIcs(icsText, fallbackName, { allowEmpty: true });
    return { icsText, info, skippedRecurringTodos };
  }

  function selectedDayBounds(dayKey) {
    const { year, month, day } = parseDay(dayKey);
    const start = new Date(year, month - 1, day, 0, 0, 0, 0);
    const end = new Date(year, month - 1, day + 1, 0, 0, 0, 0);
    return { start, end };
  }

  function recurrenceCursor(dayStart, durationMs, eventStart) {
    const target = new Date(dayStart.getTime() - durationMs);
    if (eventStart.isDate) {
      const cursor = eventStart.clone();
      cursor.year = target.getFullYear();
      cursor.month = target.getMonth() + 1;
      cursor.day = target.getDate();
      return cursor;
    }
    const cursor = ICAL.Time.fromJSDate(target, true).convertToZone(eventStart.zone);
    cursor.hour = eventStart.hour;
    cursor.minute = eventStart.minute;
    cursor.second = eventStart.second;
    return cursor;
  }

  function wallDate(time) {
    return new Date(Date.UTC(time.year, time.month - 1, time.day, time.isDate ? 0 : time.hour, time.isDate ? 0 : time.minute, time.isDate ? 0 : time.second));
  }

  function wallKey(time) {
    return time.isDate
      ? `${dateKey(time.year, time.month, time.day)}`
      : `${dateKey(time.year, time.month, time.day)}T${String(time.hour).padStart(2, '0')}:${String(time.minute).padStart(2, '0')}:${String(time.second).padStart(2, '0')}`;
  }

  function toIcalTime(date, eventStart) {
    return ICAL.Time.fromData({
      year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate(),
      hour: eventStart.isDate ? 0 : date.getUTCHours(), minute: eventStart.isDate ? 0 : date.getUTCMinutes(), second: eventStart.isDate ? 0 : date.getUTCSeconds(),
      isDate: eventStart.isDate,
    }, eventStart.zone);
  }

  function recurrenceSet(component, event) {
    const set = new RRuleSet();
    const startWall = wallDate(event.startDate);
    const ruleProperty = component.getFirstProperty('rrule');
    if (ruleProperty) {
      try {
        const rule = RRule.parseString(ruleProperty.getFirstValue().toString());
        set.rrule(new RRule({ ...rule, dtstart: startWall }));
      } catch { throw new CalendarExchangeError('日历事件的重复规则无效。'); }
    }
    // RFC 5545 includes DTSTART in the recurrence set, even if it does not
    // match the rule selectors. RRuleSet removes a matching duplicate.
    set.rdate(startWall);
    const periodOverrides = new Map();
    component.getAllProperties('rdate').forEach(property => {
      property.getValues().forEach(value => {
        if (value instanceof ICAL.Period) {
          const period = value;
          const start = period.start;
          set.rdate(wallDate(start));
          periodOverrides.set(wallKey(start), period);
        } else if (value instanceof ICAL.Time) {
          set.rdate(wallDate(value));
        }
      });
    });
    component.getAllProperties('exdate').forEach(property => property.getValues().forEach(value => {
      if (value instanceof ICAL.Time) set.exdate(wallDate(value));
    }));
    return { set, periodOverrides };
  }

  function recurrenceSearchRange(dayStart, dayEnd, durationMs, eventStart) {
    const extraDays = Math.ceil(durationMs / 86400000) + 1;
    if (eventStart.isDate) {
      const start = new Date(dayStart.getFullYear(), dayStart.getMonth(), dayStart.getDate() - extraDays);
      const end = new Date(dayEnd.getFullYear(), dayEnd.getMonth(), dayEnd.getDate() + 1);
      return {
        after: new Date(Date.UTC(start.getFullYear(), start.getMonth(), start.getDate())),
        before: new Date(Date.UTC(end.getFullYear(), end.getMonth(), end.getDate())),
      };
    }
    const startZone = ICAL.Time.fromJSDate(dayStart, true).convertToZone(eventStart.zone);
    const endZone = ICAL.Time.fromJSDate(dayEnd, true).convertToZone(eventStart.zone);
    const after = new Date(Date.UTC(startZone.year, startZone.month - 1, startZone.day - extraDays, eventStart.hour, eventStart.minute, eventStart.second));
    const before = new Date(Date.UTC(endZone.year, endZone.month - 1, endZone.day + 1, eventStart.hour, eventStart.minute, eventStart.second));
    return { after, before };
  }

  function expandOccurrencesForDay(text, dayKey, sourceName) {
    let root = parseCalendarRoot(text);
    if (!root.getAllSubcomponents('vevent').length) return [];
    registerCalendarTimezones(root);
    root = parseCalendarRoot(text);
    const events = checkedEvents(root);
    const { start: dayStart, end: dayEnd } = selectedDayBounds(dayKey);
    const name = calendarName(root, sourceName);
    const output = [];
    let totalSteps = 0;

    events.forEach(({ uid, component, event }) => {
      const status = String(component.getFirstPropertyValue('status') || '').toUpperCase();
      if (status === 'CANCELLED') return;
      const startTime = event.startDate;
      const rawDuration = startTime.isDate
        ? Math.max(1, Math.round((event.endDate.toJSDate() - startTime.toJSDate()) / 86400000)) * 86400000
        : Math.max(0, event.endDate.toJSDate().getTime() - startTime.toJSDate().getTime());
      const { set, periodOverrides } = recurrenceSet(component, event);
      const { after, before } = recurrenceSearchRange(dayStart, dayEnd, rawDuration, startTime);
      let wallOccurrences;
      try { wallOccurrences = set.between(after, before, true); }
      catch { throw new CalendarExchangeError(`ICS 事件 ${uid} 的重复日期无法展开。`); }
      if (wallOccurrences.length > MAX_EXPANSIONS_PER_DAY || totalSteps + wallOccurrences.length > MAX_EXPANSIONS_PER_DAY) {
        throw new CalendarExchangeError('所选日期的重复事件数量超过安全上限。');
      }
      totalSteps += wallOccurrences.length;
      wallOccurrences.forEach(wall => {
        const occurrence = toIcalTime(wall, startTime);
        const details = event.getOccurrenceDetails(occurrence);
        const item = details.item;
        if (String(item.component.getFirstPropertyValue('status') || '').toUpperCase() === 'CANCELLED') return;
        let startDate;
        let endDate;
        if (details.startDate.isDate) {
          startDate = new Date(details.startDate.year, details.startDate.month - 1, details.startDate.day);
          endDate = new Date(details.endDate.year, details.endDate.month - 1, details.endDate.day);
        } else {
          startDate = details.startDate.toJSDate();
          endDate = details.endDate.toJSDate();
          const period = periodOverrides.get(wallKey(occurrence));
          if (period) endDate = (period.end || period.start.clone().addDuration(period.duration)).toJSDate();
        }
        if (startTime.isDate) {
          if (!(startDate < dayEnd && endDate > dayStart)) return;
          output.push({ uid, title: String(item.summary || '未命名日历事件').slice(0, 160), description: String(item.description || '').slice(0, 2000), location: String(item.location || '').slice(0, 160), transparency: String(item.component.getFirstPropertyValue('transp') || 'OPAQUE').toUpperCase() === 'TRANSPARENT' ? 'TRANSPARENT' : 'OPAQUE', allDay: true, startAt: startDate.getTime(), endAt: endDate.getTime(), startMinute: 0, endMinute: 1440, sourceCalendar: name });
          return;
        }
        if (!(startDate < dayEnd && endDate > dayStart)) return;
        const visibleStart = Math.max(dayStart.getTime(), startDate.getTime());
        const visibleEnd = Math.min(dayEnd.getTime(), endDate.getTime());
        const minuteFrom = startDate < dayStart ? 0 : startDate.getHours() * 60 + startDate.getMinutes();
        const minuteTo = endDate > dayEnd ? 1440 : endDate.getHours() * 60 + endDate.getMinutes() + (endDate.getSeconds() || endDate.getMilliseconds() ? 1 : 0);
        output.push({ uid, title: String(item.summary || '未命名日历事件').slice(0, 160), description: String(item.description || '').slice(0, 2000), location: String(item.location || '').slice(0, 160), transparency: String(item.component.getFirstPropertyValue('transp') || 'OPAQUE').toUpperCase() === 'TRANSPARENT' ? 'TRANSPARENT' : 'OPAQUE', allDay: false, startAt: visibleStart, endAt: visibleEnd, startMinute: Math.max(0, minuteFrom), endMinute: Math.min(1440, Math.max(minuteFrom, minuteTo)), sourceCalendar: name });
      });
    });
    return output.sort((a, b) => Number(a.allDay) === Number(b.allDay) ? a.startAt - b.startAt || a.title.localeCompare(b.title) : Number(b.allDay) - Number(a.allDay));
  }

  function eventOccurrencesForDay(text, dayKey, sourceName) {
    parseDay(dayKey);
    if (typeof text !== 'string') throw new CalendarExchangeError('日历来源内容无效。');
    let sourceCache = occurrenceCache.get(text);
    if (!sourceCache) {
      sourceCache = new Map();
      occurrenceCache.set(text, sourceCache);
      if (occurrenceCache.size > 24) occurrenceCache.delete(occurrenceCache.keys().next().value);
    }
    const cacheKey = `${dayKey}\u0000${String(sourceName || '')}`;
    if (sourceCache.has(cacheKey)) return sourceCache.get(cacheKey).map(item => ({ ...item }));
    const result = expandOccurrencesForDay(text, dayKey, sourceName);
    sourceCache.set(cacheKey, result.map(item => ({ ...item })));
    if (sourceCache.size > 32) sourceCache.delete(sourceCache.keys().next().value);
    return result;
  }

  function escapeText(value) {
    return String(value == null ? '' : value).replace(/\\/g, '\\\\').replace(/\r\n|\r|\n/g, '\\n').replace(/;/g, '\\;').replace(/,/g, '\\,');
  }

  function foldLine(line) {
    const parts = [];
    let current = '';
    let bytes = 0;
    Array.from(line).forEach(character => {
      const size = utf8Length(character);
      if (bytes + size > 75) { parts.push(current); current = ` ${character}`; bytes = 1 + size; }
      else { current += character; bytes += size; }
    });
    parts.push(current);
    return parts.join('\r\n');
  }

  function compactDate(value) { return String(value).replace(/-/g, ''); }

  function compactUtc(date) {
    return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  }

  function localPlannerStart(day, time) {
    const { year, month, day: date } = parseDay(day);
    const match = /^(\d{2}):(\d{2})$/.exec(String(time || ''));
    if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return null;
    const result = new Date(year, month - 1, date, Number(match[1]), Number(match[2]), 0, 0);
    if (result.getFullYear() !== year || result.getMonth() !== month - 1 || result.getDate() !== date) return null;
    return result;
  }

  function nextDay(day) {
    const { year, month, day: date } = parseDay(day);
    const value = new Date(year, month - 1, date + 1);
    return dateKey(value.getFullYear(), value.getMonth() + 1, value.getDate());
  }

  function tasksToIcs(tasks, startDay, endDay, calendarTitle = '万象来信日程', now = new Date()) {
    parseDay(startDay); parseDay(endDay);
    if (endDay < startDay) throw new CalendarExchangeError('导出结束日期不能早于开始日期。');
    const span = Math.round((new Date(`${endDay}T00:00:00`) - new Date(`${startDay}T00:00:00`)) / 86400000);
    if (span > 366) throw new CalendarExchangeError('一次最多导出 367 天的任务。');
    const rows = (Array.isArray(tasks) ? tasks : []).filter(record => record && record.type === 'planner' && !record.sample && record.date >= startDay && record.date <= endDay).slice(0, MAX_COMPONENTS);
    const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Wanxiang Life Workspace//Planner//ZH', 'CALSCALE:GREGORIAN', `X-WR-CALNAME:${escapeText(calendarTitle)}`];
    rows.forEach(record => {
      const data = record.data || {};
      const title = String(data.title || '未命名任务').trim().slice(0, 160);
      const uid = `${String(record.id || 'task').replace(/[^A-Za-z0-9._@-]/g, '_')}@wanxiang.local`;
      const description = [String(data.note || '').trim(), data.project ? `项目：${data.project}` : '', Array.isArray(data.tags) && data.tags.length ? `标签：${data.tags.join('、')}` : ''].filter(Boolean).join('\n').slice(0, 2000);
      lines.push('BEGIN:VEVENT', `UID:${escapeText(uid)}`, `DTSTAMP:${compactUtc(now)}`, `SUMMARY:${escapeText(title)}`);
      if (description) lines.push(`DESCRIPTION:${escapeText(description)}`);
      if (data.time) {
        const start = localPlannerStart(record.date, data.time);
        if (!start) throw new CalendarExchangeError(`任务“${title}”的排程时间无效。`);
        const end = new Date(start.getTime() + Math.max(5, Math.min(24 * 60, Number(data.estimateMin) || 30)) * 60000);
        lines.push(`DTSTART:${compactUtc(start)}`, `DTEND:${compactUtc(end)}`);
      } else {
        lines.push(`DTSTART;VALUE=DATE:${compactDate(record.date)}`, `DTEND;VALUE=DATE:${compactDate(nextDay(record.date))}`);
      }
      lines.push(`X-WANXIANG-STATUS:${data.done ? 'COMPLETED' : (data.status === 'inprogress' ? 'IN-PROCESS' : 'NEEDS-ACTION')}`, 'END:VEVENT');
    });
    lines.push('END:VCALENDAR');
    return lines.map(foldLine).join('\r\n') + '\r\n';
  }

  return { CalendarExchangeError, MAX_ICS_BYTES, MAX_COMPONENTS, parseIcs, combineIcsResources, todoResourceUids, updateVtodoCompletion, eventOccurrencesForDay, tasksToIcs };
});
