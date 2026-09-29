from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QUrl

from main import NewsBridge
from wanxiang.database import get_app_setting, set_app_setting
from wanxiang.issues import DRAFT_SETTING, ISSUE_SETTING, LAYOUT_SETTING
from wanxiang.news_import import MAX_ISSUE_JSON_BYTES


def _article(article_id: str, group: str) -> dict[str, object]:
    return {
        "id": article_id,
        "group": group,
        "label": f"合成栏目 {group}",
        "category": "合成分类",
        "title": f"合成标题 {article_id}",
        "summary": "仅供 NewsBridge 测试使用。",
        "body": [f"合成正文 {article_id}，不包含真实新闻内容。"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-27T08:00:00Z",
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
        "focus": [
            _article(f"{prefix}-focus-{index}", "focus")
            for index in range(focus_count)
        ],
        "highlights": [_article(f"{prefix}-highlight-0", "highlights")],
        "articles": [_article(f"{prefix}-article-0", "articles")],
    }


def _store(active: dict[str, object], archive: list[dict[str, object]] | None = None):
    return {"active": active, "archive": archive or []}


class NewsBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.database_path = Path(self._temp_dir.name) / "news.sqlite3"

    @staticmethod
    def _json(issue: dict[str, object]) -> str:
        return json.dumps(issue, ensure_ascii=False, separators=(",", ":"))

    def test_json_preview_changes_memory_only_until_saved(self) -> None:
        persisted_draft = _issue("persisted")
        set_app_setting(self.database_path, DRAFT_SETTING, persisted_draft)
        bridge = NewsBridge(self.database_path)
        # Bridge startup may create the separate recommendation schema. Hash
        # only the preview operation, which must leave persisted issue state
        # and the database file untouched.
        before_hash = hashlib.sha256(self.database_path.read_bytes()).digest()

        result = bridge.previewJson(self._json(_issue("preview")))

        after_hash = hashlib.sha256(self.database_path.read_bytes()).digest()
        self.assertTrue(result["ok"])
        self.assertTrue(result["state"]["draftUnsaved"])
        self.assertTrue(result["state"]["draft"]["topic"] == "合成主题 preview")
        self.assertTrue(
            get_app_setting(self.database_path, DRAFT_SETTING) == persisted_draft
        )
        self.assertTrue(before_hash == after_hash)

    def test_save_preview_and_reopen_reads_saved_draft(self) -> None:
        bridge = NewsBridge(self.database_path)
        preview = bridge.previewJson(self._json(_issue("saved")))
        self.assertTrue(preview["ok"])

        saved = bridge.saveDraft()
        reopened = NewsBridge(self.database_path)

        self.assertTrue(saved["ok"])
        self.assertFalse(saved["state"]["draftUnsaved"])
        self.assertTrue(reopened.state["draft"] == saved["state"]["draft"])
        self.assertFalse(reopened.state["draftUnsaved"])

    def test_restore_saved_draft_discards_memory_only_preview(self) -> None:
        bridge = NewsBridge(self.database_path)
        saved = _issue("saved-before-preview")
        self.assertTrue(bridge.previewJson(self._json(saved))["ok"])
        self.assertTrue(bridge.saveDraft()["ok"])

        unsaved = _issue("memory-only-preview")
        self.assertTrue(bridge.previewJson(self._json(unsaved))["ok"])
        restored = bridge.restoreSavedDraft()

        self.assertTrue(restored["ok"], restored)
        self.assertEqual(restored["state"]["draft"]["topic"], saved["topic"])
        self.assertFalse(restored["state"]["draftUnsaved"])
        self.assertEqual(get_app_setting(self.database_path, DRAFT_SETTING), saved)

    def test_file_preview_and_over_500_kb_error(self) -> None:
        valid_path = Path(self._temp_dir.name) / "synthetic-issue.json"
        valid_path.write_text(self._json(_issue("file")), encoding="utf-8")
        oversized_path = Path(self._temp_dir.name) / "oversized.json"
        oversized_path.write_bytes(b" " * (MAX_ISSUE_JSON_BYTES + 1))
        bridge = NewsBridge(self.database_path)

        preview = bridge.previewFile(QUrl.fromLocalFile(str(valid_path)))
        state_after_preview = bridge.state
        rejected = bridge.previewFile(QUrl.fromLocalFile(str(oversized_path)))

        self.assertTrue(preview["ok"])
        self.assertTrue(state_after_preview["draft"]["topic"] == "合成主题 file")
        self.assertFalse(rejected["ok"])
        self.assertTrue("500 KB" in rejected.get("error", ""))
        self.assertTrue(bridge.state == state_after_preview)

    def test_link_inbox_add_deduplicate_remove_and_reopen(self) -> None:
        bridge = NewsBridge(self.database_path)

        added = bridge.addLink("https://NEWS.example.org/path here")
        duplicate = bridge.addLink("https://news.example.org/path%20here")
        removed = bridge.removeLink(0)
        reopened = NewsBridge(self.database_path)

        self.assertTrue(added["ok"] and duplicate["ok"] and removed["ok"])
        self.assertEqual(len(added["state"]["linkInbox"]), 1)
        self.assertEqual(len(duplicate["state"]["linkInbox"]), 1)
        self.assertEqual(len(removed["state"]["linkInbox"]), 0)
        self.assertEqual(len(reopened.state["linkInbox"]), 0)

    def test_group_sorting_changes_preview_and_survives_save(self) -> None:
        bridge = NewsBridge(self.database_path)
        preview = bridge.previewJson(self._json(_issue("ordered", focus_count=2)))

        moved = bridge.moveDraftItem("focus", 0, 1)
        saved = bridge.saveDraft()
        reopened = NewsBridge(self.database_path)

        self.assertTrue(preview["ok"] and moved["ok"] and saved["ok"])
        self.assertTrue(
            saved["state"]["draft"]["focus"][0]["id"] == "ordered-focus-1"
        )
        self.assertTrue(reopened.state["draft"] == saved["state"]["draft"])

    def test_layout_is_preserved_and_survives_reopen(self) -> None:
        bridge = NewsBridge(self.database_path)
        layout = {
            "order": ["focus", "articles", "highlights"],
            "slots": {"focus": 2},
            "hidden": ["articles"],
        }

        saved = bridge.saveLayout(layout)
        reopened = NewsBridge(self.database_path)

        self.assertTrue(saved["ok"])
        self.assertTrue(saved["state"]["layout"] == layout)
        self.assertTrue(reopened.state["layout"] == layout)
        self.assertTrue(get_app_setting(self.database_path, LAYOUT_SETTING) == layout)

    def test_migration_snapshot_home_layout_does_not_seed_news_groups(self) -> None:
        home_layout = {
            "order": ["lead", "briefs", "weekly", "recent", "question-desk", "habits", "quick"],
            "slots": {"lead": 2},
            "hidden": ["habits"],
        }
        bridge = NewsBridge(
            self.database_path,
            {
                "documents": {"wanxiang-paper-layout-v2": home_layout},
                "layout": home_layout,
            },
        )

        self.assertEqual(bridge.state["layout"], {})
        saved = bridge.saveLayout(
            {"order": ["focus", "highlights", "articles"], "slots": {}, "hidden": []}
        )
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["state"]["layout"]["order"], ["focus", "highlights", "articles"])
        self.assertNotIn("habits", saved["state"]["layout"]["order"])

    def test_publish_archives_previous_active_and_clears_draft(self) -> None:
        old_active = _issue("old-active")
        old_archive = [
            {
                "issue": _issue("older-archive"),
                "publishedAt": "2026-09-26T12:00:00Z",
            }
        ]
        set_app_setting(self.database_path, ISSUE_SETTING, _store(old_active, old_archive))
        set_app_setting(self.database_path, DRAFT_SETTING, _issue("staged-draft"))
        bridge = NewsBridge(self.database_path)
        persisted_active_before_publish = bridge.state["active"]
        persisted_archive_before_publish = bridge.state["archive"]
        preview = bridge.previewJson(self._json(_issue("new-active")))

        published = bridge.publishDraft()
        reopened = NewsBridge(self.database_path)

        state = published["state"]
        self.assertTrue(preview["ok"] and published["ok"])
        self.assertTrue(state["active"]["topic"] == "合成主题 new-active")
        self.assertTrue(state["archive"][0]["issue"] == persisted_active_before_publish)
        self.assertTrue(state["archive"][1:] == persisted_archive_before_publish)
        self.assertTrue(bool(state["archive"][0]["publishedAt"]))
        self.assertIsNone(state["draft"])
        self.assertFalse(state["draftUnsaved"])
        self.assertIsNone(get_app_setting(self.database_path, DRAFT_SETTING, "missing"))
        self.assertTrue(reopened.state["active"] == state["active"])
        self.assertTrue(reopened.state["archive"] == state["archive"])
        self.assertIsNone(reopened.state["draft"])

    def test_failed_publish_keeps_database_and_bridge_state_atomic(self) -> None:
        old_active = _issue("stable-active")
        old_archive = [
            {
                "issue": _issue("stable-archive"),
                "publishedAt": "2026-09-26T12:00:00Z",
            }
        ]
        persisted_draft = _issue("stable-draft")
        original_store = _store(old_active, old_archive)
        set_app_setting(self.database_path, ISSUE_SETTING, original_store)
        set_app_setting(self.database_path, DRAFT_SETTING, persisted_draft)
        bridge = NewsBridge(self.database_path)
        preview = bridge.previewJson(self._json(_issue("pending-publish")))
        before_publish = bridge.state

        # Fail after the new issue store has been written, so rollback must undo it.
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                f"""
                CREATE TRIGGER reject_draft_clear
                BEFORE INSERT ON app_settings
                WHEN NEW.key = '{DRAFT_SETTING}'
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic publish failure');
                END
                """
            )
            connection.commit()

        failed = bridge.publishDraft()
        reopened = NewsBridge(self.database_path)

        self.assertTrue(preview["ok"])
        self.assertFalse(failed["ok"])
        self.assertTrue(bridge.state == before_publish)
        self.assertTrue(get_app_setting(self.database_path, ISSUE_SETTING) == original_store)
        self.assertTrue(get_app_setting(self.database_path, DRAFT_SETTING) == persisted_draft)
        self.assertTrue(reopened.state["active"] == before_publish["active"])
        self.assertTrue(reopened.state["archive"] == before_publish["archive"])
        self.assertTrue(reopened.state["draft"] == persisted_draft)

    def test_load_history_sets_selected_entry_as_persisted_draft(self) -> None:
        active = _issue("history-active")
        archived = _issue("history-entry")
        archive = [{"issue": archived, "publishedAt": "2026-09-26T12:00:00Z"}]
        set_app_setting(self.database_path, ISSUE_SETTING, _store(active, archive))
        bridge = NewsBridge(self.database_path)

        loaded = bridge.loadHistory(0)
        reopened = NewsBridge(self.database_path)

        self.assertTrue(loaded["ok"])
        self.assertTrue(loaded["state"]["draft"]["topic"] == "合成主题 history-entry")
        self.assertFalse(loaded["state"]["draftUnsaved"])
        self.assertTrue(reopened.state["draft"] == loaded["state"]["draft"])
        self.assertTrue(reopened.state["archive"] == loaded["state"]["archive"])

    def test_feedback_recommendation_manual_order_publish_history_and_clear(self) -> None:
        issue = _issue("personal", focus_count=2)
        issue["focus"][0]["category"] = "健康"
        issue["focus"][0]["label"] = "健康观察"
        issue["focus"][1]["category"] = "科技"
        issue["focus"][1]["label"] = "科技观察"
        bridge = NewsBridge(self.database_path)
        self.assertTrue(bridge.previewJson(self._json(issue))["ok"])
        original_order = [item["id"] for item in bridge.state["draft"]["focus"]]

        preferences = {"topics": ["technology"], "preferences": {"subtopics": "", "presetSources": []}}
        suggested = bridge.recommendDraft(preferences, [])
        self.assertTrue(suggested["ok"])
        self.assertEqual([item["id"] for item in bridge.state["draft"]["focus"]], original_order)
        self.assertEqual(
            [row["id"] for row in bridge.state["recommendationSuggestions"]["groups"]["focus"]],
            [issue["focus"][1]["id"], issue["focus"][0]["id"]],
        )
        self.assertIn("关注主题", bridge.state["recommendationSuggestions"]["groups"]["focus"][0]["reason"])

        self.assertTrue(bridge.applyRecommendation()["ok"])
        self.assertEqual(
            [item["id"] for item in bridge.state["draft"]["focus"]],
            [issue["focus"][1]["id"], issue["focus"][0]["id"]],
        )
        self.assertTrue(bridge.moveDraftItem("focus", 0, 1)["ok"])
        manual_order = [item["id"] for item in bridge.state["draft"]["focus"]]
        self.assertEqual(manual_order, original_order)
        self.assertEqual(bridge.state["recommendationSuggestions"], {})

        feedback = bridge.setArticleFeedback(issue["focus"][0], issue["date"], "not_interested")
        self.assertTrue(feedback["ok"])
        self.assertEqual(
            feedback["state"]["recommendationFeedback"][f"{issue['date']}::{issue['focus'][0]['id']}"],
            "not_interested",
        )
        self.assertEqual(
            NewsBridge(self.database_path).state["recommendationFeedback"][
                f"{issue['date']}::{issue['focus'][0]['id']}"
            ],
            "not_interested",
        )

        set_app_setting(self.database_path, DRAFT_SETTING, issue)
        self.assertTrue(bridge.saveDraft()["ok"])
        self.assertTrue(bridge.publishDraft()["ok"])
        next_issue = _issue("next")
        self.assertTrue(bridge.previewJson(self._json(next_issue))["ok"])
        self.assertTrue(bridge.publishDraft()["ok"])
        self.assertEqual([item["id"] for item in bridge.state["archive"][0]["issue"]["focus"]], manual_order)
        self.assertTrue(bridge.loadHistory(0)["ok"])
        self.assertEqual([item["id"] for item in bridge.state["draft"]["focus"]], manual_order)

        before_store = get_app_setting(self.database_path, ISSUE_SETTING)
        cleared = bridge.clearRecommendationFeedback()
        self.assertTrue(cleared["ok"])
        self.assertEqual(cleared["state"]["recommendationFeedback"], {})
        self.assertEqual(get_app_setting(self.database_path, ISSUE_SETTING), before_store)
        self.assertEqual(bridge.state["draft"]["focus"], NewsBridge(self.database_path).state["draft"]["focus"])


if __name__ == "__main__":
    unittest.main()
