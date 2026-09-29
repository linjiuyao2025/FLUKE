"""Projection of the legacy home layout and native home preferences.

The legacy ``wanxiang-paper-layout-v2`` document describes cards rendered by
the v1.0.3 home page. The native news editor uses its independent
``newsIssueLayout`` setting; this module stores home choices under
``dailyOverviewLayout`` and never writes to the imported legacy snapshot.

All seven cards rendered by v1.0.3 have a native overview target. The native
settings keep the old card IDs and slot values, while the original localStorage
document remains immutable in the migration snapshot. Five stale IDs in the
legacy default list have no v1.0.3 DOM node and are not fabricated here.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
from typing import Any

from .database import get_app_setting, load_imported_data, set_app_setting
from .migration import SOURCE_IDENTITY


LEGACY_HOME_LAYOUT_KEY = "wanxiang-paper-layout-v2"
HOME_LAYOUT_SETTING = "dailyOverviewLayout"

# This order is copied from v1.0.3's PAPER_CARD_DEFAULTS. Several entries are
# stale defaults rather than cards present in that release's initial DOM.
LEGACY_DEFAULT_ORDER = (
    "lead",
    "briefs",
    "local",
    "knowledge",
    "weekly",
    "stats",
    "habits",
    "recent",
    "quick",
    "next",
    "question-desk",
    "interest-trail",
)

# The seven cards actually carrying data-paper-card in v1.0.3's initial DOM.
LEGACY_RENDERED_CARD_IDS = (
    "lead",
    "briefs",
    "weekly",
    "recent",
    "question-desk",
    "habits",
    "quick",
)

# The original page used three named slots; retain those stable IDs in SQLite.
LEGACY_SLOT_IDS = (
    "flow-briefing-slot",
    "flow-review-slot",
    "flow-work-slot",
)
RETAINED_UNMAPPED_CARD_IDS: tuple[str, ...] = ()
LEGACY_DEFAULT_IDS_WITHOUT_V103_DOM = tuple(
    card_id for card_id in LEGACY_DEFAULT_ORDER if card_id not in LEGACY_RENDERED_CARD_IDS
)

# Keys are stable legacy card IDs; values are objectName identifiers in the
# native QML tree. Keep the question desk separate from yesterday's review.
CARD_TARGET_IDS = {
    "lead": "newsScopeCard",
    "briefs": "newsCard",
    "weekly": "dailyWeeklyCard",
    "recent": "dailyRecentCard",
    "habits": "dailyHabitQuickChecks",
    "question-desk": "dailyQuestionDesk",
    "quick": "dailyQuickAddCard",
}
PENDING_CARD_TARGET_OBJECT_NAMES: dict[str, str] = {}
PENDING_CARD_TARGET_NOTE = ""
NATIVE_CARD_IDS = tuple((*CARD_TARGET_IDS, *PENDING_CARD_TARGET_OBJECT_NAMES))
DEFAULT_NATIVE_ORDER = LEGACY_RENDERED_CARD_IDS
DEFAULT_NATIVE_SLOTS = {
    "lead": "flow-briefing-slot",
    "briefs": "flow-briefing-slot",
    "weekly": "flow-review-slot",
    "recent": "flow-review-slot",
    "question-desk": "flow-review-slot",
    "habits": "flow-work-slot",
    "quick": "flow-work-slot",
}

# Legacy hidden entries are module/group names; ``news`` includes two cards.
LEGACY_HIDDEN_GROUP_TO_CARD = {
    "news": ("lead", "briefs"),
    "weekly": ("weekly",),
    "recent": ("recent",),
    "reader": ("question-desk",),
    "habits": ("habits",),
    "quick": ("quick",),
}


class HomeLayoutError(ValueError):
    """Raised when a native home layout cannot be normalized."""


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _parse_legacy_document(raw_value: str | None) -> tuple[str, Any, str | None]:
    if raw_value is None:
        return "missing", None, None
    try:
        document = json.loads(raw_value, object_pairs_hook=_reject_duplicate_object_keys)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return "malformed", None, str(exc)
    if not isinstance(document, dict):
        return "malformed", None, "legacy layout must be a JSON object"
    order = document.get("order")
    slots = document.get("slots")
    hidden = document.get("hidden")
    if "order" in document and (
        not isinstance(order, list) or any(not isinstance(item, str) for item in order)
    ):
        return "malformed", None, "legacy layout order must be an array of strings"
    if "slots" in document and not isinstance(slots, dict):
        return "malformed", None, "legacy layout slots must be an object"
    if "hidden" in document and (
        not isinstance(hidden, list) or any(not isinstance(item, str) for item in hidden)
    ):
        return "malformed", None, "legacy layout hidden must be an array of strings"
    return "valid", document, None


def _read_legacy_layout_raw(database_path: str | Path) -> str | None:
    """Read the active legacy raw value without creating or changing the DB."""
    path = Path(database_path).expanduser()
    if not path.is_file():
        return None

    connection: sqlite3.Connection | None = None
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
        connection.execute("PRAGMA query_only = ON")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {"legacy_storage", "migration_batches"}.issubset(tables):
            return None

        if "migration_sources" in tables:
            row = connection.execute(
                """
                SELECT legacy_storage.raw_value
                FROM migration_sources
                JOIN legacy_storage
                  ON legacy_storage.batch_id = migration_sources.active_batch_id
                WHERE migration_sources.source_identity = ?
                  AND legacy_storage.storage_key = ?
                """,
                (SOURCE_IDENTITY, LEGACY_HOME_LAYOUT_KEY),
            ).fetchone()
        else:
            # Read the v1 migration schema without attempting an upgrade.
            row = connection.execute(
                """
                SELECT legacy_storage.raw_value
                FROM migration_batches
                JOIN legacy_storage ON legacy_storage.batch_id = migration_batches.batch_id
                WHERE migration_batches.source_identity = ?
                  AND legacy_storage.storage_key = ?
                ORDER BY migration_batches.imported_at DESC, migration_batches.batch_id DESC
                LIMIT 1
                """,
                (SOURCE_IDENTITY, LEGACY_HOME_LAYOUT_KEY),
            ).fetchone()
        return row[0] if row is not None else None
    except (OSError, sqlite3.Error, ValueError):
        return None
    finally:
        if connection is not None:
            connection.close()


def _normalize_native_layout(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HomeLayoutError("dailyOverviewLayout must be an object")
    result = deepcopy(value)
    order = value.get("order", list(DEFAULT_NATIVE_ORDER))
    slots = value.get("slots", dict(DEFAULT_NATIVE_SLOTS))
    hidden = value.get("hidden", [])
    if not isinstance(order, list) or any(not isinstance(item, str) for item in order):
        raise HomeLayoutError("dailyOverviewLayout order must be an array of strings")
    if not isinstance(slots, dict) or any(
        not isinstance(key, str) or not isinstance(slot, str)
        for key, slot in slots.items()
    ):
        raise HomeLayoutError("dailyOverviewLayout slots must map strings to strings")
    if not isinstance(hidden, list) or any(not isinstance(item, str) for item in hidden):
        raise HomeLayoutError("dailyOverviewLayout hidden must be an array of strings")

    supported_order = [item for item in order if item in NATIVE_CARD_IDS]
    supported_order = list(dict.fromkeys(supported_order))
    supported_order.extend(item for item in DEFAULT_NATIVE_ORDER if item not in supported_order)
    supported_slots = {
        item: slots.get(item, DEFAULT_NATIVE_SLOTS[item]) for item in NATIVE_CARD_IDS
    }
    supported_slots.update(
        (key, value) for key, value in slots.items() if key not in NATIVE_CARD_IDS
    )
    supported_hidden = list(
        dict.fromkeys(item for item in hidden if item in NATIVE_CARD_IDS)
    )
    result.update(
        {
            "order": supported_order,
            "slots": supported_slots,
            "hidden": supported_hidden,
        }
    )
    return result


@dataclass(frozen=True, slots=True)
class LegacyHomeLayoutProjection:
    """Detached, immutable-by-contract view of the old layout source."""

    raw_value: str | None
    status: str
    validated_snapshot: bool
    error: str | None = None
    _document: Any = field(default=None, repr=False, compare=False)

    def snapshot(self) -> dict[str, Any]:
        document = deepcopy(self._document)
        order = document.get("order", []) if isinstance(document, dict) else []
        slots = document.get("slots", {}) if isinstance(document, dict) else {}
        hidden = document.get("hidden", []) if isinstance(document, dict) else []
        return {
            "key": LEGACY_HOME_LAYOUT_KEY,
            "rawValue": self.raw_value,
            "status": self.status,
            "validatedSnapshot": self.validated_snapshot,
            "error": self.error,
            "document": document,
            "order": deepcopy(order),
            "slots": deepcopy(slots),
            "hidden": deepcopy(hidden),
            "pendingOrder": [
                item for item in order if item in PENDING_CARD_TARGET_OBJECT_NAMES
            ],
            "unmappedOrder": [
                item
                for item in order
                if item not in CARD_TARGET_IDS and item not in PENDING_CARD_TARGET_OBJECT_NAMES
            ],
            "pendingSlots": {
                key: deepcopy(value)
                for key, value in slots.items()
                if key in PENDING_CARD_TARGET_OBJECT_NAMES
            },
            "unmappedSlots": {
                key: deepcopy(value)
                for key, value in slots.items()
                if key not in CARD_TARGET_IDS and key not in PENDING_CARD_TARGET_OBJECT_NAMES
            },
            "pendingHidden": [],
            "unmappedHidden": [
                item
                for item in hidden
                if item not in LEGACY_HIDDEN_GROUP_TO_CARD and item not in NATIVE_CARD_IDS
            ],
            "renderedCardIds": list(LEGACY_RENDERED_CARD_IDS),
            "defaultIdsWithoutV103Dom": list(LEGACY_DEFAULT_IDS_WITHOUT_V103_DOM),
            "retainedUnmappedCardIds": list(RETAINED_UNMAPPED_CARD_IDS),
        }


def _project_native_default(
    projection: LegacyHomeLayoutProjection,
) -> dict[str, Any]:
    document = projection._document if isinstance(projection._document, dict) else {}
    legacy_order = document.get("order", [])
    mapped_order = [item for item in legacy_order if item in NATIVE_CARD_IDS]
    mapped_order = list(dict.fromkeys(mapped_order))
    mapped_order.extend(item for item in DEFAULT_NATIVE_ORDER if item not in mapped_order)

    legacy_hidden = document.get("hidden", [])
    mapped_hidden: list[str] = []
    for item in legacy_hidden:
        if item in LEGACY_HIDDEN_GROUP_TO_CARD:
            mapped_hidden.extend(LEGACY_HIDDEN_GROUP_TO_CARD[item])
        elif item in NATIVE_CARD_IDS:
            mapped_hidden.append(item)
    mapped_hidden = list(dict.fromkeys(mapped_hidden))
    legacy_slots = document.get("slots", {})
    mapped_slots = {
        card_id: legacy_slots.get(card_id, DEFAULT_NATIVE_SLOTS[card_id])
        for card_id in NATIVE_CARD_IDS
    }
    return {
        "order": mapped_order,
        "slots": mapped_slots,
        "hidden": mapped_hidden,
    }


class HomeLayoutRepository:
    """Persist native overview choices separately from legacy/news layouts."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser()
        imported = load_imported_data(self.database_path)
        validated_snapshot = imported.get("status") == "loaded"
        if validated_snapshot:
            raw_value = imported.get("raw_values", {}).get(LEGACY_HOME_LAYOUT_KEY)
        else:
            # load_imported_data intentionally rejects malformed snapshots; read
            # this one raw value separately so it remains inspectable and is
            # never silently replaced by a default.
            raw_value = _read_legacy_layout_raw(self.database_path)
        status, document, error = _parse_legacy_document(raw_value)
        self._legacy_projection = LegacyHomeLayoutProjection(
            raw_value=raw_value,
            status=status,
            validated_snapshot=validated_snapshot,
            error=error,
            _document=document,
        )

        saved = get_app_setting(self.database_path, HOME_LAYOUT_SETTING, None)
        try:
            self._layout = (
                _normalize_native_layout(saved)
                if saved is not None
                else _project_native_default(self._legacy_projection)
            )
        except HomeLayoutError:
            # Keep the invalid stored value untouched for diagnosis; expose a
            # safe projection until a valid layout is explicitly saved.
            self._layout = _project_native_default(self._legacy_projection)

    def snapshot(self) -> dict[str, Any]:
        return {
            "layout": deepcopy(self._layout),
            "legacy": self._legacy_projection.snapshot(),
            "targets": dict(CARD_TARGET_IDS),
            "pendingTargets": dict(PENDING_CARD_TARGET_OBJECT_NAMES),
            "pendingTargetNote": PENDING_CARD_TARGET_NOTE,
        }

    def save_layout(self, layout: Any) -> dict[str, Any]:
        normalized = _normalize_native_layout(layout)
        set_app_setting(self.database_path, HOME_LAYOUT_SETTING, normalized)
        self._layout = normalized
        return deepcopy(normalized)


__all__ = [
    "CARD_TARGET_IDS",
    "DEFAULT_NATIVE_ORDER",
    "DEFAULT_NATIVE_SLOTS",
    "HOME_LAYOUT_SETTING",
    "HomeLayoutError",
    "HomeLayoutRepository",
    "LEGACY_SLOT_IDS",
    "LEGACY_DEFAULT_IDS_WITHOUT_V103_DOM",
    "LEGACY_DEFAULT_ORDER",
    "LEGACY_HOME_LAYOUT_KEY",
    "LEGACY_RENDERED_CARD_IDS",
    "NATIVE_CARD_IDS",
    "PENDING_CARD_TARGET_NOTE",
    "PENDING_CARD_TARGET_OBJECT_NAMES",
    "RETAINED_UNMAPPED_CARD_IDS",
]
