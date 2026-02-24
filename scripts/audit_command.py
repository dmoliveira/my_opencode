#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path

from runtime_audit import DEFAULT_AUDIT_PATH, append_event, load_audit  # type: ignore


def usage() -> int:
    print(
        "usage: /audit status [--json] | /audit list [--limit <n>] [--json] | /audit export --path <file> [--json] | /audit doctor [--json]"
    )
    return 2


def emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'audit command failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("count") is not None:
            print(f"count: {payload.get('count')}")
    return 0 if payload.get("result") == "PASS" else 1


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def cmd_status(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_audit(DEFAULT_AUDIT_PATH)
    events = state.get("events") if isinstance(state.get("events"), list) else []
    latest = events[0] if events and isinstance(events[0], dict) else {}
    return emit(
        {
            "result": "PASS",
            "command": "status",
            "path": str(DEFAULT_AUDIT_PATH),
            "count": len(events),
            "latest": latest,
        },
        as_json,
    )


def cmd_list(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    limit = 20
    if "--limit" in argv:
        idx = argv.index("--limit")
        if idx + 1 >= len(argv):
            return usage()
        try:
            limit = max(1, int(argv[idx + 1]))
        except ValueError:
            return usage()
    state = load_audit(DEFAULT_AUDIT_PATH)
    events = state.get("events") if isinstance(state.get("events"), list) else []
    return emit(
        {
            "result": "PASS",
            "command": "list",
            "count": min(limit, len(events)),
            "events": events[:limit],
        },
        as_json,
    )


def cmd_export(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        target = parse_flag_value(argv, "--path")
    except ValueError:
        return usage()
    if not target:
        return usage()
    path = Path(target).expanduser()
    state = load_audit(DEFAULT_AUDIT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    append_event("audit", "export", "PASS", {"path": str(path)})
    return emit(
        {
            "result": "PASS",
            "command": "export",
            "path": str(path),
            "count": len(state.get("events", [])),
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_audit(DEFAULT_AUDIT_PATH)
    events = state.get("events") if isinstance(state.get("events"), list) else []
    warnings: list[str] = []
    if not events:
        warnings.append("audit log is empty; run mutating commands to populate it")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "path": str(DEFAULT_AUDIT_PATH),
            "count": len(events),
            "warnings": warnings,
            "quick_fixes": [
                "/claims claim issue-1 --by human:alex --json",
                "/audit list --json",
            ],
        },
        as_json,
    )


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "-h", "--help"}:
        return usage()
    if command == "status":
        return cmd_status(rest)
    if command == "list":
        return cmd_list(rest)
    if command == "export":
        return cmd_export(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
