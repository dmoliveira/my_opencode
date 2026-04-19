#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"\b(?P<kind>task|epic|memory|doc|link)_\d+\b")


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    expected_titles: dict[str, str]
    expected_edges: list[tuple[str, str, str]]
    expect_memory_kind: bool = False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live tasker e2e sandbox simulations"
    )
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--timeout-ms", type=int, default=240000)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def run_process(
    command: list[str], *, cwd: Path, timeout_ms: int
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("CI", "true")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_EDITOR", "true")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("PAGER", "cat")
    env.setdefault("GCM_INTERACTIVE", "never")
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout_ms / 1000,
    )


def oc_json(*args: str) -> dict[str, Any]:
    result = run_process(["oc", *args], cwd=REPO_ROOT, timeout_ms=120000)
    if result.returncode != 0:
        raise RuntimeError(f"oc {' '.join(args)} failed: {result.stderr}")
    return json.loads(result.stdout)


def parse_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def extract_text(events: list[dict[str, Any]]) -> str:
    return "".join(
        str((event.get("part") or {}).get("text") or "")
        for event in events
        if event.get("type") == "text"
    )


def extract_commands(events: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for event in events:
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        if part.get("tool") != "bash":
            continue
        state = part.get("state") or {}
        input_payload = state.get("input") or {}
        command = input_payload.get("command")
        if isinstance(command, str):
            commands.append(command)
    return commands


def extract_ids(events: list[dict[str, Any]]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {
        "task": set(),
        "epic": set(),
        "memory": set(),
        "doc": set(),
        "link": set(),
    }
    for event in events:
        if event.get("type") != "tool_use":
            continue
        output = ((event.get("part") or {}).get("state") or {}).get("output")
        if not isinstance(output, str):
            continue
        for match in ID_RE.finditer(output):
            found.setdefault(match.group("kind"), set()).add(match.group(0))
    return found


def title_for(identifier: str) -> str:
    payload = oc_json("get", identifier, "--view", "full", "--format", "json")
    return str(payload.get("title") or "")


def links_for(identifier: str) -> set[tuple[str, str, str]]:
    payload = oc_json("get", identifier, "--view", "links", "--format", "json")
    return {
        (
            str(link.get("direction") or ""),
            str(link.get("edge_type") or ""),
            str(link.get("target_id") or ""),
        )
        for link in payload.get("links", [])
        if isinstance(link, dict)
    }


def choose_id(found: dict[str, set[str]], kind: str, title: str) -> str:
    for identifier in sorted(found.get(kind, set())):
        if title_for(identifier) == title:
            return identifier
    raise AssertionError(f"missing {kind} with title '{title}'")


def build_scenarios(total_runs: int) -> list[Scenario]:
    relation_phrases = [
        "make docs depend on migration",
        "make docs only after migration",
        "docs should happen after migration",
        "docs depends on migration",
        "migration must finish before docs",
    ]
    stamp = int(time.time())
    scenarios: list[Scenario] = []
    for index in range(total_runs):
        scope = f"tasker-e2e-{stamp}-{index:02d}"
        worktree = tempfile.mkdtemp(prefix=f"tasker-e2e-{index:02d}-")
        prefix = f"tasker-e2e-{index:02d}"
        if index % 3 == 0:
            task_title = f"{prefix} task"
            memory_title = f"{prefix} memory"
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}', worktree '{worktree}', and branch 'sandbox/tasker-e2e'. "
                f"Create exactly one task titled '{task_title}' and one durable note titled '{memory_title}'. "
                f"Link the durable note to the task, do not edit files or run git, and return only created ids and links."
            )
            scenarios.append(
                Scenario(
                    name=f"task-memory-{index:02d}",
                    prompt=prompt,
                    expected_titles={"task": task_title, "memory": memory_title},
                    expected_edges=[("incoming", "about", "memory")],
                    expect_memory_kind=True,
                )
            )
        elif index % 3 == 1:
            epic_title = f"{prefix} epic"
            migration_title = f"{prefix} migration"
            docs_title = f"{prefix} docs"
            relation = relation_phrases[index % len(relation_phrases)]
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}', worktree '{worktree}', and branch 'sandbox/tasker-e2e'. "
                f"Create an epic titled '{epic_title}', add tasks '{migration_title}' and '{docs_title}', and {relation}. "
                f"Return created ids and dependency summary only."
            )
            scenarios.append(
                Scenario(
                    name=f"epic-dependency-{index:02d}",
                    prompt=prompt,
                    expected_titles={
                        "epic": epic_title,
                        "migration": migration_title,
                        "docs": docs_title,
                    },
                    expected_edges=[
                        ("outgoing", "parent-of", "migration"),
                        ("outgoing", "parent-of", "docs"),
                        ("outgoing", "depends-on", "migration"),
                    ],
                )
            )
        else:
            epic_title = f"{prefix} epic"
            a_title = f"{prefix} task a"
            b_title = f"{prefix} task b"
            c_title = f"{prefix} task c"
            memory_title = f"{prefix} note"
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}', worktree '{worktree}', and branch 'sandbox/tasker-e2e'. "
                f"Create an epic titled '{epic_title}', three child tasks titled '{a_title}', '{b_title}', and '{c_title}', "
                f"make '{c_title}' depend on '{b_title}', and capture one durable note titled '{memory_title}' about '{a_title}'. "
                f"Do not edit files or run tests. Return only created ids and links."
            )
            scenarios.append(
                Scenario(
                    name=f"epic-three-task-note-{index:02d}",
                    prompt=prompt,
                    expected_titles={
                        "epic": epic_title,
                        "a": a_title,
                        "b": b_title,
                        "c": c_title,
                        "memory": memory_title,
                    },
                    expected_edges=[
                        ("outgoing", "parent-of", "a"),
                        ("outgoing", "parent-of", "b"),
                        ("outgoing", "parent-of", "c"),
                        ("outgoing", "depends-on", "b"),
                        ("incoming", "about", "memory"),
                    ],
                    expect_memory_kind=True,
                )
            )
    return scenarios


def validate_commands(scenario: Scenario, commands: list[str]) -> None:
    add_commands = [
        cmd
        for cmd in commands
        if any(
            token in cmd
            for token in (
                "oc add task ",
                "oc add epic ",
                "oc add memory ",
                "oc add doc ",
            )
        )
        and "--help" not in cmd
    ]
    if not add_commands:
        raise AssertionError("no oc add commands were observed")
    for cmd in add_commands:
        if "--scope" not in cmd or "--worktree" not in cmd or "--branch" not in cmd:
            raise AssertionError(
                f"missing scope/worktree/branch flags in command: {cmd}"
            )
    if scenario.expect_memory_kind:
        memory_commands = [cmd for cmd in add_commands if "oc add memory" in cmd]
        if not memory_commands:
            raise AssertionError("expected memory creation command was not observed")
        for cmd in memory_commands:
            if "--kind note" not in cmd and "--kind decision" not in cmd:
                raise AssertionError(f"memory command missing explicit kind: {cmd}")


def validate_scenario(
    scenario: Scenario, events: list[dict[str, Any]]
) -> dict[str, Any]:
    commands = extract_commands(events)
    validate_commands(scenario, commands)
    ids = extract_ids(events)
    final_text = extract_text(events).strip()
    if not ID_RE.search(final_text):
        raise AssertionError("final assistant text did not include artifact ids")

    resolved: dict[str, str] = {}
    for key, title in scenario.expected_titles.items():
        kind = "epic" if key == "epic" else ("memory" if key == "memory" else "task")
        resolved[key] = choose_id(ids, kind, title)

    if "epic" in resolved:
        epic_edges = links_for(resolved["epic"])
        for direction, edge_type, target_key in scenario.expected_edges:
            if direction == "outgoing" and edge_type == "parent-of":
                expected = (direction, edge_type, resolved[target_key])
                if expected not in epic_edges:
                    raise AssertionError(f"missing epic edge {expected}")

    if "docs" in resolved and "migration" in resolved:
        docs_edges = links_for(resolved["docs"])
        expected = ("outgoing", "depends-on", resolved["migration"])
        if expected not in docs_edges:
            raise AssertionError(f"missing docs dependency {expected}")

    if "c" in resolved and "b" in resolved:
        c_edges = links_for(resolved["c"])
        expected = ("outgoing", "depends-on", resolved["b"])
        if expected not in c_edges:
            raise AssertionError(f"missing task dependency {expected}")

    if "task" in resolved and "memory" in resolved:
        task_edges = links_for(resolved["task"])
        expected = ("incoming", "about", resolved["memory"])
        if expected not in task_edges:
            raise AssertionError(f"missing task memory edge {expected}")

    if "a" in resolved and "memory" in resolved:
        a_edges = links_for(resolved["a"])
        expected = ("incoming", "about", resolved["memory"])
        if expected not in a_edges:
            raise AssertionError(f"missing task A memory edge {expected}")

    return {"name": scenario.name, "resolved_ids": resolved}


def run_scenario(scenario: Scenario, *, timeout_ms: int) -> dict[str, Any]:
    result = run_process(
        [
            "opencode",
            "run",
            "--agent",
            "tasker",
            "--format",
            "json",
            "--dir",
            str(REPO_ROOT),
            scenario.prompt,
        ],
        cwd=REPO_ROOT,
        timeout_ms=timeout_ms,
    )
    events = parse_events(result.stdout)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return validate_scenario(scenario, events)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    started = time.time()
    scenarios = build_scenarios(args.runs)
    passed: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for scenario in scenarios:
        try:
            passed.append(run_scenario(scenario, timeout_ms=args.timeout_ms))
        except Exception as exc:  # noqa: BLE001
            failures.append({"name": scenario.name, "error": str(exc)})
            break
    payload = {
        "result": "PASS" if not failures else "FAIL",
        "requested_runs": args.runs,
        "completed_runs": len(passed),
        "failed_runs": len(failures),
        "warning_count": sum(len(item.get("warnings", [])) for item in passed),
        "duration_seconds": round(time.time() - started, 2),
        "passed": passed,
        "failures": failures,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {payload['result']}")
        print(f"requested_runs: {payload['requested_runs']}")
        print(f"completed_runs: {payload['completed_runs']}")
        print(f"failed_runs: {payload['failed_runs']}")
        print(f"warning_count: {payload['warning_count']}")
        print(f"duration_seconds: {payload['duration_seconds']}")
        for failure in failures:
            print(f"- FAIL {failure['name']}: {failure['error']}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
