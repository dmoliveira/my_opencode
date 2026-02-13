#!/usr/bin/env python3

from __future__ import annotations

from typing import Any

TODO_STATES = {"pending", "in_progress", "done", "skipped"}
TODO_TRANSITIONS = {
    ("pending", "in_progress"),
    ("in_progress", "done"),
    ("in_progress", "skipped"),
}
_BYPASS_TYPES = {"risk_acceptance", "scope_change", "emergency_hotfix"}
_BYPASS_REQUIRED = ("bypass_reason", "bypass_actor", "bypass_at", "bypass_type")

_REMEDIATION_HINTS = {
    "unknown_todo_state": "Normalize todo states to pending, in_progress, done, or skipped.",
    "multiple_in_progress_items": "Keep exactly one item in progress before continuing execution.",
    "invalid_transition": "Move todos through pending -> in_progress -> done|skipped, or add a valid bypass annotation.",
    "missing_bypass_metadata": "Provide bypass_reason, bypass_actor, bypass_at, and bypass_type to authorize non-standard transitions.",
    "incomplete_todo_set": "Finish or explicitly skip all remaining pending/in_progress items before marking plan completion.",
}


def normalize_todo_state(value: Any) -> str:
    state = str(value or "").strip()
    if state == "completed":
        return "done"
    return state


def _todo_id(todo: dict[str, Any], fallback_index: int) -> str:
    value = todo.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    ordinal = todo.get("ordinal")
    if isinstance(ordinal, int):
        return f"todo-{ordinal}"
    return f"todo-{fallback_index}"


def _is_valid_bypass(bypass: dict[str, Any] | None) -> bool:
    if not isinstance(bypass, dict):
        return False
    for key in _BYPASS_REQUIRED:
        value = bypass.get(key)
        if not isinstance(value, str) or not value.strip():
            return False
    return str(bypass.get("bypass_type")) in _BYPASS_TYPES


def validate_todo_transition(
    *,
    todo_id: str,
    from_state: str,
    to_state: str,
    bypass: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source = normalize_todo_state(from_state)
    target = normalize_todo_state(to_state)

    if source not in TODO_STATES:
        return {
            "code": "unknown_todo_state",
            "todo_id": todo_id,
            "from": source,
            "to": target,
            "message": f"unknown source state: {source}",
        }
    if target not in TODO_STATES:
        return {
            "code": "unknown_todo_state",
            "todo_id": todo_id,
            "from": source,
            "to": target,
            "message": f"unknown target state: {target}",
        }
    if (source, target) in TODO_TRANSITIONS:
        return None
    if source == "pending" and target in {"done", "skipped"}:
        if _is_valid_bypass(bypass):
            return None
        return {
            "code": "missing_bypass_metadata",
            "todo_id": todo_id,
            "from": source,
            "to": target,
            "message": "direct pending transition requires full bypass metadata",
        }
    return {
        "code": "invalid_transition",
        "todo_id": todo_id,
        "from": source,
        "to": target,
        "message": "transition is not allowed by compliance model",
    }


def validate_todo_set(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    in_progress_ids: list[str] = []
    for index, todo in enumerate(todos, start=1):
        todo_id = _todo_id(todo, index)
        state = normalize_todo_state(todo.get("state"))
        if state not in TODO_STATES:
            violations.append(
                {
                    "code": "unknown_todo_state",
                    "todo_id": todo_id,
                    "state": state,
                    "message": "todo item has unsupported state",
                }
            )
            continue
        if state == "in_progress":
            in_progress_ids.append(todo_id)

    if len(in_progress_ids) > 1:
        violations.append(
            {
                "code": "multiple_in_progress_items",
                "todo_ids": in_progress_ids,
                "message": "only one todo item may be in progress at a time",
            }
        )
    return violations


def validate_plan_completion(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    incomplete_ids: list[str] = []
    for index, todo in enumerate(todos, start=1):
        todo_id = _todo_id(todo, index)
        state = normalize_todo_state(todo.get("state"))
        if state not in {"done", "skipped"}:
            incomplete_ids.append(todo_id)
    if not incomplete_ids:
        return []
    return [
        {
            "code": "incomplete_todo_set",
            "todo_ids": incomplete_ids,
            "message": "plan completion is blocked because required todo items remain unchecked",
        }
    ]


def remediation_prompts(violations: list[dict[str, Any]]) -> list[str]:
    prompts: list[str] = []
    for violation in violations:
        code = str(violation.get("code") or "")
        prompt = _REMEDIATION_HINTS.get(code)
        if prompt and prompt not in prompts:
            prompts.append(prompt)
    return prompts


def build_transition_event(
    *,
    todo_id: str,
    from_state: str,
    to_state: str,
    at: str,
    actor: str,
) -> dict[str, Any]:
    return {
        "event": "todo_transition",
        "todo_id": todo_id,
        "from": normalize_todo_state(from_state),
        "to": normalize_todo_state(to_state),
        "at": at,
        "actor": actor,
        "compliance": "enforced",
    }


def build_bypass_event(
    *,
    todo_id: str,
    from_state: str,
    to_state: str,
    at: str,
    actor: str,
    bypass: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event": "todo_bypass",
        "todo_id": todo_id,
        "from": normalize_todo_state(from_state),
        "to": normalize_todo_state(to_state),
        "at": at,
        "actor": actor,
        "bypass": {
            "type": str(bypass.get("bypass_type") or ""),
            "reason": str(bypass.get("bypass_reason") or ""),
            "authorized_by": str(bypass.get("bypass_actor") or ""),
        },
    }
