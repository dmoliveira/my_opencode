#!/usr/bin/env python3
"""Validate that scripts/ Python modules are reachable from active roots."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
ROOT_FILES = [
    REPO_ROOT / "install.sh",
    REPO_ROOT / "Makefile",
    REPO_ROOT / "scripts" / "selftest.py",
    REPO_ROOT / "scripts" / "doctor_command.py",
]

WRAPPER_SCRIPT_OVERRIDES = {
    "bg": "background_task_manager.py",
    "stack": "stack_profile_command.py",
    "nvim": "nvim_integration_command.py",
    "digest": "session_digest.py",
}


def _load_script_names() -> list[str]:
    return sorted(path.name for path in SCRIPTS_DIR.glob("*.py"))


def _command_roots() -> set[str]:
    payload = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    commands = payload.get("command", {})
    roots: set[str] = set()
    if not isinstance(commands, dict):
        return roots
    for meta in commands.values():
        template = str(meta.get("template", "")) if isinstance(meta, dict) else ""
        roots.update(re.findall(r"scripts/([A-Za-z0-9_\-]+\.py)", template))
        if "scripts/slash_command_wrapper.py" not in template:
            continue
        match = re.search(r"--fixed-before\s+([A-Za-z0-9_\-]+)", template)
        if not match:
            continue
        command_name = match.group(1).strip().lower()
        normalized = command_name.replace("-", "_")
        candidates = []
        override = WRAPPER_SCRIPT_OVERRIDES.get(command_name)
        if override:
            candidates.append(override)
        candidates.extend([f"{normalized}_command.py", f"{normalized}.py"])
        for candidate in candidates:
            if (SCRIPTS_DIR / candidate).exists():
                roots.add(candidate)
                break
    return roots


def _operational_roots(script_names: set[str]) -> set[str]:
    roots: set[str] = set()
    for path in ROOT_FILES:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.findall(r"([A-Za-z0-9_\-]+\.py)", text):
            if match in script_names:
                roots.add(match)
    return roots


def _forward_import_graph(script_names: list[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {name: set() for name in script_names}
    names = set(script_names)
    for name in script_names:
        source = (SCRIPTS_DIR / name).read_text(encoding="utf-8", errors="ignore")
        for match in re.findall(r"([A-Za-z0-9_\-]+\.py)", source):
            if match in names and match != name:
                graph[name].add(match)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name.split(".")[0] + ".py"
                    if target in names:
                        graph[name].add(target)
            elif isinstance(node, ast.ImportFrom) and node.module:
                target = node.module.split(".")[0] + ".py"
                if target in names:
                    graph[name].add(target)
    return graph


def main() -> int:
    script_names = _load_script_names()
    script_set = set(script_names)
    roots = (_command_roots() | _operational_roots(script_set)) & script_set
    graph = _forward_import_graph(script_names)

    reachable: set[str] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for dep in graph.get(current, set()):
            if dep not in reachable:
                stack.append(dep)

    unreachable = sorted(script_set - reachable)
    if unreachable:
        print("script-reachability-check: FAIL")
        for name in unreachable:
            print(f"- unreachable script: scripts/{name}")
        return 1

    print("script-reachability-check: PASS")
    print(f"scripts_checked: {len(script_names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
