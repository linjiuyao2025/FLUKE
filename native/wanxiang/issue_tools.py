"""Local helpers for generating an editorial prompt and exporting one issue."""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .news_import import MAX_ISSUE_JSON_BYTES, NewsImportError, parse_issue_json


class IssueToolError(ValueError):
    """Readable error raised while creating or exporting an issue package."""


_TOPIC_LABELS = {
    "news": "新闻与时事",
    "domestic": "国内",
    "international": "国际",
    "finance": "财经商业",
    "technology": "科技数码",
    "ai": "人工智能",
    "games": "游戏",
    "culture": "文化影视",
    "health": "健康",
    "life": "生活方式",
    "other": "其他",
}


def _text_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise IssueToolError(f"{label}必须是文本数组。")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise IssueToolError(f"{label}只能包含文本。")
        clean = item.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean[:120])
    return result


def build_issue_prompt(
    *,
    topics: Any = None,
    sources: Any = None,
    custom_topics: str = "",
    custom_sources: str = "",
    personalization_summary: str = "",
    today: date | None = None,
) -> str:
    """Build the user-triggered prompt for one source-aware daily issue."""
    topic_keys = _text_list(topics, "关注主题")
    source_names = _text_list(sources, "候选媒体")
    if not isinstance(custom_topics, str) or not isinstance(custom_sources, str):
        raise IssueToolError("自定义关注方向必须是文本。")
    if not isinstance(personalization_summary, str):
        raise IssueToolError("个性化摘要必须是文本。")

    topic_lines = [
        f"- {key}：{_TOPIC_LABELS.get(key, key)}" for key in topic_keys
    ]
    custom_topic = custom_topics.strip()[:240]
    if custom_topic:
        topic_lines.append(f"- 自定义方向：{custom_topic}")
    source_lines = [f"- {source}" for source in source_names]
    custom_source = custom_sources.strip()[:240]
    if custom_source:
        source_lines.append(f"- 自定义候选媒体：{custom_source}")

    topic_text = "\n".join(topic_lines) if topic_lines else "- 尚未选择；请先询问我关注的主题。"
    source_text = "\n".join(source_lines) if source_lines else "- 未指定；请说明你实际核验的来源。"
    issue_date = (today or date.today()).isoformat()
    personalization = personalization_summary.strip()[:600]
    personalization_section = (
        f"\n## 近期个人兴趣信号\n{personalization}\n"
        "请将它作为选题排序的次要参考；它不能改变来源核验、证据标准或事实边界。\n"
        if personalization
        else ""
    )

    return f"""请为我编辑一期「FLUKE」每日新闻刊。目标刊期：{issue_date}。

## 我的关注方向
{topic_text}

## 候选媒体
{source_text}
{personalization_section}

候选媒体只用于发现报道，不代表该媒体每篇内容都可靠。逐篇核对作者、原始标题、发布时间、正文、原始来源链接和支撑关键事实的材料；优先原创调查、采访、数据报道、同行评审研究及官方原始文件。重大或有争议的事实应交叉核查，并明确区分记者核实、当事人陈述、公司回应、研究推断和仍未知的边界。排除转载、营销、缺乏证据的夸张标题和没有新增事实的旧闻。不要为了填满数量编造内容；正文不可读时不要依据搜索摘要补写。

只输出一个可解析的 JSON 对象，不要 Markdown 代码围栏或 JSON 之外的说明。每篇正文不能复制新闻源全文；请用自己的话整理，并把查证链接留在条目中。格式如下：
{{
  "version": 1,
  "date": "{issue_date}",
  "topic": "本期主题",
  "editorNote": "可选说明",
  "focus": [
    {{
      "id": "focus-01", "label": "栏目", "category": "主题分类",
      "title": "标题", "summary": "短摘要", "body": ["整理稿段落"],
      "publisher": "发布方", "publishedAt": "发布时间",
      "sourceTitle": "原始来源标题", "sourceUrl": "https://example.org/article",
      "relevance": "与关注方向的关系", "action": "可选行动",
      "caveats": "事实边界或仍未知处",
      "relatedCoverage": [{{"title": "关联报道", "summary": "关系", "publisher": "发布方", "publishedAt": "日期", "sourceUrl": "https://example.org/related"}}],
      "updates": [{{"date": "日期", "summary": "进展", "publisher": "发布方", "sourceUrl": "https://example.org/update"}}]
    }}
  ],
  "highlights": [{{"id": "highlight-01", "label": "栏目", "title": "标题", "summary": "摘要", "body": ["整理稿段落"], "publisher": "发布方", "publishedAt": "发布时间", "sourceTitle": "原文标题", "sourceUrl": "https://example.org/highlight"}}],
  "articles": []
}}

每条内容对象至少包含 id、label、title、summary、body、publisher、publishedAt、sourceTitle 和有效 HTTPS sourceUrl。focus 必须有 1–5 条，highlights 有 1–8 条，articles 可为 0–12 条；数量不足时说明真实原因，不得编造。body 使用段落字符串数组。relatedCoverage 最多 5 条，每条使用 title、summary、publisher、publishedAt、sourceUrl；updates 最多 8 条，每条使用 date、summary、publisher、sourceUrl。focus、highlights、articles 三组 id 必须互不重复。"""


def serialize_issue_json(issue: Any) -> str:
    """Validate and pretty-print a package without dropping unknown fields."""
    if not isinstance(issue, dict):
        raise IssueToolError("没有可导出的新闻刊期对象。")
    try:
        text = json.dumps(issue, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_ISSUE_JSON_BYTES:
            raise IssueToolError("本期超过 500 KB，无法导出为可重新导入的内容包。")
        parse_issue_json(encoded)
    except IssueToolError:
        raise
    except NewsImportError as exc:
        raise IssueToolError(f"本期校验失败，未导出：{exc}") from exc
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise IssueToolError("本期不是可导出的标准 JSON 内容包。") from exc
    return text


def save_issue_json(path: str | Path, issue: Any) -> Path:
    """Atomically save one validated issue beside its chosen destination."""
    destination = Path(path).expanduser()
    if not destination.name or not destination.parent.is_dir():
        raise IssueToolError("导出目录不存在，请选择一个有效的本机位置。")
    payload = serialize_issue_json(issue).encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
    except (OSError, ValueError) as exc:
        raise IssueToolError(f"导出失败，原文件未被部分写入：{exc}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return destination


__all__ = [
    "IssueToolError",
    "build_issue_prompt",
    "save_issue_json",
    "serialize_issue_json",
]
