#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path(".opencode/reservation-state.json")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "reservationActive": False,
            "writerCount": 0,
            "ownPaths": [],
            "activePaths": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("reservation state must be a JSON object")
    return {
        "reservationActive": bool(
            data.get("reservationActive", data.get("active", False))
        ),
        "writerCount": int(data.get("writerCount", data.get("writer_count", 0)) or 0),
        "ownPaths": [
            str(item) for item in (data.get("ownPaths") or data.get("own_paths") or [])
        ],
        "activePaths": [
            str(item)
            for item in (data.get("activePaths") or data.get("active_paths") or [])
        ],
    }


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def parse_paths(raw: str) -> list[str]:
    parts = [part.strip() for part in raw.replace(";", ",").split(",")]
    return [part for part in parts if part]


def command_status(state_path: Path, json_output: bool) -> int:
    state = load_state(state_path)
    state["path"] = str(state_path)
    if json_output:
        print(json.dumps(state, indent=2))
        return 0
    print(f"path: {state_path}")
    print(f"active: {str(state['reservationActive']).lower()}")
    print(f"writer_count: {state['writerCount']}")
    print(f"own_paths: {', '.join(state['ownPaths']) if state['ownPaths'] else '-'}")
    print(
        f"active_paths: {', '.join(state['activePaths']) if state['activePaths'] else '-'}"
    )
    return 0


def command_set(
    state_path: Path, own_paths: str, active_paths: str, writer_count: int
) -> int:
    own = parse_paths(own_paths)
    active = parse_paths(active_paths) if active_paths else own
    state = {
        "reservationActive": True,
        "writerCount": max(1, writer_count),
        "ownPaths": own,
        "activePaths": active,
    }
    write_state(state_path, state)
    print(f"state: updated ({state_path})")
    return 0


def command_clear(state_path: Path) -> int:
    state = {
        "reservationActive": False,
        "writerCount": 0,
        "ownPaths": [],
        "activePaths": [],
    }
    write_state(state_path, state)
    print(f"state: cleared ({state_path})")
    return 0


def command_export(state_path: Path) -> int:
    state = load_state(state_path)
    active = "true" if state["reservationActive"] else "false"
    own = ",".join(state["ownPaths"])
    active_paths = ",".join(state["activePaths"])
    writer_count = str(state["writerCount"])
    print(f"export MY_OPENCODE_FILE_RESERVATION_ACTIVE={active}")
    print(f"export MY_OPENCODE_FILE_RESERVATION_PATHS={json.dumps(own)}")
    print(f"export MY_OPENCODE_ACTIVE_RESERVATION_PATHS={json.dumps(active_paths)}")
    print(f"export MY_OPENCODE_ACTIVE_WRITERS={writer_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage file reservation state for parallel writer guardrails"
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_PATH),
        help="Reservation state file path",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show reservation status")

    set_parser = subparsers.add_parser("set", help="Set active reservation")
    set_parser.add_argument(
        "--own-paths",
        required=True,
        help="Comma-separated glob paths owned by this writer",
    )
    set_parser.add_argument(
        "--active-paths",
        default="",
        help="Comma-separated glob paths reserved by all active writers",
    )
    set_parser.add_argument(
        "--writer-count",
        type=int,
        default=1,
        help="Active writer count",
    )

    subparsers.add_parser("clear", help="Clear reservation state")
    subparsers.add_parser("export", help="Print shell exports for env-based guards")

    args = parser.parse_args()
    state_path = Path(args.state_file)

    if args.command == "status":
        return command_status(state_path, args.json)
    if args.command == "set":
        return command_set(
            state_path,
            own_paths=args.own_paths,
            active_paths=args.active_paths,
            writer_count=args.writer_count,
        )
    if args.command == "clear":
        return command_clear(state_path)
    if args.command == "export":
        return command_export(state_path)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
