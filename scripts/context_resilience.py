#!/usr/bin/env python3

from __future__ import annotations

from collections import Counter
from typing import Any


DEFAULT_PROTECTED_TOOLS = ["bash", "read", "edit", "write", "apply_patch"]
DEFAULT_PROTECTED_MESSAGE_KINDS = ["error", "result", "decision"]


def default_policy() -> dict[str, Any]:
    return {
        "enabled": True,
        "truncation_mode": "default",
        "protected_tools": list(DEFAULT_PROTECTED_TOOLS),
        "protected_message_kinds": list(DEFAULT_PROTECTED_MESSAGE_KINDS),
        "notification_level": "normal",
        "old_error_turn_threshold": 4,
    }


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        normalized.append(item.strip())
    return normalized


def resolve_policy(
    raw_policy: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    policy = default_policy()
    problems: list[str] = []
    if raw_policy is None:
        return policy, problems

    enabled = raw_policy.get("enabled")
    if enabled is not None:
        if isinstance(enabled, bool):
            policy["enabled"] = enabled
        else:
            problems.append("resilience.enabled must be a boolean")

    truncation_mode = str(raw_policy.get("truncation_mode", "")).strip().lower()
    if truncation_mode:
        if truncation_mode in {"default", "aggressive"}:
            policy["truncation_mode"] = truncation_mode
            policy["old_error_turn_threshold"] = (
                2 if truncation_mode == "aggressive" else 4
            )
        else:
            problems.append(
                "resilience.truncation_mode must be one of: default, aggressive"
            )

    notification_level = str(raw_policy.get("notification_level", "")).strip().lower()
    if notification_level:
        if notification_level in {"quiet", "normal", "verbose"}:
            policy["notification_level"] = notification_level
        else:
            problems.append(
                "resilience.notification_level must be one of: quiet, normal, verbose"
            )

    protected_tools = _string_list(raw_policy.get("protected_tools"))
    if protected_tools is None:
        problems.append("resilience.protected_tools must be a list of strings")
    elif protected_tools:
        policy["protected_tools"] = protected_tools

    protected_kinds = _string_list(raw_policy.get("protected_message_kinds"))
    if protected_kinds is None:
        problems.append("resilience.protected_message_kinds must be a list of strings")
    elif protected_kinds:
        policy["protected_message_kinds"] = protected_kinds

    return policy, problems


def _message_turn(message: dict[str, Any], default_turn: int) -> int:
    turn = message.get("turn")
    if isinstance(turn, int):
        return turn
    return default_turn


def _command_family(message: dict[str, Any]) -> str | None:
    explicit = message.get("command_family")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().lower()
    command = message.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    return command.strip().split()[0].lower()


def _is_protected(message: dict[str, Any], policy: dict[str, Any]) -> bool:
    kind = str(message.get("kind", "")).strip().lower()
    if kind and kind in set(policy.get("protected_message_kinds", [])):
        return True
    tool_name = str(message.get("tool_name", "")).strip().lower()
    if tool_name and tool_name in set(policy.get("protected_tools", [])):
        return True
    return False


def prune_context(
    messages: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    max_messages: int | None = None,
) -> dict[str, Any]:
    if policy.get("enabled") is False:
        return {
            "messages": list(messages),
            "dropped": [],
            "drop_counts": {},
            "kept_count": len(messages),
            "dropped_count": 0,
        }

    drops: dict[int, str] = {}
    current_turn = max(
        (_message_turn(message, idx) for idx, message in enumerate(messages)),
        default=0,
    )

    latest_outcome_by_family: dict[str, int] = {}
    for idx, message in enumerate(messages):
        exit_code = message.get("exit_code")
        family = _command_family(message)
        if family is None or not isinstance(exit_code, int):
            continue
        latest_outcome_by_family[family] = idx

    must_keep = set(latest_outcome_by_family.values())
    for idx, message in enumerate(messages):
        if _is_protected(message, policy):
            must_keep.add(idx)

    seen_fingerprints: set[tuple[str, str, str, str]] = set()
    for idx, message in enumerate(messages):
        if idx in must_keep:
            continue
        role = str(message.get("role", "")).strip().lower()
        kind = str(message.get("kind", "")).strip().lower()
        tool_name = str(message.get("tool_name", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        fingerprint = (role, kind, tool_name, content)
        if fingerprint in seen_fingerprints:
            drops[idx] = "deduplicated"
        else:
            seen_fingerprints.add(fingerprint)

    latest_write_by_target: dict[str, int] = {}
    write_tool_names = {"write", "edit", "apply_patch"}
    for idx, message in enumerate(messages):
        if idx in drops:
            continue
        tool_name = str(message.get("tool_name", "")).strip().lower()
        kind = str(message.get("kind", "")).strip().lower()
        target_path = str(message.get("target_path", "")).strip()
        if target_path and (tool_name in write_tool_names or kind == "write"):
            latest_write_by_target[target_path] = idx

    for idx, message in enumerate(messages):
        if idx in must_keep or idx in drops:
            continue
        tool_name = str(message.get("tool_name", "")).strip().lower()
        kind = str(message.get("kind", "")).strip().lower()
        target_path = str(message.get("target_path", "")).strip()
        if not target_path:
            continue
        if tool_name not in write_tool_names and kind != "write":
            continue
        if latest_write_by_target.get(target_path) != idx:
            drops[idx] = "superseded_write"

    latest_success_turn: dict[str, int] = {}
    for idx, message in enumerate(messages):
        exit_code = message.get("exit_code")
        family = _command_family(message)
        if family is None or not isinstance(exit_code, int):
            continue
        if exit_code == 0:
            latest_success_turn[family] = _message_turn(message, idx)

    threshold = int(policy.get("old_error_turn_threshold", 4))
    for idx, message in enumerate(messages):
        if idx in must_keep or idx in drops:
            continue
        kind = str(message.get("kind", "")).strip().lower()
        if kind != "error":
            continue
        family = _command_family(message)
        if family is None:
            continue
        error_turn = _message_turn(message, idx)
        success_turn = latest_success_turn.get(family)
        if success_turn is None or success_turn <= error_turn:
            continue
        if (current_turn - error_turn) > threshold:
            drops[idx] = "stale_error_purged"

    if str(policy.get("truncation_mode", "default")) == "aggressive":
        for idx, message in enumerate(messages):
            if idx in must_keep or idx in drops:
                continue
            kind = str(message.get("kind", "")).strip().lower()
            turn = _message_turn(message, idx)
            if kind in {"analysis", "thought"} and (current_turn - turn) > 6:
                drops[idx] = "aggressive_old_analysis"

    kept_indices = [idx for idx in range(len(messages)) if idx not in drops]
    if max_messages is not None and len(kept_indices) > max_messages:
        for idx in kept_indices:
            if len(kept_indices) <= max_messages:
                break
            if idx in must_keep:
                continue
            drops[idx] = "budget_trim"
            kept_indices = [item for item in kept_indices if item != idx]

    kept_messages = [messages[idx] for idx in range(len(messages)) if idx not in drops]
    dropped = [
        {"index": idx, "reason": reason} for idx, reason in sorted(drops.items())
    ]
    counts = dict(Counter(reason for reason in drops.values()))
    return {
        "messages": kept_messages,
        "dropped": dropped,
        "drop_counts": counts,
        "kept_count": len(kept_messages),
        "dropped_count": len(dropped),
    }


def build_recovery_plan(
    original_messages: list[dict[str, Any]],
    pruned_report: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    kept_messages = list(pruned_report.get("messages", []))
    drop_counts = dict(pruned_report.get("drop_counts", {}))

    latest_success: dict[str, Any] | None = None
    latest_error: dict[str, Any] | None = None
    for idx, message in enumerate(kept_messages):
        exit_code = message.get("exit_code")
        if isinstance(exit_code, int) and exit_code == 0:
            latest_success = {
                "index": idx,
                "command": str(message.get("command", "")).strip(),
                "tool_name": str(message.get("tool_name", "")).strip(),
            }
        kind = str(message.get("kind", "")).strip().lower()
        if kind == "error":
            latest_error = {
                "index": idx,
                "command": str(message.get("command", "")).strip(),
                "content": str(message.get("content", "")).strip(),
            }

    protected_retained = sum(
        1 for message in kept_messages if _is_protected(message, policy)
    )

    if latest_success:
        command = latest_success.get("command") or "latest successful command"
        plan = {
            "can_resume": True,
            "recovery_action": "resume_hint",
            "resume_hint": f"Resume from the last successful step: `{command}`.",
            "fallback": None,
        }
    elif latest_error:
        failed_command = latest_error.get("command") or "last failed command"
        plan = {
            "can_resume": False,
            "recovery_action": "safe_fallback",
            "resume_hint": None,
            "fallback": {
                "reason": "no_successful_recovery_anchor",
                "steps": [
                    "restore full context snapshot for the current workflow",
                    f"re-run `{failed_command}` in isolation with explicit logging",
                    "request operator review before applying any destructive edits",
                ],
            },
        }
    else:
        plan = {
            "can_resume": True,
            "recovery_action": "resume_hint",
            "resume_hint": "Resume from the latest retained decision and rerun validation.",
            "fallback": None,
        }

    return {
        **plan,
        "diagnostics": {
            "original_count": len(original_messages),
            "kept_count": len(kept_messages),
            "dropped_count": int(pruned_report.get("dropped_count", 0)),
            "drop_counts": drop_counts,
            "protected_retained_count": protected_retained,
            "notification_level": str(policy.get("notification_level", "normal")),
            "truncation_mode": str(policy.get("truncation_mode", "default")),
        },
    }
