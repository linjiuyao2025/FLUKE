"""Local, explainable ranking for already-validated daily news issues."""

from __future__ import annotations

from copy import deepcopy
from contextlib import closing
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
import unicodedata


RECOMMENDATION_SCHEMA_VERSION = 1
FEEDBACK_ACTIONS = {"useful", "not_interested", "more_topic", "less_source"}
MAX_FEEDBACK_ROWS = 500
FEEDBACK_HALF_LIFE_DAYS = 45
PROMPT_FEEDBACK_MAX_AGE_DAYS = 90
_GROUPS = ("focus", "highlights", "articles")
_WORD = re.compile(r"[a-z0-9][a-z0-9._+-]*|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
_SPLIT = re.compile(r"[,，、;；\n]+")

_TOPIC_TERMS = {
    "news": ("新闻与时事", "时事"),
    "domestic": ("国内", "中国"),
    "international": ("国际", "全球"),
    "finance": ("财经", "金融", "商业", "经济"),
    "technology": ("科技", "数码", "技术", "technology", "tech"),
    "ai": ("人工智能", "大模型", "机器学习", "ai"),
    "games": ("游戏", "电竞", "games", "gaming"),
    "culture": ("文化", "影视", "电影", "culture"),
    "health": ("健康", "医疗", "health"),
    "life": ("生活方式", "生活", "life"),
}


class RecommendationError(ValueError):
    """Readable validation or storage error for local recommendation data."""


class RecommendationRepositoryError(RuntimeError):
    """Local SQLite recommendation storage could not be read or written."""


def _clean_text(value: Any, maximum: int = 160) -> str:
    return value.strip()[:maximum] if isinstance(value, str) else ""


def _article_features(article: dict[str, Any]) -> dict[str, str]:
    """Keep only small, non-sensitive metadata needed to explain feedback."""
    return {
        "label": _clean_text(article.get("label"), 80),
        "category": _clean_text(article.get("category"), 80),
        "publisher": _clean_text(article.get("publisher"), 120),
        "title": _clean_text(article.get("title"), 180),
        "topics": _clean_text(article.get("topics"), 240),
    }


def _item_terms(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("topics", "category", "label", "title"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            values.extend(part.strip().casefold() for part in _SPLIT.split(value) if part.strip())
        elif isinstance(value, list):
            values.extend(
                part.strip().casefold()
                for part in value
                if isinstance(part, str) and part.strip()
            )
    return list(dict.fromkeys(values))


def _topic_preferences(preferences: Any) -> tuple[list[str], list[str], list[str]]:
    if not isinstance(preferences, dict):
        return [], [], []
    nested = preferences.get("preferences")
    nested = nested if isinstance(nested, dict) else preferences
    raw_topics = preferences.get("topics", [])
    topics = [value for value in raw_topics if isinstance(value, str)] if isinstance(raw_topics, list) else []
    topic_terms: list[str] = []
    for topic in topics:
        topic_terms.extend(_TOPIC_TERMS.get(topic.casefold(), (topic,)))
    custom = nested.get("subtopics", nested.get("customTopics", ""))
    if isinstance(custom, str):
        topic_terms.extend(part.strip() for part in _SPLIT.split(custom) if part.strip())
    sources = nested.get("presetSources", nested.get("sources", []))
    source_terms = [value for value in sources if isinstance(value, str)] if isinstance(sources, list) else []
    custom_sources = nested.get("sources", nested.get("customSources", ""))
    if isinstance(custom_sources, str):
        source_terms.extend(part.strip() for part in _SPLIT.split(custom_sources) if part.strip())
    return topics, list(dict.fromkeys(topic_terms)), list(dict.fromkeys(source_terms))


def _contains_any(haystack: str, needles: list[str]) -> list[str]:
    folded = unicodedata.normalize("NFKC", haystack).casefold()
    return [needle for needle in needles if needle and unicodedata.normalize("NFKC", needle).casefold() in folded]


def _age_days(created_at: Any, today: date) -> int:
    if not isinstance(created_at, str):
        return 0
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    except ValueError:
        return 0
    return max(0, (today - parsed).days)


def rank_group(
    items: Any,
    *,
    preferences: Any = None,
    feedback: list[dict[str, Any]] | None = None,
    clippings: list[dict[str, Any]] | None = None,
    issue_topic: str = "",
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return an explained, stable ordering without mutating its input list.

    This function only ranks supplied items. It does not fetch, admit, remove,
    or validate candidate news; callers must pass normalized issue content.
    """
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise RecommendationError("排序条目必须是文章对象数组。")
    if not items:
        return []
    today = today or date.today()
    feedback = feedback or []
    clippings = clippings or []
    _, manual_topics, manual_sources = _topic_preferences(preferences)
    has_signal = bool(manual_topics or manual_sources or feedback or clippings)
    if not has_signal:
        return [
            {"item": deepcopy(item), "score": 0.0, "reason": "尚无个性化信号，保留原编辑顺序。", "rank": index + 1}
            for index, item in enumerate(items)
        ]

    feedback_signals: list[tuple[dict[str, Any], str, float]] = []
    for entry in feedback:
        if not isinstance(entry, dict) or entry.get("action") not in FEEDBACK_ACTIONS:
            continue
        age = _age_days(entry.get("createdAt"), today)
        strength = 0.5 ** (age / FEEDBACK_HALF_LIFE_DAYS)
        features = entry.get("article")
        if isinstance(features, dict):
            feedback_signals.append((features, entry["action"], strength))

    clip_items = [
        entry.get("item") for entry in clippings
        if isinstance(entry, dict) and isinstance(entry.get("item"), dict)
    ]
    scored: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        searchable = " ".join(
            _clean_text(item.get(key))
            for key in ("topics", "category", "label", "title", "summary", "relevance", "publisher")
        ) + " " + issue_topic
        topic_hits = _contains_any(searchable, manual_topics)
        source_hits = _contains_any(_clean_text(item.get("publisher")), manual_sources)
        score = 2.0 * len(topic_hits) + 0.55 * len(source_hits)
        reasons = [f"关注主题：{hit}" for hit in topic_hits[:2]]
        reasons.extend(f"关注来源：{hit}" for hit in source_hits[:1])

        for features, action, strength in feedback_signals:
            if action == "less_source":
                publisher = _clean_text(features.get("publisher"))
                target = _clean_text(item.get("publisher"))
                if publisher and target and publisher.casefold() == target.casefold():
                    score -= 2.5 * strength
                    reasons.append("你反馈希望少看这个来源")
                continue
            terms = _item_terms(features)
            matches = _contains_any(searchable, terms)
            if not matches:
                continue
            if action == "useful":
                score += 1.5 * strength
                reasons.append("与你标记为有用的主题相近")
            elif action == "not_interested":
                score -= 2.2 * strength
                reasons.append("与你标记为不感兴趣的主题相近")
            elif action == "more_topic":
                score += 2.4 * strength
                reasons.append("你希望多看这个主题")

        for clipped in clip_items:
            terms = _item_terms(clipped)
            matches = _contains_any(searchable, terms)
            if matches:
                score += 0.9
                reasons.append("与你收进剪报的主题相近")
                break

        published = _clean_text(item.get("publishedAt"))[:10]
        try:
            age = max(0, (today - date.fromisoformat(published)).days)
        except ValueError:
            age = None
        if age is not None and age <= 7:
            freshness = (7 - age) / 28
            score += freshness
            if freshness >= 0.1:
                reasons.append("发布时间较近")
        scored.append({"item": deepcopy(item), "score": round(score, 4), "reasons": reasons, "index": index})

    # Greedy, small same-category penalty promotes variety without crossing groups.
    remaining = list(scored)
    ordered: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    while remaining:
        best = max(
            remaining,
            key=lambda candidate: (
                candidate["score"] - 0.25 * category_counts.get(_clean_text(candidate["item"].get("category")).casefold(), 0),
                -candidate["index"],
            ),
        )
        remaining.remove(best)
        category = _clean_text(best["item"].get("category")).casefold()
        category_counts[category] = category_counts.get(category, 0) + 1
        reason = "；".join(dict.fromkeys(best["reasons"])) or "保留原编辑顺序作为同分顺序。"
        ordered.append({"item": best["item"], "score": best["score"], "reason": reason, "rank": len(ordered) + 1})
    return ordered


def feedback_summary(feedback: list[dict[str, Any]], *, today: date | None = None) -> str:
    """Summarize recent explicit feedback without reviving stale preferences."""
    today = today or date.today()
    positive: list[str] = []
    negative: list[str] = []
    for entry in feedback:
        if not isinstance(entry, dict):
            continue
        created_at = entry.get("createdAt")
        if not isinstance(created_at, str):
            continue
        try:
            created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if max(0, (today - created_date).days) > PROMPT_FEEDBACK_MAX_AGE_DAYS:
            continue
        action = entry.get("action")
        article = entry.get("article")
        if not isinstance(article, dict):
            continue
        if action in {"more_topic", "useful"}:
            term = _clean_text(article.get("category")) or _clean_text(article.get("label"))
            if term and term not in positive:
                positive.append(term)
        elif action == "not_interested":
            term = _clean_text(article.get("category")) or _clean_text(article.get("label"))
            if term and term not in negative:
                negative.append(term)
        elif action == "less_source":
            term = _clean_text(article.get("publisher"))
            if term and term not in negative:
                negative.append(f"来源：{term}")
    parts: list[str] = []
    if positive:
        parts.append("近期正向兴趣：" + "、".join(positive[:6]))
    if negative:
        parts.append("近期减少：" + "、".join(negative[:6]))
    return "；".join(parts)


def personalized_summary(
    feedback: list[dict[str, Any]],
    clippings: list[dict[str, Any]] | None = None,
    *,
    today: date | None = None,
) -> str:
    """Combine concise explicit feedback and the active clipping collection."""
    parts = [feedback_summary(feedback, today=today)] if feedback else []
    clipped_topics: list[str] = []
    for clipping in clippings or []:
        article = clipping.get("item") if isinstance(clipping, dict) else None
        if not isinstance(article, dict):
            continue
        term = _clean_text(article.get("category")) or _clean_text(article.get("label"))
        if term and term not in clipped_topics:
            clipped_topics.append(term)
    if clipped_topics:
        parts.append("剪报关注：" + "、".join(clipped_topics[:6]))
    return "；".join(part for part in parts if part)


class RecommendationRepository:
    """Versioned local feedback tables, independent of legacy import schema."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        path = self.database_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS recommendation_schema ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS article_feedback ("
                "issue_date TEXT NOT NULL, article_id TEXT NOT NULL, "
                "action TEXT NOT NULL CHECK(action IN ('useful','not_interested','more_topic','less_source')), "
                "article_json TEXT NOT NULL, created_at TEXT NOT NULL, "
                "PRIMARY KEY(issue_date, article_id))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS article_feedback_created_idx ON article_feedback(created_at)"
            )
            row = connection.execute(
                "SELECT schema_version FROM recommendation_schema WHERE singleton=1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO recommendation_schema(singleton, schema_version) VALUES(1, ?)",
                    (RECOMMENDATION_SCHEMA_VERSION,),
                )
            elif row[0] > RECOMMENDATION_SCHEMA_VERSION or row[0] < 1:
                raise RecommendationRepositoryError("本机推荐数据版本不受支持。")
            elif row[0] < RECOMMENDATION_SCHEMA_VERSION:
                self._migrate(connection, row[0])
            connection.commit()
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            if isinstance(exc, RecommendationRepositoryError):
                raise
            raise RecommendationRepositoryError(f"初始化本机推荐数据失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _migrate(connection: sqlite3.Connection, from_version: int) -> None:
        if from_version != 1:
            raise RecommendationRepositoryError("找不到本机推荐数据的升级路径。")
        connection.execute(
            "UPDATE recommendation_schema SET schema_version=? WHERE singleton=1",
            (RECOMMENDATION_SCHEMA_VERSION,),
        )

    def set_feedback(self, issue_date: Any, article: Any, action: Any) -> str:
        if not isinstance(issue_date, str):
            raise RecommendationError("反馈必须关联有效刊期日期。")
        try:
            if date.fromisoformat(issue_date).isoformat() != issue_date:
                raise ValueError("non-canonical date")
        except ValueError as exc:
            raise RecommendationError("反馈必须关联有效刊期日期。") from exc
        if not isinstance(article, dict):
            raise RecommendationError("反馈文章格式无效。")
        article_id = _clean_text(article.get("id"), 64)
        if not article_id:
            raise RecommendationError("反馈文章缺少稳定 ID。")
        if not isinstance(action, str) or (action not in FEEDBACK_ACTIONS and action != ""):
            raise RecommendationError("反馈类型无效。")
        if action == "more_topic" and not (_clean_text(article.get("category")) or _clean_text(article.get("label"))):
            raise RecommendationError("这篇文章没有可用于反馈的主题标签。")
        if action == "less_source" and not _clean_text(article.get("publisher")):
            raise RecommendationError("这篇文章没有可用于反馈的来源名称。")
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            if action == "":
                connection.execute(
                    "DELETE FROM article_feedback WHERE issue_date=? AND article_id=?",
                    (issue_date, article_id),
                )
            else:
                article_json = json.dumps(_article_features(article), ensure_ascii=False, separators=(",", ":"))
                created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                connection.execute(
                    "INSERT INTO article_feedback(issue_date,article_id,action,article_json,created_at) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(issue_date,article_id) DO UPDATE SET "
                    "action=excluded.action, article_json=excluded.article_json, created_at=excluded.created_at",
                    (issue_date, article_id, action, article_json, created_at),
                )
                connection.execute(
                    "DELETE FROM article_feedback WHERE rowid IN ("
                    "SELECT rowid FROM article_feedback ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?)",
                    (MAX_FEEDBACK_ROWS,),
                )
            connection.commit()
            return action
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            if isinstance(exc, (RecommendationError, RecommendationRepositoryError)):
                raise
            raise RecommendationRepositoryError(f"保存文章反馈失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def feedback_for(self, issue_date: str, article_id: str) -> str:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT action FROM article_feedback WHERE issue_date=? AND article_id=?",
                    (issue_date, article_id),
                ).fetchone()
                return row[0] if row else ""
        except sqlite3.Error as exc:
            raise RecommendationRepositoryError(f"读取文章反馈失败：{exc}") from exc

    def all_feedback(self) -> list[dict[str, Any]]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT issue_date,article_id,action,article_json,created_at "
                    "FROM article_feedback ORDER BY created_at DESC, issue_date DESC, article_id"
                ).fetchall()
            return [
                {"date": row[0], "articleId": row[1], "action": row[2], "article": json.loads(row[3]), "createdAt": row[4]}
                for row in rows
            ]
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise RecommendationRepositoryError(f"读取本机推荐画像失败：{exc}") from exc

    def clear(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM article_feedback")
            connection.commit()
        except sqlite3.Error as exc:
            if connection is not None:
                connection.rollback()
            raise RecommendationRepositoryError(f"清除本机推荐画像失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()


__all__ = [
    "FEEDBACK_ACTIONS",
    "RecommendationError",
    "RecommendationRepository",
    "RecommendationRepositoryError",
    "feedback_summary",
    "personalized_summary",
    "rank_group",
]
