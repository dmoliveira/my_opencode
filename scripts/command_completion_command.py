#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config  # type: ignore


def usage() -> int:
    print(
        "usage: /complete [suggest <prefix>] [--limit <n>] [--json] | "
        "/complete families [--json] | /complete doctor [--json]"
    )
    return 2


def pop_flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def pop_value(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag not in args:
        return default
    idx = args.index(flag)
    if idx + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    value = args[idx + 1]
    del args[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _commands() -> dict[str, dict[str, Any]]:
    config, _ = load_layered_config()
    raw = config.get("command")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            result[str(key)] = value
    return result


def _normalize_prefix(raw: str) -> str:
    prefix = raw.strip()
    if prefix.startswith("/"):
        prefix = prefix[1:]
    return prefix


def _score(command_name: str, prefix: str) -> tuple[int, int, str]:
    name = command_name.lower()
    query = prefix.lower()
    if not query:
        return (3, len(name), name)
    if name == query:
        return (0, len(name), name)
    if name.startswith(query):
        return (1, len(name), name)
    if query in name:
        return (2, len(name), name)
    return (9, len(name), name)


def command_suggest(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        limit_raw = pop_value(args, "--limit", "20") or "20"
    except ValueError:
        return usage()
    if len(args) > 1:
        return usage()
    prefix = _normalize_prefix(args[0]) if args else ""

    try:
        limit = max(1, min(100, int(limit_raw)))
    except ValueError:
        return usage()

    commands = _commands()
    scored: list[tuple[tuple[int, int, str], str, dict[str, Any]]] = []
    for name, meta in commands.items():
        rank = _score(name, prefix)
        if rank[0] >= 9:
            continue
        scored.append((rank, name, meta))
    scored.sort(key=lambda item: item[0])

    suggestions: list[dict[str, Any]] = []
    for _, name, meta in scored[:limit]:
        suggestions.append(
            {
                "command": f"/{name}",
                "description": str(meta.get("description") or ""),
            }
        )

    payload = {
        "result": "PASS",
        "prefix": prefix,
        "count": len(suggestions),
        "suggestions": suggestions,
    }
    if as_json:
        emit(payload, as_json=True)
        return 0

    if not suggestions:
        print(f"no command matches '{prefix}'")
        return 0
    print(f"matches ({len(suggestions)}):")
    for item in suggestions:
        desc = item["description"]
        if desc:
            print(f"- {item['command']}: {desc}")
        else:
            print(f"- {item['command']}")
    return 0


def command_families(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    if args:
        return usage()

    commands = _commands()
    counts: dict[str, int] = {}
    for name in commands:
        family = name.split("-", 1)[0]
        counts[family] = counts.get(family, 0) + 1
    families = [
        {"family": family, "count": counts[family]} for family in sorted(counts)
    ]
    payload = {
        "result": "PASS",
        "family_count": len(families),
        "families": families,
    }
    if as_json:
        emit(payload, as_json=True)
        return 0

    print(f"families ({len(families)}):")
    for item in families:
        print(f"- {item['family']}: {item['count']}")
    return 0


def command_doctor(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    if args:
        return usage()

    commands = _commands()
    payload = {
        "result": "PASS" if commands else "FAIL",
        "command_count": len(commands),
        "has_complete": "complete" in commands,
        "warnings": [] if commands else ["no commands loaded from layered config"],
        "quick_fixes": [
            "/complete suggest au",
            "/complete suggest resume",
            "/complete families",
        ],
    }
    if as_json:
        emit(payload, as_json=True)
        return 0 if commands else 1

    print(f"command_count: {payload['command_count']}")
    print(f"complete_command_registered: {'yes' if payload['has_complete'] else 'no'}")
    if payload["warnings"]:
        print("warnings:")
        for warning in payload["warnings"]:
            print(f"- {warning}")
    print("next:")
    for fix in payload["quick_fixes"]:
        print(f"- {fix}")
    return 0 if commands else 1


def main(argv: list[str]) -> int:
    args = list(argv)
    if not args:
        return command_suggest([])

    command = args.pop(0)
    if command in {"help", "--help", "-h"}:
        return usage()
    if command == "suggest":
        return command_suggest(args)
    if command == "families":
        return command_families(args)
    if command == "doctor":
        return command_doctor(args)

    args.insert(0, command)
    return command_suggest(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
