#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_DAEMON_STATE_PATH",
        "~/.config/opencode/my_opencode/runtime/daemon_state.json",
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /daemon start [--swarm <sec>] [--metrics <sec>] [--hooks <sec>] [--json] | "
        "/daemon stop [--json] | /daemon status [--json] | /daemon summary [--json] | /daemon doctor [--json]"
    )
    return 2


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def parse_flag(argv: list[str], flag: str, default: int) -> int:
    if flag not in argv:
        return default
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = int(argv[idx + 1])
    del argv[idx : idx + 2]
    return max(1, value)


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'daemon command failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        print(f"status: {payload.get('status', 'unknown')}")
    return 0 if payload.get("result") == "PASS" else 1


def cmd_start(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        swarm_interval = parse_flag(argv, "--swarm", 3)
        metrics_interval = parse_flag(argv, "--metrics", 30)
        hooks_interval = parse_flag(argv, "--hooks", 60)
    except (ValueError, TypeError):
        return usage()
    state = {
        "status": "running",
        "started_at": now_iso(),
        "intervals": {
            "swarm": swarm_interval,
            "metrics": metrics_interval,
            "hooks": hooks_interval,
        },
        "last_tick_at": now_iso(),
        "tick_count": 1,
    }
    save_state(DEFAULT_STATE_PATH, state)
    return emit({"result": "PASS", "command": "start", **state}, as_json)


def cmd_stop(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_state(DEFAULT_STATE_PATH)
    if not state:
        return emit(
            {
                "result": "PASS",
                "command": "stop",
                "status": "stopped",
                "warnings": ["daemon was not running"],
            },
            as_json,
        )
    state["status"] = "stopped"
    state["stopped_at"] = now_iso()
    save_state(DEFAULT_STATE_PATH, state)
    return emit({"result": "PASS", "command": "stop", **state}, as_json)


def cmd_status(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_state(DEFAULT_STATE_PATH)
    if not state:
        return emit(
            {
                "result": "PASS",
                "command": "status",
                "status": "stopped",
                "warnings": ["daemon state not initialized"],
            },
            as_json,
        )
    return emit({"result": "PASS", "command": "status", **state}, as_json)


def cmd_summary(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_state(DEFAULT_STATE_PATH)
    status = str(state.get("status") or "stopped")
    intervals = (
        state.get("intervals") if isinstance(state.get("intervals"), dict) else {}
    )
    summary = {
        "result": "PASS",
        "command": "summary",
        "status": status,
        "tick_count": int(state.get("tick_count", 0) or 0),
        "swarm_interval": intervals.get("swarm", 3),
        "metrics_interval": intervals.get("metrics", 30),
        "hooks_interval": intervals.get("hooks", 60),
        "last_tick_at": state.get("last_tick_at"),
    }
    return emit(summary, as_json)


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_state(DEFAULT_STATE_PATH)
    warnings: list[str] = []
    if not state:
        warnings.append("daemon has not been started in this environment")
    if state and state.get("status") != "running":
        warnings.append("daemon is not running")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "status": str(state.get("status") or "stopped"),
            "path": str(DEFAULT_STATE_PATH),
            "warnings": warnings,
            "quick_fixes": [
                "/daemon start --json",
                "/daemon summary --json",
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
    if command == "start":
        return cmd_start(rest)
    if command == "stop":
        return cmd_stop(rest)
    if command == "status":
        return cmd_status(rest)
    if command == "summary":
        return cmd_summary(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
