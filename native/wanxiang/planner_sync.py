"""Pure local planner-sync protocol operations, independent of transport."""

from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from typing import Any


FORMAT = "wanxiang-planner-sync"
VERSION = 1
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_DEVICE_ID = re.compile(r"^[A-Za-z0-9-]{8,80}$")
_DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_device_id(value: Any) -> str:
    return value if isinstance(value, str) and _DEVICE_ID.fullmatch(value) else ""


def _js_number(value: Any) -> float | int:
    """The small JSON-value subset of JavaScript Number() used by vectors."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0
        try:
            if re.fullmatch(r"0[xX][0-9a-fA-F]+", value):
                return int(value[2:], 16)
            if re.fullmatch(r"0[bB][01]+", value):
                return int(value[2:], 2)
            if re.fullmatch(r"0[oO][0-7]+", value):
                return int(value[2:], 8)
            number = float(value)
            return int(number) if number.is_integer() else number
        except (OverflowError, ValueError):
            return math.nan
    if isinstance(value, list):
        if not value:
            return 0
        if len(value) == 1:
            return _js_number(value[0] if not isinstance(value[0], (dict, list)) else _js_string(value[0]))
    return math.nan


def _is_safe_counter(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float):
        return math.isfinite(value) and value.is_integer() and 0 <= value <= _MAX_SAFE_INTEGER
    return 0 <= value <= _MAX_SAFE_INTEGER


def normalize_vector(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int | float] = {}
    for key in sorted(value)[:1000]:
        counter = _js_number(value[key])
        if normalize_device_id(key) and _is_safe_counter(counter):
            result[key] = int(counter)
    return result


def has_valid_vector(value: Any) -> bool:
    return isinstance(value, dict) and len(value) <= 1000 and all(
        normalize_device_id(device) and _is_safe_counter(counter)
        for device, counter in value.items()
    )


def merge_vectors(*values: Any) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    for value in values:
        for device, counter in normalize_vector(value).items():
            result[device] = max(result.get(device, 0), counter)
    return dict(sorted(result.items()))


def compare_vectors(left_value: Any, right_value: Any) -> str:
    left, right = normalize_vector(left_value), normalize_vector(right_value)
    left_higher = any(left.get(device, 0) > right.get(device, 0) for device in left.keys() | right.keys())
    right_higher = any(right.get(device, 0) > left.get(device, 0) for device in left.keys() | right.keys())
    if left_higher and right_higher:
        return "concurrent"
    if left_higher:
        return "dominates"
    if right_higher:
        return "dominated"
    return "equal"


def _js_truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str):
        return bool(value)
    return True


def _js_string(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, list):
        return ",".join("" if item is None else _js_string(item) for item in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(value)


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def is_syncable_task(record: Any) -> bool:
    if not isinstance(record, dict) or record.get("type") != "planner" or _js_truthy(record.get("sample")):
        return False
    data = record.get("data")
    if not isinstance(data, (dict, list)) or not _js_truthy(data):
        return False
    external = data.get("externalTodo") if isinstance(data, dict) else None
    return not (isinstance(external, dict) and _js_truthy(external.get("provider")))


def _task_content(record: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(record)
    value.pop("remoteId", None)
    value.pop("webdavSyncVersion", None)
    value["sample"] = False
    return value


def _task_core(record: dict[str, Any]) -> dict[str, Any]:
    value = _task_content(record)
    data = value.get("data")
    if isinstance(data, dict):
        data.pop("sessions", None)
        data.pop("trackedSeconds", None)
    return value


def _task_version(record: Any, fallback: Any) -> dict[str, int | float]:
    version = normalize_vector(record.get("webdavSyncVersion") if isinstance(record, dict) else None)
    return version or normalize_vector(fallback)


def _normalize_task(raw: Any, fallback_vector: Any) -> dict[str, Any] | None:
    if not is_syncable_task(raw):
        return None
    task_id = raw.get("id")
    data = raw.get("data")
    task_date = raw.get("date")
    if (
        not isinstance(task_id, str) or not task_id or len(task_id) > 180
        or not isinstance(task_date, str) or not _DATE_SHAPE.fullmatch(task_date)
        or isinstance(data, list)
        or (raw.get("webdavSyncVersion") is not None and not has_valid_vector(raw.get("webdavSyncVersion")))
    ):
        return None
    record = _task_content(raw)
    record["webdavSyncVersion"] = _task_version(raw, fallback_vector)
    return record


def normalize_tombstones(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: dict[str, dict[str, Any]] = {}
    for item in value[-100_000:]:
        item_id = item.get("id") if isinstance(item, dict) and isinstance(item.get("id"), str) else ""
        version = normalize_vector(item.get("version") if isinstance(item, dict) else None)
        if not item_id or len(item_id) > 180 or not version:
            continue
        result[item_id] = {"id": item_id, "version": merge_vectors(result.get(item_id, {}).get("version"), version)}
    return [result[key] for key in sorted(result)]


def _normalize_variant(value: Any, fallback_vector: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    item_id = value.get("id") if isinstance(value.get("id"), str) else ""
    raw_version = value.get("version")
    if raw_version is not None and not has_valid_vector(raw_version):
        return None
    version_source = raw_version if _js_truthy(raw_version) else fallback_vector
    if not has_valid_vector(version_source):
        return None
    version = normalize_vector(version_source)
    if not item_id or len(item_id) > 180 or not version:
        return None
    if value.get("deleted") is True:
        return {"id": item_id, "deleted": True, "version": version}
    record = _normalize_task(value.get("record"), version)
    return {"id": item_id, "deleted": False, "version": version, "record": record} if record and record.get("id") == item_id else None


def _normalize_conflict(value: Any, fallback_vector: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        return None
    variants = value.get("variants") if isinstance(value.get("variants"), list) else []
    unique: dict[str, dict[str, Any]] = {}
    for item in variants:
        normalized = _normalize_variant(item, fallback_vector)
        if normalized and normalized["id"] == value["id"]:
            unique.setdefault(_json_key(normalized), normalized)
    return {"id": value["id"], "variants": list(unique.values())} if len(unique) > 1 else None


def normalize_conflicts(value: Any, fallback_vector: Any = None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [conflict for item in value[:20_000] if (conflict := _normalize_conflict(item, fallback_vector or {}))]


def normalize_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("format") != FORMAT or type(value.get("version")) is not int or value["version"] != VERSION:
        return None
    device_id = normalize_device_id(value.get("deviceId"))
    raw_vector = value.get("vector")
    if not device_id or not has_valid_vector(raw_vector):
        return None
    vector = normalize_vector(raw_vector)
    raw_tasks = value.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) > 50_000:
        return None
    tasks = [_normalize_task(item, vector) for item in raw_tasks]
    if any(not task or not task["webdavSyncVersion"] for task in tasks):
        return None
    raw_tombstones = value.get("tombstones", [])
    if not isinstance(raw_tombstones, list) or len(raw_tombstones) > 100_000 or any(
        not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
        or len(item["id"]) > 180 or not has_valid_vector(item.get("version"))
        or not normalize_vector(item.get("version"))
        for item in raw_tombstones
    ):
        return None
    tombstones = normalize_tombstones(raw_tombstones)
    raw_conflicts = value.get("conflicts", [])
    if not isinstance(raw_conflicts, list) or len(raw_conflicts) > 20_000:
        return None
    conflicts = normalize_conflicts(raw_conflicts, vector)
    if len(conflicts) != len(raw_conflicts):
        return None
    return {"format": FORMAT, "version": VERSION, "deviceId": device_id, "vector": vector,
            "tasks": tasks, "tombstones": tombstones, "conflicts": conflicts}


def _changed_planner_records(previous: Any, current: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    previous_records = previous.get("records") if isinstance(previous, dict) else None
    before = {
        record.get("id"): _task_content(record)
        for record in previous_records if is_syncable_task(record)
    } if isinstance(previous_records, list) else {}
    after: dict[Any, dict[str, Any]] = {}
    current_records = current.get("records", []) if isinstance(current, dict) else []
    if isinstance(current_records, list):
        after = {record.get("id"): record for record in current_records if is_syncable_task(record)}
    changed = [record for task_id, record in after.items() if task_id not in before or _json_key(_task_content(before[task_id])) != _json_key(_task_content(record))]
    deleted = [task_id for task_id in before if task_id not in after]
    return changed, deleted


def stamp_local_changes(previous: Any, current: Any, device_id: Any) -> bool:
    device = normalize_device_id(device_id)
    if not device or not isinstance(current, dict) or not isinstance(current.get("records"), list):
        return False
    if not isinstance(current.get("settings"), dict):
        current["settings"] = {}
    changed, deleted = _changed_planner_records(previous, current)
    if not changed and not deleted:
        return False
    settings = current["settings"]
    vector = normalize_vector(settings.get("webdavPlannerVector"))
    max_seen = max([0, *vector.values()])
    vector[device] = max(vector.get(device, 0), max_seen) + 1
    settings["webdavPlannerVector"] = vector
    existing = {item["id"]: item for item in normalize_tombstones(settings.get("webdavPlannerTombstones"))}
    for record in changed:
        record["webdavSyncVersion"] = dict(vector)
        existing.pop(record.get("id"), None)
    for task_id in deleted:
        existing[task_id] = {"id": task_id, "version": dict(vector)}
    settings["webdavPlannerTombstones"] = list(existing.values())
    return True


def snapshot_from_state(state: Any, device_id: Any) -> dict[str, Any]:
    device = normalize_device_id(device_id)
    if not device:
        raise TypeError("A stable planner sync device ID is required.")
    settings = state.get("settings") or {} if isinstance(state, dict) else {}
    vector = normalize_vector(settings.get("webdavPlannerVector") if isinstance(settings, dict) else None)
    records = state.get("records", []) if isinstance(state, dict) else []
    tasks = []
    if isinstance(records, list):
        for record in records:
            if not is_syncable_task(record):
                continue
            record_version = normalize_vector(record.get("webdavSyncVersion"))
            task = _normalize_task(record, record_version or {device: 0})
            if task:
                tasks.append(task)
    return {"format": FORMAT, "version": VERSION, "deviceId": device, "vector": vector, "tasks": tasks,
            "tombstones": normalize_tombstones(settings.get("webdavPlannerTombstones") if isinstance(settings, dict) else None),
            "conflicts": normalize_conflicts(settings.get("webdavPlannerConflicts") if isinstance(settings, dict) else None, vector)}


def _numeric_or_zero(value: Any) -> int | float:
    number = _js_number(value)
    return number if _js_truthy(number) else 0


def _merge_sessions(*values: Any) -> list[dict[str, Any]]:
    sessions: dict[tuple[str, str], dict[str, Any]] = {}
    for session in (session for value in values if isinstance(value, list) for session in value):
        if not isinstance(session, dict) or not isinstance(session.get("id"), str) or not session["id"]:
            continue
        session_date = session.get("date")
        key = (session["id"], _js_string(session_date if _js_truthy(session_date) else ""))
        previous = sessions.get(key)
        if previous is None:
            sessions[key] = deepcopy(session)
        else:
            merged = {**previous, **session}
            merged["seconds"] = max(_numeric_or_zero(previous.get("seconds")), _numeric_or_zero(session.get("seconds")))
            starts = [item for item in (previous.get("startedAt"), session.get("startedAt")) if _js_truthy(item)]
            ends = [item for item in (previous.get("endedAt"), session.get("endedAt")) if _js_truthy(item)]
            merged["startedAt"] = min(starts, key=_js_string) if starts else ""
            merged["endedAt"] = max(ends, key=_js_string) if ends else ""
            sessions[key] = merged
    return sorted(sessions.values(), key=lambda item: (
        _js_string(item.get("date") if _js_truthy(item.get("date")) else ""),
        _js_string(item.get("startedAt") if _js_truthy(item.get("startedAt")) else ""),
        item["id"],
    ))


def _stable_variant_key(variant: dict[str, Any]) -> str:
    # Preserve the protocol's key order: version sorts before record selection.
    version = _json_key(normalize_vector(variant.get("version")))
    record = _json_key(variant.get("record") or None)
    deleted = "true" if _js_truthy(variant.get("deleted")) else "false"
    return f'{{"version":{version},"record":{record},"deleted":{deleted}}}'


def _merge_variants_for_id(task_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    variants = list({_stable_variant_key(item): item for item in candidates}.values())
    while True:
        pair = None
        live = [item for item in variants if not item.get("deleted")]
        for index, left in enumerate(live):
            for right in live[index + 1:]:
                if _json_key(_task_core(left["record"])) != _json_key(_task_core(right["record"])):
                    continue
                relation = compare_vectors(left["version"], right["version"])
                if relation in {"concurrent", "equal"}:
                    pair = (left, right)
                    break
            if pair:
                break
        if not pair:
            break
        left, right = pair
        record = deepcopy(left["record"])
        data = record.setdefault("data", {})
        merged_sessions = _merge_sessions(left["record"].get("data", {}).get("sessions") if isinstance(left["record"].get("data"), dict) else None,
                                          right["record"].get("data", {}).get("sessions") if isinstance(right["record"].get("data"), dict) else None)
        data["sessions"] = merged_sessions
        data["trackedSeconds"] = max(
            _numeric_or_zero(left["record"].get("data", {}).get("trackedSeconds") if isinstance(left["record"].get("data"), dict) else 0),
            _numeric_or_zero(right["record"].get("data", {}).get("trackedSeconds") if isinstance(right["record"].get("data"), dict) else 0),
            sum((_numeric_or_zero(session.get("seconds")) for session in merged_sessions), 0),
        )
        version = merge_vectors(left["version"], right["version"])
        record["webdavSyncVersion"] = version
        variants = [item for item in variants if item is not left and item is not right]
        variants.append({"id": task_id, "deleted": False, "version": version, "record": record})

    deletes = [item for item in variants if item.get("deleted")]
    if len(deletes) > 1:
        version = merge_vectors(*(item["version"] for item in deletes))
        variants = [item for item in variants if not item.get("deleted")]
        variants.append({"id": task_id, "deleted": True, "version": version})
    variants = [candidate for index, candidate in enumerate(variants) if not any(
        other_index != index and compare_vectors(other["version"], candidate["version"]) == "dominates"
        for other_index, other in enumerate(variants)
    )]

    tombstone = next((item for item in variants if item.get("deleted")), None)
    live = [item for item in variants if not item.get("deleted")]
    if tombstone:
        relations = [compare_vectors(item["version"], tombstone["version"]) for item in live]
        if "concurrent" in relations:
            variants = [item for item, relation in zip(live, relations) if relation != "dominated"] + [tombstone]
        elif "dominates" in relations:
            variants = [item for item, relation in zip(live, relations) if relation == "dominates"]
        else:
            variants = [tombstone]
    else:
        variants = live
    task_variants = [item for item in variants if not item.get("deleted")]
    selected = min(task_variants, key=_stable_variant_key) if task_variants else None
    conflict = {"id": task_id, "variants": [{**item, "version": normalize_vector(item["version"])} for item in variants]} if len(variants) > 1 else None
    return {"selected": selected, "tombstone": next((item for item in variants if item.get("deleted")), None), "conflict": conflict}


def merge_snapshots(*input_values: Any) -> dict[str, Any]:
    snapshots = [snapshot for value in input_values if (snapshot := normalize_snapshot(value))]
    grouped: dict[str, list[dict[str, Any]]] = {}

    def add(variant: dict[str, Any]) -> None:
        grouped.setdefault(variant["id"], []).append(variant)

    for snapshot in snapshots:
        for record in snapshot["tasks"]:
            add({"id": record["id"], "deleted": False, "version": record["webdavSyncVersion"], "record": record})
        for item in snapshot["tombstones"]:
            add({"id": item["id"], "deleted": True, "version": item["version"]})
        for conflict in snapshot["conflicts"]:
            for variant in conflict["variants"]:
                add(variant)
    tasks: list[dict[str, Any]] = []
    tombstones: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for task_id, candidates in grouped.items():
        result = _merge_variants_for_id(task_id, candidates)
        if result["selected"]:
            tasks.append(result["selected"]["record"])
        if result["tombstone"]:
            tombstones.append({"id": task_id, "version": result["tombstone"]["version"]})
        if result["conflict"]:
            conflicts.append(result["conflict"])
    vector = merge_vectors(*(item["vector"] for item in snapshots),
                           *(item["webdavSyncVersion"] for item in tasks),
                           *(item["version"] for item in tombstones))
    tasks.sort(key=lambda item: (item["date"], _js_string(item.get("data", {}).get("title") or ""), item["id"]))
    tombstones.sort(key=lambda item: item["id"])
    conflicts.sort(key=lambda item: item["id"])
    return {"format": FORMAT, "version": VERSION, "deviceId": snapshots[0]["deviceId"] if snapshots else "",
            "vector": vector, "tasks": tasks, "tombstones": tombstones, "conflicts": conflicts}


def apply_merged_snapshot(state: Any, merged_value: Any) -> bool:
    merged = normalize_snapshot(merged_value)
    if not merged or not isinstance(state, dict) or not isinstance(state.get("records"), list):
        return False
    previous_by_id = {record.get("id"): record for record in state["records"] if is_syncable_task(record)}
    keep = [record for record in state["records"] if not is_syncable_task(record)]
    tasks = []
    for record in merged["tasks"]:
        local = previous_by_id.get(record["id"])
        task = {**record, "remoteId": local["remoteId"]} if isinstance(local, dict) and _js_truthy(local.get("remoteId")) else record
        tasks.append(task)
    state["records"] = keep + tasks
    if not isinstance(state.get("settings"), dict):
        state["settings"] = {}
    state["settings"]["webdavPlannerVector"] = merged["vector"]
    state["settings"]["webdavPlannerTombstones"] = merged["tombstones"]
    state["settings"]["webdavPlannerConflicts"] = merged["conflicts"]
    return True


def _array_item(values: Any, index: Any) -> Any:
    if not isinstance(values, list):
        return None
    if isinstance(index, str) and index.isdigit():
        index = int(index)
    if isinstance(index, float) and math.isfinite(index) and index.is_integer():
        index = int(index)
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    return values[index] if 0 <= index < len(values) else None


def resolve_conflict(state: Any, task_id: Any, variant_index: Any, device_id: Any, keep_both: Any = False) -> bool:
    key = _js_string(task_id if _js_truthy(task_id) else "")
    device = normalize_device_id(device_id)
    if not isinstance(state, dict):
        return False
    settings = state.get("settings")
    conflicts = settings.get("webdavPlannerConflicts") if isinstance(settings, dict) else None
    conflicts = conflicts if isinstance(conflicts, list) else []
    conflict = next((item for item in conflicts if isinstance(item, dict) and item.get("id") == key), None)
    variants = conflict.get("variants") if isinstance(conflict, dict) else None
    selected = _array_item(variants, variant_index)
    if not conflict or not isinstance(selected, dict) or not device:
        return False
    if not isinstance(settings, dict):
        state["settings"] = settings = {}
    version = merge_vectors(settings.get("webdavPlannerVector"), *(item.get("version") for item in variants if isinstance(item, dict)))
    next_version = {**version, device: max([0, *version.values()]) + 1}
    records = state.get("records") if isinstance(state.get("records"), list) else []
    existing = next((record for record in records if isinstance(record, dict) and record.get("id") == key and is_syncable_task(record)), None)
    state["records"] = [record for record in records if not (isinstance(record, dict) and record.get("id") == key and is_syncable_task(record))]
    seen_sessions: set[tuple[str, str]] = set()
    if not selected.get("deleted"):
        chosen = deepcopy(selected["record"])
        chosen["webdavSyncVersion"] = next_version
        if isinstance(existing, dict) and _js_truthy(existing.get("remoteId")):
            chosen["remoteId"] = existing["remoteId"]
        if _js_truthy(keep_both):
            data = chosen.get("data") if isinstance(chosen.get("data"), dict) else {}
            chosen["data"] = data
            for session in data.get("sessions", []) if isinstance(data.get("sessions"), list) else []:
                if isinstance(session, dict) and isinstance(session.get("id"), str):
                    seen_sessions.add((session["id"], _js_string(session.get("date") if _js_truthy(session.get("date")) else "")))
        else:
            live_variants = [item for item in variants if isinstance(item, dict) and not item.get("deleted")]
            chosen_data = chosen.setdefault("data", {})
            chosen_data["sessions"] = _merge_sessions(*(
                item.get("record", {}).get("data", {}).get("sessions")
                if isinstance(item.get("record"), dict) and isinstance(item.get("record", {}).get("data"), dict) else None
                for item in live_variants
            ))
            chosen_data["trackedSeconds"] = max(
                *[_numeric_or_zero(item.get("record", {}).get("data", {}).get("trackedSeconds"))
                  for item in live_variants if isinstance(item.get("record"), dict) and isinstance(item.get("record", {}).get("data"), dict)],
                sum((_numeric_or_zero(session.get("seconds")) for session in chosen_data["sessions"]), 0),
            )
        state["records"].append(chosen)

    if _js_truthy(keep_both):
        for index, alternative in enumerate(variants):
            if index == variant_index or not isinstance(alternative, dict) or alternative.get("deleted"):
                continue
            copy = deepcopy(alternative["record"])
            copy["id"] = f"{key}:copy:{device}:{next_version[device]}:{index}"[:180]
            copy["remoteId"] = ""
            copy["webdavSyncVersion"] = next_version
            data = copy.get("data") if isinstance(copy.get("data"), dict) else {}
            sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []
            kept = []
            removed_seconds: int | float = 0
            for session in sessions:
                session_key = (session.get("id"), _js_string(session.get("date") if _js_truthy(session.get("date")) else "")) if isinstance(session, dict) else (None, "")
                if session_key not in seen_sessions:
                    seen_sessions.add(session_key)
                    kept.append(session)
                else:
                    removed_seconds += _numeric_or_zero(session.get("seconds")) if isinstance(session, dict) else 0
            copy["data"] = {**data, "sessions": kept,
                            "trackedSeconds": max(sum((_numeric_or_zero(item.get("seconds")) for item in kept if isinstance(item, dict)), 0),
                                                  _numeric_or_zero(data.get("trackedSeconds")) - removed_seconds),
                            "title": f"{data.get('title') or '未命名任务'}（并发副本）", "webdavConflictOf": key}
            state["records"].append(copy)
    settings["webdavPlannerVector"] = next_version
    tombstones = {item["id"]: item for item in normalize_tombstones(settings.get("webdavPlannerTombstones"))}
    if selected.get("deleted"):
        tombstones[key] = {"id": key, "version": next_version}
    else:
        tombstones.pop(key, None)
    settings["webdavPlannerTombstones"] = list(tombstones.values())
    settings["webdavPlannerConflicts"] = [item for item in conflicts if not isinstance(item, dict) or item.get("id") != key]
    return True
