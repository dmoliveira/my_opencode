#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_HOOK_LEARNING_PATH",
        "~/.config/opencode/my_opencode/runtime/hook_learning.json",
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /hook-learning pre-command <command> [--json] | /hook-learning post-command <command> --success <true|false> [--json] | "
        "/hook-learning route <task> [--json] | /hook-learning metrics [--json] | /hook-learning doctor [--json]"
    )
    return 2


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "events": [],
            "routes": [],
            "metrics": {
                "pre_command": 0,
                "post_command": 0,
                "routed": 0,
                "high_risk": 0,
            },
        }
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {
            "version": 1,
            "events": [],
            "routes": [],
            "metrics": {
                "pre_command": 0,
                "post_command": 0,
                "routed": 0,
                "high_risk": 0,
            },
        }
    if not isinstance(raw.get("events"), list):
        raw["events"] = []
    if not isinstance(raw.get("routes"), list):
        raw["routes"] = []
    if not isinstance(raw.get("metrics"), dict):
        raw["metrics"] = {
            "pre_command": 0,
            "post_command": 0,
            "routed": 0,
            "high_risk": 0,
        }
    return raw


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'hook-learning failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("risk") is not None:
            print(f"risk: {payload.get('risk')}")
        if payload.get("recommended_agent"):
            print(f"recommended_agent: {payload.get('recommended_agent')}")
    return 0 if payload.get("result") == "PASS" else 1


def assess_risk(command: str) -> tuple[str, list[str]]:
    lowered = command.lower()
    reasons: list[str] = []
    if re.search(r"\brm\b\s+-rf", lowered):
        reasons.append("destructive_delete")
    if "--force" in lowered or "force" in lowered:
        reasons.append("force_flag")
    if "sudo" in lowered:
        reasons.append("privileged_command")
    if not reasons:
        return "low", []
    if "destructive_delete" in reasons or "privileged_command" in reasons:
        return "high", reasons
    return "medium", reasons


def recommend_agent(task: str) -> str:
    lowered = task.lower()
    if any(token in lowered for token in ["test", "verify", "qa"]):
        return "verifier"
    if any(token in lowered for token in ["review", "security", "risk"]):
        return "reviewer"
    if any(token in lowered for token in ["research", "docs", "reference"]):
        return "librarian"
    if any(token in lowered for token in ["explore", "where is", "find"]):
        return "explore"
    return "orchestrator"


def cmd_pre_command(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    command = " ".join(argv).strip()
    if not command:
        return usage()
    risk, reasons = assess_risk(command)
    state = load_state(DEFAULT_STATE_PATH)
    events = state.get("events") if isinstance(state.get("events"), list) else []
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    events.insert(
        0,
        {
            "type": "pre-command",
            "command": command,
            "risk": risk,
            "reasons": reasons,
            "at": now_iso(),
        },
    )
    metrics["pre_command"] = int(metrics.get("pre_command", 0) or 0) + 1
    if risk == "high":
        metrics["high_risk"] = int(metrics.get("high_risk", 0) or 0) + 1
    state["events"] = events[:500]
    state["metrics"] = metrics
    save_state(DEFAULT_STATE_PATH, state)
    return emit(
        {
            "result": "PASS",
            "command": "pre-command",
            "risk": risk,
            "reasons": reasons,
            "suggestions": [
                "use dry-run flags when available",
                "capture pre/post state for destructive operations",
            ],
        },
        as_json,
    )


def cmd_post_command(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if "--success" not in argv:
        return usage()
    idx = argv.index("--success")
    if idx + 1 >= len(argv):
        return usage()
    success_raw = argv[idx + 1].strip().lower()
    success = success_raw in {"true", "1", "yes", "y", "pass"}
    del argv[idx : idx + 2]
    if not argv:
        return usage()
    command = " ".join(argv)
    state = load_state(DEFAULT_STATE_PATH)
    events = state.get("events") if isinstance(state.get("events"), list) else []
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    events.insert(
        0,
        {
            "type": "post-command",
            "command": command,
            "success": success,
            "at": now_iso(),
        },
    )
    metrics["post_command"] = int(metrics.get("post_command", 0) or 0) + 1
    state["events"] = events[:500]
    state["metrics"] = metrics
    save_state(DEFAULT_STATE_PATH, state)
    return emit(
        {
            "result": "PASS",
            "command": "post-command",
            "success": success,
            "recorded": True,
        },
        as_json,
    )


def cmd_route(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    task = " ".join(argv).strip()
    if not task:
        return usage()
    agent = recommend_agent(task)
    confidence = 0.7
    if agent in {"verifier", "reviewer", "librarian", "explore"}:
        confidence = 0.86
    state = load_state(DEFAULT_STATE_PATH)
    routes = state.get("routes") if isinstance(state.get("routes"), list) else []
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    routes.insert(
        0,
        {
            "task": task,
            "recommended_agent": agent,
            "confidence": confidence,
            "at": now_iso(),
        },
    )
    metrics["routed"] = int(metrics.get("routed", 0) or 0) + 1
    state["routes"] = routes[:200]
    state["metrics"] = metrics
    save_state(DEFAULT_STATE_PATH, state)
    return emit(
        {
            "result": "PASS",
            "command": "route",
            "task": task,
            "recommended_agent": agent,
            "confidence": confidence,
        },
        as_json,
    )


def cmd_metrics(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_state(DEFAULT_STATE_PATH)
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    return emit(
        {
            "result": "PASS",
            "command": "metrics",
            "metrics": metrics,
            "recent_routes": (state.get("routes") or [])[:10],
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_state(DEFAULT_STATE_PATH)
    metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
    warnings: list[str] = []
    if int(metrics.get("pre_command", 0) or 0) == 0:
        warnings.append("no pre-command risk events recorded yet")
    if int(metrics.get("routed", 0) or 0) == 0:
        warnings.append("no route decisions recorded yet")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "path": str(DEFAULT_STATE_PATH),
            "metrics": metrics,
            "warnings": warnings,
            "quick_fixes": [
                '/hook-learning pre-command "make validate" --json',
                '/hook-learning route "review API risks" --json',
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
    if command == "pre-command":
        return cmd_pre_command(rest)
    if command == "post-command":
        return cmd_post_command(rest)
    if command == "route":
        return cmd_route(rest)
    if command == "metrics":
        return cmd_metrics(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
