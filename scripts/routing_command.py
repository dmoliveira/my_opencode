#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from model_routing_command import (  # type: ignore
    load_state,
    run_resolve,
)


def usage() -> int:
    print(
        "usage: /routing status [--json] | /routing explain [--category <name>] [--override-model <id>] [--available-models <csv>] [--json]"
    )
    return 2


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, state, _ = load_state()
    latest_trace = state.get("latest_trace")
    selected = {}
    if isinstance(latest_trace, dict):
        selected = latest_trace.get("selected", {})
        if not isinstance(selected, dict):
            selected = {}
    payload = {
        "result": "PASS",
        "active_category": state.get("active_category"),
        "selected_model": selected.get("model"),
        "selected_reason": selected.get("reason"),
        "has_trace": bool(latest_trace),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"active_category: {payload['active_category']}")
    print(f"selected_model: {payload['selected_model'] or '(none)'}")
    print(f"selected_reason: {payload['selected_reason'] or '(none)'}")
    print(f"has_trace: {'yes' if payload['has_trace'] else 'no'}")
    return 0


def command_explain(argv: list[str]) -> int:
    json_output = "--json" in argv
    filtered = [arg for arg in argv if arg != "--json"]

    allowed_flags = {
        "--category",
        "--override-model",
        "--override-temperature",
        "--override-reasoning",
        "--override-verbosity",
        "--available-models",
    }
    idx = 0
    while idx < len(filtered):
        token = filtered[idx]
        if token not in allowed_flags or idx + 1 >= len(filtered):
            return usage()
        idx += 2

    _, state, _ = load_state()
    report = run_resolve(state, filtered)
    if report.get("result") != "PASS":
        print(json.dumps(report, indent=2))
        return 1

    compact = {
        "result": "PASS",
        "requested_category": report.get("requested_category"),
        "selected_category": report.get("category"),
        "selected_model": report.get("settings", {}).get("model"),
        "fallback_reason": report.get("trace", [])[-1].get("reason")
        if isinstance(report.get("trace"), list) and report.get("trace")
        else None,
        "attempted_count": len(report.get("resolution_trace", {}).get("attempted", []))
        if isinstance(report.get("resolution_trace"), dict)
        else 0,
        "resolution_trace": report.get("resolution_trace", {}),
    }

    if json_output:
        print(json.dumps(compact, indent=2))
        return 0
    print(f"requested_category: {compact['requested_category']}")
    print(f"selected_category: {compact['selected_category']}")
    print(f"selected_model: {compact['selected_model']}")
    print(f"fallback_reason: {compact['fallback_reason']}")
    print(f"attempted_count: {compact['attempted_count']}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command == "status":
        return command_status(rest)
    if command == "explain":
        return command_explain(rest)
    if command in {"help", "--help", "-h"}:
        return usage()
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
