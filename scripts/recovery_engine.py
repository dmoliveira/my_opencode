#!/usr/bin/env python3

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


INTERRUPTION_COOLDOWNS = {
    "tool_failure": 30,
    "timeout": 120,
    "context_reset": 10,
    "process_crash": 60,
}
MAX_RESUME_ATTEMPTS_DEFAULT = 3

REASON_MESSAGES = {
    "resume_allowed": "resume is allowed from the latest safe checkpoint",
    "resume_missing_checkpoint": "no checkpoint is available yet; run /start-work first",
    "resume_unknown_interruption_class": "the interruption class is not recognized",
    "resume_missing_runtime_artifacts": "runtime state is incomplete for recovery",
    "resume_attempt_limit_reached": "max resume attempts reached; manual escalation required",
    "resume_blocked_cooldown": "resume is cooling down after the previous attempt",
    "resume_non_idempotent_step": "next step is non-idempotent and requires explicit approval",
    "resume_disabled": "resume is disabled in runtime controls",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _normalize_steps(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = runtime.get("steps")
    if not isinstance(raw_steps, list):
        return []
    steps: list[dict[str, Any]] = []
    for step in raw_steps:
        if isinstance(step, dict):
            steps.append(step)
    return steps


def explain_resume_reason(reason_code: str, *, cooldown_remaining: int = 0) -> str:
    message = REASON_MESSAGES.get(reason_code, reason_code)
    if reason_code == "resume_blocked_cooldown" and cooldown_remaining > 0:
        return f"{message} ({cooldown_remaining}s remaining)"
    return message


def load_last_safe_checkpoint(runtime: dict[str, Any]) -> dict[str, Any]:
    steps = _normalize_steps(runtime)
    if not steps:
        return {
            "available": False,
            "reason_code": "resume_missing_checkpoint",
            "checkpoint": None,
        }
    pending_steps = [
        step
        for step in steps
        if str(step.get("state") or "") in {"pending", "in_progress"}
    ]
    if not pending_steps:
        return {
            "available": True,
            "reason_code": "resume_allowed",
            "checkpoint": {
                "status": "completed",
                "next_step_ordinal": None,
                "next_step_idempotent": True,
            },
        }
    next_step = pending_steps[0]
    return {
        "available": True,
        "reason_code": "resume_allowed",
        "checkpoint": {
            "status": str(runtime.get("status") or "unknown"),
            "next_step_ordinal": next_step.get("ordinal"),
            "next_step_idempotent": bool(next_step.get("idempotent", True)),
        },
    }


def evaluate_resume_eligibility(
    runtime: dict[str, Any],
    interruption_class: str,
    *,
    approved_steps: set[int] | None = None,
    now_ts: str | None = None,
) -> dict[str, Any]:
    approved = approved_steps or set()
    checkpoint_info = load_last_safe_checkpoint(runtime)
    if not checkpoint_info.get("available"):
        return {
            "eligible": False,
            "reason_code": "resume_missing_checkpoint",
            "checkpoint": None,
            "cooldown_remaining": 0,
        }

    if interruption_class not in INTERRUPTION_COOLDOWNS:
        return {
            "eligible": False,
            "reason_code": "resume_unknown_interruption_class",
            "checkpoint": checkpoint_info.get("checkpoint"),
            "cooldown_remaining": 0,
        }

    status = str(runtime.get("status") or "")
    if status not in {"failed", "in_progress", "completed"}:
        return {
            "eligible": False,
            "reason_code": "resume_missing_runtime_artifacts",
            "checkpoint": checkpoint_info.get("checkpoint"),
            "cooldown_remaining": 0,
        }

    resume_meta_any = runtime.get("resume")
    resume_meta: dict[str, Any] = (
        resume_meta_any if isinstance(resume_meta_any, dict) else {}
    )
    attempt_count = int(resume_meta.get("attempt_count", 0) or 0)
    enabled = bool(resume_meta.get("enabled", True))
    if not enabled:
        return {
            "eligible": False,
            "reason_code": "resume_disabled",
            "checkpoint": checkpoint_info.get("checkpoint"),
            "cooldown_remaining": 0,
            "attempt_count": attempt_count,
            "max_attempts": int(
                resume_meta.get("max_attempts", MAX_RESUME_ATTEMPTS_DEFAULT)
                or MAX_RESUME_ATTEMPTS_DEFAULT
            ),
        }

    max_attempts = int(
        resume_meta.get("max_attempts", MAX_RESUME_ATTEMPTS_DEFAULT)
        or MAX_RESUME_ATTEMPTS_DEFAULT
    )
    if attempt_count >= max_attempts:
        return {
            "eligible": False,
            "reason_code": "resume_attempt_limit_reached",
            "checkpoint": checkpoint_info.get("checkpoint"),
            "cooldown_remaining": 0,
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
        }

    current_time = _parse_iso(now_ts or now_iso())
    last_attempt = _parse_iso(resume_meta.get("last_attempt_at"))
    cooldown = INTERRUPTION_COOLDOWNS[interruption_class]
    remaining = 0
    if current_time is not None and last_attempt is not None:
        elapsed = int((current_time - last_attempt).total_seconds())
        if elapsed < cooldown:
            remaining = cooldown - elapsed
    if remaining > 0:
        return {
            "eligible": False,
            "reason_code": "resume_blocked_cooldown",
            "checkpoint": checkpoint_info.get("checkpoint"),
            "cooldown_remaining": remaining,
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
        }

    checkpoint_raw = checkpoint_info.get("checkpoint")
    checkpoint: dict[str, Any] = (
        checkpoint_raw if isinstance(checkpoint_raw, dict) else {}
    )
    next_ordinal = checkpoint.get("next_step_ordinal")
    next_idempotent = bool(checkpoint.get("next_step_idempotent", True))
    if (
        isinstance(next_ordinal, int)
        and (not next_idempotent)
        and next_ordinal not in approved
    ):
        return {
            "eligible": False,
            "reason_code": "resume_non_idempotent_step",
            "checkpoint": checkpoint,
            "cooldown_remaining": 0,
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
        }

    return {
        "eligible": True,
        "reason_code": "resume_allowed",
        "checkpoint": checkpoint,
        "cooldown_remaining": 0,
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
    }


def execute_resume(
    runtime: dict[str, Any],
    interruption_class: str,
    *,
    approved_steps: set[int] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    approved = approved_steps or set()
    next_runtime = deepcopy(runtime)
    evaluation = evaluate_resume_eligibility(
        next_runtime,
        interruption_class,
        approved_steps=approved,
    )
    resume_meta_any = next_runtime.get("resume")
    resume_meta: dict[str, Any] = (
        resume_meta_any if isinstance(resume_meta_any, dict) else {}
    )
    trail_raw = resume_meta.get("trail")
    trail: list[dict[str, Any]] = trail_raw if isinstance(trail_raw, list) else []
    decision_at = now_iso()
    decision = {
        "event": "resume_decision",
        "interruption_class": interruption_class,
        "eligible": bool(evaluation.get("eligible")),
        "reason_code": evaluation.get("reason_code"),
        "cooldown_seconds_remaining": int(evaluation.get("cooldown_remaining", 0) or 0),
        "attempt": int(evaluation.get("attempt_count", 0) or 0) + 1,
        "max_attempts": int(
            evaluation.get("max_attempts", MAX_RESUME_ATTEMPTS_DEFAULT)
            or MAX_RESUME_ATTEMPTS_DEFAULT
        ),
        "at": decision_at,
        "actor": actor,
    }
    trail.append(decision)

    resume_meta["last_interruption_class"] = interruption_class
    resume_meta["last_attempt_at"] = decision_at
    resume_meta["attempt_count"] = int(evaluation.get("attempt_count", 0) or 0) + 1
    resume_meta["max_attempts"] = int(
        evaluation.get("max_attempts", MAX_RESUME_ATTEMPTS_DEFAULT)
        or MAX_RESUME_ATTEMPTS_DEFAULT
    )
    resume_meta["trail"] = trail
    next_runtime["resume"] = resume_meta

    if not evaluation.get("eligible"):
        if evaluation.get("reason_code") == "resume_attempt_limit_reached":
            next_runtime["status"] = "resume_escalated"
        return {
            "result": "FAIL",
            "runtime": next_runtime,
            "reason_code": evaluation.get("reason_code"),
            "cooldown_remaining": int(evaluation.get("cooldown_remaining", 0) or 0),
            "checkpoint": evaluation.get("checkpoint"),
            "resumed_steps": [],
        }

    resumed_steps: list[int] = []
    for step in _normalize_steps(next_runtime):
        state = str(step.get("state") or "")
        if state == "done":
            continue
        ordinal = step.get("ordinal")
        if isinstance(ordinal, int):
            resumed_steps.append(ordinal)
        step["state"] = "in_progress"
        trail.append(
            {
                "event": "resume_transition",
                "step_ordinal": ordinal,
                "to": "in_progress",
                "at": now_iso(),
                "actor": actor,
            }
        )
        step["state"] = "done"
        trail.append(
            {
                "event": "resume_transition",
                "step_ordinal": ordinal,
                "to": "done",
                "at": now_iso(),
                "actor": actor,
            }
        )

    next_runtime["resume"] = resume_meta
    all_done = all(
        str(step.get("state") or "") == "done"
        for step in _normalize_steps(next_runtime)
    )
    next_runtime["status"] = "completed" if all_done else "failed"
    next_runtime["finished_at"] = now_iso()
    return {
        "result": "PASS",
        "runtime": next_runtime,
        "reason_code": "resume_allowed",
        "checkpoint": evaluation.get("checkpoint"),
        "resumed_steps": resumed_steps,
    }
