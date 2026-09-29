"""WebDAV planner-sync validation and the legacy AES-GCM snapshot format."""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from .database import get_app_setting, set_app_setting
from .windows_secrets import protect_text, unprotect_text


FORMAT = "wanxiang-encrypted-backup"
VERSION = 1
KDF = "PBKDF2-HMAC-SHA256"
ITERATIONS = 600_000
CIPHER = "AES-256-GCM"
MAX_URL_BYTES = 4_096
MAX_USERNAME_BYTES = 512
MAX_PASSWORD_BYTES = 1_024
MAX_PASSPHRASE_BYTES = 256
MAX_PLAINTEXT_BYTES = 50 * 1024 * 1024
MAX_REMOTE_BYTES = 70 * 1024 * 1024
ACCOUNT_SETTING_KEY = "webdavPlannerSyncAccount"
DEVICE_SETTING_KEY = "webdavPlannerSyncDeviceId"
SECRET_PURPOSE = b"FLUKE webdav planner sync settings v1"
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


class WebDavPlannerError(ValueError):
    """A safe, user-facing WebDAV planner-sync validation error."""


def _encoded_length(value: str, label: str) -> int:
    try:
        return len(value.encode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise WebDavPlannerError(f"{label}编码无效。") from exc


def _loopback_host(hostname: str) -> bool:
    host = hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def normalize_webdav_backup_url(
    value: object, *, allow_loopback_http: bool = False
) -> tuple[str, str]:
    if not isinstance(value, str):
        raise WebDavPlannerError("WebDAV 文件地址必须是文本。")
    source = value.strip()
    if not source or _encoded_length(source, "WebDAV 地址") > MAX_URL_BYTES:
        raise WebDavPlannerError("WebDAV 文件地址不能为空，且不能超过 4096 字节。")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in source):
        raise WebDavPlannerError("WebDAV 文件地址不能包含空白或控制字符。")
    try:
        parts = urlsplit(source)
        scheme = parts.scheme.casefold()
        hostname = parts.hostname
        if scheme not in {"http", "https"} or not hostname:
            raise WebDavPlannerError("WebDAV 文件地址须是有效的 HTTPS 地址。")
        if parts.username is not None or parts.password is not None:
            raise WebDavPlannerError("请在账号栏填写登录信息，地址中不要包含账号或密码。")
        if parts.fragment:
            raise WebDavPlannerError("WebDAV 文件地址不能包含片段。")
        port = parts.port
        if scheme == "http" and not (allow_loopback_http and _loopback_host(hostname)):
            raise WebDavPlannerError("远程 WebDAV 地址必须使用 HTTPS。")
        host_ascii = hostname.encode("idna").decode("ascii").casefold()
        if ":" in host_ascii and not host_ascii.startswith("["):
            host_ascii = f"[{host_ascii}]"
        netloc = f"{host_ascii}:{port}" if port is not None else host_ascii
        path = parts.path or "/"
        normalized = urlunsplit(SplitResult(scheme, netloc, path, parts.query, ""))
    except WebDavPlannerError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise WebDavPlannerError("WebDAV 文件地址格式无效。") from exc
    if path == "/" or path.endswith("/"):
        raise WebDavPlannerError("请填写 WebDAV 上具体的 .wxbackup 文件路径。")
    if not path.casefold().endswith(".wxbackup"):
        raise WebDavPlannerError("完整备份文件名须以 .wxbackup 结尾。")
    if _encoded_length(normalized, "WebDAV 地址") > MAX_URL_BYTES:
        raise WebDavPlannerError("WebDAV 文件地址不能超过 4096 字节。")
    return normalized, hostname.casefold()


def planner_snapshot_url(backup_url: str) -> str:
    parts = urlsplit(backup_url)
    filename = parts.path.rsplit("/", 1)[-1]
    if not filename.casefold().endswith(".wxbackup"):
        raise WebDavPlannerError("WebDAV 完整备份文件名须以 .wxbackup 结尾。")
    sidecar = filename[:-len(".wxbackup")] + ".planner-sync.wxbackup"
    path = parts.path[:len(parts.path) - len(filename)] + sidecar
    return urlunsplit(parts._replace(path=path, fragment=""))


def validate_credentials(
    username: object, password: object, passphrase: object
) -> tuple[str, str, str]:
    if not isinstance(username, str) or not isinstance(password, str):
        raise WebDavPlannerError("请输入有效的 WebDAV 用户名和密码。")
    if (
        not username
        or not password
        or _encoded_length(username, "用户名") > MAX_USERNAME_BYTES
        or _encoded_length(password, "密码") > MAX_PASSWORD_BYTES
        or any(ord(char) < 32 or ord(char) == 127 or char == ":" for char in username)
        or any(ord(char) < 32 or ord(char) == 127 for char in password)
    ):
        raise WebDavPlannerError("请输入有效的 WebDAV 用户名和密码；用户名不能包含冒号。")
    if not isinstance(passphrase, str) or not 12 <= len(passphrase) or _encoded_length(
        passphrase, "日程同步密码"
    ) > MAX_PASSPHRASE_BYTES:
        raise WebDavPlannerError("日程同步密码须至少 12 个字符，且不超过 256 字节。")
    if any(ord(char) < 32 or ord(char) == 127 for char in passphrase):
        raise WebDavPlannerError("日程同步密码不能包含控制字符。")
    return username, password, passphrase


def is_strong_etag(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 1_024
        and re.fullmatch(r'"[\x21\x23-\x7e]*"', value) is not None
    )


def create_protected_account(
    url: object,
    username: object,
    password: object,
    passphrase: object,
    *,
    protector=protect_text,
    allow_loopback_http: bool = False,
) -> dict[str, object]:
    normalized_url, host = normalize_webdav_backup_url(
        url, allow_loopback_http=allow_loopback_http
    )
    username_value, password_value, passphrase_value = validate_credentials(
        username, password, passphrase
    )
    try:
        secret_json = json.dumps(
            {
                "url": normalized_url,
                "username": username_value,
                "password": password_value,
                "passphrase": passphrase_value,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        encrypted = protector(secret_json, purpose=SECRET_PURPOSE)
    except (TypeError, ValueError) as exc:
        raise WebDavPlannerError("无法加密保存 WebDAV 设置。") from exc
    if not isinstance(encrypted, str) or not encrypted or len(encrypted) > 65_536:
        raise WebDavPlannerError("无法加密保存 WebDAV 设置。")
    return {
        "format": 1,
        "id": str(uuid4()),
        "host": host,
        "fileName": urlsplit(normalized_url).path.rsplit("/", 1)[-1][:180],
        "encryptedSecret": encrypted,
        "remoteExists": False,
        "etag": "",
        "lastCheckedAt": "",
        "lastSyncAt": "",
        "lastError": "",
        "plannerRemoteExists": False,
        "plannerEtag": "",
        "lastPlannerSyncAt": "",
        "lastPlannerError": "",
    }


def reveal_account_secret(
    account: object,
    *,
    unprotector=unprotect_text,
    allow_loopback_http: bool = False,
) -> dict[str, str]:
    if not isinstance(account, dict):
        raise WebDavPlannerError("WebDAV 日程同步尚未设置。")
    encrypted = account.get("encryptedSecret")
    try:
        raw = unprotector(encrypted, purpose=SECRET_PURPOSE)
        value = json.loads(raw)
        url, host = normalize_webdav_backup_url(
            value.get("url") if isinstance(value, dict) else None,
            allow_loopback_http=allow_loopback_http,
        )
        username, password, passphrase = validate_credentials(
            value.get("username"), value.get("password"), value.get("passphrase")
        )
    except (TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, WebDavPlannerError):
            raise
        raise WebDavPlannerError("当前 Windows 用户无法解密 WebDAV 设置，请重新设置账号。") from exc
    if host != account.get("host"):
        raise WebDavPlannerError("保存的 WebDAV 主机信息不匹配。")
    return {"url": url, "host": host, "username": username, "password": password, "passphrase": passphrase}


def load_account(database_path: str | Path) -> dict[str, object] | None:
    value = get_app_setting(database_path, ACCOUNT_SETTING_KEY)
    if not isinstance(value, dict) or value.get("format") != 1:
        return None
    return dict(value)


def save_account(database_path: str | Path, account: dict[str, object]) -> None:
    set_app_setting(database_path, ACCOUNT_SETTING_KEY, account)


def ensure_device_id(database_path: str | Path) -> str:
    value = get_app_setting(database_path, DEVICE_SETTING_KEY)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9-]{8,80}", value):
        return value
    value = str(uuid4())
    set_app_setting(database_path, DEVICE_SETTING_KEY, value)
    return value


def encrypt_snapshot(snapshot: object, passphrase: str) -> str:
    if not isinstance(snapshot, dict):
        raise WebDavPlannerError("日程快照必须是对象。")
    try:
        plaintext = json.dumps(
            snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8", errors="strict")
    except (UnicodeError, TypeError, ValueError) as exc:
        raise WebDavPlannerError("日程快照无法编码。") from exc
    if not plaintext or len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise WebDavPlannerError("日程快照为空或超过 50 MB。")
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, ITERATIONS, 32)
    encrypted = AESGCM(key).encrypt(iv, plaintext, None)
    envelope = {
        "format": FORMAT,
        "version": VERSION,
        "kdf": KDF,
        "iterations": ITERATIONS,
        "cipher": CIPHER,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(encrypted).decode("ascii"),
    }
    content = json.dumps(envelope, separators=(",", ":"))
    if len(content.encode("utf-8")) > MAX_REMOTE_BYTES:
        raise WebDavPlannerError("加密日程快照文件超过 70 MB。")
    return content


def decrypt_snapshot(content: bytes | str, passphrase: str) -> dict[str, object]:
    try:
        raw = content.encode("utf-8", errors="strict") if isinstance(content, str) else bytes(content)
    except (UnicodeError, TypeError, ValueError) as exc:
        raise WebDavPlannerError("云端日程快照格式无效。") from exc
    if not raw or len(raw) > MAX_REMOTE_BYTES:
        raise WebDavPlannerError("云端日程快照为空或超过 70 MB。")
    try:
        envelope = json.loads(raw.decode("utf-8", errors="strict"))
        if not isinstance(envelope, dict) or (
            envelope.get("format") != FORMAT
            or envelope.get("version") != VERSION
            or envelope.get("kdf") != KDF
            or envelope.get("iterations") != ITERATIONS
            or envelope.get("cipher") != CIPHER
        ):
            raise ValueError("unsupported envelope")
        encoded = [envelope.get(key) for key in ("salt", "iv", "ciphertext")]
        if any(not isinstance(item, str) or not _BASE64.fullmatch(item) for item in encoded):
            raise ValueError("invalid base64")
        salt, iv, ciphertext = (base64.b64decode(item, validate=True) for item in encoded)
        if len(salt) != 16 or len(iv) != 12 or len(ciphertext) < 16:
            raise ValueError("invalid sizes")
        key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, ITERATIONS, 32)
        plaintext = AESGCM(key).decrypt(iv, ciphertext, None)
        if len(plaintext) > MAX_PLAINTEXT_BYTES:
            raise ValueError("oversized plaintext")
        decoded = json.loads(plaintext.decode("utf-8", errors="strict"))
        if not isinstance(decoded, dict):
            raise ValueError("snapshot is not an object")
        return decoded
    except (InvalidTag, binascii.Error, UnicodeError, TypeError, ValueError) as exc:
        raise WebDavPlannerError("无法解密云端日程快照，请检查同步密码或快照完整性。") from exc
