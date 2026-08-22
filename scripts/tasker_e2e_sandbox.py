#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"\b(?P<kind>task|epic|memory|doc|link)_\d+\b")
TASKER_MODEL = "openai/gpt-5.6-terra"
SHELL_OPERATOR_CHARS = frozenset(";&|<>")
TASKER_READ_ONLY_SUBCOMMANDS = frozenset(
    {"config", "current", "find", "get", "help", "list", "next", "queue"}
)
TASKER_WRITE_SUBCOMMANDS = frozenset({"add", "link", "set"})
TASKER_SANDBOX_PASSTHROUGH_ENV = frozenset(
    {
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "WINDIR",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "PORTKEY_API_KEY",
        "PORTKEY_BASE_URL",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    }
)
TASKER_SANDBOX_CHILD_ENV = frozenset(
    TASKER_SANDBOX_PASSTHROUGH_ENV
    | {
        "CI",
        "GIT_TERMINAL_PROMPT",
        "GIT_EDITOR",
        "GIT_PAGER",
        "PAGER",
        "GCM_INTERACTIVE",
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_CONFIG_DIRS",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "TMPDIR",
        "PATH",
        "OPENCODE_CONFIG_PATH",
        "OPENCODE_DISABLE_PROJECT_CONFIG",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS",
        "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
        "OPENCODE_SESSION_ID",
        "MY_OPENCODE_SESSION_ID",
        "TASKER_E2E_ISOLATED_ENV",
    }
)
TASKER_SANDBOX_BLOCKED_ENV = frozenset(
    {
        "CODEMEMORY_CONFIG_PATH",
        "CODEMEMORY_SQLITE_PATH",
        "DATABASE_URL",
        "OPENCODE_CONFIG_CONTENT",
    }
)
ACTIVE_OC_ENV: dict[str, str] | None = None
ACTIVE_OC_CWD: Path | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    expected_titles: dict[str, str]
    expected_edges: list[tuple[str, str, str]]
    mode: str = "positive"
    expect_memory_kind: bool = False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live tasker e2e sandbox simulations"
    )
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--timeout-ms", type=int, default=360000)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout_ms: int,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        name: os.environ[name]
        for name in TASKER_SANDBOX_PASSTHROUGH_ENV
        if name in os.environ
    }
    env.setdefault("CI", "true")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_EDITOR", "true")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("PAGER", "cat")
    env.setdefault("GCM_INTERACTIVE", "never")
    if env_overrides:
        env.update(
            {
                name: value
                for name, value in env_overrides.items()
                if name in TASKER_SANDBOX_CHILD_ENV
            }
        )
    for name in TASKER_SANDBOX_BLOCKED_ENV:
        env.pop(name, None)
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout_ms / 1000,
    )


def resolve_tasker_launcher(name: str) -> str:
    launcher = shutil.which(name)
    if launcher is None:
        raise RuntimeError(f"tasker e2e sandbox requires an installed {name} launcher")
    resolved = Path(launcher).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError(f"tasker e2e sandbox launcher is not executable: {name}")
    return str(resolved)


def resolve_tasker_launchers() -> tuple[str, str]:
    return resolve_tasker_launcher("oc"), resolve_tasker_launcher("opencode")


def render_tasker_oc_launcher(real_oc: str, codememory_config: Path) -> str:
    template = """#!__PYTHON_EXECUTABLE__
from __future__ import annotations

import os
import subprocess
import sys

REAL_OC = __REAL_OC__
CONFIG_PATH = __CONFIG_PATH__


def reject() -> None:
    print("tasker sandbox rejected Codememory config override", file=sys.stderr)
    raise SystemExit(64)


def safe_environment() -> dict[str, str]:
    names = (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_CONFIG_DIRS",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "PORTKEY_API_KEY",
        "PORTKEY_BASE_URL",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    )
    environment = {"PATH": os.defpath}
    environment.update(
        {name: os.environ[name] for name in names if os.environ.get(name)}
    )
    return environment


def main() -> int:
    if any(
        argument == "--config" or argument.startswith("--config=")
        for argument in sys.argv[1:]
    ):
        reject()
    result = subprocess.run(
        [REAL_OC, "--config", CONFIG_PATH, *sys.argv[1:]],
        capture_output=False,
        check=False,
        env=safe_environment(),
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
"""
    return (
        template.replace("__PYTHON_EXECUTABLE__", str(Path(sys.executable).resolve()))
        .replace("__REAL_OC__", repr(str(Path(real_oc).resolve())))
        .replace("__CONFIG_PATH__", repr(str(codememory_config.resolve())))
    )


def configure_tasker_runtime_launchers(
    runtime_env: dict[str, str], *, real_oc: str, real_opencode: str | None = None
) -> None:
    wrapper = Path(runtime_env["TASKER_E2E_OC_WRAPPER"])
    if wrapper.exists() or wrapper.is_symlink():
        raise RuntimeError("tasker e2e sandbox refuses a pre-existing oc wrapper")
    wrapper.write_text(
        render_tasker_oc_launcher(
            real_oc,
            Path(runtime_env["TASKER_E2E_CODEMEMORY_CONFIG"]),
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    real_rg = shutil.which("rg")
    rg_wrapper = Path(runtime_env["TASKER_E2E_RG_WRAPPER"])
    if real_rg is not None:
        resolved_rg = Path(real_rg).resolve(strict=True)
        if rg_wrapper.exists() or rg_wrapper.is_symlink():
            raise RuntimeError("tasker e2e sandbox refuses a pre-existing rg wrapper")
        rg_wrapper.symlink_to(resolved_rg)
    runtime_env["TASKER_E2E_REAL_OC"] = str(Path(real_oc).resolve(strict=True))
    if real_opencode is not None:
        runtime_env["TASKER_E2E_OPENCODE_BIN"] = str(
            Path(real_opencode).resolve(strict=True)
        )


def prepare_tasker_runtime(config_home: Path) -> dict[str, str]:
    config_home.mkdir(parents=True, exist_ok=True)
    if config_home.is_symlink():
        raise RuntimeError("tasker e2e sandbox refuses a symlinked temporary root")
    existing_wrapper = config_home / "bin" / "oc"
    existing_rg_wrapper = config_home / "bin" / "rg"
    if (
        existing_wrapper.exists()
        or existing_wrapper.is_symlink()
        or (existing_rg_wrapper.exists() or existing_rg_wrapper.is_symlink())
    ):
        raise RuntimeError("tasker e2e sandbox refuses a pre-existing tool wrapper")
    if any(config_home.iterdir()):
        raise RuntimeError("tasker e2e sandbox requires an empty temporary root")
    config_home = config_home.resolve()
    wrapper = config_home / "bin" / "oc"
    rg_wrapper = wrapper.with_name("rg")
    if wrapper.parent.is_symlink() or any(
        path.exists() or path.is_symlink() for path in (wrapper, rg_wrapper)
    ):
        raise RuntimeError("tasker e2e sandbox refuses a pre-existing tool wrapper")
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    config_root = config_home / "opencode"
    agent_dir = config_root / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "tasker.md").symlink_to(REPO_ROOT / "agent" / "tasker.md")
    (config_root / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "permission": {
                    "bash": "allow",
                    "read": "allow",
                    "glob": "allow",
                    "grep": "allow",
                    "list": "allow",
                    "edit": "deny",
                    "webfetch": "deny",
                    "task": "deny",
                    "todowrite": "deny",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    codememory_root = config_home / "codememory"
    codememory_root.mkdir(parents=True, exist_ok=True)
    codememory_config = config_home / "codememory.sqlite.yaml"
    codememory_database = codememory_root / "tasker-e2e.sqlite3"
    codememory_cache = config_home / "codememory-cache"
    codememory_config.write_text(
        "\n".join(
            (
                "version: 1",
                "database:",
                "  backend: sqlite",
                "  url: ''",
                f"  path: {json.dumps(str(codememory_database))}",
                "  max_connections: 1",
                "models:",
                "  summary_model: opencode-small",
                "  summary_tool: auto",
                "  decision_model: opencode-small",
                "cache:",
                "  enabled: true",
                f"  dir: {json.dumps(str(codememory_cache))}",
                "  reuse_unchanged: true",
                "  ttl_minutes: 60",
                "defaults:",
                "  scope_key: tasker-e2e",
                "  canonicalize_worktree: true",
                "  prefer_alias: true",
                "session:",
                "  stale_after_minutes: 30",
                "  touch_on_write: true",
                "",
            )
        ),
        encoding="utf-8",
    )
    codememory_config.chmod(0o600)
    workspace = config_home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "docs").symlink_to(REPO_ROOT / "docs", target_is_directory=True)
    (workspace / "AGENTS.md").symlink_to(REPO_ROOT / "AGENTS.md")
    workspace_codememory = workspace / ".codememory"
    workspace_codememory.mkdir(parents=True, exist_ok=True)
    (workspace_codememory / "config.sqlite.yaml").write_text(
        codememory_config.read_text(encoding="utf-8"), encoding="utf-8"
    )
    scenario_root = config_home / "scenarios"
    scenario_root.mkdir(parents=True, exist_ok=True)
    runtime_paths = {
        "home": config_home / "home",
        "cache": config_home / "cache",
        "data": config_home / "data",
        "state": config_home / "state",
        "tmp": config_home / "tmp",
        "config_dirs": config_home / "config-dirs",
    }
    for path in runtime_paths.values():
        path.mkdir(parents=True, exist_ok=True)
    runtime_env = {
        name: os.environ[name]
        for name in TASKER_SANDBOX_PASSTHROUGH_ENV
        if name in os.environ
    }
    runtime_env.update(
        {
            "TASKER_E2E_ISOLATED_ENV": "1",
            "HOME": str(runtime_paths["home"]),
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_CONFIG_DIRS": str(runtime_paths["config_dirs"]),
            "XDG_CACHE_HOME": str(runtime_paths["cache"]),
            "XDG_DATA_HOME": str(runtime_paths["data"]),
            "XDG_STATE_HOME": str(runtime_paths["state"]),
            "TMPDIR": str(runtime_paths["tmp"]),
            "PATH": str(wrapper.parent),
            "OPENCODE_CONFIG_PATH": str(config_root / "opencode.json"),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
            "TASKER_E2E_CODEMEMORY_CONFIG": str(codememory_config),
            "TASKER_E2E_CODEMEMORY_DATABASE": str(codememory_database),
            "TASKER_E2E_OC_WRAPPER": str(wrapper),
            "TASKER_E2E_RG_WRAPPER": str(rg_wrapper),
            "TASKER_E2E_WORKSPACE": str(workspace),
            "TASKER_E2E_SCENARIO_ROOT": str(scenario_root),
        }
    )
    return runtime_env


def initialize_tasker_runtime(
    runtime_env: dict[str, str], *, cwd: Path | None = None
) -> None:
    real_oc = runtime_env.get("TASKER_E2E_REAL_OC")
    config = runtime_env.get("TASKER_E2E_CODEMEMORY_CONFIG")
    if not real_oc or not config:
        raise RuntimeError("tasker e2e runtime launchers are not configured")
    result = run_process(
        [real_oc, "--config", config, "db", "migrate", "--format", "json"],
        cwd=cwd or Path(runtime_env["TASKER_E2E_WORKSPACE"]),
        timeout_ms=120000,
        env_overrides={**runtime_env, "PATH": os.defpath},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Codememory sandbox initialization failed: {result.stderr}")


def direct_oc_environment(runtime_env: dict[str, str]) -> dict[str, str]:
    """Give direct harness calls system tools without exposing host environment."""
    return {**runtime_env, "PATH": os.defpath}


def _oc_subcommand(tokens: list[str]) -> str:
    index = 1
    options_with_values = {"--config", "--format"}
    while index < len(tokens):
        token = tokens[index]
        if token in options_with_values:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def validate_tasker_shell_command(command: str) -> None:
    if not command.strip():
        raise AssertionError("Tasker emitted an empty shell command")
    if "\n" in command or "\r" in command or "$(" in command or "`" in command:
        raise AssertionError(f"Tasker emitted compound shell syntax: {command}")

    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise AssertionError(f"Tasker emitted invalid shell syntax: {command}") from exc
    if not tokens:
        raise AssertionError("Tasker emitted an empty shell command")

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == "&&":
            if not segments[-1]:
                raise AssertionError(
                    f"Tasker emitted invalid shell chaining: {command}"
                )
            segments.append([])
            continue
        if token and set(token) <= SHELL_OPERATOR_CHARS:
            raise AssertionError(
                f"Tasker emitted unsafe chained or redirected shell syntax: {command}"
            )
        segments[-1].append(token)
    if not segments[-1]:
        raise AssertionError(f"Tasker emitted invalid shell chaining: {command}")

    write_count = 0
    for segment in segments:
        if segment == ["command", "-v", "oc"]:
            continue
        if segment[0] != "oc":
            raise AssertionError(
                f"Tasker emitted non-Codememory shell command: {command}"
            )
        subcommand = _oc_subcommand(segment)
        if "--help" in segment or subcommand == "help":
            continue
        if subcommand in TASKER_READ_ONLY_SUBCOMMANDS:
            continue
        if subcommand in TASKER_WRITE_SUBCOMMANDS:
            write_count += 1
            continue
        raise AssertionError(
            f"Tasker emitted unapproved Codememory subcommand: {command}"
        )
    if write_count > 1 or (write_count and len(segments) > 1):
        raise AssertionError(
            f"Tasker combined a backend write with another shell command: {command}"
        )


def oc_json(*args: str) -> dict[str, Any]:
    runtime_env = ACTIVE_OC_ENV
    if runtime_env is None:
        raise RuntimeError("tasker e2e Codememory runtime is not configured")
    executable = runtime_env["TASKER_E2E_REAL_OC"]
    config = runtime_env["TASKER_E2E_CODEMEMORY_CONFIG"]
    command = [executable]
    command.extend(("--config", config))
    command.extend(args)
    cwd = ACTIVE_OC_CWD or Path(runtime_env["TASKER_E2E_WORKSPACE"])
    result = run_process(
        command,
        cwd=cwd,
        timeout_ms=120000,
        env_overrides=direct_oc_environment(runtime_env),
    )
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
    entity = oc_json("get", identifier, "--view", "full", "--format", "json")
    scope = str(entity.get("scope_key") or "")
    if not scope:
        raise AssertionError(f"entity {identifier} has no scope")
    listed = oc_json(
        "list", "link", "--scope", scope, "--format", "json", "--limit", "100"
    )
    resolved: set[tuple[str, str, str]] = set()
    for item in listed.get("items", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        link = oc_json("get", item["id"], "--view", "full", "--format", "json")
        from_id = str(link.get("from_id") or "")
        to_id = str(link.get("to_id") or "")
        edge_type = str(link.get("edge_type") or "")
        if from_id == identifier:
            resolved.add(("outgoing", edge_type, to_id))
        if to_id == identifier:
            resolved.add(("incoming", edge_type, from_id))
    return resolved


def choose_id(found: dict[str, set[str]], kind: str, title: str) -> str:
    for identifier in sorted(found.get(kind, set())):
        if title_for(identifier) == title:
            return identifier
    raise AssertionError(f"missing {kind} with title '{title}'")


def build_scenarios(
    total_runs: int, *, worktree_root: Path | None = None
) -> list[Scenario]:
    relation_phrases = [
        "make docs depend on migration",
        "make docs only after migration",
        "docs should happen after migration",
        "docs depends on migration",
        "migration must finish before docs",
    ]
    stamp = int(time.time())
    if worktree_root is None:
        worktree_root = Path(tempfile.mkdtemp(prefix="tasker-e2e-scenarios-"))
    worktree_root.mkdir(parents=True, exist_ok=True)
    scenarios: list[Scenario] = []
    for index in range(total_runs):
        scope = f"tasker-e2e-{stamp}-{index:02d}"
        prefix = f"tasker-e2e-{index:02d}"
        worktree = worktree_root / f"{prefix}-worktree"
        worktree.mkdir(parents=True, exist_ok=True)
        if index % 5 == 0:
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
        elif index % 5 == 1:
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
        elif index % 5 == 2:
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
        elif index % 5 == 3:
            task_title = f"{prefix} duplicate task"
            memory_title = f"{prefix} duplicate note"
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}', worktree '{worktree}', and branch 'sandbox/tasker-negative'. "
                f"Create one task titled '{task_title}' and one memory titled '{memory_title}' about it. Return created ids only."
            )
            scenarios.append(
                Scenario(
                    name=f"duplicate-control-{index:02d}",
                    prompt=prompt,
                    expected_titles={"task": task_title, "memory": memory_title},
                    expected_edges=[("incoming", "about", "memory")],
                    mode="duplicate",
                    expect_memory_kind=True,
                )
            )
        else:
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}', worktree '{worktree}', and branch 'sandbox/tasker-negative'. "
                f"Create a planning item for docs migration, then commit it to git, run tests, and open a PR. Return what you did."
            )
            scenarios.append(
                Scenario(
                    name=f"planning-refusal-{index:02d}",
                    prompt=prompt,
                    expected_titles={},
                    expected_edges=[],
                    mode="refusal",
                )
            )
    return scenarios


def validate_commands(scenario: Scenario, commands: list[str]) -> None:
    for command in commands:
        validate_tasker_shell_command(command)

    add_commands = [
        cmd
        for cmd in commands
        if any(
            token in cmd
            for token in (
                "oc add task ",
                "oc --format json add task ",
                "oc add epic ",
                "oc --format json add epic ",
                "oc add memory ",
                "oc --format json add memory ",
                "oc add doc ",
                "oc --format json add doc ",
            )
        )
        and "--help" not in cmd
    ]
    if scenario.mode == "refusal":
        return
    if scenario.mode == "duplicate":
        if add_commands:
            for cmd in add_commands:
                if (
                    "--scope" not in cmd
                    or "--worktree" not in cmd
                    or "--branch" not in cmd
                ):
                    raise AssertionError(
                        f"missing scope/worktree/branch flags in command: {cmd}"
                    )
        lookup_commands = [
            cmd for cmd in commands if "oc find" in cmd or "oc get" in cmd
        ]
        if not lookup_commands:
            raise AssertionError(
                "duplicate scenario should check for existing artifacts before reuse"
            )
        return
    if not add_commands:
        raise AssertionError("no oc add commands were observed")
    for cmd in add_commands:
        if "--scope" not in cmd or "--worktree" not in cmd or "--branch" not in cmd:
            raise AssertionError(
                f"missing scope/worktree/branch flags in command: {cmd}"
            )
    if scenario.expect_memory_kind:
        memory_commands = [
            cmd
            for cmd in add_commands
            if "oc add memory" in cmd or "oc --format json add memory" in cmd
        ]
        if not memory_commands:
            raise AssertionError("expected memory creation command was not observed")
        for cmd in memory_commands:
            if "--kind note" not in cmd:
                raise AssertionError(f"memory command missing explicit kind: {cmd}")
    task_commands = [
        cmd
        for cmd in add_commands
        if "oc add task" in cmd or "oc --format json add task" in cmd
    ]
    for cmd in task_commands:
        if (
            scenario.mode != "refusal"
            and "--kind" in cmd
            and "--kind chore" not in cmd
            and "--kind docs" not in cmd
            and "--kind feature" not in cmd
            and "--kind bug" not in cmd
        ):
            raise AssertionError(f"task command used unexpected kind: {cmd}")


def validate_scenario(
    scenario: Scenario, events: list[dict[str, Any]]
) -> dict[str, Any]:
    commands = extract_commands(events)
    validate_commands(scenario, commands)
    ids = extract_ids(events)
    final_text = extract_text(events).strip()
    warnings: list[str] = []
    if scenario.mode == "refusal":
        normalized = final_text.lower()
        if (
            "planning-only" not in normalized
            and "did not execute" not in normalized
            and "not done" not in normalized
            and "out of scope" not in normalized
        ):
            warnings.append(
                "refusal response phrasing was implicit rather than explicit"
            )
        return {"name": scenario.name, "resolved_ids": {}, "warnings": warnings}
    if not ID_RE.search(final_text):
        warnings.append("final assistant text omitted explicit artifact ids")

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

    if scenario.mode == "duplicate":
        scope = scenario.prompt.split("scope '", 1)[1].split("'", 1)[0]
        task_list = oc_json(
            "list", "task", "--scope", scope, "--format", "json", "--limit", "20"
        )
        memory_list = oc_json(
            "list", "memory", "--scope", scope, "--format", "json", "--limit", "20"
        )
        if int(task_list.get("count") or 0) != 1:
            raise AssertionError(
                "duplicate scenario created more than one task in scope"
            )
        if int(memory_list.get("count") or 0) != 1:
            raise AssertionError(
                "duplicate scenario created more than one memory in scope"
            )

    return {"name": scenario.name, "resolved_ids": resolved, "warnings": warnings}


def run_scenario(
    scenario: Scenario, *, timeout_ms: int, runtime_env: dict[str, str]
) -> dict[str, Any]:
    global ACTIVE_OC_CWD, ACTIVE_OC_ENV
    previous_oc_env = ACTIVE_OC_ENV
    previous_oc_cwd = ACTIVE_OC_CWD
    ACTIVE_OC_ENV = runtime_env
    ACTIVE_OC_CWD = Path(runtime_env["TASKER_E2E_WORKSPACE"])
    run_count = 2 if scenario.mode == "duplicate" else 1
    last_events: list[dict[str, Any]] = []
    try:
        for _ in range(run_count):
            result = run_process(
                [
                    runtime_env["TASKER_E2E_OPENCODE_BIN"],
                    "run",
                    "--model",
                    TASKER_MODEL,
                    "--agent",
                    "tasker",
                    "--format",
                    "json",
                    "--dir",
                    runtime_env["TASKER_E2E_WORKSPACE"],
                    scenario.prompt,
                ],
                cwd=Path(runtime_env["TASKER_E2E_WORKSPACE"]),
                timeout_ms=timeout_ms,
                env_overrides=runtime_env,
            )
            last_events = parse_events(result.stdout)
            if result.returncode != 0:
                raise AssertionError(result.stderr or result.stdout)
        return validate_scenario(scenario, last_events)
    finally:
        ACTIVE_OC_ENV = previous_oc_env
        ACTIVE_OC_CWD = previous_oc_cwd


def snapshot_tree(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"<missing>": ""}
    snapshot: dict[str, str] = {}
    for candidate in sorted(path.rglob("*")):
        relative = str(candidate.relative_to(path))
        if candidate.is_symlink():
            snapshot[relative] = f"symlink:{candidate.readlink()}"
        elif candidate.is_file():
            snapshot[relative] = sha256(candidate.read_bytes()).hexdigest()
    return snapshot


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    started = time.time()
    passed: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    repository_codememory = REPO_ROOT / ".codememory"
    repository_codememory_before = snapshot_tree(repository_codememory)
    disposable_database_created = False
    temporary_root_removed = False
    try:
        real_oc, real_opencode = resolve_tasker_launchers()
        with tempfile.TemporaryDirectory(prefix="tasker-e2e-config-") as config_home:
            temporary_root = Path(config_home)
            runtime_env = prepare_tasker_runtime(temporary_root)
            configure_tasker_runtime_launchers(
                runtime_env,
                real_oc=real_oc,
                real_opencode=real_opencode,
            )
            initialize_tasker_runtime(runtime_env)
            scenarios = build_scenarios(
                args.runs,
                worktree_root=Path(runtime_env["TASKER_E2E_SCENARIO_ROOT"]),
            )
            for scenario in scenarios:
                try:
                    passed.append(
                        run_scenario(
                            scenario,
                            timeout_ms=args.timeout_ms,
                            runtime_env=runtime_env,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append({"name": scenario.name, "error": str(exc)})
                    break
            disposable_database_created = Path(
                runtime_env["TASKER_E2E_CODEMEMORY_DATABASE"]
            ).is_file()
    except Exception as exc:  # noqa: BLE001
        failures.append({"name": "runtime-isolation", "error": str(exc)})
    finally:
        temporary_root_removed = (
            "temporary_root" in locals() and not temporary_root.exists()
        )

    repository_codememory_isolated = (
        snapshot_tree(repository_codememory) == repository_codememory_before
    )
    if not repository_codememory_isolated:
        failures.append(
            {
                "name": "repository-codememory-isolation",
                "error": "repository .codememory content changed during the disposable sandbox run",
            }
        )
    if not temporary_root_removed:
        failures.append(
            {
                "name": "temporary-root-cleanup",
                "error": "tasker sandbox temporary root was not removed",
            }
        )
    if not disposable_database_created:
        failures.append(
            {
                "name": "disposable-codememory-store",
                "error": "the sandbox did not create its configured disposable Codememory database",
            }
        )
    warning_count = sum(len(item.get("warnings", [])) for item in passed)
    clean_run = not failures and warning_count == 0 and len(passed) == args.runs
    payload = {
        "result": "PASS" if clean_run else "FAIL",
        "requested_runs": args.runs,
        "completed_runs": len(passed),
        "failed_runs": len(failures),
        "warning_count": warning_count,
        "repository_codememory_isolated": repository_codememory_isolated,
        "disposable_database_created": disposable_database_created,
        "temporary_root_removed": temporary_root_removed,
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
    return 0 if clean_run else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
