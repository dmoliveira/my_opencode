#!/usr/bin/env python3
"""Checks command/hook drift for parity hygiene guard."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
GATEWAY_SCHEMA = REPO_ROOT / "plugin/gateway-core/src/config/schema.ts"
HOOKS_DIR = REPO_ROOT / "plugin/gateway-core/src/hooks"
PARITY_PLAN = REPO_ROOT / "docs/plan/oh-my-opencode-parity-high-value-plan.md"

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
MAX_COMMAND_SURFACE = 50


@dataclass
class DriftReport:
    missing_script_refs: list[tuple[str, str]]
    duplicate_template_clusters: list[list[str]]
    unexpected_duplicate_clusters: list[list[str]]
    missing_hook_ids: list[str]
    extra_hook_ids: list[str]
    parity_plan_issues: list[str]
    parity_plan_warnings: list[str]
    command_surface_issues: list[str]

    def ok(self) -> bool:
        return not (
            self.missing_script_refs
            or self.unexpected_duplicate_clusters
            or self.missing_hook_ids
            or self.extra_hook_ids
            or self.parity_plan_issues
            or self.command_surface_issues
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


def _parity_plan_watchdog(commands: dict[str, dict[str, object]]) -> list[str]:
    issues: list[str] = []
    if not PARITY_PLAN.exists():
        return [
            "missing parity plan: docs/plan/oh-my-opencode-parity-high-value-plan.md"
        ]

    text = PARITY_PLAN.read_text(encoding="utf-8")
    command_names = set(commands.keys())

    if "| E8 Plan-handoff continuity parity" in text and "| 󰄵 [x] finished |" in text:
        if "plan-handoff" not in command_names:
            issues.append("E8 marked finished but 'plan-handoff' command is missing")

    if (
        "| E9 Parity backlog refresh + release-note automation" in text
        and "| 󰄵 [x] finished |" in text
    ):
        if "release-train-draft-milestones" not in command_names:
            issues.append(
                "E9 marked finished but 'release-train-draft-milestones' command is missing"
            )
        if "| E9-T1..E9-T3 completion |" not in text:
            issues.append(
                "E9 marked finished but E9 completion activity-log row is missing"
            )

    return issues


def _parse_finished_epics(plan_text: str) -> set[str]:
    finished: set[str] = set()
    for line in plan_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if "| 󰄵 [x] finished |" not in stripped:
            continue
        cells = [part.strip() for part in stripped.split("|")]
        if len(cells) < 2:
            continue
        match = re.match(r"(E\d+)\b", cells[1])
        if match:
            finished.add(match.group(1))
    return finished


def _parse_checklist_done_epics(plan_text: str) -> set[str]:
    done: set[str] = set()
    for line in plan_text.splitlines():
        match = re.match(r"^\s*- \[x\] (E\d+)\b", line)
        if match:
            done.add(match.group(1))
    return done


def _parse_activity_logged_epics(plan_text: str) -> set[str]:
    logged: set[str] = set()
    for line in plan_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if "| E" not in stripped:
            continue
        match = re.search(r"\b(E\d+)\b", stripped)
        if match:
            logged.add(match.group(1))
    return logged


def _fetch_recent_pr_metadata(
    repo_root: Path, *, limit: int = 30
) -> tuple[set[str], list[str], str | None]:
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "merged",
            "--limit",
            str(limit),
            "--json",
            "number,title,labels",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return (
            set(),
            [],
            "unable to fetch merged PR metadata via gh; skipping merged-PR coverage check",
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return set(), [], "merged PR metadata payload from gh is not valid JSON"

    labels: set[str] = set()
    titles: list[str] = []
    if not isinstance(payload, list):
        return labels, titles, "merged PR metadata payload from gh is not a list"

    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_title = item.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            titles.append(raw_title.strip())
        raw_labels = item.get("labels")
        if not isinstance(raw_labels, list):
            continue
        for label_entry in raw_labels:
            if isinstance(label_entry, dict):
                name = str(label_entry.get("name", "")).strip().lower()
                if name:
                    labels.add(name)
    return labels, titles, None


def _infer_area_markers_from_titles(titles: list[str]) -> set[str]:
    markers: set[str] = set()
    for title in titles:
        lowered = title.lower()
        if "lsp" in lowered:
            markers.add("lsp")
        if "parity" in lowered:
            markers.add("parity")
        if "release" in lowered:
            markers.add("release")
        if "tmux" in lowered:
            markers.add("tmux")
        if "task" in lowered:
            markers.add("task")
        if "autopilot" in lowered or "loop" in lowered:
            markers.add("loop")
    return markers


def _parity_plan_warning_audit(commands: dict[str, dict[str, object]]) -> list[str]:
    if not PARITY_PLAN.exists():
        return []
    text = PARITY_PLAN.read_text(encoding="utf-8")

    warnings: list[str] = []
    finished_epics = _parse_finished_epics(text)
    checklist_done = _parse_checklist_done_epics(text)
    logged_epics = _parse_activity_logged_epics(text)

    for epic in sorted(finished_epics):
        if epic not in checklist_done:
            warnings.append(
                f"{epic} marked finished in quick board but not marked [x] in checklist"
            )
        if epic not in logged_epics:
            warnings.append(
                f"{epic} marked finished in quick board but missing activity-log evidence"
            )

    merged_pr_labels, merged_pr_titles, metadata_warning = _fetch_recent_pr_metadata(
        REPO_ROOT
    )
    if metadata_warning:
        warnings.append(metadata_warning)
    elif merged_pr_labels:
        expected_label_tokens = ("parity", "lsp", "release")
        if not any(
            any(token in label for token in expected_label_tokens)
            for label in merged_pr_labels
        ):
            warnings.append(
                "recent merged PR labels contain no parity/lsp/release markers; label taxonomy may be drifting"
            )
    elif merged_pr_titles:
        markers = _infer_area_markers_from_titles(merged_pr_titles)
        if not ({"parity", "lsp", "release"} & markers):
            warnings.append(
                "merged PR titles contain no parity/lsp/release markers; area coverage metadata may be drifting"
            )
        else:
            pass
    else:
        warnings.append(
            "recent merged PR list has no labels or titles; unable to confirm coverage"
        )

    if "release-train-draft-milestones" not in commands:
        warnings.append("milestone draft command missing from command surface")

    return warnings



def _command_surface_audit(commands: dict[str, dict[str, object]]) -> list[str]:
    issues: list[str] = []
    if len(commands) > MAX_COMMAND_SURFACE:
        issues.append(
            f"command surface too large: {len(commands)} > {MAX_COMMAND_SURFACE} (keep aliases minimal)"
        )
    return issues

def run() -> int:
    commands = _load_commands()
    missing_script_refs = _script_reference_audit(commands)
    duplicate_clusters, unexpected_clusters = _duplicate_template_audit(commands)
    missing_hook_ids, extra_hook_ids = _hook_inventory_audit()
    parity_plan_issues = _parity_plan_watchdog(commands)
    parity_plan_warnings = _parity_plan_warning_audit(commands)
    command_surface_issues = _command_surface_audit(commands)

    report = DriftReport(
        missing_script_refs=missing_script_refs,
        duplicate_template_clusters=duplicate_clusters,
        unexpected_duplicate_clusters=unexpected_clusters,
        missing_hook_ids=missing_hook_ids,
        extra_hook_ids=extra_hook_ids,
        parity_plan_issues=parity_plan_issues,
        parity_plan_warnings=parity_plan_warnings,
        command_surface_issues=command_surface_issues,
    )

    if report.ok():
        print("hygiene drift check: PASS")
        print(f"commands: {len(commands)}")
        print(f"allowed duplicate clusters: {len(report.duplicate_template_clusters)}")
        if report.parity_plan_warnings:
            print(f"parity watchdog warnings: {len(report.parity_plan_warnings)}")
            for warning in report.parity_plan_warnings:
                print(f"- {warning}")
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
    if report.parity_plan_issues:
        print("parity plan watchdog issues:")
        for issue in report.parity_plan_issues:
            print(f"- {issue}")
    if report.command_surface_issues:
        print("command surface issues:")
        for issue in report.command_surface_issues:
            print(f"- {issue}")
    if report.parity_plan_warnings:
        print("parity plan watchdog warnings:")
        for warning in report.parity_plan_warnings:
            print(f"- {warning}")
    return 1


if __name__ == "__main__":
    sys.exit(run())
