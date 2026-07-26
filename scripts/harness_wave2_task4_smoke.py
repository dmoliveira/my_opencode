#!/usr/bin/env python3
"""Run pinned Playwright MCP and configured-tuple Wave 5 model smokes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from playwright_defaults import (
    PLAYWRIGHT_MCP_CAPABILITIES,
    PLAYWRIGHT_MCP_COMMAND,
    PLAYWRIGHT_MCP_PACKAGE_SPEC,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
EXACT_MODEL = "openai/gpt-5.4-mini"
MCP_PROTOCOL_VERSION = "2025-11-25"
PLAYWRIGHT_VERSION = "0.0.78"
PLAYWRIGHT_LICENSE = "Apache-2.0"
PLAYWRIGHT_INTEGRITY = (
    "sha512-XLTUeA6mEN9sQ+hJ4dfG8EIkDbxS0K3Trc2RBkUJuf02TgE2FQRNTMtq/"
    "aJfhyRMINsRl/Ybc4sxcWLtFn4/TQ=="
)
PLAYWRIGHT_GIT_HEAD = "5f8fc00210b27b4407c375b59cda4838045d429c"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("mcp", "projects", "all"), nargs="?", default="all"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "runtime" / "harness-wave-5" / "exact-model-e2e",
    )
    parser.add_argument("--model", default=EXACT_MODEL)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


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
    try:
        stdout, stderr = process.communicate(timeout=max(1, timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
    return {
        "command": command,
        "returncode": 124 if timed_out else process.returncode,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
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


def read_stream(stream: Any, sink: queue.Queue[str | None], lines: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.append(line)
            sink.put(line)
    finally:
        sink.put(None)


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
        "required_tools": MCP_REQUIRED_TOOLS,
        "missing_required_tools": missing,
        "pass": server_info.get("name") == "Playwright" and not missing,
    }


def npm_provenance(
    *, cwd: Path, home: Path, timeout: int, secrets: list[str], output_dir: Path
) -> dict[str, Any]:
    command = [
        "npm",
        "view",
        PLAYWRIGHT_MCP_PACKAGE_SPEC,
        "version",
        "license",
        "dist.integrity",
        "gitHead",
        "--json",
    ]
    result = run_process(command, cwd=cwd, env=isolated_env(home), timeout=timeout)
    detected = write_safe_text(
        output_dir / "npm-view.stderr.log", result["stderr"], secrets
    )
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    safe_payload = {
        "version": payload.get("version"),
        "license": payload.get("license"),
        "integrity": (
            (payload.get("dist") or {}).get("integrity")
            if isinstance(payload.get("dist"), dict)
            else payload.get("dist.integrity")
        ),
        "gitHead": payload.get("gitHead"),
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
            not detected,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        **safe_payload,
        "credential_material_detected": detected,
    }


def run_mcp_probe(
    *, output_dir: Path, timeout: int, secrets: list[str]
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wave2-playwright-mcp-") as raw_tmp:
        sandbox = Path(raw_tmp)
        home = sandbox / "home"
        home.mkdir(parents=True)
        provenance = npm_provenance(
            cwd=sandbox,
            home=home,
            timeout=timeout,
            secrets=secrets,
            output_dir=output_dir,
        )
        command = list(PLAYWRIGHT_MCP_COMMAND)
        process = subprocess.Popen(
            command,
            cwd=sandbox,
            env=isolated_env(home),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        messages: queue.Queue[str | None] = queue.Queue()
        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, messages, stdout_lines),
            daemon=True,
        )
        stderr_queue: queue.Queue[str | None] = queue.Queue()
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr_queue, stderr_lines),
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
        output_dir / "mcp.stdout.jsonl", "".join(stdout_lines), secrets
    )
    credential_detected |= write_safe_text(
        output_dir / "mcp.stderr.log", "".join(stderr_lines), secrets
    )
    inventory_artifact = {
        "command": command,
        "protocol_version": protocol_version,
        "server_info": server_info,
        "tool_count": len(tool_names),
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
    }
    if args.mode in ("mcp", "all"):
        report["mcp"] = run_mcp_probe(
            output_dir=output_dir / "mcp",
            timeout=args.timeout_seconds,
            secrets=secrets,
        )
    if args.mode in ("projects", "all"):
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
        if key in ("mcp", "projects") and isinstance(component, dict)
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
        print(f"harness Wave 5 configured-tuple proof: {report['result']}")
        print(f"artifacts: {output_dir}")
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
