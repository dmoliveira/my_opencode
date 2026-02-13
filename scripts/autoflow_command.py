#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from autoflow_adapter import evaluate_request  # type: ignore
from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
)


SECTION = "plan_execution"
START_WORK_SCRIPT = SCRIPT_DIR / "start_work_command.py"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /autoflow start <plan.md> [--deviation <note> ...] [--json] | "
        "/autoflow dry-run <plan.md> [--json] | "
        "/autoflow status [--json] | "
        "/autoflow report [--json] | "
        "/autoflow resume --interruption-class <tool_failure|timeout|context_reset|process_crash> [--approve-step <ordinal> ...] [--json] | "
        "/autoflow stop [--reason <text>] [--json]"
    )
    return 2


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(START_WORK_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _load_runtime() -> tuple[dict[str, Any], Path, dict[str, Any]]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime_any = config.get(SECTION)
    runtime = runtime_any if isinstance(runtime_any, dict) else {}
    return config, write_path, runtime


def _emit(payload: dict[str, Any], json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload.get('result', 'PASS')}")
        print(f"status: {payload.get('status', 'unknown')}")
        if payload.get("phase"):
            print(f"phase: {payload.get('phase')}")
        if payload.get("reason_code"):
            print(f"reason_code: {payload.get('reason_code')}")
        for warning in payload.get("warnings", []):
            print(f"- warning: {warning}")
        for problem in payload.get("problems", []):
            print(f"- problem: {problem}")
        if payload.get("config"):
            print(f"config: {payload.get('config')}")
    return 0 if payload.get("result") == "PASS" else 1


def _parse_start_args(args: list[str]) -> tuple[str, list[str], bool] | None:
    json_output = "--json" in args
    if not args:
        return None
    plan_path = ""
    deviations: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--deviation":
            if index + 1 >= len(args):
                return None
            deviations.append(args[index + 1].strip())
            index += 2
            continue
        if token.startswith("-"):
            return None
        if plan_path:
            return None
        plan_path = token
        index += 1
    if not plan_path:
        return None
    return plan_path, deviations, json_output


def command_start(args: list[str]) -> int:
    parsed = _parse_start_args(args)
    if parsed is None:
        return usage()
    plan_path, deviations, json_output = parsed

    gate = evaluate_request("start")
    if gate.get("result") != "PASS":
        gate_payload = {
            "result": "FAIL",
            "status": gate.get("status", "unknown"),
            "phase": gate.get("phase"),
            "reason_code": gate.get("reason_code", "autoflow_start_blocked"),
            "warnings": gate.get("warnings", []),
            "problems": gate.get(
                "problems", ["autoflow start is blocked by runtime state"]
            ),
            "trace": gate.get("trace", []),
            "config": gate.get("config"),
        }
        return _emit(gate_payload, json_output)

    cmd = [plan_path]
    for note in deviations:
        cmd.extend(["--deviation", note])
    cmd.append("--json")
    result = _run_script(*cmd)
    if not result.stdout.strip():
        payload = {
            "result": "FAIL",
            "status": "failed",
            "reason_code": "autoflow_start_no_output",
            "warnings": [],
            "problems": [result.stderr.strip() or "start-work returned no output"],
        }
        return _emit(payload, json_output)

    payload = json.loads(result.stdout)
    payload.setdefault("result", "PASS" if result.returncode == 0 else "FAIL")
    return _emit(payload, json_output)


def command_dry_run(args: list[str]) -> int:
    parsed = _parse_start_args(args)
    if parsed is None:
        return usage()
    plan_path, _, json_output = parsed
    decision = evaluate_request("dry-run")
    payload = {
        "result": decision.get("result", "PASS"),
        "status": decision.get("status", "idle"),
        "phase": decision.get("phase", "planning"),
        "reason_code": decision.get("reason_code", "autoflow_transition_allowed"),
        "plan": {"path": plan_path},
        "mutating": False,
        "effective_intent": decision.get("effective_intent", "dry-run"),
        "trace": decision.get("trace", []),
        "warnings": decision.get("warnings", []),
        "problems": decision.get("problems", []),
        "config": decision.get("config"),
    }
    return _emit(payload, json_output)


def command_status(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    payload = evaluate_request("status")
    return _emit(payload, json_output)


def command_report(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    status_payload = evaluate_request("report")
    result = _run_script("deviations", "--json")
    deviations_payload = (
        json.loads(result.stdout)
        if result.stdout.strip()
        else {"result": "PASS", "deviations": [], "count": 0}
    )
    payload = {
        "result": status_payload.get("result", "PASS"),
        "status": status_payload.get("status", "unknown"),
        "phase": status_payload.get("phase", "planning"),
        "reason_code": status_payload.get("reason_code", "autoflow_transition_allowed"),
        "primitives": status_payload.get("primitives", {}),
        "deviations": deviations_payload.get("deviations", []),
        "deviation_count": deviations_payload.get("count", 0),
        "trace": status_payload.get("trace", []),
        "warnings": status_payload.get("warnings", []),
        "problems": status_payload.get("problems", []),
        "config": status_payload.get("config"),
    }
    return _emit(payload, json_output)


def command_resume(args: list[str]) -> int:
    json_output = "--json" in args
    interruption_class = ""
    approved_steps: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--interruption-class":
            if index + 1 >= len(args):
                return usage()
            interruption_class = args[index + 1].strip()
            index += 2
            continue
        if token == "--approve-step":
            if index + 1 >= len(args):
                return usage()
            approved_steps.append(args[index + 1].strip())
            index += 2
            continue
        return usage()

    if not interruption_class:
        return usage()

    gate = evaluate_request("resume", interruption_class=interruption_class)
    gate_reason = str(gate.get("reason_code") or "")
    approved = {item for item in approved_steps if item.strip()}
    allow_non_idempotent_approved = (
        gate_reason == "resume_non_idempotent_step" and bool(approved)
    )
    if gate.get("result") != "PASS" and not allow_non_idempotent_approved:
        gate_payload = {
            "result": "FAIL",
            "status": gate.get("status", "unknown"),
            "phase": gate.get("phase"),
            "reason_code": gate.get("reason_code", "resume_not_eligible"),
            "warnings": gate.get("warnings", []),
            "problems": gate.get("problems", ["autoflow resume is blocked"]),
            "trace": gate.get("trace", []),
            "config": gate.get("config"),
        }
        return _emit(gate_payload, json_output)

    cmd = ["recover", "--interruption-class", interruption_class]
    for step in approved_steps:
        cmd.extend(["--approve-step", step])
    cmd.append("--json")
    result = _run_script(*cmd)
    if not result.stdout.strip():
        payload = {
            "result": "FAIL",
            "status": "failed",
            "reason_code": "autoflow_resume_no_output",
            "warnings": [],
            "problems": [
                result.stderr.strip() or "start-work recover returned no output"
            ],
        }
        return _emit(payload, json_output)

    payload = json.loads(result.stdout)
    payload.setdefault("result", "PASS" if result.returncode == 0 else "FAIL")
    return _emit(payload, json_output)


def command_stop(args: list[str]) -> int:
    json_output = "--json" in args
    reason = "operator stop"
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--reason":
            if index + 1 >= len(args):
                return usage()
            reason = args[index + 1].strip() or reason
            index += 2
            continue
        return usage()

    config, write_path, runtime = _load_runtime()
    runtime["status"] = "stopped"
    runtime["stop"] = {
        "reason": reason,
        "actor": "autoflow stop",
        "at": now_iso(),
    }
    config[SECTION] = runtime
    save_config_file(config, write_path)

    payload = evaluate_request("status")
    payload["result"] = "PASS"
    payload["status"] = "stopped"
    payload["reason_code"] = "autoflow_kill_switch_triggered"
    payload.setdefault("warnings", []).append("autoflow stop requested by operator")
    payload["stop"] = runtime.get("stop", {})
    return _emit(payload, json_output)


def main(argv: list[str]) -> int:
    if not argv:
        return command_status([])

    command = argv[0]
    rest = argv[1:]
    if command in {"help", "--help", "-h"}:
        return usage()
    if command == "start":
        return command_start(rest)
    if command == "dry-run":
        return command_dry_run(rest)
    if command == "status":
        return command_status(rest)
    if command == "report":
        return command_report(rest)
    if command == "resume":
        return command_resume(rest)
    if command == "stop":
        return command_stop(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
