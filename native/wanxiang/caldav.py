from __future__ import annotations

import base64
from datetime import datetime, timezone
import ipaddress
import json
import posixpath
import re
from urllib.parse import SplitResult, unquote, urljoin, urlsplit, urlunsplit
from xml.sax.saxutils import escape as escape_xml
from xml.etree import ElementTree
from lxml import etree as SecureElementTree

from .calendar_exchange import (
    CalendarExchangeError,
    _fold_line,
    _folded_lines,
    _parse_content_line,
    _unescape_text,
    parse_ical_vtodos,
)


class CalDAVError(ValueError):
    pass


_MAX_URL_BYTES = 2_048
_MAX_CREDENTIAL_BYTES = 3_072
_DAV_NS = "DAV:"
_CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
_MAX_CALENDAR_DATA_BYTES = 2_000_000


def _parse_safe_xml(payload: bytes):
    parser = SecureElementTree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=False,
    )
    try:
        root = SecureElementTree.fromstring(payload, parser=parser)
    except SecureElementTree.XMLSyntaxError as exc:
        raise ElementTree.ParseError(str(exc)) from exc
    if root.getroottree().docinfo.doctype:
        raise CalDAVError("CalDAV 服务器返回了不安全的 XML，已停止解析。")
    return root


def normalize_caldav_url(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise CalDAVError("CalDAV 地址必须是文本。")
    source = value.strip()
    if not source or len(source.encode("utf-8")) > _MAX_URL_BYTES:
        raise CalDAVError("CalDAV 地址不能为空，且不能超过 2048 字节。")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in source):
        raise CalDAVError("CalDAV 地址不能包含空格或控制字符。")
    try:
        parts = urlsplit(source)
        scheme = parts.scheme.casefold()
        if scheme not in {"http", "https"}:
            raise CalDAVError("CalDAV 地址须使用 HTTP 或 HTTPS。")
        if parts.username is not None or parts.password is not None:
            raise CalDAVError("请把账号填入账号栏，不要写在 CalDAV 地址中。")
        hostname = parts.hostname
        if not hostname:
            raise CalDAVError("CalDAV 地址缺少服务器名称。")
        port = parts.port
        host_ascii = hostname.encode("idna").decode("ascii").casefold()
        if ":" in host_ascii and not host_ascii.startswith("["):
            host_ascii = f"[{host_ascii}]"
        host = f"{host_ascii}:{port}" if port is not None else host_ascii
        normalized = urlunsplit(SplitResult(
            scheme=scheme,
            netloc=parts.netloc,
            path=parts.path or "/",
            query=parts.query,
            fragment="",
        ))
    except CalDAVError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise CalDAVError("CalDAV 地址格式无效。") from exc
    if len(normalized.encode("utf-8")) > _MAX_URL_BYTES:
        raise CalDAVError("CalDAV 地址不能超过 2048 字节。")
    return normalized, host


def validate_caldav_credentials(username: object, password: object) -> tuple[str, str]:
    if not isinstance(username, str) or not isinstance(password, str):
        raise CalDAVError("CalDAV 账号和密码必须是文本。")
    if len(username.encode("utf-8")) > 256 or len(password.encode("utf-8")) > 1_024:
        raise CalDAVError("CalDAV 账号或密码超出长度限制。")
    if any(char in username for char in ":\r\n") or any(
        ord(char) < 32 or ord(char) == 127 for char in username + password
    ):
        raise CalDAVError("CalDAV 账号或密码包含不允许的控制字符。")
    if bool(username) != bool(password):
        raise CalDAVError("如服务器需要登录，请同时填写账号和密码。")
    return username, password


def validate_caldav_transport(url: object, has_credentials: bool) -> tuple[str, str]:
    normalized, host = normalize_caldav_url(url)
    parts = urlsplit(normalized)
    if parts.scheme == "http":
        hostname = (parts.hostname or "").casefold().rstrip(".")
        loopback = hostname == "localhost" or hostname.endswith(".localhost")
        if not loopback:
            try:
                loopback = ipaddress.ip_address(hostname.split("%", 1)[0]).is_loopback
            except ValueError:
                loopback = False
        if not loopback:
            raise CalDAVError("远程 CalDAV 地址必须使用 HTTPS；本机回环地址可用于本地测试。")
    return normalized, host


def protect_caldav_credentials(username: object, password: object, protector) -> str:
    normalized_username, normalized_password = validate_caldav_credentials(username, password)
    payload = json.dumps(
        {"username": normalized_username, "password": normalized_password},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > _MAX_CREDENTIAL_BYTES:
        raise CalDAVError("CalDAV 登录信息超出长度限制。")
    try:
        return protector(payload)
    except ValueError as exc:
        raise CalDAVError(str(exc)) from exc


def unprotect_caldav_credentials(value: object, unprotector) -> tuple[str, str]:
    if not isinstance(value, str) or not value or len(value) > 16_384:
        raise CalDAVError("CalDAV 登录信息无法解密，请重新添加账号。")
    try:
        payload = unprotector(value)
        if len(payload.encode("utf-8")) > _MAX_CREDENTIAL_BYTES:
            raise CalDAVError("CalDAV 登录信息超出长度限制。")
        decoded = json.loads(payload)
    except CalDAVError:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise CalDAVError("CalDAV 登录信息无法解密，请重新添加账号。") from exc
    if not isinstance(decoded, dict):
        raise CalDAVError("CalDAV 登录信息结构无效，请重新添加账号。")
    return validate_caldav_credentials(decoded.get("username"), decoded.get("password"))


def basic_authorization_header(username: str, password: str) -> bytes | None:
    username, password = validate_caldav_credentials(username, password)
    if not username:
        return None
    token = base64.b64encode(f"{username}:{password}".encode("utf-8"))
    return b"Basic " + token


def is_strong_caldav_etag(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 1_024
        and value.startswith('"')
        and value.endswith('"')
        and not value.startswith('W/')
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def caldav_propfind_body() -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><d:displayname/><d:resourcetype/>'
        '<c:supported-calendar-component-set/></d:prop></d:propfind>'
    ).encode("utf-8")


def caldav_vtodo_query_body() -> bytes:
    """Request all VCALENDAR resources so VEVENTs and VTODOs can share a snapshot."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
        '<c:filter><c:comp-filter name="VCALENDAR"/></c:filter>'
        '</c:calendar-query>'
    ).encode("utf-8")


def _validate_caldav_sync_token(value: object, *, allow_empty: bool) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 4_096:
        raise CalDAVError("CalDAV 同步令牌无效。")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise CalDAVError("CalDAV 同步令牌包含控制字符。")
    if not value and allow_empty:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise CalDAVError("CalDAV 同步令牌不是有效 URI。") from exc
    if not parsed.scheme:
        raise CalDAVError("CalDAV 同步令牌不是有效 URI。")
    return value


def caldav_sync_collection_body(sync_token: object = "") -> bytes:
    token = _validate_caldav_sync_token(sync_token, allow_empty=True)
    escaped_token = escape_xml(token)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:sync-collection xmlns:d="DAV:">'
        f'<d:sync-token>{escaped_token}</d:sync-token>'
        '<d:sync-level>1</d:sync-level>'
        '<d:prop><d:getetag/></d:prop>'
        '</d:sync-collection>'
    ).encode("utf-8")


def _status_code(value: str) -> int:
    match = re.search(r"\s(\d{3})\s", value)
    return int(match.group(1)) if match else 0


def caldav_sync_token_was_rejected(payload: bytes) -> bool:
    if not isinstance(payload, bytes) or not payload or len(payload) > 512_000:
        return False
    try:
        root = _parse_safe_xml(payload)
    except (ElementTree.ParseError, CalDAVError):
        return False
    return any(node.tag == f"{{{_DAV_NS}}}valid-sync-token" for node in root.iter())


def parse_caldav_sync_collection_report(
    payload: bytes, collection_url: str,
) -> dict[str, object]:
    if not isinstance(payload, bytes) or not payload or len(payload) > 2_000_000:
        raise CalDAVError("CalDAV 增量同步响应为空或超过 2 MB。")
    try:
        root = _parse_safe_xml(payload)
    except ElementTree.ParseError as exc:
        raise CalDAVError("CalDAV 增量同步响应无法解析。") from exc
    dav = f"{{{_DAV_NS}}}"
    if root.tag != dav + "multistatus":
        raise CalDAVError("CalDAV 服务器没有返回 Multi-Status 增量结果。")
    tokens = root.findall(dav + "sync-token")
    if len(tokens) != 1:
        raise CalDAVError("CalDAV 增量结果缺少唯一同步令牌。")
    token = _validate_caldav_sync_token(tokens[0].text or "", allow_empty=False)
    normalized_collection, _host = normalize_caldav_url(collection_url)
    changes: dict[str, dict[str, str]] = {}
    truncated = False
    for response in root.findall(dav + "response"):
        href = response.findtext(dav + "href", default="")
        response_status = _status_code(response.findtext(dav + "status", default=""))
        if response_status == 507:
            if not href.strip() or len(href) > 4_096:
                raise CalDAVError("CalDAV 分页响应缺少有效的日历集地址。")
            response_url = urljoin(normalized_collection, href.strip())
            response_parts = urlsplit(response_url)
            collection_parts = urlsplit(normalized_collection)
            if (
                _caldav_origin(response_parts) != _caldav_origin(collection_parts)
                or response_parts.query or response_parts.fragment
                or response_parts.path.rstrip("/") != collection_parts.path.rstrip("/")
            ):
                raise CalDAVError("CalDAV 对单个资源返回了 507，未应用增量。")
            truncated = True
            continue
        resource_url = resolve_caldav_resource_url(normalized_collection, href)
        if resource_url in changes:
            raise CalDAVError("CalDAV 增量结果包含重复资源地址。")
        if response_status == 404:
            changes[resource_url] = {"href": resource_url, "etag": "", "removed": "true"}
            continue
        if response_status and response_status != 200:
            raise CalDAVError(f"CalDAV 增量资源返回 HTTP {response_status}。")
        etag = ""
        for propstat in response.findall(dav + "propstat"):
            code = _status_code(propstat.findtext(dav + "status", default=""))
            if code == 200:
                prop = propstat.find(dav + "prop")
                if prop is not None:
                    etag = etag or prop.findtext(dav + "getetag", default="")
            elif code not in {403, 404}:
                raise CalDAVError(f"CalDAV 增量属性返回 HTTP {code or '错误'}。")
        if len(etag) > 1_024 or any(ord(char) < 32 or ord(char) == 127 for char in etag):
            raise CalDAVError("CalDAV 增量结果包含无效 ETag。")
        changes[resource_url] = {"href": resource_url, "etag": etag, "removed": "false"}
        if len(changes) > 500:
            raise CalDAVError("一次增量同步最多处理 500 个资源变更。")
    return {"syncToken": token, "changes": list(changes.values()), "truncated": truncated}


def caldav_calendar_multiget_body(resource_hrefs: object) -> bytes:
    if not isinstance(resource_hrefs, list) or not 1 <= len(resource_hrefs) <= 500:
        raise CalDAVError("CalDAV 多资源请求无效或超过 500 项。")
    href_lines: list[str] = []
    seen: set[str] = set()
    for href in resource_hrefs:
        if not isinstance(href, str) or not href or len(href) > 4_096:
            raise CalDAVError("CalDAV 多资源请求包含无效地址。")
        if href in seen:
            raise CalDAVError("CalDAV 多资源请求包含重复地址。")
        seen.add(href)
        href_lines.append(f"<d:href>{escape_xml(href)}</d:href>")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
        + "".join(href_lines)
        + '</c:calendar-multiget>'
    ).encode("utf-8")


def parse_caldav_calendar_multiget_report(
    payload: bytes, collection_url: str, requested_hrefs: object,
) -> dict[str, object]:
    if not isinstance(requested_hrefs, list) or not 1 <= len(requested_hrefs) <= 500:
        raise CalDAVError("CalDAV 多资源响应对应的地址列表无效。")
    requested = {
        resolve_caldav_resource_url(collection_url, href)
        for href in requested_hrefs
    }
    if len(requested) != len(requested_hrefs):
        raise CalDAVError("CalDAV 多资源响应包含重复请求地址。")
    if not isinstance(payload, bytes) or not payload or len(payload) > 2_000_000:
        raise CalDAVError("CalDAV 多资源响应为空或超过 2 MB。")
    try:
        root = _parse_safe_xml(payload)
    except ElementTree.ParseError as exc:
        raise CalDAVError("CalDAV 多资源响应无法解析。") from exc
    dav = f"{{{_DAV_NS}}}"
    cal = f"{{{_CALDAV_NS}}}"
    if root.tag != dav + "multistatus":
        raise CalDAVError("CalDAV 服务器没有返回 Multi-Status 多资源结果。")
    resources: dict[str, dict[str, object]] = {}
    removed: set[str] = set()
    total_data_bytes = 0
    for response in root.findall(dav + "response"):
        href = resolve_caldav_resource_url(collection_url, response.findtext(dav + "href", default=""))
        if href not in requested or href in resources or href in removed:
            raise CalDAVError("CalDAV 多资源响应的地址与请求不匹配。")
        response_status = _status_code(response.findtext(dav + "status", default=""))
        if response_status == 404:
            removed.add(href)
            continue
        if response_status and response_status != 200:
            raise CalDAVError(f"CalDAV 资源返回 HTTP {response_status}，未应用本次同步。")
        etag = ""
        calendar_data = ""
        for propstat in response.findall(dav + "propstat"):
            code = _status_code(propstat.findtext(dav + "status", default=""))
            prop = propstat.find(dav + "prop")
            if code == 200 and prop is not None:
                etag = etag or prop.findtext(dav + "getetag", default="")
                data_node = prop.find(cal + "calendar-data")
                if data_node is not None:
                    if list(data_node):
                        raise CalDAVError("CalDAV 日历数据格式无法安全解析。")
                    calendar_data = data_node.text or ""
            elif code not in {403, 404}:
                raise CalDAVError(f"CalDAV 资源属性返回 HTTP {code or '错误'}。")
        data_size = len(calendar_data.encode("utf-8"))
        total_data_bytes += data_size
        if not calendar_data.strip() or data_size > 2_000_000 or total_data_bytes > 2_000_000:
            raise CalDAVError("CalDAV 资源缺少日历数据或多资源内容超过 2 MB。")
        if len(etag) > 1_024 or any(ord(char) < 32 or ord(char) == 127 for char in etag):
            raise CalDAVError("CalDAV 服务器返回了无效的 ETag。")
        try:
            _calendar_name, todos = parse_ical_vtodos(calendar_data)
        except CalendarExchangeError as exc:
            if "使用了重复规则" not in str(exc):
                raise CalDAVError(str(exc)) from exc
            todos = []
            unsupported_error = str(exc)
        else:
            unsupported_error = ""
        if len(todos) > 1:
            raise CalDAVError("一个 CalDAV 资源包含多个 VTODO，未应用本次同步。")
        resource = {
            "href": href,
            "etag": etag,
            "calendarData": calendar_data,
            "todo": todos[0] if todos else None,
        }
        if unsupported_error:
            resource["unsupportedError"] = unsupported_error
        resources[href] = resource
    if set(resources) | removed != requested:
        raise CalDAVError("CalDAV 多资源响应缺少请求项，未应用本次同步。")
    return {"resources": list(resources.values()), "removedHrefs": sorted(removed)}


def _caldav_origin(parts) -> tuple[str, str, int | None]:
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold().rstrip(".")
    port = parts.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host, port


def resolve_caldav_resource_url(collection_url: str, href: object) -> str:
    if not isinstance(href, str) or not href.strip() or len(href) > 4_096:
        raise CalDAVError("CalDAV 服务器返回了无效的资源地址。")
    base, _host = normalize_caldav_url(collection_url)
    base_parts = urlsplit(base)
    base_for_join = base if base_parts.path.endswith("/") else base + "/"
    target = urljoin(base_for_join, href.strip())
    target_parts = urlsplit(target)
    try:
        if _caldav_origin(base_parts) != _caldav_origin(target_parts):
            raise CalDAVError("CalDAV 资源地址跳到了另一个服务器，已阻止发送登录信息。")
        if target_parts.username is not None or target_parts.password is not None:
            raise CalDAVError("CalDAV 资源地址包含账号信息，已拒绝访问。")
        if target_parts.query or target_parts.fragment:
            raise CalDAVError("CalDAV 资源地址不能包含查询参数或片段。")
        decoded_path = unquote(target_parts.path)
        decoded_collection = unquote(base_parts.path)
        if "\\" in decoded_path or any(ord(char) < 32 or ord(char) == 127 for char in decoded_path):
            raise CalDAVError("CalDAV 资源路径包含不允许的字符。")
        normalized_resource = posixpath.normpath(decoded_path)
        normalized_collection = posixpath.normpath(decoded_collection)
        prefix = normalized_collection.rstrip("/") + "/"
        if not normalized_resource.startswith(prefix) or normalized_resource == normalized_collection:
            raise CalDAVError("CalDAV 资源不属于当前日历集，已拒绝访问。")
        return urlunsplit(SplitResult(
            target_parts.scheme.casefold(), target_parts.netloc,
            target_parts.path, "", "",
        ))
    except CalDAVError:
        raise
    except ValueError as exc:
        raise CalDAVError("CalDAV 资源地址格式无效。") from exc


def parse_caldav_vtodo_report(payload: bytes, collection_url: str) -> list[dict[str, object]]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_CALENDAR_DATA_BYTES:
        raise CalDAVError("CalDAV 日历响应为空或超过 2 MB。")
    try:
        root = _parse_safe_xml(payload)
    except ElementTree.ParseError as exc:
        raise CalDAVError("CalDAV 待办响应无法解析。") from exc
    dav = f"{{{_DAV_NS}}}"
    cal = f"{{{_CALDAV_NS}}}"
    if root.tag != dav + "multistatus":
        raise CalDAVError("CalDAV 服务器没有返回 Multi-Status 响应。")
    result: list[dict[str, object]] = []
    seen_resources: set[str] = set()
    for response in root.findall(dav + "response"):
        href = response.findtext(dav + "href", default="")
        resource_url = resolve_caldav_resource_url(collection_url, href)
        if resource_url in seen_resources:
            raise CalDAVError("CalDAV 响应中有重复资源地址，未应用本次同步。")
        seen_resources.add(resource_url)
        response_status = response.findtext(dav + "status", default="")
        if response_status:
            match = re.search(r"\s(\d{3})\s", response_status)
            code = int(match.group(1)) if match else 0
            if code == 404:
                continue
            if code != 200:
                raise CalDAVError(f"CalDAV 日历资源返回 HTTP {code or '错误'}，未应用本次同步。")
        successful_props: list[ElementTree.Element] = []
        for propstat in response.findall(dav + "propstat"):
            status = propstat.findtext(dav + "status", default="")
            match = re.search(r"\s(\d{3})\s", status)
            code = int(match.group(1)) if match else 0
            if code == 200:
                prop = propstat.find(dav + "prop")
                if prop is not None:
                    successful_props.append(prop)
            elif code not in {404, 403}:
                raise CalDAVError(f"CalDAV 资源属性返回 HTTP {code or '错误'}，未应用本次同步。")
        etag = ""
        calendar_data = ""
        for prop in successful_props:
            etag = etag or prop.findtext(dav + "getetag", default="")
            data_node = prop.find(cal + "calendar-data")
            if data_node is not None:
                if list(data_node):
                    raise CalDAVError("CalDAV 日历数据格式无法安全解析。")
                calendar_data = data_node.text or ""
        if not calendar_data.strip():
            raise CalDAVError("CalDAV 响应缺少日历数据，未应用本次同步。")
        if len(calendar_data.encode("utf-8")) > _MAX_CALENDAR_DATA_BYTES:
            raise CalDAVError("CalDAV 单个日历资源超过 2 MB。")
        if len(etag) > 1_024 or any(ord(char) < 32 or ord(char) == 127 for char in etag):
            raise CalDAVError("CalDAV 服务器返回了无效的 ETag。")
        try:
            _calendar_name, todos = parse_ical_vtodos(calendar_data)
        except CalendarExchangeError as exc:
            if "使用了重复规则" not in str(exc):
                raise CalDAVError(str(exc)) from exc
            todos = []
            unsupported_error = str(exc)
        else:
            unsupported_error = ""
        if len(todos) > 1:
            raise CalDAVError("一个 CalDAV 资源包含多个 VTODO；本次同步已停止以避免错误绑定。")
        resource = {
            "href": resource_url,
            "etag": etag,
            "calendarData": calendar_data,
            "todo": todos[0] if todos else None,
        }
        if unsupported_error:
            resource["unsupportedError"] = unsupported_error
        result.append(resource)
        if len(result) > 500:
            raise CalDAVError("一次最多同步 500 个 CalDAV 日历资源。")
    return result


def update_vtodo_completion(
    calendar_data: object,
    uid: str,
    done: bool,
    now: datetime | None = None,
) -> str:
    if not isinstance(calendar_data, str) or len(calendar_data.encode("utf-8")) > _MAX_CALENDAR_DATA_BYTES:
        raise CalDAVError("CalDAV 日历数据无效或超过 2 MB。")
    try:
        _name, todos = parse_ical_vtodos(calendar_data)
    except CalendarExchangeError as exc:
        raise CalDAVError(str(exc)) from exc
    if len(todos) != 1 or todos[0]["uid"] != uid:
        raise CalDAVError("CalDAV 待办 UID 与资源不匹配，无法安全回写。")
    lines = _folded_lines(calendar_data.lstrip("\ufeff"))
    target_start = -1
    target_end = -1
    target_depth = 0
    matches: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        upper = line.upper()
        if upper == "BEGIN:VTODO" and target_depth == 0:
            target_start = index
            target_depth = 1
            continue
        if target_depth:
            if upper.startswith("BEGIN:"):
                target_depth += 1
            elif upper.startswith("END:"):
                target_depth -= 1
                if target_depth == 0:
                    target_end = index
                    props: dict[str, str] = {}
                    nested = 0
                    component_uid = ""
                    for prop_line in lines[target_start + 1:target_end]:
                        prop_upper = prop_line.upper()
                        if prop_upper.startswith("BEGIN:"):
                            nested += 1
                            continue
                        if prop_upper.startswith("END:") and nested:
                            nested -= 1
                            continue
                        if nested:
                            continue
                        try:
                            name, _params, value = _parse_content_line(prop_line)
                        except CalendarExchangeError:
                            continue
                        props[name] = value
                    component_uid = _unescape_text(props.get("UID", ""))
                    if component_uid == uid:
                        matches.append((target_start, target_end))
                    target_start = target_end = -1
    if len(matches) != 1:
        raise CalDAVError("CalDAV 待办组件无法唯一定位，未执行回写。")
    start, end = matches[0]
    component_lines = lines[start + 1:end]
    kept: list[str] = []
    sequence = 0
    nested = 0
    for line in component_lines:
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            nested += 1
            kept.append(line)
            continue
        if upper.startswith("END:") and nested:
            nested -= 1
            kept.append(line)
            continue
        if nested:
            kept.append(line)
            continue
        try:
            name, _params, value = _parse_content_line(line)
        except CalendarExchangeError:
            kept.append(line)
            continue
        if name == "SEQUENCE":
            try:
                sequence = max(sequence, int(value))
            except ValueError:
                raise CalDAVError("CalDAV VTODO 的 SEQUENCE 无效，拒绝回写。")
        if name in {"STATUS", "PERCENT-COMPLETE", "COMPLETED", "DTSTAMP", "LAST-MODIFIED", "SEQUENCE"}:
            continue
        kept.append(line)
    stamp_time = now or datetime.now(timezone.utc)
    if stamp_time.tzinfo is None:
        stamp_time = stamp_time.astimezone()
    stamp = stamp_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    completion = [f"STATUS:{'COMPLETED' if done else 'NEEDS-ACTION'}", f"PERCENT-COMPLETE:{100 if done else 0}"]
    if done:
        completion.append(f"COMPLETED:{stamp}")
    completion.extend((f"DTSTAMP:{stamp}", f"LAST-MODIFIED:{stamp}", f"SEQUENCE:{sequence + 1}"))
    updated = [*lines[:start + 1], *kept, *completion, *lines[end:]]
    result = "\r\n".join(piece for line in updated for piece in _fold_line(line)) + "\r\n"
    if len(result.encode("utf-8")) > _MAX_CALENDAR_DATA_BYTES:
        raise CalDAVError("回写后的 CalDAV 待办超过 2 MB。")
    return result


def parse_caldav_collection_probe(payload: bytes) -> dict[str, object]:
    if not isinstance(payload, bytes) or not payload or len(payload) > 512_000:
        raise CalDAVError("服务器返回的 CalDAV 信息为空或超过 512 KB。")
    try:
        root = _parse_safe_xml(payload)
    except ElementTree.ParseError as exc:
        raise CalDAVError("服务器的 CalDAV 响应无法解析。") from exc
    dav = f"{{{_DAV_NS}}}"
    cal = f"{{{_CALDAV_NS}}}"
    responses = [root] if root.tag == dav + "response" else root.findall(dav + "response")
    calendars: list[dict[str, object]] = []
    for response in responses[:100]:
        href = response.findtext(dav + "href", default="")
        for propstat in response.findall(dav + "propstat"):
            status = propstat.findtext(dav + "status", default="")
            if " 200 " not in f" {status} ":
                continue
            prop = propstat.find(dav + "prop")
            if prop is None:
                continue
            resource_type = prop.find(dav + "resourcetype")
            if resource_type is None or resource_type.find(cal + "calendar") is None:
                continue
            component_set = prop.find(cal + "supported-calendar-component-set")
            components = sorted({
                item.get("name", "").upper()
                for item in (component_set.findall(cal + "comp") if component_set is not None else [])
                if item.get("name", "").upper() in {"VEVENT", "VTODO"}
            })
            name = prop.findtext(dav + "displayname", default="").strip()
            calendars.append({
                "href": href[:2_048],
                "name": name[:160],
                "components": components,
            })
    if not calendars:
        raise CalDAVError("该地址没有返回 CalDAV 日历集；请填写日历集专属地址。")
    return {"calendars": calendars}
