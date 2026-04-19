#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SPEC_DIR = REPO_ROOT / "agent" / "specs"


def usage() -> int:
    print(
        "usage: /agent-catalog list [--json] | /agent-catalog explain <agent> [--json] | /agent-catalog doctor [--json]"
    )
    return 2


def _load_specs() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    if not SPEC_DIR.exists() or not SPEC_DIR.is_dir():
        return catalog
    for path in sorted(SPEC_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        catalog[name.strip()] = payload
    return catalog


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


def _tool_surface(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    tools = spec.get("tools")
    if not isinstance(tools, dict):
        return [], []
    allowed = sorted(
        [key for key, value in tools.items() if isinstance(key, str) and value is True]
    )
    denied = sorted(
        [key for key, value in tools.items() if isinstance(key, str) and value is False]
    )
    return allowed, denied


def _entry_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    raw_metadata = spec.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    allowed_tools, denied_tools_from_flags = _tool_surface(spec)
    denied_tools = sorted(
        set(denied_tools_from_flags + _string_list(metadata.get("denied_tools")))
    )
    return {
        "name": spec.get("name"),
        "mode": spec.get("mode"),
        "description": spec.get("description_template"),
        "default_category": metadata.get("default_category"),
        "cost_tier": metadata.get("cost_tier"),
        "fallback_policy": metadata.get("fallback_policy"),
        "triggers": _string_list(metadata.get("triggers")),
        "avoid_when": _string_list(metadata.get("avoid_when")),
        "tool_surface": {
            "allowed": allowed_tools,
            "denied": denied_tools,
        },
    }


def command_list(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    specs = _load_specs()
    entries = [_entry_from_spec(spec) for _, spec in sorted(specs.items())]
    payload = {
        "result": "PASS",
        "count": len(entries),
        "agents": entries,
        "spec_dir": str(SPEC_DIR),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"result: {payload['result']}")
    print(f"count: {payload['count']}")
    for entry in entries:
        print(
            "- "
            f"{entry['name']} ({entry['mode']}): "
            f"category={entry.get('default_category') or 'n/a'} "
            f"cost_tier={entry.get('cost_tier') or 'n/a'}"
        )
    print(f"spec_dir: {payload['spec_dir']}")
    return 0


def command_explain(args: list[str]) -> int:
    remaining = [arg for arg in args if arg != "--json"]
    as_json = "--json" in args
    if len(remaining) != 1:
        return usage()
    target = remaining[0]
    specs = _load_specs()
    spec = specs.get(target)
    if not spec:
        payload = {
            "result": "FAIL",
            "reason_codes": ["agent_not_found"],
            "agent": target,
            "known_agents": sorted(specs.keys()),
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"result: {payload['result']}")
            print(f"agent: {payload['agent']}")
            print("reason: agent not found")
            print(f"known_agents: {', '.join(payload['known_agents'])}")
        return 1

    entry = _entry_from_spec(spec)
    payload = {
        "result": "PASS",
        "agent": entry,
        "spec_path": str(SPEC_DIR / f"{target}.json"),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"result: {payload['result']}")
    print(f"name: {entry['name']}")
    print(f"mode: {entry.get('mode')}")
    print(f"description: {entry.get('description')}")
    print(f"default_category: {entry.get('default_category')}")
    print(f"cost_tier: {entry.get('cost_tier')}")
    print(f"fallback_policy: {entry.get('fallback_policy')}")
    print(f"triggers: {', '.join(entry.get('triggers', []))}")
    print(f"avoid_when: {', '.join(entry.get('avoid_when', []))}")
    tool_surface = entry.get("tool_surface", {})
    if isinstance(tool_surface, dict):
        allowed = tool_surface.get("allowed", [])
        denied = tool_surface.get("denied", [])
        print(f"tools_allowed: {', '.join(allowed)}")
        print(f"tools_denied: {', '.join(denied)}")
    print(f"spec_path: {payload['spec_path']}")
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    specs = _load_specs()
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "spec_dir_exists",
            "ok": SPEC_DIR.exists() and SPEC_DIR.is_dir(),
            "reason": "" if SPEC_DIR.exists() else f"missing directory: {SPEC_DIR}",
        }
    )
    required = [
        "orchestrator",
        "tasker",
        "explore",
        "librarian",
        "oracle",
        "verifier",
        "reviewer",
        "release-scribe",
        "strategic-planner",
        "ambiguity-analyst",
        "plan-critic",
    ]
    for name in required:
        checks.append(
            {
                "name": f"agent_{name}_present",
                "ok": name in specs,
                "reason": "" if name in specs else f"missing agent spec: {name}",
            }
        )

    failures = [check for check in checks if not check.get("ok")]
    payload = {
        "result": "PASS" if not failures else "FAIL",
        "check_count": len(checks),
        "failed_count": len(failures),
        "checks": checks,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["result"] == "PASS" else 1
    print(f"result: {payload['result']}")
    print(f"check_count: {payload['check_count']}")
    print(f"failed_count: {payload['failed_count']}")
    for check in checks:
        status = "PASS" if check.get("ok") else "FAIL"
        print(f"- {check['name']}: {status}")
        if check.get("reason"):
            print(f"  reason: {check['reason']}")
    return 0 if payload["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    args = argv[1:]
    if command in ("help", "--help", "-h"):
        return usage()
    if command == "list":
        return command_list(args)
    if command == "explain":
        return command_explain(args)
    if command == "doctor":
        return command_doctor(args)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
