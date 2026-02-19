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

from config_layering import resolve_write_path  # type: ignore  # noqa: E402
from task_graph_runtime import (  # type: ignore  # noqa: E402
    TASK_STATUS,
    load_state,
    now_iso,
    ready_tasks,
    with_locked_state,
)


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


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
    write_path = resolve_write_path()

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        tasks = [item for item in state.get("tasks", []) if isinstance(item, dict)]
        task = {
            "id": args.id.strip() if args.id else "",
            "subject": subject,
            "description": (args.description or "").strip(),
            "status": "pending",
            "activeForm": (args.active_form or "").strip(),
            "blockedBy": _csv(args.blocked_by),
            "blocks": [],
            "owner": (args.owner or "").strip(),
            "metadata": {},
            "threadID": (args.thread_id or "").strip(),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        tasks.append(task)
        state["tasks"] = tasks
        return state

    locked = with_locked_state(write_path, mutate)
    created = locked.state.get("tasks", [])[-1] if locked.state.get("tasks") else {}
    return {
        "result": "PASS",
        "reason_code": "task_created",
        "task": created,
        "runtime_path": str(locked.runtime_path),
    }


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    locked = load_state(resolve_write_path())
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
    locked = load_state(resolve_write_path())
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
            args.thread_id,
        ]
    ):
        return {
            "result": "FAIL",
            "reason_code": "task_update_noop",
            "detail": "provide at least one update field",
        }

    write_path = resolve_write_path()

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
        if args.thread_id:
            task["threadID"] = args.thread_id.strip()
        task["updated_at"] = now_iso()
        return state

    before = load_state(write_path)
    if not _get_task(before.state, args.id):
        return {
            "result": "FAIL",
            "reason_code": "task_not_found",
            "detail": f"task id not found: {args.id}",
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


def command_ready(args: argparse.Namespace) -> dict[str, Any]:
    locked = load_state(resolve_write_path())
    tasks = [item for item in locked.state.get("tasks", []) if isinstance(item, dict)]
    ready = ready_tasks(tasks)
    return {
        "result": "PASS",
        "reason_code": "task_ready_list",
        "count": len(ready),
        "tasks": ready,
        "runtime_path": str(locked.runtime_path),
    }


def command_doctor(args: argparse.Namespace) -> dict[str, Any]:
    locked = load_state(resolve_write_path())
    tasks = [item for item in locked.state.get("tasks", []) if isinstance(item, dict)]
    by_id = {str(task.get("id")): task for task in tasks}
    problems: list[str] = []
    for task in tasks:
        for dep in task.get("blockedBy", []):
            if dep not in by_id:
                problems.append(f"task {task.get('id')} blockedBy missing task {dep}")
    return {
        "result": "PASS" if not problems else "FAIL",
        "reason_code": "task_graph_healthy"
        if not problems
        else "task_graph_invalid_dependencies",
        "problems": problems,
        "task_count": len(tasks),
        "ready_count": len(ready_tasks(tasks)),
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
    update.add_argument("--json", action="store_true")

    ready = sub.add_parser("ready", help="List dependency-unblocked tasks")
    ready.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="Validate task graph integrity")
    doctor.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    if command == "create":
        payload = command_create(args)
    elif command == "list":
        payload = command_list(args)
    elif command == "get":
        payload = command_get(args)
    elif command == "update":
        payload = command_update(args)
    elif command == "ready":
        payload = command_ready(args)
    elif command == "doctor":
        payload = command_doctor(args)
    else:
        parser.print_help()
        return 2
    return _json_or_human(payload, bool(getattr(args, "json", False)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
