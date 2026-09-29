"""Validate legacy v1 news packages and normalize URLs dropped onto the UI.

This module is deliberately offline: URL validation never resolves a hostname
or makes an HTTP request. A normalized public URL is data to store or display,
not authorization to fetch it.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date
import ipaddress
import json
import re
from typing import Any, Iterable
from urllib.parse import quote, urlsplit, urlunsplit


ISSUE_VERSION = 1
MAX_ISSUE_JSON_BYTES = 500_000

_GROUP_BOUNDS = {
    "focus": (1, 5),
    "highlights": (1, 8),
    "articles": (0, 12),
}
_REQUIRED_ARTICLE_FIELDS = (
    "id",
    "label",
    "title",
    "summary",
    "publisher",
    "publishedAt",
)
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_NUMERIC_ADDRESS = re.compile(
    r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}\Z",
    re.IGNORECASE,
)
_BAD_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_IMAGE_DATA_URL = re.compile(
    r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})\Z",
    re.IGNORECASE,
)
_ASSET_IMAGE = re.compile(r"assets/[A-Za-z0-9._/-]+\Z")
_NON_PUBLIC_SUFFIXES = {
    "arpa",
    "example",
    "home",
    "internal",
    "invalid",
    "lan",
    "local",
    "localhost",
    "onion",
    "test",
}
_MISSING = object()


class NewsImportError(ValueError):
    """A user-facing, Chinese validation error (possibly several at once)."""

    def __init__(self, errors: str | Iterable[str]) -> None:
        if isinstance(errors, str):
            messages = (errors,)
        else:
            messages = tuple(errors)
        self.errors = messages
        super().__init__("\n".join(messages))


def _clean_text(value: Any, limit: int = 4000) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _validate_public_host(host: str) -> str:
    """Return a lowercase ASCII host after rejecting local/non-public targets."""
    if not host or "%" in host:
        raise NewsImportError("链接主机名无效。")

    candidate = host.rstrip(".")
    if not candidate:
        raise NewsImportError("链接主机名无效。")

    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        address = None

    if address is not None:
        if not address.is_global:
            raise NewsImportError("链接不能指向本机、内网或保留 IP 地址。")
        return address.compressed.lower()

    if _NUMERIC_ADDRESS.fullmatch(candidate):
        raise NewsImportError("链接中的数字 IP 地址格式无效。")

    try:
        ascii_host = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise NewsImportError("链接主机名无法转换为有效域名。") from exc

    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or len(labels) < 2 or any(
        not _DNS_LABEL.fullmatch(label) for label in labels
    ):
        raise NewsImportError("链接必须使用公开、格式有效的域名。")
    if any(
        ascii_host == suffix or ascii_host.endswith("." + suffix)
        for suffix in _NON_PUBLIC_SUFFIXES
    ):
        raise NewsImportError("链接不能指向本机、内网或保留域名。")
    return ascii_host


def normalize_news_url(value: str, *, require_https: bool = False) -> str:
    """Normalize one absolute public HTTP(S) URL without contacting it.

    Credentials, local/reserved hosts, malformed escapes, control characters,
    and schemes other than HTTP(S) are rejected. Hostnames are IDNA-normalized,
    scheme/host casing is canonicalized, default ports are removed, and an
    empty path becomes ``/``. DNS names are not resolved here.
    """
    if not isinstance(value, str):
        raise NewsImportError("新闻链接必须是文本。")

    raw = value.strip()
    if not raw:
        raise NewsImportError("新闻链接不能为空。")
    if "\\" in raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise NewsImportError("新闻链接包含控制字符，请复制完整链接后重试。")

    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise NewsImportError("新闻链接格式无效。") from exc

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise NewsImportError("只接受 http:// 或 https:// 新闻链接。")
    if require_https and scheme != "https":
        raise NewsImportError("sourceUrl 必须使用 HTTPS。")
    if not parts.netloc or not parts.hostname:
        raise NewsImportError("新闻链接必须包含公开网站主机名。")
    if any(char.isspace() for char in parts.netloc):
        raise NewsImportError("新闻链接主机名不能包含空格。")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise NewsImportError("新闻链接不能包含用户名或密码。")
    if parts.netloc.endswith(":"):
        raise NewsImportError("新闻链接端口无效。")
    if any(
        _BAD_PERCENT_ESCAPE.search(component)
        for component in (parts.path, parts.query, parts.fragment)
    ):
        raise NewsImportError("新闻链接包含无效的百分号编码。")

    try:
        port = parts.port
    except ValueError as exc:
        raise NewsImportError("新闻链接端口无效。") from exc
    if port is not None and not 1 <= port <= 65535:
        raise NewsImportError("新闻链接端口必须在 1 到 65535 之间。")

    raw_host = parts.hostname
    try:
        address = ipaddress.ip_address(raw_host)
    except ValueError:
        address = None
    host = _validate_public_host(raw_host)
    authority_host = f"[{host}]" if isinstance(address, ipaddress.IPv6Address) else host

    default_port = 80 if scheme == "http" else 443
    authority = authority_host if port is None or port == default_port else f"{authority_host}:{port}"
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/?%:@!$&'()*+,;=-._~")
    fragment = quote(parts.fragment, safe="/?%:@!$&'()*+,;=-._~")
    return urlunsplit((scheme, authority, path, query, fragment))


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NewsImportError(f"JSON 对象包含重复字段：{key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise NewsImportError(f"JSON 包含非标准数值：{value}")


def parse_issue_json(source: str | bytes | bytearray) -> dict[str, Any]:
    """Parse and validate a legacy version-1 issue JSON document.

    Returns a normalized dictionary. Invalid input raises ``NewsImportError``
    with one or more user-facing Chinese messages. This function performs no
    file access and makes no network requests.
    """
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
        if len(raw) > MAX_ISSUE_JSON_BYTES:
            raise NewsImportError("新闻内容包超过 500 KB，请压缩图片后再导入。")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise NewsImportError("新闻内容包不是有效的 UTF-8 文本。") from exc
    elif isinstance(source, str):
        text = source
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise NewsImportError("新闻内容包包含无法编码的字符。") from exc
        # The legacy text editor measured JavaScript UTF-16 code units, while
        # the file picker measured bytes. Preserve the limit for each input.
        utf16_units = len(text.encode("utf-16-le")) // 2
        if utf16_units > MAX_ISSUE_JSON_BYTES:
            raise NewsImportError("新闻内容包超过 500 KB，请压缩图片后再导入。")
        text = text.removeprefix("\ufeff")
    else:
        raise NewsImportError("新闻内容包必须是 JSON 文本或 UTF-8 字节。")

    try:
        payload = json.loads(
            text,
            object_pairs_hook=_json_pairs,
            parse_constant=_reject_json_constant,
        )
    except NewsImportError:
        raise
    except json.JSONDecodeError as exc:
        raise NewsImportError(
            f"JSON 格式无效：{exc.msg}（第 {exc.lineno} 行，第 {exc.colno} 列）。"
        ) from exc
    return normalize_issue(payload)


def _is_legacy_version_one(value: Any) -> bool:
    # The legacy JavaScript validator used Number(value) === 1. Reject bools,
    # which Python otherwise treats as integers, but keep ordinary numeric
    # spellings that the old validator accepted.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return False
    try:
        return float(value) == 1.0
    except (ValueError, OverflowError):
        return False


def _normalize_body(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for part in value if (text := _clean_text(part))]
    if isinstance(value, str):
        return [
            text
            for part in re.split(r"\n\s*\n", value)
            if (text := _clean_text(part))
        ]
    return []


def _normalize_image(value: Any, label: str, errors: list[str]) -> dict[str, str] | None:
    # The legacy reader ignored non-object image values.
    if not isinstance(value, dict):
        return None

    raw_src = value.get("src")
    src_text = _clean_text(raw_src, 2_500_000)
    image_src = ""
    if raw_src:
        match = _IMAGE_DATA_URL.fullmatch(src_text)
        if match and len(src_text) <= 2_200_000:
            try:
                base64.b64decode(match.group(1), validate=True)
                image_src = src_text
            except (binascii.Error, ValueError):
                pass
        elif _ASSET_IMAGE.fullmatch(src_text) and ".." not in src_text.split("/"):
            image_src = src_text
        else:
            try:
                image_src = normalize_news_url(src_text, require_https=True)
            except NewsImportError:
                image_src = ""
        if not image_src:
            errors.append(f"{label} 的图片地址格式不支持。")

    return {
        "src": image_src,
        "alt": _clean_text(value.get("alt"), 240),
        "caption": _clean_text(value.get("caption"), 400),
    }


def _normalize_related_coverage(
    value: Any,
    label: str,
    errors: list[str],
) -> list[dict[str, str]]:
    if value is _MISSING:
        return []
    if not isinstance(value, list):
        errors.append(f"{label} relatedCoverage 必须是数组。")
        return []
    if len(value) > 5:
        errors.append(f"{label} relatedCoverage 最多 5 项。")

    result: list[dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        item_label = f"{label} relatedCoverage 第 {index} 项"
        if not isinstance(item, dict):
            errors.append(f"{item_label} 必须是对象。")
            continue
        normalized = {
            "title": _clean_text(item.get("title"), 180),
            "summary": _clean_text(item.get("summary"), 400),
            "publisher": _clean_text(item.get("publisher"), 120),
            "publishedAt": _clean_text(item.get("publishedAt"), 80),
            "sourceUrl": "",
        }
        for field in ("title", "publisher", "publishedAt"):
            if not normalized[field]:
                errors.append(f"{item_label} 缺少 {field}。")
        try:
            normalized["sourceUrl"] = normalize_news_url(
                item.get("sourceUrl"), require_https=True
            )
        except NewsImportError:
            errors.append(f"{item_label} 需要有效的 HTTPS sourceUrl。")
        result.append(normalized)
    return result


def _normalize_updates(
    value: Any,
    label: str,
    errors: list[str],
) -> list[dict[str, str]]:
    if value is _MISSING:
        return []
    if not isinstance(value, list):
        errors.append(f"{label} updates 必须是数组。")
        return []
    if len(value) > 8:
        errors.append(f"{label} updates 最多 8 项。")

    result: list[dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        item_label = f"{label} updates 第 {index} 项"
        if not isinstance(item, dict):
            errors.append(f"{item_label} 必须是对象。")
            continue
        normalized = {
            "date": _clean_text(item.get("date"), 80),
            "summary": _clean_text(item.get("summary"), 600),
            "publisher": _clean_text(item.get("publisher"), 120),
            "sourceUrl": "",
        }
        for field in ("date", "summary", "publisher"):
            if not normalized[field]:
                errors.append(f"{item_label} 缺少 {field}。")
        try:
            normalized["sourceUrl"] = normalize_news_url(
                item.get("sourceUrl"), require_https=True
            )
        except NewsImportError:
            errors.append(f"{item_label} 需要有效的 HTTPS sourceUrl。")
        result.append(normalized)
    return result


def _normalize_article(
    item: dict[str, Any],
    group: str,
    index: int,
    errors: list[str],
) -> dict[str, Any]:
    label = f"{group} 第 {index + 1} 条"
    body = _normalize_body(item.get("body"))
    normalized: dict[str, Any] = {
        "id": _clean_text(item.get("id"), 64) or f"{group}-{index + 1}",
        "group": group,
        "label": _clean_text(item.get("label"), 80),
        "category": _clean_text(item.get("category"), 80),
        "title": _clean_text(item.get("title"), 180),
        "summary": _clean_text(item.get("summary"), 600),
        "body": body,
        "publisher": _clean_text(item.get("publisher"), 120),
        "publishedAt": _clean_text(item.get("publishedAt"), 80),
        "sourceTitle": _clean_text(item.get("sourceTitle"), 180),
        "sourceUrl": "",
        "relevance": _clean_text(item.get("relevance"), 1200),
        "action": _clean_text(item.get("action"), 800),
        "caveats": _clean_text(item.get("caveats"), 1200),
        "relatedCoverage": _normalize_related_coverage(
            item.get("relatedCoverage", _MISSING), label, errors
        ),
        "updates": _normalize_updates(item.get("updates", _MISSING), label, errors),
        "image": _normalize_image(item.get("image"), label, errors),
    }

    for field in _REQUIRED_ARTICLE_FIELDS:
        if not normalized[field]:
            errors.append(f"{label} 缺少 {field}。")
    if not body:
        errors.append(f"{label} 需要至少一个非空 body 段落。")
    try:
        normalized["sourceUrl"] = normalize_news_url(
            item.get("sourceUrl"), require_https=True
        )
    except NewsImportError:
        errors.append(f"{label} 需要有效的 HTTPS sourceUrl。")
    return normalized


def normalize_issue(payload: Any) -> dict[str, Any]:
    """Validate an already-decoded legacy issue and return its normalized form."""
    if not isinstance(payload, dict):
        raise NewsImportError("内容包最外层必须是 JSON 对象。")

    errors: list[str] = []
    if not _is_legacy_version_one(payload.get("version")):
        errors.append("内容包 version 必须为 1。")

    raw_date = payload.get("date")
    normalized_date = raw_date if isinstance(raw_date, str) else ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized_date):
        errors.append("date 必须使用有效的 YYYY-MM-DD 日期。")
    else:
        try:
            date.fromisoformat(normalized_date)
        except ValueError:
            errors.append("date 必须使用有效的 YYYY-MM-DD 日期。")

    topic = _clean_text(payload.get("topic"), 100)
    if not topic:
        errors.append("topic 不能为空。")

    normalized_groups: dict[str, list[dict[str, Any]]] = {}
    article_ids: list[str] = []
    for group, (minimum, maximum) in _GROUP_BOUNDS.items():
        if group == "articles" and group not in payload:
            items: Any = []
        else:
            items = payload.get(group)
        if not isinstance(items, list):
            errors.append(f"{group} 必须是数组，包含 {minimum}–{maximum} 条。")
            normalized_groups[group] = []
            continue
        if not minimum <= len(items) <= maximum:
            errors.append(f"{group} 需要 {minimum}–{maximum} 条。")

        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{group} 第 {index + 1} 条必须是对象。")
                continue
            normalized = _normalize_article(item, group, index, errors)
            normalized_items.append(normalized)
            if normalized["id"]:
                article_ids.append(normalized["id"])
        normalized_groups[group] = normalized_items

    if len(article_ids) != len(set(article_ids)):
        errors.append("所有条目的 id 必须唯一。")

    if errors:
        raise NewsImportError(errors)

    return {
        "version": ISSUE_VERSION,
        "date": normalized_date,
        "topic": topic,
        "editorNote": _clean_text(payload.get("editorNote"), 500),
        "focus": normalized_groups["focus"],
        "highlights": normalized_groups["highlights"],
        "articles": normalized_groups["articles"],
    }


__all__ = [
    "ISSUE_VERSION",
    "MAX_ISSUE_JSON_BYTES",
    "NewsImportError",
    "normalize_issue",
    "normalize_news_url",
    "parse_issue_json",
]
