#!/usr/bin/env python3

import json
import sys
from pathlib import Path


CONFIG_PATH = Path("~/.config/opencode/opencode.json").expanduser()
KNOWN_PLUGINS = {
    "notifier": "@mohak34/opencode-notifier@latest",
    "supermemory": "opencode-supermemory",
    "morph": "github:JRedeker/opencode-morph-fast-apply",
    "worktree": "github:kdcokenny/opencode-worktree",
    "wakatime": "opencode-wakatime",
}
PLUGIN_ORDER = ["notifier", "supermemory", "morph", "worktree", "wakatime"]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_plugins(data: dict) -> list[str]:
    value = data.get("plugin")
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str)]
    return []


def set_plugins(data: dict, plugins: list[str]) -> None:
    data["plugin"] = plugins


def usage() -> int:
    print(
        "usage: /plugin status | /plugin enable <name|all> | /plugin disable <name|all>"
    )
    print("names: notifier, supermemory, morph, worktree, wakatime")
    return 2


def print_status(plugins: list[str]) -> None:
    for alias in PLUGIN_ORDER:
        package = KNOWN_PLUGINS[alias]
        state = "enabled" if package in plugins else "disabled"
        print(f"{alias}: {state} ({package})")
    print(f"config: {CONFIG_PATH}")


def main(argv: list[str]) -> int:
    data = load_config()
    plugins = get_plugins(data)

    if not argv or argv[0] == "status":
        print_status(plugins)
        return 0

    if len(argv) < 2:
        return usage()

    action, target = argv[0], argv[1]
    if action not in ("enable", "disable"):
        return usage()

    targets = PLUGIN_ORDER if target == "all" else [target]
    if any(name not in KNOWN_PLUGINS for name in targets):
        return usage()

    known_packages = [KNOWN_PLUGINS[name] for name in PLUGIN_ORDER]
    plugin_set = set(plugins)

    if action == "enable":
        for alias in targets:
            plugin_set.add(KNOWN_PLUGINS[alias])
    else:
        for alias in targets:
            plugin_set.discard(KNOWN_PLUGINS[alias])

    unknown_existing = [p for p in plugins if p not in known_packages]
    ordered_known = [
        KNOWN_PLUGINS[a] for a in PLUGIN_ORDER if KNOWN_PLUGINS[a] in plugin_set
    ]
    updated = ordered_known + unknown_existing

    set_plugins(data, updated)
    save_config(data)

    state = "enabled" if action == "enable" else "disabled"
    for alias in targets:
        print(f"{alias}: {state}")
    print(f"config: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
