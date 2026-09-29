"""Asynchronous Qt WebDAV transport for the legacy planner-sync protocol."""

from __future__ import annotations

from base64 import b64encode
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .database import set_app_setting
from .planner import PlannerRepository, PlannerRepositoryError
from .planner_sync import (
    FORMAT as SYNC_FORMAT,
    VERSION as SYNC_VERSION,
    merge_snapshots,
    normalize_snapshot,
    resolve_conflict,
    snapshot_from_state,
    stamp_local_changes,
)
from .webdav_planner import (
    ACCOUNT_SETTING_KEY,
    MAX_REMOTE_BYTES,
    WebDavPlannerError,
    create_protected_account,
    decrypt_snapshot,
    encrypt_snapshot,
    ensure_device_id,
    is_strong_etag,
    load_account,
    planner_snapshot_url,
    reveal_account_secret,
    save_account,
)


_BASIC_AUTH = b"Basic "
_AUTO_RETRY_MS = 60_000


class WebDavPlannerSyncBridge(QObject):
    """Keeps WebDAV credentials local and syncs only planner protocol snapshots."""

    changed = Signal()

    def __init__(
        self,
        database_path: Path,
        repository: PlannerRepository,
        network: QNetworkAccessManager,
        parent: QObject | None = None,
        *,
        allow_loopback_http: bool = False,
        start_automatically: bool = True,
    ) -> None:
        super().__init__(parent)
        self.database_path = Path(database_path)
        self.repository = repository
        self.network = network
        self.allow_loopback_http = allow_loopback_http
        self.account = load_account(self.database_path)
        self.device_id = ensure_device_id(self.database_path)
        self._job: dict[str, Any] | None = None
        self._buffer_size = 0
        self._applying_remote = False
        self._revision = 0
        self._baseline = repository.webdav_sync_state()
        self._status = "idle" if self.account else "unconfigured"
        self._message = "尚未设置 WebDAV 日程同步。" if not self.account else ""
        self._sync_again = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.sync_now)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.sync_now)
        if self.account and start_automatically:
            QTimer.singleShot(900, self.sync_now)

    def state(self) -> dict[str, object]:
        account = self.account or {}
        sync_state = self.repository.webdav_sync_state()
        conflicts = sync_state.get("settings", {}).get("webdavPlannerConflicts", [])
        remote_exists = account.get("plannerRemoteExists") is True
        etag = account.get("plannerEtag", "")
        return {
            "configured": bool(self.account),
            "enabled": bool(self.account),
            "busy": self._job is not None,
            "status": self._status,
            "message": self._message,
            "error": self._status == "error",
            "host": account.get("host", ""),
            "fileName": account.get("fileName", ""),
            "plannerRemoteExists": remote_exists,
            "plannerCanSafelyReplace": not remote_exists or is_strong_etag(etag),
            "lastSyncAt": account.get("lastPlannerSyncAt", ""),
            "conflictCount": len(conflicts) if isinstance(conflicts, list) else 0,
        }

    def conflicts(self) -> list[dict[str, Any]]:
        value = self.repository.webdav_sync_state().get("settings", {}).get(
            "webdavPlannerConflicts", []
        )
        return deepcopy(value) if isinstance(value, list) else []

    def observe_local_changes(self) -> bool:
        current = self.repository.webdav_sync_state()
        if self._applying_remote or self._baseline is None:
            self._baseline = current
            return False
        if not stamp_local_changes(self._baseline, current, self.device_id):
            self._baseline = current
            return False
        try:
            self.repository.save_webdav_sync_state(current, self.device_id)
            self._baseline = self.repository.webdav_sync_state()
            self._revision += 1
            if self.account:
                self._status = "pending"
                self._message = "有本机日程变更等待同步。"
                self._debounce.start(900)
            return True
        except (PlannerRepositoryError, OSError, RuntimeError, ValueError) as exc:
            self._status = "error"
            self._message = str(exc) or "本机日程同步标记未能保存。"
            return False

    def configure(
        self, url: str, username: str, password: str, passphrase: str
    ) -> dict[str, object]:
        self._cancel_active()
        self._retry.stop()
        try:
            account = create_protected_account(
                url,
                username,
                password,
                passphrase,
                allow_loopback_http=self.allow_loopback_http,
            )
            save_account(self.database_path, account)
        except (WebDavPlannerError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "WebDAV 设置未保存。"}
        self.account = account
        self._status = "syncing"
        self._message = "设置已在本机加密保存，正在读取云端日程。"
        self._begin_get(0, self._current_secret(), self._revision)
        self.changed.emit()
        return {"ok": True, "pending": True}

    def clear(self) -> dict[str, object]:
        self._cancel_active()
        self._debounce.stop()
        self._retry.stop()
        try:
            set_app_setting(self.database_path, ACCOUNT_SETTING_KEY, None)
        except (OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "WebDAV 设置未能移除。"}
        self.account = None
        self._status = "unconfigured"
        self._message = "WebDAV 设置已移除；本机日程与同步历史仍保留。"
        self.changed.emit()
        return {"ok": True}

    def sync_now(self) -> dict[str, object]:
        if not self.account:
            return {"ok": False, "error": "请先设置 WebDAV 日程同步。"}
        if self._job is not None:
            self._sync_again = True
            return {"ok": True, "pending": True}
        self._retry.stop()
        self._status = "syncing"
        self._message = "正在读取并合并云端日程。"
        self._begin_get(0, self._current_secret(), self._revision)
        self.changed.emit()
        return {"ok": True, "pending": True}

    def resolve(self, task_id: str, variant_index: Any, keep_both: bool) -> dict[str, object]:
        state = self.repository.webdav_sync_state()
        if not resolve_conflict(state, task_id, variant_index, self.device_id, keep_both):
            return {"ok": False, "error": "没有找到这项日程冲突，列表已刷新。"}
        try:
            self.repository.save_webdav_sync_state(state, self.device_id)
        except (PlannerRepositoryError, OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "冲突选择未能保存。"}
        self._baseline = self.repository.webdav_sync_state()
        self._revision += 1
        self._status = "pending"
        self._message = "冲突选择已保存，准备同步。"
        self._debounce.start(150)
        self.changed.emit()
        return {"ok": True}

    def _current_secret(self) -> dict[str, str]:
        return reveal_account_secret(
            self.account,
            allow_loopback_http=self.allow_loopback_http,
        )

    def _begin_get(
        self, attempt: int, secret: dict[str, str], starting_revision: int
    ) -> None:
        if not self.account:
            return
        try:
            url = planner_snapshot_url(secret["url"])
            self._send({
                "stage": "get",
                "attempt": attempt,
                "secret": secret,
                "url": url,
                "startingRevision": starting_revision,
                "buffer": bytearray(),
                "oversized": False,
            }, "GET")
        except (WebDavPlannerError, RuntimeError, TypeError, ValueError) as exc:
            self._fail(str(exc) or "无法准备 WebDAV 日程读取。")

    def _send(
        self,
        job: dict[str, Any],
        method: str,
        *,
        body: str = "",
        etag: str = "",
        remote_exists: bool = False,
    ) -> None:
        url = QUrl(job["url"])
        if not url.isValid() or not url.scheme() or not url.host():
            raise WebDavPlannerError("WebDAV 地址无法转换为网络请求。")
        request = QNetworkRequest(url)
        request.setTransferTimeout(60_000)
        request.setRawHeader(QByteArray(b"Authorization"), QByteArray(
            _BASIC_AUTH + b64encode(
                f"{job['secret']['username']}:{job['secret']['password']}".encode("utf-8")
            )
        ))
        request.setRawHeader(QByteArray(b"Accept"), QByteArray(b"application/json, */*;q=0.1"))
        request.setRawHeader(QByteArray(b"User-Agent"), QByteArray(b"FLUKE Planner Sync/1.0"))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        if method == "PUT":
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader,
                "application/json; charset=utf-8",
            )
            if remote_exists:
                if not is_strong_etag(etag):
                    raise WebDavPlannerError(
                        "云端日程没有强版本标记，无法安全覆盖；两端数据均已保留。"
                    )
                request.setRawHeader(QByteArray(b"If-Match"), QByteArray(etag.encode("ascii")))
            else:
                request.setRawHeader(QByteArray(b"If-None-Match"), QByteArray(b"*"))
        if method == "GET":
            reply = self.network.get(request)
        else:
            reply = self.network.sendCustomRequest(
                request, QByteArray(method.encode("ascii")), QByteArray(body.encode("utf-8"))
            )
        job["reply"] = reply
        job["method"] = method
        job["buffer"] = bytearray()
        self._job = job

        def receive() -> None:
            if self._job is not job:
                return
            chunk = bytes(reply.readAll())
            buffer = job["buffer"]
            if len(buffer) + len(chunk) > MAX_REMOTE_BYTES:
                job["oversized"] = True
                reply.abort()
                return
            buffer.extend(chunk)

        reply.readyRead.connect(receive)
        reply.finished.connect(lambda job=job, reply=reply: self._finished(job, reply))

    @staticmethod
    def _strong_etag(reply: QNetworkReply) -> str:
        raw = bytes(reply.rawHeader("ETag"))
        if len(raw) > 1_024 or any(byte < 32 or byte == 127 for byte in raw):
            return ""
        try:
            value = raw.decode("ascii").strip()
        except UnicodeError:
            return ""
        return value if is_strong_etag(value) else ""

    def _finished(self, job: dict[str, Any], reply: QNetworkReply) -> None:
        if self._job is not job:
            reply.deleteLater()
            return
        trailing = bytes(reply.readAll())
        buffer: bytearray = job["buffer"]
        if len(buffer) + len(trailing) > MAX_REMOTE_BYTES:
            job["oversized"] = True
        elif trailing:
            buffer.extend(trailing)
        self._job = None
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status_value) if status_value is not None else 0
        etag = self._strong_etag(reply)
        network_error = reply.error()
        reply.deleteLater()
        try:
            if job.get("oversized"):
                raise WebDavPlannerError("云端日程快照超过 70 MB，已停止读取。")
            if 300 <= status < 400:
                raise WebDavPlannerError("WebDAV 返回了重定向；请填写最终的 HTTPS 文件地址。")
            if job["stage"] == "get":
                self._handle_get(job, status, etag, bytes(buffer), network_error)
            else:
                self._handle_put(job, status, etag, network_error)
        except (WebDavPlannerError, PlannerRepositoryError, OSError, RuntimeError,
                TypeError, UnicodeError, ValueError) as exc:
            self._fail(str(exc) or "WebDAV 日程同步失败；本机数据已保留。")

    def _handle_get(
        self,
        job: dict[str, Any],
        status: int,
        etag: str,
        body: bytes,
        network_error: QNetworkReply.NetworkError,
    ) -> None:
        if status not in (200, 404, 410) or (status == 200 and network_error != QNetworkReply.NetworkError.NoError):
            raise WebDavPlannerError(self._http_error(status))
        remote_exists = status == 200
        if remote_exists:
            try:
                decoded = decrypt_snapshot(body, job["secret"]["passphrase"])
            except WebDavPlannerError as exc:
                raise WebDavPlannerError(
                    "无法解密云端日程；请确认新旧设备使用相同的同步密码。"
                ) from exc
            remote = normalize_snapshot(decoded)
            if remote is None:
                raise WebDavPlannerError("云端文件不是有效的万象来信日程快照，未覆盖任何数据。")
        else:
            remote = {
                "format": SYNC_FORMAT,
                "version": SYNC_VERSION,
                "deviceId": self.device_id,
                "vector": {},
                "tasks": [],
                "tombstones": [],
                "conflicts": [],
            }
        account = {
            **(self.account or {}),
            "plannerRemoteExists": remote_exists,
            "plannerEtag": etag if remote_exists else "",
            "lastPlannerError": "",
        }
        self._save_account(account)
        local = self._local_snapshot()
        merged = merge_snapshots(local, remote)
        if not self._same_content(merged, remote):
            if remote_exists and not is_strong_etag(etag):
                raise WebDavPlannerError(
                    "云端日程没有强版本标记，无法安全覆盖；两端数据均已保留。"
                )
            encrypted = encrypt_snapshot(merged, job["secret"]["passphrase"])
            job["stage"] = "put"
            job["merged"] = merged
            job["remoteExists"] = remote_exists
            job["etag"] = etag
            self._send(
                job,
                "PUT",
                body=encrypted,
                etag=etag,
                remote_exists=remote_exists,
            )
            return
        self._finish_success(merged, int(job["startingRevision"]))

    def _handle_put(
        self,
        job: dict[str, Any],
        status: int,
        etag: str,
        network_error: QNetworkReply.NetworkError,
    ) -> None:
        if status == 412:
            attempt = int(job.get("attempt", 0))
            if attempt >= 4:
                raise WebDavPlannerError("云端连续发生版本变化；本机内容未覆盖，稍后可重试。")
            self._begin_get(attempt + 1, job["secret"], int(job["startingRevision"]))
            return
        if status not in (200, 201, 204) or network_error != QNetworkReply.NetworkError.NoError:
            raise WebDavPlannerError(self._http_error(status))
        account = {
            **(self.account or {}),
            "plannerRemoteExists": True,
            "plannerEtag": etag,
            "lastPlannerError": "",
        }
        self._save_account(account)
        self._finish_success(job["merged"], int(job["startingRevision"]))

    def _local_snapshot(self) -> dict[str, Any]:
        snapshot = snapshot_from_state(self.repository.webdav_sync_state(), self.device_id)
        normalized = normalize_snapshot(snapshot)
        if normalized is None:
            raise WebDavPlannerError("本机日程无法生成有效的同步快照。")
        return normalized

    @staticmethod
    def _same_content(left: object, right: object) -> bool:
        a = merge_snapshots(left)
        b = merge_snapshots(right)
        a["deviceId"] = ""
        b["deviceId"] = ""
        return json.dumps(a, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
            b, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def _finish_success(self, merged: dict[str, Any], starting_revision: int) -> None:
        latest = self._local_snapshot()
        latest_merged = merge_snapshots(merged, latest)
        needs_apply = not self._same_content(latest, latest_merged)
        if needs_apply:
            self._applying_remote = True
            try:
                self.repository.apply_webdav_sync_snapshot(latest_merged)
                self._baseline = self.repository.webdav_sync_state()
            finally:
                self._applying_remote = False
        account = {
            **(self.account or {}),
            "lastPlannerSyncAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "lastPlannerError": "",
        }
        self._save_account(account)
        conflict_count = len(latest_merged.get("conflicts", []))
        self._status = "conflict" if conflict_count else "ok"
        self._message = (
            f"日程已合并，有 {conflict_count} 项并发修改待处理。"
            if conflict_count else "跨设备日程已同步。"
        )
        self.changed.emit()
        if self._sync_again or self._revision != starting_revision:
            self._sync_again = False
            self._debounce.start(250)

    def _save_account(self, account: dict[str, Any]) -> None:
        save_account(self.database_path, account)
        self.account = account

    def _http_error(self, status: int) -> str:
        if status in (401, 403):
            return "WebDAV 拒绝登录或没有文件访问权限，请检查账号与目录权限。"
        if status:
            return f"WebDAV 服务器返回 HTTP {status}；本机日程已保留。"
        return "无法连接 WebDAV 服务器，请检查地址和网络；本机日程已保留。"

    def _fail(self, message: str) -> None:
        self._job = None
        self._status = "error"
        self._message = message[:300]
        if self.account:
            account = {**self.account, "lastPlannerError": self._message}
            try:
                self._save_account(account)
            except (OSError, RuntimeError, ValueError):
                pass
            self._retry.start(_AUTO_RETRY_MS)
        self.changed.emit()

    def _cancel_active(self) -> None:
        job = self._job
        self._job = None
        if job is not None:
            reply = job.get("reply")
            if isinstance(reply, QNetworkReply):
                reply.abort()
