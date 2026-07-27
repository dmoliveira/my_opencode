#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    edit_layered_config,
    load_layered_config,
    resolve_write_path,
)
from playwright_defaults import (  # type: ignore
    PLAYWRIGHT_MCP_CAPABILITIES,
    PLAYWRIGHT_MCP_COMMAND,
    inspect_playwright_invocation,
    migrate_known_mcp_command,
    parse_playwright_capabilities,
)

CONFIG_PATH = resolve_write_path()
ACTIVE_SERVERS = (
    "context7",
    "gh_grep",
    "playwright",
    "exa_search",
    "github",
)
RETIRED_SERVERS = {
    "firecrawl": "retired_disable_only",
}
REPORT_SERVERS = (*ACTIVE_SERVERS, *RETIRED_SERVERS)
TARGET_ALIASES = {
    "ghgrep": "gh_grep",
    "exa": "exa_search",
}
SERVER_DEFAULTS = {
    "context7": {"type": "remote", "url": "https://mcp.context7.com/mcp"},
    "gh_grep": {"type": "remote", "url": "https://mcp.grep.app"},
    "playwright": {
        "type": "local",
        "command": list(PLAYWRIGHT_MCP_COMMAND),
    },
    "exa_search": {"type": "remote", "url": "https://mcp.exa.ai/mcp"},
    "github": {"type": "remote", "url": "https://api.githubcopilot.com/mcp/"},
}
PROFILE_MAP = {
    "minimal": [],
    "research": ["context7", "gh_grep"],
    "context7": ["context7"],
    "ghgrep": ["gh_grep"],
    "playwright": ["playwright"],
    "exa": ["exa_search"],
    "github": ["github"],
    "web": ["playwright", "exa_search"],
    "all": list(ACTIVE_SERVERS),
}


def normalized_target(target: str) -> str:
    return TARGET_ALIASES.get(target, target)


def profile_names_text() -> str:
    return "|".join(PROFILE_MAP)


def target_names_text(*, include_retired: bool) -> str:
    retired = tuple(RETIRED_SERVERS) if include_retired else ()
    return "|".join((*ACTIVE_SERVERS, *retired, *TARGET_ALIASES, "all"))


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


def parse_capabilities(command: list[str]) -> list[str]:
    return parse_playwright_capabilities(command)


def ensure_server_entry(mcp: dict, name: str) -> dict:
    current = mcp.get(name)
    entry = dict(current) if isinstance(current, dict) else {}
    defaults = SERVER_DEFAULTS.get(name, {})
    for key, value in defaults.items():
        if key not in entry:
            entry[key] = json.loads(json.dumps(value))
    if name == "playwright" and isinstance(entry.get("command"), list):
        entry["command"], _ = migrate_known_mcp_command(entry["command"])
    mcp[name] = entry
    return entry


def disable_retired_entry(mcp: dict, name: str) -> bool:
    current = mcp.get(name)
    if not isinstance(current, dict) or current.get("enabled") is False:
        return False
    entry = dict(current)
    entry["enabled"] = False
    mcp[name] = entry
    return True


def load_config() -> dict:
    data, _ = load_layered_config()
    return data


def edit_config(mutator) -> None:
    global CONFIG_PATH
    result = edit_layered_config(mutator)
    CONFIG_PATH = result.files[0].path


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
        f"/mcp enable <{target_names_text(include_retired=False)}> | "
        f"/mcp disable <{target_names_text(include_retired=True)}>"
    )
    return 2


def print_next_steps() -> None:
    print("\nnext:")
    print("- /mcp profile research")
    print("- /mcp profile web")
    print("- /mcp enable context7")
    print("- /mcp enable gh_grep")
    print("- /mcp enable exa_search")
    print("- /mcp enable github")
    print("- /mcp profile all")
    print("- /mcp disable all")
    print("- /mcp disable firecrawl  # retired compatibility target")
    print(f"- /mcp profile {profile_names_text()}")
    print("- /mcp doctor")


def print_status(mcp: dict) -> None:
    for name in ACTIVE_SERVERS:
        entry = mcp.get(name, {}) if isinstance(mcp.get(name), dict) else {}
        state = status_line(entry)
        endpoint = endpoint_label(entry)
        print(f"{name}: {state}" + (f" ({endpoint})" if endpoint else ""))
    for name, reason in RETIRED_SERVERS.items():
        configured = isinstance(mcp.get(name), dict)
        entry = mcp[name] if configured else {}
        state = status_line(entry) if configured else "absent"
        print(f"{name}: {state} [retired: {reason}]")
    print(f"config: {CONFIG_PATH}")


def collect_doctor(mcp: dict) -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    servers: dict[str, dict[str, object]] = {}

    for name in ACTIVE_SERVERS:
        entry = mcp.get(name, {}) if isinstance(mcp.get(name), dict) else {}
        kind = str(entry.get("type") or "") if isinstance(entry, dict) else ""
        url = entry.get("url", "") if isinstance(entry.get("url"), str) else ""
        command_value = entry.get("command")
        command = command_value if isinstance(command_value, list) else []
        capabilities = parse_capabilities(command)
        playwright = (
            inspect_playwright_invocation(command) if name == "playwright" else {}
        )
        missing_capabilities = (
            [cap for cap in PLAYWRIGHT_MCP_CAPABILITIES if cap not in capabilities]
            if name == "playwright"
            else []
        )
        state = status_line(entry)
        servers[name] = {
            "status": state,
            "url": url,
            "command": [str(part) for part in command],
            "type": kind,
            "configured": "true" if isinstance(mcp.get(name), dict) else "false",
            "capabilities": capabilities,
            "recommended_capabilities": PLAYWRIGHT_MCP_CAPABILITIES if name == "playwright" else [],
            "missing_capabilities": missing_capabilities,
            **playwright,
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
            elif name == "playwright" and missing_capabilities:
                warnings.append(
                    "playwright command missing recommended capabilities: " + ", ".join(missing_capabilities)
                )
            if name == "playwright":
                if playwright.get("legacy_arguments"):
                    warnings.append(
                        "playwright command uses exact legacy @latest arguments; run a mutating /mcp command to migrate the bundled default"
                    )
                if not playwright.get("pinned"):
                    warnings.append("playwright package is not pinned")
                if not playwright.get("isolated"):
                    warnings.append("playwright command is missing --isolated")
                if not playwright.get("canonical") and not playwright.get(
                    "known_legacy"
                ):
                    warnings.append(
                        "playwright command is custom or noncanonical; doctor preserved it without rewriting"
                    )
        elif kind:
            problems.append(f"{name} type is invalid: {kind}")

    for name, reason in RETIRED_SERVERS.items():
        configured = isinstance(mcp.get(name), dict)
        entry = mcp[name] if configured else {}
        state = status_line(entry) if configured else "absent"
        servers[name] = {
            "name": name,
            "configured": "true" if configured else "false",
            "status": state,
            "reason": reason,
        }
        if state == "enabled":
            warnings.append(
                f"{name} is retired and still enabled; run /mcp disable {name}"
            )

    return {
        "result": "PASS" if not problems else "FAIL",
        "config": str(CONFIG_PATH),
        "servers": servers,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "run /mcp profile research, /mcp profile web, or enable only the MCPs you need",
            "keep playwright on the full-capability default so assertions, network/storage control, vision mode, and devtools remain available",
            "use playwright-cli for advanced canvas, WebGL, and browser-game loops when the task needs longer token-efficient sessions",
            "set remote MCP URLs and local MCP commands in ~/.config/opencode/opencode.json under mcp",
            "use /mcp status to stay minimal until extra context is worth the cost",
        ] if problems or warnings else [],
    }


def print_doctor(mcp: dict, json_output: bool = False) -> int:
    report = collect_doctor(mcp)

    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("mcp doctor")
    print("----------")
    print(f"config: {report['config']}")
    for name in REPORT_SERVERS:
        item = report["servers"][name]
        if name in RETIRED_SERVERS:
            print(
                f"- {name}: {item['status']} "
                f"[retired: {item['reason']}]"
            )
            continue
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


def apply_profile(profile: str) -> int:
    if profile not in PROFILE_MAP:
        return usage()

    enable_set = set(PROFILE_MAP[profile])

    def mutate(data: dict) -> None:
        mcp = data.setdefault("mcp", {})
        for name in ACTIVE_SERVERS:
            entry = ensure_server_entry(mcp, name)
            entry["enabled"] = name in enable_set
        for name in RETIRED_SERVERS:
            disable_retired_entry(mcp, name)
        data["mcp"] = mcp

    edit_config(mutate)

    print(f"profile: {profile}")
    print("enabled servers:")
    if enable_set:
        for name in ACTIVE_SERVERS:
            if name in enable_set:
                print(f"- {name}")
    else:
        print("- none")
    print(f"config: {CONFIG_PATH}")
    return 0


def set_enabled(action: str, target: str) -> int:
    normalized = normalized_target(target)
    if normalized in RETIRED_SERVERS:
        if action == "enable":
            print(f"error: {normalized} is retired and cannot be enabled")
            return 1
        changed = False

        def mutate(data: dict) -> None:
            nonlocal changed
            mcp = data.setdefault("mcp", {})
            changed = disable_retired_entry(mcp, normalized)
            data["mcp"] = mcp

        edit_config(mutate)
        if changed:
            print(f"{normalized}: disabled")
            print(f"config: {CONFIG_PATH}")
        else:
            print(f"{normalized}: absent or already disabled (no change)")
        return 0

    targets = ACTIVE_SERVERS if normalized == "all" else (normalized,)
    if any(name not in ACTIVE_SERVERS for name in targets):
        return usage()

    value = action == "enable"
    retired_disabled: list[str] = []

    def mutate(data: dict) -> None:
        mcp = data.setdefault("mcp", {})
        for name in targets:
            entry = ensure_server_entry(mcp, name)
            entry["enabled"] = value
        if normalized == "all" and action == "disable":
            for name in RETIRED_SERVERS:
                if disable_retired_entry(mcp, name):
                    retired_disabled.append(name)
        data["mcp"] = mcp

    edit_config(mutate)
    state = "enabled" if value else "disabled"
    for name in targets:
        print(f"{name}: {state}")
    for name in retired_disabled:
        print(f"{name}: disabled (retired)")
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
        return apply_profile(argv[1])

    if len(argv) < 2:
        return usage()

    action, target = argv[0], argv[1]
    if action not in ("enable", "disable"):
        return usage()

    return set_enabled(action, target)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001 - CLI boundary normalizes failures.
        print(f"error: {exc}")
        raise SystemExit(1)
