#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
START_WORK_SCRIPT = SCRIPT_DIR / "start_work_command.py"


def usage() -> int:
    print(
        "usage: /autoflow start <plan.md> [--deviation <note> ...] [--background] [--json] | "
        "/autoflow status [--json] | /autoflow report [--json] | /autoflow resume --interruption-class <class> [--approve-step <ordinal> ...] [--json] | /autoflow doctor [--json]"
    )
    return 2


def _run_backend(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(START_WORK_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _emit(
    completed: subprocess.CompletedProcess[str], payload: dict[str, Any] | None = None
) -> int:
    if payload is not None:
        print(json.dumps(payload, indent=2))
    elif completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


def _rewrite_entrypoint(payload: dict[str, Any]) -> dict[str, Any]:
    raw_routing = payload.get("model_routing")
    routing: dict[str, Any] = raw_routing if isinstance(raw_routing, dict) else {}
    payload["model_routing"] = {**routing, "entrypoint": "autoflow"}
    return payload


def _run_and_rewrite_json(args: list[str]) -> int:
    completed = _run_backend(args)
    if completed.returncode != 0:
        return _emit(completed)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return _emit(completed)
    if isinstance(payload, dict):
        _rewrite_entrypoint(payload)
        if "state" not in payload and "status" in payload:
            payload["state"] = payload.get("status")
        if "phase" not in payload and "status" in payload:
            payload["phase"] = payload.get("status")
        return _emit(completed, payload)
    return _emit(completed)


def _run_status(rest: list[str]) -> int:
    return (
        _run_and_rewrite_json(["status", *rest])
        if "--json" in rest
        else _emit(_run_backend(["status", *rest]))
    )


def _run_report(rest: list[str]) -> int:
    if "--json" not in rest:
        return _emit(_run_backend(["deviations", *rest]))
    status_completed = _run_backend(["status", *rest])
    deviations_completed = _run_backend(["deviations", *rest])
    if status_completed.returncode != 0:
        return _emit(status_completed)
    if deviations_completed.returncode != 0:
        return _emit(deviations_completed)
    try:
        status_payload = json.loads(status_completed.stdout)
        deviations_payload = json.loads(deviations_completed.stdout)
    except json.JSONDecodeError:
        return _emit(deviations_completed)
    if not isinstance(status_payload, dict) or not isinstance(deviations_payload, dict):
        return _emit(deviations_completed)
    payload: dict[str, Any] = {
        "result": status_payload.get("result", "PASS"),
        "state": status_payload.get("status", "idle"),
        "status": status_payload.get("status", "idle"),
        "phase": status_payload.get("status", "idle"),
        "plan": status_payload.get("plan", {}),
        "summary": {
            "status": status_payload.get("status", "idle"),
            "step_counts": status_payload.get("step_counts", {}),
            "deviation_count": deviations_payload.get("count", 0),
        },
        "step_counts": status_payload.get("step_counts", {}),
        "todo_compliance": status_payload.get("todo_compliance", {}),
        "budget": status_payload.get("budget", {}),
        "blockers": status_payload.get("task_graph", {}).get("blocked", []),
        "next_actions": deviations_payload.get("quick_fixes", []),
        "recommendations": deviations_payload.get("quick_fixes", []),
        "deviations": {
            "count": deviations_payload.get("count", 0),
            "entries": deviations_payload.get("deviations", []),
        },
        "task_graph_path": status_payload.get("task_graph_path"),
        "task_graph": status_payload.get("task_graph", {}),
        "config": status_payload.get("config"),
        "quick_fixes": deviations_payload.get("quick_fixes", []),
    }
    _rewrite_entrypoint(payload)
    return _emit(status_completed, payload)


def main(argv: list[str]) -> int:
    if not START_WORK_SCRIPT.exists():
        print("autoflow: backend unavailable (missing start_work_command.py)")
        return 1

    if not argv or argv[0] in {"help", "-h", "--help"}:
        return usage()

    command = argv[0]
    rest = argv[1:]

    if command == "start":
        if not rest:
            return usage()
        return (
            _run_and_rewrite_json(rest)
            if "--json" in rest
            else _emit(_run_backend(rest))
        )

    if command == "status":
        return _run_status(rest)

    if command == "report":
        return _run_report(rest)

    if command == "resume":
        args = ["recover", *rest]
        return (
            _run_and_rewrite_json(args)
            if "--json" in rest
            else _emit(_run_backend(args))
        )

    if command == "doctor":
        args = ["doctor", *rest]
        return (
            _run_and_rewrite_json(args)
            if "--json" in rest
            else _emit(_run_backend(args))
        )

    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
