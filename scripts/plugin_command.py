#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
)
from gateway_plugin_bridge import plugin_entry_spec  # type: ignore


CONFIG_PATH = resolve_write_path()
RETIRED_PLUGINS = {
    "notifier": "@mohak34/opencode-notifier@latest",
    "morph": "github:JRedeker/opencode-morph-fast-apply",
    "worktree": "github:kdcokenny/opencode-worktree",
}
RETIRED_PLUGIN_ORDER = ["notifier", "morph", "worktree"]
PROFILE_MAP: dict[str, list[str]] = {
    "lean": [],
    "stable": [],
    "experimental": [],
}


def load_config() -> dict:
    data, _ = load_layered_config()
    return data


def save_config(data: dict) -> None:
    global CONFIG_PATH
    CONFIG_PATH = resolve_write_path()
    save_config_file(data, CONFIG_PATH)


def get_plugin_entries(data: dict) -> list[Any]:
    value = data.get("plugin")
    return list(value) if isinstance(value, list) else []


def get_plugins(data: dict) -> list[str]:
    return [
        spec
        for entry in get_plugin_entries(data)
        if (spec := plugin_entry_spec(entry)) is not None
    ]


def set_plugins(data: dict, plugins: list[Any]) -> None:
    data["plugin"] = plugins


def compose_plugin_entries(
    current_entries: list[Any], desired_managed_packages: list[str]
) -> list[Any]:
    managed_packages = set(RETIRED_PLUGINS.values())
    first_managed_entry: dict[str, Any] = {}
    unknown_entries: list[Any] = []
    for entry in current_entries:
        spec = plugin_entry_spec(entry)
        if spec in managed_packages:
            first_managed_entry.setdefault(spec, entry)
        else:
            unknown_entries.append(entry)
    selected = [
        first_managed_entry.get(package, package)
        for package in desired_managed_packages
    ]
    return selected + unknown_entries


def remove_retired_plugin_entries(
    current_entries: list[Any], aliases: list[str]
) -> list[Any]:
    target_specs = {RETIRED_PLUGINS[alias] for alias in aliases}
    return [
        entry
        for entry in current_entries
        if plugin_entry_spec(entry) not in target_specs
    ]


def usage() -> int:
    print(
        "usage: /plugin status | /plugin doctor [--json] | /plugin setup-keys | /plugin profile <lean|stable|experimental> | /plugin enable <name|all> | /plugin disable <name|all>"
    )
    print("retired names (disable-only): notifier, morph, worktree")
    print("policy: no curated third-party plugins are enabled by managed profiles")
    return 2


def print_next_steps() -> None:
    print("\nnext:")
    print("- /plugin profile lean")
    print("- /plugin disable all")
    print("- /plugin doctor")
    print("- use /gateway status for the maintained local plugin")


def retired_states(plugins: list[str]) -> dict[str, dict[str, str]]:
    states: dict[str, dict[str, str]] = {}
    for alias in RETIRED_PLUGIN_ORDER:
        package = RETIRED_PLUGINS[alias]
        states[alias] = {
            "status": "present" if package in plugins else "absent",
            "kind": "retired",
            "package": package,
        }
    return states


def print_status(plugins: list[str]) -> None:
    print("curated external plugins: none")
    for alias, state in retired_states(plugins).items():
        print(f"{alias}: {state['status']} [retired] ({state['package']})")
    print("maintained capabilities: gateway notifications, native edits, governed worktrees")
    print(f"config: {CONFIG_PATH}")


def collect_doctor(plugins: list[str]) -> dict:
    problems: list[str] = []
    quick_fixes: list[str] = []
    states = retired_states(plugins)

    if not CONFIG_PATH.exists():
        problems.append(f"missing config file: {CONFIG_PATH}")

    present = [alias for alias, state in states.items() if state["status"] == "present"]
    for alias in present:
        problems.append(
            f"retired curated plugin is still configured: {alias} ({RETIRED_PLUGINS[alias]})"
        )
        quick_fixes.append(f"disable with: /plugin disable {alias}")
    if present:
        quick_fixes.append("remove all retired curated plugins with: /plugin profile lean")

    return {
        "result": "PASS" if not problems else "FAIL",
        "config": str(CONFIG_PATH),
        "python": sys.executable,
        "policy": "external-free",
        "plugins": states,
        "warnings": [],
        "problems": problems,
        "quick_fixes": quick_fixes,
    }


def print_doctor(plugins: list[str], json_output: bool = False) -> int:
    report = collect_doctor(plugins)
    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("plugin doctor")
    print("-------------")
    print(f"config: {report['config']}")
    print(f"python: {report['python']}")
    print("policy: external-free")
    for alias in RETIRED_PLUGIN_ORDER:
        state = report["plugins"][alias]
        print(f"- {alias}: {state['status']} [retired]")

    if report["quick_fixes"]:
        print("\nquick fixes:")
        for item in report["quick_fixes"]:
            print(f"- {item}")
    if report["problems"]:
        print("\nproblems:")
        for item in report["problems"]:
            print(f"- {item}")
        print("\nresult: FAIL")
        return 1
    print("\nresult: PASS")
    return 0


def print_setup_keys() -> int:
    print("setup keys")
    print("----------")
    print("no curated third-party plugins are enabled; no plugin API keys are required")
    return 0


def apply_profile(data: dict, current_entries: list[Any], profile: str) -> int:
    if profile not in PROFILE_MAP:
        return usage()
    set_plugins(data, compose_plugin_entries(current_entries, []))
    save_config(data)

    print("profile: lean")
    if profile != "lean":
        print(f"requested profile '{profile}' is retired; applied external-free lean policy")
    print("enabled curated aliases: none")
    print(f"config: {CONFIG_PATH}")
    return 0


def main(argv: list[str]) -> int:
    data = load_config()
    plugin_entries = get_plugin_entries(data)
    plugins = get_plugins(data)

    if not argv or argv[0] == "status":
        print_status(plugins)
        print_next_steps()
        return 0
    if argv[0] == "help":
        usage()
        print_next_steps()
        return 0
    if argv[0] == "doctor":
        json_output = len(argv) > 1 and argv[1] == "--json"
        if len(argv) > 1 and not json_output:
            return usage()
        return print_doctor(plugins, json_output=json_output)
    if argv[0] == "setup-keys":
        return print_setup_keys()
    if argv[0] == "profile":
        if len(argv) != 2:
            return usage()
        return apply_profile(data, plugin_entries, argv[1])
    if len(argv) != 2:
        return usage()

    action, target = argv
    targets = RETIRED_PLUGIN_ORDER if target == "all" else [target]
    if any(name not in RETIRED_PLUGINS for name in targets):
        return usage()
    if action == "enable":
        print("error: curated third-party plugins are retired and cannot be enabled")
        print("use a reviewed, immutable spec in opencode.json only after explicit approval")
        return 1
    if action != "disable":
        return usage()

    if target == "all":
        updated_entries = compose_plugin_entries(plugin_entries, [])
        set_plugins(data, updated_entries)
        save_config(data)
    else:
        updated_entries = remove_retired_plugin_entries(plugin_entries, targets)
        if updated_entries != plugin_entries:
            set_plugins(data, updated_entries)
            save_config(data)
    for alias in targets:
        print(f"{alias}: absent [retired]")
    if target == "all":
        print("applied profile: lean")
    print(f"config: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
