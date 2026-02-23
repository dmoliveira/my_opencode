#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_POOL_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_AGENT_POOL_PATH",
        "~/.config/opencode/my_opencode/runtime/agent_pool.json",
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /agent-pool spawn --type <role> [--count <n>] [--json] | "
        "/agent-pool list [--json] | /agent-pool health [--json] | /agent-pool drain --id <agent_id> [--json] | "
        "/agent-pool logs [--limit <n>] [--json] | /agent-pool doctor [--json]"
    )
    return 2


def load_pool(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "agents": [], "events": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"version": 1, "agents": [], "events": []}
    agents = raw.get("agents") if isinstance(raw.get("agents"), list) else []
    events = raw.get("events") if isinstance(raw.get("events"), list) else []
    return {
        "version": int(raw.get("version", 1) or 1),
        "agents": agents,
        "events": events,
    }


def save_pool(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'agent-pool command failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("count") is not None:
            print(f"count: {payload.get('count')}")
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


def cmd_spawn(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        role = parse_flag_value(argv, "--type")
        count_raw = parse_flag_value(argv, "--count") or "1"
        count = max(1, int(count_raw))
    except (ValueError, TypeError):
        return usage()
    if not role:
        return usage()
    state = load_pool(DEFAULT_POOL_PATH)
    agents = state.get("agents") if isinstance(state.get("agents"), list) else []
    created: list[dict[str, Any]] = []
    base = len(agents) + 1
    for idx in range(count):
        agent_id = f"{role}-{base + idx}"
        item = {
            "agent_id": agent_id,
            "role": role,
            "status": "active",
            "created_at": now_iso(),
            "load": 0,
        }
        agents.append(item)
        created.append(item)
    state["agents"] = agents
    events = state.get("events") if isinstance(state.get("events"), list) else []
    events.insert(0, {"type": "spawn", "role": role, "count": count, "at": now_iso()})
    state["events"] = events[:200]
    save_pool(DEFAULT_POOL_PATH, state)
    return emit(
        {
            "result": "PASS",
            "command": "spawn",
            "count": len(created),
            "agents": created,
        },
        as_json,
    )


def cmd_list(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_pool(DEFAULT_POOL_PATH)
    agents = state.get("agents") if isinstance(state.get("agents"), list) else []
    return emit(
        {"result": "PASS", "command": "list", "count": len(agents), "agents": agents},
        as_json,
    )


def cmd_health(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_pool(DEFAULT_POOL_PATH)
    agents = state.get("agents") if isinstance(state.get("agents"), list) else []
    active = sum(
        1 for a in agents if isinstance(a, dict) and a.get("status") == "active"
    )
    drained = sum(
        1 for a in agents if isinstance(a, dict) and a.get("status") == "drained"
    )
    return emit(
        {
            "result": "PASS",
            "command": "health",
            "count": len(agents),
            "active": active,
            "drained": drained,
            "status": "healthy" if active > 0 else "idle",
        },
        as_json,
    )


def cmd_drain(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        agent_id = parse_flag_value(argv, "--id")
    except ValueError:
        return usage()
    if not agent_id:
        return usage()
    state = load_pool(DEFAULT_POOL_PATH)
    agents = state.get("agents") if isinstance(state.get("agents"), list) else []
    target = next(
        (a for a in agents if isinstance(a, dict) and a.get("agent_id") == agent_id),
        None,
    )
    if not isinstance(target, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "drain",
                "error": f"agent not found: {agent_id}",
            },
            as_json,
        )
    target["status"] = "drained"
    target["drained_at"] = now_iso()
    events = state.get("events") if isinstance(state.get("events"), list) else []
    events.insert(0, {"type": "drain", "agent_id": agent_id, "at": now_iso()})
    state["events"] = events[:200]
    save_pool(DEFAULT_POOL_PATH, state)
    return emit({"result": "PASS", "command": "drain", **target}, as_json)


def cmd_logs(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    limit = 20
    if "--limit" in argv:
        idx = argv.index("--limit")
        if idx + 1 >= len(argv):
            return usage()
        try:
            limit = max(1, int(argv[idx + 1]))
        except ValueError:
            return usage()
    state = load_pool(DEFAULT_POOL_PATH)
    events = state.get("events") if isinstance(state.get("events"), list) else []
    return emit(
        {
            "result": "PASS",
            "command": "logs",
            "count": min(limit, len(events)),
            "events": events[:limit],
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_pool(DEFAULT_POOL_PATH)
    agents = state.get("agents") if isinstance(state.get("agents"), list) else []
    warnings: list[str] = []
    if not agents:
        warnings.append("no agents in pool; spawn with /agent-pool spawn --type coder")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "path": str(DEFAULT_POOL_PATH),
            "count": len(agents),
            "warnings": warnings,
            "quick_fixes": [
                "/agent-pool spawn --type coder --count 2 --json",
                "/agent-pool health --json",
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
    if command == "spawn":
        return cmd_spawn(rest)
    if command == "list":
        return cmd_list(rest)
    if command == "health":
        return cmd_health(rest)
    if command == "drain":
        return cmd_drain(rest)
    if command == "logs":
        return cmd_logs(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
