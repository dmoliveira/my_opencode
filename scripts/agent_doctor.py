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

REQUIRED_AGENT_DOCS: dict[str, list[str]] = {
    "docs/model-allocation-policy.md": [
        "## Effort-Band Fallback Chains",
        "## Provider Outage Behavior",
    ],
    "docs/agent-architecture.md": [
        "## Inventory",
        "## Execution Workflow",
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
        "strategic-planner",
        "ambiguity-analyst",
        "plan-critic",
        "build` as the default agent",
    ],
    "instructions/agent_operating_contract.md": [
        "`default_agent` remains `build`",
        "`orchestrator` is the preferred primary for larger, multi-step work.",
    ],
}

ALLOWED_COST_TIERS = {"free", "cheap", "expensive"}
ALLOWED_DEFAULT_CATEGORIES = {
    "quick",
    "balanced",
    "deep",
    "critical",
    "visual",
    "writing",
}

REQUIRED_AGENTS: dict[str, dict[str, str]] = {
    "orchestrator": {"mode": "primary"},
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
        "Use `verifier` before claiming done",
        "Use `reviewer` for final quality/safety pass",
        "Anti-loop guard",
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
                "ok": isinstance(category, str)
                and category in ALLOWED_DEFAULT_CATEGORIES,
                "reason": ""
                if isinstance(category, str) and category in ALLOWED_DEFAULT_CATEGORIES
                else f"invalid default_category: {category}",
                "path": str(path),
            }
        )

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
