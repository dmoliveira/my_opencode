#!/usr/bin/env python3

import json
import os
import re
import sys
from pathlib import Path


CONFIG_PATH = Path(
    os.environ.get("OPENCODE_CONFIG_PATH", "~/.config/opencode/opencode.json")
).expanduser()
SUPPORTED = ("context7", "gh_grep")
PROFILE_MAP = {
    "minimal": [],
    "research": ["context7", "gh_grep"],
    "context7": ["context7"],
    "ghgrep": ["gh_grep"],
}


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
        "usage: /mcp status | /mcp help | /mcp doctor [--json] | /mcp profile <minimal|research|context7|ghgrep> | /mcp enable <context7|gh_grep|all> | /mcp disable <context7|gh_grep|all>"
    )
    return 2


def print_next_steps() -> None:
    print("\nnext:")
    print("- /mcp enable context7")
    print("- /mcp enable gh_grep")
    print("- /mcp disable all")
    print("- /mcp profile minimal|research|context7|ghgrep")
    print("- /mcp doctor")


def print_status(mcp: dict) -> None:
    for name in SUPPORTED:
        entry = mcp.get(name, {}) if isinstance(mcp.get(name), dict) else {}
        state = status_line(entry)
        url = entry.get("url", "") if isinstance(entry.get("url", ""), str) else ""
        print(f"{name}: {state}" + (f" ({url})" if url else ""))
    print(f"config: {CONFIG_PATH}")


def collect_doctor(mcp: dict) -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    servers: dict[str, dict[str, str]] = {}

    for name in SUPPORTED:
        entry = mcp.get(name, {}) if isinstance(mcp.get(name), dict) else {}
        url = entry.get("url", "") if isinstance(entry.get("url"), str) else ""
        state = status_line(entry)
        servers[name] = {
            "status": state,
            "url": url,
            "configured": "true" if isinstance(mcp.get(name), dict) else "false",
        }

        if not isinstance(mcp.get(name), dict):
            problems.append(f"{name} server config missing in mcp block")
            continue

        if not url:
            problems.append(f"{name} url is missing")
        elif not re.match(r"^https?://", url):
            problems.append(f"{name} url is invalid: {url}")

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
            "run /mcp enable context7 or /mcp enable gh_grep",
            "set missing URLs in ~/.config/opencode/opencode.json under mcp",
            "use /mcp profile research for both context MCP servers",
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
        print(
            f"- {name}: {item['status']}" + (f" ({item['url']})" if item["url"] else "")
        )

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
        if not isinstance(mcp.get(name), dict):
            mcp[name] = {}
        mcp[name]["enabled"] = name in enable_set

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
    targets = SUPPORTED if target == "all" else (target,)
    if any(name not in SUPPORTED for name in targets):
        return usage()

    value = action == "enable"
    for name in targets:
        if not isinstance(mcp.get(name), dict):
            mcp[name] = {}
        mcp[name]["enabled"] = value

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
