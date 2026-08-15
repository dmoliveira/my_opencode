#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from codememory_task_graph_projection import (  # type: ignore  # noqa: E402
    ProjectionError,
    apply_projection,
    build_projection,
    check_projection,
    default_oc_bin,
    default_oc_config,
    load_source_snapshot,
    make_oc_runner,
    projection_local_health,
)
from config_layering import resolve_write_path  # type: ignore  # noqa: E402
from task_graph_runtime import (  # type: ignore  # noqa: E402
    TASK_STATUS,
    ManagedTaskMutationError,
    TaskGraphStateError,
    graph_snapshot,
    is_codememory_managed,
    load_state,
    load_strict_state,
    now_iso,
    runtime_path,
    with_locked_state,
)


def _write_path() -> Path:
    def valid_path_text(text: str) -> bool:
        return all(token not in text for token in ("{", "}", "[", "]"))

    value = resolve_write_path()
    if isinstance(value, Path):
        candidate = str(value)
        if valid_path_text(candidate):
            return value
    if isinstance(value, str) and value.strip():
        candidate = value.strip()
        if valid_path_text(candidate):
            return Path(candidate).expanduser()
    return Path("~/.config/opencode/opencode.json").expanduser()


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _metadata_payload(args: argparse.Namespace) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    reservation_paths = _csv(getattr(args, "reservation_paths", ""))
    if reservation_paths:
        metadata["reservation_paths"] = reservation_paths
    return metadata


def _get_task(state: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for task in state.get("tasks", []):
        if isinstance(task, dict) and str(task.get("id")) == task_id:
            return task
    return None


def _json_or_human(payload: dict[str, Any], json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1
    print(f"result: {payload.get('result')}")
    print(f"reason_code: {payload.get('reason_code')}")
    if "detail" in payload and payload.get("detail"):
        print(f"detail: {payload.get('detail')}")
    if "task" in payload and isinstance(payload.get("task"), dict):
        task = payload["task"]
        print(f"task: {task.get('id')} [{task.get('status')}] {task.get('subject')}")
    if "count" in payload:
        print(f"count: {payload.get('count')}")
    return 0 if payload.get("result") == "PASS" else 1


def command_create(args: argparse.Namespace) -> dict[str, Any]:
    subject = (args.subject or "").strip()
    if not subject:
        return {
            "result": "FAIL",
            "reason_code": "task_subject_required",
            "detail": "provide --subject for task creation",
        }
    write_path = _write_path()
    requested_id = args.id.strip() if args.id else ""
    duplicate_id = False

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal duplicate_id
        tasks = [item for item in state.get("tasks", []) if isinstance(item, dict)]
        if requested_id and _get_task(state, requested_id):
            duplicate_id = True
            return state
        task = {
            "id": requested_id,
            "subject": subject,
            "description": (args.description or "").strip(),
            "status": "pending",
            "activeForm": (args.active_form or "").strip(),
            "blockedBy": _csv(args.blocked_by),
            "blocks": [],
            "owner": (args.owner or "").strip(),
            "metadata": _metadata_payload(args),
            "threadID": (args.thread_id or "").strip(),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        tasks.append(task)
        state["tasks"] = tasks
        return state

    locked = with_locked_state(write_path, mutate)
    if duplicate_id:
        return {
            "result": "FAIL",
            "reason_code": "task_id_exists",
            "detail": f"task id already exists: {requested_id}",
            "runtime_path": str(locked.runtime_path),
        }
    created = locked.state.get("tasks", [])[-1] if locked.state.get("tasks") else {}
    return {
        "result": "PASS",
        "reason_code": "task_created",
        "task": created,
        "runtime_path": str(locked.runtime_path),
    }


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    locked = load_state(_write_path())
    tasks = [item for item in locked.state.get("tasks", []) if isinstance(item, dict)]
    status_filter = (args.status or "").strip().lower()
    if status_filter:
        tasks = [task for task in tasks if str(task.get("status")) == status_filter]
    return {
        "result": "PASS",
        "reason_code": "task_list",
        "count": len(tasks),
        "tasks": tasks,
        "runtime_path": str(locked.runtime_path),
    }


def command_get(args: argparse.Namespace) -> dict[str, Any]:
    locked = load_state(_write_path())
    task = _get_task(locked.state, args.id)
    if not task:
        return {
            "result": "FAIL",
            "reason_code": "task_not_found",
            "detail": f"task id not found: {args.id}",
            "runtime_path": str(locked.runtime_path),
        }
    return {
        "result": "PASS",
        "reason_code": "task_found",
        "task": task,
        "runtime_path": str(locked.runtime_path),
    }


def command_update(args: argparse.Namespace) -> dict[str, Any]:
    if args.status and args.status not in TASK_STATUS:
        return {
            "result": "FAIL",
            "reason_code": "task_status_invalid",
            "detail": f"status must be one of: {', '.join(sorted(TASK_STATUS))}",
        }
    if not any(
        [
            args.status,
            args.subject,
            args.description,
            args.owner,
            args.active_form,
            args.blocked_by,
            args.reservation_paths,
            args.thread_id,
        ]
    ):
        return {
            "result": "FAIL",
            "reason_code": "task_update_noop",
            "detail": "provide at least one update field",
        }

    write_path = _write_path()

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        task = _get_task(state, args.id)
        if not task:
            return state
        if args.status:
            task["status"] = args.status
        if args.subject:
            task["subject"] = args.subject.strip()
        if args.description:
            task["description"] = args.description.strip()
        if args.owner:
            task["owner"] = args.owner.strip()
        if args.active_form:
            task["activeForm"] = args.active_form.strip()
        if args.blocked_by is not None:
            task["blockedBy"] = _csv(args.blocked_by)
        if getattr(args, "reservation_paths", None) is not None:
            raw_metadata = task.get("metadata")
            metadata: dict[str, Any] = (
                raw_metadata if isinstance(raw_metadata, dict) else {}
            )
            reservation_paths = _csv(args.reservation_paths)
            if reservation_paths:
                metadata["reservation_paths"] = reservation_paths
            else:
                metadata.pop("reservation_paths", None)
            task["metadata"] = metadata
        if args.thread_id:
            task["threadID"] = args.thread_id.strip()
        task["updated_at"] = now_iso()
        return state

    before = load_state(write_path)
    existing_task = _get_task(before.state, args.id)
    if not existing_task:
        return {
            "result": "FAIL",
            "reason_code": "task_not_found",
            "detail": f"task id not found: {args.id}",
            "runtime_path": str(before.runtime_path),
        }
    if is_codememory_managed(existing_task):
        return {
            "result": "FAIL",
            "reason_code": "task_managed_by_codememory",
            "detail": "run Codememory commands and refresh the projection instead",
            "runtime_path": str(before.runtime_path),
        }
    locked = with_locked_state(write_path, mutate)
    task = _get_task(locked.state, args.id)
    return {
        "result": "PASS",
        "reason_code": "task_updated",
        "task": task,
        "runtime_path": str(locked.runtime_path),
    }


def command_project(args: argparse.Namespace) -> dict[str, Any]:
    config_path = (
        Path(args.codememory_config).expanduser()
        if args.codememory_config
        else default_oc_config()
    )
    runner = make_oc_runner(
        oc_bin=(args.oc_bin or default_oc_bin()).strip(),
        config_path=config_path,
        cwd=Path.cwd(),
    )
    snapshot = load_source_snapshot(runner, args.scope)
    projection = build_projection(snapshot)
    write_path = _write_path()
    if args.check:
        drift = check_projection(write_path, projection)
        current = not drift["drifted"]
        return {
            "result": "PASS" if current else "FAIL",
            "reason_code": "task_projection_current"
            if current
            else "task_projection_drift",
            "scope_key": projection.scope_key,
            "revision": projection.revision,
            "managed_task_count": len(projection.tasks),
            "changed": False,
            "drift": drift,
            "runtime_path": str(runtime_path(write_path)),
        }
    drift, changed, runtime = apply_projection(write_path, projection)
    return {
        "result": "PASS",
        "reason_code": "task_projection_applied"
        if changed
        else "task_projection_current",
        "scope_key": projection.scope_key,
        "revision": projection.revision,
        "managed_task_count": len(projection.tasks),
        "changed": changed,
        "drift": drift,
        "runtime_path": str(runtime),
    }


def command_ready(args: argparse.Namespace) -> dict[str, Any]:
    locked = load_state(_write_path())
    tasks = [item for item in locked.state.get("tasks", []) if isinstance(item, dict)]
    snapshot = graph_snapshot(tasks)
    return {
        "result": "PASS",
        "reason_code": "task_ready_list",
        "count": snapshot["ready_count"],
        "tasks": snapshot["ready"],
        "runnable_lanes": snapshot["runnable_lanes"],
        "blocked": snapshot["blocked"],
        "summary": {
            "ready_count": snapshot["ready_count"],
            "blocked_count": snapshot["blocked_count"],
            "lane_count": snapshot["lane_count"],
        },
        "runtime_path": str(locked.runtime_path),
    }


def command_doctor(args: argparse.Namespace) -> dict[str, Any]:
    locked = load_strict_state(_write_path())
    tasks = [item for item in locked.state.get("tasks", []) if isinstance(item, dict)]
    raw_tasks = [
        item for item in locked.raw_state.get("tasks", []) if isinstance(item, dict)
    ]
    raw_ids = {str(task.get("id")) for task in raw_tasks}
    problems: list[str] = []
    for task in raw_tasks:
        for dep in task.get("blockedBy", []):
            if dep not in raw_ids:
                problems.append(f"task {task.get('id')} blockedBy missing task {dep}")
    projection = projection_local_health(locked.state)
    problems.extend(str(problem) for problem in projection.get("problems", []))
    snapshot = graph_snapshot(tasks)
    if not problems:
        reason_code = "task_graph_healthy"
    elif projection.get("present") and not projection.get("healthy"):
        reason_code = "task_graph_projection_invalid"
    else:
        reason_code = "task_graph_invalid_dependencies"
    return {
        "result": "PASS" if not problems else "FAIL",
        "reason_code": reason_code,
        "problems": problems,
        "task_count": len(tasks),
        "ready_count": snapshot["ready_count"],
        "lane_count": snapshot["lane_count"],
        "blocked_count": snapshot["blocked_count"],
        "projection": projection,
        "runtime_path": str(locked.runtime_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="/task",
        description="Persistent dependency-aware task graph commands",
    )
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create", help="Create a task")
    create.add_argument("--id", default="")
    create.add_argument("--subject", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--owner", default="")
    create.add_argument("--thread-id", default="")
    create.add_argument("--active-form", default="")
    create.add_argument("--blocked-by", default="")
    create.add_argument("--reservation-paths", default="")
    create.add_argument("--json", action="store_true")

    list_cmd = sub.add_parser("list", help="List tasks")
    list_cmd.add_argument("--status", default="")
    list_cmd.add_argument("--json", action="store_true")

    get_cmd = sub.add_parser("get", help="Get one task")
    get_cmd.add_argument("id")
    get_cmd.add_argument("--json", action="store_true")

    update = sub.add_parser("update", help="Update task fields")
    update.add_argument("id")
    update.add_argument("--status", default="")
    update.add_argument("--subject", default="")
    update.add_argument("--description", default="")
    update.add_argument("--owner", default="")
    update.add_argument("--thread-id", default="")
    update.add_argument("--active-form", default="")
    update.add_argument("--blocked-by")
    update.add_argument("--reservation-paths")
    update.add_argument("--json", action="store_true")

    project = sub.add_parser(
        "project", help="Check or apply the one-way Codememory task projection"
    )
    project.add_argument("--scope", required=True)
    project.add_argument("--codememory-config", default="")
    project.add_argument("--oc-bin", default="")
    project_mode = project.add_mutually_exclusive_group(required=True)
    project_mode.add_argument("--check", action="store_true")
    project_mode.add_argument("--apply", action="store_true")
    project.add_argument("--json", action="store_true")

    ready = sub.add_parser("ready", help="List dependency-unblocked tasks")
    ready.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="Validate task graph integrity")
    doctor.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    try:
        if command == "create":
            payload = command_create(args)
        elif command == "list":
            payload = command_list(args)
        elif command == "get":
            payload = command_get(args)
        elif command == "update":
            payload = command_update(args)
        elif command == "project":
            payload = command_project(args)
        elif command == "ready":
            payload = command_ready(args)
        elif command == "doctor":
            payload = command_doctor(args)
        else:
            parser.print_help()
            return 2
    except ProjectionError as exc:
        payload = {
            "result": "FAIL",
            "reason_code": exc.reason_code,
            "detail": exc.detail,
        }
    except TaskGraphStateError as exc:
        payload = {
            "result": "FAIL",
            "reason_code": "task_projection_destination_invalid"
            if command == "project"
            else "task_graph_state_invalid",
            "detail": str(exc),
        }
    except ManagedTaskMutationError as exc:
        payload = {
            "result": "FAIL",
            "reason_code": "task_managed_by_codememory",
            "detail": str(exc),
        }
    return _json_or_human(payload, bool(getattr(args, "json", False)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
