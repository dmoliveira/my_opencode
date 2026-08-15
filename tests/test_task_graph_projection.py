from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import autopilot_command
import codememory_task_graph_projection as projection
import start_work_command
import task_graph_command
import task_graph_runtime
import workflow_command


class FakeCodememoryRunner:
    def __init__(
        self,
        tasks: list[dict[str, str]],
        dependencies: list[tuple[str, str]] | None = None,
        *,
        explicit_links: list[tuple[str, str, str]] | None = None,
        scope: str = "example/repo",
        unstable: bool = False,
        unstable_link: bool = False,
        link_display: str | None = None,
    ) -> None:
        self.tasks = [dict(task) for task in tasks]
        self.dependencies = list(dependencies or [])
        self.scope = scope
        self.unstable = unstable
        self.unstable_link = unstable_link
        self.link_display = link_display
        self.task_scans = 0
        self.link_gets: dict[str, int] = {}
        self.calls: list[tuple[list[str], str]] = []
        source_links = [
            ("depends-on", source, target)
            for source, target in (dependencies or [])
        ]
        source_links.extend(explicit_links or [])
        self.link_details = {
            f"link_{index}": {
                "id": f"link_{index}",
                "type": "link",
                "from_id": source,
                "edge_type": edge_type,
                "to_id": target,
            }
            for index, (edge_type, source, target) in enumerate(source_links, start=1)
        }

    def __call__(self, arguments: list[str], operation: str) -> dict[str, object]:
        self.calls.append((list(arguments), operation))
        if arguments[:2] == ["list", "task"]:
            status = (
                arguments[arguments.index("--status") + 1]
                if "--status" in arguments
                else None
            )
            if status is None:
                self.task_scans += 1
            changed = self.unstable and self.task_scans >= 2
            tasks = [dict(task) for task in self.tasks]
            if changed and tasks:
                tasks[0]["title"] = f"{tasks[0]['title']} changed"
            if status is not None:
                tasks = [task for task in tasks if task["status"] == status]
            items = [
                {"id": task["id"], "display": task["title"], "kind": task["kind"]}
                for task in sorted(tasks, key=lambda task: task["id"])
            ]
            return {
                "type": "list_result",
                "entity_type": "task",
                "scope_key": self.scope,
                "count": len(items),
                "items": items,
            }
        if arguments[:2] == ["list", "link"]:
            items = [
                {
                    "id": link_id,
                    "display": self.link_display or f"depends-on {detail['to_id']}",
                }
                for link_id, detail in sorted(self.link_details.items())
            ]
            return {
                "type": "list_result",
                "entity_type": "link",
                "scope_key": self.scope,
                "count": len(items),
                "items": items,
            }
        if arguments and arguments[0] == "get":
            link_id = arguments[1]
            self.link_gets[link_id] = self.link_gets.get(link_id, 0) + 1
            detail = dict(self.link_details[link_id])
            if self.unstable_link and self.link_gets[link_id] >= 2:
                detail["from_id"] = detail["to_id"]
            return detail
        raise AssertionError(f"unexpected Codememory arguments: {arguments}")


def source_task(
    task_id: str,
    status: str = "not-started",
    *,
    title: str | None = None,
    kind: str = "feature",
) -> dict[str, str]:
    return {
        "id": task_id,
        "title": title or f"Task {task_id}",
        "kind": kind,
        "status": status,
    }


def make_projection(
    tasks: list[dict[str, str]] | None = None,
    dependencies: list[tuple[str, str]] | None = None,
    *,
    scope: str = "example/repo",
) -> projection.TaskGraphProjection:
    runner = FakeCodememoryRunner(
        tasks or [source_task("task_1")], dependencies, scope=scope
    )
    return projection.build_projection(projection.load_source_snapshot(runner, scope))


def write_path(root: Path) -> Path:
    return root / "config" / "opencode.json"


def runtime_path(root: Path) -> Path:
    return task_graph_runtime.runtime_path(write_path(root))


def write_raw_state(root: Path, tasks: list[dict[str, object]]) -> Path:
    path = runtime_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "updated_at": "2026-08-15T00:00:00Z",
                "tasks": tasks,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def local_task(task_id: str = "workflow:local#step") -> dict[str, object]:
    return {
        "id": task_id,
        "subject": "Local workflow step",
        "description": "",
        "status": "pending",
        "activeForm": "Local workflow step",
        "blockedBy": [],
        "blocks": [],
        "owner": "workflow",
        "metadata": {"command_family": "workflow"},
        "completionGates": {},
        "requiredArtifacts": [],
        "threadID": "",
        "created_at": "2026-08-15T00:00:00Z",
        "updated_at": "2026-08-15T00:00:00Z",
    }


class TaskGraphProjectionTests(unittest.TestCase):
    def test_snapshot_maps_every_status_and_dependency_direction(self) -> None:
        statuses = list(projection.SOURCE_STATUSES)
        tasks = [
            source_task(f"task_{index}", status)
            for index, status in enumerate(statuses, start=1)
        ]
        runner = FakeCodememoryRunner(
            tasks,
            [("task_2", "task_1")],
            link_display="human-facing relationship label",
        )

        snapshot = projection.load_source_snapshot(runner, "example/repo")
        projected = projection.build_projection(snapshot)
        by_id = {task["id"]: task for task in projected.tasks}

        self.assertEqual(
            [projection.STATUS_MAP[status] for status in statuses],
            [by_id[f"task_{index}"]["status"] for index in range(1, 7)],
        )
        self.assertEqual(["task_1"], by_id["task_2"]["blockedBy"])
        self.assertEqual("codememory", by_id["task_1"]["owner"])
        self.assertEqual(
            projected.fingerprint,
            projection.build_projection(snapshot).fingerprint,
        )
        self.assertTrue(projected.revision.startswith("sha256:"))
        self.assertTrue(
            all(operation.endswith(("_list", "_get")) for _, operation in runner.calls)
        )
        self.assertEqual({"link_1": 2}, runner.link_gets)

    def test_source_blocked_by_links_fail_closed(self) -> None:
        tasks = [source_task("task_1"), source_task("task_2")]
        for target_id in ("task_1", "memory_1"):
            with self.subTest(target_id=target_id):
                runner = FakeCodememoryRunner(
                    tasks,
                    explicit_links=[("blocked-by", "task_2", target_id)],
                )
                with self.assertRaises(projection.ProjectionError) as raised:
                    projection.load_source_snapshot(runner, "example/repo")
                self.assertEqual(
                    "task_projection_source_unsupported_edge",
                    raised.exception.reason_code,
                )
                self.assertIn("link_1", raised.exception.detail)
                self.assertIn("task_2", raised.exception.detail)

    def test_source_scan_fails_closed_on_change_unknown_status_and_limit(self) -> None:
        unstable = FakeCodememoryRunner([source_task("task_1")], unstable=True)
        with self.assertRaises(projection.ProjectionError) as changed:
            projection.load_source_snapshot(unstable, "example/repo")
        self.assertEqual(
            "task_projection_source_changed", changed.exception.reason_code
        )

        unknown = FakeCodememoryRunner([source_task("task_1", "paused")])
        with self.assertRaises(projection.ProjectionError) as status:
            projection.load_source_snapshot(unknown, "example/repo")
        self.assertEqual(
            "task_projection_source_status_unknown", status.exception.reason_code
        )

        bounded = FakeCodememoryRunner(
            [source_task("task_1"), source_task("task_2"), source_task("task_3")]
        )
        with (
            patch.object(projection, "SOURCE_FETCH_LIMIT", 3),
            self.assertRaises(projection.ProjectionError) as limit,
        ):
            projection.load_source_snapshot(bounded, "example/repo")
        self.assertEqual(
            "task_projection_source_too_large", limit.exception.reason_code
        )

        unstable_link = FakeCodememoryRunner(
            [source_task("task_1"), source_task("task_2")],
            [("task_2", "task_1")],
            unstable_link=True,
        )
        with self.assertRaises(projection.ProjectionError) as link_change:
            projection.load_source_snapshot(unstable_link, "example/repo")
        self.assertEqual(
            "task_projection_source_changed", link_change.exception.reason_code
        )

    def test_apply_preserves_unmanaged_tasks_repairs_drift_and_is_byte_stable(
        self,
    ) -> None:
        projected = make_projection(
            [source_task("task_1"), source_task("task_2", "doing")],
            [("task_2", "task_1")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_raw_state(root, [local_task()])

            initial = projection.check_projection(write_path(root), projected)
            self.assertEqual(["task_1", "task_2"], initial["missing"])
            _, changed, _ = projection.apply_projection(write_path(root), projected)
            self.assertTrue(changed)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                {"workflow:local#step", "task_1", "task_2"},
                {task["id"] for task in state["tasks"]},
            )
            self.assertEqual("example/repo", state["projection"]["scope_key"])
            self.assertFalse(
                projection.check_projection(write_path(root), projected)["drifted"]
            )

            before_bytes = path.read_bytes()
            before_mtime = path.stat().st_mtime_ns
            _, changed, _ = projection.apply_projection(write_path(root), projected)
            self.assertFalse(changed)
            self.assertEqual(before_bytes, path.read_bytes())
            self.assertEqual(before_mtime, path.stat().st_mtime_ns)

            state["tasks"] = [
                {
                    **task,
                    "subject": "tampered",
                }
                if task["id"] == "task_1"
                else task
                for task in state["tasks"]
            ]
            path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(task_graph_runtime.TaskGraphStateError):
                task_graph_runtime.load_state(write_path(root))
            output = io.StringIO()
            with (
                patch.object(
                    task_graph_command, "_write_path", return_value=write_path(root)
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(1, task_graph_command.main(["ready", "--json"]))
            self.assertEqual(
                "task_graph_state_invalid",
                json.loads(output.getvalue())["reason_code"],
            )
            drift = projection.check_projection(write_path(root), projected)
            self.assertEqual(["task_1"], drift["changed"])
            projection.apply_projection(write_path(root), projected)
            repaired = json.loads(path.read_text(encoding="utf-8"))
            task_one = next(
                task for task in repaired["tasks"] if task["id"] == "task_1"
            )
            self.assertEqual("Task task_1", task_one["subject"])
            self.assertTrue(projection.projection_local_health(repaired)["healthy"])

    def test_scope_collision_and_retained_reference_block_apply(self) -> None:
        first = make_projection(
            [source_task("task_1"), source_task("task_2")], scope="scope/one"
        )
        second_scope = make_projection([source_task("task_1")], scope="scope/two")
        reduced = make_projection([source_task("task_1")], scope="scope/one")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projection.apply_projection(write_path(root), first)
            with self.assertRaises(projection.ProjectionError):
                projection.apply_projection(write_path(root), second_scope)

            def add_reference(state: dict[str, object]) -> dict[str, object]:
                tasks = list(state.get("tasks", []))
                task = local_task("local-dependent")
                task["blockedBy"] = ["task_2"]
                tasks.append(task)
                state["tasks"] = tasks
                return state

            task_graph_runtime.with_locked_state(write_path(root), add_reference)
            drift = projection.check_projection(write_path(root), reduced)
            self.assertEqual(
                [{"task_id": "local-dependent", "dependency_id": "task_2"}],
                drift["retained_references"],
            )
            with self.assertRaises(projection.ProjectionError):
                projection.apply_projection(write_path(root), reduced)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_raw_state(root, [{**local_task("task_1"), "blockedBy": []}])
            with self.assertRaises(projection.ProjectionError):
                projection.apply_projection(write_path(root), reduced)

    def test_strict_destination_rejects_malformed_and_duplicate_state(self) -> None:
        projected = make_projection()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = runtime_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(task_graph_runtime.TaskGraphStateError):
                projection.check_projection(write_path(root), projected)
            with self.assertRaises(task_graph_runtime.TaskGraphStateError):
                task_graph_runtime.load_state(write_path(root))
            with self.assertRaises(task_graph_runtime.TaskGraphStateError):
                task_graph_runtime.with_locked_state(
                    write_path(root), lambda state: state
                )
            self.assertEqual("{broken", path.read_text(encoding="utf-8"))

            write_raw_state(root, [local_task("same"), local_task("same")])
            with self.assertRaises(task_graph_runtime.TaskGraphStateError):
                projection.apply_projection(write_path(root), projected)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_raw_state(
                root,
                [{**local_task("dependent"), "blockedBy": ["missing"]}],
            )
            output = io.StringIO()
            with (
                patch.object(
                    task_graph_command, "_write_path", return_value=write_path(root)
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(1, task_graph_command.main(["doctor", "--json"]))
            payload = json.loads(output.getvalue())
            self.assertEqual("task_graph_invalid_dependencies", payload["reason_code"])
            self.assertEqual(
                ["task dependent blockedBy missing task missing"], payload["problems"]
            )

    def test_regular_writers_cannot_change_managed_fields_but_can_derive_blocks(
        self,
    ) -> None:
        projected = make_projection()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projection.apply_projection(write_path(root), projected)
            path = runtime_path(root)
            before = path.read_bytes()

            def tamper(state: dict[str, object]) -> dict[str, object]:
                task = next(task for task in state["tasks"] if task["id"] == "task_1")
                task["status"] = "completed"
                return state

            with self.assertRaises(task_graph_runtime.ManagedTaskMutationError):
                task_graph_runtime.with_locked_state(write_path(root), tamper)
            self.assertEqual(before, path.read_bytes())

            def add_local(state: dict[str, object]) -> dict[str, object]:
                task = local_task("local-dependent")
                task["blockedBy"] = ["task_1"]
                state["tasks"].append(task)
                return state

            task_graph_runtime.with_locked_state(write_path(root), add_local)
            state = task_graph_runtime.load_state(write_path(root)).state
            managed = next(task for task in state["tasks"] if task["id"] == "task_1")
            self.assertEqual(["local-dependent"], managed["blocks"])

    def test_blocked_and_failed_statuses_never_become_ready(self) -> None:
        tasks = [
            {**local_task("blocked"), "status": "blocked"},
            {**local_task("failed"), "status": "failed"},
            {**local_task("canceled"), "status": "canceled"},
            {
                **local_task("dependent"),
                "blockedBy": ["failed"],
            },
            {
                **local_task("canceled-dependent"),
                "blockedBy": ["canceled"],
            },
        ]
        normalized = task_graph_runtime.normalize_state({"tasks": tasks})["tasks"]
        self.assertEqual([], task_graph_runtime.ready_tasks(normalized))
        blocked = task_graph_runtime.blocked_details(normalized)
        by_id = {item["id"]: item["reason_code"] for item in blocked}
        self.assertEqual("codememory_blocked", by_id["blocked"])
        self.assertEqual("dependency_failed", by_id["dependent"])
        self.assertEqual("dependency_canceled", by_id["canceled-dependent"])

    def test_atomic_replace_failure_preserves_old_bytes_and_cleans_temp(self) -> None:
        projected = make_projection()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_raw_state(root, [local_task()])
            before = path.read_bytes()
            with (
                patch("task_graph_runtime.os.replace", side_effect=OSError("replace")),
                self.assertRaises(OSError),
            ):
                projection.apply_projection(write_path(root), projected)
            self.assertEqual(before, path.read_bytes())
            leftovers = [
                item
                for item in path.parent.iterdir()
                if item not in {path, task_graph_runtime.lock_path(write_path(root))}
            ]
            self.assertEqual([], leftovers)

    def test_cli_check_apply_check_and_managed_update_guard(self) -> None:
        runner = FakeCodememoryRunner([source_task("task_1")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with (
                patch.object(task_graph_command, "make_oc_runner", return_value=runner),
                patch.object(
                    task_graph_command, "_write_path", return_value=write_path(root)
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    1,
                    task_graph_command.main(
                        ["project", "--scope", "example/repo", "--check", "--json"]
                    ),
                )
            self.assertEqual(
                "task_projection_drift", json.loads(output.getvalue())["reason_code"]
            )

            output = io.StringIO()
            with (
                patch.object(task_graph_command, "make_oc_runner", return_value=runner),
                patch.object(
                    task_graph_command, "_write_path", return_value=write_path(root)
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    0,
                    task_graph_command.main(
                        ["project", "--scope", "example/repo", "--apply", "--json"]
                    ),
                )
            self.assertTrue(json.loads(output.getvalue())["changed"])

            output = io.StringIO()
            with (
                patch.object(task_graph_command, "make_oc_runner", return_value=runner),
                patch.object(
                    task_graph_command, "_write_path", return_value=write_path(root)
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    0,
                    task_graph_command.main(
                        ["project", "--scope", "example/repo", "--check", "--json"]
                    ),
                )
            self.assertEqual(
                "task_projection_current", json.loads(output.getvalue())["reason_code"]
            )

            output = io.StringIO()
            with (
                patch.object(
                    task_graph_command, "_write_path", return_value=write_path(root)
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    1,
                    task_graph_command.main(
                        ["update", "task_1", "--subject", "tamper", "--json"]
                    ),
                )
            self.assertEqual(
                "task_managed_by_codememory",
                json.loads(output.getvalue())["reason_code"],
            )

    def test_cli_apply_preserves_destination_for_unsupported_blocked_by(self) -> None:
        runner = FakeCodememoryRunner(
            [source_task("task_1")],
            explicit_links=[("blocked-by", "task_1", "memory_1")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_raw_state(root, [local_task("existing")])
            before = path.read_bytes()
            output = io.StringIO()
            build_projection = Mock(
                side_effect=AssertionError("unsupported source must not project")
            )
            with (
                patch.object(task_graph_command, "make_oc_runner", return_value=runner),
                patch.object(
                    task_graph_command, "build_projection", build_projection
                ),
                patch.object(
                    task_graph_command, "_write_path", return_value=write_path(root)
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    1,
                    task_graph_command.main(
                        ["project", "--scope", "example/repo", "--apply", "--json"]
                    ),
                )
            build_projection.assert_not_called()
            payload = json.loads(output.getvalue())
            self.assertEqual(
                "task_projection_source_unsupported_edge", payload["reason_code"]
            )
            self.assertEqual(before, path.read_bytes())

    def test_workflow_preflight_blocks_execution_and_commands_return_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow_path = root / "workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "name": "projection-preflight",
                        "steps": [{"id": "one", "action": "run-fixed"}],
                    }
                ),
                encoding="utf-8",
            )
            state_path = root / "workflow-state.json"
            execute_steps = Mock()
            output = io.StringIO()
            with (
                patch.object(workflow_command, "DEFAULT_STATE_PATH", state_path),
                patch.object(
                    workflow_command,
                    "check_operation",
                    return_value={"allowed": True},
                ),
                patch.object(
                    workflow_command,
                    "task_graph_runtime_path",
                    side_effect=task_graph_runtime.TaskGraphStateError("tampered"),
                ),
                patch.object(workflow_command, "execute_steps", execute_steps),
                patch.object(
                    workflow_command, "entrypoint_model_routing", return_value={}
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    1,
                    workflow_command.main(
                        [
                            "run",
                            "--file",
                            str(workflow_path),
                            "--execute",
                            "--json",
                        ]
                    ),
                )
            execute_steps.assert_not_called()
            self.assertFalse(state_path.exists())
            self.assertEqual(
                "task_graph_state_invalid",
                json.loads(output.getvalue())["reason_code"],
            )

            output = io.StringIO()
            with (
                patch.object(
                    autopilot_command, "load_layered_config", return_value=({}, {})
                ),
                patch.object(
                    autopilot_command,
                    "resolve_write_path",
                    return_value=root / "opencode.json",
                ),
                patch.object(autopilot_command, "load_runtime", return_value={}),
                patch.object(
                    autopilot_command,
                    "task_graph_status_snapshot",
                    side_effect=task_graph_runtime.TaskGraphStateError("tampered"),
                ),
                patch.object(
                    autopilot_command, "entrypoint_model_routing", return_value={}
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(1, autopilot_command.main(["status", "--json"]))
            self.assertEqual(
                "task_graph_state_invalid",
                json.loads(output.getvalue())["reason_code"],
            )

            output = io.StringIO()
            with (
                patch.object(
                    start_work_command,
                    "read_runtime_state",
                    return_value=({}, root / "opencode.json"),
                ),
                patch.object(
                    start_work_command,
                    "task_graph_status_snapshot",
                    side_effect=task_graph_runtime.TaskGraphStateError("tampered"),
                ),
                patch.object(
                    start_work_command,
                    "decorate_report",
                    side_effect=lambda payload: payload,
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(1, start_work_command.main(["status", "--json"]))
            self.assertEqual(
                "task_graph_state_invalid",
                json.loads(output.getvalue())["reason_code"],
            )


if __name__ == "__main__":
    unittest.main()
