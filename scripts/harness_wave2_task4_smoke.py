#!/usr/bin/env python3
"""Run pinned Playwright MCP and exact-model wave-2 integration smokes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import signal
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
        default=REPO_ROOT / "runtime" / "harness-wave-2" / "task4-live",
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
        stdout, stderr = process.communicate(timeout=max(5, timeout))
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


def sanitize_text(text: str, secrets: list[str]) -> tuple[str, bool]:
    sanitized = text
    detected = False
    for secret in secrets:
        if secret and secret in sanitized:
            detected = True
            sanitized = sanitized.replace(secret, "[CREDENTIAL_REMOVED]")
    return sanitized, detected


def write_safe_text(path: Path, text: str, secrets: list[str]) -> bool:
    sanitized, detected = sanitize_text(text, secrets)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sanitized, encoding="utf-8")
    return detected


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


def link_auth(home: Path, source: Path) -> bool:
    if not source.is_file():
        return False
    destination = home / ".local" / "share" / "opencode" / "auth.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source)
    return True


def write_opencode_config(home: Path, model: str) -> dict[str, Any]:
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
        "plugin": [],
        "mcp": {},
        "lsp": False,
        "formatter": False,
        "permission": "allow",
    }
    path = home / ".config" / "opencode" / "opencode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def write_gateway_shim(project: Path, dist_entry: Path) -> Path:
    plugin_dir = project / ".opencode" / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    shim = plugin_dir / "gateway-core.js"
    shim.write_text(
        "export { default as GatewayCorePlugin } from "
        + json.dumps(dist_entry.as_uri())
        + ";\n",
        encoding="utf-8",
    )
    return shim


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
    return {
        "entry_count": len(entries),
        "bootstrap_count": len(bootstrap),
        "observed_models": list(dict.fromkeys(observed)),
        "audit_path": str(path),
    }


def fixture_hashes(project: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if (
            not path.is_file()
            or ".opencode" in path.parts
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
    home: Path,
    audit_path: Path,
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
        env=isolated_env(home, audit_path),
        timeout=timeout,
    )


def prepare_model_sandbox(
    base: Path,
    *,
    model: str,
    dist_entry: Path,
    auth_source: Path,
) -> tuple[Path, Path, Path, dict[str, Any], Path]:
    home = base / "home"
    project = base / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = write_opencode_config(home, model)
    if not link_auth(home, auth_source):
        raise FileNotFoundError("OpenCode auth store is unavailable")
    shim = write_gateway_shim(project, dist_entry)
    audit_path = base / "gateway-events.jsonl"
    return home, project, audit_path, config, shim


def run_model_preflight(
    *,
    base: Path,
    model: str,
    dist_entry: Path,
    auth_source: Path,
    output_dir: Path,
    timeout: int,
    secrets: list[str],
) -> dict[str, Any]:
    home, project, audit_path, config, shim = prepare_model_sandbox(
        base,
        model=model,
        dist_entry=dist_entry,
        auth_source=auth_source,
    )
    marker = "MODEL_PREFLIGHT_OK"
    result = run_model_once(
        model=model,
        project=project,
        home=home,
        audit_path=audit_path,
        prompt=f"Reply with exactly {marker}. Do not use tools.",
        title="Harness wave 2 exact-model preflight",
        timeout=timeout,
    )
    credential_detected = write_safe_text(
        output_dir / "preflight.stdout.jsonl", result["stdout"], secrets
    )
    credential_detected |= write_safe_text(
        output_dir / "preflight.stderr.log", result["stderr"], secrets
    )
    audit = audit_summary(audit_path)
    retained_audit = output_dir / "preflight.gateway-events.jsonl"
    credential_detected |= write_safe_text(
        retained_audit,
        audit_path.read_text(encoding="utf-8", errors="replace")
        if audit_path.exists()
        else "",
        secrets,
    )
    audit["audit_path"] = str(retained_audit)
    passed = all(
        (
            result["returncode"] == 0,
            marker in result["stdout"],
            audit["bootstrap_count"] == 1,
            audit["observed_models"] == [model],
            config["plugin"] == [],
            len(list((project / ".opencode" / "plugins").glob("*"))) == 1,
            shim.is_file(),
            not credential_detected,
        )
    )
    return {
        "result": "PASS" if passed else "BLOCKED",
        "reason": (
            "exact_model_available"
            if passed
            else "model_auth_or_availability_preflight_failed"
        ),
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "marker_seen": marker in result["stdout"],
        "audit": audit,
        "observed_models": audit["observed_models"],
        "observed_model_source": "gateway_audit",
        "configured_plugin_entries": config["plugin"],
        "project_gateway_shim_count": 1 if shim.is_file() else 0,
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
    secrets: list[str],
) -> dict[str, Any]:
    home, project, audit_path, config, shim = prepare_model_sandbox(
        base,
        model=model,
        dist_entry=dist_entry,
        auth_source=auth_source,
    )
    spec = write_project_fixture(project, name)
    initial_test = run_process(
        list(spec["test_command"]),
        cwd=project,
        env=isolated_env(home),
        timeout=60,
    )
    before_hashes = fixture_hashes(project)
    model_run = run_model_once(
        model=model,
        project=project,
        home=home,
        audit_path=audit_path,
        prompt=project_prompt(name, spec),
        title=f"Harness wave 2 {name} fixture",
        timeout=timeout,
    )
    final_test = run_process(
        list(spec["test_command"]),
        cwd=project,
        env=isolated_env(home),
        timeout=60,
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
            artifact_dir / f"{label}.stdout.log", run["stdout"], secrets
        )
        credential_detected |= write_safe_text(
            artifact_dir / f"{label}.stderr.log", run["stderr"], secrets
        )
    audit = audit_summary(audit_path)
    audit_text = (
        audit_path.read_text(encoding="utf-8", errors="replace")
        if audit_path.exists()
        else ""
    )
    credential_detected |= write_safe_text(
        artifact_dir / "gateway-events.jsonl", audit_text, secrets
    )
    audit["audit_path"] = str(artifact_dir / "gateway-events.jsonl")
    shim_files = list((project / ".opencode" / "plugins").glob("*"))
    passed = all(
        (
            initial_test["returncode"] != 0,
            model_run["returncode"] == 0,
            final_test["returncode"] == 0,
            changed_files == [spec["implementation"]],
            audit["bootstrap_count"] == 1,
            audit["observed_models"] == [model],
            config["plugin"] == [],
            len(shim_files) == 1,
            shim_files[0] == shim,
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
        "test_hash_unchanged": (
            before_hashes.get(spec["test_file"])
            == after_hashes.get(spec["test_file"])
        ),
        "audit": audit,
        "observed_models": audit["observed_models"],
        "observed_model_source": "gateway_audit",
        "configured_plugin_entries": config["plugin"],
        "project_gateway_shim_count": len(shim_files),
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
) -> dict[str, Any]:
    dist_entry = repo_root / "plugin" / "gateway-core" / "dist" / "index.js"
    source_entry = repo_root / "plugin" / "gateway-core" / "src" / "index.ts"
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
    if not dist_entry.is_file() or not source_entry.is_file():
        return {"result": "FAIL", "reason": "gateway_candidate_missing"}

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wave2-exact-model-") as raw_tmp:
        sandbox = Path(raw_tmp)
        preflight = run_model_preflight(
            base=sandbox / "preflight",
            model=model,
            dist_entry=dist_entry,
            auth_source=auth_source,
            output_dir=output_dir,
            timeout=timeout,
            secrets=secrets,
        )
        if preflight["result"] != "PASS":
            return {
                "result": "BLOCKED",
                "reason": preflight["reason"],
                "model": model,
                "preflight": preflight,
            }
        fixtures = {
            name: run_project_fixture(
                name=name,
                base=sandbox / name,
                model=model,
                dist_entry=dist_entry,
                auth_source=auth_source,
                output_dir=output_dir,
                timeout=timeout,
                secrets=secrets,
            )
            for name in PROJECT_FIXTURES
        }
    candidate = {
        "source_path": str(source_entry),
        "source_sha256": sha256_file(source_entry),
        "dist_path": str(dist_entry),
        "dist_sha256": sha256_file(dist_entry),
    }
    passed = all(report["result"] == "PASS" for report in fixtures.values())
    return {
        "result": "PASS" if passed else "FAIL",
        "reason": (
            "exact_model_projects_green" if passed else "project_validation_failed"
        ),
        "model": model,
        "auth_source": "isolated_symlink_to_opencode_oauth_store",
        "preflight": preflight,
        "candidate": candidate,
        "fixtures": fixtures,
    }


def retained_artifacts_safe(output_dir: Path, secrets: list[str]) -> bool:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(secret and secret in text for secret in secrets):
            return False
    return True


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    secrets = credential_values(host_auth_path())
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
        )
    component_results = [
        component.get("result")
        for key, component in report.items()
        if key in ("mcp", "projects") and isinstance(component, dict)
    ]
    artifact_safe = retained_artifacts_safe(output_dir, secrets)
    report["retained_artifacts_safe"] = artifact_safe
    report["result"] = (
        "PASS"
        if component_results
        and all(result == "PASS" for result in component_results)
        and artifact_safe
        else "BLOCKED"
        if "BLOCKED" in component_results
        else "FAIL"
    )
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"harness wave 2 task 4: {report['result']}")
        print(f"artifacts: {output_dir}")
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
