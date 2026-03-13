#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
from fnmatch import fnmatch
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from checkpoint_snapshot_manager import write_snapshot
from completion_gates import (
    VALIDATION_CATEGORIES,
    evaluate_completion_gates,
    normalize_completion_gates,
)
from execution_budget_runtime import (
    build_budget_state,
    evaluate_budget,
    resolve_budget_policy,
)
from todo_enforcement import (
    remediation_prompts,
    validate_plan_completion,
    validate_todo_set,
)


RUNTIME_ENV_VAR = "MY_OPENCODE_AUTOPILOT_RUNTIME_PATH"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_path(write_path: Path) -> Path:
    override = os.environ.get(RUNTIME_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return write_path.parent / "my_opencode" / "runtime" / "autopilot_runtime.json"


def load_runtime(write_path: Path) -> dict[str, Any]:
    path = runtime_path(write_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_runtime(write_path: Path, runtime: dict[str, Any]) -> Path:
    path = runtime_path(write_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    return path


def _normalize_done_criteria(raw: Any) -> list[str]:
    if isinstance(raw, list):
        criteria = [str(item).strip() for item in raw if str(item).strip()]
        return criteria
    if isinstance(raw, str):
        parts = [part.strip() for part in re.split(r"[\n;]+", raw) if part.strip()]
        return parts
    return []


def _normalized_objective(objective: dict[str, Any]) -> dict[str, Any]:
    completion_mode = str(objective.get("completion_mode") or "promise").strip().lower()
    if completion_mode not in {"promise", "objective"}:
        completion_mode = "promise"
    completion_promise = str(objective.get("completion_promise") or "DONE").strip()
    if not completion_promise:
        completion_promise = "DONE"
    fallback_markers = _normalize_done_criteria(
        objective.get("required_markers") or objective.get("required-markers")
    )
    completion_gates = normalize_completion_gates(
        objective.get("completion_gates") or objective.get("completion-gates"),
        fallback_markers=fallback_markers,
    )
    extra_validation = [
        item.strip().lower()
        for item in _normalize_done_criteria(
            objective.get("required_validation") or objective.get("required-validation")
        )
        if item.strip() and item.strip().lower() in VALIDATION_CATEGORIES
    ]
    if extra_validation:
        completion_gates["required_validation"] = sorted(
            set(
                list(completion_gates.get("required_validation") or [])
                + extra_validation
            )
        )
    evidence_mode = (
        str(
            objective.get("evidence_mode")
            or objective.get("evidence-mode")
            or completion_gates.get("evidence_mode")
            or "hybrid"
        )
        .strip()
        .lower()
    )
    if evidence_mode:
        completion_gates["evidence_mode"] = evidence_mode
    return {
        "goal": str(objective.get("goal", "")).strip(),
        "scope": str(objective.get("scope", "")).strip(),
        "done_criteria": _normalize_done_criteria(
            objective.get("done_criteria") or objective.get("done-criteria")
        ),
        "max_budget": objective.get("max_budget") or objective.get("max-budget"),
        "risk_level": str(objective.get("risk_level") or "medium"),
        "continuous_mode": bool(objective.get("continuous_mode", False)),
        "completion_mode": completion_mode,
        "completion_promise": completion_promise,
        "completion_gates": completion_gates,
    }


def validate_objective(objective: dict[str, Any]) -> dict[str, Any]:
    norm = _normalized_objective(objective)
    missing: list[str] = []
    if not norm["goal"]:
        missing.append("goal")
    if not norm["scope"]:
        missing.append("scope")
    if norm["completion_mode"] == "objective" and not norm["done_criteria"]:
        missing.append("done-criteria")
    if not norm["max_budget"]:
        missing.append("max-budget")

    if missing:
        return {
            "result": "FAIL",
            "reason_code": "objective_schema_invalid",
            "missing_fields": missing,
            "remediation": [
                "provide goal, scope, done-criteria, and max-budget before starting /autopilot",
                "use /autopilot start --dry-run to validate objective shape",
            ],
            "objective": norm,
        }
    return {
        "result": "PASS",
        "reason_code": "objective_schema_valid",
        "missing_fields": [],
        "objective": norm,
    }


def build_cycles(objective: dict[str, Any]) -> list[dict[str, Any]]:
    criteria = _normalize_done_criteria(
        objective.get("done_criteria") or objective.get("done-criteria")
    )
    cycles: list[dict[str, Any]] = []
    if not criteria:
        fallback = str(objective.get("goal") or "advance objective").strip()
        criteria = [fallback]
    for idx, item in enumerate(criteria, start=1):
        cycles.append(
            {
                "cycle_id": f"cycle-{idx}",
                "ordinal": idx,
                "title": item,
                "state": "pending",
            }
        )
    return cycles


def _append_continuous_cycle(run: dict[str, Any]) -> dict[str, Any]:
    updated = dict(run)
    cycles_any = updated.get("cycles")
    cycles = cycles_any if isinstance(cycles_any, list) else []
    next_ordinal = len(cycles) + 1
    objective_any = updated.get("objective")
    objective = objective_any if isinstance(objective_any, dict) else {}
    goal = str(objective.get("goal") or "continue objective").strip()
    title = f"{goal} (cycle {next_ordinal})"
    cycles.append(
        {
            "cycle_id": f"cycle-{next_ordinal}",
            "ordinal": next_ordinal,
            "title": title,
            "state": "pending",
        }
    )
    updated["cycles"] = cycles
    return updated


def _budget_profile_from_objective(max_budget: Any) -> str:
    if isinstance(max_budget, str) and max_budget in {
        "conservative",
        "balanced",
        "extended",
    }:
        return max_budget
    return "balanced"


def _scope_patterns(raw_scope: Any) -> list[str]:
    if not isinstance(raw_scope, str):
        return []
    return [part.strip() for part in re.split(r"[,;\n]+", raw_scope) if part.strip()]


def _in_scope(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch(path, pattern):
            return True
        normalized = pattern.rstrip("/")
        if normalized and path.startswith(normalized + "/"):
            return True
    return False


def _has_hard_continuation_cue(text: str) -> bool:
    normalized = text.lower()
    if "<continue-loop>" in normalized:
        return True
    return any(
        cue in normalized
        for cue in (
            "still left to do",
            "remaining actionable",
            "remaining epic",
            "next remaining epic",
            "remaining tasks",
            "remaining items",
            "continue loop",
            "in-progress right now",
            "still left to do (next",
            "need finish",
        )
    )


def _has_completion_closure_cue(text: str) -> bool:
    normalized = text.lower()
    return any(
        cue in normalized
        for cue in (
            "nothing additional",
            "nothing more to",
            "nothing left to",
            "there is nothing additional",
            "this slice is done",
            "work from this slice is done",
            "task is finished",
            "task complete",
            "complete for now",
            "done for now",
            "already included",
            "already in the current released state",
            "already in the released state",
        )
    )


def _has_actionable_next_slice_cue(text: str) -> bool:
    normalized = text.lower()
    return any(
        cue in normalized
        for cue in (
            "next steps",
            "next safe steps",
            "natural next",
            "best next safe slice",
            "next safe slice",
            "next slice",
        )
    )


def _has_direct_continuation_offer_cue(text: str) -> bool:
    normalized = text.lower()
    return bool(
        re.search(r"\bi\s+will\s+continue\b", normalized)
        or re.search(r"\bi'?ll\s+continue\b", normalized)
        or re.search(r"\bi\s+am\s+continuing\b", normalized)
        or re.search(r"\bi'?m\s+continuing\b", normalized)
        or re.search(r"\bcontinuing\s+with\s+the\s+next\b", normalized)
        or "continue directly" in normalized
    )


def _assistant_text_requires_continuation(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if _has_hard_continuation_cue(normalized):
        return True
    return (
        _has_completion_closure_cue(normalized)
        and _has_actionable_next_slice_cue(normalized)
        and _has_direct_continuation_offer_cue(normalized)
    )


def _evaluate_run_todo_controls(run: dict[str, Any]) -> dict[str, Any]:
    todos_any = run.get("todos")
    todos = todos_any if isinstance(todos_any, list) else []
    normalized_todos: list[dict[str, Any]] = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        normalized = dict(todo)
        if "state" not in normalized and "status" in normalized:
            normalized["state"] = normalized.get("status")
        normalized_todos.append(normalized)
    violations = [
        *validate_todo_set(normalized_todos),
        *validate_plan_completion(normalized_todos),
    ]
    reason_code = "autopilot_todo_completion_blocked"
    if violations:
        primary_code = str(violations[0].get("code") or "").strip()
        if primary_code:
            reason_code = primary_code
    return {
        "result": "PASS" if not violations else "FAIL",
        "reason_code": reason_code,
        "violations": violations,
        "remediation": remediation_prompts(violations),
    }


def _apply_todo_completion_block(
    updated: dict[str, Any], *, todo_status: dict[str, Any], promise_tag: str
) -> None:
    updated["status"] = "running"
    updated["reason_code"] = str(
        todo_status.get("reason_code") or "autopilot_todo_completion_blocked"
    )
    violations = list(todo_status.get("violations") or [])
    updated["todo_violations"] = violations
    updated["blockers"] = [
        str(item.get("code") or "todo_violation")
        for item in violations
        if isinstance(item, dict)
    ] or ["autopilot_todo_completion_blocked"]
    remediation = [
        str(item).strip()
        for item in list(todo_status.get("remediation") or [])
        if str(item).strip()
    ]
    updated["next_actions"] = remediation or [
        "complete or explicitly skip remaining todo items before finalizing the run",
        f"output {promise_tag} only after todo completion blockers are cleared",
    ]


def _sync_run_todos_from_cycles(run: dict[str, Any]) -> None:
    cycles_any = run.get("cycles")
    cycles = cycles_any if isinstance(cycles_any, list) else []
    if not cycles:
        return
    todos_any = run.get("todos")
    todos = todos_any if isinstance(todos_any, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        todo_id = str(todo.get("id") or "").strip()
        if todo_id:
            by_id[todo_id] = dict(todo)
            ordered.append(by_id[todo_id])
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        todo_id = str(cycle.get("ordinal") or "").strip()
        if not todo_id:
            continue
        status = "done" if str(cycle.get("state") or "pending") == "done" else "pending"
        existing = by_id.get(todo_id)
        if existing is None:
            existing = {
                "id": todo_id,
                "content": str(cycle.get("title") or f"cycle {todo_id}").strip(),
                "state": status,
                "status": status,
                "priority": "high",
            }
            by_id[todo_id] = existing
            ordered.append(existing)
        else:
            existing.setdefault(
                "content", str(cycle.get("title") or f"cycle {todo_id}").strip()
            )
            existing.setdefault("priority", "high")
            existing["state"] = status
            existing["status"] = status
    run["todos"] = ordered


def _completed_task_ids_from_run(run: dict[str, Any]) -> list[str]:
    completed: list[str] = []
    seen: set[str] = set()
    todos_any = run.get("todos")
    todos = todos_any if isinstance(todos_any, list) else []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        state = str(todo.get("status") or todo.get("state") or "").strip().lower()
        if state not in {"done", "skipped"}:
            continue
        todo_id = str(todo.get("id") or "").strip()
        if todo_id and todo_id not in seen:
            seen.add(todo_id)
            completed.append(todo_id)
    cycles_any = run.get("cycles")
    cycles = cycles_any if isinstance(cycles_any, list) else []
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        if str(cycle.get("state") or "pending") != "done":
            continue
        for value in (cycle.get("ordinal"), cycle.get("cycle_id")):
            item = str(value or "").strip()
            if item and item not in seen:
                seen.add(item)
                completed.append(item)
    return completed


def _extend_unique(target: list[str], extras: list[str]) -> list[str]:
    for item in extras:
        if item and item not in target:
            target.append(item)
    return target


def _augment_continuation_pending_details(
    updated: dict[str, Any], *, directory: Path, completion_text: str, promise_tag: str
) -> None:
    todo_status = _evaluate_run_todo_controls(updated)
    if todo_status.get("result") != "PASS":
        violations = list(todo_status.get("violations") or [])
        updated["todo_violations"] = violations
        _extend_unique(
            updated["blockers"],
            [
                str(item.get("code") or "todo_violation")
                for item in violations
                if isinstance(item, dict)
            ],
        )
        remediation = [
            str(item).strip()
            for item in list(todo_status.get("remediation") or [])
            if str(item).strip()
        ]
        _extend_unique(updated["next_actions"], remediation)
    gate_status = _evaluate_run_completion_gates(
        updated, directory=directory, completion_text=completion_text
    )
    if gate_status.get("result") != "PASS":
        _extend_unique(
            updated["blockers"],
            [
                str(item).strip()
                for item in list(gate_status.get("blockers") or [])
                if str(item).strip()
            ],
        )
        _extend_unique(
            updated["next_actions"],
            [
                "run required validation and collect evidence for missing completion gates",
                "resume autopilot after gate blockers are cleared",
            ],
        )
    if not updated["next_actions"]:
        updated["next_actions"] = [
            "continue the next actionable slice before finalizing the run",
            f"output {promise_tag} only after continuation cues and blockers are cleared",
        ]


def _evaluate_run_completion_gates(
    run: dict[str, Any], *, directory: Path, completion_text: str = ""
) -> dict[str, Any]:
    objective_any = run.get("objective")
    objective = objective_any if isinstance(objective_any, dict) else {}
    gates = (
        objective.get("completion_gates")
        if isinstance(objective.get("completion_gates"), dict)
        else {}
    )
    result = evaluate_completion_gates(
        gates,
        directory=directory,
        completed_task_ids=_completed_task_ids_from_run(run),
        current_owner=str(run.get("actor") or ""),
        completion_text=completion_text,
    )
    run["completion_gate_status"] = result
    return result


def initialize_run(
    *,
    config: dict[str, Any],
    write_path: Path,
    objective: dict[str, Any],
    actor: str = "autopilot",
    directory: Path | None = None,
) -> dict[str, Any]:
    schema = validate_objective(objective)
    if schema.get("result") != "PASS":
        return schema

    objective_norm = dict(schema.get("objective") or {})
    objective_norm["max_budget"] = _budget_profile_from_objective(
        objective_norm.get("max_budget")
    )
    cycles = build_cycles(objective_norm)
    started_at = now_iso()
    run_id = f"autopilot-{started_at.replace(':', '').replace('-', '').replace('T', '-')[:-1]}"

    profile_config = dict(config)
    profile_config["budget_runtime"] = {
        "profile": objective_norm["max_budget"],
    }
    policy = resolve_budget_policy(profile_config)

    run = {
        "run_id": run_id,
        "status": "draft",
        "reason_code": "dry_run_required_before_execute",
        "objective": objective_norm,
        "cycles": cycles,
        "started_at": started_at,
        "updated_at": started_at,
        "actor": actor,
        "budget": {
            "policy": policy,
            "counters": build_budget_state(
                started_at, tool_call_count=0, token_estimate=0, now_ts=started_at
            ),
            "result": "PASS",
            "reason_code": "budget_within_limits",
        },
        "progress": {
            "total_cycles": len(cycles),
            "completed_cycles": 0,
            "pending_cycles": len(cycles),
        },
        "blockers": ["dry_run_required_before_execute"],
        "next_actions": [
            "review dry-run plan and confirm scope boundaries",
            "start first execution cycle after guardrail acknowledgment",
        ],
    }
    _sync_run_todos_from_cycles(run)
    _evaluate_run_completion_gates(run, directory=directory or Path.cwd())

    runtime_file = save_runtime(write_path, run)
    snapshot = write_snapshot(
        write_path,
        {
            "status": run["status"],
            "plan": {"metadata": {"id": run_id}, "path": str(runtime_file)},
            "steps": [
                {"ordinal": cycle["ordinal"], "state": cycle["state"]}
                for cycle in cycles
            ],
        },
        source="autopilot_initialize",
        command_outcomes=[
            {
                "kind": "slash_command",
                "name": "/autopilot start",
                "result": "PASS",
                "reason_code": run["reason_code"],
                "summary": "autopilot run initialized with dry-run requirement",
            }
        ],
    )
    return {
        "result": "PASS",
        "run": run,
        "runtime_path": str(runtime_file),
        "checkpoint": snapshot,
    }


def execute_cycle(
    *,
    config: dict[str, Any],
    write_path: Path,
    run: dict[str, Any],
    tool_call_increment: int,
    token_increment: int,
    touched_paths: list[str] | None = None,
    completion_signal: bool = False,
    assistant_text: str | None = None,
    now_ts: str | None = None,
    directory: Path | None = None,
) -> dict[str, Any]:
    objective = (
        run.get("objective", {}) if isinstance(run.get("objective"), dict) else {}
    )
    profile = _budget_profile_from_objective(objective.get("max_budget"))
    completion_mode = str(objective.get("completion_mode") or "promise").strip().lower()
    completion_promise = (
        str(objective.get("completion_promise") or "DONE").strip() or "DONE"
    )
    normalized_assistant = str(assistant_text or "")
    promise_tag = f"<promise>{completion_promise}</promise>"
    if not completion_signal and normalized_assistant:
        completion_signal = promise_tag.lower() in normalized_assistant.lower()

    scope_patterns = _scope_patterns(objective.get("scope"))
    paths = [str(item).strip() for item in (touched_paths or []) if str(item).strip()]
    scope_violations = [path for path in paths if not _in_scope(path, scope_patterns)]

    updated = dict(run)
    updated["updated_at"] = now_ts or now_iso()
    eval_directory = directory or Path.cwd()
    _sync_run_todos_from_cycles(updated)

    if not paths:
        cycles_any = updated.get("cycles")
        cycles = cycles_any if isinstance(cycles_any, list) else []
        pending = sum(
            1
            for cycle in cycles
            if isinstance(cycle, dict)
            and str(cycle.get("state") or "pending") == "pending"
        )
        done = sum(
            1
            for cycle in cycles
            if isinstance(cycle, dict)
            and str(cycle.get("state") or "pending") == "done"
        )

        objective_any = updated.get("objective")
        objective = objective_any if isinstance(objective_any, dict) else {}
        continuous_mode = bool(objective.get("continuous_mode", False))

        assistant_requires_continuation = _assistant_text_requires_continuation(
            normalized_assistant
        )

        if pending == 0 and completion_mode == "promise" and completion_signal:
            if assistant_requires_continuation:
                updated["status"] = "running"
                updated["reason_code"] = "autopilot_continuation_pending"
                updated["blockers"] = ["continuation_pending"]
                updated["next_actions"] = [
                    "continue the next actionable slice before finalizing the run",
                    f"output {promise_tag} only after continuation cues are cleared",
                ]
                _augment_continuation_pending_details(
                    updated,
                    directory=eval_directory,
                    completion_text=normalized_assistant,
                    promise_tag=promise_tag,
                )
                updated["progress"] = {
                    "total_cycles": len(cycles),
                    "completed_cycles": done,
                    "pending_cycles": pending,
                }
                runtime_file = save_runtime(write_path, updated)
                snapshot = write_snapshot(
                    write_path,
                    {
                        "status": updated["status"],
                        "plan": {
                            "metadata": {"id": updated.get("run_id")},
                            "path": str(runtime_file),
                        },
                        "steps": [
                            {
                                "ordinal": cycle.get("ordinal"),
                                "state": cycle.get("state"),
                            }
                            for cycle in cycles
                            if isinstance(cycle, dict)
                        ],
                    },
                    source="autopilot_cycle_continuation_pending",
                    command_outcomes=[
                        {
                            "kind": "slash_command",
                            "name": "/autopilot resume",
                            "result": "PASS",
                            "reason_code": updated["reason_code"],
                            "summary": "autopilot deferred completion because assistant text indicates immediate continuation",
                        }
                    ],
                )
                return {
                    "result": "PASS",
                    "run": updated,
                    "runtime_path": str(runtime_file),
                    "checkpoint": snapshot,
                }
            updated["status"] = "completed"
            updated["reason_code"] = "autopilot_completion_promise_detected"
            updated["blockers"] = []
            updated["next_actions"] = [
                "review report and confirm completion promise output",
                "archive final run summary for future objectives",
            ]
            updated["progress"] = {
                "total_cycles": len(cycles),
                "completed_cycles": done,
                "pending_cycles": pending,
            }
            todo_status = _evaluate_run_todo_controls(updated)
            if todo_status.get("result") != "PASS":
                _apply_todo_completion_block(
                    updated, todo_status=todo_status, promise_tag=promise_tag
                )
            gate_status = _evaluate_run_completion_gates(
                updated, directory=eval_directory, completion_text=normalized_assistant
            )
            if (
                updated.get("status") == "completed"
                and gate_status.get("result") != "PASS"
            ):
                updated["status"] = "running"
                updated["reason_code"] = str(
                    gate_status.get("reason_code") or "completion_gates_blocked"
                )
                updated["blockers"] = list(gate_status.get("blockers") or [])
                updated["next_actions"] = [
                    "run required validation and collect evidence for missing completion gates",
                    "resume autopilot after gate blockers are cleared",
                ]
            runtime_file = save_runtime(write_path, updated)
            snapshot = write_snapshot(
                write_path,
                {
                    "status": updated["status"],
                    "plan": {
                        "metadata": {"id": updated.get("run_id")},
                        "path": str(runtime_file),
                    },
                    "steps": [
                        {"ordinal": cycle.get("ordinal"), "state": cycle.get("state")}
                        for cycle in cycles
                        if isinstance(cycle, dict)
                    ],
                },
                source="autopilot_cycle_promise_complete",
                command_outcomes=[
                    {
                        "kind": "slash_command",
                        "name": "/autopilot resume",
                        "result": "PASS",
                        "reason_code": updated["reason_code"],
                        "summary": "autopilot completion promise detected and run finalized",
                    }
                ],
            )
            return {
                "result": "PASS",
                "run": updated,
                "runtime_path": str(runtime_file),
                "checkpoint": snapshot,
            }

        if (
            pending == 0
            and len(cycles) > 0
            and completion_mode == "objective"
            and not continuous_mode
        ):
            if assistant_requires_continuation:
                updated["status"] = "running"
                updated["reason_code"] = "autopilot_continuation_pending"
                updated["blockers"] = ["continuation_pending"]
                updated["next_actions"] = [
                    "continue the next actionable slice before finalizing the run",
                    "resume autopilot after the assistant no longer signals immediate continuation",
                ]
                _augment_continuation_pending_details(
                    updated,
                    directory=eval_directory,
                    completion_text=normalized_assistant,
                    promise_tag=promise_tag,
                )
                updated["progress"] = {
                    "total_cycles": len(cycles),
                    "completed_cycles": done,
                    "pending_cycles": pending,
                }
                runtime_file = save_runtime(write_path, updated)
                snapshot = write_snapshot(
                    write_path,
                    {
                        "status": updated["status"],
                        "plan": {
                            "metadata": {"id": updated.get("run_id")},
                            "path": str(runtime_file),
                        },
                        "steps": [
                            {
                                "ordinal": cycle.get("ordinal"),
                                "state": cycle.get("state"),
                            }
                            for cycle in cycles
                            if isinstance(cycle, dict)
                        ],
                    },
                    source="autopilot_cycle_continuation_pending",
                    command_outcomes=[
                        {
                            "kind": "slash_command",
                            "name": "/autopilot resume",
                            "result": "PASS",
                            "reason_code": updated["reason_code"],
                            "summary": "autopilot deferred completion because assistant text indicates immediate continuation",
                        }
                    ],
                )
                return {
                    "result": "PASS",
                    "run": updated,
                    "runtime_path": str(runtime_file),
                    "checkpoint": snapshot,
                }
            updated["status"] = "completed"
            updated["reason_code"] = "autopilot_objective_completed"
            updated["blockers"] = []
            updated["next_actions"] = [
                "review report and confirm objective done-criteria",
                "archive final run summary for future objectives",
            ]
            updated["progress"] = {
                "total_cycles": len(cycles),
                "completed_cycles": done,
                "pending_cycles": pending,
            }
            todo_status = _evaluate_run_todo_controls(updated)
            if todo_status.get("result") != "PASS":
                _apply_todo_completion_block(
                    updated, todo_status=todo_status, promise_tag=promise_tag
                )
            gate_status = _evaluate_run_completion_gates(
                updated, directory=eval_directory, completion_text=normalized_assistant
            )
            if (
                updated.get("status") == "completed"
                and gate_status.get("result") != "PASS"
            ):
                updated["status"] = "running"
                updated["reason_code"] = str(
                    gate_status.get("reason_code") or "completion_gates_blocked"
                )
                updated["blockers"] = list(gate_status.get("blockers") or [])
                updated["next_actions"] = [
                    "run required validation and collect evidence for missing completion gates",
                    "resume autopilot after gate blockers are cleared",
                ]
            runtime_file = save_runtime(write_path, updated)
            snapshot = write_snapshot(
                write_path,
                {
                    "status": updated["status"],
                    "plan": {
                        "metadata": {"id": updated.get("run_id")},
                        "path": str(runtime_file),
                    },
                    "steps": [
                        {"ordinal": cycle.get("ordinal"), "state": cycle.get("state")}
                        for cycle in cycles
                        if isinstance(cycle, dict)
                    ],
                },
                source="autopilot_cycle_completed",
                command_outcomes=[
                    {
                        "kind": "slash_command",
                        "name": "/autopilot resume",
                        "result": "PASS",
                        "reason_code": updated["reason_code"],
                        "summary": "autopilot run already completed; no further touched paths required",
                    }
                ],
            )
            return {
                "result": "PASS",
                "run": updated,
                "runtime_path": str(runtime_file),
                "checkpoint": snapshot,
            }

        if pending == 0 and continuous_mode:
            updated = _append_continuous_cycle(updated)
            cycles_any = updated.get("cycles")
            cycles = cycles_any if isinstance(cycles_any, list) else []
            pending = sum(
                1
                for cycle in cycles
                if isinstance(cycle, dict)
                and str(cycle.get("state") or "pending") == "pending"
            )
            done = sum(
                1
                for cycle in cycles
                if isinstance(cycle, dict)
                and str(cycle.get("state") or "pending") == "done"
            )

        updated["status"] = "running"
        updated["reason_code"] = "autopilot_waiting_for_execution_evidence"
        updated["blockers"] = ["execution_evidence_missing"]
        updated["next_actions"] = [
            "run work cycle and include --touched-paths with concrete changed files",
            "resume autopilot after at least one in-scope artifact change",
        ]
        if completion_mode == "promise":
            updated["next_actions"].append(
                f"output {promise_tag} once the objective is fully complete"
            )
        updated["progress"] = {
            "total_cycles": len(cycles),
            "completed_cycles": done,
            "pending_cycles": pending,
        }
        runtime_file = save_runtime(write_path, updated)
        snapshot = write_snapshot(
            write_path,
            {
                "status": updated["status"],
                "plan": {
                    "metadata": {"id": updated.get("run_id")},
                    "path": str(runtime_file),
                },
                "steps": [
                    {"ordinal": cycle.get("ordinal"), "state": cycle.get("state")}
                    for cycle in cycles
                    if isinstance(cycle, dict)
                ],
            },
            source="autopilot_cycle_waiting_for_evidence",
            command_outcomes=[
                {
                    "kind": "slash_command",
                    "name": "/autopilot resume",
                    "result": "PASS",
                    "reason_code": updated["reason_code"],
                    "summary": "autopilot cycle held until concrete touched paths are provided",
                }
            ],
        )
        return {
            "result": "PASS",
            "run": updated,
            "runtime_path": str(runtime_file),
            "checkpoint": snapshot,
        }

    if scope_violations:
        updated["status"] = "scope_stopped"
        updated["reason_code"] = "scope_violation_detected"
        updated["blockers"] = ["scope_violation_detected", *scope_violations]
        updated["scope_violations"] = scope_violations
        updated["next_actions"] = [
            "review objective scope and remove out-of-scope paths",
            "restart or resume only with in-scope execution targets",
        ]
        runtime_file = save_runtime(write_path, updated)
        snapshot = write_snapshot(
            write_path,
            {
                "status": updated["status"],
                "plan": {
                    "metadata": {"id": updated.get("run_id")},
                    "path": str(runtime_file),
                },
                "steps": [
                    {"ordinal": cycle.get("ordinal"), "state": cycle.get("state")}
                    for cycle in updated.get("cycles", [])
                    if isinstance(cycle, dict)
                ],
                "resume_hints": {
                    "eligible": False,
                    "reason_code": updated["reason_code"],
                    "next_actions": updated["next_actions"],
                },
            },
            source="autopilot_cycle_scope_guard",
            command_outcomes=[
                {
                    "kind": "slash_command",
                    "name": "/autopilot resume",
                    "result": "FAIL",
                    "reason_code": updated["reason_code"],
                    "summary": "autopilot cycle blocked due to out-of-scope execution targets",
                }
            ],
        )
        return {
            "result": "FAIL",
            "run": updated,
            "runtime_path": str(runtime_file),
            "checkpoint": snapshot,
        }

    policy_config = dict(config)
    policy_config["budget_runtime"] = {"profile": profile}
    policy = resolve_budget_policy(policy_config)

    current_counters = run.get("budget", {}).get("counters", {})
    tool_calls = int(current_counters.get("tool_call_count", 0) or 0) + max(
        0, tool_call_increment
    )
    tokens = int(current_counters.get("token_estimate", 0) or 0) + max(
        0, token_increment
    )
    started_at = str(run.get("started_at") or now_iso())
    budget_anchor = started_at
    if completion_mode == "promise":
        previous_capture = str(current_counters.get("captured_at") or "").strip()
        if previous_capture:
            budget_anchor = previous_capture
    counters = build_budget_state(
        budget_anchor, tool_call_count=tool_calls, token_estimate=tokens, now_ts=now_ts
    )
    budget_eval = evaluate_budget(policy, counters)

    updated.setdefault("budget", {})
    updated["budget"] = {
        "policy": policy,
        "counters": counters,
        "result": budget_eval.get("result"),
        "reason_code": budget_eval.get("reason_code"),
        "warnings": budget_eval.get("warnings", []),
    }

    cycles_any = updated.get("cycles")
    cycles = cycles_any if isinstance(cycles_any, list) else []

    if budget_eval.get("result") == "FAIL":
        updated["status"] = "budget_stopped"
        updated["reason_code"] = str(
            budget_eval.get("reason_code") or "budget_threshold_reached"
        )
        updated["blockers"] = [updated["reason_code"]]
        updated["next_actions"] = list(budget_eval.get("recommendations", []))
    else:
        updated["status"] = "running"
        updated["reason_code"] = "autopilot_cycle_progressed"
        updated["blockers"] = []
        objective_any = updated.get("objective")
        objective = objective_any if isinstance(objective_any, dict) else {}
        continuous_mode = bool(objective.get("continuous_mode", False))
        assistant_requires_continuation = _assistant_text_requires_continuation(
            normalized_assistant
        )
        progressed = False
        for cycle in cycles:
            if not isinstance(cycle, dict):
                continue
            if str(cycle.get("state") or "pending") == "pending":
                cycle["state"] = "done"
                progressed = True
                break

        if progressed and continuous_mode:
            pending_after_progress = sum(
                1
                for cycle in cycles
                if isinstance(cycle, dict)
                and str(cycle.get("state") or "pending") == "pending"
            )
            if pending_after_progress == 0:
                updated = _append_continuous_cycle(updated)
                cycles_any = updated.get("cycles")
                cycles = cycles_any if isinstance(cycles_any, list) else []
                updated["reason_code"] = "autopilot_cycle_progressed_and_queued"

        if completion_mode == "promise" and completion_signal:
            updated["status"] = "completed"
            updated["reason_code"] = "autopilot_completion_promise_detected"
            updated["blockers"] = []

        if not progressed:
            if completion_mode == "promise" and completion_signal:
                updated["status"] = "completed"
                updated["reason_code"] = "autopilot_completion_promise_detected"
            elif completion_mode == "promise":
                updated["status"] = "running"
                updated["reason_code"] = "autopilot_waiting_for_completion_promise"
                updated["blockers"] = ["completion_promise_missing"]
                updated["next_actions"] = [
                    f"emit <promise>{completion_promise}</promise> only when objective is truly complete",
                    "continue execution until completion criteria are satisfied",
                ]
            elif continuous_mode:
                updated = _append_continuous_cycle(updated)
                cycles_any = updated.get("cycles")
                cycles = cycles_any if isinstance(cycles_any, list) else []
                updated["status"] = "running"
                updated["reason_code"] = "autopilot_cycle_queued"
            else:
                updated["status"] = "completed"
                updated["reason_code"] = "autopilot_objective_completed"

        _sync_run_todos_from_cycles(updated)

        if updated["status"] == "completed" and assistant_requires_continuation:
            updated["status"] = "running"
            updated["reason_code"] = "autopilot_continuation_pending"
            updated["blockers"] = ["continuation_pending"]
            if completion_mode == "promise":
                updated["next_actions"] = [
                    "continue the next actionable slice before finalizing the run",
                    f"output {promise_tag} only after continuation cues are cleared",
                ]
            else:
                updated["next_actions"] = [
                    "continue the next actionable slice before finalizing the run",
                    "resume autopilot after the assistant no longer signals immediate continuation",
                ]
            _augment_continuation_pending_details(
                updated,
                directory=eval_directory,
                completion_text=normalized_assistant,
                promise_tag=promise_tag,
            )

        if updated["status"] == "completed":
            todo_status = _evaluate_run_todo_controls(updated)
            if todo_status.get("result") != "PASS":
                _apply_todo_completion_block(
                    updated, todo_status=todo_status, promise_tag=promise_tag
                )

        pending = sum(
            1
            for cycle in cycles
            if isinstance(cycle, dict)
            and str(cycle.get("state") or "pending") == "pending"
        )
        done = sum(
            1
            for cycle in cycles
            if isinstance(cycle, dict)
            and str(cycle.get("state") or "pending") == "done"
        )
        updated["progress"] = {
            "total_cycles": len(cycles),
            "completed_cycles": done,
            "pending_cycles": pending,
        }
        if updated["status"] == "completed":
            gate_status = _evaluate_run_completion_gates(
                updated, directory=eval_directory, completion_text=normalized_assistant
            )
            if gate_status.get("result") != "PASS":
                updated["status"] = "running"
                updated["reason_code"] = str(
                    gate_status.get("reason_code") or "completion_gates_blocked"
                )
                updated["blockers"] = list(gate_status.get("blockers") or [])
                updated["next_actions"] = [
                    "run required validation and collect evidence for missing completion gates",
                    "resume autopilot after gate blockers are cleared",
                ]
        if updated["status"] == "completed":
            updated["next_actions"] = [
                "review report and confirm completion criteria",
                "archive final run summary for future objectives",
            ]
        elif updated["reason_code"] not in {
            "autopilot_waiting_for_completion_promise",
            "autopilot_continuation_pending",
            "completion_gates_blocked",
        } and not updated.get("todo_violations"):
            updated["next_actions"] = [
                "continue next bounded cycle",
                "pause run if confidence drops or scope uncertainty increases",
            ]

    runtime_file = save_runtime(write_path, updated)
    snapshot = write_snapshot(
        write_path,
        {
            "status": updated.get("status"),
            "plan": {
                "metadata": {"id": str(updated.get("run_id") or "autopilot")},
                "path": str(runtime_file),
            },
            "steps": [
                {
                    "ordinal": int(cycle.get("ordinal", 0) or 0),
                    "state": str(cycle.get("state") or "pending"),
                }
                for cycle in cycles
                if isinstance(cycle, dict)
            ],
        },
        source="autopilot_cycle",
        command_outcomes=[
            {
                "kind": "slash_command",
                "name": "/autopilot start",
                "result": "PASS"
                if updated.get("status") != "budget_stopped"
                else "FAIL",
                "reason_code": str(
                    updated.get("reason_code") or "autopilot_cycle_progressed"
                ),
                "summary": "autopilot cycle evaluated with budget and checkpoint guardrails",
            }
        ],
    )

    return {
        "result": "PASS" if updated.get("status") != "budget_stopped" else "FAIL",
        "run": updated,
        "checkpoint": snapshot,
        "runtime_path": str(runtime_file),
    }
