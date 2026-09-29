"""Small JSON helpers shared by repositories."""

import json
import math
from typing import Any


def copy_json(
    value: Any,
    label: str,
    error_type: type[Exception],
    *,
    compact: bool = False,
    error_suffix: str = " 不是有效 JSON 数据。",
) -> Any:
    """Copy a JSON-compatible value while preserving the caller's error type."""
    try:
        separators = (",", ":") if compact else None
        return json.loads(
            json.dumps(value, ensure_ascii=False, allow_nan=False, separators=separators)
        )
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label}{error_suffix}") from exc


def strict_copy_json(
    value: Any,
    label: str,
    error_type: type[Exception],
    *,
    invalid_number_suffix: str = " 含有无效数值。",
    invalid_type_suffix: str = " 含有不能保存的数据类型。",
    invalid_json_suffix: str = " 不是有效的 JSON 数据。",
) -> Any:
    def validate(item: Any) -> None:
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise error_type(f"{label} 的对象字段名必须是字符串。")
            for child in item.values():
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)
        elif isinstance(item, float) and not math.isfinite(item):
            raise error_type(f"{label}{invalid_number_suffix}")
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise error_type(f"{label}{invalid_type_suffix}")

    validate(value)
    return copy_json(value, label, error_type, error_suffix=invalid_json_suffix)


def strict_json_loads(raw: str, label: str, error_type: type[Exception]) -> Any:
    def reject_constant(constant: str) -> None:
        raise error_type(f"{label} 含有无效数值。")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error_type(f"{label} 含有重复字段。")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_constant)
    except error_type:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise error_type(f"{label} 不是有效 JSON。") from exc
