#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from typing import Any

from hook_actions import (  # type: ignore
    continuation_reminder,
    error_recovery_hint,
    output_truncation_safety,
)


def usage() -> int:
    print(
        "usage: /hooks status | /hooks help | /hooks run <continuation-reminder|truncate-safety|error-hints> [--json '<payload>']"
    )
    return 2


def parse_json(argv: list[str], name: str) -> dict[str, Any]:
    if name not in argv:
        return {}
    idx = argv.index(name)
    if idx + 1 >= len(argv):
        raise ValueError(f"missing value for {name}")
    raw = argv[idx + 1]
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} payload must be an object")
    return parsed


def command_status() -> int:
    print("hooks: baseline")
    print("available:")
    print("- continuation-reminder")
    print("- truncate-safety")
    print("- error-hints")
    return 0


def command_run(argv: list[str]) -> int:
    if not argv:
        return usage()

    hook = argv[0]
    payload = parse_json(argv[1:], "--json")

    if hook == "continuation-reminder":
        report = continuation_reminder(payload)
    elif hook == "truncate-safety":
        report = output_truncation_safety(payload)
    elif hook == "error-hints":
        report = error_recovery_hint(payload)
    else:
        return usage()

    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status()
    if argv[0] == "help":
        return usage()
    if argv[0] == "run":
        return command_run(argv[1:])
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
