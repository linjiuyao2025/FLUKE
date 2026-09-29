from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication

from main import (
    DailyBridge,
    IssuePreferencesBridge,
    NewsBridge,
    ReadingBridge,
)
from wanxiang.news_import import parse_issue_json


def _issue() -> dict[str, object]:
    article = {
        "id": "bridge-story",
        "label": "合成栏目",
        "title": "合成报道标题",
        "summary": "只供桌面桥接测试。",
        "body": ["这是合成正文。"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-27",
        "sourceTitle": "原始来源标题",
        "sourceUrl": "https://example.org/synthetic",
    }
    return {
        "version": 1,
        "date": "2026-09-27",
        "topic": "合成主题",
        "editorNote": "",
        "focus": [{**article, "id": "bridge-focus"}],
        "highlights": [{**article, "id": "bridge-highlight"}],
        "articles": [{**article, "id": "bridge-story"}],
    }


class DesktopBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.database_path = Path(self._temp_dir.name) / "synthetic.sqlite3"

    @staticmethod
    def _legacy() -> dict[str, object]:
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        return {
            "raw_values": {"wanxiang-saved-knowledge": "1"},
            "documents": {
                "wanxiang-issue-topics-v1": ["ai", "technology"],
                "wanxiang-issue-preferences-v1": {
                    "subtopics": "开源模型",
                    "sources": "研究机构、技术媒体",
                    "presetSources": ["Reuters"],
                },
                "wanxiang-saved-knowledge": True,
                "wanxiang-issue-clippings-v1": [],
                "richangji-state-v1": {
                    "settings": {
                        "dailyFlowNotes": {yesterday: "合成跟进"},
                        "dailyFlowFocusTask": "合成专注任务",
                        "dailyFlowAudioUrl": "https://open.spotify.com/track/abc123",
                    },
                    "records": [
                        {
                            "id": "record-yesterday",
                            "type": "money",
                            "date": yesterday,
                            "data": {"note": "昨日合成记录", "category": "测试", "amount": 1},
                            "createdAt": 10,
                        },
                        {
                            "id": "task-today",
                            "type": "planner",
                            "date": today,
                            "data": {"title": "今日合成待办"},
                            "createdAt": 11,
                        },
                    ],
                    "habits": [],
                    "mediaItems": [],
                },
                "wanxiang-issue-questions-v1": [{
                    "text": "合成问题", "createdDate": today, "createdAt": 12
                }],
}
        }

    def test_preferences_bridge_and_prompt_copy_use_nested_saved_preferences(self) -> None:
        preferences = IssuePreferencesBridge(self.database_path, self._legacy())
        saved = preferences.save(
            ["ai", "technology"],
            {"subtopics": "开源模型", "sources": "研究机构", "presetSources": ["Reuters"]},
        )
        self.assertTrue(saved["ok"])
        news = NewsBridge(self.database_path)
        copied = news.copyIssuePrompt(
            preferences.state,
            [{"item": {"category": "科技", "label": "科技观察"}}],
        )
        self.assertTrue(copied["ok"])
        prompt = QGuiApplication.clipboard().text()
        self.assertIn("人工智能", prompt)
        self.assertIn("Reuters", prompt)
        self.assertIn("开源模型", prompt)
        self.assertIn("研究机构", prompt)
        self.assertIn("近期个人兴趣信号", prompt)
        self.assertIn("剪报关注：科技", prompt)

    def test_reading_bridge_persists_global_flag_and_clipping(self) -> None:
        reading = ReadingBridge(self.database_path, self._legacy())
        self.assertTrue(reading.state["savedKnowledge"])
        toggled = reading.toggleSavedKnowledge()
        self.assertTrue(toggled["ok"])
        self.assertFalse(toggled["state"]["savedKnowledge"])
        story = _issue()["articles"][0]
        result = reading.toggleClipping(story, "2026-09-27", "合成主题")
        self.assertTrue(result["ok"])
        self.assertTrue(result["saved"])
        self.assertTrue(reading.isClipped("bridge-story", "2026-09-27"))
        restarted = ReadingBridge(self.database_path)
        self.assertFalse(restarted.state["savedKnowledge"])
        self.assertEqual(restarted.state["clippings"][0]["item"]["id"], "bridge-story")

    def test_daily_bridge_writes_notes_questions_and_focus_task(self) -> None:
        daily = DailyBridge(self.database_path, self._legacy())
        self.assertEqual(daily.review["items"][0]["title"], "昨日合成记录")
        self.assertEqual(daily.review["followUp"], "合成跟进")
        self.assertEqual(daily.todayWork["tasks"][0]["title"], "今日合成待办")
        self.assertEqual(daily.state["focusTask"], "合成专注任务")
        self.assertTrue(daily.saveFollowUp("2026-09-27", "今天的合成跟进")["ok"])
        self.assertTrue(daily.saveFocusTask("完成合成任务")["ok"])
        self.assertTrue(daily.addQuestion("需要确认的合成问题")["ok"])
        daily.toggleFocus()
        self.assertTrue(daily.focusRunning)
        daily.tickFocus()
        daily.resetFocus()
        self.assertEqual(daily.focusDisplay, "25:00")
        restarted = DailyBridge(self.database_path)
        self.assertEqual(restarted.state["focusTask"], "完成合成任务")
        self.assertEqual(restarted.state["questions"][0]["text"], "需要确认的合成问题")

    def test_focus_timer_checkpoint_restarts_and_late_import_respects_local_runtime(self) -> None:
        now = [datetime(2026, 9, 27, 23, 59, 50).astimezone()]
        legacy = self._legacy()
        main_state = legacy["documents"]["richangji-state-v1"]
        main_state["settings"]["flowTimer"] = {
            "mode": "countdown",
            "durationSeconds": 300,
            "remainingSeconds": 300,
            "elapsedSeconds": 0,
            "running": True,
            "checkpointAt": (now[0] - timedelta(seconds=2)).isoformat(),
            "sessionId": "restart-session",
            "taskId": "",
            "taskTitle": "重启前的独立任务",
        }
        main_state["settings"]["focusSessions"] = [
            {"id": "imported-session", "date": "2026-09-26", "seconds": 90,
             "mode": "pomodoro", "taskTitle": "旧版独立专注"},
        ]
        daily = DailyBridge(self.database_path, legacy, clock=lambda: now[0])
        self.assertEqual(daily.focusDisplay, "04:58")
        self.assertTrue(daily.focusRunning)
        self.assertEqual(daily.state["focusTimer"]["elapsedSeconds"], 2)
        self.assertEqual(daily.state["focusSessions"][0]["id"], "imported-session")

        later = self._legacy()
        changed_main = later["documents"]["richangji-state-v1"]
        changed_main["settings"]["flowTimer"] = {
            "mode": "flowtime", "durationSeconds": 0, "remainingSeconds": 0,
            "elapsedSeconds": 7, "running": False,
        }
        changed_main["settings"]["focusSessions"] = [
            {"id": "new-import", "date": "2026-09-26", "seconds": 999},
        ]
        daily.adoptImportedData(later)
        self.assertEqual(daily.state["focusTimer"]["mode"], "countdown")
        self.assertEqual(daily.state["focusSessions"][0]["id"], "imported-session")
        daily.close()

        restarted = DailyBridge(self.database_path, later, clock=lambda: now[0])
        self.assertFalse(restarted.focusRunning)
        self.assertEqual(restarted.focusDisplay, "04:58")
        self.assertEqual(restarted.state["focusTimer"]["elapsedSeconds"], 2)
        self.assertEqual(restarted.state["focusTimer"]["taskTitle"], "重启前的独立任务")
        self.assertEqual(restarted.state["focusSessions"][0]["id"], "imported-session")

    def test_news_bridge_copies_validated_prompt_and_exports_active_issue(self) -> None:
        news = NewsBridge(self.database_path)
        previewed = news.previewJson(json.dumps(_issue(), ensure_ascii=False))
        self.assertTrue(previewed["ok"])
        self.assertTrue(news.publishDraft()["ok"])
        destination = Path(self._temp_dir.name) / "exported.json"
        exported = news.exportActiveIssue(QUrl.fromLocalFile(str(destination)))
        self.assertTrue(exported["ok"])
        parsed = parse_issue_json(destination.read_bytes())
        self.assertEqual(parsed["topic"], "合成主题")
        self.assertEqual(parsed["articles"][0]["title"], "合成报道标题")


if __name__ == "__main__":
    unittest.main()
