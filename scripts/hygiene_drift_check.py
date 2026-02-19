#!/usr/bin/env python3
"""Checks command/hook drift for parity hygiene guard."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
GATEWAY_SCHEMA = REPO_ROOT / "plugin/gateway-core/src/config/schema.ts"
HOOKS_DIR = REPO_ROOT / "plugin/gateway-core/src/hooks"

ALLOWED_DUPLICATE_CLUSTERS = {
    frozenset({"complete", "ac"}),
    frozenset({"model-routing", "model-profile"}),
    frozenset({"model-routing-status", "model-profile-status"}),
    frozenset({"autopilot-go", "continue-work"}),
    frozenset({"autoloop", "ulw-loop", "ralph-loop"}),
}

# Transitional allowlist for hook IDs present in config order but not yet
# guaranteed in every branch snapshot. Keep this list short and temporary.
ALLOWED_MISSING_HOOK_IDS = {"mistake-ledger"}


@dataclass
class DriftReport:
    missing_script_refs: list[tuple[str, str]]
    duplicate_template_clusters: list[list[str]]
    unexpected_duplicate_clusters: list[list[str]]
    missing_hook_ids: list[str]
    extra_hook_ids: list[str]

    def ok(self) -> bool:
        return not (
            self.missing_script_refs
            or self.unexpected_duplicate_clusters
            or self.missing_hook_ids
            or self.extra_hook_ids
        )


def _load_commands() -> dict[str, dict[str, object]]:
    payload = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    commands = payload.get("command", {})
    return commands if isinstance(commands, dict) else {}


def _script_reference_audit(
    commands: dict[str, dict[str, object]],
) -> list[tuple[str, str]]:
    pattern = re.compile(r"scripts/([A-Za-z0-9_\-]+\.py)")
    missing: list[tuple[str, str]] = []
    for command_name, meta in commands.items():
        template = meta.get("template", "") if isinstance(meta, dict) else ""
        for script_name in pattern.findall(str(template)):
            script_path = REPO_ROOT / "scripts" / script_name
            if not script_path.exists():
                missing.append((command_name, script_name))
    return missing


def _duplicate_template_audit(
    commands: dict[str, dict[str, object]],
) -> tuple[list[list[str]], list[list[str]]]:
    clusters: dict[str, list[str]] = {}
    for command_name, meta in commands.items():
        if not isinstance(meta, dict):
            continue
        template = str(meta.get("template", ""))
        clusters.setdefault(template, []).append(command_name)

    duplicates = [sorted(names) for names in clusters.values() if len(names) > 1]
    duplicates.sort(key=lambda values: (len(values), values), reverse=True)

    unexpected: list[list[str]] = []
    for cluster in duplicates:
        if frozenset(cluster) not in ALLOWED_DUPLICATE_CLUSTERS:
            unexpected.append(cluster)
    return duplicates, unexpected


def _configured_hook_order() -> list[str]:
    source = GATEWAY_SCHEMA.read_text(encoding="utf-8")
    match = re.search(r"hooks:\s*\{[\s\S]*?order:\s*\[([\s\S]*?)\],", source)
    if not match:
        return []
    return re.findall(r'"([a-z0-9\-]+)"', match.group(1))


def _implemented_hook_ids() -> list[str]:
    ids: list[str] = []
    for file_path in sorted(HOOKS_DIR.glob("*/index.ts")):
        source = file_path.read_text(encoding="utf-8")
        match = re.search(r'id:\s*"([a-z0-9\-]+)"', source)
        if match:
            ids.append(match.group(1))
    return ids


def _hook_inventory_audit() -> tuple[list[str], list[str]]:
    configured = set(_configured_hook_order())
    implemented = set(_implemented_hook_ids())
    missing = sorted(
        item
        for item in configured
        if item not in implemented and item not in ALLOWED_MISSING_HOOK_IDS
    )
    extra = sorted(item for item in implemented if item not in configured)
    return missing, extra


def run() -> int:
    commands = _load_commands()
    missing_script_refs = _script_reference_audit(commands)
    duplicate_clusters, unexpected_clusters = _duplicate_template_audit(commands)
    missing_hook_ids, extra_hook_ids = _hook_inventory_audit()

    report = DriftReport(
        missing_script_refs=missing_script_refs,
        duplicate_template_clusters=duplicate_clusters,
        unexpected_duplicate_clusters=unexpected_clusters,
        missing_hook_ids=missing_hook_ids,
        extra_hook_ids=extra_hook_ids,
    )

    if report.ok():
        print("hygiene drift check: PASS")
        print(f"commands: {len(commands)}")
        print(f"allowed duplicate clusters: {len(report.duplicate_template_clusters)}")
        return 0

    print("hygiene drift check: FAIL")
    if report.missing_script_refs:
        print("missing script references:")
        for command_name, script_name in report.missing_script_refs:
            print(f"- {command_name}: scripts/{script_name}")
    if report.unexpected_duplicate_clusters:
        print("unexpected duplicate template clusters:")
        for cluster in report.unexpected_duplicate_clusters:
            print(f"- {', '.join(cluster)}")
    if report.missing_hook_ids:
        print("configured hook ids missing implementation:")
        for hook_id in report.missing_hook_ids:
            print(f"- {hook_id}")
    if report.extra_hook_ids:
        print("implemented hook ids missing from config order:")
        for hook_id in report.extra_hook_ids:
            print(f"- {hook_id}")
    return 1


if __name__ == "__main__":
    sys.exit(run())
