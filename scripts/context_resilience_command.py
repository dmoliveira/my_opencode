#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path  # type: ignore
from context_resilience import (  # type: ignore
    build_recovery_plan,
    prune_context,
    resolve_policy,
)


SECTION = "resilience"


def usage() -> int:
    print("usage: /resilience status [--json] | /resilience doctor [--json]")
    return 2


def load_state() -> tuple[dict[str, Any], dict[str, Any], list[str], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    raw = config.get(SECTION)
    raw_dict = raw if isinstance(raw, dict) else {}
    policy, problems = resolve_policy(raw_dict)
    return config, policy, problems, write_path


def _stress_messages() -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in range(1, 121):
        messages.append(
            {
                "role": "assistant",
                "kind": "analysis",
                "content": f"analysis-turn-{turn % 7}",
                "turn": turn,
            }
        )
        if turn % 9 == 0:
            messages.append(
                {
                    "role": "tool",
                    "tool_name": "write",
                    "kind": "write",
                    "target_path": "README.md",
                    "content": f"draft-{turn}",
                    "turn": turn,
                }
            )
        if turn % 11 == 0:
            messages.append(
                {
                    "role": "tool",
                    "tool_name": "bash",
                    "kind": "error",
                    "command": "make validate",
                    "exit_code": 1,
                    "content": "transient failure",
                    "turn": turn,
                }
            )
    messages.append(
        {
            "role": "tool",
            "tool_name": "bash",
            "kind": "result",
            "command": "make validate",
            "exit_code": 0,
            "content": "validation pass",
            "turn": 130,
        }
    )
    messages.append(
        {
            "role": "assistant",
            "kind": "decision",
            "content": "continue with integration",
            "turn": 131,
        }
    )
    return messages


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, policy, problems, write_path = load_state()
    payload = {
        "enabled": bool(policy.get("enabled", True)),
        "truncation_mode": str(policy.get("truncation_mode", "default")),
        "notification_level": str(policy.get("notification_level", "normal")),
        "protected_tools": list(policy.get("protected_tools", [])),
        "protected_message_kinds": list(policy.get("protected_message_kinds", [])),
        "validation_problems": problems,
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"enabled: {'yes' if payload['enabled'] else 'no'}")
    print(f"truncation_mode: {payload['truncation_mode']}")
    print(f"notification_level: {payload['notification_level']}")
    print(f"protected_tools: {','.join(payload['protected_tools']) or '(none)'}")
    print(
        "protected_message_kinds: "
        f"{','.join(payload['protected_message_kinds']) or '(none)'}"
    )
    print(
        f"validation_problems: {','.join(payload['validation_problems']) or '(none)'}"
    )
    print(f"config: {payload['config']}")
    return 0


def command_doctor(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv

    _, policy, problems, write_path = load_state()
    stress_messages = _stress_messages()
    pruned = prune_context(stress_messages, policy, max_messages=48)
    recovery = build_recovery_plan(stress_messages, pruned, policy)
    can_resume = bool(recovery.get("can_resume"))

    payload = {
        "result": "PASS" if not problems and can_resume else "FAIL",
        "enabled": bool(policy.get("enabled", True)),
        "stress_input_count": len(stress_messages),
        "stress_kept_count": int(pruned.get("kept_count", 0)),
        "stress_dropped_count": int(pruned.get("dropped_count", 0)),
        "recovery_action": recovery.get("recovery_action"),
        "can_resume": can_resume,
        "warnings": list(problems),
        "problems": [] if can_resume else ["stress recovery plan has no resume anchor"],
        "quick_fixes": [
            "/resilience status --json",
            "/resilience doctor --json",
        ],
        "config": str(write_path),
    }

    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"result: {payload['result']}")
    print(f"enabled: {'yes' if payload['enabled'] else 'no'}")
    print(f"stress_input_count: {payload['stress_input_count']}")
    print(f"stress_kept_count: {payload['stress_kept_count']}")
    print(f"stress_dropped_count: {payload['stress_dropped_count']}")
    print(f"recovery_action: {payload['recovery_action']}")
    print(f"can_resume: {'yes' if payload['can_resume'] else 'no'}")
    print(f"config: {payload['config']}")
    return 0 if payload["result"] == "PASS" else 1


def main() -> int:
    if len(sys.argv) < 2:
        return usage()
    command = sys.argv[1]
    argv = sys.argv[2:]
    if command == "status":
        return command_status(argv)
    if command == "doctor":
        return command_doctor(argv)
    if command in {"help", "-h", "--help"}:
        return usage()
    return usage()


if __name__ == "__main__":
    raise SystemExit(main())
