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
from todo_enforcement import (  # type: ignore
    normalize_todo_state,
    remediation_prompts,
    validate_plan_completion,
    validate_todo_set,
)


def usage() -> int:
    print("usage: /todo status [--json] | /todo enforce [--json]")
    return 2


def _load_runtime() -> tuple[dict[str, Any], Path]:
    config, _ = load_layered_config()
    runtime = config.get("plan_execution")
    if not isinstance(runtime, dict):
        runtime = {}
    return runtime, resolve_write_path()


def _normalized_steps(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = runtime.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        item = dict(step)
        item["id"] = item.get("id") or f"todo-{item.get('ordinal', index)}"
        item["state"] = normalize_todo_state(item.get("state"))
        normalized.append(item)
    return normalized


def _build_report(
    runtime: dict[str, Any], write_path: Path, enforce_completion: bool
) -> dict[str, Any]:
    status = str(runtime.get("status") or "idle")
    plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
    steps = _normalized_steps(runtime)

    violations = validate_todo_set(steps)
    if enforce_completion:
        violations.extend(validate_plan_completion(steps))

    stored = runtime.get("todo_compliance")
    stored_result = "unknown"
    if isinstance(stored, dict):
        stored_result = str(stored.get("result") or "unknown")

    counts = {
        "total": len(steps),
        "done": sum(1 for step in steps if step.get("state") == "done"),
        "pending": sum(1 for step in steps if step.get("state") == "pending"),
        "in_progress": sum(1 for step in steps if step.get("state") == "in_progress"),
        "skipped": sum(1 for step in steps if step.get("state") == "skipped"),
    }

    result = "PASS" if not violations else "FAIL"
    return {
        "result": result,
        "status": status,
        "plan": plan,
        "step_counts": counts,
        "checked_completion": enforce_completion,
        "stored_compliance_result": stored_result,
        "violations": violations,
        "remediation": remediation_prompts(violations),
        "config": str(write_path),
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"result: {report.get('result')}")
    print(f"status: {report.get('status')}")
    counts = report.get("step_counts", {})
    if isinstance(counts, dict):
        print(
            "steps: "
            f"done={counts.get('done', 0)} "
            f"pending={counts.get('pending', 0)} "
            f"in_progress={counts.get('in_progress', 0)} "
            f"skipped={counts.get('skipped', 0)}"
        )
    print(f"stored_compliance: {report.get('stored_compliance_result')}")
    for item in report.get("violations", []):
        if isinstance(item, dict):
            print(
                f"- violation[{item.get('code', 'unknown')}]: {item.get('message', '')}"
            )
    for prompt in report.get("remediation", []):
        if isinstance(prompt, str):
            print(f"- remediation: {prompt}")
    print(f"config: {report.get('config')}")


def command_status(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    runtime, write_path = _load_runtime()
    report = _build_report(runtime, write_path, enforce_completion=False)
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    return 0 if report.get("result") == "PASS" else 1


def command_enforce(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    json_output = "--json" in args
    runtime, write_path = _load_runtime()
    report = _build_report(runtime, write_path, enforce_completion=True)
    if json_output:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    return 0 if report.get("result") == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in ("help", "--help", "-h"):
        return usage()
    if command == "status":
        return command_status(rest)
    if command == "enforce":
        return command_enforce(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
