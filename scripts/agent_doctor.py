#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SOURCE_AGENT_DIR = REPO_ROOT / "agent"
SPEC_DIR = SOURCE_AGENT_DIR / "specs"
INSTALLED_AGENT_DIR = Path.home() / ".config" / "opencode" / "agent"
ROUTING_PROFILES_PATH = (
    REPO_ROOT / "plugin" / "gateway-core" / "routing-profiles.data.json"
)

REQUIRED_AGENT_DOCS: dict[str, list[str]] = {
    "docs/model-allocation-policy.md": [
        "## Effort-Band Fallback Chains",
        "## Provider Outage Behavior",
        "The primary `orchestrator` pins `openai/gpt-5.6-terra` to match `balanced`",
        "`tasker` remains unpinned and inherits `openai/gpt-5.4` from `writing`.",
    ],
    "docs/agent-architecture.md": [
        "## Inventory",
        "## Execution Workflow",
        "| `tasker` | primary | contract-only | cheap | `writing` | Codememory-backed planning capture without implementation |",
        "Select lead agent (`tasker` for planning capture, `orchestrator` for complex execution).",
    ],
    "docs/agent-tool-restrictions.md": [
        "## Contract",
        "## Deny Lists (Current)",
    ],
    "docs/agents-playbook.md": [
        "## When not to use each agent",
        "Planner + reservation example:",
    ],
    "README.md": [
        "tasker",
        "strategic-planner",
        "ambiguity-analyst",
        "plan-critic",
        "build` as the default agent",
    ],
    "instructions/agent_operating_contract.md": [
        "`default_agent` remains `build`",
        "`orchestrator` is the preferred primary for larger, multi-step work.",
        "`tasker` is the preferred primary for Codememory-backed planning capture",
    ],
}

ALLOWED_COST_TIERS = {"free", "cheap", "expensive"}

ORCHESTRATOR_BODY_WORD_BASELINE = 687
ORCHESTRATOR_BODY_WORD_LIMIT = 450
ORCHESTRATOR_RENDERED_CONTRACT_MARKERS = [
    "Low risk (",
    "Medium risk (",
    "High risk (",
    "Use `explore`",
    "Use `librarian`",
    "Use `oracle`",
    "Use `verifier` before claiming done",
    "Use `reviewer` for final quality/safety pass",
    "Use `release-scribe`",
    "Use `tasker`",
    "Use `/model-routing set-category quick`",
    "Use `/model-routing set-category balanced`",
    "Use `/model-routing set-category deep` for planner-heavy work (`strategic-planner`, `ambiguity-analyst`)",
    "Use `/model-routing set-category critical`",
    "Keep at most 2 concurrent subagents",
    "Do not run duplicate `reviewer` or `verifier` passes on unchanged diffs",
    "Default to a single writer",
    "objective, scoped ownership, constrained file paths, acceptance criteria, required checks, and expected output format",
    "Docs-only",
    "Tests-only",
    "Runtime/core",
    "Release/config",
    "Completion gates",
    "Blocker contract",
    "Anti-loop guard",
]
ORCHESTRATOR_TEMPLATE_ONLY_MARKERS = [
    "{{FAILED_ATTEMPTS}}",
    "{{QUALITY_POSTURE}}",
]

REQUIRED_AGENTS: dict[str, dict[str, str]] = {
    "orchestrator": {"mode": "primary"},
    "tasker": {"mode": "primary"},
    "experience-designer": {"mode": "subagent"},
    "explore": {"mode": "subagent"},
    "librarian": {"mode": "subagent"},
    "oracle": {"mode": "subagent"},
    "verifier": {"mode": "subagent"},
    "reviewer": {"mode": "subagent"},
    "release-scribe": {"mode": "subagent"},
    "strategic-planner": {"mode": "subagent"},
    "ambiguity-analyst": {"mode": "subagent"},
    "plan-critic": {"mode": "subagent"},
}

REQUIRED_MARKERS: dict[str, list[str]] = {
    "orchestrator.md": [
        "mode: primary",
        *ORCHESTRATOR_RENDERED_CONTRACT_MARKERS,
    ],
    "tasker.md": [
        "mode: primary",
        "bash: true",
        "write: false",
        "edit: false",
        "Current backend adapter: Codememory via `oc`.",
        "Never edit repo files, write code, run git/gh, run tests/builds, create worktrees, open PRs, or execute implementation steps.",
        "Use bash only for `oc`, `command -v oc`, and closely related backend health/install checks.",
    ],
    "explore.md": [
        "mode: subagent",
        "hidden: true",
        "bash: false",
        "write: false",
        "edit: false",
    ],
    "librarian.md": [
        "mode: subagent",
        "hidden: true",
        "bash: false",
        "write: false",
        "edit: false",
    ],
    "oracle.md": ["mode: subagent", "hidden: true", "write: false", "edit: false"],
    "verifier.md": ["mode: subagent", "hidden: true", "write: false", "edit: false"],
    "reviewer.md": ["mode: subagent", "hidden: true", "write: false", "edit: false"],
    "release-scribe.md": [
        "mode: subagent",
        "hidden: true",
        "write: false",
        "edit: false",
    ],
    "strategic-planner.md": [
        "mode: subagent",
        "hidden: true",
        "write: false",
        "edit: false",
    ],
    "ambiguity-analyst.md": [
        "mode: subagent",
        "hidden: true",
        "write: false",
        "edit: false",
    ],
    "plan-critic.md": ["mode: subagent", "hidden: true", "write: false", "edit: false"],
}

REQUIRED_ORCHESTRATION_MARKERS: list[str] = [
    "## Orchestration quickplay",
    "### wt flow",
    "WT execution checklist (use in every run)",
    "### Memory-aware orchestration (default)",
    "Pressure mode matrix (deterministic defaults)",
    "Print `<CONTINUE-LOOP>` as the final line only when at least one task is still pending after the current cycle.",
]


def usage() -> int:
    print("usage: /agent-doctor [run] [--json] | /agent-doctor help")
    return 2


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return

    print(f"result: {payload.get('result')}")
    print(f"check_count: {payload.get('check_count')}")
    print(f"failed_count: {payload.get('failed_count')}")
    for check in payload.get("checks", []):
        if not isinstance(check, dict):
            continue
        status = "PASS" if check.get("ok") else "FAIL"
        print(f"- {check.get('name')}: {status}")
        reason = str(check.get("reason") or "").strip()
        if reason:
            print(f"  reason: {reason}")


def _check_agent_files(directory: Path, prefix: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": f"{prefix}_directory_exists",
            "ok": directory.exists() and directory.is_dir(),
            "reason": "" if directory.exists() else f"missing directory: {directory}",
            "path": str(directory),
        }
    )
    if not directory.exists() or not directory.is_dir():
        return checks

    for filename, markers in REQUIRED_MARKERS.items():
        path = directory / filename
        exists = path.exists() and path.is_file()
        checks.append(
            {
                "name": f"{prefix}_{filename}_exists",
                "ok": exists,
                "reason": "" if exists else f"missing file: {path}",
                "path": str(path),
            }
        )
        if not exists:
            continue
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            checks.append(
                {
                    "name": f"{prefix}_{filename}_{marker}",
                    "ok": marker in content,
                    "reason": "" if marker in content else f"missing marker: {marker}",
                    "path": str(path),
                }
            )
    return checks


def _parse_agent_list_output(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    pattern = re.compile(r"^([a-zA-Z0-9_-]+) \((primary|subagent)\)$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        found[match.group(1)] = match.group(2)
    return found


def count_prompt_words(body: str) -> int:
    """Count prompt words as deterministic non-whitespace runs."""
    return len(re.findall(r"\S+", body.strip()))


def prompt_body_budget_check(
    agent: str, body: str, *, baseline: int, limit: int, path: Path
) -> dict[str, Any]:
    actual = count_prompt_words(body)
    return {
        "name": f"spec_{agent}_body_word_budget",
        "ok": actual <= limit,
        "reason": ""
        if actual <= limit
        else f"body has {actual} words; limit is {limit}",
        "path": str(path),
        "baseline": baseline,
        "actual": actual,
        "limit": limit,
    }


def _check_orchestrator_prompt_contract(
    spec: dict[str, Any], path: Path
) -> list[dict[str, Any]]:
    body = spec.get("body_template")
    if not isinstance(body, str):
        return [
            {
                "name": "spec_orchestrator_body_template",
                "ok": False,
                "reason": "body_template must be a string",
                "path": str(path),
            }
        ]

    checks = [
        prompt_body_budget_check(
            "orchestrator",
            body,
            baseline=ORCHESTRATOR_BODY_WORD_BASELINE,
            limit=ORCHESTRATOR_BODY_WORD_LIMIT,
            path=path,
        )
    ]
    for marker in (
        *ORCHESTRATOR_RENDERED_CONTRACT_MARKERS,
        *ORCHESTRATOR_TEMPLATE_ONLY_MARKERS,
    ):
        checks.append(
            {
                "name": f"spec_orchestrator_contract_{marker}",
                "ok": marker in body,
                "reason": "" if marker in body else f"missing marker: {marker}",
                "path": str(path),
            }
        )
    return checks


def load_routing_categories(
    path: Path = ROUTING_PROFILES_PATH,
) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("routing profiles must define a non-empty profiles object")
    categories: dict[str, dict[str, Any]] = {}
    for name, profile in profiles.items():
        if not isinstance(name, str) or not name or not isinstance(profile, dict):
            raise ValueError("routing profile entries must map names to objects")
        categories[name] = profile
    return categories


def agent_model_policy_check(
    spec: dict[str, Any], routing_categories: dict[str, dict[str, Any]], path: Path
) -> dict[str, Any]:
    name = str(spec.get("name") or path.stem).strip() or path.stem
    metadata = spec.get("metadata")
    category = metadata.get("default_category") if isinstance(metadata, dict) else None
    profile = routing_categories.get(category) if isinstance(category, str) else None
    expected_model = profile.get("model") if isinstance(profile, dict) else None
    has_pin = "model" in spec
    raw_pinned_model = spec.get("model") if has_pin else None
    pinned_model = (
        raw_pinned_model.strip()
        if isinstance(raw_pinned_model, str) and raw_pinned_model.strip()
        else raw_pinned_model
    )
    problems: list[str] = []

    if not isinstance(category, str) or category not in routing_categories:
        problems.append(f"unknown routing category: {category}")
    elif not isinstance(expected_model, str) or not expected_model.strip():
        problems.append(f"routing category {category} has no model")

    if has_pin:
        if (
            not isinstance(pinned_model, str)
            or not pinned_model
            or "/" not in pinned_model
        ):
            problems.append(f"invalid explicit model pin: {raw_pinned_model}")
        elif isinstance(expected_model, str) and pinned_model != expected_model:
            problems.append(
                f"model pin {pinned_model} does not match {category}: {expected_model}"
            )

    return {
        "name": f"spec_{name}_model_policy",
        "ok": not problems,
        "reason": "; ".join(problems),
        "path": str(path),
        "category": category,
        "pinned_model": pinned_model,
        "expected_model": expected_model,
        "effective_model": pinned_model if has_pin else expected_model,
        "inherits_category": not has_pin,
    }


def _check_runtime_discovery() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    binary = shutil.which("opencode")
    checks.append(
        {
            "name": "opencode_binary_available",
            "ok": binary is not None,
            "reason": "" if binary else "opencode binary not found on PATH",
            "path": binary or "",
        }
    )
    if not binary:
        return checks

    proc = subprocess.run(
        [binary, "agent", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    checks.append(
        {
            "name": "opencode_agent_list_executes",
            "ok": proc.returncode == 0,
            "reason": "" if proc.returncode == 0 else proc.stderr.strip(),
        }
    )
    if proc.returncode != 0:
        return checks

    discovered = _parse_agent_list_output(proc.stdout)
    for name, expected in REQUIRED_AGENTS.items():
        actual = discovered.get(name)
        checks.append(
            {
                "name": f"runtime_{name}_registered",
                "ok": actual is not None,
                "reason": "" if actual else f"missing runtime agent: {name}",
            }
        )
        if actual is None:
            continue
        checks.append(
            {
                "name": f"runtime_{name}_mode",
                "ok": actual == expected["mode"],
                "reason": ""
                if actual == expected["mode"]
                else f"expected {expected['mode']} got {actual}",
            }
        )
    return checks


def _check_orchestration_contract(path: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    exists = path.exists() and path.is_file()
    checks.append(
        {
            "name": "orchestration_contract_exists",
            "ok": exists,
            "reason": "" if exists else f"missing file: {path}",
            "path": str(path),
        }
    )
    if not exists:
        return checks

    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(REPO_ROOT)
    except ValueError:
        checks.append(
            {
                "name": "orchestration_contract_external_source",
                "ok": True,
                "reason": "marker checks skipped for external AGENTS.md source",
                "path": str(resolved_path),
            }
        )
        return checks

    content = path.read_text(encoding="utf-8")
    for marker in REQUIRED_ORCHESTRATION_MARKERS:
        checks.append(
            {
                "name": f"orchestration_contract_{marker}",
                "ok": marker in content,
                "reason": "" if marker in content else f"missing marker: {marker}",
                "path": str(path),
            }
        )
    return checks


def _check_agent_spec_metadata() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "spec_directory_exists",
            "ok": SPEC_DIR.exists() and SPEC_DIR.is_dir(),
            "reason": ""
            if SPEC_DIR.exists()
            else f"missing spec directory: {SPEC_DIR}",
            "path": str(SPEC_DIR),
        }
    )
    if not SPEC_DIR.exists() or not SPEC_DIR.is_dir():
        return checks

    discovered_agents = {path.stem for path in SPEC_DIR.glob("*.json")}
    expected_agents = set(REQUIRED_AGENTS)
    missing_agents = sorted(expected_agents - discovered_agents)
    unexpected_agents = sorted(discovered_agents - expected_agents)
    checks.append(
        {
            "name": "spec_inventory_exact",
            "ok": not missing_agents and not unexpected_agents,
            "reason": ""
            if not missing_agents and not unexpected_agents
            else f"missing={missing_agents}; unexpected={unexpected_agents}",
            "path": str(SPEC_DIR),
            "expected": sorted(expected_agents),
            "actual": sorted(discovered_agents),
        }
    )

    try:
        routing_categories = load_routing_categories()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        routing_categories = {}
        checks.append(
            {
                "name": "routing_profiles_load",
                "ok": False,
                "reason": str(exc),
                "path": str(ROUTING_PROFILES_PATH),
            }
        )
    else:
        checks.append(
            {
                "name": "routing_profiles_load",
                "ok": True,
                "reason": "",
                "path": str(ROUTING_PROFILES_PATH),
                "categories": sorted(routing_categories),
            }
        )

    for agent, expected in REQUIRED_AGENTS.items():
        path = SPEC_DIR / f"{agent}.json"
        checks.append(
            {
                "name": f"spec_{agent}_exists",
                "ok": path.exists() and path.is_file(),
                "reason": "" if path.exists() else f"missing spec file: {path}",
                "path": str(path),
            }
        )
        if not path.exists() or not path.is_file():
            continue

        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            checks.append(
                {
                    "name": f"spec_{agent}_parseable",
                    "ok": False,
                    "reason": f"invalid json: {exc}",
                    "path": str(path),
                }
            )
            continue

        checks.append(
            {
                "name": f"spec_{agent}_mode",
                "ok": spec.get("mode") == expected["mode"],
                "reason": ""
                if spec.get("mode") == expected["mode"]
                else f"expected {expected['mode']} got {spec.get('mode')}",
                "path": str(path),
            }
        )

        if agent == "orchestrator":
            checks.extend(_check_orchestrator_prompt_contract(spec, path))

        metadata = spec.get("metadata")
        checks.append(
            {
                "name": f"spec_{agent}_metadata_exists",
                "ok": isinstance(metadata, dict),
                "reason": ""
                if isinstance(metadata, dict)
                else "missing metadata object",
                "path": str(path),
            }
        )
        if not isinstance(metadata, dict):
            continue

        cost_tier = metadata.get("cost_tier")
        checks.append(
            {
                "name": f"spec_{agent}_cost_tier",
                "ok": isinstance(cost_tier, str) and cost_tier in ALLOWED_COST_TIERS,
                "reason": ""
                if isinstance(cost_tier, str) and cost_tier in ALLOWED_COST_TIERS
                else f"invalid cost_tier: {cost_tier}",
                "path": str(path),
            }
        )

        category = metadata.get("default_category")
        checks.append(
            {
                "name": f"spec_{agent}_default_category",
                "ok": isinstance(category, str) and category in routing_categories,
                "reason": ""
                if isinstance(category, str) and category in routing_categories
                else f"invalid default_category: {category}",
                "path": str(path),
            }
        )
        checks.append(agent_model_policy_check(spec, routing_categories, path))

        for list_key in ("triggers", "avoid_when", "denied_tools"):
            value = metadata.get(list_key)
            valid_list = isinstance(value, list) and all(
                isinstance(item, str) and item.strip() for item in value
            )
            checks.append(
                {
                    "name": f"spec_{agent}_{list_key}",
                    "ok": valid_list,
                    "reason": ""
                    if valid_list
                    else f"metadata.{list_key} must be list of non-empty strings",
                    "path": str(path),
                }
            )

        tools = spec.get("tools")
        denied_tools = metadata.get("denied_tools")
        if isinstance(tools, dict) and isinstance(denied_tools, list):
            inconsistent = [
                tool
                for tool in denied_tools
                if isinstance(tool, str) and tools.get(tool) is not False
            ]
            checks.append(
                {
                    "name": f"spec_{agent}_denied_tools_match",
                    "ok": not inconsistent,
                    "reason": ""
                    if not inconsistent
                    else f"denied tools not disabled: {', '.join(inconsistent)}",
                    "path": str(path),
                }
            )

    return checks


def _check_agent_reference_docs() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for relative_path, markers in REQUIRED_AGENT_DOCS.items():
        path = REPO_ROOT / relative_path
        exists = path.exists() and path.is_file()
        checks.append(
            {
                "name": f"agent_doc_{relative_path}_exists",
                "ok": exists,
                "reason": "" if exists else f"missing file: {path}",
                "path": str(path),
            }
        )
        if not exists:
            continue
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            checks.append(
                {
                    "name": f"agent_doc_{relative_path}_{marker}",
                    "ok": marker in content,
                    "reason": "" if marker in content else f"missing marker: {marker}",
                    "path": str(path),
                }
            )
    return checks


def _resolve_orchestration_contract_path() -> Path | None:
    override = os.environ.get("MY_OPENCODE_ORCHESTRATION_CONTRACT_PATH", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate
        return None
    candidate = REPO_ROOT / "AGENTS.md"
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def command_run(*, as_json: bool) -> int:
    checks: list[dict[str, Any]] = []
    if SOURCE_AGENT_DIR.exists() and SOURCE_AGENT_DIR.is_dir():
        checks.extend(_check_agent_files(SOURCE_AGENT_DIR, "source"))
    else:
        checks.append(
            {
                "name": "source_directory_exists",
                "ok": True,
                "reason": "source agent directory not present in this install context",
                "path": str(SOURCE_AGENT_DIR),
            }
        )
    checks.extend(_check_agent_files(INSTALLED_AGENT_DIR, "installed"))
    checks.extend(_check_runtime_discovery())
    checks.extend(_check_agent_spec_metadata())
    checks.extend(_check_agent_reference_docs())
    contract_path = _resolve_orchestration_contract_path()
    if contract_path is None:
        checks.append(
            {
                "name": "orchestration_contract_exists",
                "ok": True,
                "reason": "orchestration contract check skipped: AGENTS.md not found in repo ancestry",
                "path": str(REPO_ROOT),
            }
        )
    else:
        checks.extend(_check_orchestration_contract(contract_path))

    failed = [check for check in checks if not bool(check.get("ok"))]
    payload = {
        "result": "PASS" if not failed else "FAIL",
        "check_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
        "remediation": []
        if not failed
        else [
            "run install.sh to sync agent files to ~/.config/opencode/agent",
            "run opencode agent list and verify required agents/modes",
            "repair missing agent markers in agent/*.md files",
        ],
    }
    emit(payload, as_json=as_json)
    return 0 if not failed else 1


def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = False
    if "--json" in args:
        args.remove("--json")
        as_json = True

    if not args:
        return command_run(as_json=as_json)
    cmd = args.pop(0)
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "run" and not args:
        return command_run(as_json=as_json)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
