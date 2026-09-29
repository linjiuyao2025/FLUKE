from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from wanxiang.issue_tools import (
    IssueToolError,
    build_issue_prompt,
    save_issue_json,
    serialize_issue_json,
)
from wanxiang.news_import import parse_issue_json


def valid_issue() -> dict[str, object]:
    def article(item_id: str, title: str) -> dict[str, object]:
        return {
            "id": item_id,
            "label": "科技观察",
            "category": "科技",
            "title": title,
            "summary": "经来源核对的简短摘要。",
            "body": ["第一段整理稿。", "第二段整理稿。"],
            "publisher": "Example Publisher",
            "publishedAt": "2026-09-27",
            "sourceTitle": title,
            "sourceUrl": "https://example.org/story",
            "caveats": "尚待后续观察。",
            "relatedCoverage": [
                {
                    "title": "关联报道",
                    "summary": "另一家来源独立报道同一事件。",
                    "publisher": "Another Publisher",
                    "publishedAt": "2026-09-26",
                    "sourceUrl": "https://example.net/related",
                }
            ],
            "updates": [
                {
                    "date": "2026-09-27",
                    "summary": "发布方补充说明。",
                    "publisher": "Example Publisher",
                    "sourceUrl": "https://example.org/update",
                }
            ],
        }

    return {
        "version": 1,
        "date": "2026-09-27",
        "topic": "合成测试刊",
        "editorNote": "只用于自动化测试。",
        "focus": [article("focus-01", "测试头条")],
        "highlights": [article("highlight-01", "测试看点")],
        "articles": [],
        "unknownExtension": {"keep": True},
    }


class BuildIssuePromptTests(unittest.TestCase):
    def test_prompt_uses_date_preferences_and_source_evidence_rules(self) -> None:
        prompt = build_issue_prompt(
            topics=["technology", "ai", "technology"],
            sources=["Nature", "Reuters"],
            custom_topics="AI Agent、独立游戏",
            custom_sources="本地媒体",
            today=date(2026, 9, 27),
        )

        self.assertIn('"date": "2026-09-27"', prompt)
        self.assertIn("科技数码", prompt)
        self.assertIn("人工智能", prompt)
        self.assertIn("AI Agent、独立游戏", prompt)
        self.assertIn("Nature", prompt)
        self.assertIn("Reuters", prompt)
        self.assertIn("候选媒体只用于发现报道", prompt)
        self.assertIn("relatedCoverage", prompt)
        self.assertIn("最多 5 条", prompt)
        self.assertIn("updates", prompt)
        self.assertIn("最多 8 条", prompt)
        self.assertIn("只输出一个可解析的 JSON 对象", prompt)
        self.assertEqual(prompt.count('"technology"'), 0)

    def test_prompt_rejects_non_text_preferences(self) -> None:
        with self.assertRaises(IssueToolError):
            build_issue_prompt(topics="technology")
        with self.assertRaises(IssueToolError):
            build_issue_prompt(sources=["Reuters", 3])

    def test_prompt_includes_optional_personalization_without_changing_default_contract(self) -> None:
        ordinary = build_issue_prompt(today=date(2026, 9, 27))
        personalized = build_issue_prompt(
            today=date(2026, 9, 27),
            personalization_summary="近期正向兴趣：科技；近期减少：来源：Example Publisher",
        )
        self.assertNotIn("近期个人兴趣信号", ordinary)
        self.assertIn("近期个人兴趣信号", personalized)
        self.assertIn("科技", personalized)
        self.assertIn("不能改变来源核验、证据标准或事实边界", personalized)
        with self.assertRaises(IssueToolError):
            build_issue_prompt(personalization_summary=[])  # type: ignore[arg-type]


class SerializeIssueTests(unittest.TestCase):
    def test_export_round_trips_and_preserves_optional_unknown_fields(self) -> None:
        issue = valid_issue()

        serialized = serialize_issue_json(issue)
        parsed = parse_issue_json(serialized)

        self.assertEqual(parsed["topic"], "合成测试刊")
        self.assertIn('"unknownExtension"', serialized)
        self.assertIn('"relatedCoverage"', serialized)
        self.assertIn('"updates"', serialized)
        self.assertTrue(serialized.endswith("\n"))
        self.assertEqual(issue["unknownExtension"], {"keep": True})

    def test_invalid_package_and_oversize_package_are_rejected(self) -> None:
        issue = valid_issue()
        issue["focus"] = []
        with self.assertRaisesRegex(IssueToolError, "校验失败"):
            serialize_issue_json(issue)

        large_issue = valid_issue()
        large_issue["extra"] = "x" * 500_001
        with self.assertRaisesRegex(IssueToolError, "500 KB"):
            serialize_issue_json(large_issue)

    def test_atomic_save_and_failed_replacement_keep_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "issue.json"
            original = serialize_issue_json(valid_issue())
            target.write_text(original, encoding="utf-8")

            invalid = valid_issue()
            invalid["focus"] = []
            with self.assertRaises(IssueToolError):
                save_issue_json(target, invalid)
            self.assertEqual(target.read_text(encoding="utf-8"), original)

            updated = valid_issue()
            updated["editorNote"] = "替换完成。"
            self.assertEqual(save_issue_json(target, updated), target)
            self.assertEqual(
                parse_issue_json(target.read_bytes())["editorNote"], "替换完成。"
            )
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
