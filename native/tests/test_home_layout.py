from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from main import HomeLayoutBridge
from wanxiang.database import get_app_setting, import_package, set_app_setting
from wanxiang.home_layout import (
    CARD_TARGET_IDS,
    DEFAULT_NATIVE_ORDER,
    HOME_LAYOUT_SETTING,
    HomeLayoutRepository,
    LEGACY_DEFAULT_IDS_WITHOUT_V103_DOM,
    LEGACY_DEFAULT_ORDER,
    LEGACY_HOME_LAYOUT_KEY,
    LEGACY_RENDERED_CARD_IDS,
    LEGACY_SLOT_IDS,
    PENDING_CARD_TARGET_OBJECT_NAMES,
    RETAINED_UNMAPPED_CARD_IDS,
)
from wanxiang.issues import LAYOUT_SETTING
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _package(layout_raw: str) -> object:
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = _json(
        {"records": [], "habits": [], "mediaItems": [], "settings": {}}
    )
    raw_values[LEGACY_HOME_LAYOUT_KEY] = layout_raw
    payload = {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-home-layout-test",
        "exportedAt": "2026-09-29T00:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    }
    return validate_package(payload)


class HomeLayoutRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.database_path = Path(self._temp_dir.name) / "home-layout.sqlite3"

    def _import_layout(self, layout_raw: str) -> None:
        import_package(_package(layout_raw), self.database_path)

    def test_legacy_projection_preserves_malformed_raw_payload_without_rewriting_it(self) -> None:
        self._import_layout('{"order":["habits"],"slots":{},"hidden":[]}')
        malformed = '{ "order": ["habits", 7], "unknown": "preserve exactly" '
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("BEGIN")
            batch_id = connection.execute(
                "SELECT active_batch_id FROM migration_sources LIMIT 1"
            ).fetchone()[0]
            connection.execute(
                "UPDATE legacy_storage SET raw_value = ? "
                "WHERE batch_id = ? AND storage_key = ?",
                (malformed, batch_id, LEGACY_HOME_LAYOUT_KEY),
            )
            connection.commit()

        repository = HomeLayoutRepository(self.database_path)
        before_save = repository.snapshot()
        self.assertEqual(before_save["legacy"]["rawValue"], malformed)
        self.assertEqual(before_save["legacy"]["status"], "malformed")
        self.assertFalse(before_save["legacy"]["validatedSnapshot"])
        self.assertEqual(before_save["layout"]["order"], list(DEFAULT_NATIVE_ORDER))

        saved = repository.save_layout(
            {"order": ["question-desk"], "hidden": ["question-desk"]}
        )
        self.assertEqual(
            saved["order"],
            ["question-desk", "lead", "briefs", "weekly", "recent", "habits", "quick"],
        )
        self.assertEqual(saved["hidden"], ["question-desk"])
        self.assertEqual(repository.snapshot()["legacy"]["rawValue"], malformed)
        with closing(sqlite3.connect(self.database_path)) as connection:
            stored_raw = connection.execute(
                "SELECT raw_value FROM legacy_storage "
                "WHERE storage_key = ?",
                (LEGACY_HOME_LAYOUT_KEY,),
            ).fetchone()[0]
        self.assertEqual(stored_raw, malformed)

    def test_default_projection_maps_all_rendered_cards_and_retains_source_fields(self) -> None:
        legacy_document = {
            "order": [
                "lead", "briefs", "weekly", "recent", "question-desk",
                "habits", "quick", "future-card",
            ],
            "slots": {
                "lead": "flow-briefing-slot",
                "briefs": "flow-briefing-slot",
                "weekly": "flow-review-slot",
                "recent": "flow-review-slot",
                "question-desk": "flow-review-slot",
                "habits": "flow-work-slot",
                "quick": "flow-work-slot",
                "future-card": "future-slot",
            },
            "hidden": ["news", "weekly", "recent", "reader", "habits", "quick", "future-group"],
            "futureField": {"keep": True},
        }
        raw = _json(legacy_document)
        self._import_layout(raw)

        snapshot = HomeLayoutRepository(self.database_path).snapshot()
        self.assertEqual(snapshot["legacy"]["status"], "valid")
        self.assertTrue(snapshot["legacy"]["validatedSnapshot"])
        self.assertEqual(snapshot["legacy"]["rawValue"], raw)
        self.assertEqual(snapshot["legacy"]["document"], legacy_document)
        self.assertEqual(
            snapshot["layout"]["order"],
            ["lead", "briefs", "weekly", "recent", "question-desk", "habits", "quick"],
        )
        self.assertEqual(
            snapshot["layout"]["slots"],
            {
                "lead": "flow-briefing-slot",
                "briefs": "flow-briefing-slot",
                "weekly": "flow-review-slot",
                "recent": "flow-review-slot",
                "question-desk": "flow-review-slot",
                "habits": "flow-work-slot",
                "quick": "flow-work-slot",
            },
        )
        self.assertEqual(
            snapshot["layout"]["hidden"],
            ["lead", "briefs", "weekly", "recent", "question-desk", "habits", "quick"],
        )
        self.assertEqual(snapshot["legacy"]["pendingOrder"], [])
        self.assertEqual(
            snapshot["legacy"]["unmappedOrder"], ["future-card"]
        )
        self.assertEqual(
            snapshot["legacy"]["unmappedSlots"], {"future-card": "future-slot"}
        )
        self.assertEqual(snapshot["legacy"]["pendingSlots"], {})
        self.assertEqual(snapshot["legacy"]["pendingHidden"], [])
        self.assertEqual(snapshot["legacy"]["unmappedHidden"], ["future-group"])
        self.assertEqual(snapshot["legacy"]["document"]["futureField"], {"keep": True})

    def test_native_layout_setting_is_independent_of_news_issue_layout(self) -> None:
        legacy_raw = '{"order":["habits","question-desk"],"slots":{},"hidden":[]}'
        self._import_layout(legacy_raw)
        news_layout = {
            "order": ["articles", "focus", "highlights"],
            "slots": {"focus": "news-column"},
            "hidden": ["articles"],
        }
        set_app_setting(self.database_path, LAYOUT_SETTING, news_layout)

        repository = HomeLayoutRepository(self.database_path)
        native_layout = repository.save_layout(
            {
                "order": ["question-desk", "habits"],
                "slots": {"recent": "flow-work-slot"},
                "hidden": ["habits"],
            }
        )
        reopened = HomeLayoutRepository(self.database_path)

        self.assertEqual(
            native_layout["order"],
            ["question-desk", "habits", "lead", "briefs", "weekly", "recent", "quick"],
        )
        self.assertEqual(native_layout["slots"]["recent"], "flow-work-slot")
        self.assertEqual(native_layout["hidden"], ["habits"])
        self.assertEqual(reopened.snapshot()["layout"], native_layout)
        self.assertEqual(get_app_setting(self.database_path, HOME_LAYOUT_SETTING), native_layout)
        self.assertEqual(get_app_setting(self.database_path, LAYOUT_SETTING), news_layout)
        self.assertEqual(reopened.snapshot()["legacy"]["rawValue"], legacy_raw)

    def test_all_rendered_cards_have_unique_native_targets(self) -> None:
        self.assertEqual(set(CARD_TARGET_IDS), set(LEGACY_RENDERED_CARD_IDS))
        self.assertEqual(CARD_TARGET_IDS["lead"], "newsScopeCard")
        self.assertEqual(CARD_TARGET_IDS["briefs"], "newsCard")
        self.assertEqual(CARD_TARGET_IDS["weekly"], "dailyWeeklyCard")
        self.assertEqual(CARD_TARGET_IDS["recent"], "dailyRecentCard")
        self.assertEqual(CARD_TARGET_IDS["habits"], "dailyHabitQuickChecks")
        self.assertEqual(CARD_TARGET_IDS["question-desk"], "dailyQuestionDesk")
        self.assertEqual(CARD_TARGET_IDS["quick"], "dailyQuickAddCard")
        self.assertEqual(PENDING_CARD_TARGET_OBJECT_NAMES, {})
        all_targets = [*CARD_TARGET_IDS.values(), *PENDING_CARD_TARGET_OBJECT_NAMES.values()]
        self.assertEqual(len(all_targets), len(set(all_targets)))

        self._import_layout('{"order":["habits","question-desk","habits"]}')
        repository = HomeLayoutRepository(self.database_path)
        saved = repository.save_layout(
            {"order": ["habits", "question-desk", "habits"]}
        )
        self.assertEqual(
            saved["order"],
            ["habits", "question-desk", "lead", "briefs", "weekly", "recent", "quick"],
        )
        self.assertEqual(len(saved["order"]), len(set(saved["order"])))
        self.assertEqual(repository.snapshot()["targets"], CARD_TARGET_IDS)
        self.assertEqual(repository.snapshot()["pendingTargets"], {})

    def test_production_bridge_saves_reopens_and_refreshes_after_import(self) -> None:
        legacy_raw = '{"order":["question-desk","habits"],"hidden":["reader"]}'
        self._import_layout(legacy_raw)
        bridge = HomeLayoutBridge(self.database_path)
        self.assertEqual(bridge.state["legacy"]["rawValue"], legacy_raw)
        self.assertEqual(bridge.state["layout"]["hidden"], ["question-desk"])

        saved = {
            **bridge.state["layout"],
            "hidden": ["habits"],
            "unknownMetadata": {"retain": True},
        }
        result = bridge.saveLayout(saved)
        self.assertTrue(result["ok"], result)
        self.assertEqual(bridge.state["layout"]["hidden"], ["habits"])
        self.assertEqual(
            bridge.state["layout"]["unknownMetadata"], {"retain": True}
        )
        reopened = HomeLayoutBridge(self.database_path)
        self.assertEqual(reopened.state["layout"], result["layout"])
        self.assertEqual(reopened.state["legacy"]["rawValue"], legacy_raw)

        next_raw = '{"order":["habits"],"hidden":[]}'
        import_package(_package(next_raw), self.database_path)
        reopened.refreshFromDatabase()
        self.assertEqual(reopened.state["legacy"]["rawValue"], next_raw)
        self.assertEqual(reopened.state["layout"]["hidden"], ["habits"])

    def test_legacy_card_inventory_matches_release_and_does_not_fabricate_defaults(self) -> None:
        self.assertEqual(
            LEGACY_DEFAULT_ORDER,
            (
                "lead", "briefs", "local", "knowledge", "weekly", "stats",
                "habits", "recent", "quick", "next", "question-desk", "interest-trail",
            ),
        )
        self.assertEqual(
            LEGACY_RENDERED_CARD_IDS,
            ("lead", "briefs", "weekly", "recent", "question-desk", "habits", "quick"),
        )
        self.assertEqual(
            LEGACY_DEFAULT_IDS_WITHOUT_V103_DOM,
            ("local", "knowledge", "stats", "next", "interest-trail"),
        )
        self.assertEqual(
            RETAINED_UNMAPPED_CARD_IDS,
            (),
        )
        self.assertEqual(
            LEGACY_SLOT_IDS,
            ("flow-briefing-slot", "flow-review-slot", "flow-work-slot"),
        )


if __name__ == "__main__":
    unittest.main()
