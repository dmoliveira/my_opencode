#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable

import fcntl


RUNTIME_ENV_VAR = "MY_OPENCODE_TASK_GRAPH_PATH"
LOCK_ENV_VAR = "MY_OPENCODE_TASK_GRAPH_LOCK_PATH"
FORMAT_VERSION = 1
TASK_STATUS = {"pending", "in_progress", "completed", "deleted"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_override_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    if value.startswith("{") or value.startswith("["):
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
            if not parent or parent.get("status") not in {"completed", "deleted"}:
                is_ready = False
                break
        if is_ready:
            ready.append(task)
    return ready
