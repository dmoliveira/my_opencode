#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from config_layering import resolve_write_path  # type: ignore
from task_graph_runtime import graph_snapshot, load_state, now_iso, with_locked_state  # type: ignore


def _task_graph_write_path() -> Path:
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


def task_graph_runtime_path() -> Path:
    return load_state(_task_graph_write_path()).runtime_path


def task_graph_status_snapshot() -> dict[str, Any]:
    locked = load_state(_task_graph_write_path())
    tasks = [item for item in locked.state.get("tasks", []) if isinstance(item, dict)]
    snapshot = graph_snapshot(tasks)
    return {
        "task_graph_path": str(locked.runtime_path),
        "task_graph": {
            "summary": {
                "ready_count": snapshot["ready_count"],
                "blocked_count": snapshot["blocked_count"],
                "lane_count": snapshot["lane_count"],
            },
            "runnable_lanes": snapshot["runnable_lanes"],
            "blocked": snapshot["blocked"],
        },
    }


def _workflow_task_id(workflow_path: Path, step_id: str) -> str:
    return f"workflow:{workflow_path.resolve()}#{step_id}"


def _step_status_to_task_status(step_status: str) -> str:
    normalized = str(step_status or "").strip().lower()
    if normalized == "passed":
        return "completed"
    if normalized == "in_progress":
        return "in_progress"
    if normalized == "skipped":
        return "skipped"
    return "pending"


def _step_reservation_paths(step: dict[str, Any]) -> list[str]:
    for key in ("reservation_paths", "write_paths"):
        value = step.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    return []


def sync_workflow_run_to_task_graph(
    workflow_path: Path,
    workflow: dict[str, Any],
    ordered_steps: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
    run_record: dict[str, Any],
) -> Path:
    workflow_resolved = workflow_path.expanduser().resolve()
    step_results_by_id = {
        str(item.get("id") or "").strip(): item
        for item in step_results
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    workflow_name = str(workflow.get("name") or workflow_resolved.name).strip()
    run_id = str(run_record.get("run_id") or "").strip()
    run_status = str(run_record.get("status") or "").strip()
    execution_mode = str(run_record.get("execution_mode") or "").strip()

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        tasks = [item for item in state.get("tasks", []) if isinstance(item, dict)]
        existing_by_id = {str(item.get("id") or ""): item for item in tasks}
        workflow_prefix = f"workflow:{workflow_resolved}#"
        retained = [
            item
            for item in tasks
            if not str(item.get("id") or "").startswith(workflow_prefix)
        ]
        next_tasks = list(retained)

        prior_step_ids: list[str] = []
        for step in ordered_steps:
            step_id = str(step.get("id") or "").strip()
            if not step_id:
                continue
            task_id = _workflow_task_id(workflow_resolved, step_id)
            existing = existing_by_id.get(task_id, {})
            result = step_results_by_id.get(step_id, {})
            task_status = _step_status_to_task_status(str(result.get("status") or ""))
            blocked_by = [
                _workflow_task_id(workflow_resolved, str(dep).strip())
                for dep in step.get("depends_on", [])
                if str(dep).strip()
            ]
            when = str(step.get("when") or "always").strip().lower()
            if prior_step_ids and when in {"on_success", "on_failure"}:
                blocked_by = sorted(
                    set(blocked_by)
                    | {
                        _workflow_task_id(workflow_resolved, dep_id)
                        for dep_id in prior_step_ids
                    }
                )
            metadata = (
                dict(existing.get("metadata", {}))
                if isinstance(existing.get("metadata"), dict)
                else {}
            )
            metadata.update(
                {
                    "command_family": "workflow",
                    "workflow_name": workflow_name,
                    "workflow_path": str(workflow_resolved),
                    "step_id": step_id,
                    "run_id": run_id,
                    "run_status": run_status,
                    "execution_mode": execution_mode,
                    "step_status": str(result.get("status") or ""),
                    "step_reason_code": str(result.get("reason_code") or ""),
                    "when": when,
                }
            )
            reservation_paths = _step_reservation_paths(step)
            if reservation_paths:
                metadata["reservation_paths"] = reservation_paths
            else:
                metadata.pop("reservation_paths", None)
            next_tasks.append(
                {
                    "id": task_id,
                    "subject": f"{workflow_name}: {step_id}",
                    "description": str(step.get("action") or "").strip(),
                    "status": task_status,
                    "activeForm": str(step.get("action") or "").strip(),
                    "blockedBy": blocked_by,
                    "blocks": [],
                    "owner": "workflow",
                    "metadata": metadata,
                    "threadID": run_id,
                    "created_at": str(existing.get("created_at") or now_iso()),
                    "updated_at": now_iso(),
                }
            )
            prior_step_ids.append(step_id)

        state["tasks"] = next_tasks
        return state

    locked = with_locked_state(_task_graph_write_path(), mutate)
    return locked.runtime_path
