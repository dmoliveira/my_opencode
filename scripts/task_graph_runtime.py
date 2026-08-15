#!/usr/bin/env python3

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

RUNTIME_ENV_VAR = "MY_OPENCODE_TASK_GRAPH_PATH"
LOCK_ENV_VAR = "MY_OPENCODE_TASK_GRAPH_LOCK_PATH"
RESERVATION_STATE_ENV_VAR = "MY_OPENCODE_RESERVATION_STATE_PATH"
FORMAT_VERSION = 1
TASK_STATUS = {
    "pending",
    "in_progress",
    "blocked",
    "canceled",
    "completed",
    "failed",
    "deleted",
    "skipped",
}
PROJECTION_SCHEMA_VERSION = 1
SUCCESSFUL_TERMINAL_STATUS = {"completed", "deleted", "skipped"}


class TaskGraphStateError(RuntimeError):
    pass


class ManagedTaskMutationError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_override_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    if any(token in value for token in "{}[]"):
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


def is_codememory_managed(task: dict[str, Any]) -> bool:
    metadata = task.get("metadata")
    if not isinstance(metadata, dict):
        return False
    codememory = metadata.get("codememory")
    return isinstance(codememory, dict) and codememory.get("managed") is True


def projection_task_semantic(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(task.get("id") or ""),
        "subject": str(task.get("subject") or ""),
        "description": str(task.get("description") or ""),
        "status": str(task.get("status") or ""),
        "activeForm": str(task.get("activeForm") or ""),
        "blockedBy": sorted(set(_string_list(task.get("blockedBy")))),
        "owner": str(task.get("owner") or ""),
        "metadata": task.get("metadata")
        if isinstance(task.get("metadata"), dict)
        else {},
        "completionGates": task.get("completionGates")
        if isinstance(task.get("completionGates"), dict)
        else {},
        "requiredArtifacts": _string_list(task.get("requiredArtifacts")),
        "threadID": str(task.get("threadID") or ""),
        "created_at": str(task.get("created_at") or ""),
        "updated_at": str(task.get("updated_at") or ""),
    }


def _canonical_value(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    return value


def projection_fingerprint(scope: str, tasks: list[dict[str, Any]]) -> str:
    payload = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "scope_key": scope,
        "tasks": sorted(
            (projection_task_semantic(task) for task in tasks),
            key=lambda task: task["id"],
        ),
    }
    canonical = json.dumps(
        _canonical_value(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def projection_health(state: dict[str, Any]) -> dict[str, Any]:
    header = state.get("projection")
    managed = [
        task
        for task in state.get("tasks", [])
        if isinstance(task, dict) and is_codememory_managed(task)
    ]
    if header is None:
        problems = (
            ["Codememory-managed tasks exist without projection metadata"]
            if managed
            else []
        )
        return {"present": False, "healthy": not problems, "problems": problems}
    if not isinstance(header, dict):
        return {
            "present": True,
            "healthy": False,
            "problems": ["projection metadata is not an object"],
        }

    scope = str(header.get("scope_key") or "")
    problems: list[str] = []
    observed_fingerprint = projection_fingerprint(scope, managed) if scope else ""
    if header.get("schema_version") != PROJECTION_SCHEMA_VERSION:
        problems.append("projection schema version is unsupported")
    if header.get("source") != "codememory":
        problems.append("projection source is invalid")
    if not scope:
        problems.append("projection scope is missing")
    for task in managed:
        task_id = str(task.get("id") or "")
        metadata = task.get("metadata", {}).get("codememory", {})
        if metadata.get("schema_version") != PROJECTION_SCHEMA_VERSION:
            problems.append(
                f"managed task {task_id} has unsupported projection metadata"
            )
        if metadata.get("scope_key") != scope:
            problems.append(f"managed task {task_id} has the wrong projection scope")
        if metadata.get("task_id") != task_id:
            problems.append(f"managed task {task_id} has inconsistent source identity")
    if header.get("fingerprint") != observed_fingerprint:
        problems.append("projection fingerprint does not match managed tasks")
    if header.get("revision") != f"sha256:{observed_fingerprint}":
        problems.append("projection revision does not match managed tasks")
    if header.get("managed_task_count") != len(managed):
        problems.append("projection managed task count is stale")
    return {
        "present": True,
        "healthy": not problems,
        "scope_key": scope,
        "revision": str(header.get("revision") or ""),
        "managed_task_count": len(managed),
        "problems": problems,
    }


def _validate_projection_health(state: dict[str, Any]) -> None:
    health = projection_health(state)
    if not health["healthy"]:
        raise TaskGraphStateError("; ".join(health["problems"]))


def _managed_task_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(task.get("id") or ""): projection_task_semantic(task)
        for task in state.get("tasks", [])
        if isinstance(task, dict) and is_codememory_managed(task)
    }


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
    normalized = {
        "format_version": FORMAT_VERSION,
        "updated_at": str(payload.get("updated_at") or now_iso()),
        "tasks": ordered,
    }
    projection = payload.get("projection")
    if isinstance(projection, dict):
        normalized["projection"] = dict(projection)
    return normalized


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(json.dumps(payload, indent=2) + "\n")
        tmp.flush()
        Path(tmp.name).replace(path)


def _atomic_write_json_durable(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(json.dumps(payload, indent=2) + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(temp_path, path)
        temp_path = None
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


_STATE_KEYS = {"format_version", "updated_at", "tasks", "projection"}
_TASK_KEYS = {
    "id",
    "subject",
    "description",
    "status",
    "activeForm",
    "blockedBy",
    "blocks",
    "owner",
    "metadata",
    "completionGates",
    "requiredArtifacts",
    "threadID",
    "created_at",
    "updated_at",
}
_PROJECTION_KEYS = {
    "schema_version",
    "source",
    "scope_key",
    "revision",
    "fingerprint",
    "managed_task_count",
    "projected_at",
}


def _read_raw_state(runtime: Path, *, strict: bool) -> dict[str, Any]:
    if not runtime.exists():
        return {}
    try:
        raw = json.loads(runtime.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        if strict:
            raise TaskGraphStateError("task graph state is unreadable") from exc
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise TaskGraphStateError("task graph state must be an object")
        return {}
    return raw


def _validate_strict_raw_state(raw: dict[str, Any]) -> None:
    if not raw:
        return
    unknown_state = sorted(set(raw) - _STATE_KEYS)
    if unknown_state:
        raise TaskGraphStateError(
            f"task graph state has unknown fields: {', '.join(unknown_state)}"
        )
    if (
        isinstance(raw.get("format_version"), bool)
        or raw.get("format_version") != FORMAT_VERSION
    ):
        raise TaskGraphStateError("task graph format_version is unsupported")
    if not isinstance(raw.get("updated_at"), str):
        raise TaskGraphStateError("task graph updated_at must be a string")
    tasks = raw.get("tasks")
    if not isinstance(tasks, list):
        raise TaskGraphStateError("task graph tasks must be an array")
    seen: set[str] = set()
    for item in tasks:
        if not isinstance(item, dict):
            raise TaskGraphStateError("task graph task entries must be objects")
        unknown_task = sorted(set(item) - _TASK_KEYS)
        if unknown_task:
            raise TaskGraphStateError(
                f"task graph task has unknown fields: {', '.join(unknown_task)}"
            )
        task_id = item.get("id")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or task_id != task_id.strip()
        ):
            raise TaskGraphStateError("task graph task id must be non-empty")
        if task_id in seen:
            raise TaskGraphStateError(f"task graph has duplicate task id: {task_id}")
        seen.add(task_id)
        status = item.get("status", "pending")
        if not isinstance(status, str) or status not in TASK_STATUS:
            raise TaskGraphStateError(
                f"task graph task {task_id} has unsupported status"
            )
        blocked_by = item.get("blockedBy", [])
        if not isinstance(blocked_by, list) or any(
            not isinstance(value, str) or not value.strip() or value != value.strip()
            for value in blocked_by
        ):
            raise TaskGraphStateError(
                f"task graph task {task_id} has invalid blockedBy"
            )
        if len(blocked_by) != len(set(blocked_by)) or task_id in blocked_by:
            raise TaskGraphStateError(
                f"task graph task {task_id} has duplicate or self dependencies"
            )
        blocks = item.get("blocks", [])
        if not isinstance(blocks, list) or any(
            not isinstance(value, str) or not value.strip() or value != value.strip()
            for value in blocks
        ):
            raise TaskGraphStateError(f"task graph task {task_id} has invalid blocks")
        for field in (
            "subject",
            "description",
            "activeForm",
            "owner",
            "threadID",
            "created_at",
            "updated_at",
        ):
            if field in item and not isinstance(item[field], str):
                raise TaskGraphStateError(
                    f"task graph task {task_id} has invalid {field}"
                )
        for field in ("metadata", "completionGates"):
            if field in item and not isinstance(item[field], dict):
                raise TaskGraphStateError(
                    f"task graph task {task_id} has invalid {field}"
                )
        if "requiredArtifacts" in item and (
            not isinstance(item["requiredArtifacts"], list)
            or any(
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                for value in item["requiredArtifacts"]
            )
        ):
            raise TaskGraphStateError(
                f"task graph task {task_id} has invalid requiredArtifacts"
            )
    projection = raw.get("projection")
    if projection is None:
        return
    if not isinstance(projection, dict):
        raise TaskGraphStateError("task graph projection must be an object")
    unknown_projection = sorted(set(projection) - _PROJECTION_KEYS)
    if unknown_projection:
        raise TaskGraphStateError(
            "task graph projection has unknown fields: " + ", ".join(unknown_projection)
        )
    if (
        projection.get("schema_version") != PROJECTION_SCHEMA_VERSION
        or projection.get("source") != "codememory"
    ):
        raise TaskGraphStateError("task graph projection metadata is unsupported")
    for field in ("scope_key", "revision", "fingerprint", "projected_at"):
        if not isinstance(projection.get(field), str) or not projection[field]:
            raise TaskGraphStateError(
                f"task graph projection {field} must be non-empty"
            )
    managed_task_count = projection.get("managed_task_count")
    if (
        isinstance(managed_task_count, bool)
        or not isinstance(managed_task_count, int)
        or managed_task_count < 0
    ):
        raise TaskGraphStateError(
            "task graph projection managed_task_count must be an integer"
        )


def _validate_runtime_references(raw: dict[str, Any]) -> None:
    tasks = raw.get("tasks", [])
    if not isinstance(tasks, list):
        return
    task_ids = {
        item["id"]
        for item in tasks
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for item in tasks:
        if not isinstance(item, dict):
            continue
        missing = sorted(set(item.get("blockedBy", [])) - task_ids)
        if missing:
            raise TaskGraphStateError(
                f"task graph task {item.get('id')} references missing dependencies: "
                + ", ".join(missing)
            )


@dataclass
class LockedState:
    state: dict[str, Any]
    runtime_path: Path
    changed: bool = False


@dataclass
class StrictState:
    raw_state: dict[str, Any]
    state: dict[str, Any]
    runtime_path: Path
    changed: bool = False


def with_locked_state(
    write_path: Path, mutate: Callable[[dict[str, Any]], dict[str, Any]]
) -> LockedState:
    runtime = runtime_path(write_path)
    lock = lock_path(write_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        raw = _read_raw_state(runtime, strict=True)
        _validate_strict_raw_state(raw)
        _validate_runtime_references(raw)
        current = normalize_state(raw)
        _validate_projection_health(current)
        managed_before = _managed_task_map(current)
        next_state = mutate(copy.deepcopy(current))
        normalized = normalize_state(next_state)
        _validate_strict_raw_state(normalized)
        _validate_runtime_references(normalized)
        if _managed_task_map(normalized) != managed_before:
            raise ManagedTaskMutationError(
                "Codememory-managed tasks can only change through projection"
            )
        _validate_projection_health(normalized)
        changed = normalized != current
        if changed:
            normalized["updated_at"] = now_iso()
            _atomic_write_json(runtime, normalized)
        else:
            normalized = current
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return LockedState(state=normalized, runtime_path=runtime, changed=changed)


def load_state(write_path: Path) -> LockedState:
    runtime = runtime_path(write_path)
    raw = _read_raw_state(runtime, strict=True)
    _validate_strict_raw_state(raw)
    _validate_runtime_references(raw)
    state = normalize_state(raw)
    _validate_projection_health(state)
    return LockedState(state=state, runtime_path=runtime)


def load_strict_state(write_path: Path) -> StrictState:
    runtime = runtime_path(write_path)
    raw = _read_raw_state(runtime, strict=True)
    _validate_strict_raw_state(raw)
    return StrictState(
        raw_state=raw,
        state=normalize_state(raw),
        runtime_path=runtime,
    )


def with_locked_projection_state(
    write_path: Path,
    mutate: Callable[[StrictState], dict[str, Any]],
) -> StrictState:
    runtime = runtime_path(write_path)
    lock = lock_path(write_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        raw = _read_raw_state(runtime, strict=True)
        _validate_strict_raw_state(raw)
        current = normalize_state(raw)
        strict_state = StrictState(
            raw_state=raw,
            state=copy.deepcopy(current),
            runtime_path=runtime,
        )
        next_state = normalize_state(mutate(strict_state))
        _validate_strict_raw_state(next_state)
        _validate_runtime_references(next_state)
        _validate_projection_health(next_state)
        changed = next_state != current
        if changed:
            next_state["updated_at"] = now_iso()
            _atomic_write_json_durable(runtime, next_state)
        else:
            next_state = current
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return StrictState(
        raw_state=raw,
        state=next_state,
        runtime_path=runtime,
        changed=changed,
    )


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
            if not parent or parent.get("status") not in SUCCESSFUL_TERMINAL_STATUS:
                is_ready = False
                break
        if is_ready:
            ready.append(task)
    return ready


def blocked_details(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {task["id"]: task for task in tasks}
    blocked: list[dict[str, Any]] = []
    for task in tasks:
        task_status = task.get("status")
        if task_status == "blocked":
            blocked.append(
                {
                    "id": task["id"],
                    "reason_code": "codememory_blocked",
                    "blocked_by": [],
                }
            )
            continue
        if task_status != "pending":
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
                "blocked": "dependency_blocked",
                "canceled": "dependency_canceled",
                "failed": "dependency_failed",
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
                        "dependency_canceled",
                        "dependency_blocked",
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
            if not parent or parent.get("status") not in SUCCESSFUL_TERMINAL_STATUS:
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
