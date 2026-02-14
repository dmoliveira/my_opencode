#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
)
from plan_execution_runtime import (  # type: ignore
    load_plan_execution_state,
    save_plan_execution_state,
)
from recovery_engine import (  # type: ignore
    build_resume_hints,
    execute_resume,
    evaluate_resume_eligibility,
    explain_resume_reason,
)


DEFAULT_INTERRUPTION_CLASS = "tool_failure"


def usage() -> int:
    print(
        "usage: /resume status [--interruption-class <class>] [--json] | "
        "/resume now [--interruption-class <class>] [--approve-step <ordinal> ...] [--json] | "
        "/resume disable [--json]"
    )
    return 2


def _load_runtime() -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    runtime, _ = load_plan_execution_state(config, write_path)
    return config, runtime, write_path


def _save_runtime(
    config: dict[str, Any], write_path: Path, runtime: dict[str, Any]
) -> None:
    save_plan_execution_state(config, write_path, runtime)


def _default_interruption_class(runtime: dict[str, Any]) -> str:
    resume_meta = runtime.get("resume")
    if isinstance(resume_meta, dict):
        value = str(resume_meta.get("last_interruption_class") or "").strip()
        if value:
            return value
    return DEFAULT_INTERRUPTION_CLASS


def _actor(runtime: dict[str, Any]) -> str:
    raw_plan = runtime.get("plan")
    if isinstance(raw_plan, dict):
        metadata = raw_plan.get("metadata")
        if isinstance(metadata, dict):
            return str(metadata.get("owner") or "system")
    return "system"


def command_status(args: list[str]) -> int:
    json_output = "--json" in args
    interruption_class = ""

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
        return usage()

    config, runtime, write_path = _load_runtime()
    _ = config
    if not runtime:
        report = {
            "result": "PASS",
            "enabled": True,
            "status": "idle",
            "interruption_class": DEFAULT_INTERRUPTION_CLASS,
            "reason_code": "resume_missing_checkpoint",
            "reason": explain_resume_reason("resume_missing_checkpoint"),
            "cooldown_remaining": 0,
            "attempt_count": 0,
            "max_attempts": 3,
            "checkpoint": None,
            "resume_hints": build_resume_hints(
                "resume_missing_checkpoint",
                interruption_class=DEFAULT_INTERRUPTION_CLASS,
            ),
            "eligible": False,
            "warnings": [
                "no checkpoint found yet; create one by running /autopilot or /autopilot go first"
            ],
            "config": str(write_path),
        }
        print(json.dumps(report, indent=2) if json_output else report["reason"])
        return 0

    interruption = interruption_class or _default_interruption_class(runtime)
    eligibility = evaluate_resume_eligibility(runtime, interruption)
    reason_code = str(
        eligibility.get("reason_code") or "resume_missing_runtime_artifacts"
    )
    report = {
        "result": "PASS" if eligibility.get("eligible") else "FAIL",
        "enabled": bool((runtime.get("resume") or {}).get("enabled", True))
        if isinstance(runtime.get("resume"), dict)
        else True,
        "status": runtime.get("status", "idle"),
        "interruption_class": interruption,
        "eligible": bool(eligibility.get("eligible")),
        "reason_code": reason_code,
        "reason": explain_resume_reason(
            reason_code,
            cooldown_remaining=int(eligibility.get("cooldown_remaining", 0) or 0),
        ),
        "cooldown_remaining": int(eligibility.get("cooldown_remaining", 0) or 0),
        "attempt_count": int(eligibility.get("attempt_count", 0) or 0),
        "max_attempts": int(eligibility.get("max_attempts", 0) or 0),
        "checkpoint": eligibility.get("checkpoint"),
        "resume_hints": build_resume_hints(
            reason_code,
            interruption_class=interruption,
            checkpoint=(
                eligibility.get("checkpoint")
                if isinstance(eligibility.get("checkpoint"), dict)
                else None
            ),
            cooldown_remaining=int(eligibility.get("cooldown_remaining", 0) or 0),
        ),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"enabled: {'yes' if report['enabled'] else 'no'}")
        print(f"status: {report['status']}")
        print(f"interruption_class: {report['interruption_class']}")
        print(f"eligible: {'yes' if report['eligible'] else 'no'}")
        print(f"reason: {report['reason']}")
        print(f"attempts: {report['attempt_count']}/{report['max_attempts']}")
        hints = report.get("resume_hints", {})
        actions = hints.get("next_actions", []) if isinstance(hints, dict) else []
        if actions:
            print("resume_hints:")
            for action in actions:
                print(f"- {action}")
        print(f"config: {report['config']}")
    return 0


def command_now(args: list[str]) -> int:
    json_output = "--json" in args
    interruption_class = ""
    approved_steps: set[int] = set()

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
            try:
                approved_steps.add(int(args[index + 1]))
            except ValueError:
                return usage()
            index += 2
            continue
        return usage()

    config, runtime, write_path = _load_runtime()
    if not runtime:
        report = {
            "result": "FAIL",
            "reason_code": "resume_missing_checkpoint",
            "reason": explain_resume_reason("resume_missing_checkpoint"),
            "resume_hints": build_resume_hints(
                "resume_missing_checkpoint",
                interruption_class=DEFAULT_INTERRUPTION_CLASS,
            ),
            "config": str(write_path),
        }
        print(json.dumps(report, indent=2) if json_output else report["reason"])
        return 1

    interruption = interruption_class or _default_interruption_class(runtime)
    resume_result = execute_resume(
        runtime,
        interruption,
        approved_steps=approved_steps,
        actor=_actor(runtime),
    )

    next_runtime = resume_result.get("runtime")
    if isinstance(next_runtime, dict):
        _save_runtime(config, write_path, next_runtime)

    reason_code = str(
        resume_result.get("reason_code") or "resume_missing_runtime_artifacts"
    )
    report = {
        "result": resume_result.get("result", "FAIL"),
        "status": next_runtime.get("status")
        if isinstance(next_runtime, dict)
        else None,
        "interruption_class": interruption,
        "reason_code": reason_code,
        "reason": explain_resume_reason(
            reason_code,
            cooldown_remaining=int(resume_result.get("cooldown_remaining", 0) or 0),
        ),
        "cooldown_remaining": int(resume_result.get("cooldown_remaining", 0) or 0),
        "checkpoint": resume_result.get("checkpoint"),
        "resumed_steps": resume_result.get("resumed_steps", []),
        "resume_hints": build_resume_hints(
            reason_code,
            interruption_class=interruption,
            checkpoint=(
                resume_result.get("checkpoint")
                if isinstance(resume_result.get("checkpoint"), dict)
                else None
            ),
            cooldown_remaining=int(resume_result.get("cooldown_remaining", 0) or 0),
        ),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"status: {report['status']}")
        print(f"reason: {report['reason']}")
        print(f"resumed_steps: {len(report['resumed_steps'])}")
        hints = report.get("resume_hints", {})
        actions = hints.get("next_actions", []) if isinstance(hints, dict) else []
        if actions:
            print("resume_hints:")
            for action in actions:
                print(f"- {action}")
        print(f"config: {report['config']}")
    return 0 if report["result"] == "PASS" else 1


def command_disable(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args

    config, runtime, write_path = _load_runtime()
    resume_any = runtime.get("resume")
    resume = dict(resume_any) if isinstance(resume_any, dict) else {}
    resume["enabled"] = False
    runtime["resume"] = resume
    if not runtime.get("status"):
        runtime["status"] = "idle"
    _save_runtime(config, write_path, runtime)

    report = {
        "result": "PASS",
        "enabled": False,
        "reason": explain_resume_reason("resume_disabled"),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print("enabled: no")
        print(f"reason: {report['reason']}")
        print(f"config: {report['config']}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in ("help", "--help", "-h"):
        return usage()
    if command == "status":
        return command_status(rest)
    if command == "now":
        return command_now(rest)
    if command == "disable":
        return command_disable(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
