from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codememory_task_graph_projection as projection
import rolling_decomposition as rolling
import rolling_decomposition_qualification as qualification
import task_graph_command as command
from task_graph_runtime import bounded_frontier


class RollingDecompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.proposals = rolling.fragments(50)

    def tasks(self):
        return copy.deepcopy(
            list(
                projection.build_projection(
                    rolling.model_snapshot(self.proposals)
                ).tasks
            )
        )

    def test_all_sizes_cover_independent_inventory_and_bounded_fragments(self):
        for size in rolling.SIZES:
            proposals = rolling.fragments(size)
            with self.subTest(size=size):
                report = rolling.coverage(proposals, rolling.assignments(size), size)
                self.assertEqual(report["task_count"], size)
                self.assertEqual(report["epic_count"], (size + 2) // 3)
                self.assertEqual(report["covered_requirements"], size)
                self.assertEqual(report["hierarchy_edges"], size)
                self.assertEqual(report["dependency_edges"], size - (size + 2) // 3)
                self.assertEqual(report["max_task_depth"], 2)
                self.assertTrue(
                    all(len(p["records"]) + len(p["links"]) <= 10 for p in proposals)
                )

    def test_every_scale_passes_real_planner_admission(self):
        (self.root / "contract.md").write_text(
            "Track every requirement and keep graph writes with the coordinator.\n"
        )
        for size in rolling.SIZES:
            for proposal in rolling.fragments(size):
                self.assertEqual(qualification.admit(proposal, self.root), proposal)

    def test_negative_coverage_controls_reject_omissions_duplicates_and_broken_hierarchy(
        self,
    ):
        for fault in (
            "omitted_atom",
            "duplicate_atom",
            "duplicate_owner",
            "missing_parent",
            "duplicate_title",
            "duplicate_key",
            "cycle",
        ):
            proposals = copy.deepcopy(self.proposals)
            assignments = rolling.assignments(50)
            if fault == "omitted_atom":
                assignments.pop()
            elif fault == "duplicate_atom":
                assignments[1] = (assignments[0][0], assignments[1][1])
            elif fault == "duplicate_owner":
                assignments[1] = (assignments[1][0], assignments[0][1])
            elif fault == "missing_parent":
                proposals[0]["links"].pop(0)
            elif fault == "duplicate_title":
                proposals[1]["records"][1]["title"] = proposals[0]["records"][1][
                    "title"
                ]
            elif fault == "duplicate_key":
                proposals.append(copy.deepcopy(proposals[0]))
            elif fault == "cycle":
                proposals[0]["links"][0]["from"] = proposals[0]["records"][2]["key"]
            with (
                self.subTest(fault=fault),
                self.assertRaises(
                    (
                        rolling.QualificationError,
                        qualification.coordinator.CoordinatorError,
                    )
                ),
            ):
                rolling.coverage(proposals, assignments, 50)

    def test_rolling_completion_restart_and_byte_stable_projection_at_all_sizes(self):
        for size in rolling.SIZES:
            root = self.root / str(size)
            root.mkdir()
            report = qualification.local_checks(
                rolling.model_snapshot(rolling.fragments(size)), root
            )
            with self.subTest(size=size):
                self.assertEqual(report["completed_task_count"], size)
                self.assertLessEqual(report["peak_frontier"], 2)
                self.assertTrue(report["checkpoint_recovered"])

    def test_frontier_counts_existing_work_and_reports_over_capacity(self):
        tasks = self.tasks()
        initial = bounded_frontier(tasks)
        self.assertEqual(initial["selected_count"], 2)
        self.assertGreater(initial["deferred_count"], 0)
        initial["tasks"][0]["status"] = "in_progress"
        self.assertEqual(bounded_frontier(tasks)["selected_count"], 1)
        initial["tasks"][1]["status"] = "in_progress"
        self.assertEqual(bounded_frontier(tasks)["selected_count"], 0)
        remaining = next(
            task
            for task in tasks
            if not task["blockedBy"] and task["status"] == "pending"
        )
        remaining["status"] = "in_progress"
        report = bounded_frontier(tasks)
        self.assertEqual(report["selected_count"], 0)
        self.assertTrue(report["over_capacity"])
        self.assertEqual(report["active_count"], 3)

    def test_frontier_is_deterministic_advisory_and_does_not_mutate_graph(self):
        tasks = self.tasks()
        before = copy.deepcopy(tasks)
        report = bounded_frontier(tasks)
        self.assertEqual(report, bounded_frontier(list(reversed(tasks))))
        self.assertEqual(tasks, before)
        self.assertEqual(report["authority"], "advisory-only")
        self.assertEqual(len(tasks), 50)
        for value in (0, -1, 33, True, "2", None, 2.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bounded_frontier(tasks, value)
        self.assertEqual(bounded_frontier(tasks, 1)["selected_count"], 1)

    def test_failed_blocked_canceled_missing_and_cyclic_prerequisites_never_run(self):
        tasks = self.tasks()
        child = next(task for task in tasks if task["blockedBy"])
        parent = next(task for task in tasks if task["id"] == child["blockedBy"][0])
        for status in ("pending", "in_progress", "failed", "blocked", "canceled"):
            parent["status"] = status
            self.assertNotIn(
                child["id"],
                {task["id"] for task in bounded_frontier(tasks, 32)["tasks"]},
            )
        parent["status"] = "completed"
        self.assertIn(
            child["id"], {task["id"] for task in bounded_frontier(tasks, 32)["tasks"]}
        )
        parent["status"] = "pending"
        parent["blockedBy"] = [child["id"]]
        self.assertFalse(bounded_frontier([parent, child])["tasks"])
        self.assertFalse(bounded_frontier([child])["tasks"])

    def test_cli_wiring_and_invalid_limit_preserve_projection_bytes(self):
        path = self.root / "config" / "opencode.json"
        _, _, runtime = projection.apply_projection(
            path, projection.build_projection(rolling.model_snapshot(self.proposals))
        )
        before = runtime.read_bytes()
        for arguments, expected in (
            (["frontier", "--json"], 0),
            (["frontier", "--limit", "33", "--json"], 1),
        ):
            with (
                patch.object(command, "_write_path", return_value=path),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(command.main(arguments), expected)
            report = json.loads(output.getvalue())
            self.assertEqual(report["result"], "PASS" if expected == 0 else "FAIL")
            if expected == 0:
                self.assertEqual(report["selected_count"], 2)
                self.assertTrue(report["projection_revision"].startswith("sha256:"))
            self.assertEqual(runtime.read_bytes(), before)
        state = json.loads(before)
        state["tasks"][0]["subject"] = "tampered"
        runtime.write_text(json.dumps(state))
        with (
            patch.object(command, "_write_path", return_value=path),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(command.main(["frontier", "--json"]), 1)
        self.assertEqual(
            json.loads(output.getvalue())["reason_code"], "task_graph_state_invalid"
        )

    def test_projection_sandbox_ignores_and_restores_external_runtime_overrides(self):
        scenario = self.root / "scenario"
        scenario.mkdir()
        sentinel = self.root / "host-graph.json"
        sentinel_lock = self.root / "host-graph.lock"
        sentinel.write_bytes(b"host graph sentinel")
        sentinel_lock.write_bytes(b"host lock sentinel")
        overrides = {
            "MY_OPENCODE_TASK_GRAPH_PATH": str(sentinel),
            "MY_OPENCODE_TASK_GRAPH_LOCK_PATH": str(sentinel_lock),
        }
        with patch.dict(os.environ, overrides):
            report = qualification.local_checks(
                rolling.model_snapshot(self.proposals), scenario
            )
            self.assertEqual(50, report["completed_task_count"])
            self.assertEqual(str(sentinel), os.environ["MY_OPENCODE_TASK_GRAPH_PATH"])
            self.assertEqual(
                str(sentinel_lock), os.environ["MY_OPENCODE_TASK_GRAPH_LOCK_PATH"]
            )
        self.assertEqual(b"host graph sentinel", sentinel.read_bytes())
        self.assertEqual(b"host lock sentinel", sentinel_lock.read_bytes())
        self.assertEqual(1, len(list(scenario.rglob("task_graph.json"))))
        self.assertEqual(1, len(list(scenario.rglob("task_graph.lock"))))

    def test_human_frontier_displays_selected_ids_capacity_and_overflow(self):
        path = self.root / "config" / "opencode.json"
        snapshot = rolling.model_snapshot(self.proposals)
        projection.apply_projection(path, projection.build_projection(snapshot))
        with (
            patch.object(command, "_write_path", return_value=path),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(0, command.main(["frontier"]))
        self.assertIn("authority: advisory-only", output.getvalue())
        self.assertIn("active: 0/2", output.getvalue())
        self.assertIn("task:r00000", output.getvalue())
        self.assertIn("selected: 2", output.getvalue())
        status = {task.id: "doing" for task in snapshot.tasks[:3]}
        active_snapshot = rolling.model_snapshot(self.proposals, status)
        projection.apply_projection(path, projection.build_projection(active_snapshot))
        with (
            patch.object(command, "_write_path", return_value=path),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(0, command.main(["frontier"]))
        self.assertIn("active: 3/2", output.getvalue())
        self.assertIn("over_capacity: True", output.getvalue())
        self.assertIn("selected: 0", output.getvalue())

    def test_model_deadlock_and_latency_fail_explicitly(self):
        snapshot = rolling.model_snapshot(self.proposals)
        with self.assertRaisesRegex(rolling.QualificationError, "latency budget"):
            rolling.rolling_model(snapshot, self.root / "checkpoint", seconds=0)
        cyclic = projection.SourceSnapshot(
            snapshot.scope_key,
            snapshot.tasks,
            tuple(
                (task.id, snapshot.tasks[(index + 1) % len(snapshot.tasks)].id)
                for index, task in enumerate(snapshot.tasks)
            ),
        )
        with self.assertRaisesRegex(rolling.QualificationError, "deadlocked"):
            rolling.rolling_model(cyclic, self.root / "checkpoint")

    def test_native_cli_reports_bounded_process_failure_as_json(self):
        failure = qualification.BoundedCommandError(
            SimpleNamespace(detail="bounded fixture failure")
        )
        with (
            patch.object(qualification.shutil, "which", return_value=sys.executable),
            patch.object(qualification, "qualify", side_effect=failure),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(1, qualification.main(["--sizes", "9"]))
        self.assertEqual(
            {"result": "FAIL", "detail": "bounded fixture failure"},
            json.loads(output.getvalue()),
        )

    def test_native_stage_deadline_rejects_before_subprocess(self):
        backend = object.__new__(qualification.NativeScope)
        backend.deadline = time.monotonic()
        with (
            patch.object(
                qualification,
                "run_bounded",
                side_effect=AssertionError("process started"),
            ),
            self.assertRaisesRegex(rolling.QualificationError, "aggregate deadline"),
        ):
            backend.bounded(["not-executed"])
        for size in rolling.SIZES:
            budgets = qualification.latency_budgets(size)
            self.assertGreaterEqual(budgets["intake"], 30)
            self.assertGreaterEqual(budgets["snapshot"], 30)


if __name__ == "__main__":
    unittest.main()
