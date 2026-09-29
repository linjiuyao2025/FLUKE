from __future__ import annotations

import json
import unittest

from wanxiang.news_import import (
    NewsImportError,
    normalize_issue,
    normalize_news_url,
    parse_issue_json,
)


def _article(title: str, article_id: str | None = "story-1") -> dict[str, object]:
    result: dict[str, object] = {
        "label": "  合成栏目  ",
        "title": title,
        "summary": "合成摘要",
        "body": ["第一段合成正文", "第二段合成正文"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-20T08:00:00Z",
        "sourceUrl": "https://news.example.com/story",
    }
    if article_id is not None:
        result["id"] = article_id
    return result


def _issue() -> dict[str, object]:
    return {
        "version": 1,
        "date": "2026-09-20",
        "topic": "合成主题",
        "focus": [_article("合成焦点")],
        "highlights": [_article("合成快讯", "brief-1")],
    }


class IssueImportTests(unittest.TestCase):
    def test_parses_and_normalizes_legacy_v1_json(self) -> None:
        payload = _issue()
        payload["version"] = "1"  # The old JavaScript Number check accepted this.
        payload["focus"] = [
            {
                **_article("  合成焦点  ", article_id=None),
                "body": "第一段合成正文\n\n第二段合成正文",
                "sourceUrl": "HTTPS://NEWS.EXAMPLE.COM:443/story",
            }
        ]

        normalized = parse_issue_json(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(normalized["version"], 1)
        self.assertEqual(normalized["topic"], "合成主题")
        self.assertEqual(normalized["articles"], [])
        self.assertEqual(normalized["focus"][0]["id"], "focus-1")
        self.assertEqual(normalized["focus"][0]["title"], "合成焦点")
        self.assertEqual(normalized["focus"][0]["body"], ["第一段合成正文", "第二段合成正文"])
        self.assertEqual(normalized["focus"][0]["sourceUrl"], "https://news.example.com/story")

    def test_accepts_byte_input_with_utf8_bom(self) -> None:
        encoded = json.dumps(_issue(), ensure_ascii=False).encode("utf-8")
        normalized = parse_issue_json(b"\xef\xbb\xbf" + encoded)
        self.assertEqual(normalized["date"], "2026-09-20")

    def test_requires_object_v1_and_real_calendar_date(self) -> None:
        with self.assertRaisesRegex(NewsImportError, "最外层"):
            normalize_issue([])

        payload = _issue()
        payload["version"] = 2
        payload["date"] = "2026-02-30"
        with self.assertRaises(NewsImportError) as caught:
            normalize_issue(payload)
        self.assertIn("version 必须为 1", str(caught.exception))
        self.assertIn("有效的 YYYY-MM-DD", str(caught.exception))

    def test_requires_topic_and_focus_highlights(self) -> None:
        payload = _issue()
        payload["topic"] = "  "
        payload["focus"] = []
        payload["highlights"] = []
        with self.assertRaises(NewsImportError) as caught:
            normalize_issue(payload)
        self.assertIn("topic 不能为空", str(caught.exception))
        self.assertIn("focus 需要 1–5 条", str(caught.exception))
        self.assertIn("highlights 需要 1–8 条", str(caught.exception))

    def test_enforces_all_group_upper_bounds(self) -> None:
        payload = _issue()
        payload["focus"] = [_article(f"焦点 {index}", f"f-{index}") for index in range(6)]
        payload["highlights"] = [_article(f"快讯 {index}", f"h-{index}") for index in range(9)]
        payload["articles"] = [_article(f"延伸 {index}", f"a-{index}") for index in range(13)]
        with self.assertRaises(NewsImportError) as caught:
            normalize_issue(payload)
        self.assertIn("focus 需要 1–5 条", str(caught.exception))
        self.assertIn("highlights 需要 1–8 条", str(caught.exception))
        self.assertIn("articles 需要 0–12 条", str(caught.exception))

    def test_rejects_missing_required_article_fields_and_empty_body(self) -> None:
        payload = _issue()
        payload["focus"] = [{"title": "合成焦点", "body": [" "]}]
        with self.assertRaises(NewsImportError) as caught:
            normalize_issue(payload)
        message = str(caught.exception)
        for expected in ("缺少 label", "缺少 summary", "缺少 publisher", "sourceUrl", "body"):
            self.assertIn(expected, message)

    def test_requires_https_source_urls(self) -> None:
        payload = _issue()
        payload["focus"] = [_article("焦点", "focus-1") | {"sourceUrl": "http://news.example.com/a"}]
        with self.assertRaisesRegex(NewsImportError, "HTTPS sourceUrl"):
            normalize_issue(payload)

    def test_normalizes_related_coverage_and_updates(self) -> None:
        payload = _issue()
        focus = _article("合成焦点")
        focus["relatedCoverage"] = [
            {
                "title": "  关联报道  ",
                "publisher": "合成媒体",
                "publishedAt": "2026-09-20",
                "sourceUrl": "https://coverage.example.org/report",
            }
        ]
        focus["updates"] = [
            {
                "date": "2026-09-21",
                "summary": "合成进展",
                "publisher": "合成媒体",
                "sourceUrl": "https://updates.example.org/story",
            }
        ]
        payload["focus"] = [focus]

        normalized = normalize_issue(payload)

        self.assertEqual(normalized["focus"][0]["relatedCoverage"][0]["title"], "关联报道")
        self.assertEqual(normalized["focus"][0]["updates"][0]["summary"], "合成进展")

    def test_enforces_related_coverage_and_update_limits_and_fields(self) -> None:
        payload = _issue()
        focus = _article("合成焦点")
        focus["relatedCoverage"] = [{}] * 6
        focus["updates"] = [{}] * 9
        payload["focus"] = [focus]
        with self.assertRaises(NewsImportError) as caught:
            normalize_issue(payload)
        message = str(caught.exception)
        self.assertIn("relatedCoverage 最多 5 项", message)
        self.assertIn("updates 最多 8 项", message)
        self.assertIn("relatedCoverage 第 1 项 缺少 title", message)
        self.assertIn("updates 第 1 项 缺少 date", message)

    def test_generates_absent_ids_but_rejects_duplicates_across_groups(self) -> None:
        payload = _issue()
        payload["focus"] = [_article("焦点", article_id=None)]
        payload["highlights"] = [_article("快讯", article_id=None)]
        normalized = normalize_issue(payload)
        self.assertEqual(normalized["focus"][0]["id"], "focus-1")
        self.assertEqual(normalized["highlights"][0]["id"], "highlights-1")

        duplicate_payload = _issue()
        duplicate_payload["highlights"] = [_article("重复 ID", "story-1")]
        with self.assertRaisesRegex(NewsImportError, "id 必须唯一"):
            normalize_issue(duplicate_payload)

    def test_rejects_invalid_json_and_nonstandard_numbers(self) -> None:
        with self.assertRaisesRegex(NewsImportError, "JSON 格式无效"):
            parse_issue_json("{bad json")
        with self.assertRaisesRegex(NewsImportError, "非标准数值"):
            parse_issue_json('{"version":NaN}')


class NewsUrlNormalizationTests(unittest.TestCase):
    def test_normalizes_public_http_and_https_urls(self) -> None:
        self.assertEqual(
            normalize_news_url("  HTTP://NEWS.EXAMPLE.COM:80/a b?q=中  "),
            "http://news.example.com/a%20b?q=%E4%B8%AD",
        )
        self.assertEqual(
            normalize_news_url("https://news.example.com:443/story#top"),
            "https://news.example.com/story#top",
        )

    def test_rejects_credentials(self) -> None:
        for value in (
            "https://user:password@news.example.com/story",
            "https://@news.example.com/story",
        ):
            with self.subTest(value=value), self.assertRaisesRegex(NewsImportError, "用户名或密码"):
                normalize_news_url(value)

    def test_rejects_non_web_schemes_and_relative_urls(self) -> None:
        for value in (
            "javascript:alert(1)",
            "file:///C:/private.txt",
            "data:text/html,hello",
            "ftp://news.example.com/file",
            "//news.example.com/story",
        ):
            with self.subTest(value=value), self.assertRaises(NewsImportError):
                normalize_news_url(value)

    def test_rejects_local_reserved_and_private_ip_hosts(self) -> None:
        for value in (
            "http://localhost/story",
            "http://printer.local/story",
            "http://news.test/story",
            "http://127.0.0.1/story",
            "http://10.0.0.8/story",
            "http://[::1]/story",
            "http://169.254.1.2/story",
            "http://127.1/story",
        ):
            with self.subTest(value=value), self.assertRaises(NewsImportError):
                normalize_news_url(value)

    def test_rejects_bad_ports_controls_and_malformed_escapes(self) -> None:
        for value in (
            "https://news.example.com:99999/story",
            "https://news.example.com:/story",
            "https://news.example.com/a%ZZ",
            "https://news.example.com/story\nhttps://other.example.org/",
            "https:\\news.example.com\\story",
        ):
            with self.subTest(value=value), self.assertRaises(NewsImportError):
                normalize_news_url(value)

    def test_source_urls_can_require_https(self) -> None:
        with self.assertRaisesRegex(NewsImportError, "sourceUrl 必须使用 HTTPS"):
            normalize_news_url("http://news.example.com/story", require_https=True)


if __name__ == "__main__":
    unittest.main()
