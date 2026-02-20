#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROLE_MAP: dict[str, dict[str, Any]] = {
    "sisyphus": {
        "local_agent": "orchestrator",
        "result": "PASS",
        "rationale": "Primary execution lead with delegation and completion gates.",
    },
    "hephaestus": {
        "local_agent": "orchestrator",
        "result": "PASS",
        "rationale": "Deep goal-oriented execution maps to orchestrator objective flow.",
    },
    "prometheus": {
        "local_agent": "strategic-planner",
        "result": "PASS",
        "rationale": "Strategic planning maps directly to strategic-planner role.",
    },
    "metis": {
        "local_agent": "ambiguity-analyst",
        "result": "PASS",
        "rationale": "Ambiguity/unknown analysis maps directly to ambiguity-analyst.",
    },
    "momus": {
        "local_agent": "plan-critic",
        "result": "PASS",
        "rationale": "Plan critique/review maps directly to plan-critic.",
    },
    "oracle": {
        "local_agent": "oracle",
        "result": "PASS",
        "rationale": "Architecture/debug advisory role already exists with same label.",
    },
    "librarian": {
        "local_agent": "librarian",
        "result": "PASS",
        "rationale": "External docs/OSS research role already exists with same label.",
    },
    "explore": {
        "local_agent": "explore",
        "result": "PASS",
        "rationale": "Read-only codebase discovery role already exists with same label.",
    },
    "multimodal-looker": {
        "local_agent": "orchestrator",
        "result": "WARN",
        "rationale": "No dedicated multimodal-looker agent; route via orchestrator plus relevant tools.",
    },
}

REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_SCHEMA_PATH = (
    REPO_ROOT / "plugin" / "gateway-core" / "src" / "config" / "schema.ts"
)
REQUIRED_BRIDGE_HOOKS = [
    "todo-continuation-enforcer",
    "edit-error-recovery",
    "json-error-recovery",
    "provider-token-limit-recovery",
    "max-step-recovery",
    "mode-transition-reminder",
    "codex-header-injector",
    "plan-handoff-reminder",
]


def _emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        for key in ("result", "upstream_role", "local_agent", "rationale"):
            if key in payload:
                print(f"{key}: {payload[key]}")
    return 0 if payload.get("result") in {"PASS", "WARN"} else 1


def _status_payload() -> dict[str, Any]:
    hook_bridge = _hook_bridge_status()
    status = "PASS" if hook_bridge.get("result") == "PASS" else "WARN"
    return {
        "result": status,
        "mode": "compatibility_map",
        "upstream_roles": sorted(ROLE_MAP.keys()),
        "local_agents": sorted(
            {str(item.get("local_agent")) for item in ROLE_MAP.values()}
        ),
        "hook_bridge": hook_bridge,
        "notes": [
            "Canonical local agents remain source of truth.",
            "Mappings are compatibility hints, not runtime replacement.",
        ],
    }


def _hook_bridge_status() -> dict[str, Any]:
    if not GATEWAY_SCHEMA_PATH.exists():
        return {
            "result": "WARN",
            "schema_path": str(GATEWAY_SCHEMA_PATH),
            "missing": list(REQUIRED_BRIDGE_HOOKS),
            "message": "gateway schema missing; unable to verify hook bridge set",
        }

    text = GATEWAY_SCHEMA_PATH.read_text(encoding="utf-8")
    missing = [hook for hook in REQUIRED_BRIDGE_HOOKS if hook not in text]
    return {
        "result": "PASS" if not missing else "WARN",
        "schema_path": str(GATEWAY_SCHEMA_PATH),
        "required": list(REQUIRED_BRIDGE_HOOKS),
        "missing": missing,
    }


def _map_payload(role: str) -> dict[str, Any]:
    normalized = role.strip().lower()
    entry = ROLE_MAP.get(normalized)
    if entry is None:
        return {
            "result": "FAIL",
            "code": "unknown_upstream_role",
            "upstream_role": normalized,
            "message": "No compatibility mapping found for requested upstream role.",
            "known_roles": sorted(ROLE_MAP.keys()),
        }
    return {
        "result": entry.get("result", "PASS"),
        "upstream_role": normalized,
        "local_agent": entry.get("local_agent"),
        "rationale": entry.get("rationale"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upstream_agent_compat_command.py",
        description="Map upstream agent labels to local compatible agents.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    status = sub.add_parser("status", help="show compatibility map status")
    status.add_argument("--json", action="store_true")

    map_parser = sub.add_parser("map", help="map one upstream role to local agent")
    map_parser.add_argument("--role", required=True)
    map_parser.add_argument("--json", action="store_true")

    sub.add_parser("help", help="show usage")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand in {None, "help"}:
        parser.print_help()
        return 0 if args.subcommand == "help" else 2

    if args.subcommand == "status":
        return _emit(_status_payload(), as_json=bool(args.json))

    if args.subcommand == "map":
        return _emit(_map_payload(str(args.role)), as_json=bool(args.json))

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
