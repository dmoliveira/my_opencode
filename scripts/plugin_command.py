#!/usr/bin/env python3

import json
import os
import re
import shutil
import sys
from pathlib import Path


CONFIG_PATH = Path(
    os.environ.get("OPENCODE_CONFIG_PATH", "~/.config/opencode/opencode.json")
).expanduser()
KNOWN_PLUGINS = {
    "notifier": "@mohak34/opencode-notifier@latest",
    "supermemory": "opencode-supermemory",
    "morph": "github:JRedeker/opencode-morph-fast-apply",
    "worktree": "github:kdcokenny/opencode-worktree",
    "wakatime": "opencode-wakatime",
}
PLUGIN_ORDER = ["notifier", "supermemory", "morph", "worktree", "wakatime"]
STABLE_ALIASES = ["notifier", "supermemory", "wakatime"]
EXPERIMENTAL_ALIASES = ["morph", "worktree"]
PROFILE_MAP = {
    "lean": ["notifier"],
    "stable": ["notifier", "supermemory", "wakatime"],
    "experimental": ["notifier", "supermemory", "wakatime", "morph", "worktree"],
}


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
        "usage: /plugin status | /plugin doctor | /plugin setup-keys | /plugin profile <lean|stable|experimental> | /plugin enable <name|all> | /plugin disable <name|all>"
    )
    print("names: notifier, supermemory, morph, worktree, wakatime")
    print("note: 'all' applies stable plugins only: notifier, supermemory, wakatime")
    print("note: morph/worktree may require manual setup depending on plugin resolver")
    return 2


def print_next_steps() -> None:
    print("\nnext:")
    print("- /plugin enable notifier")
    print("- /plugin enable supermemory")
    print("- /plugin enable wakatime")
    print("- /plugin enable morph")
    print("- /plugin enable worktree")
    print("- /plugin profile lean|stable|experimental")
    print("- /plugin doctor")


def print_status(plugins: list[str]) -> None:
    for alias in PLUGIN_ORDER:
        package = KNOWN_PLUGINS[alias]
        state = "enabled" if package in plugins else "disabled"
        kind = "stable" if alias in STABLE_ALIASES else "experimental"
        print(f"{alias}: {state} [{kind}] ({package})")
    print(f"config: {CONFIG_PATH}")


def has_supermemory_key() -> bool:
    env_key = os.environ.get("SUPERMEMORY_API_KEY", "").strip()
    if env_key:
        return True

    candidates = [
        Path("~/.config/opencode/supermemory.json").expanduser(),
        Path("~/.config/opencode/supermemory.jsonc").expanduser(),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if re.search(r'"apiKey"\s*:\s*".+"', content):
            return True
    return False


def has_wakatime_key() -> bool:
    cfg = Path("~/.wakatime.cfg").expanduser()
    if not cfg.exists():
        return False
    try:
        content = cfg.read_text(encoding="utf-8")
    except Exception:
        return False
    return bool(re.search(r"(?im)^\s*api_key\s*=\s*\S+", content))


def print_doctor(plugins: list[str]) -> int:
    problems: list[str] = []
    warnings: list[str] = []

    print("plugin doctor")
    print("-------------")
    print(f"config: {CONFIG_PATH}")
    print(f"python: {sys.executable}")

    if not CONFIG_PATH.exists():
        problems.append(f"missing config file: {CONFIG_PATH}")

    for alias in PLUGIN_ORDER:
        package = KNOWN_PLUGINS[alias]
        enabled = package in plugins
        status = "enabled" if enabled else "disabled"
        kind = "stable" if alias in STABLE_ALIASES else "experimental"
        print(f"- {alias}: {status} [{kind}]")

    if KNOWN_PLUGINS["supermemory"] in plugins and not has_supermemory_key():
        problems.append(
            "supermemory enabled but no API key found (set SUPERMEMORY_API_KEY or ~/.config/opencode/supermemory.json[c])"
        )

    if KNOWN_PLUGINS["wakatime"] in plugins and not has_wakatime_key():
        problems.append("wakatime enabled but ~/.wakatime.cfg api_key is missing")

    if (
        KNOWN_PLUGINS["morph"] in plugins
        and not os.environ.get("MORPH_API_KEY", "").strip()
    ):
        problems.append("morph enabled but MORPH_API_KEY is not set")

    if KNOWN_PLUGINS["worktree"] in plugins and shutil.which("git") is None:
        problems.append("worktree enabled but git command is not available")

    if KNOWN_PLUGINS["morph"] in plugins or KNOWN_PLUGINS["worktree"] in plugins:
        if shutil.which("bun") is None:
            warnings.append(
                "bun is not in PATH; some github: plugins may fail to resolve depending on OpenCode runtime"
            )

    cache_dir = Path("~/.cache/opencode/node_modules").expanduser()
    if not cache_dir.exists():
        warnings.append("plugin cache not found yet (~/.cache/opencode/node_modules)")

    if warnings:
        print("\nwarnings:")
        for item in warnings:
            print(f"- {item}")

    if problems:
        print("\nproblems:")
        for item in problems:
            print(f"- {item}")
        print("\nquick fixes:")
        print(
            "- set SUPERMEMORY_API_KEY and/or create ~/.config/opencode/supermemory.jsonc"
        )
        print("- add api_key to ~/.wakatime.cfg")
        print("- disable unmet plugins with: /plugin disable <name>")
        print("\nresult: FAIL")
        return 1

    print("\nresult: PASS")
    return 0


def print_setup_keys(plugins: list[str]) -> int:
    print("setup keys")
    print("----------")

    needs_supermemory = (
        KNOWN_PLUGINS["supermemory"] in plugins and not has_supermemory_key()
    )
    needs_wakatime = KNOWN_PLUGINS["wakatime"] in plugins and not has_wakatime_key()
    needs_morph = (
        KNOWN_PLUGINS["morph"] in plugins
        and not os.environ.get("MORPH_API_KEY", "").strip()
    )

    if not (needs_supermemory or needs_wakatime or needs_morph):
        print("all required keys are already configured for enabled plugins")
        return 0

    if needs_supermemory:
        print("\n[supermemory]")
        print("export SUPERMEMORY_API_KEY='sm_your_key_here'")
        print("or create ~/.config/opencode/supermemory.jsonc:")
        print("{")
        print('  "apiKey": "sm_your_key_here"')
        print("}")

    if needs_wakatime:
        print("\n[wakatime]")
        print("create ~/.wakatime.cfg with:")
        print("[settings]")
        print("api_key = waka_your_key_here")

    if needs_morph:
        print("\n[morph]")
        print("export MORPH_API_KEY='sk_your_key_here'")

    print("\nthen run: /plugin doctor")
    return 0


def apply_profile(data: dict, current_plugins: list[str], profile: str) -> int:
    if profile not in PROFILE_MAP:
        return usage()

    profile_aliases = PROFILE_MAP[profile]
    profile_packages = [KNOWN_PLUGINS[a] for a in profile_aliases]
    known_packages = [KNOWN_PLUGINS[a] for a in PLUGIN_ORDER]
    unknown_existing = [p for p in current_plugins if p not in known_packages]
    updated = profile_packages + unknown_existing
    set_plugins(data, updated)
    save_config(data)

    print(f"profile: {profile}")
    print("enabled aliases:")
    for alias in profile_aliases:
        print(f"- {alias}")
    print(f"config: {CONFIG_PATH}")
    return 0


def main(argv: list[str]) -> int:
    data = load_config()
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
        return print_doctor(plugins)

    if argv[0] == "setup-keys":
        return print_setup_keys(plugins)

    if argv[0] == "profile":
        if len(argv) < 2:
            return usage()
        return apply_profile(data, plugins, argv[1])

    if len(argv) < 2:
        return usage()

    action, target = argv[0], argv[1]
    if action not in ("enable", "disable"):
        return usage()

    targets = STABLE_ALIASES if target == "all" else [target]
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
    if target == "all":
        print("applied profile: stable")
    if action == "enable":
        experimental_enabled = [a for a in targets if a in EXPERIMENTAL_ALIASES]
        if experimental_enabled:
            print(
                "note: experimental plugin(s) enabled. If OpenCode fails to load them, disable with /plugin disable <name>."
            )
    print(f"config: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
