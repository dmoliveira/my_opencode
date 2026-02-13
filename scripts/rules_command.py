#!/usr/bin/env python3

from __future__ import annotations

import json
import os
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
from rules_engine import discover_rules, resolve_effective_rules  # type: ignore


SECTION = "rules"
DEFAULT_STATE = {
    "enabled": True,
    "disabled_ids": [],
    "extra_paths": [],
}


def usage() -> int:
    print(
        "usage: /rules status [--json] | /rules explain <path> [--json] | /rules disable-id <id> | /rules enable-id <id> | /rules doctor [--json]"
    )
    return 2


def normalize_id(raw: str) -> str:
    return raw.strip().lower()


def load_state() -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, _ = load_layered_config()
    write_path = resolve_write_path()
    state = config.get(SECTION)
    merged = dict(DEFAULT_STATE)
    if isinstance(state, dict):
        merged["enabled"] = bool(state.get("enabled", True))
        disabled_ids = state.get("disabled_ids")
        if isinstance(disabled_ids, list):
            merged["disabled_ids"] = sorted(
                {
                    normalize_id(str(item))
                    for item in disabled_ids
                    if isinstance(item, str) and normalize_id(item)
                }
            )
        extra_paths = state.get("extra_paths")
        if isinstance(extra_paths, list):
            merged["extra_paths"] = [
                str(item) for item in extra_paths if isinstance(item, str)
            ]
    return config, merged, write_path


def save_state(config: dict[str, Any], state: dict[str, Any], write_path: Path) -> None:
    config[SECTION] = {
        "enabled": bool(state.get("enabled", True)),
        "disabled_ids": sorted(
            {
                normalize_id(str(item))
                for item in state.get("disabled_ids", [])
                if isinstance(item, str) and normalize_id(item)
            }
        ),
        "extra_paths": [
            str(item)
            for item in state.get("extra_paths", [])
            if isinstance(item, str) and str(item).strip()
        ],
    }
    save_config_file(config, write_path)


def serialize_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule.get("id"),
        "description": rule.get("description"),
        "priority": rule.get("priority"),
        "scope": rule.get("scope"),
        "path": rule.get("path"),
        "alwaysApply": bool(rule.get("alwaysApply", False)),
        "globs": rule.get("globs", []),
        "problems": rule.get("problems", []),
    }


def get_discovery_roots(extra_paths: list[str]) -> list[Path]:
    roots = []
    for raw in extra_paths:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        roots.append(path)
    return roots


def gather_rules(extra_paths: list[str]) -> list[dict[str, Any]]:
    rules = discover_rules(Path.cwd(), home=Path.home())
    for root in get_discovery_roots(extra_paths):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            from rules_engine import parse_frontmatter, normalize_rule_id, validate_rule  # type: ignore

            frontmatter, body = parse_frontmatter(text)
            rule = dict(frontmatter)
            rule["id"] = normalize_rule_id(
                str(frontmatter.get("id"))
                if frontmatter.get("id") is not None
                else None,
                path.stem,
            )
            rule["scope"] = "extra"
            rule["path"] = str(path)
            rule["body"] = body
            rule["problems"] = validate_rule(rule)
            rules.append(rule)
    return rules


def command_status(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, state, write_path = load_state()
    rules = gather_rules(state.get("extra_paths", []))
    invalid = [serialize_rule(rule) for rule in rules if rule.get("problems")]
    scope_counts = {
        "project": sum(1 for rule in rules if rule.get("scope") == "project"),
        "user": sum(1 for rule in rules if rule.get("scope") == "user"),
        "extra": sum(1 for rule in rules if rule.get("scope") == "extra"),
    }
    payload = {
        "enabled": bool(state.get("enabled", True)),
        "disabled_ids": sorted(state.get("disabled_ids", [])),
        "scope_counts": scope_counts,
        "discovered_count": len(rules),
        "invalid_count": len(invalid),
        "invalid_rules": invalid,
        "config": str(write_path),
    }
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"enabled: {'yes' if payload['enabled'] else 'no'}")
    print(f"disabled_ids: {','.join(payload['disabled_ids']) or '(none)'}")
    print(
        "scope_counts: "
        f"project={scope_counts['project']} user={scope_counts['user']} extra={scope_counts['extra']}"
    )
    print(f"discovered_count: {payload['discovered_count']}")
    print(f"invalid_count: {payload['invalid_count']}")
    print(f"config: {payload['config']}")
    return 0


def command_explain(argv: list[str]) -> int:
    json_output = "--json" in argv
    filtered = [arg for arg in argv if arg != "--json"]
    if len(filtered) != 1:
        return usage()
    target = filtered[0]
    _, state, _ = load_state()
    rules = gather_rules(state.get("extra_paths", []))
    if not bool(state.get("enabled", True)):
        report = {
            "result": "PASS",
            "target_path": target,
            "enabled": False,
            "effective_rules": [],
            "conflicts": [],
            "skipped_disabled": [],
            "message": "rules subsystem disabled",
        }
    else:
        report = {
            "result": "PASS",
            "enabled": True,
            **resolve_effective_rules(
                rules,
                target,
                disabled_rule_ids={
                    normalize_id(item)
                    for item in state.get("disabled_ids", [])
                    if isinstance(item, str)
                },
            ),
        }
        report["effective_rules"] = [
            serialize_rule(rule) for rule in report.get("effective_rules", [])
        ]
    if json_output:
        print(json.dumps(report, indent=2))
        return 0
    print(f"target_path: {report.get('target_path')}")
    print(f"enabled: {'yes' if report.get('enabled') else 'no'}")
    print(f"effective_rules: {len(report.get('effective_rules', []))}")
    print(f"conflicts: {len(report.get('conflicts', []))}")
    print(f"skipped_disabled: {len(report.get('skipped_disabled', []))}")
    return 0


def command_set_disabled_id(argv: list[str], disable: bool) -> int:
    if len(argv) != 1:
        return usage()
    rule_id = normalize_id(argv[0])
    if not rule_id:
        return usage()
    config, state, write_path = load_state()
    disabled = {
        normalize_id(item)
        for item in state.get("disabled_ids", [])
        if isinstance(item, str)
    }
    if disable:
        disabled.add(rule_id)
    else:
        disabled.discard(rule_id)
    state["disabled_ids"] = sorted(disabled)
    save_state(config, state, write_path)
    print(f"rule_id: {rule_id}")
    print(f"disabled: {'yes' if disable else 'no'}")
    print(f"disabled_ids: {','.join(state['disabled_ids']) or '(none)'}")
    print(f"config: {write_path}")
    return 0


def command_doctor(argv: list[str]) -> int:
    if any(arg not in ("--json",) for arg in argv):
        return usage()
    json_output = "--json" in argv
    _, state, write_path = load_state()
    rules = gather_rules(state.get("extra_paths", []))
    invalid = [serialize_rule(rule) for rule in rules if rule.get("problems")]
    payload = {
        "result": "PASS" if not invalid else "FAIL",
        "enabled": bool(state.get("enabled", True)),
        "discovered_count": len(rules),
        "invalid_count": len(invalid),
        "disabled_ids": sorted(state.get("disabled_ids", [])),
        "invalid_rules": invalid,
        "warnings": [],
        "problems": [],
        "quick_fixes": [
            "/rules status --json",
            "/rules explain scripts/selftest.py --json",
        ],
        "config": str(write_path),
    }
    if not payload["enabled"]:
        payload["warnings"].append("rules subsystem is disabled")
    if invalid:
        payload["problems"].append("one or more rules failed schema validation")
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload["result"] == "PASS" else 1
    print(f"result: {payload['result']}")
    print(f"enabled: {'yes' if payload['enabled'] else 'no'}")
    print(f"discovered_count: {payload['discovered_count']}")
    print(f"invalid_count: {payload['invalid_count']}")
    print(f"config: {payload['config']}")
    return 0 if payload["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status(argv[1:] if argv else [])
    if argv[0] == "explain":
        return command_explain(argv[1:])
    if argv[0] == "disable-id":
        return command_set_disabled_id(argv[1:], True)
    if argv[0] == "enable-id":
        return command_set_disabled_id(argv[1:], False)
    if argv[0] == "doctor":
        return command_doctor(argv[1:])
    if argv[0] == "help":
        return usage()
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
