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
from execution_budget_runtime import (
    build_budget_state,
    evaluate_budget,
    resolve_budget_policy,
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


def initialize_run(
    *,
    config: dict[str, Any],
    write_path: Path,
    objective: dict[str, Any],
    actor: str = "autopilot",
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

        if pending == 0 and completion_mode == "promise" and completion_signal:
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
            updated["next_actions"] = [
                "review report and confirm completion criteria",
                "archive final run summary for future objectives",
            ]
        elif updated["reason_code"] not in {
            "autopilot_waiting_for_completion_promise",
        }:
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
