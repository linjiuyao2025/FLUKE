from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from wanxiang.planner import PlannerRepository
from wanxiang.planner_sync import FORMAT, VERSION, merge_snapshots, snapshot_from_state


DEVICE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DEVICE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def record(record_id: str, title: str, **extra: object) -> dict[str, object]:
    return {
        "id": record_id,
        "type": "planner",
        "date": "2026-09-29",
        "createdAt": 10,
        "sample": False,
        "data": {"title": title, "done": False, "sessions": [], "trackedSeconds": 0},
        **extra,
    }


def source(records: list[dict[str, object]]) -> dict[str, object]:
    return {"richangji-state-v1": {"records": records, "settings": {}, "drafts": {}}}


def snapshot(device: str, tasks: list[dict[str, object]], tombstones: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "deviceId": device,
        "vector": {},
        "tasks": tasks,
        "tombstones": tombstones or [],
        "conflicts": [],
    }


class PlannerSyncRepositoryTests(unittest.TestCase):
    def test_merge_roundtrips_over_legacy_source_without_mutating_imported_original(self) -> None:
        imported = record("legacy-task", "old-title", legacyEnvelope={"keep": True})
        sample = record("sample-task", "sample", sample=True)
        external = record("external-task", "external", data={"title": "external", "externalTodo": {"provider": "caldav"}})
        original = deepcopy(source([imported, sample, external]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planner-sync.sqlite3"
            repository = PlannerRepository(path, source([imported, sample, external]))
            local = repository.webdav_sync_state()
            local_snapshot = snapshot_from_state(local, DEVICE_A)
            changed = record(
                "legacy-task", "remote-title",
                webdavSyncVersion={DEVICE_B: 1},
                legacyEnvelope={"keep": True},
            )
            remote = snapshot(DEVICE_B, [changed])
            merged = merge_snapshots(local_snapshot, remote)

            repository.apply_webdav_sync_snapshot(merged)
            by_id = {item["id"]: item for item in repository.records()}
            self.assertEqual(by_id["legacy-task"]["data"]["title"], "remote-title")
            self.assertEqual({item["id"] for item in repository.records()}, {
                "legacy-task", "sample-task", "external-task",
            })
            self.assertEqual(repository._state["legacyRecords"][0], imported)
            self.assertEqual(repository._state["legacyRecords"][0]["data"]["title"], "old-title")
            self.assertEqual(repository.webdav_sync_state()["settings"]["webdavPlannerVector"], {DEVICE_B: 1})

            reopened = PlannerRepository(path)
            self.assertEqual(reopened.records(), repository.records())
            self.assertEqual(reopened._state["legacyRecords"][0], imported)
            self.assertEqual(original["richangji-state-v1"]["records"][0], imported)

    def test_remote_tombstone_hides_imported_task_and_keeps_source_row(self) -> None:
        imported = record("legacy-task", "preserve-source")
        with tempfile.TemporaryDirectory() as directory:
            repository = PlannerRepository(Path(directory) / "deleted.sqlite3", source([imported]))
            local = snapshot_from_state(repository.webdav_sync_state(), DEVICE_A)
            remote = snapshot(DEVICE_B, [], [{"id": "legacy-task", "version": {DEVICE_B: 2}}])
            merged = merge_snapshots(local, remote)
            repository.apply_webdav_sync_snapshot(merged)

            self.assertEqual(repository.records(), [])
            self.assertIn({"type": "planner", "id": "legacy-task"}, repository._state["deletedRecords"])
            self.assertEqual(repository._state["legacyRecords"][0], imported)


if __name__ == "__main__":
    unittest.main()
