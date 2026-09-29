from __future__ import annotations

from copy import deepcopy
import unittest

from wanxiang import planner_sync as sync


DEVICE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DEVICE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DEVICE_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def task(task_id: str, title: str, version: dict, **extra: object) -> dict:
    return {
        "id": task_id,
        "type": "planner",
        "date": "2026-09-29",
        "createdAt": 10,
        "webdavSyncVersion": version,
        "data": {"title": title, "done": False, "list": "生活", "note": "", **extra},
    }


def snapshot(device_id: str, tasks: list | None = None, tombstones: list | None = None,
             conflicts: list | None = None, vector: dict | None = None) -> dict:
    return {
        "format": sync.FORMAT,
        "version": sync.VERSION,
        "deviceId": device_id,
        "vector": vector or {},
        "tasks": tasks or [],
        "tombstones": tombstones or [],
        "conflicts": conflicts or [],
    }


class PlannerSyncTests(unittest.TestCase):
    def test_vector_normalization_validation_and_causal_order(self) -> None:
        self.assertEqual(sync.normalize_device_id(DEVICE_A), DEVICE_A)
        self.assertEqual(sync.normalize_device_id("bad id"), "")
        self.assertEqual(sync.normalize_vector({DEVICE_A: "2", DEVICE_B: True, "bad id": 4}),
                         {DEVICE_A: 2, DEVICE_B: 1})
        self.assertFalse(sync.has_valid_vector({DEVICE_A: "2"}))
        self.assertFalse(sync.has_valid_vector({DEVICE_A: 2**53}))
        self.assertEqual(sync.compare_vectors({DEVICE_A: 2}, {DEVICE_A: 1}), "dominates")
        self.assertEqual(sync.compare_vectors({DEVICE_A: 1, DEVICE_B: 2}, {DEVICE_A: 2}), "concurrent")
        self.assertEqual(sync.compare_vectors({DEVICE_A: 1}, {DEVICE_A: 1}), "equal")
        self.assertEqual(sync.merge_vectors({DEVICE_A: 1}, {DEVICE_B: 3}), {DEVICE_A: 1, DEVICE_B: 3})

    def test_local_edits_are_stamped_and_deletes_leave_tombstones(self) -> None:
        previous = {"records": [task("task-a", "Old title", {DEVICE_A: 1})],
                    "settings": {"webdavPlannerVector": {DEVICE_A: 1}}}
        current = deepcopy(previous)
        current["records"][0]["data"]["title"] = "Changed title"
        current["records"].append(task("task-b", "New task", {}))
        external = task("external", "CalDAV task", {})
        external["data"] = {"title": "CalDAV task", "externalTodo": {"provider": "caldav"}}
        current["records"].append(external)
        self.assertTrue(sync.stamp_local_changes(previous, current, DEVICE_A))
        self.assertEqual(current["records"][0]["webdavSyncVersion"], {DEVICE_A: 2})
        self.assertEqual(current["records"][1]["webdavSyncVersion"], {DEVICE_A: 2})
        self.assertEqual(current["records"][2]["webdavSyncVersion"], {})

        after_delete = deepcopy(current)
        after_delete["records"] = [record for record in after_delete["records"] if record["id"] != "task-a"]
        self.assertTrue(sync.stamp_local_changes(current, after_delete, DEVICE_A))
        self.assertEqual(after_delete["settings"]["webdavPlannerTombstones"], [
            {"id": "task-a", "version": {DEVICE_A: 3}},
        ])

    def test_duplicate_tombstones_merge_versions(self) -> None:
        self.assertEqual(sync.normalize_tombstones([
            {"id": "task-a", "version": {DEVICE_A: 1}},
            {"id": "task-a", "version": {DEVICE_B: 2}},
        ]), [{"id": "task-a", "version": {DEVICE_A: 1, DEVICE_B: 2}}])

    def test_malformed_snapshot_entries_reject_the_whole_snapshot(self) -> None:
        self.assertIsNone(sync.normalize_snapshot(snapshot(DEVICE_A, [
            task("valid", "Keep me", {DEVICE_A: 1}),
            {**task("broken", "Invalid date", {DEVICE_A: 1}), "date": "not-a-date"},
        ])))
        self.assertIsNone(sync.normalize_snapshot(snapshot(DEVICE_A, [task("unversioned", "Unversioned", {})])))
        self.assertIsNone(sync.normalize_snapshot(snapshot(DEVICE_A, [task("valid", "Keep me", {DEVICE_A: 1})], [
            {"id": "deleted", "version": {"bad device id": 2}},
        ])))
        self.assertIsNone(sync.normalize_snapshot({**snapshot(DEVICE_A), "vector": {DEVICE_A: -1}}))
        self.assertIsNone(sync.normalize_snapshot({**snapshot(DEVICE_A), "version": True}))

    def test_disjoint_changes_and_causally_newer_task_merge(self) -> None:
        merged = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("shared", "Old", {DEVICE_A: 1}), task("a-only", "A", {DEVICE_A: 1})], vector={DEVICE_A: 1}),
            snapshot(DEVICE_B, [task("shared", "New", {DEVICE_A: 2}), task("b-only", "B", {DEVICE_B: 1})], vector={DEVICE_B: 1}),
        )
        self.assertEqual([item["id"] for item in merged["tasks"]], ["a-only", "b-only", "shared"])
        self.assertEqual(next(item for item in merged["tasks"] if item["id"] == "shared")["data"]["title"], "New")
        self.assertEqual(merged["conflicts"], [])

    def test_concurrent_task_edits_remain_reviewable(self) -> None:
        merged = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("shared", "Title from A", {DEVICE_A: 2})], vector={DEVICE_A: 2}),
            snapshot(DEVICE_B, [task("shared", "Title from B", {DEVICE_B: 3})], vector={DEVICE_B: 3}),
        )
        self.assertEqual(len(merged["tasks"]), 1)
        self.assertEqual(merged["tasks"][0]["data"]["title"], "Title from A")
        self.assertEqual(len(merged["conflicts"]), 1)
        self.assertEqual({item["record"]["data"]["title"] for item in merged["conflicts"][0]["variants"]},
                         {"Title from A", "Title from B"})

    def test_concurrent_focus_sessions_merge_by_id_and_date(self) -> None:
        left = task("shared", "Same task", {DEVICE_A: 4}, sessions=[
            {"id": "focus-a", "date": "2026-09-29", "seconds": 300,
             "startedAt": "2026-09-29T10:00:00", "endedAt": "2026-09-29T10:05:00"},
        ])
        right = task("shared", "Same task", {DEVICE_B: 2}, sessions=[
            {"id": "focus-a", "date": "2026-09-29", "seconds": 500,
             "startedAt": "2026-09-29T09:58:00", "endedAt": "2026-09-29T10:12:00"},
            {"id": "focus-b", "date": "2026-09-29", "seconds": 600},
        ])
        merged = sync.merge_snapshots(snapshot(DEVICE_A, [left]), snapshot(DEVICE_B, [right]))
        self.assertEqual(merged["conflicts"], [])
        self.assertEqual(len(merged["tasks"][0]["data"]["sessions"]), 2)
        focus_a = next(item for item in merged["tasks"][0]["data"]["sessions"] if item["id"] == "focus-a")
        self.assertEqual(focus_a["seconds"], 500)
        self.assertEqual(focus_a["startedAt"], "2026-09-29T09:58:00")
        self.assertEqual(focus_a["endedAt"], "2026-09-29T10:12:00")
        self.assertEqual(merged["tasks"][0]["data"]["trackedSeconds"], 1100)
        self.assertEqual(merged["tasks"][0]["webdavSyncVersion"], {DEVICE_A: 4, DEVICE_B: 2})

    def test_causal_deletion_wins_but_concurrent_deletion_is_a_conflict(self) -> None:
        deleted = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("gone", "Task", {DEVICE_A: 1})]),
            snapshot(DEVICE_B, [], [{"id": "gone", "version": {DEVICE_A: 2}}]),
        )
        self.assertEqual(deleted["tasks"], [])
        self.assertEqual(deleted["tombstones"][0]["id"], "gone")
        self.assertEqual(deleted["conflicts"], [])

        concurrent = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("maybe", "Edited task", {DEVICE_A: 3})]),
            snapshot(DEVICE_B, [], [{"id": "maybe", "version": {DEVICE_B: 1}}]),
        )
        self.assertEqual(len(concurrent["tasks"]), 1)
        self.assertEqual(len(concurrent["tombstones"]), 1)
        self.assertTrue(any(item["deleted"] for item in concurrent["conflicts"][0]["variants"]))

    def test_conflict_resolution_can_keep_a_separate_copy(self) -> None:
        merged = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("shared", "One", {DEVICE_A: 1})]),
            snapshot(DEVICE_B, [task("shared", "Two", {DEVICE_B: 1})]),
        )
        state = {"records": deepcopy(merged["tasks"]), "settings": {
            "webdavPlannerVector": merged["vector"], "webdavPlannerTombstones": merged["tombstones"],
            "webdavPlannerConflicts": merged["conflicts"],
        }}
        self.assertTrue(sync.resolve_conflict(state, "shared", 0, DEVICE_A, True))
        self.assertEqual(state["settings"]["webdavPlannerConflicts"], [])
        self.assertEqual(len(state["records"]), 2)
        self.assertTrue(any(item["data"].get("webdavConflictOf") == "shared" for item in state["records"]))
        self.assertEqual(sorted(item["id"] for item in sync.snapshot_from_state(state, DEVICE_A)["tasks"]),
                         sorted(item["id"] for item in state["records"]))

    def test_choosing_concurrent_delete_can_preserve_the_edited_task_copy(self) -> None:
        merged = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("shared", "Edited on A", {DEVICE_A: 2})]),
            snapshot(DEVICE_B, [], [{"id": "shared", "version": {DEVICE_B: 1}}]),
        )
        state = {"records": deepcopy(merged["tasks"]), "settings": {
            "webdavPlannerVector": merged["vector"], "webdavPlannerTombstones": merged["tombstones"],
            "webdavPlannerConflicts": merged["conflicts"],
        }}
        delete_index = next(index for index, item in enumerate(merged["conflicts"][0]["variants"]) if item["deleted"])
        self.assertTrue(sync.resolve_conflict(state, "shared", delete_index, DEVICE_A, True))
        self.assertEqual(len(state["records"]), 1)
        self.assertRegex(state["records"][0]["id"], r"^shared:copy:")
        self.assertEqual(state["records"][0]["data"]["webdavConflictOf"], "shared")
        self.assertTrue(any(item["id"] == "shared" for item in state["settings"]["webdavPlannerTombstones"]))

    def test_resolution_merges_focus_history_and_can_preserve_all_live_variants(self) -> None:
        merged = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("shared", "Version A", {DEVICE_A: 1}, sessions=[
                {"id": "focus-a", "date": "2026-09-29", "seconds": 300},
            ])]),
            snapshot(DEVICE_B, [task("shared", "Version B", {DEVICE_B: 1}, sessions=[
                {"id": "focus-b", "date": "2026-09-29", "seconds": 600},
            ])]),
        )
        state = {"records": deepcopy(merged["tasks"]), "settings": {
            "webdavPlannerVector": merged["vector"], "webdavPlannerTombstones": merged["tombstones"],
            "webdavPlannerConflicts": merged["conflicts"],
        }}
        self.assertTrue(sync.resolve_conflict(state, "shared", 0, DEVICE_A))
        self.assertEqual(len(state["records"]), 1)
        data = state["records"][0]["data"]
        self.assertEqual({item["id"] for item in data["sessions"]}, {"focus-a", "focus-b"})
        self.assertEqual(data["trackedSeconds"], 900)

        three = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("multi", "A", {DEVICE_A: 1})]),
            snapshot(DEVICE_B, [task("multi", "B", {DEVICE_B: 1})]),
            snapshot(DEVICE_C, [task("multi", "C", {DEVICE_C: 1})]),
        )
        keep_state = {"records": deepcopy(three["tasks"]), "settings": {
            "webdavPlannerVector": three["vector"], "webdavPlannerTombstones": three["tombstones"],
            "webdavPlannerConflicts": three["conflicts"],
        }}
        self.assertEqual(len(three["conflicts"][0]["variants"]), 3)
        self.assertTrue(sync.resolve_conflict(keep_state, "multi", 0, DEVICE_A, True))
        self.assertEqual(len(keep_state["records"]), 3)
        self.assertEqual(len({item["id"] for item in keep_state["records"]}), 3)

        # The legacy JS helper accepted only two arrays despite spreading every
        # conflict variant here; Python merges all branches so later focus work survives.
        three_focus = sync.merge_snapshots(
            snapshot(DEVICE_A, [task("focus", "A", {DEVICE_A: 1}, sessions=[
                {"id": "focus-a", "date": "2026-09-29", "seconds": 100},
            ])]),
            snapshot(DEVICE_B, [task("focus", "B", {DEVICE_B: 1}, sessions=[
                {"id": "focus-b", "date": "2026-09-29", "seconds": 200},
            ])]),
            snapshot(DEVICE_C, [task("focus", "C", {DEVICE_C: 1}, sessions=[
                {"id": "focus-c", "date": "2026-09-29", "seconds": 300},
            ])]),
        )
        focus_state = {"records": deepcopy(three_focus["tasks"]), "settings": {
            "webdavPlannerVector": three_focus["vector"],
            "webdavPlannerTombstones": three_focus["tombstones"],
            "webdavPlannerConflicts": three_focus["conflicts"],
        }}
        self.assertTrue(sync.resolve_conflict(focus_state, "focus", 0, DEVICE_A))
        self.assertEqual({item["id"] for item in focus_state["records"][0]["data"]["sessions"]},
                         {"focus-a", "focus-b", "focus-c"})

    def test_apply_preserves_device_local_remote_ids_and_unrelated_records(self) -> None:
        local = task("shared", "Local stale", {DEVICE_A: 1})
        local["remoteId"] = "notion-row"
        remote = task("shared", "Remote new", {DEVICE_A: 2})
        state = {"records": [local, {"id": "money", "type": "money", "date": "2026-09-29", "data": {}}], "settings": {}}
        self.assertTrue(sync.apply_merged_snapshot(state, sync.merge_snapshots(snapshot(DEVICE_B, [remote]))))
        applied = next(item for item in state["records"] if item["id"] == "shared")
        self.assertEqual(applied["data"]["title"], "Remote new")
        self.assertEqual(applied["remoteId"], "notion-row")
        self.assertTrue(any(item["id"] == "money" for item in state["records"]))


if __name__ == "__main__":
    unittest.main()
