from __future__ import annotations

from datetime import date
import base64
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage

from wanxiang.media import (
    MAX_COVER_SOURCE_BYTES,
    MediaRepository,
    MediaRepositoryError,
    prepare_cover_file,
)


def _item(item_id: str, name: str, day: str, status: str, kind: str = "电影", rating: int = 0, **extra: object) -> dict[str, object]:
    return {
        "id": item_id,
        "name": name,
        "type": kind,
        "status": status,
        "rating": rating,
        "review": "",
        "date": day,
        "cover": "",
        "sample": False,
        **extra,
    }


def _source(
    items: list[dict[str, object]] | None = None,
    settings: dict[str, object] | None = None,
    draft: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "documents": {
            "richangji-state-v1": {
                "version": 2,
                "records": [],
                "habits": [],
                "mediaItems": items or [],
                "settings": settings or {},
                "drafts": {"mediaForm": draft or {}},
                "futureStateField": {"keep": True},
            }
        },
        "raw_values": {"richangji-state-v1": "original raw string"},
    }


class MediaRepositoryTests(unittest.TestCase):
    def test_import_keeps_unknown_fields_remote_id_and_cover_original_immutable(self) -> None:
        original = _item(
            "legacy-1", "旧电影", "2026-09-26", "看完", rating=4,
            remoteId="remote-73", futureItemField={"keep": [1, "x"]},
            cover="data:image/webp;base64,old-cover-bytes",
        )
        source = _source([original], {"mediaView": "list", "futureMediaSetting": {"keep": 8}})
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "media.sqlite3"
            repository = MediaRepository(database, source, today_provider=lambda: date(2026, 9, 27))

            self.assertEqual(repository.legacy_items(), [original])
            effective = repository.items()[0]
            self.assertEqual(effective["remoteId"], "remote-73")
            self.assertEqual(effective["futureItemField"], {"keep": [1, "x"]})
            self.assertEqual(effective["cover"], "data:image/webp;base64,old-cover-bytes")
            self.assertEqual(repository.settings()["futureMediaSetting"], {"keep": 8})
            self.assertEqual(repository.settings()["mediaView"], "list")

            repository.set_view("wall")
            reopened = MediaRepository(database, today_provider=lambda: date(2026, 9, 27))
            self.assertEqual(reopened.items()[0], effective)
            self.assertEqual(reopened.settings()["mediaView"], "wall")
            self.assertEqual(reopened.legacy_items(), [original])

    def test_filters_and_statistics_match_legacy_scope(self) -> None:
        rows = [
            _item("f1", "先看完", "2026-02-10", "看完", "书", 5),
            _item("f2", "后看完", "2026-05-01", "看完", "电影", 3),
            _item("f3", "没评分", "2026-06-01", "看完", "电影", 0),
            _item("f4", "去年看完", "2025-12-31", "看完", "番", 4),
            _item("q1", "现在在看", "2026-09-26", "在看", "剧", 0),
            _item("q2", "还想看", "2026-09-25", "想看", "电影", 0),
            _item("q3", "弃了", "2026-09-24", "弃了", "书", 0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = MediaRepository(
                Path(directory) / "media.sqlite3", _source(rows),
                today_provider=lambda: date(2026, 9, 27),
            )
            summary = repository.summary()
            self.assertEqual(summary["yearFinishedCount"], 3)
            self.assertEqual(summary["yearAverageRating"], 4.0)
            self.assertEqual(summary["favoriteType"], "电影")
            self.assertEqual(summary["ratingDistribution"], {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1})
            self.assertEqual(summary["inProgressCount"], 1)
            self.assertEqual([item["id"] for item in summary["queue"]], ["q1", "q2"])

            repository.set_status_filter("看完")
            repository.set_rating_filter(4)
            self.assertEqual([item["id"] for item in repository.filtered_items()], ["f1", "f4"])
            repository.set_status_filter("all")
            repository.set_rating_filter(0)
            self.assertEqual(len(repository.filtered_items()), 7)

    def test_add_validation_filter_persistence_and_local_cover_data(self) -> None:
        jpeg = b"\xff\xd8\xffsynthetic-jpeg-bytes\xff\xd9"
        data_uri = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "media.sqlite3"
            repository = MediaRepository(database, _source(), today_provider=lambda: date(2026, 9, 27))
            created = repository.add_item(
                "  新作品  ", "番", "在看", 4, "  这句短评  ", "2026-09-25", data_uri,
                item_id="local-1",
            )
            self.assertEqual(created["name"], "新作品")
            self.assertEqual(created["review"], "这句短评")
            self.assertEqual(created["cover"], data_uri)
            repository.set_status_filter("在看")
            repository.set_rating_filter(3)
            reopened = MediaRepository(database, today_provider=lambda: date(2026, 9, 27))
            self.assertEqual([item["id"] for item in reopened.filtered_items()], ["local-1"])
            self.assertEqual(reopened.settings()["mediaStatusFilter"], "在看")
            self.assertEqual(reopened.settings()["mediaRatingFilter"], 3)

            for kwargs, message in (
                ({"name": "  "}, "名称不能为空"),
                ({"name": "名" * 61}, "最多 60"),
                ({"kind": "播客"}, "电影、剧、书或番"),
                ({"status": "收藏"}, "有效的作品状态"),
                ({"rating": 5.5}, "0 到 5 的整数"),
                ({"review": "评" * 101}, "最多 100"),
                ({"day": "2026-02-30"}, "有效日期"),
                ({"cover": "https://example.invalid/cover.jpg"}, "本机处理后的 JPEG"),
            ):
                values: dict[str, object] = {
                    "name": "坏输入", "kind": "电影", "status": "想看", "rating": 0,
                    "review": "", "day": "2026-09-27", "cover": "",
                }
                values.update(kwargs)
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(MediaRepositoryError, message):
                    reopened.add_item(**values)  # type: ignore[arg-type]

    def test_imported_delete_tombstone_survives_reimport_and_preserves_raw_base(self) -> None:
        old = _item("legacy-delete", "不想看了", "2026-09-27", "想看", remoteId="remote-9")
        source = _source([old])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "media.sqlite3"
            repository = MediaRepository(database, source)
            self.assertTrue(repository.delete_item("legacy-delete"))
            self.assertEqual(repository.items(), [])
            self.assertEqual(repository.deleted_item_ids(), ["legacy-delete"])
            self.assertEqual(repository.legacy_items(), [old])
            self.assertTrue(repository.adopt_imported_data(source))
            reopened = MediaRepository(database, source)
            self.assertEqual(reopened.items(), [])
            self.assertEqual(reopened.legacy_items(), [old])

    def test_delayed_import_retains_local_items_and_local_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "media.sqlite3"
            repository = MediaRepository(database, _source([_item("base-1", "初始", "2026-01-01", "想看")]))
            repository.add_item("本机新增", "书", "看完", 5, item_id="local-1")
            repository.set_view("list")
            new_source = _source(
                [_item("new-1", "后导入", "2026-09-27", "看完", remoteId="r-2")],
                {"mediaView": "wall", "mediaRatingFilter": 4, "newLegacySetting": "retained"},
            )
            self.assertTrue(repository.adopt_imported_data(new_source))
            items = {item["id"]: item for item in repository.items()}
            self.assertEqual(set(items), {"new-1", "local-1"})
            self.assertEqual(items["new-1"]["remoteId"], "r-2")
            self.assertEqual(repository.settings()["mediaView"], "list")
            self.assertEqual(repository.settings()["mediaRatingFilter"], 4)
            self.assertEqual(repository.settings()["newLegacySetting"], "retained")

    def test_imported_media_form_draft_can_be_overlaid_and_cleared_locally(self) -> None:
        old_draft = {
            "name": "未提交的作品",
            "type": "书",
            "status": "想看",
            "rating": "0",
            "review": "先写下的一句话",
            "futureInput": "keep me",
        }
        source = _source(draft=old_draft)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "media.sqlite3"
            repository = MediaRepository(database, source)
            self.assertEqual(repository.state()["draft"], old_draft)
            repository.save_draft({"name": "本机草稿", "date": "2026-09-27"})
            reopened = MediaRepository(database)
            self.assertEqual(reopened.draft(), {
                **old_draft,
                "name": "本机草稿",
                "date": "2026-09-27",
            })
            reopened.clear_draft()
            self.assertEqual(reopened.draft(), {})
            self.assertTrue(reopened.adopt_imported_data(source))
            self.assertEqual(reopened.draft(), {})
            self.assertEqual(source["documents"]["richangji-state-v1"]["drafts"]["mediaForm"], old_draft)

    def test_native_delete_removes_local_addition_without_hiding_legacy_rows(self) -> None:
        old = _item("old", "旧条目", "2026-09-01", "在看")
        with tempfile.TemporaryDirectory() as directory:
            repository = MediaRepository(Path(directory) / "media.sqlite3", _source([old]))
            repository.add_item("本机条目", "电影", "想看", item_id="local")
            self.assertTrue(repository.delete_item("local"))
            self.assertEqual([item["id"] for item in repository.items()], ["old"])
            self.assertEqual(repository.deleted_item_ids(), [])
            self.assertFalse(repository.delete_item("absent"))

    def test_snapshot_fallback_and_empty_database_do_not_invent_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "media.sqlite3"
            repository = MediaRepository(database, {"status": "empty", "hasData": False, "entities": {"media_items": []}})
            self.assertEqual(repository.items(), [])
            fallback = {"status": "loaded", "hasData": True, "entities": {"media_items": [_item("row", "导入行", "2026-09-27", "在看")]}}
            self.assertTrue(repository.adopt_imported_data(fallback))
            self.assertEqual([item["id"] for item in repository.items()], ["row"])

    def test_prepare_cover_enforces_source_size_and_reencodes_bounded_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.png"
            image = QImage(720, 960, QImage.Format.Format_RGB32)
            image.fill(0xFFAA6633)
            self.assertTrue(image.save(str(path), "PNG"))
            prepared = prepare_cover_file(path)
            self.assertEqual(prepared["format"], "JPEG")
            self.assertEqual((prepared["width"], prepared["height"]), (360, 480))
            self.assertTrue(str(prepared["dataUri"]).startswith("data:image/jpeg;base64,"))
            decoded = QImage()
            encoded = QByteArray.fromBase64(str(prepared["dataUri"]).split(",", 1)[1].encode("ascii"))
            self.assertTrue(decoded.loadFromData(encoded, "JPEG"))
            self.assertEqual((decoded.width(), decoded.height()), (360, 480))

            bad = Path(directory) / "not-an-image.bin"
            bad.write_bytes(b"not an image")
            with self.assertRaisesRegex(MediaRepositoryError, "格式不支持"):
                prepare_cover_file(bad)

            oversized = Path(directory) / "oversized.png"
            with oversized.open("wb") as stream:
                stream.truncate(MAX_COVER_SOURCE_BYTES + 1)
            with self.assertRaisesRegex(MediaRepositoryError, "12MB"):
                prepare_cover_file(oversized)

    def test_filter_validation_and_imported_cover_is_not_rewritten(self) -> None:
        old = _item("web-cover", "远程字段旧封面", "2026-09-27", "想看", cover="https://cover.invalid/x.webp")
        with tempfile.TemporaryDirectory() as directory:
            repository = MediaRepository(Path(directory) / "media.sqlite3", _source([old]))
            with self.assertRaisesRegex(MediaRepositoryError, "视图必须"):
                repository.set_view("cover")
            with self.assertRaisesRegex(MediaRepositoryError, "状态筛选"):
                repository.set_status_filter("收藏")
            with self.assertRaisesRegex(MediaRepositoryError, "0、3、4 或 5"):
                repository.set_rating_filter(2)
            with self.assertRaisesRegex(MediaRepositoryError, "0、3、4 或 5"):
                repository.set_rating_filter(3.5)
            self.assertEqual(repository.items()[0]["cover"], "https://cover.invalid/x.webp")


if __name__ == "__main__":
    unittest.main()
