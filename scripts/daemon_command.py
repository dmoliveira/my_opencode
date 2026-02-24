#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
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

SCRIPT_DIR = Path(__file__).resolve().parent
CLAIMS_SCRIPT = SCRIPT_DIR / "claims_command.py"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /daemon start [--swarm <sec>] [--metrics <sec>] [--hooks <sec>] [--json] | "
        "/daemon stop [--json] | /daemon status [--json] | /daemon tick [--claims-hours <n>] [--json] | "
        "/daemon summary [--json] | /daemon doctor [--json]"
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


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def run_claims_expire(hours: int) -> dict[str, Any]:
    if not CLAIMS_SCRIPT.exists():
        return {
            "result": "WARN",
            "reason_code": "claims_script_missing",
            "expired_count": 0,
            "updated": [],
        }
    completed = subprocess.run(
        [
            sys.executable,
            str(CLAIMS_SCRIPT),
            "expire-stale",
            "--hours",
            str(hours),
            "--apply",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        loaded = json.loads((completed.stdout or "").strip() or "{}")
        payload = loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        payload = {
            "result": "FAIL",
            "reason_code": "claims_expire_non_json",
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
    raw_updated = payload.get("updated")
    updated = raw_updated if isinstance(raw_updated, list) else []
    return {
        "result": "PASS" if completed.returncode == 0 else "FAIL",
        "claims_payload": payload,
        "expired_count": len(updated),
        "updated": updated,
    }


def intervals_map(state: dict[str, Any]) -> dict[str, int]:
    raw_intervals = state.get("intervals")
    if not isinstance(raw_intervals, dict):
        return {}
    return {
        "swarm": int(raw_intervals.get("swarm", 3) or 3),
        "metrics": int(raw_intervals.get("metrics", 30) or 30),
        "hooks": int(raw_intervals.get("hooks", 60) or 60),
        "claims_expire_hours": int(raw_intervals.get("claims_expire_hours", 48) or 48),
    }


def cmd_start(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        swarm_interval = parse_flag(argv, "--swarm", 3)
        metrics_interval = parse_flag(argv, "--metrics", 30)
        hooks_interval = parse_flag(argv, "--hooks", 60)
        claims_expire_hours = parse_flag(argv, "--claims-hours", 48)
    except (ValueError, TypeError):
        return usage()
    state = {
        "status": "running",
        "started_at": now_iso(),
        "intervals": {
            "swarm": swarm_interval,
            "metrics": metrics_interval,
            "hooks": hooks_interval,
            "claims_expire_hours": claims_expire_hours,
        },
        "last_tick_at": now_iso(),
        "tick_count": 1,
        "last_tick_summary": {
            "expired_claims": 0,
            "updated": [],
        },
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


def cmd_tick(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    state = load_state(DEFAULT_STATE_PATH)
    if not state:
        return emit(
            {
                "result": "PASS",
                "command": "tick",
                "status": "stopped",
                "warnings": ["daemon state not initialized"],
            },
            as_json,
        )
    intervals = intervals_map(state)
    claims_hours = int(intervals.get("claims_expire_hours", 48) or 48)
    try:
        override = parse_flag_value(argv, "--claims-hours")
    except ValueError:
        return usage()
    if override is not None:
        try:
            claims_hours = max(1, int(override))
        except ValueError:
            return usage()

    expire_report = run_claims_expire(claims_hours)
    state["last_tick_at"] = now_iso()
    state["tick_count"] = int(state.get("tick_count", 0) or 0) + 1
    state["last_tick_summary"] = {
        "expired_claims": int(expire_report.get("expired_count", 0) or 0),
        "updated": expire_report.get("updated", []),
        "claims_hours": claims_hours,
    }
    save_state(DEFAULT_STATE_PATH, state)
    return emit(
        {
            "result": "PASS",
            "command": "tick",
            "status": str(state.get("status") or "stopped"),
            "tick_count": state.get("tick_count"),
            "last_tick_at": state.get("last_tick_at"),
            "last_tick_summary": state.get("last_tick_summary"),
        },
        as_json,
    )


def cmd_summary(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_state(DEFAULT_STATE_PATH)
    status = str(state.get("status") or "stopped")
    intervals = intervals_map(state)
    summary = {
        "result": "PASS",
        "command": "summary",
        "status": status,
        "tick_count": int(state.get("tick_count", 0) or 0),
        "swarm_interval": intervals.get("swarm", 3),
        "metrics_interval": intervals.get("metrics", 30),
        "hooks_interval": intervals.get("hooks", 60),
        "claims_expire_hours": intervals.get("claims_expire_hours", 48),
        "last_tick_at": state.get("last_tick_at"),
        "last_tick_summary": state.get("last_tick_summary", {}),
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
    if command == "tick":
        return cmd_tick(rest)
    if command == "summary":
        return cmd_summary(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
