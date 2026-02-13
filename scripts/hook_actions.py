#!/usr/bin/env python3

from __future__ import annotations

from typing import Any


def continuation_reminder(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    checklist = data.get("checklist")
    if not isinstance(checklist, list):
        return {
            "hook_id": "continuation-reminder",
            "triggered": False,
            "reason": "checklist_unavailable",
            "reminder": None,
        }

    pending = [item for item in checklist if isinstance(item, str) and item.strip()]
    if not pending:
        return {
            "hook_id": "continuation-reminder",
            "triggered": False,
            "reason": "no_pending_items",
            "reminder": None,
        }

    preview = pending[:3]
    suffix = "" if len(pending) <= 3 else f" (+{len(pending) - 3} more)"
    return {
        "hook_id": "continuation-reminder",
        "triggered": True,
        "reason": "pending_checklist_items",
        "pending_count": len(pending),
        "pending_preview": preview,
        "reminder": f"Continue unfinished checklist items before ending turn{suffix}.",
    }


def output_truncation_safety(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    text = data.get("text")
    if not isinstance(text, str):
        text = ""

    max_chars = data.get("max_chars", 12_000)
    max_lines = data.get("max_lines", 220)
    if not isinstance(max_chars, int) or max_chars < 200:
        max_chars = 12_000
    if not isinstance(max_lines, int) or max_lines < 20:
        max_lines = 220

    lines = text.splitlines()
    truncated_lines = lines[:max_lines]
    text_by_lines = "\n".join(truncated_lines)

    line_truncated = len(lines) > max_lines
    char_truncated = len(text_by_lines) > max_chars

    if char_truncated:
        text_by_lines = text_by_lines[:max_chars]

    if not line_truncated and not char_truncated:
        return {
            "hook_id": "truncate-safety",
            "triggered": False,
            "truncated": False,
            "text": text,
            "warnings": [],
        }

    warnings = [
        "tool output was truncated for safety",
        "use read/grep with narrower scope for full details",
    ]
    return {
        "hook_id": "truncate-safety",
        "triggered": True,
        "truncated": True,
        "line_truncated": line_truncated,
        "char_truncated": char_truncated,
        "original_line_count": len(lines),
        "output_line_count": len(text_by_lines.splitlines()),
        "max_lines": max_lines,
        "max_chars": max_chars,
        "text": text_by_lines,
        "warnings": warnings,
    }


def error_recovery_hint(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    command = str(data.get("command") or "").strip()
    stderr = str(data.get("stderr") or "").strip()
    stdout = str(data.get("stdout") or "").strip()
    exit_code = data.get("exit_code")

    if not isinstance(exit_code, int) or exit_code == 0:
        return {
            "hook_id": "error-hints",
            "triggered": False,
            "hint": None,
            "category": None,
        }

    haystack = f"{stderr}\n{stdout}".lower()

    hint = (
        "rerun with a narrower scope and inspect stderr/stdout for exact failing step"
    )
    category = "generic_failure"

    if "command not found" in haystack or "not recognized as" in haystack:
        category = "command_not_found"
        hint = "verify the command exists, then install missing tooling or fix PATH"
    elif "no such file or directory" in haystack:
        category = "path_missing"
        hint = "verify file paths exist and use repo-relative paths where possible"
    elif "permission denied" in haystack:
        category = "permission_denied"
        hint = "check file permissions and avoid writing outside allowed directories"
    elif "not a git repository" in haystack:
        category = "git_context"
        hint = "run command from repository root or pass explicit workdir"
    elif "timed out" in haystack or exit_code == 124:
        category = "timeout"
        hint = "retry with a longer timeout or split work into smaller commands"

    return {
        "hook_id": "error-hints",
        "triggered": True,
        "category": category,
        "command": command,
        "exit_code": exit_code,
        "hint": hint,
    }
