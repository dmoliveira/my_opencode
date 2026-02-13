#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
)
from plan_execution_runtime import load_plan_execution_state  # type: ignore
from execution_budget_runtime import (  # type: ignore
    DEFAULT_PROFILE,
    PROFILE_LIMITS,
    resolve_budget_policy,
)


SECTION = "budget_runtime"
LIMIT_FIELDS = ("wall_clock_seconds", "tool_call_count", "token_estimate")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /budget status [--json] | "
        "/budget profile <conservative|balanced|extended> | "
        "/budget override [--wall-clock-seconds <n>] [--tool-call-count <n>] [--token-estimate <n>] [--clear] [--reason <text>] [--json] | "
        "/budget doctor [--json]"
    )
    return 2


def _load() -> tuple[dict[str, Any], Path]:
    config, _ = load_layered_config()
    return config, resolve_write_path()


def _section(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get(SECTION)
    if isinstance(raw, dict):
        return dict(raw)
    return {
        "profile": DEFAULT_PROFILE,
        "overrides": {},
        "updated_at": None,
        "updated_by": "system",
        "override_reason": None,
    }


def _save(config: dict[str, Any], write_path: Path, section: dict[str, Any]) -> None:
    config[SECTION] = section
    save_config_file(config, write_path)


def _parse_positive_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def command_status(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args

    config, write_path = _load()
    section = _section(config)
    policy = resolve_budget_policy(config)
    runtime, _ = load_plan_execution_state(config, write_path)
    runtime_budget = runtime.get("budget", {})

    report = {
        "result": "PASS",
        "profile": policy.get("profile"),
        "limits": policy.get("limits"),
        "overrides": section.get("overrides", {}),
        "runtime_budget": runtime_budget,
        "updated_at": section.get("updated_at"),
        "updated_by": section.get("updated_by"),
        "override_reason": section.get("override_reason"),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"profile: {report['profile']}")
        print(f"limits: {json.dumps(report['limits'])}")
        print(f"overrides: {json.dumps(report['overrides'])}")
        runtime_result = (
            runtime_budget.get("result") if isinstance(runtime_budget, dict) else None
        )
        if runtime_result:
            print(f"runtime_budget: {runtime_result}")
        print(f"config: {write_path}")
    return 0


def command_profile(args: list[str]) -> int:
    if len(args) != 1:
        return usage()
    profile = args[0].strip()
    if profile not in PROFILE_LIMITS:
        return usage()

    config, write_path = _load()
    section = _section(config)
    section["profile"] = profile
    section["updated_at"] = now_iso()
    section["updated_by"] = "budget profile"
    section.setdefault("overrides", {})
    _save(config, write_path, section)

    print(f"profile: {profile}")
    print(f"limits: {json.dumps(PROFILE_LIMITS[profile])}")
    print(f"config: {write_path}")
    return 0


def command_override(args: list[str]) -> int:
    json_output = "--json" in args
    clear = "--clear" in args
    reason: str | None = None
    updates: dict[str, int] = {}

    index = 0
    while index < len(args):
        token = args[index]
        if token in ("--json", "--clear"):
            index += 1
            continue
        if token == "--reason":
            if index + 1 >= len(args):
                return usage()
            reason = args[index + 1].strip()
            index += 2
            continue
        if token == "--wall-clock-seconds":
            if index + 1 >= len(args):
                return usage()
            parsed = _parse_positive_int(args[index + 1])
            if parsed is None:
                return usage()
            updates["wall_clock_seconds"] = parsed
            index += 2
            continue
        if token == "--tool-call-count":
            if index + 1 >= len(args):
                return usage()
            parsed = _parse_positive_int(args[index + 1])
            if parsed is None:
                return usage()
            updates["tool_call_count"] = parsed
            index += 2
            continue
        if token == "--token-estimate":
            if index + 1 >= len(args):
                return usage()
            parsed = _parse_positive_int(args[index + 1])
            if parsed is None:
                return usage()
            updates["token_estimate"] = parsed
            index += 2
            continue
        return usage()

    if not clear and not updates and reason is None:
        return usage()

    config, write_path = _load()
    section = _section(config)
    if clear:
        section["overrides"] = {}
    else:
        current = section.get("overrides")
        overrides = current if isinstance(current, dict) else {}
        for key, value in updates.items():
            overrides[key] = value
        section["overrides"] = overrides
    section["override_reason"] = reason
    section["updated_at"] = now_iso()
    section["updated_by"] = "budget override"
    _save(config, write_path, section)

    report = {
        "result": "PASS",
        "profile": section.get("profile", DEFAULT_PROFILE),
        "overrides": section.get("overrides", {}),
        "override_reason": section.get("override_reason"),
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"profile: {report['profile']}")
        print(f"overrides: {json.dumps(report['overrides'])}")
        print(f"config: {write_path}")
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    config, write_path = _load()
    section = _section(config)
    policy = resolve_budget_policy(config)
    runtime, _ = load_plan_execution_state(config, write_path)
    runtime_budget = runtime.get("budget") if isinstance(runtime, dict) else {}

    warnings: list[str] = []
    problems: list[str] = []
    profile = str(policy.get("profile") or DEFAULT_PROFILE)
    if profile not in PROFILE_LIMITS:
        problems.append(f"unknown budget profile: {profile}")

    runtime_result = (
        str(runtime_budget.get("result") or "")
        if isinstance(runtime_budget, dict)
        else ""
    )
    if runtime_result == "WARN":
        warnings.append("runtime budget is near configured thresholds")
    if runtime_result == "FAIL":
        warnings.append("runtime budget exceeded hard limit in latest run")

    overrides = section.get("overrides")
    if isinstance(overrides, dict):
        for key in LIMIT_FIELDS:
            value = overrides.get(key)
            if value is None:
                continue
            if not isinstance(value, int) or value <= 0:
                problems.append(f"override {key} must be a positive integer")

    report = {
        "result": "PASS" if not problems else "FAIL",
        "profile": profile,
        "limits": policy.get("limits"),
        "runtime_result": runtime_result or None,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/budget status --json",
            "/budget profile balanced",
            "/budget override --clear --json",
        ],
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        for warning in warnings:
            print(f"- warning: {warning}")
        for problem in problems:
            print(f"- problem: {problem}")
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("status",):
        return command_status(argv[1:] if argv and argv[0] == "status" else [])

    command = argv[0]
    rest = argv[1:]
    if command in ("help", "--help", "-h"):
        return usage()
    if command == "profile":
        return command_profile(rest)
    if command == "override":
        return command_override(rest)
    if command == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
