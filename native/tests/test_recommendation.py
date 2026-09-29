import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
import tempfile
import unittest

from wanxiang.recommendation import (
    RecommendationError,
    RecommendationRepository,
    RecommendationRepositoryError,
    feedback_summary,
    personalized_summary,
    rank_group,
)
from wanxiang.preferences import IssuePreferencesRepository
from wanxiang.reading import ReadingRepository


def _article(article_id: str, category: str, publisher: str = "来源 A") -> dict[str, object]:
    return {
        "id": article_id,
        "label": category + "观察",
        "category": category,
        "title": category + "行业进展",
        "summary": "合成摘要",
        "publisher": publisher,
        "publishedAt": "2026-09-27",
    }


class RecommendationRankingTests(unittest.TestCase):
    def test_empty_profile_preserves_input_order_and_does_not_mutate(self) -> None:
        source = [_article("health", "健康"), _article("tech", "科技")]
        before = [dict(item) for item in source]

        ranked = rank_group(source, today=date(2026, 9, 27))

        self.assertEqual([entry["item"]["id"] for entry in ranked], ["health", "tech"])
        self.assertEqual(source, before)
        self.assertIn("保留原编辑顺序", ranked[0]["reason"])

    def test_manual_topic_feedback_and_clip_signal_change_order_explainably(self) -> None:
        items = [_article("health", "健康"), _article("tech", "科技")]
        preferences = {"topics": ["technology"], "preferences": {"subtopics": "", "presetSources": []}}
        ranked = rank_group(items, preferences=preferences, today=date(2026, 9, 27))
        self.assertEqual(ranked[0]["item"]["id"], "tech")
        self.assertIn("关注主题", ranked[0]["reason"])

        negative = [{
            "date": "2026-09-01",
            "articleId": "old-health",
            "action": "not_interested",
            "article": {"category": "健康", "label": "健康观察", "publisher": "来源 A", "title": ""},
            "createdAt": "2026-09-27T00:00:00+00:00",
        }]
        ranked = rank_group(items, feedback=negative, today=date(2026, 9, 27))
        self.assertEqual(ranked[0]["item"]["id"], "tech")
        self.assertIn("不感兴趣", ranked[1]["reason"])

        ranked = rank_group(
            items,
            clippings=[{"item": _article("saved", "科技")}],
            today=date(2026, 9, 27),
        )
        self.assertEqual(ranked[0]["item"]["id"], "tech")
        self.assertIn("剪报", ranked[0]["reason"])

    def test_feedback_decay_stable_ties_and_summary(self) -> None:
        candidates = [_article("tech-a", "科技"), _article("tech-b", "科技")]
        old_signal = [{
            "action": "not_interested",
            "article": {"category": "科技", "label": "科技观察", "publisher": "来源 A", "title": ""},
            "createdAt": "2026-01-01T00:00:00+00:00",
        }]
        first = rank_group(candidates, feedback=old_signal, today=date(2026, 9, 27))
        second = rank_group(candidates, feedback=old_signal, today=date(2026, 9, 27))
        self.assertEqual(first, second)
        self.assertEqual([entry["item"]["id"] for entry in first], ["tech-a", "tech-b"])
        recent_feedback = [{
            "action": "more_topic",
            "article": {"category": "科技", "label": "科技观察"},
            "createdAt": "2026-09-20T00:00:00+00:00",
        }]
        self.assertIn("科技", feedback_summary(recent_feedback, today=date(2026, 9, 27)))
        stale_feedback = [{
            "action": "more_topic",
            "article": {"category": "游戏", "label": "游戏"},
            "createdAt": "2026-01-01T00:00:00+00:00",
        }]
        self.assertNotIn("游戏", feedback_summary(stale_feedback, today=date(2026, 9, 27)))
        self.assertNotIn(
            "游戏",
            personalized_summary(stale_feedback, [], today=date(2026, 9, 27)),
        )
        self.assertIn("剪报关注：科技", personalized_summary([], [{"item": _article("saved", "科技")}]))


class RecommendationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.database_path = Path(self._temp_dir.name) / "isolated.sqlite3"

    def test_feedback_upsert_reopen_undo_and_reset_preserves_other_tables(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("CREATE TABLE legacy_storage (storage_key TEXT PRIMARY KEY, raw_value TEXT)")
            connection.execute("INSERT INTO legacy_storage VALUES ('source-row', 'unchanged')")
            connection.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
            connection.execute("INSERT INTO app_settings VALUES ('dailyIssueDraft', '{\"safe\":true}')")
            connection.commit()

        # This test deliberately starts with a partial database containing
        # unrelated tables. Seed preferences directly so it tests table
        # coexistence without pretending those tables are a valid migration DB.
        preferences = IssuePreferencesRepository(self.database_path, legacy_store={})
        preferences.save(
            ["technology"],
            {"subtopics": "AI", "sources": "", "presetSources": ["Reuters"]},
        )
        reading = ReadingRepository(self.database_path, legacy_snapshot={})
        reading.toggle_clipping(_article("saved", "科技"), "2026-09-26", "科技")
        repo = RecommendationRepository(self.database_path)
        item = _article("stable-1", "科技")
        self.assertEqual(repo.set_feedback("2026-09-27", item, "more_topic"), "more_topic")
        self.assertEqual(repo.feedback_for("2026-09-27", "stable-1"), "more_topic")
        repo.set_feedback("2026-09-27", item, "useful")

        reopened = RecommendationRepository(self.database_path)
        self.assertEqual(reopened.feedback_for("2026-09-27", "stable-1"), "useful")
        reopened.clear()
        self.assertEqual(reopened.all_feedback(), [])
        self.assertEqual(preferences.get()["topics"], ["technology"])
        self.assertEqual(len(ReadingRepository(self.database_path, legacy_snapshot={}).clippings()), 1)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT raw_value FROM legacy_storage WHERE storage_key='source-row'").fetchone()[0], "unchanged")
            self.assertEqual(connection.execute("SELECT value_json FROM app_settings WHERE key='dailyIssueDraft'").fetchone()[0], '{"safe":true}')

    def test_invalid_feedback_and_failed_write_are_atomic(self) -> None:
        repo = RecommendationRepository(self.database_path)
        item = _article("stable-2", "科技")
        with self.assertRaises(RecommendationError):
            repo.set_feedback("2026-02-30", item, "useful")
        with self.assertRaises(RecommendationError):
            repo.set_feedback("2026-09-27", item, "bad-action")
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "CREATE TRIGGER fail_feedback BEFORE INSERT ON article_feedback "
                "BEGIN SELECT RAISE(ABORT, 'blocked synthetic write'); END"
            )
            connection.commit()
        with self.assertRaises(RecommendationRepositoryError):
            repo.set_feedback("2026-09-27", item, "useful")
        self.assertEqual(repo.all_feedback(), [])


if __name__ == "__main__":
    unittest.main()
