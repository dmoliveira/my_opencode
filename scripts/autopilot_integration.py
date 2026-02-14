#!/usr/bin/env python3

from __future__ import annotations

from copy import deepcopy
from typing import Any

from checkpoint_snapshot_manager import list_snapshots
from recovery_engine import evaluate_resume_eligibility
from todo_enforcement import (
    remediation_prompts,
    validate_plan_completion,
    validate_todo_set,
)


STATUS_TO_ORCHESTRATION_INTENT = {
    "draft": "dry-run",
    "running": "status",
    "paused": "resume",
    "completed": "report",
    "failed": "resume",
    "budget_stopped": "report",
    "stopped": "report",
}

INTENT_TO_PHASE = {
    "dry-run": "planning",
    "status": "execution",
    "resume": "recovery",
    "report": "reporting",
}


def _todo_controls(run: dict[str, Any]) -> dict[str, Any]:
    todos_any = run.get("todos")
    todos = todos_any if isinstance(todos_any, list) else []
    violations = validate_todo_set(todos)
    completion_violations = validate_plan_completion(todos)
    all_violations = [*violations, *completion_violations]
    result = "PASS" if not all_violations else "FAIL"
    return {
        "result": result,
        "violations": all_violations,
        "remediation": remediation_prompts(all_violations),
    }


def _resume_controls(run: dict[str, Any], interruption_class: str) -> dict[str, Any]:
    runtime = {
        "status": str(run.get("status") or "failed"),
        "steps": [
            {
                "ordinal": int(item.get("ordinal", 0) or 0),
                "state": "pending"
                if str(item.get("state") or "pending") != "done"
                else "done",
                "idempotent": True,
            }
            for item in run.get("cycles", [])
            if isinstance(item, dict)
        ],
        "resume": {
            "enabled": True,
            "attempt_count": 0,
            "max_attempts": 3,
        },
    }
    return evaluate_resume_eligibility(runtime, interruption_class)


def _orchestration_bridge(
    run: dict[str, Any], interruption_class: str
) -> dict[str, Any]:
    status = str(run.get("status") or "draft")
    intent = STATUS_TO_ORCHESTRATION_INTENT.get(status, "status")
    phase = INTENT_TO_PHASE.get(intent, "execution")
    return {
        "intent": intent,
        "result": "PASS",
        "reason_code": "autopilot_orchestration_bridge_ready",
        "phase": phase,
        "warnings": [],
        "interruption_class": interruption_class,
    }


def integrate_controls(
    *,
    run: dict[str, Any],
    write_path: Any,
    confidence_score: float,
    interruption_class: str = "tool_failure",
) -> dict[str, Any]:
    updated = deepcopy(run)

    todo = _todo_controls(updated)
    resume = _resume_controls(updated, interruption_class)
    orchestration = _orchestration_bridge(updated, interruption_class)
    checkpoint_count = len(list_snapshots(write_path))

    handoff_mode = "auto"
    handoff_reason = ""
    if confidence_score < 0.60:
        handoff_mode = "manual"
        handoff_reason = "confidence_drop_requires_handoff"
        updated["status"] = "paused"
        updated["reason_code"] = handoff_reason
        updated["blockers"] = [handoff_reason]
        updated["next_actions"] = [
            "handoff to operator for manual review",
            "resume only after confidence is restored",
        ]

    return {
        "result": "PASS",
        "run": updated,
        "control_integrations": {
            "orchestration_bridge": orchestration,
            "todo_controls": todo,
            "resume_controls": resume,
            "checkpoint_count": checkpoint_count,
            "manual_handoff": {
                "mode": handoff_mode,
                "reason_code": handoff_reason,
            },
        },
    }
