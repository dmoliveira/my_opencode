#!/usr/bin/env python3

import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    load_layered_config,
    resolve_write_path,
    save_config as save_config_file,
)


CONFIG_PATH = resolve_write_path()
SUPPORTED = (
    "context7",
    "gh_grep",
    "playwright",
    "exa_search",
    "firecrawl",
    "github",
)
TARGET_ALIASES = {
    "ghgrep": "gh_grep",
    "exa": "exa_search",
}
SERVER_DEFAULTS = {
    "context7": {"type": "remote", "url": "https://mcp.context7.com/mcp"},
    "gh_grep": {"type": "remote", "url": "https://mcp.grep.app"},
    "playwright": {
        "type": "local",
        "command": ["npx", "-y", "@playwright/mcp@latest"],
    },
    "exa_search": {"type": "remote", "url": "https://mcp.exa.ai/mcp"},
    "firecrawl": {"type": "local", "command": ["npx", "-y", "firecrawl-mcp"]},
    "github": {"type": "remote", "url": "https://api.githubcopilot.com/mcp/"},
}
PROFILE_MAP = {
    "minimal": [],
    "research": ["context7", "gh_grep"],
    "context7": ["context7"],
    "ghgrep": ["gh_grep"],
    "playwright": ["playwright"],
    "exa": ["exa_search"],
    "firecrawl": ["firecrawl"],
    "github": ["github"],
    "web": ["playwright", "exa_search", "firecrawl"],
    "all": list(SUPPORTED),
}


def normalized_target(target: str) -> str:
    return TARGET_ALIASES.get(target, target)


def profile_names_text() -> str:
    return "|".join(PROFILE_MAP)


def target_names_text() -> str:
    return "|".join((*SUPPORTED, *TARGET_ALIASES, "all"))


def endpoint_label(entry: dict) -> str:
    kind = entry.get("type")
    if kind == "remote":
        url = entry.get("url")
        return str(url).strip() if isinstance(url, str) else ""
    if kind == "local":
        command = entry.get("command")
        if isinstance(command, list):
            parts = [str(item).strip() for item in command if str(item).strip()]
            return " ".join(parts)
    return ""


def ensure_server_entry(mcp: dict, name: str) -> dict:
    current = mcp.get(name)
    entry = dict(current) if isinstance(current, dict) else {}
    defaults = SERVER_DEFAULTS.get(name, {})
    for key, value in defaults.items():
        if key not in entry:
            entry[key] = json.loads(json.dumps(value))
    mcp[name] = entry
    return entry


def load_config() -> dict:
    data, _ = load_layered_config()
    return data


def save_config(data: dict) -> None:
    global CONFIG_PATH
    CONFIG_PATH = resolve_write_path()
    save_config_file(data, CONFIG_PATH)


def status_line(entry: dict) -> str:
    enabled = entry.get("enabled")
    if enabled is True:
        return "enabled"
    if enabled is False:
        return "disabled"
    return "unset"


def usage() -> int:
    print(
        "usage: /mcp status | /mcp help | /mcp doctor [--json] | "
        f"/mcp profile <{profile_names_text()}> | "
        f"/mcp enable <{target_names_text()}> | "
        f"/mcp disable <{target_names_text()}>"
    )
    return 2


def print_next_steps() -> None:
    print("\nnext:")
    print("- /mcp enable context7")
    print("- /mcp enable gh_grep")
    print("- /mcp enable exa_search")
    print("- /mcp enable firecrawl")
    print("- /mcp enable github")
    print("- /mcp profile web")
    print("- /mcp profile all")
    print("- /mcp disable all")
    print(f"- /mcp profile {profile_names_text()}")
    print("- /mcp doctor")


def print_status(mcp: dict) -> None:
    for name in SUPPORTED:
        entry = mcp.get(name, {}) if isinstance(mcp.get(name), dict) else {}
        state = status_line(entry)
        endpoint = endpoint_label(entry)
        print(f"{name}: {state}" + (f" ({endpoint})" if endpoint else ""))
    print(f"config: {CONFIG_PATH}")


def collect_doctor(mcp: dict) -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    servers: dict[str, dict[str, object]] = {}

    for name in SUPPORTED:
        entry = mcp.get(name, {}) if isinstance(mcp.get(name), dict) else {}
        kind = str(entry.get("type") or "") if isinstance(entry, dict) else ""
        url = entry.get("url", "") if isinstance(entry.get("url"), str) else ""
        command_value = entry.get("command")
        command = command_value if isinstance(command_value, list) else []
        state = status_line(entry)
        servers[name] = {
            "status": state,
            "url": url,
            "command": [str(part) for part in command],
            "type": kind,
            "configured": "true" if isinstance(mcp.get(name), dict) else "false",
        }

        if not isinstance(mcp.get(name), dict):
            continue

        if kind == "remote":
            if not url:
                problems.append(f"{name} url is missing")
            elif not re.match(r"^https?://", url):
                problems.append(f"{name} url is invalid: {url}")
        elif kind == "local":
            if not command:
                problems.append(f"{name} command is missing")
        elif kind:
            problems.append(f"{name} type is invalid: {kind}")

    enabled_count = sum(1 for name in SUPPORTED if servers[name]["status"] == "enabled")
    if enabled_count == 0:
        warnings.append("all MCP servers are disabled")

    return {
        "result": "PASS" if not problems else "FAIL",
        "config": str(CONFIG_PATH),
        "servers": servers,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "run /mcp profile all or enable only the MCPs you need",
            "set remote MCP URLs and local MCP commands in ~/.config/opencode/opencode.json under mcp",
            "use /mcp profile research for lightweight context MCP defaults",
        ]
        if problems or warnings
        else [],
    }


def print_doctor(mcp: dict, json_output: bool = False) -> int:
    report = collect_doctor(mcp)

    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("mcp doctor")
    print("----------")
    print(f"config: {report['config']}")
    for name in SUPPORTED:
        item = report["servers"][name]
        command = item.get("command")
        command_parts = command if isinstance(command, list) else []
        endpoint = item.get("url") or " ".join(str(part) for part in command_parts)
        print(f"- {name}: {item['status']}" + (f" ({endpoint})" if endpoint else ""))

    if report["warnings"]:
        print("\nwarnings:")
        for item in report["warnings"]:
            print(f"- {item}")

    if report["problems"]:
        print("\nproblems:")
        for item in report["problems"]:
            print(f"- {item}")
        print("\nquick fixes:")
        for item in report["quick_fixes"]:
            print(f"- {item}")
        print("\nresult: FAIL")
        return 1

    print("\nresult: PASS")
    return 0


def apply_profile(data: dict, mcp: dict, profile: str) -> int:
    if profile not in PROFILE_MAP:
        return usage()

    enable_set = set(PROFILE_MAP[profile])
    for name in SUPPORTED:
        entry = ensure_server_entry(mcp, name)
        entry["enabled"] = name in enable_set

    data["mcp"] = mcp
    save_config(data)

    print(f"profile: {profile}")
    print("enabled servers:")
    if enable_set:
        for name in SUPPORTED:
            if name in enable_set:
                print(f"- {name}")
    else:
        print("- none")
    print(f"config: {CONFIG_PATH}")
    return 0


def set_enabled(data: dict, mcp: dict, action: str, target: str) -> int:
    normalized = normalized_target(target)
    targets = SUPPORTED if normalized == "all" else (normalized,)
    if any(name not in SUPPORTED for name in targets):
        return usage()

    value = action == "enable"
    for name in targets:
        entry = ensure_server_entry(mcp, name)
        entry["enabled"] = value

    data["mcp"] = mcp
    save_config(data)
    state = "enabled" if value else "disabled"
    for name in targets:
        print(f"{name}: {state}")
    print(f"config: {CONFIG_PATH}")
    return 0


def main(argv: list[str]) -> int:
    data = load_config()
    mcp = data.setdefault("mcp", {})

    if not argv or argv[0] == "status":
        print_status(mcp)
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
        return print_doctor(mcp, json_output=json_output)

    if argv[0] == "profile":
        if len(argv) < 2:
            return usage()
        return apply_profile(data, mcp, argv[1])

    if len(argv) < 2:
        return usage()

    action, target = argv[0], argv[1]
    if action not in ("enable", "disable"):
        return usage()

    return set_enabled(data, mcp, action, target)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
