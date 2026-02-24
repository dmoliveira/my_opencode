#!/usr/bin/env python3

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


FORMAT_VERSION = 1
MAX_HISTORY_PER_RUN = 50
MAX_AGE_DAYS = 14


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _sha256_json(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_id(runtime: dict[str, Any]) -> str:
    plan_any = runtime.get("plan")
    plan = plan_any if isinstance(plan_any, dict) else {}
    metadata_any = plan.get("metadata")
    metadata = metadata_any if isinstance(metadata_any, dict) else {}
    plan_id = str(metadata.get("id") or "session").strip() or "session"
    started_at = str(runtime.get("started_at") or now_iso())
    stamp = (
        started_at.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    )
    return f"{plan_id}-{stamp}"


def runtime_run_id(runtime: dict[str, Any]) -> str:
    return _run_id(runtime)


def _snapshot_paths(
    config_write_path: Path, run_id: str, snapshot_id: str
) -> dict[str, Path]:
    root = config_write_path.parent / "checkpoints" / run_id
    history = root / "history"
    return {
        "root": root,
        "history_dir": history,
        "latest": root / "latest.json",
        "history": history / f"{snapshot_id}.json",
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(json.dumps(payload, indent=2) + "\n")
        tmp.flush()
        Path(tmp.name).replace(path)


def build_snapshot(
    runtime: dict[str, Any],
    source: str,
    *,
    command_outcomes: list[dict[str, Any]] | None = None,
    source_details: list[str] | None = None,
) -> dict[str, Any]:
    created_at = now_iso()
    snapshot_core = {
        "snapshot_id": f"cp_{created_at.replace(':', '').replace('-', '').replace('T', '_').replace('Z', '')}",
        "created_at": created_at,
        "run_id": _run_id(runtime),
        "source": source,
        "source_details": source_details or [source],
        "status": str(runtime.get("status") or "in_progress"),
        "step_state": {
            "plan_path": (
                runtime.get("plan", {}).get("path")
                if isinstance(runtime.get("plan"), dict)
                else ""
            ),
            "step_id": None,
            "step_ordinal": None,
            "step_status": None,
            "todo_compliance": runtime.get("todo_compliance", {}),
            "resume_hints": {
                "eligible": None,
                "reason_code": None,
                "next_actions": [],
            },
        },
        "context_digest": {
            "window_pressure": "low",
            "protected_artifacts": [],
            "dropped_items": 0,
            "policy_profile": "default",
        },
        "command_outcomes": command_outcomes or [],
        "runtime_state": runtime,
    }

    steps_any = runtime.get("steps")
    if isinstance(steps_any, list):
        for step in steps_any:
            if not isinstance(step, dict):
                continue
            state = str(step.get("state") or "")
            if state in {"pending", "in_progress"}:
                snapshot_core["step_state"]["step_ordinal"] = step.get("ordinal")
                snapshot_core["step_state"]["step_status"] = state
                break

    integrity_target = dict(snapshot_core)
    checksum = _sha256_json(integrity_target)
    snapshot_core["integrity"] = {
        "format_version": FORMAT_VERSION,
        "checksum_sha256": checksum,
    }
    return snapshot_core


def restore_runtime_from_snapshot(
    snapshot_payload: dict[str, Any],
) -> dict[str, Any] | None:
    runtime_any = snapshot_payload.get("runtime_state")
    if not isinstance(runtime_any, dict):
        return None
    return runtime_any


def write_snapshot(
    config_write_path: Path,
    runtime: dict[str, Any],
    *,
    source: str,
    command_outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshot = build_snapshot(runtime, source, command_outcomes=command_outcomes)
    run_id = str(snapshot.get("run_id") or "session")
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    paths = _snapshot_paths(config_write_path, run_id, snapshot_id)
    try:
        _atomic_write_json(paths["history"], snapshot)
        _atomic_write_json(paths["latest"], snapshot)
    except OSError as exc:
        return {
            "result": "FAIL",
            "reason_code": "checkpoint_atomic_write_failed",
            "detail": str(exc),
            "snapshot": snapshot,
        }
    return {
        "result": "PASS",
        "reason_code": "checkpoint_written",
        "snapshot": snapshot,
        "paths": {
            "latest": str(paths["latest"]),
            "history": str(paths["history"]),
        },
    }


def list_snapshots(
    config_write_path: Path, run_id: str | None = None
) -> list[dict[str, Any]]:
    root = config_write_path.parent / "checkpoints"
    if run_id:
        run_dirs = [root / run_id]
    elif root.exists():
        run_dirs = [path for path in root.iterdir() if path.is_dir()]
    else:
        return []

    snapshots: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        history_dir = run_dir / "history"
        if not history_dir.exists():
            continue
        for entry in history_dir.glob("*.json"):
            try:
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                snapshots.append(payload)
    snapshots.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return snapshots


def show_snapshot(
    config_write_path: Path, run_id: str, snapshot_id: str | None = None
) -> dict[str, Any]:
    root = config_write_path.parent / "checkpoints" / run_id
    if snapshot_id in (None, "latest"):
        path = root / "latest.json"
    else:
        path = root / "history" / f"{snapshot_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "result": "FAIL",
            "reason_code": "resume_missing_checkpoint",
            "snapshot": None,
        }
    except (OSError, json.JSONDecodeError):
        return {
            "result": "FAIL",
            "reason_code": "checkpoint_schema_invalid",
            "snapshot": None,
        }
    if not isinstance(payload, dict):
        return {
            "result": "FAIL",
            "reason_code": "checkpoint_schema_invalid",
            "snapshot": None,
        }

    integrity_any = payload.get("integrity")
    integrity = integrity_any if isinstance(integrity_any, dict) else {}
    expected = str(integrity.get("checksum_sha256") or "")
    payload_for_hash = dict(payload)
    payload_for_hash.pop("integrity", None)
    actual = _sha256_json(payload_for_hash)
    if expected and expected != actual:
        return {
            "result": "FAIL",
            "reason_code": "checkpoint_integrity_mismatch",
            "snapshot": None,
        }
    return {"result": "PASS", "reason_code": "checkpoint_loaded", "snapshot": payload}


def prune_snapshots(
    config_write_path: Path,
    *,
    max_per_run: int = MAX_HISTORY_PER_RUN,
    max_age_days: int = MAX_AGE_DAYS,
    compress_after_hours: int = 24,
) -> dict[str, Any]:
    root = config_write_path.parent / "checkpoints"
    if not root.exists():
        return {"result": "PASS", "removed": 0, "compressed": 0}

    removed = 0
    compressed = 0
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=max_age_days)
    compress_cutoff = now - timedelta(hours=compress_after_hours)

    try:
        for run_dir in [path for path in root.iterdir() if path.is_dir()]:
            history = run_dir / "history"
            if not history.exists():
                continue
            entries: list[tuple[Path, datetime]] = []
            for item in history.glob("*.json"):
                payload: dict[str, Any] | None = None
                created_at = datetime.fromtimestamp(item.stat().st_mtime, tz=UTC)
                try:
                    payload = json.loads(item.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                if isinstance(payload, dict):
                    parsed = _parse_iso(payload.get("created_at"))
                    if parsed is not None:
                        created_at = parsed
                entries.append((item, created_at))

                if created_at < compress_cutoff:
                    gz_path = item.with_suffix(".json.gz")
                    with gzip.open(gz_path, "wt", encoding="utf-8") as handle:
                        handle.write(item.read_text(encoding="utf-8"))
                    item.unlink(missing_ok=True)
                    compressed += 1

            entries.sort(key=lambda pair: pair[1], reverse=True)
            keep = set(path for path, _ in entries[:max_per_run])
            for path, created_at in entries:
                if path in keep and created_at >= cutoff:
                    continue
                path.unlink(missing_ok=True)
                removed += 1
    except OSError as exc:
        return {
            "result": "FAIL",
            "reason_code": "checkpoint_retention_prune_failed",
            "detail": str(exc),
            "removed": removed,
            "compressed": compressed,
        }

    return {"result": "PASS", "removed": removed, "compressed": compressed}
