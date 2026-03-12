#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable

import fcntl


RUNTIME_ENV_VAR = "MY_OPENCODE_TASK_GRAPH_PATH"
LOCK_ENV_VAR = "MY_OPENCODE_TASK_GRAPH_LOCK_PATH"
RESERVATION_STATE_ENV_VAR = "MY_OPENCODE_RESERVATION_STATE_PATH"
FORMAT_VERSION = 1
TASK_STATUS = {"pending", "in_progress", "completed", "deleted", "skipped"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_override_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    if (
        value.startswith("{")
        or value.startswith("[")
        or "{" in value
        or "}" in value
        or "[" in value
        or "]" in value
    ):
        return None
    return Path(value).expanduser()


def runtime_path(write_path: Path) -> Path:
    override = _env_override_path(RUNTIME_ENV_VAR)
    if override is not None:
        return override
    return write_path.parent / "my_opencode" / "runtime" / "task_graph.json"


def lock_path(write_path: Path) -> Path:
    override = _env_override_path(LOCK_ENV_VAR)
    if override is not None:
        return override
    return runtime_path(write_path).with_suffix(".lock")


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            token = str(item).strip()
            if token:
                out.append(token)
        return out
    return []


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").replace("./", "", 1).strip()


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    normalized = _normalize_path(pattern)
    escaped = re.escape(normalized).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.compile(f"^{escaped}$")


def _matches_any(path: str, patterns: list[str]) -> bool:
    normalized = _normalize_path(path)
    for pattern in patterns:
        try:
            if _glob_to_regex(pattern).match(normalized):
                return True
        except re.error:
            continue
    return False


def _reservation_state_path() -> Path:
    override = _env_override_path(RESERVATION_STATE_ENV_VAR)
    if override is not None:
        return override
    return Path(".opencode/reservation-state.json")


def _load_reservation_state() -> dict[str, Any]:
    path = _reservation_state_path()
    if not path.exists():
        return {
            "reservationActive": False,
            "writerCount": 0,
            "ownPaths": [],
            "activePaths": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "reservationActive": bool(
            data.get("reservationActive", data.get("active", False))
        ),
        "writerCount": int(data.get("writerCount", data.get("writer_count", 0)) or 0),
        "ownPaths": _string_list(data.get("ownPaths") or data.get("own_paths") or []),
        "activePaths": _string_list(
            data.get("activePaths") or data.get("active_paths") or []
        ),
    }


def _task_reservation_paths(task: dict[str, Any]) -> list[str]:
    raw_metadata = task.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    return _string_list(
        metadata.get("reservation_paths") or metadata.get("write_paths") or []
    )


def _task_id(value: Any) -> str:
    token = str(value or "").strip()
    if token:
        return token
    return f"T-{uuid.uuid4().hex[:12]}"


def _normalize_task(raw: dict[str, Any]) -> dict[str, Any]:
    created_at = str(raw.get("created_at") or now_iso())
    updated_at = str(raw.get("updated_at") or created_at)
    status = str(raw.get("status") or "pending").strip().lower()
    if status not in TASK_STATUS:
        status = "pending"
    return {
        "id": _task_id(raw.get("id")),
        "subject": str(raw.get("subject") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "status": status,
        "activeForm": str(raw.get("activeForm") or "").strip(),
        "blockedBy": sorted(set(_string_list(raw.get("blockedBy")))),
        "blocks": sorted(set(_string_list(raw.get("blocks")))),
        "owner": str(raw.get("owner") or "").strip(),
        "metadata": raw.get("metadata")
        if isinstance(raw.get("metadata"), dict)
        else {},
        "completionGates": raw.get("completionGates")
        if isinstance(raw.get("completionGates"), dict)
        else {},
        "requiredArtifacts": _string_list(raw.get("requiredArtifacts")),
        "threadID": str(raw.get("threadID") or "").strip(),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _rebuild_blocks(tasks: list[dict[str, Any]]) -> None:
    by_id = {task["id"]: task for task in tasks}
    for task in tasks:
        task["blockedBy"] = [
            dep
            for dep in task.get("blockedBy", [])
            if dep in by_id and dep != task["id"]
        ]
        task["blocks"] = []
    for task in tasks:
        for dep in task["blockedBy"]:
            by_id[dep]["blocks"].append(task["id"])
    for task in tasks:
        task["blockedBy"] = sorted(set(task.get("blockedBy", [])))
        task["blocks"] = sorted(set(task.get("blocks", [])))


def normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    tasks_raw = payload.get("tasks")
    tasks: list[dict[str, Any]] = []
    if isinstance(tasks_raw, list):
        for item in tasks_raw:
            if isinstance(item, dict):
                tasks.append(_normalize_task(item))
    deduped: dict[str, dict[str, Any]] = {}
    for task in tasks:
        deduped[task["id"]] = task
    ordered = sorted(
        deduped.values(),
        key=lambda item: (item.get("created_at", ""), item.get("id", "")),
    )
    _rebuild_blocks(ordered)
    return {
        "format_version": FORMAT_VERSION,
        "updated_at": str(payload.get("updated_at") or now_iso()),
        "tasks": ordered,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(json.dumps(payload, indent=2) + "\n")
        tmp.flush()
        Path(tmp.name).replace(path)


@dataclass
class LockedState:
    state: dict[str, Any]
    runtime_path: Path


def with_locked_state(
    write_path: Path, mutate: Callable[[dict[str, Any]], dict[str, Any]]
) -> LockedState:
    runtime = runtime_path(write_path)
    lock = lock_path(write_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        if runtime.exists():
            try:
                raw = json.loads(runtime.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw = {}
        else:
            raw = {}
        state = normalize_state(raw)
        next_state = mutate(state)
        normalized = normalize_state(next_state)
        normalized["updated_at"] = now_iso()
        _atomic_write_json(runtime, normalized)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return LockedState(state=normalized, runtime_path=runtime)


def load_state(write_path: Path) -> LockedState:
    runtime = runtime_path(write_path)
    if runtime.exists():
        try:
            raw = json.loads(runtime.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
    else:
        raw = {}
    return LockedState(state=normalize_state(raw), runtime_path=runtime)


def ready_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {task["id"]: task for task in tasks}
    ready: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("status") != "pending":
            continue
        blocked_by = task.get("blockedBy", [])
        is_ready = True
        for dep in blocked_by:
            parent = by_id.get(dep)
            if not parent or parent.get("status") not in {
                "completed",
                "deleted",
                "skipped",
            }:
                is_ready = False
                break
        if is_ready:
            ready.append(task)
    return ready


def blocked_details(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {task["id"]: task for task in tasks}
    blocked: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("status") != "pending":
            continue
        blockers: list[dict[str, Any]] = []
        for dep in task.get("blockedBy", []):
            parent = by_id.get(dep)
            if not parent:
                blockers.append(
                    {
                        "task_id": dep,
                        "status": "missing",
                        "reason_code": "dependency_missing",
                    }
                )
                continue
            parent_status = str(parent.get("status") or "pending")
            parent_step_status = (
                str(parent.get("metadata", {}).get("step_status") or "").strip().lower()
            )
            if parent_status in {"completed", "deleted", "skipped"}:
                continue
            reason_code = {
                "pending": "dependency_pending",
                "in_progress": "dependency_in_progress",
            }.get(parent_status, "dependency_not_completed")
            if parent_step_status == "failed":
                reason_code = "dependency_failed"
            blockers.append(
                {
                    "task_id": dep,
                    "status": parent_status,
                    "step_status": parent_step_status,
                    "reason_code": reason_code,
                }
            )
        if blockers:
            strongest_reason = next(
                (
                    reason
                    for reason in [
                        "dependency_failed",
                        "dependency_in_progress",
                        "dependency_pending",
                        "dependency_missing",
                    ]
                    if any(item.get("reason_code") == reason for item in blockers)
                ),
                "dependency_not_completed",
            )
            blocked.append(
                {
                    "id": task["id"],
                    "reason_code": strongest_reason,
                    "blocked_by": blockers,
                }
            )
    return blocked


def reservation_blocked_details(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reservation_state = _load_reservation_state()
    if not reservation_state.get("reservationActive"):
        return []
    own_paths = _string_list(reservation_state.get("ownPaths") or [])
    active_paths = _string_list(reservation_state.get("activePaths") or [])
    blocked: list[dict[str, Any]] = []
    for task in ready_tasks(tasks):
        reservation_paths = _task_reservation_paths(task)
        if not reservation_paths:
            continue
        blockers: list[dict[str, Any]] = []
        if own_paths:
            uncovered = [
                path for path in reservation_paths if not _matches_any(path, own_paths)
            ]
            if uncovered:
                blockers.append(
                    {
                        "reason_code": "reservation_uncovered",
                        "paths": uncovered,
                    }
                )
        conflicting = [
            path
            for path in reservation_paths
            if _matches_any(path, active_paths) and not _matches_any(path, own_paths)
        ]
        if conflicting:
            blockers.append(
                {
                    "reason_code": "reservation_conflict",
                    "paths": conflicting,
                }
            )
        if blockers:
            strongest_reason = next(
                (
                    reason
                    for reason in ["reservation_conflict", "reservation_uncovered"]
                    if any(item.get("reason_code") == reason for item in blockers)
                ),
                blockers[0]["reason_code"],
            )
            blocked.append(
                {
                    "id": task["id"],
                    "reason_code": strongest_reason,
                    "blocked_by": blockers,
                }
            )
    return blocked


def runnable_lanes(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reservation_blocked_ids = {
        item.get("id")
        for item in reservation_blocked_details(tasks)
        if isinstance(item, dict)
    }
    ready = [
        task
        for task in ready_tasks(tasks)
        if task.get("id") not in reservation_blocked_ids
    ]
    by_id = {task["id"]: task for task in tasks}
    pending_ids = {
        str(task.get("id") or "") for task in tasks if task.get("status") == "pending"
    }

    def dependencies_satisfied(task_id: str, virtual_done: set[str]) -> bool:
        task = by_id.get(task_id, {})
        for dep in task.get("blockedBy", []):
            if dep in virtual_done:
                continue
            parent = by_id.get(dep)
            if not parent or parent.get("status") not in {
                "completed",
                "deleted",
                "skipped",
            }:
                return False
        return True

    lanes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in ready:
        root_id = str(root.get("id") or "")
        if not root_id or root_id in seen:
            continue
        stack = [root_id]
        virtual_done = {root_id}
        lane_task_ids: list[str] = []
        while stack:
            current = stack.pop()
            if current in seen or current not in pending_ids:
                continue
            seen.add(current)
            lane_task_ids.append(current)
            current_task = by_id.get(current, {})
            dependents = [
                dep
                for dep in current_task.get("blocks", [])
                if dep in pending_ids
                and dep not in seen
                and dependencies_satisfied(dep, virtual_done)
            ]
            for dep in dependents:
                virtual_done.add(dep)
                stack.append(dep)
        if lane_task_ids:
            lanes.append(
                {
                    "lane_id": f"lane-{len(lanes) + 1}",
                    "root_task_id": root_id,
                    "task_ids": lane_task_ids,
                    "ready_now": [root_id],
                    "depth": len(lane_task_ids),
                }
            )
    return lanes


def graph_snapshot(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    reservation_blocked = reservation_blocked_details(tasks)
    ready = [
        task
        for task in ready_tasks(tasks)
        if task.get("id") not in {item.get("id") for item in reservation_blocked}
    ]
    blocked = blocked_details(tasks) + reservation_blocked
    lanes = runnable_lanes(tasks)
    return {
        "ready": ready,
        "ready_count": len(ready),
        "blocked_count": len(blocked),
        "lane_count": len(lanes),
        "runnable_lanes": lanes,
        "blocked": blocked,
    }
