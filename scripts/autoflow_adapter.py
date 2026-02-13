#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from checkpoint_snapshot_manager import list_snapshots  # type: ignore
from config_layering import load_layered_config, resolve_write_path  # type: ignore
from plan_execution_runtime import load_plan_execution_state  # type: ignore
from recovery_engine import evaluate_resume_eligibility  # type: ignore


KNOWN_STATUSES = {
    "idle",
    "queued",
    "running",
    "in_progress",
    "paused",
    "completed",
    "failed",
    "stopped",
    "budget_stopped",
    "resume_required",
}
ALLOWED_INTENTS = {"start", "status", "resume", "stop", "report", "dry-run"}
PHASE_BY_STATUS = {
    "idle": "planning",
    "queued": "planning",
    "running": "executing",
    "in_progress": "executing",
    "paused": "paused",
    "completed": "completed",
    "failed": "failed",
    "stopped": "paused",
    "budget_stopped": "paused",
    "resume_required": "recovering",
}
TRANSITIONS = {
    "idle": {"start": "running", "status": "idle", "report": "idle", "dry-run": "idle"},
    "queued": {
        "status": "queued",
        "report": "queued",
        "stop": "stopped",
        "dry-run": "queued",
    },
    "running": {
        "status": "running",
        "report": "running",
        "stop": "stopped",
        "dry-run": "running",
    },
    "in_progress": {
        "status": "in_progress",
        "report": "in_progress",
        "stop": "stopped",
        "dry-run": "in_progress",
    },
    "paused": {
        "status": "paused",
        "report": "paused",
        "resume": "running",
        "stop": "stopped",
        "dry-run": "paused",
    },
    "completed": {
        "start": "running",
        "status": "completed",
        "report": "completed",
        "dry-run": "completed",
    },
    "failed": {
        "start": "running",
        "status": "failed",
        "report": "failed",
        "resume": "running",
        "dry-run": "failed",
    },
    "stopped": {
        "start": "running",
        "status": "stopped",
        "report": "stopped",
        "resume": "running",
        "dry-run": "stopped",
    },
    "budget_stopped": {
        "start": "running",
        "status": "budget_stopped",
        "report": "budget_stopped",
        "resume": "running",
        "dry-run": "budget_stopped",
    },
    "resume_required": {
        "status": "resume_required",
        "report": "resume_required",
        "resume": "running",
        "stop": "stopped",
        "dry-run": "resume_required",
    },
}


def usage() -> int:
    print(
        "usage: autoflow_adapter.py status [--json] | "
        "autoflow_adapter.py explain --intent <start|status|resume|stop|report|dry-run> "
        "[--status <status>] [--interruption-class <tool_failure|timeout|context_reset|process_crash>] [--json]"
    )
    return 2


def _load_runtime() -> tuple[dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, _ = load_plan_execution_state(config, write_path)
    return runtime, write_path


def normalize_status(value: Any) -> str:
    status = str(value or "idle")
    return status if status in KNOWN_STATUSES else "idle"


def _checkpoint_summary(write_path: Path) -> dict[str, Any]:
    snapshots = list_snapshots(write_path)
    latest = snapshots[0] if snapshots else {}
    return {
        "count": len(snapshots),
        "latest_snapshot_id": latest.get("snapshot_id")
        if isinstance(latest, dict)
        else None,
        "latest_status": latest.get("status") if isinstance(latest, dict) else None,
        "latest_created_at": latest.get("created_at")
        if isinstance(latest, dict)
        else None,
    }


def compose_primitives(
    runtime: dict[str, Any],
    write_path: Path,
    *,
    interruption_class: str = "tool_failure",
) -> dict[str, Any]:
    status = normalize_status(runtime.get("status"))
    steps_any = runtime.get("steps")
    steps = steps_any if isinstance(steps_any, list) else []
    in_progress_count = sum(
        1
        for step in steps
        if isinstance(step, dict) and str(step.get("state") or "") == "in_progress"
    )
    budget_any = runtime.get("budget")
    budget = budget_any if isinstance(budget_any, dict) else {}
    todo_any = runtime.get("todo_compliance")
    todo = todo_any if isinstance(todo_any, dict) else {}
    resume = evaluate_resume_eligibility(runtime, interruption_class)

    loop_reason = "loop_healthy"
    loop_halted = False
    if str(budget.get("result") or "") == "FAIL":
        loop_halted = True
        loop_reason = str(budget.get("reason_code") or "budget_wall_clock_exceeded")
    elif status in {"stopped", "budget_stopped"}:
        loop_halted = True
        loop_reason = "operator_stop"
    elif in_progress_count > 1:
        loop_halted = True
        loop_reason = "state_machine_conflict"

    return {
        "plan": runtime.get("plan", {}),
        "todo_compliance": todo,
        "budget": budget,
        "resume": resume,
        "checkpoint": _checkpoint_summary(write_path),
        "loop_guard": {
            "halted": loop_halted,
            "reason_code": loop_reason,
            "in_progress_count": in_progress_count,
        },
    }


def explain_transition(
    *, intent: str, current_status: str, primitives: dict[str, Any]
) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    allowed = intent in TRANSITIONS.get(current_status, {})

    trace.append(
        {
            "step": 1,
            "source": "state_machine",
            "decision": "allow" if allowed else "deny",
            "current_status": current_status,
            "intent": intent,
        }
    )

    if not allowed:
        fallback_intent = (
            "status" if intent in {"resume", "stop", "start"} else "report"
        )
        trace.append(
            {
                "step": 2,
                "source": "fallback",
                "decision": "fallback",
                "reason_code": "autoflow_illegal_transition",
                "fallback_intent": fallback_intent,
            }
        )
        return {
            "result": "FAIL",
            "reason_code": "autoflow_illegal_transition",
            "next_status": current_status,
            "effective_intent": fallback_intent,
            "trace": trace,
            "warnings": ["requested transition is not allowed in current state"],
        }

    if intent == "resume" and not bool(primitives.get("resume", {}).get("eligible")):
        trace.append(
            {
                "step": 2,
                "source": "resume_gate",
                "decision": "fallback",
                "reason_code": str(
                    primitives.get("resume", {}).get("reason_code")
                    or "resume_not_eligible"
                ),
                "fallback_intent": "status",
            }
        )
        return {
            "result": "FAIL",
            "reason_code": str(
                primitives.get("resume", {}).get("reason_code") or "resume_not_eligible"
            ),
            "next_status": current_status,
            "effective_intent": "status",
            "trace": trace,
            "warnings": [
                "resume is not currently eligible; review runtime diagnostics"
            ],
        }

    next_status = TRANSITIONS.get(current_status, {}).get(intent, current_status)
    trace.append(
        {
            "step": 2,
            "source": "state_machine",
            "decision": "transition",
            "next_status": next_status,
            "phase": PHASE_BY_STATUS.get(next_status, "planning"),
        }
    )
    return {
        "result": "PASS",
        "reason_code": "autoflow_transition_allowed",
        "next_status": next_status,
        "effective_intent": intent,
        "trace": trace,
        "warnings": [],
    }


def evaluate_request(
    intent: str,
    *,
    status_override: str | None = None,
    interruption_class: str = "tool_failure",
) -> dict[str, Any]:
    runtime, write_path = _load_runtime()
    current_status = normalize_status(
        status_override if status_override is not None else runtime.get("status")
    )
    primitives = compose_primitives(
        runtime,
        write_path,
        interruption_class=interruption_class,
    )

    transition = explain_transition(
        intent=intent,
        current_status=current_status,
        primitives=primitives,
    )

    next_status = str(transition.get("next_status") or current_status)
    warnings = list(transition.get("warnings", []))
    problems: list[str] = []
    if intent not in ALLOWED_INTENTS:
        problems.append("unknown intent")
    if primitives.get("loop_guard", {}).get("halted"):
        warnings.append(
            f"loop guard halted: {primitives.get('loop_guard', {}).get('reason_code', 'unknown')}"
        )

    result = "PASS" if not problems and transition.get("result") == "PASS" else "FAIL"
    return {
        "result": result,
        "intent": intent,
        "status": next_status,
        "phase": PHASE_BY_STATUS.get(next_status, "planning"),
        "effective_intent": transition.get("effective_intent", intent),
        "reason_code": transition.get("reason_code", "autoflow_transition_allowed"),
        "primitives": primitives,
        "trace": transition.get("trace", []),
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/start-work status --json",
            "/start-work doctor --json",
            "/resume status --json",
        ],
        "config": str(write_path),
    }


def command_status(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    payload = evaluate_request("status")
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"result: {payload['result']}")
    print(f"status: {payload['status']}")
    print(f"phase: {payload['phase']}")
    print(f"checkpoint_count: {payload['primitives']['checkpoint']['count']}")
    print(f"config: {payload['config']}")
    return 0


def command_explain(args: list[str]) -> int:
    json_output = "--json" in args
    intent = ""
    status_override: str | None = None
    interruption_class = "tool_failure"

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--intent":
            if index + 1 >= len(args):
                return usage()
            intent = args[index + 1].strip()
            index += 2
            continue
        if token == "--status":
            if index + 1 >= len(args):
                return usage()
            status_override = args[index + 1].strip()
            index += 2
            continue
        if token == "--interruption-class":
            if index + 1 >= len(args):
                return usage()
            interruption_class = args[index + 1].strip()
            index += 2
            continue
        return usage()

    if intent not in ALLOWED_INTENTS:
        return usage()

    payload = evaluate_request(
        intent,
        status_override=status_override,
        interruption_class=interruption_class,
    )
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"intent: {intent}")
        print(f"effective_intent: {payload['effective_intent']}")
        print(f"status: {payload['status']}")
        print(f"reason_code: {payload['reason_code']}")
        for warning in payload.get("warnings", []):
            print(f"- warning: {warning}")
    return 0 if payload["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return command_status([])
    command = argv[0]
    rest = argv[1:]
    if command in ("help", "--help", "-h"):
        return usage()
    if command == "status":
        return command_status(rest)
    if command == "explain":
        return command_explain(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
