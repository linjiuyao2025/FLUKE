from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.database import (
    get_app_setting,
    import_package,
    load_imported_data,
    set_app_setting,
)
from wanxiang.home_layout import HOME_LAYOUT_SETTING, HomeLayoutRepository
from wanxiang.issues import (
    DRAFT_SETTING,
    INBOX_SETTING,
    ISSUE_SETTING,
    LAYOUT_SETTING,
    IssueRepository,
    IssueRepositoryError,
)
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _legacy_package(home_layout: dict[str, object]):
    raw_values = {key: None for key in STORAGE_KEYS}
    raw_values.update({
        "richangji-state-v1": json.dumps(
            {"version": 2, "records": [], "habits": [], "mediaItems": []},
            separators=(",", ":"),
        ),
        "richangji-samples-cleared": "1",
        "wanxiang-paper-layout-v2": json.dumps(
            home_layout, ensure_ascii=False, separators=(",", ":")
        ),
        "wanxiang-daily-issues-v1": '{"active":null,"archive":[]}',
        "wanxiang-issue-questions-v1": "[]",
        "wanxiang-issue-topics-v1": "[]",
        "wanxiang-issue-preferences-v1": "{}",
        "wanxiang-issue-clippings-v1": "[]",
        "wanxiang-saved-knowledge": "1",
    })
    return validate_package(
        {
            "format": PACKAGE_FORMAT,
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "sourceVersion": "synthetic",
            "exportedAt": "2026-09-29T00:00:00Z",
            "keys": raw_values,
            "checksum": calculate_checksum(raw_values),
        }
    )


def _article(article_id: str, group: str) -> dict[str, object]:
    return {
        "id": article_id,
        "group": group,
        "label": f"合成标签 {article_id}",
        "category": "",
        "title": f"合成标题 {article_id}",
        "summary": "用于仓储测试的合成摘要。",
        "body": ["仅用于测试，不包含个人数据。"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-27",
        "sourceTitle": "",
        "sourceUrl": f"https://news.example.org/{article_id}",
        "relevance": "",
        "action": "",
        "caveats": "",
        "relatedCoverage": [],
        "updates": [],
        "image": None,
    }


def _issue(prefix: str, *, focus_count: int = 1) -> dict[str, object]:
    return {
        "version": 1,
        "date": "2026-09-27",
        "topic": f"合成主题 {prefix}",
        "editorNote": "",
        "focus": [_article(f"{prefix}-f-{index}", "focus") for index in range(focus_count)],
        "highlights": [_article(f"{prefix}-h-1", "highlights")],
        "articles": [_article(f"{prefix}-a-1", "articles")],
    }


def _archive_entry(prefix: str, published_at: str = "2026-09-27T00:00:00Z") -> dict[str, object]:
    return {"issue": _issue(prefix), "publishedAt": published_at}


class IssueRepositoryTests(unittest.TestCase):
    def test_app_settings_take_priority_and_legacy_values_are_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "priority.sqlite3"
            setting_issue = _issue("setting")
            setting_layout = {"order": ["setting-slot"]}
            set_app_setting(database_path, ISSUE_SETTING, {"active": setting_issue, "archive": []})
            set_app_setting(database_path, LAYOUT_SETTING, setting_layout)

            repository = IssueRepository(
                database_path,
                legacy_store={"active": _issue("legacy"), "archive": []},
            )
            self.assertEqual(repository.snapshot()["active"]["topic"], setting_issue["topic"])
            self.assertEqual(repository.snapshot()["layout"], setting_layout)

            fallback_repository = IssueRepository(
                Path(directory) / "legacy.sqlite3",
                legacy_store={
                    "parsed_values": {
                        "wanxiang-daily-issues-v1": {
                            "active": _issue("legacy-fallback"),
                            "archive": [],
                        },
                        # This is the old homepage layout and is deliberately
                        # not a fallback for the news issue-group editor.
                        "wanxiang-paper-layout-v2": {"order": ["habits", "quick"]},
                    }
                },
            )
            self.assertEqual(
                fallback_repository.snapshot()["active"]["topic"],
                "合成主题 legacy-fallback",
            )
            self.assertEqual(
                fallback_repository.snapshot()["layout"],
                {},
            )

    def test_home_layout_import_and_news_layout_save_remain_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "layout-boundary.sqlite3"
            old_home_layout = {
                "order": ["lead", "briefs", "weekly", "recent", "question-desk", "habits", "quick"],
                "slots": {"lead": 2},
                "hidden": ["habits"],
            }
            package = _legacy_package(old_home_layout)
            import_package(package, database_path)
            raw_home_layout = package.raw_values["wanxiang-paper-layout-v2"]

            # A previous native build may have stored the old homepage object
            # under this ambiguous key; the news repository must ignore it.
            set_app_setting(database_path, "paperLayout", old_home_layout)
            news = IssueRepository(database_path)
            self.assertEqual(news.snapshot()["layout"], {})

            news_layout = {
                "order": ["focus", "highlights", "articles"],
                "slots": {},
                "hidden": ["articles"],
            }
            self.assertEqual(news.save_layout(news_layout), news_layout)

            home = HomeLayoutRepository(database_path)
            self.assertEqual(home.snapshot()["legacy"]["rawValue"], raw_home_layout)
            home_layout = {
                "order": ["habits", "question-desk", "quick"],
                "slots": {
                    "habits": "main",
                    "question-desk": "main",
                    "quick": "dailyQuickAddCard",
                },
                "hidden": ["question-desk"],
            }
            saved_home_layout = home.save_layout(home_layout)

            reopened_news = IssueRepository(database_path)
            self.assertEqual(reopened_news.snapshot()["layout"], news_layout)
            self.assertEqual(get_app_setting(database_path, LAYOUT_SETTING), news_layout)
            self.assertEqual(saved_home_layout["order"][:3], home_layout["order"])
            self.assertEqual(saved_home_layout["hidden"], home_layout["hidden"])
            self.assertEqual(
                get_app_setting(database_path, HOME_LAYOUT_SETTING), saved_home_layout
            )
            self.assertEqual(get_app_setting(database_path, "paperLayout"), old_home_layout)
            self.assertEqual(
                load_imported_data(database_path)["raw_values"],
                package.raw_values,
            )
            self.assertNotIn("habits", reopened_news.snapshot()["layout"]["order"])

    def test_saved_draft_survives_repository_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "draft.sqlite3"
            issue = _issue("draft")
            IssueRepository(database_path).save_draft(issue)

            reopened = IssueRepository(database_path)
            self.assertEqual(reopened.snapshot()["draft"], issue)

    def test_publish_archives_previous_active_caps_history_and_loads_history_to_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "history.sqlite3"
            set_app_setting(
                database_path,
                ISSUE_SETTING,
                {
                    "active": _issue("previous-active"),
                    "archive": [_archive_entry(f"old-{index}") for index in range(40)],
                },
            )
            repository = IssueRepository(database_path)
            issue = _issue("to-publish")
            repository.save_draft(issue)

            published = repository.publish_draft("2026-09-27T12:34:56.000Z")
            current = repository.snapshot()
            self.assertEqual(published, issue)
            self.assertEqual(current["active"], issue)
            self.assertIsNone(current["draft"])
            self.assertEqual(len(current["archive"]), 40)
            self.assertEqual(current["archive"][0]["issue"]["topic"], "合成主题 previous-active")
            self.assertEqual(current["archive"][0]["publishedAt"], "2026-09-27T12:34:56.000Z")

            historical = repository.load_history(0)
            self.assertEqual(historical, current["archive"][0]["issue"])
            self.assertEqual(repository.snapshot()["draft"], historical)
            self.assertEqual(IssueRepository(database_path).snapshot()["draft"], historical)

    def test_publish_issue_publishes_an_unsaved_preview_and_clears_saved_draft_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "publish-preview.sqlite3"
            set_app_setting(
                database_path,
                ISSUE_SETTING,
                {"active": _issue("active-before-preview"), "archive": []},
            )
            repository = IssueRepository(database_path)
            repository.save_draft(_issue("older-saved-draft"))

            published = repository.publish_issue(
                _issue("unsaved-preview"), "2026-09-27T12:34:56.000Z"
            )

            state = repository.snapshot()
            self.assertEqual(published["topic"], "合成主题 unsaved-preview")
            self.assertEqual(state["active"]["topic"], "合成主题 unsaved-preview")
            self.assertEqual(
                state["archive"][0]["issue"]["topic"],
                "合成主题 active-before-preview",
            )
            self.assertIsNone(state["draft"])
            self.assertEqual(IssueRepository(database_path).snapshot(), state)

    def test_move_draft_items_only_within_supported_groups_and_respects_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = IssueRepository(Path(directory) / "order.sqlite3")
            repository.save_draft(_issue("ordered", focus_count=2))
            before = repository.snapshot()["draft"]

            self.assertFalse(repository.move_draft_item("focus", 0, -1))
            self.assertEqual(repository.snapshot()["draft"], before)
            self.assertTrue(repository.move_draft_item("focus", 0, 1))
            after = repository.snapshot()["draft"]
            self.assertEqual(after["focus"][0]["id"], "ordered-f-1")
            self.assertEqual(after["focus"][1]["id"], "ordered-f-0")
            with self.assertRaises(IssueRepositoryError):
                repository.move_draft_item("archive", 0, 1)
            self.assertFalse(repository.move_draft_item("articles", 0, 1))
            with self.assertRaises(IssueRepositoryError):
                repository.move_draft_item("articles", 1, -1)
            with self.assertRaises(IssueRepositoryError):
                repository.move_draft_item([], 0, 1)

    def test_link_inbox_normalizes_deduplicates_and_removes_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "links.sqlite3"
            repository = IssueRepository(database_path)
            self.assertTrue(repository.add_link("https://NEWS.example.org/path here", "2026-09-27T10:00:00Z"))
            self.assertFalse(repository.add_link("https://news.example.org/path%20here", "2026-09-27T11:00:00Z"))
            self.assertEqual(
                repository.snapshot()["linkInbox"],
                [{"url": "https://news.example.org/path%20here", "addedAt": "2026-09-27T10:00:00Z"}],
            )
            removed = repository.remove_link(0)
            self.assertEqual(removed["url"], "https://news.example.org/path%20here")
            self.assertEqual(IssueRepository(database_path).snapshot()["linkInbox"], [])

    def test_layout_is_validated_and_persists_across_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "layout.sqlite3"
            layout = {"order": ["lead", "brief"], "slots": {"lead": 2}, "hidden": ["unused"]}
            self.assertEqual(IssueRepository(database_path).save_layout(layout), layout)
            self.assertEqual(IssueRepository(database_path).snapshot()["layout"], layout)
            with self.assertRaises(IssueRepositoryError):
                IssueRepository(database_path).save_layout({"order": ["lead", 2]})

    def test_failed_publish_rolls_back_database_and_in_memory_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "rollback.sqlite3"
            set_app_setting(
                database_path,
                ISSUE_SETTING,
                {"active": _issue("stable-active"), "archive": []},
            )
            repository = IssueRepository(database_path)
            repository.save_draft(_issue("persisted-draft"))
            before = repository.snapshot()
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    f"""
                    CREATE TRIGGER reject_issue_store_write
                    BEFORE INSERT ON app_settings
                    WHEN NEW.key = '{ISSUE_SETTING}'
                    BEGIN
                        SELECT RAISE(ABORT, 'synthetic write failure');
                    END
                    """
                )
                connection.commit()

            with self.assertRaises(IssueRepositoryError):
                repository.publish_issue(
                    _issue("unsaved-preview"), "2026-09-27T12:00:00Z"
                )

            self.assertEqual(repository.snapshot(), before)
            reopened = IssueRepository(database_path)
            self.assertEqual(reopened.snapshot(), before)
            self.assertEqual(
                reopened.snapshot()["draft"]["topic"], "合成主题 persisted-draft"
            )


if __name__ == "__main__":
    unittest.main()
