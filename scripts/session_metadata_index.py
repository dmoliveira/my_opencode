#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from config_layering import load_layered_config  # type: ignore


class SessionIndexError(ValueError):
    pass


DEFAULT_INDEX_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SESSION_INDEX_PATH", "~/.config/opencode/sessions/index.json"
    )
).expanduser()


def _parse_iso(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _session_id(timestamp: str, cwd: str) -> str:
    explicit = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    if explicit:
        return explicit
    ts = _parse_iso(timestamp) or _utc_now()
    return f"{cwd}::{ts.isoformat()}::{uuid.uuid4().hex}"


def _load_policy() -> dict[str, int]:
    policy = {
        "max_sessions": 120,
        "max_age_days": 30,
        "max_events_per_session": 24,
        "max_reasons_per_session": 12,
        "max_plan_ids_per_session": 12,
    }
    try:
        config, _ = load_layered_config()
    except Exception:
        return policy
    section = config.get("session_index")
    if not isinstance(section, dict):
        return policy
    for key in policy:
        value = section.get(key)
        if isinstance(value, int) and value > 0:
            policy[key] = value
    return policy


@contextmanager
def _index_write_lock(path: Path) -> Iterator[None]:
    """Serialize the sidecar load-modify-write transaction across supported hosts."""
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write("0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "generated_at": None, "sessions": []}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SessionIndexError(f"session index is malformed; preserved at {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SessionIndexError(f"session index root must be an object; preserved at {path}")
    raw_sessions = loaded.get("sessions")
    sessions = raw_sessions if isinstance(raw_sessions, list) else []
    return {
        "version": 1,
        "generated_at": loaded.get("generated_at"),
        "sessions": [item for item in sessions if isinstance(item, dict)],
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist sidecar JSON without exposing a partially written index."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _event_from_digest(digest: dict[str, Any]) -> dict[str, Any]:
    raw_git = digest.get("git")
    raw_plan = digest.get("plan_execution")
    git: dict[str, Any] = raw_git if isinstance(raw_git, dict) else {}
    plan: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
    return {
        "timestamp": digest.get("timestamp"),
        "reason": digest.get("reason"),
        "changes": git.get("status_count", 0),
        "branch": git.get("branch"),
        "plan_status": plan.get("status"),
        "plan_id": plan.get("plan_id"),
    }


def _prune_sessions(
    sessions: list[dict[str, Any]], policy: dict[str, int]
) -> list[dict[str, Any]]:
    cutoff = _utc_now() - timedelta(days=policy["max_age_days"])
    kept: list[dict[str, Any]] = []
    for session in sessions:
        parsed = _parse_iso(str(session.get("last_event_at") or ""))
        if parsed is None or parsed >= cutoff:
            kept.append(session)
    kept.sort(key=lambda item: str(item.get("last_event_at") or ""), reverse=True)
    return kept[: policy["max_sessions"]]


def update_session_index(
    digest: dict[str, Any], path: Path | None = None
) -> dict[str, Any]:
    index_path = path or DEFAULT_INDEX_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with _index_write_lock(index_path):
        return _update_session_index_unlocked(digest, index_path)


def _update_session_index_unlocked(
    digest: dict[str, Any], path: Path | None = None
) -> dict[str, Any]:
    index_path = path or DEFAULT_INDEX_PATH
    try:
        index = _load_index(index_path)
    except SessionIndexError as exc:
        return {"result": "FAIL", "path": str(index_path), "error": str(exc)}
    policy = _load_policy()

    timestamp = str(digest.get("timestamp") or _utc_now().isoformat())
    cwd = str(digest.get("cwd") or "")
    session_id = _session_id(timestamp, cwd)
    event = _event_from_digest(digest)

    raw_sessions = index.get("sessions")
    sessions: list[dict[str, Any]] = (
        [item for item in raw_sessions if isinstance(item, dict)]
        if isinstance(raw_sessions, list)
        else []
    )
    target: dict[str, Any] | None = None
    for candidate in sessions:
        if candidate.get("session_id") == session_id:
            target = candidate
            break
    if target is None:
        target = {
            "session_id": session_id,
            "cwd": cwd,
            "started_at": timestamp,
            "last_event_at": timestamp,
            "event_count": 0,
            "last_reason": None,
            "reasons": [],
            "plan_ids": [],
            "events": [],
        }
        sessions.append(target)

    raw_events = target.get("events")
    events: list[dict[str, Any]] = (
        [item for item in raw_events if isinstance(item, dict)]
        if isinstance(raw_events, list)
        else []
    )
    events.append(event)
    pruned_event_count = max(0, len(events) - policy["max_events_per_session"])
    if pruned_event_count:
        events = events[-policy["max_events_per_session"] :]

    raw_reasons = target.get("reasons")
    reasons: list[str] = (
        [item for item in raw_reasons if isinstance(item, str)]
        if isinstance(raw_reasons, list)
        else []
    )
    reason = event.get("reason")
    if isinstance(reason, str) and reason and reason not in reasons:
        reasons.append(reason)

    raw_plan_ids = target.get("plan_ids")
    plan_ids: list[str] = (
        [item for item in raw_plan_ids if isinstance(item, str)]
        if isinstance(raw_plan_ids, list)
        else []
    )
    plan_id = event.get("plan_id")
    if isinstance(plan_id, str) and plan_id and plan_id not in plan_ids:
        plan_ids.append(plan_id)

    target["events"] = events
    target["event_count"] = int(target.get("event_count", 0)) + 1
    target["last_event_at"] = timestamp
    target["last_reason"] = reason
    pruned_reason_count = max(0, len(reasons) - policy["max_reasons_per_session"])
    pruned_plan_id_count = max(0, len(plan_ids) - policy["max_plan_ids_per_session"])
    target["reasons"] = reasons[-policy["max_reasons_per_session"] :]
    target["plan_ids"] = plan_ids[-policy["max_plan_ids_per_session"] :]
    target["cwd"] = cwd

    index["sessions"] = _prune_sessions(sessions, policy)
    index["generated_at"] = _utc_now().isoformat()

    index_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(index_path, index)

    return {
        "result": "PASS",
        "path": str(index_path),
        "session_id": session_id,
        "session_count": len(index["sessions"]),
        "policy": policy,
        "pruned": {
            "events": pruned_event_count,
            "reasons": pruned_reason_count,
            "plan_ids": pruned_plan_id_count,
        },
    }
