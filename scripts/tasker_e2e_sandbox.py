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
# This public fallback is available without inheriting host provider configuration.
TASKER_MODEL = "opencode/deepseek-v4-flash-free"
SHELL_OPERATOR_CHARS = frozenset(";&|<>")
TASKER_READ_ONLY_SUBCOMMANDS = frozenset(
    {"config", "current", "find", "get", "history", "list", "next", "queue"}
)
TASKER_WRITE_SUBCOMMANDS = frozenset(
    {"add", "cancel", "link", "set", "unlink"}
)
TASKER_RECOVERY_SUBCOMMANDS = frozenset({"archive", "restore"})
TASKER_RESEARCH_AGENTS = frozenset({"explore", "librarian"})
TASKER_SANDBOX_STRIPPED_ENV = frozenset(
    {
        "OPENCODE_CONFIG_PATH",
        "OPENCODE_CONFIG_CONTENT",
        "CODEMEMORY_SQLITE_PATH",
        "DATABASE_URL",
        "CODEMEMORY_BIN",
        "CODEMEMORY_CONFIG_PATH",
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
    require_bootstrap: bool = False
    require_research: bool = False
    scope: str = ""


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
    isolated = bool(
        env_overrides and env_overrides.get("TASKER_E2E_ISOLATED_ENV") == "1"
    )
    env = {} if isolated else os.environ.copy()
    env.setdefault("CI", "true")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_EDITOR", "true")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("PAGER", "cat")
    env.setdefault("GCM_INTERACTIVE", "never")
    if env_overrides:
        env.update(env_overrides)
    if isolated:
        for name in TASKER_SANDBOX_STRIPPED_ENV:
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


def render_tasker_oc_wrapper(
    real_oc: str,
    codememory_config: Path,
    recovery_tokens: Path,
    record_inspections: Path,
    planning_links: Path,
    allowed_scope: str | None,
) -> str:
    """Render a per-run OC gateway that cannot select a host-backed store."""
    template = """#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REAL_OC = __REAL_OC__
CONFIG_PATH = __CONFIG_PATH__
RECOVERY_TOKENS = Path(__RECOVERY_TOKENS__)
RECORD_INSPECTIONS = Path(__RECORD_INSPECTIONS__)
PLANNING_LINKS = Path(__PLANNING_LINKS__)
ALLOWED_SCOPE = __ALLOWED_SCOPE__


def reject() -> None:
    print("tasker sandbox rejected unsafe Codememory command", file=sys.stderr)
    raise SystemExit(64)


def option_values(args: list[str], option: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == option:
            if index + 1 >= len(args) or not args[index + 1]:
                reject()
            values.append(args[index + 1])
            index += 2
            continue
        prefix = option + "="
        if argument.startswith(prefix):
            value = argument[len(prefix) :]
            if not value:
                reject()
            values.append(value)
        index += 1
    return values


def one_option(args: list[str], option: str, *, required: bool = False) -> str | None:
    values = option_values(args, option)
    if len(values) > 1 or (required and not values):
        reject()
    return values[0] if values else None


def require_allowed_scope(args: list[str], *, required: bool = False) -> str | None:
    scope = one_option(args, "--scope", required=required)
    if ALLOWED_SCOPE and scope != ALLOWED_SCOPE:
        reject()
    return scope


def split_command(args: list[str]) -> tuple[str, list[str]]:
    if not args or args[0].startswith("-"):
        reject()
    return args[0], args[1:]


def safe_environment() -> dict[str, str]:
    environment = {"PATH": os.defpath}
    for name in ("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def run_oc(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [REAL_OC, "--config", CONFIG_PATH, *args],
        capture_output=True,
        text=True,
        check=False,
        env=safe_environment(),
    )


def relay(result: subprocess.CompletedProcess[str]) -> None:
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)


def load_recovery_tokens() -> dict[str, dict[str, str]]:
    if not RECOVERY_TOKENS.exists():
        return {}
    try:
        payload = json.loads(RECOVERY_TOKENS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reject()
    if not isinstance(payload, dict):
        reject()
    return {
        str(token): value
        for token, value in payload.items()
        if isinstance(value, dict)
        and all(isinstance(value.get(field), str) for field in ("command", "target", "reason"))
    }


def save_recovery_tokens(tokens: dict[str, dict[str, str]]) -> None:
    temporary = RECOVERY_TOKENS.with_suffix(".tmp")
    temporary.write_text(json.dumps(tokens, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(RECOVERY_TOKENS)


def load_record_inspections() -> dict[str, dict[str, object]]:
    if not RECORD_INSPECTIONS.exists():
        return {}
    try:
        payload = json.loads(RECORD_INSPECTIONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reject()
    if not isinstance(payload, dict):
        reject()
    return {
        str(identifier): record
        for identifier, record in payload.items()
        if isinstance(record, dict)
    }


def save_record_inspections(inspections: dict[str, dict[str, object]]) -> None:
    temporary = RECORD_INSPECTIONS.with_suffix(".tmp")
    temporary.write_text(json.dumps(inspections, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(RECORD_INSPECTIONS)


def load_planning_links() -> dict[str, dict[str, str]]:
    if not PLANNING_LINKS.exists():
        return {}
    try:
        payload = json.loads(PLANNING_LINKS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reject()
    if not isinstance(payload, dict):
        reject()
    return {
        str(identifier): link
        for identifier, link in payload.items()
        if isinstance(link, dict)
        and all(isinstance(link.get(field), str) for field in ("from_id", "edge_type", "to_id"))
    }


def save_planning_links(links: dict[str, dict[str, str]]) -> None:
    temporary = PLANNING_LINKS.with_suffix(".tmp")
    temporary.write_text(json.dumps(links, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(PLANNING_LINKS)


def allowed_link(source: str, relation: str, target: str) -> bool:
    return (
        relation == "parent-of"
        and source.startswith("epic_")
        and target.startswith("task_")
    ) or (
        relation == "depends-on"
        and source.startswith("task_")
        and target.startswith("task_")
    ) or (
        relation == "about"
        and source.startswith("memory_")
        and target.startswith(("task_", "epic_", "doc_"))
    )


def require_unreferenced(target_id: str) -> None:
    if any(
        target_id in {link["from_id"], link["to_id"]}
        for link in load_planning_links().values()
    ):
        reject()


def require_recovery_inspection(target_id: str) -> None:
    record = load_record_inspections().get(target_id)
    if not record or record.get("type") not in {"memory", "doc"}:
        reject()
    require_unreferenced(target_id)


def require_cancel_inspection(task_id: str) -> None:
    record = load_record_inspections().get(task_id)
    if (
        not record
        or record.get("type") != "task"
        or record.get("status") != "not-started"
        or record.get("claimed_by_active_session") is True
    ):
        reject()


def require_unlink_inspection(link_id: str) -> None:
    record = load_record_inspections().get(link_id)
    if (
        not record
        or record.get("type") != "link"
        or not isinstance(record.get("from_id"), str)
        or not isinstance(record.get("edge_type"), str)
        or not isinstance(record.get("to_id"), str)
        or not allowed_link(record["from_id"], record["edge_type"], record["to_id"])
    ):
        reject()


def cache_full_record_inspection(
    args: list[str], result: subprocess.CompletedProcess[str]
) -> None:
    command, rest = split_command(args)
    if (
        command != "get"
        or not rest
        or one_option(args, "--view") != "full"
        or one_option(args, "--format") != "json"
    ):
        return
    try:
        record = json.loads(result.stdout)
    except json.JSONDecodeError:
        reject()
    identifier = record.get("id") if isinstance(record, dict) else None
    if not isinstance(identifier, str) or not identifier:
        reject()
    inspections = load_record_inspections()
    inspections[identifier] = record
    save_record_inspections(inspections)


def cache_planning_link(args: list[str], result: subprocess.CompletedProcess[str]) -> None:
    command, rest = split_command(args)
    if command != "link":
        return
    try:
        record = json.loads(result.stdout)
    except json.JSONDecodeError:
        reject()
    identifier = record.get("id") if isinstance(record, dict) else None
    if not isinstance(identifier, str) or not identifier or len(rest) < 3:
        reject()
    links = load_planning_links()
    links[identifier] = {
        "from_id": rest[0],
        "edge_type": rest[1],
        "to_id": rest[2],
    }
    save_planning_links(links)


def validate_command(args: list[str]) -> tuple[str, str | None, str | None, str | None]:
    if not args:
        reject()
    for argument in args:
        if argument in {"--config", "--override", "--worktree", "--branch", "--task"}:
            reject()
        if argument.startswith(("--config=", "--override=", "--worktree=", "--branch=", "--task=")):
            reject()
    if "--help" in args or "-h" in args:
        if args != ["--help"]:
            reject()
        return "help", None, None, None

    command, rest = split_command(args)
    if command == "config":
        if not rest or rest[0] != "--doctor":
            reject()
    elif command in {"current", "find", "get", "history", "list", "next", "queue"}:
        if command == "find":
            require_allowed_scope(args, required=True)
        elif command == "list":
            require_allowed_scope(args)
    elif command == "db":
        if not rest or rest[0] != "migrate":
            reject()
    elif command == "add":
        if len(rest) < 2 or rest[0] not in {"task", "epic", "memory", "doc"}:
            reject()
        require_allowed_scope(args, required=True)
    elif command == "link":
        if len(rest) < 3:
            reject()
        source, relation, target = rest[:3]
        if not allowed_link(source, relation, target):
            reject()
        if one_option(args, "--format", required=True) != "json":
            reject()
        if any(
            link == {"from_id": source, "edge_type": relation, "to_id": target}
            for link in load_planning_links().values()
        ):
            reject()
    elif command == "set":
        if len(rest) < 3 or not rest[0].startswith(("task_", "epic_")) or rest[1] == "status":
            reject()
        one_option(args, "--reason", required=True)
        one_option(args, "--expected-revision", required=True)
    elif command == "cancel":
        if not rest or not rest[0].startswith("task_"):
            reject()
        one_option(args, "--why", required=True)
        if one_option(args, "--expected-revision", required=True) != "1":
            reject()
        return command, rest[0], None, None
    elif command == "unlink":
        if not rest or not rest[0].startswith("link_"):
            reject()
        one_option(args, "--reason", required=True)
        return command, rest[0], None, None
    elif command in {"archive", "restore"}:
        if not rest or not rest[0].startswith(("memory_", "doc_")):
            reject()
        reason = one_option(args, "--reason", required=True)
        if one_option(args, "--format", required=True) != "json":
            reject()
        return command, rest[0], reason, one_option(args, "--apply")
    else:
        reject()
    return command, None, None, None


def main() -> int:
    args = sys.argv[1:]
    command, target, reason, approval_code = validate_command(args)
    if command in {"archive", "restore"} and approval_code:
        expected = {"command": command, "target": target, "reason": reason}
        if load_recovery_tokens().get(approval_code) != expected:
            reject()
    if command == "cancel":
        require_cancel_inspection(target or "")
    if command == "unlink":
        require_unlink_inspection(target or "")
    if command in {"archive", "restore"}:
        require_recovery_inspection(target or "")

    result = run_oc(args)
    relay(result)
    if result.returncode != 0:
        return result.returncode
    if command == "help":
        return 0

    cache_full_record_inspection(args, result)
    cache_planning_link(args, result)
    if command in {"cancel", "unlink"}:
        inspections = load_record_inspections()
        inspections.pop(target or "", None)
        save_record_inspections(inspections)
    if command == "unlink":
        links = load_planning_links()
        links.pop(target or "", None)
        save_planning_links(links)

    if command in {"archive", "restore"}:
        tokens = load_recovery_tokens()
        if approval_code:
            tokens.pop(approval_code, None)
            save_recovery_tokens(tokens)
            return 0
        try:
            plan_hash = json.loads(result.stdout).get("plan_hash")
        except json.JSONDecodeError:
            reject()
        if not isinstance(plan_hash, str) or not plan_hash:
            reject()
        tokens[plan_hash] = {"command": command, "target": target, "reason": reason}
        save_recovery_tokens(tokens)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    return (
        template.replace("__REAL_OC__", repr(real_oc))
        .replace("__CONFIG_PATH__", repr(str(codememory_config)))
        .replace("__RECOVERY_TOKENS__", repr(str(recovery_tokens)))
        .replace("__RECORD_INSPECTIONS__", repr(str(record_inspections)))
        .replace("__PLANNING_LINKS__", repr(str(planning_links)))
        .replace("__ALLOWED_SCOPE__", repr(allowed_scope))
    )


def render_sandbox_research_agent(source: Path) -> str:
    """Keep the shipped read-only agent contract while using the isolated test model."""
    content = source.read_text(encoding="utf-8")
    rendered, replacements = re.subn(
        r"(?m)^model: .+$", f"model: {TASKER_MODEL}", content, count=1
    )
    if replacements != 1:
        raise RuntimeError(f"sandbox research agent has no model declaration: {source}")
    return rendered


def prepare_tasker_runtime(
    config_home: Path, *, allowed_scope: str | None = None
) -> dict[str, str]:
    config_root = config_home / "opencode"
    agent_dir = config_root / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "tasker.md").symlink_to(REPO_ROOT / "agent" / "tasker.md")
    (agent_dir / "explore.md").write_text(
        render_sandbox_research_agent(REPO_ROOT / "agent" / "explore.md"),
        encoding="utf-8",
    )
    (agent_dir / "librarian.md").write_text(
        render_sandbox_research_agent(REPO_ROOT / "agent" / "librarian.md"),
        encoding="utf-8",
    )
    (config_root / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "agent": {
                    "build": {"disable": True},
                    "general": {"disable": True},
                    "plan": {"disable": True},
                },
                "permission": {
                    "bash": {
                        "*": "deny",
                        "command -v oc": "allow",
                        "oc --help": "allow",
                        "oc config --doctor*": "allow",
                        "oc current*": "allow",
                        "oc next*": "allow",
                        "oc queue*": "allow",
                        "oc find *": "allow",
                        "oc get *": "allow",
                        "oc list*": "allow",
                        "oc history *": "allow",
                        "oc db migrate*": "allow",
                        "oc add task *": "allow",
                        "oc add epic *": "allow",
                        "oc add memory *": "allow",
                        "oc add doc *": "allow",
                        "oc set task_*": "allow",
                        "oc set epic_*": "allow",
                        "oc link *": "allow",
                        "oc cancel task_*": "allow",
                        "oc unlink link_*": "allow",
                        "oc archive memory_*": "allow",
                        "oc archive doc_*": "allow",
                        "oc restore memory_*": "allow",
                        "oc restore doc_*": "allow",
                        "oc init *": "deny",
                        "oc db backup *": "deny",
                        "oc db restore *": "deny",
                        "oc done *": "deny",
                        "oc fail *": "deny",
                        "oc transition *": "deny",
                        "oc event *": "deny",
                        "oc end-session *": "deny",
                    },
                    "read": "allow",
                    "glob": "allow",
                    "grep": "allow",
                    "list": "allow",
                    "edit": "deny",
                    "webfetch": "allow",
                    "task": "allow",
                    "todowrite": "deny",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    real_oc = shutil.which("oc")
    if real_oc is None:
        raise RuntimeError("tasker e2e sandbox requires an installed oc launcher")
    real_opencode = shutil.which("opencode")
    if real_opencode is None:
        raise RuntimeError("tasker e2e sandbox requires an installed opencode launcher")
    codememory_home = config_home / "codememory"
    codememory_home.mkdir(parents=True, exist_ok=True)
    codememory_config = config_home / "codememory.sqlite.yaml"
    codememory_database = codememory_home / "tasker-e2e.sqlite3"
    codememory_config.write_text(
        "\n".join(
            (
                "version: 1",
                "database:",
                "  backend: sqlite",
                "  url: ''",
                f"  path: {codememory_database}",
                "  max_connections: 1",
                "cache:",
                "  enabled: true",
                f"  dir: {config_home / 'codememory-cache'}",
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
    workspace = config_home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "docs").symlink_to(REPO_ROOT / "docs", target_is_directory=True)
    (workspace / "AGENTS.md").symlink_to(REPO_ROOT / "AGENTS.md")
    workspace_codememory = workspace / ".codememory"
    workspace_codememory.mkdir(parents=True, exist_ok=True)
    (workspace_codememory / "config.sqlite.yaml").write_text(
        codememory_config.read_text(encoding="utf-8"), encoding="utf-8"
    )
    wrapper_dir = config_home / "bin"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper = wrapper_dir / "oc"
    recovery_tokens = config_home / "recovery-approvals.json"
    record_inspections = config_home / "record-inspections.json"
    planning_links = config_home / "planning-links.json"
    wrapper.write_text(
        render_tasker_oc_wrapper(
            real_oc,
            codememory_config,
            recovery_tokens,
            record_inspections,
            planning_links,
            allowed_scope,
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
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
        name: value
        for name in ("LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "WINDIR")
        if (value := os.environ.get(name))
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
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
            "PATH": f"{wrapper_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "TASKER_E2E_CODEMEMORY_CONFIG": str(codememory_config),
            "TASKER_E2E_CODEMEMORY_DATABASE": str(codememory_database),
            "TASKER_E2E_RECOVERY_APPROVALS": str(recovery_tokens),
            "TASKER_E2E_RECORD_INSPECTIONS": str(record_inspections),
            "TASKER_E2E_PLANNING_LINKS": str(planning_links),
            "TASKER_E2E_OC_WRAPPER": str(wrapper),
            "TASKER_E2E_WORKSPACE": str(workspace),
            "TASKER_E2E_ALLOWED_SCOPE": allowed_scope or "",
            "TASKER_E2E_REAL_OC": str(Path(real_oc).resolve()),
            "TASKER_E2E_OPENCODE_BIN": str(Path(real_opencode).resolve()),
        }
    )
    return runtime_env


def _oc_subcommand_index(tokens: list[str]) -> int:
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
        return index
    return len(tokens)


def _oc_subcommand(tokens: list[str]) -> str:
    index = _oc_subcommand_index(tokens)
    return tokens[index] if index < len(tokens) else ""


def _validate_global_options(tokens: list[str]) -> None:
    if len(tokens) > 1 and tokens[1].startswith("-"):
        raise AssertionError(
            f"Tasker emitted unapproved leading Codememory option: {' '.join(tokens)}"
        )


def _oc_command_path(tokens: list[str]) -> tuple[str, str]:
    index = _oc_subcommand_index(tokens)
    if index >= len(tokens):
        return "", ""
    first = tokens[index]
    second = ""
    if first == "db" and index + 1 < len(tokens):
        second = tokens[index + 1]
    return first, second


def _option_value(tokens: list[str], option: str) -> str | None:
    for index, token in enumerate(tokens):
        if token == option and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(f"{option}="):
            return token.split("=", 1)[1]
    return None


def _has_option(tokens: list[str], option: str) -> bool:
    return _option_value(tokens, option) is not None or option in tokens


def _is_tasker_write(tokens: list[str]) -> bool:
    command, nested = _oc_command_path(tokens)
    if command in TASKER_WRITE_SUBCOMMANDS:
        return True
    if command == "db" and nested == "migrate":
        return True
    if command in TASKER_RECOVERY_SUBCOMMANDS:
        return _has_option(tokens, "--apply")
    return False


def _is_tasker_read_only(tokens: list[str]) -> bool:
    command, _nested = _oc_command_path(tokens)
    if command in TASKER_READ_ONLY_SUBCOMMANDS:
        return True
    return command in TASKER_RECOVERY_SUBCOMMANDS and not _has_option(
        tokens, "--apply"
    )


def _validate_add_command(tokens: list[str]) -> None:
    index = _oc_subcommand_index(tokens)
    if index + 2 >= len(tokens):
        raise AssertionError("Tasker add command is missing entity or title")
    entity = tokens[index + 1]
    if entity not in {"task", "epic", "session", "memory", "doc"}:
        raise AssertionError(f"Tasker used unsupported add entity: {entity}")
    if _option_value(tokens, "--scope") is None:
        raise AssertionError(f"Tasker add command is missing --scope: {' '.join(tokens)}")
    if entity == "session":
        raise AssertionError("Tasker must not create execution sessions")
    if any(_option_value(tokens, option) is not None for option in ("--worktree", "--branch")):
        raise AssertionError(
            f"Tasker passed execution-only worktree/branch flags to {entity}: {' '.join(tokens)}"
        )
    if entity == "memory" and _option_value(tokens, "--kind") is None:
        raise AssertionError(f"Tasker memory command is missing --kind: {' '.join(tokens)}")
    if entity == "doc" and (
        _option_value(tokens, "--type") is None or _option_value(tokens, "--ref") is None
    ):
        raise AssertionError(f"Tasker document command is missing --type or --ref: {' '.join(tokens)}")


def _validate_recovery_command(tokens: list[str]) -> None:
    index = _oc_subcommand_index(tokens)
    if index + 1 >= len(tokens) or not tokens[index + 1].startswith(("memory_", "doc_")):
        raise AssertionError("Tasker archive/restore commands require a memory or doc id")
    if _option_value(tokens, "--reason") is None:
        raise AssertionError("Tasker archive/restore command is missing --reason")
    if _option_value(tokens, "--format") != "json":
        raise AssertionError("Tasker archive/restore commands require --format json")
    if _has_option(tokens, "--override"):
        raise AssertionError("Tasker archive/restore commands must not use overrides")


def _validate_write_command(tokens: list[str]) -> None:
    command, nested = _oc_command_path(tokens)
    if command == "add":
        _validate_add_command(tokens)
    elif command == "link":
        index = _oc_subcommand_index(tokens)
        if index + 3 >= len(tokens):
            raise AssertionError("Tasker link command is missing endpoints")
        source, relation, target = tokens[index + 1 : index + 4]
        allowed_link = (
            relation == "parent-of"
            and source.startswith("epic_")
            and target.startswith("task_")
        ) or (
            relation == "depends-on"
            and source.startswith("task_")
            and target.startswith("task_")
        ) or (
            relation == "about"
            and source.startswith("memory_")
            and target.startswith(("task_", "epic_", "doc_"))
        )
        if not allowed_link:
            raise AssertionError("Tasker must not create execution/session links")
        if _option_value(tokens, "--format") != "json":
            raise AssertionError("Tasker link command requires --format json")
    elif command == "set":
        index = _oc_subcommand_index(tokens)
        if index + 3 >= len(tokens) or tokens[index + 2] == "status":
            raise AssertionError("Tasker may only update explicit non-status planning metadata")
        if _option_value(tokens, "--reason") is None:
            raise AssertionError("Tasker set command is missing --reason")
        if _option_value(tokens, "--expected-revision") is None:
            raise AssertionError("Tasker set command is missing --expected-revision")
        if _has_option(tokens, "--override"):
            raise AssertionError("Tasker must not use set overrides")
    elif command == "cancel":
        if _option_value(tokens, "--why") is None:
            raise AssertionError("Tasker cancel command is missing --why")
        if _option_value(tokens, "--expected-revision") is None:
            raise AssertionError("Tasker cancel command is missing --expected-revision")
    elif command == "unlink":
        if _option_value(tokens, "--reason") is None:
            raise AssertionError("Tasker unlink command is missing --reason")
    elif command in TASKER_RECOVERY_SUBCOMMANDS:
        _validate_recovery_command(tokens)
    elif command == "db" and nested != "migrate":
        raise AssertionError("Tasker may write only through oc db migrate")


def parse_tasker_shell_command(command: str) -> list[list[str]]:
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
            raise AssertionError(f"Tasker emitted chained shell syntax: {command}")
        if token and set(token) <= SHELL_OPERATOR_CHARS:
            raise AssertionError(
                f"Tasker emitted unsafe chained or redirected shell syntax: {command}"
            )
        segments[-1].append(token)
    if not segments[-1]:
        raise AssertionError(f"Tasker emitted invalid shell chaining: {command}")

    return segments


def validate_tasker_shell_command(command: str) -> None:
    segments = parse_tasker_shell_command(command)
    write_count = 0
    for segment in segments:
        if segment == ["command", "-v", "oc"]:
            continue
        if segment[0] != "oc":
            raise AssertionError(
                f"Tasker emitted non-Codememory shell command: {command}"
            )
        if "--help" in segment or "-h" in segment:
            if segment != ["oc", "--help"]:
                raise AssertionError(
                    f"Tasker emitted unapproved Codememory help command: {command}"
                )
            continue
        _validate_global_options(segment)
        for token in segment:
            if token in {"--config", "--override", "--worktree", "--branch", "--task"} or token.startswith(
                ("--config=", "--override=", "--worktree=", "--branch=", "--task=")
            ):
                raise AssertionError(
                    f"Tasker emitted sandbox-escaping Codememory option: {command}"
                )
        subcommand = _oc_subcommand(segment)
        if subcommand == "config" and "--doctor" not in segment:
            raise AssertionError(
                f"Tasker emitted unapproved Codememory config command: {command}"
            )
        if subcommand in TASKER_RECOVERY_SUBCOMMANDS:
            _validate_recovery_command(segment)
        if _is_tasker_read_only(segment):
            continue
        if _is_tasker_write(segment):
            _validate_write_command(segment)
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
    result = run_process(
        ["oc", *args],
        cwd=ACTIVE_OC_CWD or REPO_ROOT,
        timeout_ms=120000,
        env_overrides=ACTIVE_OC_ENV,
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


def extract_research_delegations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [delegation for _, delegation in extract_research_delegation_events(events)]


def extract_research_delegation_events(
    events: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    indexed_delegations: list[tuple[int, dict[str, Any]]] = []
    for event_index, event in enumerate(events):
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        if part.get("tool") != "task":
            continue
        state = part.get("state") or {}
        input_payload = state.get("input") or {}
        if not isinstance(input_payload, dict):
            continue
        agent = str(input_payload.get("subagent_type") or input_payload.get("agent") or "")
        prompt = str(input_payload.get("prompt") or "")
        delegation = {
            "agent": agent,
            "prompt": prompt,
            "completed": bool(state.get("output")),
        }
        indexed_delegations.append((event_index, delegation))
    return indexed_delegations


def validate_tasker_research_delegations(delegations: list[dict[str, Any]]) -> None:
    if len(delegations) > 2:
        raise AssertionError("Tasker delegated more than two total research requests")
    for delegation in delegations:
        agent = delegation.get("agent", "")
        prompt = delegation.get("prompt", "")
        if agent not in TASKER_RESEARCH_AGENTS:
            raise AssertionError(f"Tasker delegated to unsupported agent: {agent}")
        lowered = prompt.lower()
        required_packet_sections = {
            "objective": ("objective",),
            "scope": ("scope", "workspace root", "inspect exactly"),
            "ownership": (
                "ownership",
                "read-only explore agent",
                "read-only librarian",
                "explore agent",
                "librarian",
            ),
            "acceptance": (
                "acceptance",
                "return in your final message",
                "return a ",
                "return an ",
            ),
            "required checks": (
                "required checks",
                "hard constraints",
                "questions to answer",
                "only job",
            ),
            "evidence": ("evidence", "quote", "line number"),
        }
        for section, markers in required_packet_sections.items():
            if not any(marker in lowered for marker in markers):
                raise AssertionError(
                    f"Tasker research delegation is missing {section}: {prompt}"
                )
        sentences = re.split(r"[.!?]", lowered)
        prohibited_actions = {
            "implementation": (
                ("implement", "write", "edit"),
                ("implement", "write", "edit"),
            ),
            "tests": (("run tests",), ("run tests",)),
            "git": (("run git",), ("git",)),
            "Codememory": (
                ("create codememory", "oc add", "oc link", "oc set"),
                ("oc", "codememory"),
            ),
            "delegation": (("delegate",), ("delegat",)),
            "validation": (("validate",), ("validat",)),
        }
        for action, (references, denial_terms) in prohibited_actions.items():
            if not any(reference in lowered for reference in references):
                continue
            explicitly_denied = any(
                re.search(r"\b(?:do not|don't|never)\b", sentence)
                and any(term in sentence for term in denial_terms)
                for sentence in sentences
            )
            if not explicitly_denied:
                raise AssertionError(
                    f"Tasker research delegation permits prohibited {action} work: {prompt}"
                )


def validate_research_precedes_persistence(
    scenario: Scenario, events: list[dict[str, Any]], final_text: str
) -> None:
    if not scenario.require_research:
        return
    research_events = extract_research_delegation_events(events)
    if not research_events:
        raise AssertionError("scenario required a bounded research delegation")
    first_write_index: int | None = None
    for event_index, event in enumerate(events):
        part = event.get("part") or {}
        if part.get("tool") != "bash":
            continue
        state = part.get("state") or {}
        input_payload = state.get("input") or {}
        command = input_payload.get("command")
        if not isinstance(command, str):
            continue
        if any(
            _is_tasker_write(segment)
            for segment in parse_tasker_shell_command(command)
        ):
            first_write_index = event_index
            break
    if first_write_index is not None and any(
        research_index >= first_write_index for research_index, _ in research_events
    ):
        raise AssertionError("Tasker persisted before completing required research")
    if first_write_index is not None and not any(
        research_index < first_write_index and delegation.get("completed")
        for research_index, delegation in research_events
    ):
        raise AssertionError(
            "Tasker persisted before a required research delegation completed"
        )
    if "research synthesis" not in final_text.lower():
        raise AssertionError("Tasker response omitted the required research synthesis")


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


def link_records_for(identifier: str) -> list[tuple[str, str, str, str]]:
    entity = oc_json("get", identifier, "--view", "full", "--format", "json")
    scope = str(entity.get("scope_key") or "")
    if not scope:
        raise AssertionError(f"entity {identifier} has no scope")
    listed = oc_json(
        "list", "link", "--scope", scope, "--format", "json", "--limit", "100"
    )
    resolved: list[tuple[str, str, str, str]] = []
    for item in listed.get("items", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        link = oc_json("get", item["id"], "--view", "full", "--format", "json")
        from_id = str(link.get("from_id") or "")
        to_id = str(link.get("to_id") or "")
        edge_type = str(link.get("edge_type") or "")
        if from_id == identifier:
            resolved.append((str(item["id"]), "outgoing", edge_type, to_id))
        if to_id == identifier:
            resolved.append((str(item["id"]), "incoming", edge_type, from_id))
    return resolved


def links_for(identifier: str) -> set[tuple[str, str, str]]:
    return {
        (direction, edge_type, target)
        for _link_id, direction, edge_type, target in link_records_for(identifier)
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
        prefix = f"tasker-e2e-{index:02d}"
        if index % 5 == 0:
            task_title = f"{prefix} task"
            memory_title = f"{prefix} memory"
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}'. "
                "Before persistence, delegate exactly one bounded read-only explore request to inspect docs/codememory-workflow.md and docs/codememory-conventions.md; make no other research delegation, then synthesize its evidence. Inspect the workspace `.codememory/config.sqlite.yaml` with the read tool after `oc config --doctor`; do not use unsupported `oc config --show`. "
                f"Create exactly one task titled '{task_title}' and one durable note titled '{memory_title}'. "
                f"Link the durable note to the task, do not edit files or run git, and return created ids, links, and a `Research synthesis:` line."
            )
            scenarios.append(
                Scenario(
                    name=f"task-memory-{index:02d}",
                    prompt=prompt,
                    expected_titles={"task": task_title, "memory": memory_title},
                    expected_edges=[("incoming", "about", "memory")],
                    expect_memory_kind=True,
                    require_bootstrap=index == 0,
                    require_research=True,
                    scope=scope,
                )
            )
        elif index % 5 == 1:
            epic_title = f"{prefix} epic"
            migration_title = f"{prefix} migration"
            docs_title = f"{prefix} docs"
            relation = relation_phrases[index % len(relation_phrases)]
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}'. "
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
                    scope=scope,
                )
            )
        elif index % 5 == 2:
            epic_title = f"{prefix} epic"
            a_title = f"{prefix} task a"
            b_title = f"{prefix} task b"
            c_title = f"{prefix} task c"
            memory_title = f"{prefix} note"
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}'. "
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
                    scope=scope,
                )
            )
        elif index % 5 == 3:
            task_title = f"{prefix} duplicate task"
            memory_title = f"{prefix} duplicate note"
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}'. "
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
                    scope=scope,
                )
            )
        else:
            prompt = (
                f"Planning-only request. Use Codememory scope '{scope}'. "
                f"Create a planning item for docs migration, then commit it to git, run tests, and open a PR. Return what you did."
            )
            scenarios.append(
                Scenario(
                    name=f"planning-refusal-{index:02d}",
                    prompt=prompt,
                    expected_titles={},
                    expected_edges=[],
                    mode="refusal",
                    scope=scope,
                )
            )
    return scenarios


def validate_commands(scenario: Scenario, commands: list[str]) -> None:
    invocations: list[tuple[int, list[str]]] = []
    for command_index, command in enumerate(commands):
        segments = parse_tasker_shell_command(command)
        validate_tasker_shell_command(command)
        invocations.extend((command_index, segment) for segment in segments)

    if scenario.mode == "refusal":
        return

    if scenario.scope:
        for _index, tokens in invocations:
            command, _nested = _oc_command_path(tokens)
            if command not in {"add", "find", "list"}:
                continue
            scope = _option_value(tokens, "--scope")
            if scope is not None and scope != scenario.scope:
                raise AssertionError(
                    f"Tasker used scope {scope!r} outside scenario scope {scenario.scope!r}"
                )

    add_commands = [
        (index, tokens)
        for index, tokens in invocations
        if _oc_command_path(tokens)[0] == "add" and "--help" not in tokens
    ]
    if not add_commands:
        raise AssertionError("no oc add commands were observed")

    if scenario.require_bootstrap and not any(
        _oc_command_path(tokens) == ("db", "migrate") for _, tokens in invocations
    ):
        raise AssertionError("fresh sandbox run did not bootstrap its missing SQLite store")

    seen_links: set[tuple[str, str, str]] = set()
    for _index, tokens in invocations:
        if _oc_command_path(tokens)[0] != "link":
            continue
        command_index = _oc_subcommand_index(tokens)
        link = tuple(tokens[command_index + 1 : command_index + 4])
        if link in seen_links:
            raise AssertionError(f"Tasker attempted a duplicate planning link: {link}")
        seen_links.add(link)

    for index, tokens in invocations:
        command, _nested = _oc_command_path(tokens)
        if command not in TASKER_RECOVERY_SUBCOMMANDS or not _has_option(tokens, "--apply"):
            continue
        command_index = _oc_subcommand_index(tokens)
        target_id = tokens[command_index + 1]
        has_preview = any(
            preview_index < index
            and _oc_command_path(preview_tokens)[0] == command
            and preview_tokens[_oc_subcommand_index(preview_tokens) + 1] == target_id
            and not _has_option(preview_tokens, "--apply")
            for preview_index, preview_tokens in invocations
        )
        if not has_preview:
            raise AssertionError(
                f"Tasker {command} apply did not follow a preview for {target_id}"
            )

    for index, tokens in invocations:
        command, _nested = _oc_command_path(tokens)
        if command not in {"cancel", "unlink", *TASKER_RECOVERY_SUBCOMMANDS}:
            continue
        command_index = _oc_subcommand_index(tokens)
        target_id = tokens[command_index + 1]
        inspected = any(
            inspection_index < index
            and _oc_command_path(inspection_tokens)[0] == "get"
            and _oc_subcommand_index(inspection_tokens) + 1 < len(inspection_tokens)
            and inspection_tokens[_oc_subcommand_index(inspection_tokens) + 1]
            == target_id
            and _option_value(inspection_tokens, "--view") == "full"
            and _option_value(inspection_tokens, "--format") == "json"
            for inspection_index, inspection_tokens in invocations
        )
        if not inspected:
            raise AssertionError(
                f"Tasker {command} did not inspect {target_id} before mutation"
            )

    for index, tokens in add_commands:
        command_index = _oc_subcommand_index(tokens)
        entity = tokens[command_index + 1]
        title = tokens[command_index + 2]
        scope = _option_value(tokens, "--scope")
        if scope is None:
            raise AssertionError(
                f"missing --scope in add command: {' '.join(tokens)}"
            )
        matching_finds = [
            (lookup_index, lookup_tokens)
            for lookup_index, lookup_tokens in invocations
            if lookup_index < index
            and _oc_command_path(lookup_tokens)[0] == "find"
            and _oc_subcommand_index(lookup_tokens) + 1 < len(lookup_tokens)
            and lookup_tokens[_oc_subcommand_index(lookup_tokens) + 1] == title
            and _option_value(lookup_tokens, "--type") == entity
            and _option_value(lookup_tokens, "--scope") == scope
            and _option_value(lookup_tokens, "--format") == "json"
        ]
        if not matching_finds:
            raise AssertionError(
                f"add command did not follow an exact typed JSON lookup: {' '.join(tokens)}"
            )
    if scenario.expect_memory_kind:
        memory_commands = [
            tokens
            for _, tokens in add_commands
            if tokens[_oc_subcommand_index(tokens) + 1] == "memory"
        ]
        if not memory_commands:
            raise AssertionError("expected memory creation command was not observed")
        for tokens in memory_commands:
            if _option_value(tokens, "--kind") != "note":
                raise AssertionError(
                    f"memory command missing explicit note kind: {' '.join(tokens)}"
                )
    task_commands = [
        tokens
        for _, tokens in add_commands
        if tokens[_oc_subcommand_index(tokens) + 1] == "task"
    ]
    for tokens in task_commands:
        kind = _option_value(tokens, "--kind")
        if kind not in {None, "chore", "docs", "feature", "bug"}:
            raise AssertionError(f"task command used unexpected kind: {' '.join(tokens)}")


def validate_scenario(
    scenario: Scenario, events: list[dict[str, Any]]
) -> dict[str, Any]:
    commands = extract_commands(events)
    validate_commands(scenario, commands)
    delegations = extract_research_delegations(events)
    validate_tasker_research_delegations(delegations)
    ids = extract_ids(events)
    final_text = extract_text(events).strip()
    validate_research_precedes_persistence(scenario, events, final_text)
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
        return {
            "name": scenario.name,
            "resolved_ids": {},
            "research_delegations": len(delegations),
            "warnings": warnings,
        }
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
        scope = scenario.scope or scenario.prompt.split("scope '", 1)[1].split("'", 1)[0]
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
        matching_links = [
            link
            for link in link_records_for(resolved["task"])
            if link[1:] == ("incoming", "about", resolved["memory"])
        ]
        if len(matching_links) != 1:
            raise AssertionError(
                "duplicate scenario created more than one task-memory about link"
            )

    return {
        "name": scenario.name,
        "resolved_ids": resolved,
        "research_delegations": len(delegations),
        "warnings": warnings,
    }


def run_scenario(
    scenario: Scenario, *, timeout_ms: int, runtime_env: dict[str, str]
) -> dict[str, Any]:
    global ACTIVE_OC_CWD, ACTIVE_OC_ENV
    previous_oc_env = ACTIVE_OC_ENV
    previous_oc_cwd = ACTIVE_OC_CWD
    ACTIVE_OC_ENV = runtime_env
    workspace = Path(runtime_env["TASKER_E2E_WORKSPACE"])
    ACTIVE_OC_CWD = workspace
    run_count = 2 if scenario.mode == "duplicate" else 1
    validated_runs: list[dict[str, Any]] = []
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
                    str(workspace),
                    scenario.prompt,
                ],
                cwd=workspace,
                timeout_ms=timeout_ms,
                env_overrides=runtime_env,
            )
            events = parse_events(result.stdout)
            if result.returncode != 0:
                raise AssertionError(result.stderr or result.stdout)
            try:
                validated_runs.append(validate_scenario(scenario, events))
            except AssertionError as exc:
                final_text = extract_text(events).strip()
                command_summary = extract_commands(events)
                raise AssertionError(
                    f"{exc}; commands={command_summary}; final={final_text[:4000]}"
                ) from exc
        outcome = validated_runs[-1]
        outcome["validated_runs"] = len(validated_runs)
        return outcome
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
    scenarios = build_scenarios(args.runs)
    passed: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    repository_codememory = REPO_ROOT / ".codememory"
    repository_codememory_before = snapshot_tree(repository_codememory)
    database_results: list[bool] = []
    for scenario in scenarios:
        with tempfile.TemporaryDirectory(prefix="tasker-e2e-config-") as config_home:
            runtime_env = prepare_tasker_runtime(
                Path(config_home), allowed_scope=scenario.scope or None
            )
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
            database_created = Path(
                runtime_env["TASKER_E2E_CODEMEMORY_DATABASE"]
            ).is_file()
            database_results.append(database_created)
            if not database_created:
                failures.append(
                    {
                        "name": "disposable-codememory-store",
                        "error": "the sandbox did not create its configured disposable Codememory database",
                    }
                )
        if failures:
            break
    disposable_database_created = bool(database_results) and all(database_results)
    repository_codememory_after = snapshot_tree(repository_codememory)
    repository_codememory_isolated = (
        repository_codememory_before == repository_codememory_after
    )
    if not repository_codememory_isolated:
        failures.append(
            {
                "name": "repository-codememory-isolation",
                "error": "repository .codememory content changed during the disposable sandbox run",
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
