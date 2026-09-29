"""Small, defensive iCalendar exchange for local planner events.

The importer handles ordinary VEVENT entries (including all-day events and
IANA time zones) and deliberately rejects recurrence rules it cannot expand.
Imported calendar rows stay separate from planner tasks.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from io import StringIO
from pathlib import Path
import os
import re
import tempfile
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dateutil.rrule import rruleset, rrulestr
from dateutil.tz import tzical
from tzlocal import get_localzone


class CalendarExchangeError(ValueError):
    """Readable validation error for an iCalendar import or export."""


_DATE_RE = re.compile(r"^\d{8}$")
_DATETIME_RE = re.compile(r"^\d{8}T\d{6}Z?$")
_DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_RRULE_FREQ_RE = re.compile(r"(?:^|;)FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)(?:;|$)", re.IGNORECASE)


def _split_unquoted(value: str, delimiter: str) -> list[str]:
    parts: list[str] = []
    quoted = False
    escaped = False
    start = 0
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == delimiter and not quoted:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return parts


def _parse_content_line(line: str) -> tuple[str, dict[str, str], str]:
    quoted = False
    escaped = False
    separator = -1
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == ":" and not quoted:
            separator = index
            break
    if separator <= 0:
        raise CalendarExchangeError("ICS 文件含有格式错误的属性行。")
    left, value = line[:separator], line[separator + 1:]
    parts = _split_unquoted(left, ";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        params[key.upper()] = raw.strip().strip('"')
    return name, params, value


def _unescape_text(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            next_char = value[index + 1]
            result.append("\n" if next_char in "nN" else next_char)
            index += 2
        else:
            result.append(char)
            index += 1
    return "".join(result)


def _folded_lines(text: str) -> list[str]:
    physical = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    logical: list[str] = []
    for line in physical:
        if line.startswith((" ", "\t")) and logical:
            logical[-1] += line[1:]
        elif line:
            logical.append(line)
    return logical


def _parse_date_value(value: str) -> date:
    if not _DATE_RE.fullmatch(value):
        raise CalendarExchangeError("ICS 全天事件日期须使用 YYYYMMDD。")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise CalendarExchangeError("ICS 文件含有无效的全天事件日期。") from exc


@lru_cache(maxsize=64)
def _timezone_from_definition(tzid: str, definition: str = "") -> Any:
    if definition:
        try:
            parsed = tzical(StringIO(definition))
            zone = parsed.get(tzid)
        except (TypeError, ValueError, KeyError) as exc:
            raise CalendarExchangeError(f"ICS 时区定义无效：{tzid}") from exc
        if zone is None:
            raise CalendarExchangeError(f"ICS 时区定义中找不到 TZID：{tzid}")
        return zone
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CalendarExchangeError(f"ICS 使用了本机无法识别的时区：{tzid}") from exc


def _strip_timezone_components(
    lines: list[str],
) -> tuple[list[str], dict[str, str]]:
    timezone_definitions: dict[str, str] = {}
    filtered_lines: list[str] = []
    timezone_total_size = 0
    index = 1
    while index < len(lines) - 1:
        if lines[index].upper() != "BEGIN:VTIMEZONE":
            filtered_lines.append(lines[index])
            index += 1
            continue
        block = [lines[index]]
        index += 1
        while index < len(lines) - 1 and lines[index].upper() != "END:VTIMEZONE":
            if lines[index].upper() == "BEGIN:VTIMEZONE":
                raise CalendarExchangeError("ICS 文件包含嵌套的 VTIMEZONE。")
            block.append(lines[index])
            index += 1
        if index >= len(lines) - 1:
            raise CalendarExchangeError("ICS 文件有未结束的 VTIMEZONE。")
        block.append(lines[index])
        index += 1
        definition = "\r\n".join(block) + "\r\n"
        definition_size = len(definition.encode("utf-8"))
        timezone_total_size += definition_size
        if definition_size > 64_000 or timezone_total_size > 256_000 or len(timezone_definitions) >= 32:
            raise CalendarExchangeError("ICS 时区定义超出安全导入限制。")
        try:
            parsed_zone = tzical(StringIO(definition))
            zone_ids = parsed_zone.keys()
        except (TypeError, ValueError) as exc:
            raise CalendarExchangeError("ICS 文件包含无效的 VTIMEZONE 定义。") from exc
        if len(zone_ids) != 1 or not zone_ids[0]:
            raise CalendarExchangeError("ICS 每个 VTIMEZONE 必须提供一个有效 TZID。")
        zone_id = zone_ids[0]
        if zone_id in timezone_definitions:
            raise CalendarExchangeError(f"ICS 文件重复定义时区：{zone_id}")
        timezone_definitions[zone_id] = definition
    return filtered_lines, timezone_definitions


def _event_timezone(event: dict[str, Any]) -> Any:
    timezone_id = str(event.get("timezoneId", ""))
    definition = str(event.get("timezoneDefinition", ""))
    if timezone_id:
        return _timezone_from_definition(timezone_id, definition)
    start_at = event.get("startAt", "")
    if start_at:
        parsed = datetime.fromisoformat(start_at)
        if parsed.tzinfo is not None:
            return parsed.tzinfo
    return get_localzone()


def _parse_datetime_value(value: str, tzid: str, timezone_definitions: dict[str, str] | None = None) -> datetime:
    if not _DATETIME_RE.fullmatch(value):
        raise CalendarExchangeError("ICS 事件时间须使用 YYYYMMDDTHHMMSS 或 UTC 的 Z 格式。")
    is_utc = value.endswith("Z")
    raw = value[:-1] if is_utc else value
    try:
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%S")
    except ValueError as exc:
        raise CalendarExchangeError("ICS 文件含有无效的事件时间。") from exc
    if is_utc:
        if tzid:
            raise CalendarExchangeError("ICS 的 UTC 时间不能同时声明 TZID。")
        return parsed.replace(tzinfo=timezone.utc)
    if tzid:
        definition = (timezone_definitions or {}).get(tzid, "")
        return parsed.replace(tzinfo=_timezone_from_definition(tzid, definition))
    return parsed.replace(tzinfo=get_localzone())


def _parse_duration(value: str) -> timedelta:
    match = _DURATION_RE.fullmatch(value)
    if not match or not any(match.groups()):
        raise CalendarExchangeError("ICS 事件使用了暂不支持的 DURATION 格式。")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def _validate_recurrence_rule(value: str, dtstart: datetime) -> str:
    rule = value.strip().upper()
    if not rule or len(rule) > 512 or not _RRULE_FREQ_RE.search(rule):
        raise CalendarExchangeError("ICS 重复规则无效或使用了暂不支持的频率。")
    fields: dict[str, str] = {}
    for part in rule.split(";"):
        if "=" not in part:
            raise CalendarExchangeError("ICS 重复规则格式无效。")
        key, field_value = part.split("=", 1)
        key = key.strip().upper()
        field_value = field_value.strip()
        if not key or not field_value or key in fields:
            raise CalendarExchangeError("ICS 重复规则包含空字段或重复字段。")
        fields[key] = field_value
    if "COUNT" in fields and "UNTIL" in fields:
        raise CalendarExchangeError("ICS 重复规则不能同时使用 COUNT 和 UNTIL。")
    if {"BYHOUR", "BYMINUTE", "BYSECOND"} & fields.keys():
        raise CalendarExchangeError("ICS 重复规则包含可能产生高频事件的时间选择器。")
    try:
        rrulestr(rule, dtstart=dtstart)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalendarExchangeError("ICS 重复规则参数无效。") from exc
    return rule


def _parse_recurrence_values(
    properties: list[tuple[dict[str, str], str]],
    *,
    all_day: bool,
    default_timezone_id: str,
    default_timezone: tzinfo | None = None,
    timezone_definitions: dict[str, str] | None = None,
) -> list[str]:
    result: list[str] = []
    for params, raw_values in properties:
        if params.get("VALUE", "").upper() == "PERIOD":
            raise CalendarExchangeError("ICS RDATE/EXDATE 暂不支持 PERIOD 时段值。")
        property_timezone_id = params.get("TZID", "")
        for raw_value in _split_unquoted(raw_values, ","):
            raw_value = raw_value.strip()
            value_is_date = params.get("VALUE", "").upper() == "DATE" or bool(_DATE_RE.fullmatch(raw_value))
            if value_is_date != all_day:
                raise CalendarExchangeError("ICS 重复附加日期的数据类型须与 DTSTART 一致。")
            if all_day:
                if property_timezone_id:
                    raise CalendarExchangeError("ICS 的 DATE 值不能同时声明 TZID。")
                result.append(_parse_date_value(raw_value).isoformat())
            else:
                # A UTC recurrence value must not inherit DTSTART's TZID.
                # Parse it as an instant, then normalize it into the master's
                # zone because occurrence expansion stores master-zone wall time.
                timezone_id = property_timezone_id
                if not timezone_id and not raw_value.endswith("Z"):
                    timezone_id = default_timezone_id
                parsed = _parse_datetime_value(raw_value, timezone_id, timezone_definitions)
                if default_timezone is not None:
                    parsed = parsed.astimezone(default_timezone)
                # Keep recurring values as wall-clock time; their owning event
                # supplies the real zone rules when an occurrence is expanded.
                result.append(parsed.replace(tzinfo=None).isoformat(timespec="seconds"))
            if len(result) > 1000:
                raise CalendarExchangeError("单个 ICS 事件最多支持 1000 个附加或排除日期。")
    return result


def _event_value(properties: dict[str, list[tuple[dict[str, str], str]]], name: str) -> tuple[dict[str, str], str] | None:
    values = properties.get(name, [])
    return values[0] if values else None


def _build_ics_event(
    properties: dict[str, list[tuple[dict[str, str], str]]],
    uid: str,
    calendar_name: str,
    timezone_definitions: dict[str, str],
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start_prop = _event_value(properties, "DTSTART")
    if start_prop is None:
        raise CalendarExchangeError(f"ICS 事件 {uid} 缺少 DTSTART。")
    start_params, start_raw = start_prop
    is_all_day = start_params.get("VALUE", "").upper() == "DATE" or bool(_DATE_RE.fullmatch(start_raw))
    if base is not None and is_all_day != bool(base["allDay"]):
        raise CalendarExchangeError(f"ICS 重复例外项 {uid} 的日期类型与主事件不一致。")

    end_prop = _event_value(properties, "DTEND")
    duration_prop = _event_value(properties, "DURATION")
    if is_all_day:
        start_day = _parse_date_value(start_raw)
        if end_prop:
            end_day = _parse_date_value(end_prop[1])
        elif duration_prop:
            delta = _parse_duration(duration_prop[1])
            if delta.total_seconds() <= 0 or delta.total_seconds() % 86400:
                raise CalendarExchangeError("全天事件的 DURATION 须为正整天数。")
            end_day = start_day + delta
        elif base is not None:
            old_duration = date.fromisoformat(base["endDate"]) - date.fromisoformat(base["startDate"])
            end_day = start_day + old_duration
        else:
            end_day = start_day + timedelta(days=1)
        if end_day <= start_day:
            raise CalendarExchangeError(f"ICS 全天事件 {uid} 的结束日期必须晚于开始日期。")
        start_at = ""
        end_at = ""
        start_date = start_day.isoformat()
        end_date = end_day.isoformat()
        timezone_id = ""
        timezone_definition = ""
        start_dt = end_dt = None
    else:
        if start_params.get("VALUE", "DATE-TIME").upper() == "DATE":
            raise CalendarExchangeError(f"ICS 事件 {uid} 的 DTSTART 数据类型不一致。")
        timezone_id = start_params.get("TZID", "")
        if not timezone_id and base is not None and not start_raw.endswith("Z"):
            timezone_id = str(base.get("timezoneId", ""))
        start_dt = _parse_datetime_value(start_raw, timezone_id, timezone_definitions)
        if end_prop:
            end_params, end_raw = end_prop
            end_tzid = end_params.get("TZID", "")
            if not end_raw.endswith("Z") and not end_tzid:
                end_tzid = timezone_id
            if end_tzid != timezone_id:
                raise CalendarExchangeError(f"ICS 事件 {uid} 的起止时区不一致。")
            end_dt = _parse_datetime_value(end_raw, end_tzid, timezone_definitions)
        elif duration_prop:
            end_dt = start_dt + _parse_duration(duration_prop[1])
        elif base is not None:
            base_start = datetime.fromisoformat(base["startAt"])
            base_end = datetime.fromisoformat(base["endAt"])
            elapsed = base_end.astimezone(timezone.utc) - base_start.astimezone(timezone.utc)
            end_dt = (start_dt.astimezone(timezone.utc) + elapsed).astimezone(start_dt.tzinfo)
        else:
            end_dt = start_dt
        if end_dt < start_dt:
            raise CalendarExchangeError(f"ICS 事件 {uid} 的结束时间早于开始时间。")
        if not timezone_id and not start_raw.endswith("Z"):
            timezone_id = getattr(start_dt.tzinfo, "key", "") or ""
        timezone_definition = timezone_definitions.get(timezone_id, "")
        start_at = start_dt.isoformat(timespec="seconds")
        end_at = end_dt.isoformat(timespec="seconds")
        start_date = start_dt.astimezone().date().isoformat()
        end_date = end_dt.astimezone().date().isoformat()

    summary_prop = _event_value(properties, "SUMMARY")
    description_prop = _event_value(properties, "DESCRIPTION")
    location_prop = _event_value(properties, "LOCATION")
    if len(properties.get("TRANSP", [])) > 1:
        raise CalendarExchangeError(f"ICS 事件 {uid} 包含多条 TRANSP 属性。")
    transparency_prop = _event_value(properties, "TRANSP")
    transparency = (
        transparency_prop[1].strip().upper()
        if transparency_prop
        else str((base or {}).get("transparency", "OPAQUE")).upper()
    )
    if transparency not in {"OPAQUE", "TRANSPARENT"}:
        raise CalendarExchangeError(f"ICS 事件 {uid} 的 TRANSP 值无效。")
    event = {
        "id": uid,
        "uid": uid,
        "title": _unescape_text(summary_prop[1]) if summary_prop else (base or {}).get("title", "未命名日历事件"),
        "description": _unescape_text(description_prop[1]) if description_prop else (base or {}).get("description", ""),
        "location": _unescape_text(location_prop[1]) if location_prop else (base or {}).get("location", ""),
        "transparency": transparency,
        "allDay": is_all_day,
        "startAt": start_at,
        "endAt": end_at,
        "startDate": start_date,
        "endDate": end_date,
        "timezoneId": timezone_id,
        "timezoneDefinition": timezone_definition,
        "sourceCalendar": (base or {}).get("sourceCalendar", calendar_name),
        "recurrenceRule": "",
        "recurrenceDates": [],
        "excludedDates": [],
        "recurrenceOverrides": [],
    }
    if base is None:
        rule_props = properties.get("RRULE", [])
        if len(rule_props) > 1:
            raise CalendarExchangeError(f"ICS 事件 {uid} 包含多条 RRULE。")
        if rule_props:
            recurrence_start = datetime.combine(start_day, time.min) if is_all_day else start_dt
            event["recurrenceRule"] = _validate_recurrence_rule(rule_props[0][1], recurrence_start)
        event["recurrenceDates"] = _parse_recurrence_values(
            properties.get("RDATE", []), all_day=is_all_day, default_timezone_id=timezone_id,
            default_timezone=start_dt.tzinfo if start_dt is not None else None,
            timezone_definitions=timezone_definitions,
        )
        event["excludedDates"] = _parse_recurrence_values(
            properties.get("EXDATE", []), all_day=is_all_day, default_timezone_id=timezone_id,
            default_timezone=start_dt.tzinfo if start_dt is not None else None,
            timezone_definitions=timezone_definitions,
        )
        if event["recurrenceRule"] or event["recurrenceDates"]:
            recurrence_duration = (
                timedelta(days=(end_day - start_day).days)
                if is_all_day
                else end_dt.astimezone(timezone.utc) - start_dt.astimezone(timezone.utc)
            )
            if recurrence_duration > timedelta(days=31):
                raise CalendarExchangeError("重复日历事件单次时长不能超过 31 天。")
    elif properties.get("RRULE") or properties.get("RDATE") or properties.get("EXDATE"):
        raise CalendarExchangeError(f"ICS 重复例外项 {uid} 不能另带重复规则。")
    return event


def _parse_recurrence_id(
    property_value: tuple[dict[str, str], str],
    master: dict[str, Any],
    timezone_definitions: dict[str, str],
) -> tuple[str, str]:
    params, raw = property_value
    range_value = params.get("RANGE", "").upper()
    if range_value not in {"", "THISANDFUTURE"}:
        raise CalendarExchangeError(f"ICS 重复例外范围暂不支持：{range_value}；本次导入未应用。")
    is_date = params.get("VALUE", "").upper() == "DATE" or bool(_DATE_RE.fullmatch(raw))
    if is_date != bool(master["allDay"]):
        raise CalendarExchangeError(f"ICS 重复例外项 {master['uid']} 的 RECURRENCE-ID 类型与主事件不一致。")
    if is_date:
        return _parse_date_value(raw).isoformat(), range_value
    timezone_id = params.get("TZID", "")
    if not timezone_id and not raw.endswith("Z"):
        timezone_id = str(master.get("timezoneId", ""))
    occurrence = _parse_datetime_value(raw, timezone_id, timezone_definitions)
    return occurrence.astimezone(_event_timezone(master)).isoformat(timespec="seconds"), range_value


def parse_ics(
    text: str, *, source_name: str = "", allow_empty: bool = False
) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(text, str) or not text.strip():
        raise CalendarExchangeError("ICS 文件为空。")
    if len(text.encode("utf-8")) > 2_000_000:
        raise CalendarExchangeError("ICS 文件不能超过 2 MB。")
    lines = _folded_lines(text.lstrip("\ufeff"))
    if not lines or lines[0].upper() != "BEGIN:VCALENDAR" or lines[-1].upper() != "END:VCALENDAR":
        raise CalendarExchangeError("文件不是完整的 iCalendar（VCALENDAR）文件。")

    calendar_name = source_name.strip()
    calendar_props: dict[str, list[tuple[dict[str, str], str]]] = {}
    filtered_lines, timezone_definitions = _strip_timezone_components(lines)
    event_components: list[dict[str, list[tuple[dict[str, str], str]]]] = []
    current: dict[str, list[tuple[dict[str, str], str]]] | None = None
    nested_component_depth = 0
    for line in filtered_lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            if current is not None:
                raise CalendarExchangeError("ICS 文件包含嵌套的 VEVENT。")
            current = {}
            nested_component_depth = 0
            continue
        if upper == "END:VEVENT":
            if current is None:
                raise CalendarExchangeError("ICS 文件包含没有开始标记的 VEVENT。")
            if nested_component_depth:
                raise CalendarExchangeError("ICS VEVENT 中包含未结束的子组件。")
            event_components.append(current)
            current = None
            continue
        if current is not None and upper.startswith("BEGIN:"):
            nested_component_depth += 1
            continue
        if current is not None and upper.startswith("END:") and nested_component_depth:
            nested_component_depth -= 1
            continue
        if current is not None and nested_component_depth:
            continue
        name, params, value = _parse_content_line(line)
        if current is not None:
            current.setdefault(name, []).append((params, value))
        else:
            calendar_props.setdefault(name, []).append((params, value))
    name_prop = _event_value(calendar_props, "X-WR-CALNAME")
    if name_prop:
        calendar_name = _unescape_text(name_prop[1]).strip() or calendar_name

    masters: dict[str, dict[str, Any]] = {}
    master_components: dict[str, dict[str, list[tuple[dict[str, str], str]]]] = {}
    pending_overrides: list[tuple[str, dict[str, list[tuple[dict[str, str], str]]]]] = []
    for component in event_components:
        if component.get("EXRULE"):
            raise CalendarExchangeError("ICS EXRULE 已废弃且当前无法安全展开；本次导入未应用。")
        uid_prop = _event_value(component, "UID")
        if uid_prop is None or not uid_prop[1].strip():
            raise CalendarExchangeError("ICS 的 VEVENT 缺少 UID，无法安全去重。")
        uid = _unescape_text(uid_prop[1].strip())
        if _event_value(component, "RECURRENCE-ID") is not None:
            pending_overrides.append((uid, component))
            continue
        if uid in master_components:
            raise CalendarExchangeError("ICS 文件中有重复 UID 的主事件，导入已取消以避免误覆盖。")
        master_components[uid] = component

    for uid, component in master_components.items():
        status_prop = _event_value(component, "STATUS")
        if status_prop and status_prop[1].strip().upper() == "CANCELLED":
            continue
        masters[uid] = _build_ics_event(component, uid, calendar_name, timezone_definitions)

    override_keys: dict[str, set[str]] = {}
    for uid, component in pending_overrides:
        master = masters.get(uid)
        if master is None:
            raise CalendarExchangeError(f"ICS 重复例外项 {uid} 找不到对应的主事件。")
        if not master.get("recurrenceRule") and not master.get("recurrenceDates"):
            raise CalendarExchangeError(f"ICS 重复例外项 {uid} 对应的主事件不是重复事件。")
        recurrence_id_prop = _event_value(component, "RECURRENCE-ID")
        assert recurrence_id_prop is not None
        recurrence_id, recurrence_range = _parse_recurrence_id(recurrence_id_prop, master, timezone_definitions)
        seen_keys = override_keys.setdefault(uid, set())
        if recurrence_id in seen_keys:
            raise CalendarExchangeError(f"ICS 重复事件 {uid} 有重复的 RECURRENCE-ID。")
        seen_keys.add(recurrence_id)
        status_prop = _event_value(component, "STATUS")
        if status_prop and status_prop[1].strip().upper() == "CANCELLED":
            override = {"recurrenceId": recurrence_id, "range": recurrence_range, "cancelled": True}
        else:
            override = _build_ics_event(component, uid, calendar_name, timezone_definitions, base=master)
            override.update({"recurrenceId": recurrence_id, "range": recurrence_range, "cancelled": False})
        master.setdefault("recurrenceOverrides", []).append(override)
        if len(master["recurrenceOverrides"]) > 1000:
            raise CalendarExchangeError("单个 ICS 重复事件最多支持 1000 个例外项。")

    events = list(masters.values())
    if len(events) > 500:
        raise CalendarExchangeError("一次最多导入 500 个日历事件。")
    if not events and not allow_empty:
        raise CalendarExchangeError("ICS 文件没有可导入的单次事件。")
    return calendar_name or "外部日历", events


def _todo_date_time(
    property_value: tuple[dict[str, str], str] | None,
    timezone_definitions: dict[str, str],
) -> tuple[str, str]:
    if property_value is None:
        return "", ""
    params, raw = property_value
    declared_type = params.get("VALUE", "").upper()
    is_date = declared_type == "DATE" or (not declared_type and bool(_DATE_RE.fullmatch(raw)))
    if is_date:
        if params.get("TZID"):
            raise CalendarExchangeError("VTODO 的 DATE 值不能同时声明 TZID。")
        return _parse_date_value(raw).isoformat(), ""
    if declared_type not in {"", "DATE-TIME"} or _DATE_RE.fullmatch(raw):
        raise CalendarExchangeError("VTODO 的日期必须是 DATE 或 DATE-TIME。")
    timezone_id = params.get("TZID", "")
    parsed = _parse_datetime_value(raw, timezone_id, timezone_definitions)
    local = parsed.astimezone() if parsed.tzinfo is not None else parsed
    return local.date().isoformat(), local.strftime("%H:%M")


def parse_ical_vtodos(
    text: str, *, source_name: str = ""
) -> tuple[str, list[dict[str, Any]]]:
    """Read standalone VTODO tasks from an iCalendar file or CalDAV object."""
    if not isinstance(text, str) or not text.strip():
        raise CalendarExchangeError("ICS 文件为空。")
    if len(text.encode("utf-8")) > 2_000_000:
        raise CalendarExchangeError("ICS 文件不能超过 2 MB。")
    lines = _folded_lines(text.lstrip("\ufeff"))
    if not lines or lines[0].upper() != "BEGIN:VCALENDAR" or lines[-1].upper() != "END:VCALENDAR":
        raise CalendarExchangeError("文件不是完整的 iCalendar（VCALENDAR）文件。")
    filtered_lines, timezone_definitions = _strip_timezone_components(lines)
    calendar_props: dict[str, list[tuple[dict[str, str], str]]] = {}
    components: list[dict[str, list[tuple[dict[str, str], str]]]] = []
    current: dict[str, list[tuple[dict[str, str], str]]] | None = None
    nested_depth = 0
    other_component_depth = 0
    for line in filtered_lines:
        upper = line.upper()
        if upper == "BEGIN:VTODO":
            if current is not None or other_component_depth:
                raise CalendarExchangeError("ICS 文件包含嵌套的 VTODO。")
            current = {}
            nested_depth = 0
            continue
        if upper == "END:VTODO":
            if current is None:
                raise CalendarExchangeError("ICS 文件包含没有开始标记的 VTODO。")
            components.append(current)
            current = None
            continue
        if current is None:
            if upper.startswith("BEGIN:"):
                other_component_depth += 1
                continue
            if upper.startswith("END:"):
                if other_component_depth:
                    other_component_depth -= 1
                continue
            if other_component_depth:
                continue
            name, params, value = _parse_content_line(line)
            calendar_props.setdefault(name, []).append((params, value))
            continue
        if upper.startswith("BEGIN:"):
            nested_depth += 1
            continue
        if upper.startswith("END:") and nested_depth:
            nested_depth -= 1
            continue
        if nested_depth:
            continue
        name, params, value = _parse_content_line(line)
        current.setdefault(name, []).append((params, value))
    if current is not None:
        raise CalendarExchangeError("ICS 文件有未结束的 VTODO。")
    name_prop = _event_value(calendar_props, "X-WR-CALNAME")
    calendar_name = source_name.strip()
    if name_prop:
        calendar_name = _unescape_text(name_prop[1]).strip() or calendar_name

    tasks: list[dict[str, Any]] = []
    seen_uids: set[str] = set()
    for component in components:
        uid_prop = _event_value(component, "UID")
        summary_prop = _event_value(component, "SUMMARY")
        if uid_prop is None or not uid_prop[1].strip():
            raise CalendarExchangeError("ICS 的 VTODO 缺少 UID，无法安全去重。")
        if summary_prop is None or not _unescape_text(summary_prop[1]).strip():
            raise CalendarExchangeError("ICS 的 VTODO 缺少任务标题。")
        uid = _unescape_text(uid_prop[1].strip())
        if len(uid) > 512 or uid in seen_uids:
            raise CalendarExchangeError("ICS 文件中有重复或过长的 VTODO UID。")
        seen_uids.add(uid)
        if any(component.get(key) for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
            raise CalendarExchangeError(f"VTODO {uid} 使用了重复规则；重复待办暂不导入。")
        title = _unescape_text(summary_prop[1]).strip()
        if len(title) > 60:
            raise CalendarExchangeError(f"VTODO {uid} 的标题超过本机 60 字限制。")
        description_prop = _event_value(component, "DESCRIPTION")
        description = _unescape_text(description_prop[1]).strip() if description_prop else ""
        if len(description) > 2_000:
            raise CalendarExchangeError(f"VTODO {uid} 的描述超过 2000 字限制。")

        start_day, start_time = _todo_date_time(_event_value(component, "DTSTART"), timezone_definitions)
        due_day, due_time = _todo_date_time(_event_value(component, "DUE"), timezone_definitions)
        status_prop = _event_value(component, "STATUS")
        status_value = status_prop[1].strip().upper() if status_prop else "NEEDS-ACTION"
        if status_value not in {"NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"}:
            raise CalendarExchangeError(f"VTODO {uid} 使用了无效的 STATUS。")
        percent_prop = _event_value(component, "PERCENT-COMPLETE")
        try:
            percent_complete = int(percent_prop[1]) if percent_prop else (100 if status_value == "COMPLETED" else 0)
        except ValueError as exc:
            raise CalendarExchangeError(f"VTODO {uid} 的完成百分比无效。") from exc
        if not 0 <= percent_complete <= 100:
            raise CalendarExchangeError(f"VTODO {uid} 的完成百分比须在 0 至 100 之间。")
        done = status_value == "COMPLETED" or (
            status_value != "CANCELLED" and percent_complete == 100
        )
        partial = status_value != "CANCELLED" and (
            status_value == "IN-PROCESS" or 0 < percent_complete < 100
        )
        priority_prop = _event_value(component, "PRIORITY")
        try:
            priority_value = int(priority_prop[1]) if priority_prop else 0
        except ValueError as exc:
            raise CalendarExchangeError(f"VTODO {uid} 的优先级无效。") from exc
        if not 0 <= priority_value <= 9:
            raise CalendarExchangeError(f"VTODO {uid} 的优先级须在 0 至 9 之间。")
        priority = "high" if 1 <= priority_value <= 4 else "low" if priority_value >= 7 else "normal"
        completed_prop = _event_value(component, "COMPLETED")
        completed_at = ""
        if completed_prop:
            completed_day, completed_time = _todo_date_time(completed_prop, timezone_definitions)
            completed_at = f"{completed_day}T{completed_time}:00" if completed_time else completed_day
        url_prop = _event_value(component, "URL")
        url = _unescape_text(url_prop[1]).strip() if url_prop else ""
        if len(url) > 2_048:
            raise CalendarExchangeError(f"VTODO {uid} 的链接过长。")
        tasks.append({
            "uid": uid,
            "title": title,
            "description": description,
            "startDate": start_day,
            "startTime": start_time,
            "dueDate": due_day,
            "dueTime": due_time,
            "done": done,
            "partial": partial,
            "cancelled": status_value == "CANCELLED",
            "priority": priority,
            "percentComplete": percent_complete,
            "completedAt": completed_at,
            "url": url,
        })
        if len(tasks) > 500:
            raise CalendarExchangeError("一次最多导入 500 个 iCalendar 任务。")
    return calendar_name or "外部日历任务", tasks


def normalize_calendar_events(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CalendarExchangeError("本机外部日历事件结构无效。")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        uid = raw.get("uid", raw.get("id"))
        if not isinstance(uid, str) or not uid.strip() or len(uid) > 512 or uid in seen:
            raise CalendarExchangeError("本机日历事件 UID 缺失或重复。")
        title = raw.get("title", "")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise CalendarExchangeError("本机日历事件标题无效。")
        all_day = raw.get("allDay", False)
        if not isinstance(all_day, bool):
            raise CalendarExchangeError("本机日历全天标记无效。")
        try:
            start_date = date.fromisoformat(raw.get("startDate", ""))
            end_date = date.fromisoformat(raw.get("endDate", ""))
        except (TypeError, ValueError) as exc:
            raise CalendarExchangeError("本机日历事件日期无效。") from exc
        if end_date < start_date or (all_day and end_date <= start_date):
            raise CalendarExchangeError("本机日历事件日期范围无效。")
        start_at, end_at = raw.get("startAt", ""), raw.get("endAt", "")
        if not isinstance(start_at, str) or not isinstance(end_at, str):
            raise CalendarExchangeError("本机日历事件时间无效。")
        if not all_day:
            try:
                started = datetime.fromisoformat(start_at)
                ended = datetime.fromisoformat(end_at)
            except ValueError as exc:
                raise CalendarExchangeError("本机日历事件时间无效。") from exc
            try:
                if ended < started:
                    raise CalendarExchangeError("本机日历事件结束时间早于开始时间。")
            except TypeError as exc:
                raise CalendarExchangeError("本机日历事件的起止时间必须使用兼容的时区格式。") from exc
        description, location = raw.get("description", ""), raw.get("location", "")
        transparency = raw.get("transparency", "OPAQUE")
        source = raw.get("sourceCalendar", "外部日历")
        subscription_id = raw.get("subscriptionId", "")
        source_event_uid = raw.get("sourceEventUid", "")
        timezone_id = raw.get("timezoneId", "")
        timezone_definition = raw.get("timezoneDefinition", "")
        recurrence_rule = raw.get("recurrenceRule", "")
        recurrence_dates = raw.get("recurrenceDates", [])
        excluded_dates = raw.get("excludedDates", [])
        recurrence_overrides = raw.get("recurrenceOverrides", [])
        if any(not isinstance(item, str) for item in (
            description, location, source, subscription_id, source_event_uid,
            timezone_id, timezone_definition,
        )):
            raise CalendarExchangeError("本机日历事件说明、地点或来源无效。")
        if not isinstance(transparency, str) or transparency not in {"OPAQUE", "TRANSPARENT"}:
            raise CalendarExchangeError("本机日历事件忙闲属性无效。")
        if (
            len(description) > 2000 or len(location) > 160 or len(source) > 160
            or len(subscription_id) > 80 or len(source_event_uid) > 512
            or len(timezone_id) > 160 or len(timezone_definition) > 64_000
        ):
            raise CalendarExchangeError("本机日历事件字段超出长度限制。")
        if not isinstance(recurrence_rule, str) or not isinstance(recurrence_dates, list) or not isinstance(excluded_dates, list):
            raise CalendarExchangeError("本机日历重复规则结构无效。")
        if len(recurrence_dates) > 1000 or len(excluded_dates) > 1000 or any(
            not isinstance(item, str) for item in [*recurrence_dates, *excluded_dates]
        ):
            raise CalendarExchangeError("本机日历重复日期结构无效。")
        recurrence_start = datetime.combine(start_date, time.min) if all_day else datetime.fromisoformat(start_at)
        if timezone_id and not all_day:
            try:
                event_zone = _timezone_from_definition(timezone_id, timezone_definition)
            except CalendarExchangeError as exc:
                raise CalendarExchangeError(f"本机日历事件使用了无法识别的时区：{timezone_id}") from exc
            recurrence_start = recurrence_start.astimezone(event_zone)
        elif timezone_definition:
            raise CalendarExchangeError("全天事件不能附带时区定义。")
        if recurrence_rule:
            recurrence_rule = _validate_recurrence_rule(recurrence_rule, recurrence_start)
        for recurrence_value in [*recurrence_dates, *excluded_dates]:
            try:
                if all_day:
                    date.fromisoformat(recurrence_value)
                else:
                    recurrence_datetime = datetime.fromisoformat(recurrence_value)
                    if timezone_id and recurrence_datetime.tzinfo is not None:
                        recurrence_datetime.astimezone(_timezone_from_definition(timezone_id, timezone_definition))
            except ValueError as exc:
                raise CalendarExchangeError("本机日历重复日期无效。") from exc
        if recurrence_rule or recurrence_dates:
            duration = (
                timedelta(days=(end_date - start_date).days)
                if all_day
                else datetime.fromisoformat(end_at).astimezone(timezone.utc)
                - datetime.fromisoformat(start_at).astimezone(timezone.utc)
            )
            if duration > timedelta(days=31):
                raise CalendarExchangeError("重复日历事件单次时长不能超过 31 天。")
        if recurrence_overrides and not (recurrence_rule or recurrence_dates):
            raise CalendarExchangeError("本机日历重复例外项找不到可应用的重复规则。")
        normalized = {
            **raw,
            "id": uid,
            "uid": uid,
            "title": title.strip(),
            "description": description,
            "location": location,
            "transparency": transparency,
            "allDay": all_day,
            "startAt": start_at,
            "endAt": end_at,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "timezoneId": timezone_id,
            "timezoneDefinition": timezone_definition,
            "sourceCalendar": source,
            "subscriptionId": subscription_id,
            "sourceEventUid": source_event_uid,
            "recurrenceRule": recurrence_rule,
            "recurrenceDates": recurrence_dates,
            "excludedDates": excluded_dates,
        }
        if not isinstance(recurrence_overrides, list) or len(recurrence_overrides) > 1000:
            raise CalendarExchangeError("本机日历重复例外项结构无效。")
        normalized_overrides: list[dict[str, Any]] = []
        seen_override_ids: set[str] = set()
        for override in recurrence_overrides:
            if not isinstance(override, dict):
                raise CalendarExchangeError("本机日历重复例外项结构无效。")
            recurrence_id = override.get("recurrenceId", "")
            recurrence_range = override.get("range", "")
            cancelled = override.get("cancelled", False)
            if (
                not isinstance(recurrence_id, str) or not recurrence_id or len(recurrence_id) > 64
                or recurrence_range not in {"", "THISANDFUTURE"}
                or not isinstance(cancelled, bool)
            ):
                raise CalendarExchangeError("本机日历重复例外项标识无效。")
            if recurrence_id in seen_override_ids:
                raise CalendarExchangeError("本机日历重复例外项 RECURRENCE-ID 重复。")
            seen_override_ids.add(recurrence_id)
            try:
                date.fromisoformat(recurrence_id) if all_day else datetime.fromisoformat(recurrence_id)
            except ValueError as exc:
                raise CalendarExchangeError("本机日历重复例外项的 RECURRENCE-ID 无效。") from exc
            if cancelled:
                normalized_overrides.append({
                    "recurrenceId": recurrence_id,
                    "range": recurrence_range,
                    "cancelled": True,
                })
                continue
            if override.get("allDay", all_day) is not all_day:
                raise CalendarExchangeError("本机日历重复例外项日期类型不一致。")
            override_title = override.get("title", normalized["title"])
            override_description = override.get("description", normalized["description"])
            override_location = override.get("location", normalized["location"])
            override_transparency = override.get("transparency", normalized["transparency"])
            if not isinstance(override_title, str) or not override_title.strip() or len(override_title) > 160:
                raise CalendarExchangeError("本机日历重复例外项标题无效。")
            if not isinstance(override_description, str) or len(override_description) > 2000:
                raise CalendarExchangeError("本机日历重复例外项说明无效。")
            if not isinstance(override_location, str) or len(override_location) > 160:
                raise CalendarExchangeError("本机日历重复例外项地点无效。")
            if not isinstance(override_transparency, str) or override_transparency not in {"OPAQUE", "TRANSPARENT"}:
                raise CalendarExchangeError("本机日历重复例外项忙闲属性无效。")
            override_timezone_id = override.get("timezoneId", timezone_id)
            override_timezone_definition = override.get("timezoneDefinition", timezone_definition)
            if not isinstance(override_timezone_id, str) or not isinstance(override_timezone_definition, str):
                raise CalendarExchangeError("本机日历重复例外项时区无效。")
            if len(override_timezone_id) > 160 or len(override_timezone_definition) > 64_000:
                raise CalendarExchangeError("本机日历重复例外项时区超出长度限制。")
            override_value = {
                "id": uid,
                "uid": uid,
                "recurrenceId": recurrence_id,
                "range": recurrence_range,
                "cancelled": False,
                "title": override_title.strip(),
                "description": override_description,
                "location": override_location,
                "transparency": override_transparency,
                "allDay": all_day,
                "timezoneId": override_timezone_id,
                "timezoneDefinition": override_timezone_definition,
                "sourceCalendar": source,
                "recurringInstance": True,
            }
            if all_day:
                try:
                    override_start_date = date.fromisoformat(override.get("startDate", ""))
                    override_end_date = date.fromisoformat(override.get("endDate", ""))
                except (TypeError, ValueError) as exc:
                    raise CalendarExchangeError("本机全天重复例外项日期无效。") from exc
                if override_end_date <= override_start_date:
                    raise CalendarExchangeError("本机全天重复例外项结束日期必须晚于开始日期。")
                if override_end_date - override_start_date > timedelta(days=31):
                    raise CalendarExchangeError("重复日历例外项单次时长不能超过 31 天。")
                if override_timezone_id or override_timezone_definition:
                    raise CalendarExchangeError("全天重复例外项不能附带时区。")
                override_value.update({
                    "startAt": "", "endAt": "",
                    "startDate": override_start_date.isoformat(),
                    "endDate": override_end_date.isoformat(),
                })
            else:
                try:
                    override_start_at = datetime.fromisoformat(override.get("startAt", ""))
                    override_end_at = datetime.fromisoformat(override.get("endAt", ""))
                    if override_end_at < override_start_at:
                        raise CalendarExchangeError("本机日历重复例外项结束时间早于开始时间。")
                    if override_end_at.astimezone(timezone.utc) - override_start_at.astimezone(timezone.utc) > timedelta(days=31):
                        raise CalendarExchangeError("重复日历例外项单次时长不能超过 31 天。")
                    if override_timezone_id:
                        _timezone_from_definition(override_timezone_id, override_timezone_definition)
                except (TypeError, ValueError) as exc:
                    raise CalendarExchangeError("本机日历重复例外项时间无效。") from exc
                override_value.update({
                    "startAt": override_start_at.isoformat(timespec="seconds"),
                    "endAt": override_end_at.isoformat(timespec="seconds"),
                    "startDate": override_start_at.astimezone().date().isoformat(),
                    "endDate": override_end_at.astimezone().date().isoformat(),
                })
            normalized_overrides.append(override_value)
        normalized["recurrenceOverrides"] = normalized_overrides
        seen.add(uid)
        result.append(normalized)
    return result


def calendar_occurrences_for_day(events: list[dict[str, Any]], day_key: str) -> list[dict[str, Any]]:
    """Expand supported recurrence sets only across the selected local day."""
    selected = date.fromisoformat(day_key)
    local_zone = get_localzone()
    local_start = datetime.combine(selected, time.min).replace(tzinfo=local_zone)
    local_end = datetime.combine(selected + timedelta(days=1), time.min).replace(tzinfo=local_zone)
    local_start_utc = local_start.astimezone(timezone.utc)
    local_end_utc = local_end.astimezone(timezone.utc)
    result: list[dict[str, Any]] = []

    for event in events:
        recurrence_rule = event.get("recurrenceRule", "")
        recurrence_dates = event.get("recurrenceDates", [])
        excluded_dates = event.get("excludedDates", [])
        recurrence_overrides = event.get("recurrenceOverrides", [])
        if not recurrence_rule and not recurrence_dates and not excluded_dates and not recurrence_overrides:
            result.append(event)
            continue

        all_day = bool(event.get("allDay"))
        if all_day:
            start_day = date.fromisoformat(event["startDate"])
            end_day = date.fromisoformat(event["endDate"])
            start_value = datetime.combine(start_day, time.min)
            duration_days = (end_day - start_day).days
            duration = timedelta(days=duration_days)
            range_start = datetime.combine(selected - timedelta(days=duration_days), time.min)
            range_end = datetime.combine(selected + timedelta(days=1), time.min)
        else:
            start_value = datetime.fromisoformat(event["startAt"])
            end_value = datetime.fromisoformat(event["endAt"])
            event_zone = _event_timezone(event)
            if start_value.tzinfo is None:
                start_value = start_value.replace(tzinfo=event_zone)
            else:
                start_value = start_value.astimezone(event_zone)
            if end_value.tzinfo is None:
                end_value = end_value.replace(tzinfo=event_zone)
            else:
                end_value = end_value.astimezone(event_zone)
            duration = end_value.astimezone(timezone.utc) - start_value.astimezone(timezone.utc)
            range_start = (local_start_utc - duration).astimezone(event_zone)
            range_end = local_end_utc.astimezone(event_zone)

        values = rruleset(cache=True)
        # RFC 5545 treats DTSTART as the first member of the recurrence set,
        # even when the rule's selectors would otherwise skip that date.
        values.rdate(start_value)
        if recurrence_rule:
            values.rrule(rrulestr(recurrence_rule, dtstart=start_value))
        for raw_date in recurrence_dates:
            occurrence = (
                datetime.combine(date.fromisoformat(raw_date), time.min)
                if all_day
                else datetime.fromisoformat(raw_date)
            )
            if not all_day:
                occurrence = occurrence.replace(tzinfo=event_zone) if occurrence.tzinfo is None else occurrence.astimezone(event_zone)
            values.rdate(occurrence)
        for raw_date in excluded_dates:
            excluded = (
                datetime.combine(date.fromisoformat(raw_date), time.min)
                if all_day
                else datetime.fromisoformat(raw_date)
            )
            if not all_day:
                excluded = excluded.replace(tzinfo=event_zone) if excluded.tzinfo is None else excluded.astimezone(event_zone)
            values.exdate(excluded)

        override_map: dict[str, dict[str, Any]] = {}
        range_overrides: list[tuple[date | datetime, dict[str, Any], timedelta]] = []
        range_padding = timedelta(0)
        range_padding_days = 0
        range_duration_padding = timedelta(0)
        range_duration_padding_days = 0
        for item in recurrence_overrides:
            recurrence_id = str(item.get("recurrenceId", ""))
            if item.get("range") != "THISANDFUTURE":
                override_map[recurrence_id] = item
                continue
            if all_day:
                threshold: date | datetime = date.fromisoformat(recurrence_id)
                actual_start_day = date.fromisoformat(item["startDate"]) if not item.get("cancelled") else threshold
                shift_days = (actual_start_day - threshold).days
                range_padding_days = max(range_padding_days, abs(shift_days))
                if not item.get("cancelled"):
                    override_duration_days = (date.fromisoformat(item["endDate"]) - date.fromisoformat(item["startDate"])).days
                    range_duration_padding_days = max(range_duration_padding_days, override_duration_days - duration_days, 0)
                range_overrides.append((threshold, item, timedelta(days=shift_days)))
            else:
                threshold_dt = datetime.fromisoformat(recurrence_id)
                threshold_dt = (
                    threshold_dt.replace(tzinfo=event_zone)
                    if threshold_dt.tzinfo is None
                    else threshold_dt.astimezone(event_zone)
                )
                if item.get("cancelled"):
                    shift = timedelta(0)
                else:
                    moved_start = datetime.fromisoformat(item["startAt"])
                    moved_zone = _event_timezone(item)
                    moved_local = moved_start.astimezone(moved_zone).replace(tzinfo=None)
                    shift = moved_local - threshold_dt.replace(tzinfo=None)
                range_padding = max(range_padding, abs(shift))
                if not item.get("cancelled"):
                    moved_end = datetime.fromisoformat(item["endAt"])
                    override_duration = moved_end.astimezone(timezone.utc) - moved_start.astimezone(timezone.utc)
                    range_duration_padding = max(range_duration_padding, override_duration - duration, timedelta(0))
                range_overrides.append((threshold_dt, item, shift))
        range_overrides.sort(key=lambda entry: entry[0])
        if all_day:
            range_start -= timedelta(days=range_padding_days + range_duration_padding_days)
            range_end += timedelta(days=range_padding_days)
        elif range_padding or range_duration_padding:
            range_start = (range_start - range_padding - range_duration_padding).astimezone(event_zone)
            range_end = (range_end + range_padding).astimezone(event_zone)

        range_index = 0
        active_range: tuple[date | datetime, dict[str, Any], timedelta] | None = None
        for occurrence_start in values.between(range_start, range_end, inc=True):
            if all_day:
                occurrence_day = occurrence_start.date()
                occurrence_key = occurrence_day.isoformat()
                while range_index < len(range_overrides) and range_overrides[range_index][0] <= occurrence_day:
                    active_range = range_overrides[range_index]
                    range_index += 1
                if occurrence_key in override_map or (active_range and active_range[1].get("cancelled")):
                    continue
                if active_range:
                    range_event, shift_days = active_range[1], int(active_range[2].total_seconds() // 86400)
                    actual_day = occurrence_day + timedelta(days=shift_days)
                    actual_duration = (
                        date.fromisoformat(range_event["endDate"])
                        - date.fromisoformat(range_event["startDate"])
                    ).days
                    occurrence_end = actual_day + timedelta(days=actual_duration)
                    effective = {
                        **event,
                        "title": range_event["title"],
                        "description": range_event["description"],
                        "location": range_event["location"],
                        "transparency": range_event["transparency"],
                    }
                else:
                    actual_day = occurrence_day
                    occurrence_end = actual_day + timedelta(days=duration_days)
                    effective = event
                if actual_day < selected + timedelta(days=1) and occurrence_end > selected:
                    result.append({
                        **effective,
                        "id": f"{event['uid']}@{occurrence_key}",
                        "startDate": actual_day.isoformat(),
                        "endDate": occurrence_end.isoformat(),
                        "recurringInstance": True,
                    })
            else:
                original_start = occurrence_start.astimezone(event_zone)
                occurrence_key = original_start.isoformat(timespec="seconds")
                while range_index < len(range_overrides) and range_overrides[range_index][0] <= original_start:
                    active_range = range_overrides[range_index]
                    range_index += 1
                if occurrence_key in override_map or (active_range and active_range[1].get("cancelled")):
                    continue
                effective = event
                if active_range:
                    range_event, shift = active_range[1], active_range[2]
                    range_zone = _event_timezone(range_event)
                    actual_local = original_start.replace(tzinfo=None) + shift
                    actual_start = actual_local.replace(tzinfo=range_zone)
                    range_start_at = datetime.fromisoformat(range_event["startAt"])
                    range_end_at = datetime.fromisoformat(range_event["endAt"])
                    range_duration = range_end_at.astimezone(timezone.utc) - range_start_at.astimezone(timezone.utc)
                    occurrence_end_utc = actual_start.astimezone(timezone.utc) + range_duration
                    occurrence_end = occurrence_end_utc.astimezone(range_zone)
                    effective = {
                        **event,
                        "title": range_event["title"],
                        "description": range_event["description"],
                        "location": range_event["location"],
                        "transparency": range_event["transparency"],
                    }
                else:
                    actual_start = original_start
                    occurrence_end_utc = actual_start.astimezone(timezone.utc) + duration
                    occurrence_end = occurrence_end_utc.astimezone(event_zone)
                occurrence_start_utc = actual_start.astimezone(timezone.utc)
                intersects = (
                    occurrence_start_utc < local_end_utc and occurrence_end_utc > local_start_utc
                ) or (
                    occurrence_end_utc == occurrence_start_utc
                    and local_start_utc <= occurrence_start_utc < local_end_utc
                )
                if not intersects:
                    continue
                result.append({
                    **effective,
                    "id": f"{event['uid']}@{occurrence_key}",
                    "startAt": actual_start.isoformat(timespec="seconds"),
                    "endAt": occurrence_end.isoformat(timespec="seconds"),
                    "startDate": actual_start.astimezone().date().isoformat(),
                    "endDate": occurrence_end.astimezone().date().isoformat(),
                    "recurringInstance": True,
                })
        for recurrence_id, override in override_map.items():
            if override.get("cancelled"):
                continue
            if all_day:
                override_start = date.fromisoformat(override["startDate"])
                override_end = date.fromisoformat(override["endDate"])
                if override_start < selected + timedelta(days=1) and override_end > selected:
                    result.append({
                        **event, **override,
                        "id": f"{event['uid']}@{recurrence_id}",
                        "recurringInstance": True,
                    })
            else:
                override_start = datetime.fromisoformat(override["startAt"])
                override_end = datetime.fromisoformat(override["endAt"])
                override_start_utc = override_start.astimezone(timezone.utc)
                override_end_utc = override_end.astimezone(timezone.utc)
                intersects = (
                    override_start_utc < local_end_utc and override_end_utc > local_start_utc
                ) or (
                    override_start_utc == override_end_utc
                    and local_start_utc <= override_start_utc < local_end_utc
                )
                if intersects:
                    result.append({
                        **event, **override,
                        "id": f"{event['uid']}@{recurrence_id}",
                        "recurringInstance": True,
                    })
    return result


def _escape_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n").replace(";", "\\;").replace(",", "\\,")


def _fold_line(line: str, max_octets: int = 75) -> list[str]:
    pieces: list[str] = []
    current = ""
    current_size = 0
    limit = max_octets
    for char in line:
        size = len(char.encode("utf-8"))
        if current and current_size + size > limit:
            pieces.append(current)
            current = " "
            current_size = 1
            limit = max_octets
        current += char
        current_size += size
    pieces.append(current)
    return pieces


def _utc_ical(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def task_events_to_ics(tasks: list[dict[str, Any]], start_date: str, end_date: str, now: datetime) -> str:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise CalendarExchangeError("ICS 导出日期无效。") from exc
    if start > end:
        raise CalendarExchangeError("ICS 导出开始日期不能晚于结束日期。")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FLUKE//Planner//ZH",
        "CALSCALE:GREGORIAN", "X-WR-CALNAME:FLUKE 日程",
    ]
    stamp = _utc_ical(now if now.tzinfo is not None else now.astimezone())
    for task in tasks:
        data = task.get("data") if isinstance(task.get("data"), dict) else {}
        day_key = str(data.get("plannedDate", "") or task.get("date", ""))
        try:
            task_day = date.fromisoformat(day_key)
        except ValueError:
            continue
        if not start <= task_day <= end:
            continue
        task_id = str(task.get("id", "")).strip()
        title = str(data.get("title", "未命名待办")).strip() or "未命名待办"
        planned_start = str(data.get("plannedStart", "") or data.get("time", ""))
        try:
            estimate = int(data.get("estimateMinutes", 30))
        except (TypeError, ValueError):
            estimate = 30
        estimate = min(480, max(5, estimate))
        lines.extend(("BEGIN:VEVENT", f"UID:task-{_escape_text(task_id)}@fluke.local", f"DTSTAMP:{stamp}"))
        if planned_start:
            try:
                hour, minute = (int(part) for part in planned_start.split(":"))
                started_local = datetime.combine(task_day, time(hour, minute), tzinfo=get_localzone())
            except (ValueError, TypeError):
                started_local = datetime.combine(task_day, time(9, 0), tzinfo=get_localzone())
            ended_local = started_local + timedelta(minutes=estimate)
            lines.extend((f"DTSTART:{_utc_ical(started_local)}", f"DTEND:{_utc_ical(ended_local)}"))
        else:
            lines.extend((
                f"DTSTART;VALUE=DATE:{task_day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(task_day + timedelta(days=1)).strftime('%Y%m%d')}",
            ))
        lines.append(f"SUMMARY:{_escape_text(title)}")
        note = str(data.get("note", ""))
        project = str(data.get("project", ""))
        tags = data.get("tags", [])
        details = [note] if note else []
        if project:
            details.append(f"项目：{project}")
        if isinstance(tags, list) and tags:
            details.append("标签：" + ", ".join(str(tag) for tag in tags))
        if details:
            lines.append(f"DESCRIPTION:{_escape_text(chr(10).join(details))}")
        if data.get("done"):
            lines.extend(("STATUS:CONFIRMED", "X-FLUKE-DONE:TRUE"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(piece for line in lines for piece in _fold_line(line)) + "\r\n"


def write_ics_file(target_path: str | Path, text: str) -> Path:
    target = Path(target_path).expanduser()
    if target.suffix.lower() != ".ics":
        raise CalendarExchangeError("iCalendar 文件须使用 .ics 扩展名。")
    parent = target.parent.resolve()
    if not parent.is_dir():
        raise CalendarExchangeError("iCalendar 保存文件夹不存在。")
    handle: int | None = None
    temporary: str | None = None
    try:
        handle, temporary = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".tmp", dir=parent)
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            handle = None
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
        return target.resolve()
    finally:
        if handle is not None:
            os.close(handle)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
