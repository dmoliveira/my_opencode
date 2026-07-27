#!/usr/bin/env python3
"""Run verified Playwright CLI/MCP and configured-tuple model smokes."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import queue
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from playwright_defaults import (
    PLAYWRIGHT_CLI_COMMAND,
    PLAYWRIGHT_CLI_LIFECYCLE_SCRIPTS,
    PLAYWRIGHT_CLI_METADATA_FIELDS,
    PLAYWRIGHT_CLI_MIN_NODE_MAJOR,
    PLAYWRIGHT_CLI_PACKAGE_SPEC,
    PLAYWRIGHT_CLI_VERSION_COMMAND,
    PLAYWRIGHT_CLI_VERSION_OUTPUT,
    PLAYWRIGHT_MCP_CAPABILITIES,
    PLAYWRIGHT_MCP_COMMAND,
    PLAYWRIGHT_MCP_GIT_HEAD,
    PLAYWRIGHT_MCP_INTEGRITY,
    PLAYWRIGHT_MCP_LICENSE,
    PLAYWRIGHT_MCP_PACKAGE_SPEC,
    PLAYWRIGHT_MCP_TOOL_COUNT,
    PLAYWRIGHT_MCP_VERSION,
    inspect_playwright_cli_metadata,
    playwright_cli_npm_environment,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
EXACT_MODEL = "openai/gpt-5.4-mini"
MCP_PROTOCOL_VERSION = "2025-11-25"
PLAYWRIGHT_VERSION = PLAYWRIGHT_MCP_VERSION
PLAYWRIGHT_LICENSE = PLAYWRIGHT_MCP_LICENSE
PLAYWRIGHT_INTEGRITY = PLAYWRIGHT_MCP_INTEGRITY
PLAYWRIGHT_GIT_HEAD = PLAYWRIGHT_MCP_GIT_HEAD
MCP_REQUIRED_TOOL_COUNT = PLAYWRIGHT_MCP_TOOL_COUNT
SELECTED_GATEWAY_HOOK = "noninteractive-shell-guard"
MCP_REQUIRED_TOOLS = {
    "core": "browser_navigate",
    "testing": "browser_generate_locator",
    "network": "browser_route",
    "storage": "browser_storage_state",
    "vision": "browser_mouse_move_xy",
    "devtools": "browser_resume",
    "pdf": "browser_pdf_save",
}
SENSITIVE_ENV_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")
CLI_LOG_BYTES = 128 * 1024
CLI_SNAPSHOT_BYTES = 1024 * 1024
CLI_SCREENSHOT_BYTES = 5 * 1024 * 1024

PROJECT_FIXTURES: dict[str, dict[str, Any]] = {
    "python": {
        "implementation": "stats.py",
        "test_file": "test_stats.py",
        "test_command": ["python3", "-m", "unittest", "-v"],
        "files": {
            "stats.py": '''def summarize(values):
    """Return count, total, average, minimum, and maximum for numeric values."""
    return {}
''',
            "test_stats.py": '''import unittest

from stats import summarize


class SummarizeTests(unittest.TestCase):
    def test_nonempty_values(self):
        self.assertEqual(
            summarize([2, 4, 9]),
            {"count": 3, "total": 15, "average": 5, "minimum": 2, "maximum": 9},
        )

    def test_empty_values(self):
        self.assertEqual(
            summarize([]),
            {"count": 0, "total": 0, "average": None, "minimum": None, "maximum": None},
        )


if __name__ == "__main__":
    unittest.main()
''',
        },
    },
    "node": {
        "implementation": "slugify.mjs",
        "test_file": "slugify.test.mjs",
        "test_command": ["node", "--test", "slugify.test.mjs"],
        "files": {
            "slugify.mjs": '''export function slugify(value) {
  return String(value).toLowerCase()
}
''',
            "slugify.test.mjs": '''import assert from "node:assert/strict"
import test from "node:test"

import { slugify } from "./slugify.mjs"

test("normalizes punctuation and repeated whitespace", () => {
  assert.equal(slugify("  Ship Fast, Stay Safe!  "), "ship-fast-stay-safe")
})

test("collapses separators and trims their edges", () => {
  assert.equal(slugify("Already---Slugged___Value"), "already-slugged-value")
})
''',
        },
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("cli", "mcp", "projects", "all"), nargs="?", default="all"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "runtime" / "harness-wave-5" / "exact-model-e2e",
    )
    parser.add_argument("--model", default=EXACT_MODEL)
    parser.add_argument("--scenario-label", default="wave6")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def selected_components(mode: str) -> tuple[str, ...]:
    if mode == "all":
        return ("mcp", "projects")
    return (mode,)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    process_group = process.pid
    try:
        stdout, stderr = process.communicate(timeout=max(1, timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
    return {
        "command": command,
        "returncode": 124 if timed_out else process.returncode,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "process_pid": process.pid,
        "process_group": process_group,
    }


def sha256_tree(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest(), len(files)


def remaining_timeout(deadline: float, maximum: int) -> int:
    remaining = int(deadline - time.monotonic())
    if remaining < 1:
        raise TimeoutError("exact-model aggregate deadline exceeded")
    return max(1, min(maximum, remaining))


def verify_committed_candidate(
    repo_root: Path, timeout: int
) -> dict[str, Any]:
    source_root = repo_root / "plugin" / "gateway-core" / "src"
    dist_root = repo_root / "plugin" / "gateway-core" / "dist"
    if not source_root.is_dir() or not dist_root.is_dir():
        return {"result": "FAIL", "reason": "gateway_candidate_missing"}
    try:
        with tempfile.TemporaryDirectory(prefix="wave5-gateway-build-") as raw_home:
            build = run_process(
                [
                    "npm",
                    "--prefix",
                    "plugin/gateway-core",
                    "run",
                    "build",
                ],
                cwd=repo_root,
                env=isolated_env(Path(raw_home)),
                timeout=timeout,
            )
        head = run_process(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            env=isolated_env(repo_root),
            timeout=min(30, timeout),
        )
        tracked_status = run_process(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_root,
            env=isolated_env(repo_root),
            timeout=min(30, timeout),
        )
        candidate_status = run_process(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "plugin/gateway-core/src",
                "plugin/gateway-core/dist",
            ],
            cwd=repo_root,
            env=isolated_env(repo_root),
            timeout=min(30, timeout),
        )
    except OSError:
        return {"result": "FAIL", "reason": "candidate_verification_command_failed"}

    head_commit = head["stdout"].strip().lower()
    source_sha256, source_file_count = sha256_tree(source_root)
    dist_sha256, dist_file_count = sha256_tree(dist_root)
    passed = all(
        (
            build["returncode"] == 0,
            head["returncode"] == 0,
            len(head_commit) == 40,
            all(char in "0123456789abcdef" for char in head_commit),
            tracked_status["returncode"] == 0,
            not tracked_status["stdout"].strip(),
            candidate_status["returncode"] == 0,
            not candidate_status["stdout"].strip(),
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "reason": "candidate_committed_and_built" if passed else "candidate_not_clean",
        "head_commit": head_commit if len(head_commit) == 40 else "unavailable",
        "build_returncode": build["returncode"],
        "tracked_clean_after_build": not tracked_status["stdout"].strip(),
        "candidate_paths_clean_after_build": not candidate_status[
            "stdout"
        ].strip(),
        "source": {
            "path": "plugin/gateway-core/src",
            "sha256": source_sha256,
            "file_count": source_file_count,
        },
        "dist": {
            "path": "plugin/gateway-core/dist",
            "sha256": dist_sha256,
            "file_count": dist_file_count,
        },
    }


def host_auth_path() -> Path:
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    )
    return data_home / "opencode" / "auth.json"


def collect_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if len(value) >= 16:
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from collect_string_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from collect_string_values(item)


def credential_values(auth_path: Path) -> list[str]:
    values = {
        value
        for key, value in os.environ.items()
        if len(value) >= 8
        and any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
    }
    if auth_path.exists():
        try:
            values.update(collect_string_values(json.loads(auth_path.read_text())))
        except (OSError, json.JSONDecodeError):
            pass
    return sorted(values, key=len, reverse=True)


def auth_store_summary(auth_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    openai = payload.get("openai", {}) if isinstance(payload, dict) else {}
    auth_type = openai.get("type") if isinstance(openai, dict) else None
    return {
        "store_available": auth_path.is_file(),
        "openai_auth_type": auth_type if auth_type == "oauth" else "unavailable",
        "oauth_store_only": auth_type == "oauth",
    }


def sanitize_text(text: str, secrets: list[str]) -> tuple[str, bool]:
    sanitized = text
    detected = False
    for secret in secrets:
        if secret and secret in sanitized:
            detected = True
            sanitized = sanitized.replace(secret, "[CREDENTIAL_REMOVED]")
    return sanitized, detected


def write_safe_text(
    path: Path,
    text: str,
    secrets: list[str],
    private_values: Iterable[str] = (),
) -> bool:
    sanitized, detected = sanitize_text(text, secrets)
    for value in sorted({item for item in private_values if item}, key=len, reverse=True):
        sanitized = sanitized.replace(value, "[PRIVATE_VALUE_REMOVED]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sanitized, encoding="utf-8")
    return detected


def sanitize_report_value(
    value: Any,
    secrets: list[str],
    private_values: Iterable[str],
) -> tuple[Any, bool]:
    if isinstance(value, str):
        sanitized, credential_detected = sanitize_text(value, secrets)
        private_detected = False
        for private in sorted(
            {item for item in private_values if item}, key=len, reverse=True
        ):
            if private in sanitized:
                private_detected = True
                sanitized = sanitized.replace(private, "[PRIVATE_VALUE_REMOVED]")
        return sanitized, credential_detected or private_detected
    if isinstance(value, list):
        output: list[Any] = []
        detected = False
        for item in value:
            sanitized, item_detected = sanitize_report_value(
                item, secrets, private_values
            )
            output.append(sanitized)
            detected |= item_detected
        return output, detected
    if isinstance(value, dict):
        output_dict: dict[str, Any] = {}
        detected = False
        for key, item in value.items():
            sanitized, item_detected = sanitize_report_value(
                item, secrets, private_values
            )
            output_dict[str(key)] = sanitized
            detected |= item_detected
        return output_dict, detected
    return value, False


def write_safe_report(
    path: Path,
    report: dict[str, Any],
    secrets: list[str],
    private_values: Iterable[str],
) -> tuple[dict[str, Any], bool]:
    sanitized, detected = sanitize_report_value(report, secrets, private_values)
    safe_report = sanitized if isinstance(sanitized, dict) else {"result": "FAIL"}
    path.write_text(json.dumps(safe_report, indent=2) + "\n", encoding="utf-8")
    return safe_report, detected


def isolated_env(home: Path, audit_path: Path | None = None) -> dict[str, str]:
    env = {
        key: value
        for key in ("LANG", "LC_ALL", "LOGNAME", "PATH", "SHELL", "TMPDIR", "USER")
        if (value := os.environ.get(key))
    }
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "CI": "true",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GCM_INTERACTIVE": "never",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
        }
    )
    if audit_path is not None:
        env["MY_OPENCODE_GATEWAY_EVENT_AUDIT"] = "1"
        env["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"] = str(audit_path)
    session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    if session_id:
        env["OPENCODE_SESSION_ID"] = session_id
    return env


def runtime_auth_contract(env: dict[str, str]) -> dict[str, Any]:
    forwarded_api_keys = [key for key in env if "API_KEY" in key.upper()]
    return {
        "forwarded_api_key_count": len(forwarded_api_keys),
        "default_plugins_retained": "OPENCODE_DISABLE_DEFAULT_PLUGINS" not in env,
    }


def copy_auth_store(home: Path, source: Path) -> bool:
    if not source.is_file():
        return False
    destination = home / ".local" / "share" / "opencode" / "auth.json"
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    destination.chmod(0o600)
    return True


def gateway_plugin_spec(dist_entry: Path) -> str:
    return dist_entry.resolve().as_uri()


def ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=False)
    except FileExistsError:
        pass
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise PermissionError("exact-model sandbox directory must be owner-only")


def gateway_tuple_options() -> dict[str, Any]:
    return {
        "hooks": {
            "enabled": True,
            "order": [SELECTED_GATEWAY_HOOK],
            "disabled": [],
        },
        "noninteractiveShellGuard": {"enabled": True},
    }


def write_opencode_config(
    home: Path, model: str, dist_entry: Path
) -> dict[str, Any]:
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "small_model": model,
        "default_agent": "build",
        "provider": {
            "openai": {
                "models": {
                    "gpt-5.4-mini": {"name": "GPT-5.4 mini"},
                }
            }
        },
        "plugin": [[gateway_plugin_spec(dist_entry), gateway_tuple_options()]],
        "mcp": {},
        "lsp": False,
        "formatter": False,
        "permission": "allow",
    }
    path = home / ".config" / "opencode" / "opencode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def configured_tuple_summary(config: dict[str, Any]) -> dict[str, Any]:
    entries = config.get("plugin", [])
    entry = entries[0] if isinstance(entries, list) and len(entries) == 1 else None
    options = (
        entry[1]
        if isinstance(entry, list)
        and len(entry) == 2
        and isinstance(entry[0], str)
        and isinstance(entry[1], dict)
        else {}
    )
    hooks = options.get("hooks", {}) if isinstance(options, dict) else {}
    order = hooks.get("order", []) if isinstance(hooks, dict) else []
    return {
        "configured_plugin_entry_count": len(entries) if isinstance(entries, list) else 0,
        "configured_plugin_entry_kind": "tuple" if options else "invalid",
        "hooks_enabled": hooks.get("enabled") is True if isinstance(hooks, dict) else False,
        "selected_hook_ids": order if isinstance(order, list) else [],
    }


def project_gateway_shim_count(project: Path) -> int:
    plugin_dir = project / ".opencode" / "plugins"
    return len(list(plugin_dir.glob("*"))) if plugin_dir.is_dir() else 0


def read_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def audit_summary(path: Path) -> dict[str, Any]:
    entries = read_audit(path)
    bootstrap = [
        entry
        for entry in entries
        if entry.get("reason_code") == "gateway_runtime_bootstrap"
    ]
    observed = [
        str(entry.get("actual_model"))
        for entry in entries
        if entry.get("reason_code") == "agent_runtime_model_observed"
        and entry.get("actual_model")
    ]
    session_env_prefixed = [
        entry
        for entry in entries
        if entry.get("reason_code") == "runtime_session_env_prefixed"
    ]
    return {
        "entry_count": len(entries),
        "bootstrap_count": len(bootstrap),
        "bootstrap_hooks_enabled": (
            len(bootstrap) == 1 and bootstrap[0].get("hooks_enabled") is True
        ),
        "observed_models": list(dict.fromkeys(observed)),
        "runtime_session_env_prefixed_count": len(session_env_prefixed),
    }


def fixture_hashes(project: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
        ):
            continue
        hashes[str(path.relative_to(project))] = sha256_file(path)
    return hashes


def write_project_fixture(project: Path, name: str) -> dict[str, Any]:
    spec = PROJECT_FIXTURES[name]
    project.mkdir(parents=True, exist_ok=True)
    for relative, content in spec["files"].items():
        (project / relative).write_text(content, encoding="utf-8")
    (project / "AGENTS.md").write_text(
        "# Fixture instructions\n\n"
        f"Edit only `{spec['implementation']}`. Never edit tests, AGENTS.md, or .opencode files. "
        f"Run `{' '.join(spec['test_command'])}` and leave it green.\n",
        encoding="utf-8",
    )
    return spec


def project_prompt(name: str, spec: dict[str, Any]) -> str:
    return (
        f"Fix the {name} fixture. Edit only {spec['implementation']}; do not create, rename, "
        "or edit any other file. Run the native test command "
        f"`{' '.join(spec['test_command'])}` and keep working until it passes. "
        "Do not use git. Report the implementation change and final test result concisely."
    )


def run_model_once(
    *,
    model: str,
    project: Path,
    env: dict[str, str],
    prompt: str,
    title: str,
    timeout: int,
) -> dict[str, Any]:
    command = [
        "opencode",
        "run",
        "--model",
        model,
        "--agent",
        "build",
        "--format",
        "json",
        "--print-logs",
        "--log-level",
        "DEBUG",
        "--title",
        title,
        prompt,
    ]
    return run_process(
        command,
        cwd=project,
        env=env,
        timeout=timeout,
    )


def prepare_model_sandbox(
    base: Path,
    *,
    model: str,
    dist_entry: Path,
    auth_source: Path,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    ensure_private_directory(base)
    home = base / "home"
    project = base / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = write_opencode_config(home, model, dist_entry)
    if not copy_auth_store(home, auth_source):
        raise FileNotFoundError("OpenCode auth store is unavailable")
    audit_path = base / "gateway-events.jsonl"
    return home, project, audit_path, config


def run_model_preflight(
    *,
    base: Path,
    model: str,
    dist_entry: Path,
    auth_source: Path,
    output_dir: Path,
    timeout: int,
    secrets: list[str],
    additional_private_values: Iterable[str] = (),
) -> dict[str, Any]:
    home, project, audit_path, config = prepare_model_sandbox(
        base,
        model=model,
        dist_entry=dist_entry,
        auth_source=auth_source,
    )
    runtime_env = isolated_env(home, audit_path)
    auth_contract = runtime_auth_contract(runtime_env)
    tuple_summary = configured_tuple_summary(config)
    private_values = (
        str(base.absolute()),
        str(base.resolve()),
        str(auth_source.absolute()),
        str(auth_source.resolve()),
        str(dist_entry.absolute()),
        str(dist_entry.resolve()),
        dist_entry.absolute().as_uri(),
        dist_entry.resolve().as_uri(),
        gateway_plugin_spec(dist_entry),
        "noninteractiveShellGuard",
        *additional_private_values,
    )
    marker = "MODEL_PREFLIGHT_OK"
    result = run_model_once(
        model=model,
        project=project,
        env=runtime_env,
        prompt=f"Reply with exactly {marker}. Do not use tools.",
        title="Harness Wave 5 exact-model preflight",
        timeout=timeout,
    )
    credential_detected = write_safe_text(
        output_dir / "preflight.stdout.jsonl",
        result["stdout"],
        secrets,
        private_values,
    )
    credential_detected |= write_safe_text(
        output_dir / "preflight.stderr.log",
        result["stderr"],
        secrets,
        private_values,
    )
    audit = audit_summary(audit_path)
    retained_audit = output_dir / "preflight.gateway-events.jsonl"
    credential_detected |= write_safe_text(
        retained_audit,
        audit_path.read_text(encoding="utf-8", errors="replace")
        if audit_path.exists()
        else "",
        secrets,
        private_values,
    )
    shim_count = project_gateway_shim_count(project)
    marker_seen = marker in result["stdout"]
    passed = all(
        (
            result["returncode"] == 0,
            marker_seen,
            audit["bootstrap_count"] == 1,
            audit["bootstrap_hooks_enabled"],
            audit["observed_models"] == [model],
            tuple_summary["configured_plugin_entry_count"] == 1,
            tuple_summary["configured_plugin_entry_kind"] == "tuple",
            tuple_summary["hooks_enabled"],
            tuple_summary["selected_hook_ids"] == [SELECTED_GATEWAY_HOOK],
            shim_count == 0,
            auth_contract["forwarded_api_key_count"] == 0,
            auth_contract["default_plugins_retained"],
            not credential_detected,
        )
    )
    if passed:
        reason = "exact_model_available"
    elif result["returncode"] == 0 and marker_seen and audit["bootstrap_count"] != 1:
        reason = "gateway_audit_unavailable"
    else:
        reason = "model_auth_or_availability_preflight_failed"
    return {
        "result": "PASS" if passed else "BLOCKED",
        "reason": reason,
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "marker_seen": marker_seen,
        "audit": audit,
        "observed_models": audit["observed_models"],
        "observed_model_source": "gateway_audit",
        **tuple_summary,
        **auth_contract,
        "project_gateway_shim_count": shim_count,
        "credential_material_detected": credential_detected,
    }


def run_project_fixture(
    *,
    name: str,
    base: Path,
    model: str,
    dist_entry: Path,
    auth_source: Path,
    output_dir: Path,
    timeout: int,
    deadline: float,
    secrets: list[str],
    additional_private_values: Iterable[str] = (),
) -> dict[str, Any]:
    home, project, audit_path, config = prepare_model_sandbox(
        base,
        model=model,
        dist_entry=dist_entry,
        auth_source=auth_source,
    )
    runtime_env = isolated_env(home, audit_path)
    auth_contract = runtime_auth_contract(runtime_env)
    tuple_summary = configured_tuple_summary(config)
    private_values = (
        str(base.absolute()),
        str(base.resolve()),
        str(auth_source.absolute()),
        str(auth_source.resolve()),
        str(dist_entry.absolute()),
        str(dist_entry.resolve()),
        dist_entry.absolute().as_uri(),
        dist_entry.resolve().as_uri(),
        gateway_plugin_spec(dist_entry),
        "noninteractiveShellGuard",
        *additional_private_values,
    )
    spec = write_project_fixture(project, name)
    initial_test = run_process(
        list(spec["test_command"]),
        cwd=project,
        env=isolated_env(home),
        timeout=remaining_timeout(deadline, 60),
    )
    before_hashes = fixture_hashes(project)
    model_run = run_model_once(
        model=model,
        project=project,
        env=runtime_env,
        prompt=project_prompt(name, spec),
        title=f"Harness Wave 5 {name} fixture",
        timeout=remaining_timeout(deadline, timeout),
    )
    final_test = run_process(
        list(spec["test_command"]),
        cwd=project,
        env=isolated_env(home),
        timeout=remaining_timeout(deadline, 60),
    )
    after_hashes = fixture_hashes(project)
    changed_files = sorted(
        path
        for path in set(before_hashes) | set(after_hashes)
        if before_hashes.get(path) != after_hashes.get(path)
    )
    artifact_dir = output_dir / name
    credential_detected = False
    for label, run in (
        ("initial-test", initial_test),
        ("model", model_run),
        ("final-test", final_test),
    ):
        credential_detected |= write_safe_text(
            artifact_dir / f"{label}.stdout.log",
            run["stdout"],
            secrets,
            private_values,
        )
        credential_detected |= write_safe_text(
            artifact_dir / f"{label}.stderr.log",
            run["stderr"],
            secrets,
            private_values,
        )
    audit = audit_summary(audit_path)
    audit_text = (
        audit_path.read_text(encoding="utf-8", errors="replace")
        if audit_path.exists()
        else ""
    )
    credential_detected |= write_safe_text(
        artifact_dir / "gateway-events.jsonl",
        audit_text,
        secrets,
        private_values,
    )
    shim_count = project_gateway_shim_count(project)
    test_hash_unchanged = (
        before_hashes.get(spec["test_file"]) == after_hashes.get(spec["test_file"])
    )
    passed = all(
        (
            initial_test["returncode"] != 0,
            model_run["returncode"] == 0,
            final_test["returncode"] == 0,
            changed_files == [spec["implementation"]],
            test_hash_unchanged,
            audit["bootstrap_count"] == 1,
            audit["bootstrap_hooks_enabled"],
            audit["observed_models"] == [model],
            audit["runtime_session_env_prefixed_count"] >= 1,
            tuple_summary["configured_plugin_entry_count"] == 1,
            tuple_summary["configured_plugin_entry_kind"] == "tuple",
            tuple_summary["hooks_enabled"],
            tuple_summary["selected_hook_ids"] == [SELECTED_GATEWAY_HOOK],
            shim_count == 0,
            auth_contract["forwarded_api_key_count"] == 0,
            auth_contract["default_plugins_retained"],
            not credential_detected,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "fixture": name,
        "implementation": spec["implementation"],
        "test_file": spec["test_file"],
        "test_command": spec["test_command"],
        "initial_test_returncode": initial_test["returncode"],
        "model_returncode": model_run["returncode"],
        "model_timed_out": model_run["timed_out"],
        "final_test_returncode": final_test["returncode"],
        "changed_files": changed_files,
        "test_hash_unchanged": test_hash_unchanged,
        "audit": audit,
        "observed_models": audit["observed_models"],
        "observed_model_source": "gateway_audit",
        **tuple_summary,
        **auth_contract,
        "project_gateway_shim_count": shim_count,
        "credential_material_detected": credential_detected,
    }


def _append_bounded_line(lines: deque[str], line: str, retained_bytes: int) -> int:
    encoded = line.encode("utf-8", errors="replace")
    if len(encoded) > CLI_LOG_BYTES:
        encoded = encoded[-CLI_LOG_BYTES:]
        line = encoded.decode("utf-8", errors="replace")
    lines.append(line)
    retained_bytes += len(encoded)
    while retained_bytes > CLI_LOG_BYTES and lines:
        overflow = retained_bytes - CLI_LOG_BYTES
        first = lines[0].encode("utf-8", errors="replace")
        if len(first) <= overflow:
            lines.popleft()
            retained_bytes -= len(first)
            continue
        lines[0] = first[overflow:].decode("utf-8", errors="replace")
        retained_bytes -= overflow
    return retained_bytes


def read_stream(
    stream: Any,
    sink: queue.Queue[str | None] | None,
    lines: deque[str],
    stop: threading.Event,
) -> None:
    retained_bytes = 0
    try:
        for line in iter(stream.readline, ""):
            retained_bytes = _append_bounded_line(lines, line, retained_bytes)
            if sink is None:
                continue
            while not stop.is_set():
                try:
                    sink.put(line, timeout=0.05)
                    break
                except queue.Full:
                    continue
    finally:
        if sink is not None:
            try:
                sink.put_nowait(None)
            except queue.Full:
                pass


def stop_process_group(process: subprocess.Popen[str]) -> None:
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


def wait_for_response(
    messages: queue.Queue[str | None],
    response_id: int,
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            line = messages.get(timeout=remaining)
        except queue.Empty as error:
            raise TimeoutError(f"MCP response {response_id} timed out") from error
        if line is None:
            raise RuntimeError(f"MCP stdout closed before response {response_id}")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError("MCP stdout emitted invalid JSON") from error
        if payload.get("id") == response_id:
            return payload
    raise TimeoutError(f"MCP response {response_id} timed out")


def evaluate_mcp_inventory(
    server_info: dict[str, Any], tool_names: list[str]
) -> dict[str, Any]:
    missing = {
        capability: tool
        for capability, tool in MCP_REQUIRED_TOOLS.items()
        if tool not in tool_names
    }
    return {
        "server_name": server_info.get("name"),
        "tool_count": len(tool_names),
        "required_tool_count": MCP_REQUIRED_TOOL_COUNT,
        "required_tools": MCP_REQUIRED_TOOLS,
        "missing_required_tools": missing,
        "pass": (
            server_info.get("name") == "Playwright"
            and len(tool_names) == MCP_REQUIRED_TOOL_COUNT
            and not missing
        ),
    }


def npm_provenance(
    *, cwd: Path, sandbox: Path, timeout: int, secrets: list[str], output_dir: Path
) -> dict[str, Any]:
    command = [
        "npm",
        "view",
        PLAYWRIGHT_MCP_PACKAGE_SPEC,
        "version",
        "license",
        "dist.integrity",
        "gitHead",
        "scripts",
        "--json",
    ]
    result = run_process(
        command,
        cwd=cwd,
        env=playwright_cli_npm_environment(sandbox),
        timeout=timeout,
    )
    detected = write_safe_text(
        output_dir / "npm-view.stderr.log",
        _bounded_text(result["stderr"]),
        secrets,
        [str(sandbox)],
    )
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    scripts = payload.get("scripts")
    script_map = scripts if isinstance(scripts, dict) else {}
    lifecycle_scripts = sorted(
        name for name in PLAYWRIGHT_CLI_LIFECYCLE_SCRIPTS if script_map.get(name)
    )
    safe_payload = {
        "version": payload.get("version"),
        "license": payload.get("license"),
        "integrity": (
            (payload.get("dist") or {}).get("integrity")
            if isinstance(payload.get("dist"), dict)
            else payload.get("dist.integrity")
        ),
        "gitHead": payload.get("gitHead"),
        "lifecycle_scripts": lifecycle_scripts,
    }
    (output_dir / "npm-provenance.json").write_text(
        json.dumps(safe_payload, indent=2) + "\n", encoding="utf-8"
    )
    passed = all(
        (
            result["returncode"] == 0,
            safe_payload["version"] == PLAYWRIGHT_VERSION,
            safe_payload["license"] == PLAYWRIGHT_LICENSE,
            safe_payload["integrity"] == PLAYWRIGHT_INTEGRITY,
            safe_payload["gitHead"] == PLAYWRIGHT_GIT_HEAD,
            safe_payload["lifecycle_scripts"] == [],
            not detected,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        **safe_payload,
        "credential_material_detected": detected,
    }


class _QuietTodoHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def prepare_playwright_npm_sandbox(sandbox: Path) -> None:
    ensure_private_directory(sandbox)
    for name in (
        "home",
        "tmp",
        "xdg-cache",
        "xdg-config",
        "npm-cache",
        "npm-prefix",
        "s",
    ):
        ensure_private_directory(sandbox / name)
    for name in ("user.npmrc", "global.npmrc"):
        path = sandbox / name
        path.write_text("", encoding="utf-8")
        path.chmod(0o600)


def prepare_playwright_cli_sandbox(sandbox: Path) -> tuple[Path, Path]:
    prepare_playwright_npm_sandbox(sandbox)
    for name in ("workspace", "site"):
        ensure_private_directory(sandbox / name)
    return sandbox / "workspace", sandbox / "site"


def write_todo_fixture(site: Path) -> Path:
    path = site / "index.html"
    path.write_text(
        """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Wave 6 Todo</title></head>
<body>
  <main>
    <h1>Wave 6 Todo</h1>
    <form id="todo-form">
      <label for="new-todo">New todo</label>
      <input id="new-todo" aria-label="New todo">
      <button type="submit">Add</button>
    </form>
    <p role="status" id="status">0 items</p>
    <ul aria-label="Todo items" id="items"></ul>
  </main>
  <script>
    document.querySelector('#todo-form').addEventListener('submit', event => {
      event.preventDefault();
      const input = document.querySelector('#new-todo');
      if (!input.value.trim()) return;
      const item = document.createElement('li');
      item.textContent = input.value.trim();
      document.querySelector('#items').append(item);
      document.querySelector('#status').textContent =
        `${document.querySelectorAll('#items li').length} items`;
      input.value = '';
    });
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return path


def start_todo_server(
    site: Path,
) -> tuple[http.server.ThreadingHTTPServer, threading.Thread, str]:
    handler = functools.partial(_QuietTodoHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(
        target=server.serve_forever,
        name="wave6-todo-server",
        daemon=True,
    )
    thread.start()
    port = int(server.server_address[1])
    return server, thread, f"http://127.0.0.1:{port}/"


def sandbox_inventory(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(size.to_bytes(8, "big"))
        file_count += 1
        total_bytes += size
    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "metadata_sha256": digest.hexdigest(),
        "top_level": sorted(path.name for path in root.iterdir()),
    }


def tracked_worktree_fingerprint(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=repo_root,
        env=isolated_env(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "unavailable"
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _bounded_text(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= CLI_LOG_BYTES:
        return text
    return encoded[-CLI_LOG_BYTES:].decode("utf-8", errors="replace")


def _workspace_artifact(
    workspace: Path, relative: str, maximum_bytes: int
) -> Path:
    candidate = (workspace / relative).resolve()
    root = workspace.resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise RuntimeError("Playwright CLI emitted an unsafe artifact path")
    if candidate.stat().st_size > maximum_bytes:
        raise RuntimeError("Playwright CLI artifact exceeded its size limit")
    return candidate


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _process_identity(pid: int) -> str | None:
    if not _process_alive(pid):
        return None
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid=,lstart=,comm="],
        capture_output=True,
        text=True,
        check=False,
    )
    identity = " ".join(result.stdout.split())
    if result.returncode != 0 or not identity.startswith(f"{pid} "):
        return None
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _identity_alive(pid: int, identity: str) -> bool:
    return _process_identity(pid) == identity


def _process_group_members(group: int) -> set[int]:
    if group <= 0:
        return set()
    result = subprocess.run(
        ["ps", "-axo", "pid=,pgid="],
        capture_output=True,
        text=True,
        check=False,
    )
    members: set[int] = set()
    if result.returncode != 0:
        return members
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, pgid = (int(part) for part in parts)
        except ValueError:
            continue
        if pgid == group:
            members.add(pid)
    return members


def _terminate_owned_processes(
    identities: dict[int, str], groups: set[int]
) -> None:
    own_group = os.getpgrp()
    for group in sorted(groups):
        members = _process_group_members(group)
        group_is_owned = bool(members) and all(
            pid in identities and _identity_alive(pid, identities[pid])
            for pid in members
        )
        if group == own_group or not group_is_owned:
            continue
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(
        _identity_alive(pid, identity) for pid, identity in identities.items()
    ):
        time.sleep(0.05)
    for pid, identity in sorted(identities.items()):
        if not _identity_alive(pid, identity):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _safe_error(error: str, secrets: list[str], private_values: list[str]) -> tuple[str, bool]:
    sanitized, detected = sanitize_text(error, secrets)
    for private in sorted(private_values, key=len, reverse=True):
        if private:
            sanitized = sanitized.replace(private, "[PRIVATE_VALUE_REMOVED]")
    return sanitized, detected


def run_cli_probe(
    *,
    repo_root: Path,
    output_dir: Path,
    scenario_label: str,
    timeout: int,
    secrets: list[str],
) -> dict[str, Any]:
    missing = [name for name in ("node", "npm", "npx") if shutil.which(name) is None]
    if missing:
        return {
            "result": "BLOCKED",
            "reason": "playwright_cli_runtime_missing",
            "missing_binaries": missing,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    artifacts_dir = output_dir / "artifacts"
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^a-zA-Z0-9_-]+", "-", scenario_label).strip("-") or "wave6"
    session = f"{label}-{uuid.uuid4().hex[:10]}"
    commands: list[dict[str, Any]] = []
    artifact_paths: set[str] = set()
    owned_pids: set[int] = set()
    owned_groups: set[int] = set()
    owned_identities: dict[int, str] = {}
    live_owned_groups: set[int] = set()
    credential_detected = False
    provenance: dict[str, Any] = {"verified": False, "mismatches": ["not_run"]}
    assertions = {"item_count": False, "added_text": False}
    error = ""
    scoped_close = False
    version_verified = False
    repo_before = tracked_worktree_fingerprint(repo_root)
    sandbox_cleanup_confirmed = False

    with tempfile.TemporaryDirectory(prefix="wave6-playwright-cli-") as raw_tmp:
        sandbox = Path(raw_tmp)
        workspace, site = prepare_playwright_cli_sandbox(sandbox)
        write_todo_fixture(site)
        env = playwright_cli_npm_environment(sandbox)
        before_inventory = sandbox_inventory(sandbox)
        private_values = [str(sandbox)]
        deadline = time.monotonic() + max(30, timeout)
        open_attempted = False
        server: http.server.ThreadingHTTPServer | None = None
        server_thread: threading.Thread | None = None
        base_url = ""

        def capture_identity(pid: int) -> bool:
            identity = _process_identity(pid)
            if identity is None:
                return False
            owned_pids.add(pid)
            owned_identities[pid] = identity
            return True

        def execute(label_name: str, command: list[str], *, cleanup: bool = False) -> dict[str, Any]:
            nonlocal credential_detected
            try:
                command_timeout = (
                    min(20, max(1, timeout))
                    if cleanup
                    else remaining_timeout(deadline, max(1, timeout))
                )
                result = run_process(
                    command,
                    cwd=workspace,
                    env=env,
                    timeout=command_timeout,
                )
            except (OSError, TimeoutError) as execution_error:
                result = {
                    "command": command,
                    "returncode": 124 if isinstance(execution_error, TimeoutError) else 1,
                    "stdout": "",
                    "stderr": str(execution_error),
                    "timed_out": isinstance(execution_error, TimeoutError),
                    "duration_seconds": 0.0,
                }
            pid = result.get("process_pid")
            group = result.get("process_group")
            if isinstance(pid, int) and pid > 0:
                owned_pids.add(pid)
            if isinstance(group, int) and group > 0:
                owned_groups.add(group)
                members = _process_group_members(group)
                captured_group_member = False
                for member in members:
                    captured_group_member |= capture_identity(member)
                if captured_group_member:
                    live_owned_groups.add(group)
            stdout_path = logs_dir / f"{label_name}.stdout.log"
            stderr_path = logs_dir / f"{label_name}.stderr.log"
            credential_detected |= write_safe_text(
                stdout_path,
                _bounded_text(str(result.get("stdout") or "")),
                secrets,
                private_values,
            )
            credential_detected |= write_safe_text(
                stderr_path,
                _bounded_text(str(result.get("stderr") or "")),
                secrets,
                private_values,
            )
            artifact_paths.update(
                {
                    stdout_path.relative_to(output_dir).as_posix(),
                    stderr_path.relative_to(output_dir).as_posix(),
                }
            )
            safe_command = ["[TODO_URL]" if item == base_url else item for item in command]
            commands.append(
                {
                    "label": label_name,
                    "command": safe_command,
                    "returncode": result.get("returncode"),
                    "timed_out": bool(result.get("timed_out")),
                    "duration_seconds": result.get("duration_seconds"),
                    "stdout_artifact": stdout_path.relative_to(output_dir).as_posix(),
                    "stderr_artifact": stderr_path.relative_to(output_dir).as_posix(),
                }
            )
            return result

        try:
            node_result = execute("node-version", ["node", "--version"])
            node_output = str(node_result.get("stdout") or "").strip()
            try:
                node_major = int(node_output.removeprefix("v").split(".", 1)[0])
            except (ValueError, IndexError):
                node_major = 0
            if (
                node_result.get("returncode") != 0
                or node_major < PLAYWRIGHT_CLI_MIN_NODE_MAJOR
            ):
                raise RuntimeError("Playwright CLI requires Node 18+")

            metadata_result = execute(
                "npm-view",
                [
                    "npm",
                    "view",
                    PLAYWRIGHT_CLI_PACKAGE_SPEC,
                    *PLAYWRIGHT_CLI_METADATA_FIELDS,
                    "--json",
                ],
            )
            provenance = inspect_playwright_cli_metadata(
                _parse_json_object(str(metadata_result.get("stdout") or ""))
            )
            if metadata_result.get("returncode") != 0 or not provenance["verified"]:
                raise RuntimeError("Playwright CLI provenance verification failed")

            version_result = execute("version", list(PLAYWRIGHT_CLI_VERSION_COMMAND))
            version_verified = all(
                (
                    version_result.get("returncode") == 0,
                    str(version_result.get("stdout") or "").strip()
                    == PLAYWRIGHT_CLI_VERSION_OUTPUT,
                )
            )
            if not version_verified:
                raise RuntimeError("Playwright CLI exact version check failed")

            server, server_thread, base_url = start_todo_server(site)
            private_values.append(base_url)
            open_attempted = True
            open_result = execute(
                "open",
                [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "open", base_url, "--json"],
            )
            if open_result.get("returncode") != 0:
                raise RuntimeError("Playwright CLI open failed")
            open_payload = _parse_json_object(str(open_result.get("stdout") or ""))
            daemon_pid = open_payload.get("pid")
            if isinstance(daemon_pid, int) and daemon_pid > 0:
                capture_identity(daemon_pid)
                try:
                    daemon_group = os.getpgid(daemon_pid)
                except ProcessLookupError:
                    daemon_group = 0
                if daemon_group > 0:
                    owned_groups.add(daemon_group)
                    live_owned_groups.add(daemon_group)
                    for member in _process_group_members(daemon_group):
                        capture_identity(member)
            snapshot_info = (open_payload.get("result") or {}).get("snapshot", {})
            snapshot_relative = (
                snapshot_info.get("file") if isinstance(snapshot_info, dict) else ""
            )
            if not isinstance(snapshot_relative, str) or not snapshot_relative:
                raise RuntimeError("Playwright CLI open snapshot missing")
            open_snapshot = _workspace_artifact(
                workspace, snapshot_relative, CLI_SNAPSHOT_BYTES
            )
            snapshot_text = open_snapshot.read_text(encoding="utf-8")
            textbox_match = re.search(
                r'textbox "New todo"[^\n]*\[ref=(e\d+)\]', snapshot_text
            )
            button_match = re.search(r'button "Add"[^\n]*\[ref=(e\d+)\]', snapshot_text)
            if textbox_match is None or button_match is None:
                raise RuntimeError("Playwright CLI Todo element references missing")
            retained_snapshot = artifacts_dir / "open-snapshot.yml"
            shutil.copyfile(open_snapshot, retained_snapshot)
            artifact_paths.add(retained_snapshot.relative_to(output_dir).as_posix())

            flow = (
                (
                    "fill",
                    [
                        *PLAYWRIGHT_CLI_COMMAND,
                        f"-s={session}",
                        "fill",
                        textbox_match.group(1),
                        "Ship Wave 6",
                        "--json",
                    ],
                ),
                (
                    "click",
                    [
                        *PLAYWRIGHT_CLI_COMMAND,
                        f"-s={session}",
                        "click",
                        button_match.group(1),
                        "--json",
                    ],
                ),
                (
                    "snapshot",
                    [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "snapshot", "--json"],
                ),
                (
                    "screenshot",
                    [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "screenshot", "--json"],
                ),
            )
            flow_results: dict[str, dict[str, Any]] = {}
            for flow_label, flow_command in flow:
                flow_result = execute(flow_label, flow_command)
                flow_results[flow_label] = flow_result
                if flow_result.get("returncode") != 0:
                    raise RuntimeError(f"Playwright CLI {flow_label} failed")
            snapshot_payload = _parse_json_object(
                str(flow_results["snapshot"].get("stdout") or "")
            )
            final_snapshot = str(snapshot_payload.get("snapshot") or "")
            assertions = {
                "item_count": "1 items" in final_snapshot,
                "added_text": "Ship Wave 6" in final_snapshot,
            }
            retained_final = artifacts_dir / "todo-snapshot.txt"
            retained_final.write_text(final_snapshot, encoding="utf-8")
            artifact_paths.add(retained_final.relative_to(output_dir).as_posix())

            screenshot_payload = _parse_json_object(
                str(flow_results["screenshot"].get("stdout") or "")
            )
            screenshot_match = re.search(
                r"\(([^)]+\.png)\)", str(screenshot_payload.get("result") or "")
            )
            if screenshot_match is None:
                raise RuntimeError("Playwright CLI screenshot artifact missing")
            screenshot = _workspace_artifact(
                workspace, screenshot_match.group(1), CLI_SCREENSHOT_BYTES
            )
            retained_screenshot = artifacts_dir / "todo.png"
            shutil.copyfile(screenshot, retained_screenshot)
            artifact_paths.add(retained_screenshot.relative_to(output_dir).as_posix())
            if not all(assertions.values()):
                raise RuntimeError("Playwright CLI Todo assertions failed")
        except (OSError, RuntimeError, TimeoutError) as execution_error:
            error, detected = _safe_error(str(execution_error), secrets, private_values)
            credential_detected |= detected
        finally:
            if open_attempted:
                close_result = execute(
                    "close",
                    [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "close", "--json"],
                    cleanup=True,
                )
                close_payload = _parse_json_object(
                    str(close_result.get("stdout") or "")
                )
                scoped_close = all(
                    (
                        close_result.get("returncode") == 0,
                        close_payload.get("session") == session,
                        close_payload.get("status") == "closed",
                    )
                )
            if server is not None:
                server.shutdown()
                server.server_close()
            if server_thread is not None:
                server_thread.join(timeout=3)
            for group in live_owned_groups:
                for member in _process_group_members(group):
                    capture_identity(member)
            wait_deadline = time.monotonic() + 5
            while time.monotonic() < wait_deadline and any(
                _identity_alive(pid, identity)
                for pid, identity in owned_identities.items()
            ):
                time.sleep(0.05)
            surviving = {
                pid
                for pid, identity in owned_identities.items()
                if _identity_alive(pid, identity)
            }
            if surviving:
                _terminate_owned_processes(owned_identities, live_owned_groups)
                surviving = {
                    pid
                    for pid, identity in owned_identities.items()
                    if _identity_alive(pid, identity)
                }
            unverified_group_members = {
                pid
                for group in live_owned_groups
                for pid in _process_group_members(group)
                if pid not in owned_identities
                or not _identity_alive(pid, owned_identities[pid])
            }
            after_inventory = sandbox_inventory(sandbox)
            repo_after = tracked_worktree_fingerprint(repo_root)
            sandbox_only_writes = repo_before != "unavailable" and repo_before == repo_after

        passed = all(
            (
                provenance.get("verified") is True,
                version_verified,
                not error,
                all(assertions.values()),
                scoped_close,
                not surviving,
                not unverified_group_members,
                sandbox_only_writes,
                not credential_detected,
            )
        )
        report = {
            "result": "PASS" if passed else "FAIL",
            "reason": "playwright_cli_todo_green" if passed else "playwright_cli_failed",
            "session": session,
            "package_spec": PLAYWRIGHT_CLI_PACKAGE_SPEC,
            "provenance": provenance,
            "version_verified": version_verified,
            "commands": commands,
            "assertions": assertions,
            "scoped_close": scoped_close,
            "close_all_used": False,
            "kill_all_used": False,
            "owned_child_pids": sorted(owned_pids),
            "owned_process_groups": sorted(owned_groups),
            "surviving_owned_pids": sorted(surviving),
            "unverified_owned_group_pids": sorted(unverified_group_members),
            "sandbox_inventory_before": before_inventory,
            "sandbox_inventory_after": after_inventory,
            "sandbox_only_writes": sandbox_only_writes,
            "artifact_paths": sorted(artifact_paths),
            "credential_material_detected": credential_detected,
            "error": error,
        }
    sandbox_cleanup_confirmed = not sandbox.exists()
    report["sandbox_cleanup_confirmed"] = sandbox_cleanup_confirmed
    if not sandbox_cleanup_confirmed:
        report["result"] = "FAIL"
        report["reason"] = "playwright_cli_sandbox_cleanup_failed"
    return report


def run_mcp_probe(
    *, output_dir: Path, timeout: int, secrets: list[str]
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wave2-playwright-mcp-") as raw_tmp:
        sandbox = Path(raw_tmp)
        prepare_playwright_npm_sandbox(sandbox)
        npm_env = playwright_cli_npm_environment(sandbox)
        provenance = npm_provenance(
            cwd=sandbox,
            sandbox=sandbox,
            timeout=timeout,
            secrets=secrets,
            output_dir=output_dir,
        )
        command = list(PLAYWRIGHT_MCP_COMMAND)
        if provenance["result"] != "PASS":
            return {
                "result": "FAIL",
                "command": command,
                "capabilities": list(PLAYWRIGHT_MCP_CAPABILITIES),
                "protocol_version": None,
                "inventory": evaluate_mcp_inventory({}, []),
                "provenance": provenance,
                "error": "Playwright MCP provenance verification failed",
                "credential_material_detected": provenance.get(
                    "credential_material_detected", False
                ),
            }
        process = subprocess.Popen(
            command,
            cwd=sandbox,
            env=npm_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        stdout_lines: deque[str] = deque()
        stderr_lines: deque[str] = deque()
        messages: queue.Queue[str | None] = queue.Queue(maxsize=128)
        stream_stop = threading.Event()
        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, messages, stdout_lines, stream_stop),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, None, stderr_lines, stream_stop),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        error = ""
        initialize: dict[str, Any] = {}
        tools_response: dict[str, Any] = {}
        deadline = time.monotonic() + max(10, timeout)
        try:
            assert process.stdin is not None
            initialize_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "wave2-stdio-probe",
                        "version": "1.0.0",
                    },
                },
            }
            process.stdin.write(
                json.dumps(initialize_request, separators=(",", ":")) + "\n"
            )
            process.stdin.flush()
            initialize = wait_for_response(messages, 1, deadline)
            process.stdin.write(
                json.dumps(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.flush()
            tools_response = wait_for_response(messages, 2, deadline)
        except (AssertionError, BrokenPipeError, RuntimeError, TimeoutError) as exc:
            error = str(exc)
        finally:
            stop_process_group(process)
            stream_stop.set()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)

    initialize_result = initialize.get("result", {})
    tools_result = tools_response.get("result", {})
    tools = tools_result.get("tools", []) if isinstance(tools_result, dict) else []
    tool_names = sorted(
        str(tool.get("name"))
        for tool in tools
        if isinstance(tool, dict) and tool.get("name")
    )
    server_info = (
        initialize_result.get("serverInfo", {})
        if isinstance(initialize_result, dict)
        else {}
    )
    inventory = evaluate_mcp_inventory(server_info, tool_names)
    protocol_version = (
        initialize_result.get("protocolVersion")
        if isinstance(initialize_result, dict)
        else None
    )
    credential_detected = write_safe_text(
        output_dir / "mcp.stdout.jsonl",
        _bounded_text("".join(stdout_lines)),
        secrets,
        [str(sandbox)],
    )
    credential_detected |= write_safe_text(
        output_dir / "mcp.stderr.log",
        _bounded_text("".join(stderr_lines)),
        secrets,
        [str(sandbox)],
    )
    inventory_artifact = {
        "command": command,
        "protocol_version": protocol_version,
        "server_info": server_info,
        "tool_count": len(tool_names),
        "required_tool_count": MCP_REQUIRED_TOOL_COUNT,
        "tool_names": tool_names,
        "required_tools": MCP_REQUIRED_TOOLS,
    }
    (output_dir / "mcp-inventory.json").write_text(
        json.dumps(inventory_artifact, indent=2) + "\n", encoding="utf-8"
    )
    passed = all(
        (
            provenance["result"] == "PASS",
            not error,
            protocol_version == MCP_PROTOCOL_VERSION,
            inventory["pass"],
            not credential_detected,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "command": command,
        "capabilities": list(PLAYWRIGHT_MCP_CAPABILITIES),
        "protocol_version": protocol_version,
        "inventory": inventory,
        "provenance": provenance,
        "error": error,
        "credential_material_detected": credential_detected,
    }


def run_projects(
    *,
    repo_root: Path,
    output_dir: Path,
    model: str,
    timeout: int,
    secrets: list[str],
    forbidden_values: list[str] | None = None,
) -> dict[str, Any]:
    dist_entry = repo_root / "plugin" / "gateway-core" / "dist" / "index.js"
    auth_source = host_auth_path()
    if model != EXACT_MODEL:
        return {
            "result": "BLOCKED",
            "reason": "exact_model_required",
            "requested_model": model,
            "required_model": EXACT_MODEL,
        }
    if shutil.which("opencode") is None:
        return {"result": "BLOCKED", "reason": "opencode_missing"}
    if not auth_source.is_file():
        return {"result": "BLOCKED", "reason": "opencode_auth_store_missing"}
    auth = auth_store_summary(auth_source)
    if not auth["oauth_store_only"]:
        return {"result": "BLOCKED", "reason": "openai_oauth_store_required"}
    candidate = verify_committed_candidate(repo_root, timeout)
    if candidate["result"] != "PASS":
        return {
            "result": "FAIL",
            "reason": candidate["reason"],
            "candidate": candidate,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(1, timeout)
    preflight: dict[str, Any] = {
        "result": "BLOCKED",
        "reason": "preflight_not_run",
    }
    fixtures: dict[str, dict[str, Any]] = {}
    sandbox_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="wave5-exact-model-") as raw_tmp:
            raw_sandbox_path = Path(raw_tmp).absolute()
            sandbox_path = raw_sandbox_path.resolve()
            sandbox_private_values = [
                str(raw_sandbox_path),
                str(sandbox_path),
                str(auth_source.absolute()),
                str(auth_source.resolve()),
                str(dist_entry.absolute()),
                str(dist_entry.resolve()),
                dist_entry.absolute().as_uri(),
                dist_entry.resolve().as_uri(),
                gateway_plugin_spec(dist_entry),
                "noninteractiveShellGuard",
            ]
            if forbidden_values is not None:
                forbidden_values.extend(sandbox_private_values)
            preflight = run_model_preflight(
                base=sandbox_path / "preflight",
                model=model,
                dist_entry=dist_entry,
                auth_source=auth_source,
                output_dir=output_dir,
                timeout=remaining_timeout(deadline, timeout),
                secrets=secrets,
                additional_private_values=sandbox_private_values,
            )
            if preflight["result"] == "PASS":
                for name in PROJECT_FIXTURES:
                    try:
                        fixtures[name] = run_project_fixture(
                            name=name,
                            base=sandbox_path / name,
                            model=model,
                            dist_entry=dist_entry,
                            auth_source=auth_source,
                            output_dir=output_dir,
                            timeout=timeout,
                            deadline=deadline,
                            secrets=secrets,
                            additional_private_values=sandbox_private_values,
                        )
                    except TimeoutError:
                        fixtures[name] = {
                            "result": "FAIL",
                            "fixture": name,
                            "reason": "project_aggregate_timeout",
                            "model_timed_out": True,
                        }
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        preflight = {
            "result": "BLOCKED",
            "reason": "exact_model_sandbox_failed",
            "error_type": type(error).__name__,
        }
    sandbox_cleanup_confirmed = bool(
        sandbox_path is not None and not sandbox_path.exists()
    )
    fixtures_pass = len(fixtures) == len(PROJECT_FIXTURES) and all(
        report["result"] == "PASS" for report in fixtures.values()
    )
    passed = all(
        (
            preflight.get("result") == "PASS",
            fixtures_pass,
            sandbox_cleanup_confirmed,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "reason": (
            "exact_model_projects_green"
            if passed
            else preflight.get("reason", "project_validation_failed")
            if preflight.get("result") != "PASS"
            else "project_validation_failed"
        ),
        "model": model,
        "auth": {
            **auth,
            "source": "isolated_opencode_oauth_store",
        },
        "preflight": preflight,
        "candidate": candidate,
        "fixtures": fixtures,
        "aggregate_timeout_seconds": timeout,
        "sandbox_cleanup_confirmed": sandbox_cleanup_confirmed,
    }


def retained_artifacts_safe(
    output_dir: Path,
    secrets: list[str],
    forbidden_values: Iterable[str] = (),
) -> bool:
    forbidden = [value for value in forbidden_values if value]
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(secret and secret in text for secret in secrets) or any(
            value in text for value in forbidden
        ):
            return False
    return True


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    secrets = credential_values(host_auth_path())
    forbidden_values: list[str] = []
    report: dict[str, Any] = {
        "mode": args.mode,
        "model": args.model,
        "scenario_label": args.scenario_label,
    }
    components = selected_components(args.mode)
    if "cli" in components:
        report["cli"] = run_cli_probe(
            repo_root=repo_root,
            output_dir=output_dir / "cli",
            scenario_label=args.scenario_label,
            timeout=args.timeout_seconds,
            secrets=secrets,
        )
    if "mcp" in components:
        report["mcp"] = run_mcp_probe(
            output_dir=output_dir / "mcp",
            timeout=args.timeout_seconds,
            secrets=secrets,
        )
    if "projects" in components:
        report["projects"] = run_projects(
            repo_root=repo_root,
            output_dir=output_dir / "projects",
            model=args.model,
            timeout=args.timeout_seconds,
            secrets=secrets,
            forbidden_values=forbidden_values,
        )
    component_results = [
        component.get("result")
        for key, component in report.items()
        if key in ("cli", "mcp", "projects") and isinstance(component, dict)
    ]
    report["retained_artifacts_safe"] = False
    report["result"] = (
        "PASS"
        if component_results
        and all(result == "PASS" for result in component_results)
        else "BLOCKED"
        if "BLOCKED" in component_results
        else "FAIL"
    )
    report_path = output_dir / "report.json"
    report, report_sensitive = write_safe_report(
        report_path, report, secrets, forbidden_values
    )
    artifact_safe = retained_artifacts_safe(
        output_dir, secrets, forbidden_values
    ) and not report_sensitive
    report["retained_artifacts_safe"] = artifact_safe
    if not artifact_safe:
        report["result"] = "FAIL"
    report, final_report_sensitive = write_safe_report(
        report_path, report, secrets, forbidden_values
    )
    if final_report_sensitive:
        report["retained_artifacts_safe"] = False
        report["result"] = "FAIL"
        report, _ = write_safe_report(
            report_path, report, secrets, forbidden_values
        )
    if not retained_artifacts_safe(output_dir, secrets, forbidden_values):
        report["retained_artifacts_safe"] = False
        report["result"] = "FAIL"
        report, _ = write_safe_report(
            report_path, report, secrets, forbidden_values
        )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"harness Wave 6 configured-tuple proof: {report['result']}")
        print(f"artifacts: {output_dir}")
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
