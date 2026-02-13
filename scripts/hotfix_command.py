#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hotfix_runtime import load_runtime, resolve_write_path, runtime_path  # type: ignore


HOTFIX_RUNTIME_SCRIPT = SCRIPT_DIR / "hotfix_runtime.py"


def usage() -> int:
    print(
        "usage: /hotfix [start|status|close|remind|doctor] [args] [--json] | "
        "/hotfix start --incident-id <id> --scope <patch|rollback|config_only> --impact <sev1|sev2|sev3> [--json] | "
        "/hotfix close --outcome <resolved|mitigated|rolled_back> --followup-issue <id> --deferred-validation-owner <owner> --deferred-validation-due <date> [--json]"
    )
    return 2


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def run_runtime(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOTFIX_RUNTIME_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def command_passthrough(args: list[str]) -> int:
    proc = run_runtime(args)
    if proc.stdout:
        print(proc.stdout.strip())
    elif proc.stderr:
        print(proc.stderr.strip())
    return proc.returncode


def command_remind(args: list[str]) -> int:
    as_json = "--json" in args
    if any(arg not in ("--json",) for arg in args):
        return usage()

    write_path = resolve_write_path()
    state = load_runtime(write_path)
    timeline = (
        state.get("timeline", []) if isinstance(state.get("timeline"), list) else []
    )
    closed_events = [
        e for e in timeline if isinstance(e, dict) and e.get("event") == "closed"
    ]
    latest = closed_events[-1] if closed_events else None
    details = latest.get("details", {}) if isinstance(latest, dict) else {}

    reminders = [
        "run make selftest and make install-test for deferred full validation",
        "confirm follow-up issue includes prevention and test-hardening tasks",
        "remove temporary overrides introduced during incident mitigation",
    ]

    payload = {
        "result": "PASS",
        "active": bool(state.get("active")),
        "incident_id": state.get("incident_id"),
        "followup_issue": details.get("followup_issue")
        if isinstance(details, dict)
        else None,
        "deferred_validation": details.get("deferred_validation")
        if isinstance(details, dict)
        else None,
        "reminders": reminders,
        "runtime": str(runtime_path(write_path)),
    }
    emit(payload, as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    runtime_exists = HOTFIX_RUNTIME_SCRIPT.exists()
    policy_exists = (
        SCRIPT_DIR.parent / "instructions" / "hotfix_mode_policy_contract.md"
    ).exists()
    report = {
        "result": "PASS" if runtime_exists else "FAIL",
        "runtime_exists": runtime_exists,
        "policy_exists": policy_exists,
        "warnings": [] if policy_exists else ["missing hotfix policy contract"],
        "problems": [] if runtime_exists else ["missing scripts/hotfix_runtime.py"],
        "quick_fixes": [
            "/hotfix start --incident-id INC-1 --scope patch --impact sev2 --json",
            "/hotfix status --json",
            "/hotfix remind --json",
        ],
    }
    emit(report, as_json)
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return command_passthrough(["status", "--json"])

    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "status":
        return command_passthrough(["status", *rest])
    if cmd == "start":
        return command_passthrough(["start", *rest])
    if cmd == "close":
        return command_passthrough(["close", *rest])
    if cmd == "doctor":
        return command_doctor(rest)
    if cmd == "remind":
        return command_remind(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
