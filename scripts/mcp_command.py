#!/usr/bin/env python3

import json
import sys
from pathlib import Path


CONFIG_PATH = Path("~/.config/opencode/opencode.json").expanduser()
SUPPORTED = ("context7", "gh_grep")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def status_line(entry: dict) -> str:
    enabled = entry.get("enabled")
    if enabled is True:
        return "enabled"
    if enabled is False:
        return "disabled"
    return "unset"


def usage() -> int:
    print(
        "usage: /mcp status | /mcp enable <context7|gh_grep|all> | /mcp disable <context7|gh_grep|all>"
    )
    return 2


def main(argv: list[str]) -> int:
    data = load_config()
    mcp = data.setdefault("mcp", {})

    if not argv or argv[0] == "status":
        for name in SUPPORTED:
            entry = mcp.get(name, {}) if isinstance(mcp.get(name), dict) else {}
            print(f"{name}: {status_line(entry)}")
        print(f"config: {CONFIG_PATH}")
        return 0

    if len(argv) < 2:
        return usage()

    action = argv[0]
    target = argv[1]
    if action not in ("enable", "disable"):
        return usage()

    targets = SUPPORTED if target == "all" else (target,)
    if any(name not in SUPPORTED for name in targets):
        return usage()

    value = action == "enable"
    for name in targets:
        if not isinstance(mcp.get(name), dict):
            mcp[name] = {}
        mcp[name]["enabled"] = value

    save_config(data)
    state = "enabled" if value else "disabled"
    for name in targets:
        print(f"{name}: {state}")
    print(f"config: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
