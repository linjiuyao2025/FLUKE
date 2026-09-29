const assert = require('node:assert/strict');
const test = require('node:test');
const { CalendarExchangeError, MAX_ICS_BYTES, parseIcs, combineIcsResources, todoResourceUids, updateVtodoCompletion, eventOccurrencesForDay, tasksToIcs } = require('./calendar-exchange.js');
const makeCalendar = (...components) => ['BEGIN:VCALENDAR', 'VERSION:2.0', ...components.flat(), 'END:VCALENDAR'].join('\r\n');

const dailyAcrossDst = [
  'BEGIN:VCALENDAR',
  'VERSION:2.0',
  'X-WR-CALNAME:Work',
  'BEGIN:VEVENT',
  'UID:daily-work',
  'SUMMARY:Daily standup',
  'DTSTART;TZID=America/New_York:20260307T090000',
  'DTEND;TZID=America/New_York:20260307T100000',
  'RRULE:FREQ=DAILY;COUNT=3',
  'END:VEVENT',
  'END:VCALENDAR',
].join('\r\n');

const weeklyWithException = [
  'BEGIN:VCALENDAR', 'VERSION:2.0',
  'BEGIN:VEVENT',
  'UID:weekly-team', 'SUMMARY:Weekly sync',
  'DTSTART;TZID=America/New_York:20260302T090000',
  'DTEND;TZID=America/New_York:20260302T100000',
  'RRULE:FREQ=WEEKLY;COUNT=3',
  'END:VEVENT',
  'BEGIN:VEVENT',
  'UID:weekly-team',
  'RECURRENCE-ID;TZID=America/New_York:20260309T090000',
  'SUMMARY:Moved sync',
  'DTSTART;TZID=America/New_York:20260310T110000',
  'DTEND;TZID=America/New_York:20260310T120000',
  'END:VEVENT',
  'END:VCALENDAR',
].join('\r\n');

const dateSet = [
  'BEGIN:VCALENDAR', 'VERSION:2.0',
  'BEGIN:VEVENT', 'UID:date-set', 'SUMMARY:Date set',
  'DTSTART;TZID=America/New_York:20260302T090000',
  'DTEND;TZID=America/New_York:20260302T100000',
  'RRULE:FREQ=WEEKLY;COUNT=3',
  'RDATE;TZID=America/New_York:20260304T130000',
  'EXDATE;TZID=America/New_York:20260302T090000',
  'END:VEVENT', 'END:VCALENDAR',
].join('\r\n');

test('IANA time zones without embedded VTIMEZONE keep wall time through daylight saving changes', () => {
  const parsed = parseIcs(dailyAcrossDst);
  assert.equal(parsed.name, 'Work');
  assert.equal(parsed.eventCount, 1);
  assert.equal(parsed.todoCount, 0);
  assert.equal(parsed.componentCount, 1);
  const before = eventOccurrencesForDay(dailyAcrossDst, '2026-03-07')[0];
  const after = eventOccurrencesForDay(dailyAcrossDst, '2026-03-09')[0];
  assert.equal(before.startMinute, 22 * 60);
  assert.equal(after.startMinute, 21 * 60);
  assert.equal(after.startAt - before.startAt, 47 * 60 * 60 * 1000);
});

test('CalDAV resources combine recurrence exceptions and events into one validated source', () => {
  const master = makeCalendar(
    'BEGIN:VEVENT', 'UID:series', 'SUMMARY:Weekly work', 'DTSTART;TZID=America/New_York:20261005T090000',
    'DTEND;TZID=America/New_York:20261005T100000', 'RRULE:FREQ=WEEKLY;COUNT=2', 'END:VEVENT',
  );
  const exception = makeCalendar(
    'BEGIN:VEVENT', 'UID:series', 'RECURRENCE-ID;TZID=America/New_York:20261012T090000',
    'SUMMARY:Moved work', 'DTSTART;TZID=America/New_York:20261012T110000',
    'DTEND;TZID=America/New_York:20261012T120000', 'END:VEVENT',
  );
  const other = makeCalendar(
    'BEGIN:VEVENT', 'UID:single', 'SUMMARY:Single event', 'DTSTART:20261013T100000Z',
    'DTEND:20261013T110000Z', 'END:VEVENT',
    'BEGIN:VTODO', 'UID:skip-repeat', 'SUMMARY:Repeating task', 'DTSTART:20261013T080000Z',
    'RRULE:FREQ=DAILY;COUNT=2', 'END:VTODO',
  );
  const result = combineIcsResources([
    { calendarData: master }, { calendarData: exception }, { calendarData: other },
  ], 'Work');
  assert.equal(result.info.name, 'Work');
  assert.equal(result.info.eventCount, 2);
  assert.equal(result.info.todoCount, 0);
  assert.equal(result.skippedRecurringTodos, 1);
  assert.match(result.icsText, /RECURRENCE-ID/u);
  assert.equal(eventOccurrencesForDay(result.icsText, '2026-10-12')[0].title, 'Moved work');
});

test('pure VTODO imports date, scheduled start, priority, progress, and a safe source link', () => {
  const parsed = parseIcs(makeCalendar([
    'BEGIN:VTODO', 'UID:task-1', 'SUMMARY:Prepare report', 'STATUS:IN-PROCESS',
    'PERCENT-COMPLETE:40', 'PRIORITY:2', 'DTSTART:20260929T093000Z',
    'DUE;VALUE=DATE:20260930', 'DESCRIPTION:First draft', 'URL:https://example.com/report', 'END:VTODO',
  ]));
  const localStart = new Date('2026-09-29T09:30:00Z');
  assert.equal(parsed.eventCount, 0);
  assert.equal(parsed.todoCount, 1);
  assert.equal(parsed.componentCount, 1);
  assert.deepEqual(parsed.todos[0], {
    uid: 'task-1', title: 'Prepare report', description: 'First draft', url: 'https://example.com/report',
    date: '2026-09-30', time: `${String(localStart.getHours()).padStart(2, '0')}:${String(localStart.getMinutes()).padStart(2, '0')}`,
    priority: 'high', status: 'inprogress', done: false, cancelled: false, percentComplete: 40, completedAt: '',
  });
});

test('VTODO completed and cancelled states stay distinct', () => {
  const parsed = parseIcs(makeCalendar(
    ['BEGIN:VTODO', 'UID:done-1', 'SUMMARY:Finished', 'STATUS:COMPLETED', 'PERCENT-COMPLETE:100', 'PRIORITY:9', 'COMPLETED:20260929T110000Z', 'END:VTODO'],
    ['BEGIN:VTODO', 'UID:cancel-1', 'SUMMARY:Cancelled item', 'STATUS:CANCELLED', 'PERCENT-COMPLETE:0', 'END:VTODO'],
  ));
  assert.equal(parsed.todoCount, 2);
  assert.equal(parsed.todos[0].status, 'done');
  assert.equal(parsed.todos[0].done, true);
  assert.equal(parsed.todos[0].priority, 'low');
  assert.equal(parsed.todos[0].completedAt, new Date('2026-09-29T11:00:00Z').toISOString());
  assert.equal(parsed.todos[1].status, 'cancelled');
  assert.equal(parsed.todos[1].cancelled, true);
  assert.equal(parsed.todos[1].done, false);
});

test('mixed VEVENT and VTODO files retain both component types', () => {
  const parsed = parseIcs(makeCalendar(
    ['BEGIN:VEVENT', 'UID:event-1', 'SUMMARY:Meeting', 'DTSTART:20260929T090000Z', 'DTEND:20260929T100000Z', 'END:VEVENT'],
    ['BEGIN:VTODO', 'UID:task-1', 'SUMMARY:Write notes', 'END:VTODO'],
  ));
  assert.equal(parsed.eventCount, 1);
  assert.equal(parsed.todoCount, 1);
  assert.equal(parsed.componentCount, 2);
  assert.equal(eventOccurrencesForDay(makeCalendar(
    ['BEGIN:VEVENT', 'UID:event-1', 'SUMMARY:Meeting', 'DTSTART:20260929T090000Z', 'DTEND:20260929T100000Z', 'END:VEVENT'],
    ['BEGIN:VTODO', 'UID:task-1', 'SUMMARY:Write notes', 'END:VTODO'],
  ), '2026-09-29').length, 1);
});

test('VTODO timezone wall times convert into the computer local time', () => {
  const parsed = parseIcs(makeCalendar([
    'BEGIN:VTODO', 'UID:tz-task', 'SUMMARY:Timezone task',
    'DTSTART;TZID=America/New_York:20260307T093000', 'END:VTODO',
  ])).todos[0];
  const expected = new Date('2026-03-07T14:30:00Z');
  assert.equal(parsed.date, `${expected.getFullYear()}-${String(expected.getMonth() + 1).padStart(2, '0')}-${String(expected.getDate()).padStart(2, '0')}`);
  assert.equal(parsed.time, `${String(expected.getHours()).padStart(2, '0')}:${String(expected.getMinutes()).padStart(2, '0')}`);
});

test('invalid VTODOs fail the complete import instead of partially applying', () => {
  assert.throws(() => parseIcs(makeCalendar(['BEGIN:VTODO', 'UID:no-title', 'END:VTODO'])), /缺少标题/);
  assert.throws(() => parseIcs(makeCalendar(['BEGIN:VTODO', 'UID:bad-status', 'SUMMARY:Task', 'STATUS:WAITING', 'END:VTODO'])), /状态无效/);
  assert.throws(() => parseIcs(makeCalendar(['BEGIN:VTODO', 'UID:bad-priority', 'SUMMARY:Task', 'PRIORITY:10', 'END:VTODO'])), /优先级无效/);
  assert.throws(() => parseIcs(makeCalendar(['BEGIN:VTODO', 'UID:repeating', 'SUMMARY:Task', 'RRULE:FREQ=DAILY', 'END:VTODO'])), /不支持的重复规则/);
  assert.throws(() => parseIcs(makeCalendar(['BEGIN:VTODO', 'UID:unsafe-link', 'SUMMARY:Task', 'URL:javascript:alert(1)', 'END:VTODO'])), /链接无效/);
  assert.throws(() => parseIcs(makeCalendar(
    ['BEGIN:VTODO', 'UID:duplicate', 'SUMMARY:First', 'END:VTODO'],
    ['BEGIN:VTODO', 'UID:duplicate', 'SUMMARY:Second', 'END:VTODO'],
  )), /UID 重复/);
});

test('weekly recurrence exceptions cancel one instance and show its moved replacement once', () => {
  assert.deepEqual(eventOccurrencesForDay(weeklyWithException, '2026-03-02').map(event => event.title), ['Weekly sync']);
  assert.deepEqual(eventOccurrencesForDay(weeklyWithException, '2026-03-09'), []);
  const moved = eventOccurrencesForDay(weeklyWithException, '2026-03-10');
  assert.equal(moved.length, 1);
  assert.equal(moved[0].title, 'Moved sync');
  assert.equal(moved[0].startMinute, 23 * 60);
  assert.equal(eventOccurrencesForDay(weeklyWithException, '2026-03-16').length, 1);
});

test('RDATE adds an extra occurrence while EXDATE removes the original', () => {
  assert.deepEqual(eventOccurrencesForDay(dateSet, '2026-03-02'), []);
  const added = eventOccurrencesForDay(dateSet, '2026-03-05');
  assert.equal(added.length, 1);
  assert.equal(added[0].startMinute, 2 * 60);
});

test('all-day events use exclusive end dates and transparent events do not reserve time', () => {
  const ics = [
    'BEGIN:VCALENDAR', 'VERSION:2.0',
    'BEGIN:VEVENT', 'UID:holiday', 'SUMMARY:Holiday',
    'DTSTART;VALUE=DATE:20260929', 'DTEND;VALUE=DATE:20260930',
    'END:VEVENT',
    'BEGIN:VEVENT', 'UID:transparent', 'SUMMARY:Optional event', 'TRANSP:TRANSPARENT',
    'DTSTART:20260929T090000Z', 'DTEND:20260929T100000Z',
    'END:VEVENT', 'END:VCALENDAR',
  ].join('\r\n');
  const events = eventOccurrencesForDay(ics, '2026-09-29');
  assert.equal(events.length, 2);
  assert.equal(events.find(event => event.uid === 'holiday').allDay, true);
  assert.equal(events.find(event => event.uid === 'transparent').transparency, 'TRANSPARENT');
  assert.equal(eventOccurrencesForDay(ics, '2026-09-30').some(event => event.uid === 'holiday'), false);
});

test('malformed, unsupported, oversized, and ambiguous series fail closed', () => {
  assert.throws(() => parseIcs(''), CalendarExchangeError);
  assert.throws(() => parseIcs('x'.repeat(MAX_ICS_BYTES + 1)), /1 MB/);
  assert.throws(() => parseIcs('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR'), /没有可导入/);
  assert.throws(() => parseIcs('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART:20260929T090000Z\r\nRRULE:FREQ=HOURLY;COUNT=2\r\nEND:VEVENT\r\nEND:VCALENDAR'), /仅支持/);
  assert.throws(() => parseIcs('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART:20260929T090000Z\r\nEXRULE:FREQ=DAILY\r\nEND:VEVENT\r\nEND:VCALENDAR'), /EXRULE/);
});

test('empty calendars are accepted only when the caller opts in for an online subscription refresh', () => {
  const empty = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//FLUKE//Empty calendar//EN\r\nEND:VCALENDAR\r\n';
  assert.throws(() => parseIcs(empty), /没有可导入/);
  assert.equal(parseIcs(empty, 'Team calendar', { allowEmpty: true }).eventCount, 0);
  assert.deepEqual(eventOccurrencesForDay(empty, '2026-09-29'), []);
});

test('CalDAV completion rewrites only status metadata, preserves nested content, and increments SEQUENCE', () => {
  const source = [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VTODO', 'UID:writeback-1', 'SUMMARY:评审计划',
    'DESCRIPTION:保留这段说明', 'STATUS:IN-PROCESS', 'PERCENT-COMPLETE:45',
    'SEQUENCE:7', 'SEQUENCE:8', 'COMPLETED:20260928T090000Z',
    'BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:完成后提醒', 'END:VALARM',
    'X-CUSTOM-META:must-stay', 'END:VTODO', 'END:VCALENDAR', '',
  ].join('\r\n');
  assert.deepEqual(todoResourceUids(source), ['writeback-1']);
  const completed = updateVtodoCompletion(source, 'writeback-1', true, new Date('2026-09-29T10:11:12.000Z'));
  assert.deepEqual(parseIcs(completed).todos.map(todo => todo.done), [true]);
  assert.match(completed, /STATUS:COMPLETED\r\n/u);
  assert.match(completed, /PERCENT-COMPLETE:100\r\n/u);
  assert.match(completed, /COMPLETED:20260929T101112Z\r\n/u);
  assert.match(completed, /SEQUENCE:9\r\n/u);
  assert.match(completed, /DESCRIPTION:保留这段说明\r\n/u);
  assert.match(completed, /BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:完成后提醒\r\nEND:VALARM\r\n/u);
  assert.match(completed, /X-CUSTOM-META:must-stay\r\n/u);
  assert.doesNotMatch(completed, /PERCENT-COMPLETE:45|SEQUENCE:7|SEQUENCE:8|COMPLETED:20260928/u);
  for (const line of completed.split('\r\n').filter(Boolean)) assert.ok(Buffer.byteLength(line, 'utf8') <= 75);

  const reopened = updateVtodoCompletion(completed, 'writeback-1', false, new Date('2026-09-30T01:02:03.000Z'));
  assert.deepEqual(parseIcs(reopened).todos.map(todo => todo.done), [false]);
  assert.match(reopened, /STATUS:NEEDS-ACTION\r\n/u);
  assert.match(reopened, /PERCENT-COMPLETE:0\r\n/u);
  assert.match(reopened, /SEQUENCE:10\r\n/u);
  assert.doesNotMatch(reopened, /COMPLETED:/u);
});

test('CalDAV completion refuses mismatched, recurring, or ambiguous resources', () => {
  const one = makeCalendar([
    'BEGIN:VTODO', 'UID:one', 'SUMMARY:One', 'END:VTODO',
  ]);
  assert.throws(() => updateVtodoCompletion(one, 'other', true), /UID/u);
  const recurring = makeCalendar([
    'BEGIN:VTODO', 'UID:repeat', 'SUMMARY:Repeat', 'RRULE:FREQ=DAILY', 'END:VTODO',
  ]);
  assert.throws(() => updateVtodoCompletion(recurring, 'repeat', true), /循环/u);
  const ambiguous = makeCalendar([
    'BEGIN:VTODO', 'UID:one', 'SUMMARY:One', 'END:VTODO',
    'BEGIN:VTODO', 'UID:two', 'SUMMARY:Two', 'END:VTODO',
  ]);
  assert.throws(() => updateVtodoCompletion(ambiguous, 'one', true), /UID/u);
});

test('task export round-trips scheduled and all-day tasks with bounded UTF-8 lines', () => {
  const tasks = [
    { id: 'timed-task', type: 'planner', date: '2026-09-29', sample: false, data: { title: '写一份项目总结', time: '09:15', estimateMin: 45, note: '初稿，之后校对', project: '工作', tags: ['写作'], done: false } },
    { id: 'all-day-task', type: 'planner', date: '2026-09-30', sample: false, data: { title: '安排休息', time: '', estimateMin: 30, done: true } },
  ];
  const text = tasksToIcs(tasks, '2026-09-29', '2026-09-30', '测试导出', new Date('2026-09-29T00:00:00Z'));
  assert.ok(text.includes('BEGIN:VCALENDAR'));
  assert.ok(text.includes('X-WANXIANG-STATUS:COMPLETED'));
  for (const line of text.split('\r\n').filter(Boolean)) assert.ok(Buffer.byteLength(line, 'utf8') <= 75, `${Buffer.byteLength(line, 'utf8')} bytes: ${line}`);
  assert.equal(parseIcs(text).eventCount, 2);
  const timed = eventOccurrencesForDay(text, '2026-09-29');
  assert.equal(timed.length, 1);
  assert.equal(timed[0].startMinute, 9 * 60 + 15);
  const allDay = eventOccurrencesForDay(text, '2026-09-30');
  assert.equal(allDay.length, 1);
  assert.equal(allDay[0].allDay, true);
});
