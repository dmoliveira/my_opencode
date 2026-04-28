#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any

from kvforge_discovery import KVFORGE_STATE_PATH, select_state, write_gateway_connection


def usage() -> int:
    print("usage: /connect [--mode <assist|shadow|enforce>] [--name <name>] [--model <provider/model>] [--json]")
    return 2


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value, indent=2)}")
        else:
            print(f"{key}: {value}")


def parse_flag(argv: list[str], name: str, default: str) -> str:
    if name not in argv:
        return default
    idx = argv.index(name)
    if idx + 1 >= len(argv):
        raise ValueError(f"missing value for {name}")
    return str(argv[idx + 1]).strip()


def connect_payload(argv: list[str]) -> dict[str, Any]:
    mode = parse_flag(argv, "--mode", "assist")
    if mode not in {"assist", "shadow", "enforce"}:
        raise ValueError("invalid mode")
    requested_name = parse_flag(argv, "--name", "")
    requested_model = parse_flag(argv, "--model", "")
    selected, running_states = select_state(requested_name=requested_name, requested_model=requested_model)
    if not selected:
        return {
            "result": "FAIL",
            "reason": "kvforge_server_not_running" if not running_states else "kvforge_selection_required",
            "state_path": str(KVFORGE_STATE_PATH),
            "available": [
                {
                    "connection_name": state.get("connection_name"),
                    "provider_model": state.get("provider_model"),
                    "base_url": state.get("base_url"),
                }
                for state in running_states
            ],
        }
    connection_name = requested_name or str(selected.get("connection_name") or "kvforge-local")
    result = write_gateway_connection(selected, mode=mode, connection_name=connection_name)
    return {"result": "PASS", "reason": "connected", **result}


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [item for item in argv if item != "--json"]
    if args and args[0] in {"-h", "--help", "help"}:
        return usage()
    try:
        emit(connect_payload(args), as_json=as_json)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
