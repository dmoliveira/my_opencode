#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from autopilot_integration import integrate_controls  # type: ignore
from autopilot_runtime import execute_cycle, initialize_run, load_runtime, save_runtime  # type: ignore
from config_layering import load_layered_config, resolve_write_path  # type: ignore


def usage() -> int:
    print(
        "usage: /autopilot [start|status|pause|resume|stop|report|doctor] [--json] "
        "| /autopilot start --goal <text> --scope <text> --done-criteria <text> --max-budget <profile> [--json] "
        "| /autopilot resume [--confidence <0-1>] [--tool-calls <n>] [--token-estimate <n>] [--touched-paths <csv>] [--json]"
    )
    return 2


def pop_flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def pop_value(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag not in args:
        return default
    idx = args.index(flag)
    if idx + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    value = args[idx + 1]
    del args[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _runtime_or_fail(
    write_path: Path, *, as_json: bool
) -> tuple[dict[str, Any] | None, int]:
    runtime = load_runtime(write_path)
    if runtime:
        return runtime, 0
    emit(
        {
            "result": "FAIL",
            "reason_code": "autopilot_runtime_missing",
            "remediation": [
                "run /autopilot start with required objective fields",
                "use /autopilot doctor --json to inspect subsystem readiness",
            ],
        },
        as_json=as_json,
    )
    return None, 1


def command_start(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        goal = pop_value(args, "--goal")
        scope = pop_value(args, "--scope")
        done_criteria = pop_value(args, "--done-criteria")
        max_budget = pop_value(args, "--max-budget", "balanced")
    except ValueError:
        return usage()
    if args:
        return usage()

    inferred_defaults: list[str] = []
    if not goal:
        goal = (
            "continue the active user request from current session context until done"
        )
        inferred_defaults.append("goal")
    if not scope:
        scope = "**"
        inferred_defaults.append("scope")
    if not done_criteria:
        done_criteria = goal
        inferred_defaults.append("done-criteria")

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    objective = {
        "goal": goal or "",
        "scope": scope or "",
        "done-criteria": done_criteria or "",
        "max-budget": max_budget or "balanced",
    }
    initialized = initialize_run(
        config=config,
        write_path=write_path,
        objective=objective,
        actor="autopilot",
    )
    if inferred_defaults:
        initialized["inferred_defaults"] = inferred_defaults
        initialized["warnings"] = initialized.get("warnings", [])
        if isinstance(initialized["warnings"], list):
            initialized["warnings"].append(
                "autopilot inferred missing objective fields; use explicit fields for tighter control"
            )
    emit(initialized, as_json=as_json)
    return 0 if initialized.get("result") == "PASS" else 1


def command_status(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        confidence_raw = pop_value(args, "--confidence", "0.8") or "0.8"
        interruption_class = (
            pop_value(args, "--interruption-class", "tool_failure") or "tool_failure"
        )
    except ValueError:
        return usage()
    if args:
        return usage()
    try:
        confidence = float(confidence_raw)
    except ValueError:
        return usage()

    _, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime = load_runtime(write_path)
    if not runtime:
        emit(
            {
                "result": "PASS",
                "status": "idle",
                "reason_code": "autopilot_runtime_missing",
                "warnings": [
                    "autopilot has no active runtime yet; start a run to track status"
                ],
                "next_actions": [
                    "run /autopilot start with required objective fields",
                    "use /autopilot doctor --json to inspect subsystem readiness",
                ],
            },
            as_json=as_json,
        )
        return 0

    integrated = integrate_controls(
        run=runtime,
        write_path=write_path,
        confidence_score=confidence,
        interruption_class=interruption_class,
    )
    emit(integrated, as_json=as_json)
    return 0


def command_pause(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    if args:
        return usage()

    _, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    runtime["status"] = "paused"
    runtime["reason_code"] = "operator_paused"
    runtime["next_actions"] = [
        "review blockers and confidence before resume",
        "run /autopilot resume when safe to continue",
    ]
    path = save_runtime(write_path, runtime)
    emit(
        {
            "result": "PASS",
            "status": runtime["status"],
            "reason_code": runtime["reason_code"],
            "runtime_path": str(path),
        },
        as_json=as_json,
    )
    return 0


def command_resume(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        confidence_raw = pop_value(args, "--confidence", "0.8") or "0.8"
        tool_calls_raw = pop_value(args, "--tool-calls", "1") or "1"
        token_raw = pop_value(args, "--token-estimate", "100") or "100"
        touched_paths_raw = pop_value(args, "--touched-paths", "") or ""
    except ValueError:
        return usage()
    if args:
        return usage()
    try:
        confidence = float(confidence_raw)
        tool_calls = max(0, int(tool_calls_raw))
        token_estimate = max(0, int(token_raw))
    except ValueError:
        return usage()
    touched_paths = [
        path.strip() for path in touched_paths_raw.split(",") if path.strip()
    ]

    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    integrated = integrate_controls(
        run=runtime,
        write_path=write_path,
        confidence_score=confidence,
    )
    handoff_mode = (
        integrated.get("control_integrations", {})
        .get("manual_handoff", {})
        .get("mode", "auto")
    )
    if handoff_mode == "manual":
        emit(integrated, as_json=as_json)
        return 1

    resumed = execute_cycle(
        config=config,
        write_path=write_path,
        run=integrated.get("run", runtime),
        tool_call_increment=tool_calls,
        token_increment=token_estimate,
        touched_paths=touched_paths,
    )
    emit(resumed, as_json=as_json)
    return 0 if resumed.get("result") == "PASS" else 1


def command_stop(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    reason = "manual"
    try:
        reason = pop_value(args, "--reason", "manual") or "manual"
    except ValueError:
        return usage()
    if args:
        return usage()

    _, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    runtime["status"] = "stopped"
    runtime["reason_code"] = "autopilot_stop_requested"
    runtime["stop_reason"] = reason
    runtime["next_actions"] = [
        "use /autopilot report to inspect final progress and blockers",
        "use /autopilot start to begin a new objective run",
    ]
    path = save_runtime(write_path, runtime)
    emit(
        {
            "result": "PASS",
            "status": runtime["status"],
            "reason_code": runtime["reason_code"],
            "stop_reason": runtime["stop_reason"],
            "runtime_path": str(path),
        },
        as_json=as_json,
    )
    return 0


def command_report(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    if args:
        return usage()

    _, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, code = _runtime_or_fail(write_path, as_json=as_json)
    if runtime is None:
        return code

    progress = (
        runtime.get("progress", {}) if isinstance(runtime.get("progress"), dict) else {}
    )
    payload = {
        "result": "PASS",
        "run_id": runtime.get("run_id"),
        "status": runtime.get("status"),
        "reason_code": runtime.get("reason_code"),
        "summary": {
            "goal": runtime.get("objective", {}).get("goal")
            if isinstance(runtime.get("objective"), dict)
            else None,
            "completed_cycles": progress.get("completed_cycles", 0),
            "pending_cycles": progress.get("pending_cycles", 0),
        },
        "blockers": runtime.get("blockers", []),
        "next_actions": runtime.get("next_actions", []),
    }
    emit(payload, as_json=as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    report = {
        "result": "PASS"
        if (SCRIPT_DIR / "autopilot_runtime.py").exists()
        and (SCRIPT_DIR / "autopilot_integration.py").exists()
        and (
            SCRIPT_DIR.parent / "instructions" / "autopilot_command_contract.md"
        ).exists()
        else "FAIL",
        "runtime_exists": (SCRIPT_DIR / "autopilot_runtime.py").exists(),
        "integration_exists": (SCRIPT_DIR / "autopilot_integration.py").exists(),
        "contract_exists": (
            SCRIPT_DIR.parent / "instructions" / "autopilot_command_contract.md"
        ).exists(),
        "warnings": [],
        "problems": [],
        "quick_fixes": [
            "/autopilot start --goal 'Ship objective' --scope 'scripts/**' --done-criteria 'all checks pass' --max-budget balanced --json",
            "/autopilot status --json",
            "/autopilot report --json",
        ],
    }
    if not report["runtime_exists"]:
        report["problems"].append("missing scripts/autopilot_runtime.py")
    if not report["integration_exists"]:
        report["problems"].append("missing scripts/autopilot_integration.py")
    if not report["contract_exists"]:
        report["warnings"].append("missing instructions/autopilot_command_contract.md")
    emit(report, as_json=as_json)
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return command_status(["--json"])
    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "start":
        return command_start(rest)
    if cmd == "status":
        return command_status(rest)
    if cmd == "pause":
        return command_pause(rest)
    if cmd == "resume":
        return command_resume(rest)
    if cmd == "stop":
        return command_stop(rest)
    if cmd == "report":
        return command_report(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
