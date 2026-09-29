from __future__ import annotations

import json
import base64
from pathlib import Path
import tempfile
import unittest

from wanxiang.database import get_app_setting
from wanxiang.webdav_planner import (
    ACCOUNT_SETTING_KEY,
    DEVICE_SETTING_KEY,
    FORMAT,
    WebDavPlannerError,
    create_protected_account,
    decrypt_snapshot,
    encrypt_snapshot,
    ensure_device_id,
    is_strong_etag,
    load_account,
    normalize_webdav_backup_url,
    planner_snapshot_url,
    reveal_account_secret,
    save_account,
)


PASSWORD = "separate sync password"
SNAPSHOT = {
    "format": "wanxiang-planner-sync",
    "version": 1,
    "deviceId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "vector": {},
    "tasks": [],
    "tombstones": [],
    "conflicts": [],
}


def identity_protector(value: str, *, purpose: bytes) -> str:
    return base64.urlsafe_b64encode(purpose + b"\0" + value.encode("utf-8")).decode("ascii")


def identity_unprotector(value: object, *, purpose: bytes) -> str:
    if not isinstance(value, str):
        raise ValueError("wrong purpose")
    decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    prefix = purpose + b"\0"
    if not decoded.startswith(prefix):
        raise ValueError("wrong purpose")
    return decoded[len(prefix):].decode("utf-8")


class WebDavPlannerTests(unittest.TestCase):
    def test_webdav_url_and_sidecar_retain_directory_and_query(self) -> None:
        url, host = normalize_webdav_backup_url(
            "https://cloud.example.test/dav/life.wxbackup?user=42"
        )
        self.assertEqual(url, "https://cloud.example.test/dav/life.wxbackup?user=42")
        self.assertEqual(host, "cloud.example.test")
        self.assertEqual(
            planner_snapshot_url(url),
            "https://cloud.example.test/dav/life.planner-sync.wxbackup?user=42",
        )
        loopback, _ = normalize_webdav_backup_url(
            "http://127.0.0.1:8080/dav/life.wxbackup", allow_loopback_http=True
        )
        self.assertTrue(loopback.startswith("http://127.0.0.1:8080/"))

    def test_webdav_url_rejects_non_tls_remote_and_bad_paths(self) -> None:
        for url in (
            "http://cloud.example.test/dav/life.wxbackup",
            "https://user:pass@cloud.example.test/dav/life.wxbackup",
            "https://cloud.example.test/dav/",
            "https://cloud.example.test/dav/life.json",
            "https://cloud.example.test/dav/life.wxbackup#part",
        ):
            with self.subTest(url=url), self.assertRaises(WebDavPlannerError):
                normalize_webdav_backup_url(url, allow_loopback_http=True)

    def test_sync_snapshot_uses_legacy_webcrypto_aes_gcm_envelope(self) -> None:
        content = encrypt_snapshot(SNAPSHOT, PASSWORD)
        envelope = json.loads(content)
        self.assertEqual(envelope["format"], "wanxiang-encrypted-backup")
        self.assertEqual(envelope["version"], 1)
        self.assertEqual(envelope["kdf"], "PBKDF2-HMAC-SHA256")
        self.assertEqual(envelope["iterations"], 600_000)
        self.assertEqual(envelope["cipher"], "AES-256-GCM")
        self.assertEqual(decrypt_snapshot(content, PASSWORD), SNAPSHOT)
        with self.assertRaisesRegex(WebDavPlannerError, "无法解密"):
            decrypt_snapshot(content, "a different password")

    def test_tampered_or_unbounded_remote_envelope_is_rejected(self) -> None:
        envelope = json.loads(encrypt_snapshot(SNAPSHOT, PASSWORD))
        envelope["ciphertext"] = "A" + envelope["ciphertext"][1:]
        with self.assertRaises(WebDavPlannerError):
            decrypt_snapshot(json.dumps(envelope), PASSWORD)
        with self.assertRaises(WebDavPlannerError):
            decrypt_snapshot("x" * (70 * 1024 * 1024 + 1), PASSWORD)

    def test_protected_settings_keep_all_secrets_outside_plain_app_setting(self) -> None:
        account = create_protected_account(
            "https://cloud.example.test/dav/life.wxbackup",
            "user-name",
            "user-password",
            PASSWORD,
            protector=identity_protector,
        )
        secret = reveal_account_secret(account, unprotector=identity_unprotector)
        self.assertEqual(secret["username"], "user-name")
        self.assertEqual(secret["password"], "user-password")
        self.assertEqual(secret["passphrase"], PASSWORD)
        self.assertNotIn("user-password", json.dumps(account))
        self.assertNotIn(PASSWORD, json.dumps(account))
        self.assertEqual(is_strong_etag('"v1"'), True)
        self.assertEqual(is_strong_etag('W/"v1"'), False)

    def test_account_and_new_device_id_persist_in_local_sqlite_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sync.sqlite3"
            account = create_protected_account(
                "https://cloud.example.test/dav/life.wxbackup",
                "user-name",
                "user-password",
                PASSWORD,
                protector=identity_protector,
            )
            save_account(database, account)
            self.assertEqual(load_account(database), account)
            self.assertEqual(get_app_setting(database, ACCOUNT_SETTING_KEY), account)
            first = ensure_device_id(database)
            self.assertTrue(8 <= len(first) <= 80)
            self.assertEqual(ensure_device_id(database), first)
            self.assertEqual(get_app_setting(database, DEVICE_SETTING_KEY), first)


if __name__ == "__main__":
    unittest.main()
