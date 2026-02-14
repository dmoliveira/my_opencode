#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


DEFAULT_INDEX_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SESSION_INDEX_PATH", "~/.config/opencode/sessions/index.json"
    )
).expanduser()


def _usage() -> int:
    print(
        "usage: /session list [--limit <n>] [--json] | /session show <id> [--json] "
        "| /session search <query> [--limit <n>] [--json] | /session doctor [--json]"
    )
    return 2


def _parse_limit(argv: list[str], default: int = 10) -> int:
    if "--limit" not in argv:
        return default
    idx = argv.index("--limit")
    if idx + 1 >= len(argv):
        raise ValueError("missing limit value")
    try:
        return max(1, int(argv[idx + 1]))
    except ValueError as exc:
        raise ValueError("invalid limit value") from exc


def _load_index(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "generated_at": None, "sessions": []}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("session index root must be object")
    sessions = loaded.get("sessions")
    if sessions is not None and not isinstance(sessions, list):
        raise ValueError("session index sessions must be list")
    return {
        "version": loaded.get("version", 1),
        "generated_at": loaded.get("generated_at"),
        "sessions": sessions if isinstance(sessions, list) else [],
    }


def _session_rows(index: dict) -> list[dict]:
    rows: list[dict] = []
    for item in index.get("sessions", []):
        if isinstance(item, dict):
            rows.append(item)
    rows.sort(key=lambda row: str(row.get("last_event_at") or ""), reverse=True)
    return rows


def _emit(payload: dict, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1
    if payload.get("result") != "PASS":
        print(f"error: {payload.get('error', 'session command failed')}")
        return 1
    if payload.get("command") == "list":
        print(f"index: {payload.get('index_path')}")
        print(f"count: {payload.get('count')}")
        for row in payload.get("sessions", []):
            print(
                f"- {row.get('session_id')} | last={row.get('last_event_at')} "
                f"| reason={row.get('last_reason')} | events={row.get('event_count')}"
            )
        return 0
    if payload.get("command") == "show":
        row = payload.get("session", {})
        print(f"session_id: {row.get('session_id')}")
        print(f"cwd: {row.get('cwd')}")
        print(f"started_at: {row.get('started_at')}")
        print(f"last_event_at: {row.get('last_event_at')}")
        print(f"event_count: {row.get('event_count')}")
        print(f"last_reason: {row.get('last_reason')}")
        return 0
    if payload.get("command") == "search":
        print(f"query: {payload.get('query')}")
        print(f"count: {payload.get('count')}")
        for row in payload.get("sessions", []):
            print(
                f"- {row.get('session_id')} | last={row.get('last_event_at')} "
                f"| reason={row.get('last_reason')}"
            )
        return 0
    if payload.get("command") == "doctor":
        print("session doctor")
        print("--------------")
        print(f"index: {payload.get('index_path')}")
        print(f"exists: {'yes' if payload.get('exists') else 'no'}")
        if payload.get("warnings"):
            print("warnings:")
            for warning in payload.get("warnings", []):
                print(f"- {warning}")
        print(f"result: {payload.get('result')}")
        return 0 if payload.get("result") == "PASS" else 1
    return 0


def _command_list(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    try:
        limit = _parse_limit(argv)
        rows = _session_rows(_load_index(index_path))[:limit]
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "list",
                "error": str(exc),
                "index_path": str(index_path),
            },
            json_output,
        )
    return _emit(
        {
            "result": "PASS",
            "command": "list",
            "index_path": str(index_path),
            "count": len(rows),
            "sessions": rows,
        },
        json_output,
    )


def _command_show(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    args = [arg for arg in argv if arg != "--json"]
    if not args:
        return _usage()
    target_id = args[0]
    try:
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "show",
                "error": str(exc),
                "index_path": str(index_path),
            },
            json_output,
        )
    match = next((row for row in rows if row.get("session_id") == target_id), None)
    if not isinstance(match, dict):
        return _emit(
            {
                "result": "FAIL",
                "command": "show",
                "error": f"session not found: {target_id}",
                "index_path": str(index_path),
            },
            json_output,
        )
    return _emit(
        {
            "result": "PASS",
            "command": "show",
            "index_path": str(index_path),
            "session": match,
        },
        json_output,
    )


def _command_search(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    args = [arg for arg in argv if arg not in {"--json"}]
    if not args:
        return _usage()
    query = args[0].strip().lower()
    try:
        limit = _parse_limit(argv)
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "search",
                "error": str(exc),
                "index_path": str(index_path),
            },
            json_output,
        )
    matches = [
        row
        for row in rows
        if query in str(row.get("session_id", "")).lower()
        or query in str(row.get("cwd", "")).lower()
        or query in str(row.get("last_reason", "")).lower()
    ][:limit]
    return _emit(
        {
            "result": "PASS",
            "command": "search",
            "index_path": str(index_path),
            "query": query,
            "count": len(matches),
            "sessions": matches,
        },
        json_output,
    )


def _command_doctor(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    warnings: list[str] = []
    exists = index_path.exists()
    if not exists:
        warnings.append("session index does not exist yet; run /digest run first")
        return _emit(
            {
                "result": "PASS",
                "command": "doctor",
                "index_path": str(index_path),
                "exists": False,
                "warnings": warnings,
            },
            json_output,
        )
    try:
        index = _load_index(index_path)
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "doctor",
                "error": f"failed to parse index: {exc}",
                "index_path": str(index_path),
                "exists": True,
                "warnings": warnings,
            },
            json_output,
        )
    rows = _session_rows(index)
    if not rows:
        warnings.append("session index exists but no sessions are recorded yet")
    return _emit(
        {
            "result": "PASS",
            "command": "doctor",
            "index_path": str(index_path),
            "exists": True,
            "warnings": warnings,
            "count": len(rows),
        },
        json_output,
    )


def main(argv: list[str]) -> int:
    if not argv:
        return _usage()
    command = argv[0]
    rest = argv[1:]
    index_path = DEFAULT_INDEX_PATH

    if command == "help":
        return _usage()
    if command == "list":
        return _command_list(rest, index_path)
    if command == "show":
        return _command_show(rest, index_path)
    if command == "search":
        return _command_search(rest, index_path)
    if command == "doctor":
        return _command_doctor(rest, index_path)
    return _usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
