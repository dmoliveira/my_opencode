#!/usr/bin/env python3

"""Exercise the built gateway status hook through a real local OpenCode server."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_OPENCODE_VERSION = "1.18.18"
STATE_DIRECTORY = ".opencode"
STATE_FILE = "gateway-core.state.json"


class SmokeError(RuntimeError):
    """A deterministic live-smoke failure suitable for concise reporting."""


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise SmokeError("private_work_directory_invalid")


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def resolve_opencode_binary(binary: str) -> str:
    candidate = Path(binary).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        resolved = candidate.resolve(strict=False)
    else:
        found = shutil.which(binary)
        resolved = Path(found).resolve(strict=False) if found else candidate
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise SmokeError("opencode_binary_not_found")
    return str(resolved)


def opencode_version(binary: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        [binary, "--version"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    version = result.stdout.strip()
    if result.returncode != 0 or version != EXPECTED_OPENCODE_VERSION:
        raise SmokeError("opencode_version_mismatch")
    return version


def isolated_environment(home: Path, audit_path: Path, without_bun: bool) -> dict[str, str]:
    env = {
        key: value
        for key in ("LANG", "LC_ALL", "LOGNAME", "PATH", "SHELL", "TMPDIR", "USER")
        if (value := os.environ.get(key))
    }
    if without_bun:
        entries = [
            entry
            for entry in env.get("PATH", "").split(os.pathsep)
            if not (Path(entry) / "bun").is_file()
        ]
        env["PATH"] = os.pathsep.join(entries)
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
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT": "1",
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_path),
        }
    )
    runtime_session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    if runtime_session_id:
        env["OPENCODE_SESSION_ID"] = runtime_session_id
    return env


def write_isolated_config(home: Path) -> None:
    config_dir = home / ".config" / "opencode"
    ensure_private_directory(config_dir)
    repo_link = config_dir / "my_opencode"
    repo_link.symlink_to(REPO_ROOT, target_is_directory=True)
    config = {
        "$schema": "https://opencode.ai/config.json",
        "plugin": [
            "file://{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core/dist/index.js"
        ],
    }
    config_path = config_dir / "opencode.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.chmod(config_path, 0o600)


def start_server(
    binary: str,
    project: Path,
    port: int,
    env: dict[str, str],
    log_path: Path,
) -> tuple[subprocess.Popen[str], Any]:
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            binary,
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(port),
            "--print-logs",
            "--log-level",
            "INFO",
        ],
        cwd=project,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    return process, handle


def wait_for_server(process: subprocess.Popen[str], log_path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "server listening" in log_path.read_text(encoding="utf-8", errors="replace"):
            return
        if process.poll() is not None:
            raise SmokeError("server_start_failed")
        time.sleep(0.1)
    raise SmokeError("server_start_timeout")


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError) as error:
        raise SmokeError("local_api_request_failed") from error
    if not isinstance(parsed, dict):
        raise SmokeError("local_api_response_invalid")
    return parsed


def wait_for_status(state_path: Path, session_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            entry = state["executionStatus"]["sessions"][session_id]
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            time.sleep(0.1)
            continue
        if isinstance(entry, dict) and entry.get("last") == "Session ready":
            return state
        time.sleep(0.1)
    raise SmokeError("execution_status_not_updated")


def validate_private_state(state_path: Path, session_id: str, title: str) -> None:
    state_directory = state_path.parent
    directory_metadata = state_directory.lstat()
    file_metadata = state_path.lstat()
    if (
        state_directory.is_symlink()
        or not stat.S_ISDIR(directory_metadata.st_mode)
        or directory_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(directory_metadata.st_mode) != 0o700
    ):
        raise SmokeError("state_directory_not_private")
    if (
        state_path.is_symlink()
        or not stat.S_ISREG(file_metadata.st_mode)
        or file_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(file_metadata.st_mode) != 0o600
    ):
        raise SmokeError("state_file_not_private")
    raw = state_path.read_text(encoding="utf-8")
    if title in raw:
        raise SmokeError("session_title_persisted")
    try:
        entry = json.loads(raw)["executionStatus"]["sessions"][session_id]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SmokeError("execution_status_missing") from error
    if entry.get("last") != "Session ready" or entry.get("next") != "Begin execution":
        raise SmokeError("execution_status_wrong_milestone")


def audit_has_status_event(path: Path, session_id: str) -> bool:
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, json.JSONDecodeError):
        return False
    return any(
        isinstance(record, dict)
        and record.get("reason_code") == "execution_status_session_ready"
        and record.get("session_id") == session_id
        for record in records
    )


def stop_server(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=5)


def run(binary: str, timeout: float, without_bun: bool) -> dict[str, Any]:
    resolved_binary = resolve_opencode_binary(binary)
    work_dir = Path(tempfile.mkdtemp(prefix="gateway-execution-status-live-"))
    process: subprocess.Popen[str] | None = None
    handle: Any = None
    try:
        ensure_private_directory(work_dir)
        home = work_dir / "home"
        project = work_dir / "project"
        audit_path = work_dir / "gateway-events.jsonl"
        log_path = work_dir / "server.log"
        ensure_private_directory(home)
        ensure_private_directory(project)
        env = isolated_environment(home, audit_path, without_bun)
        version = opencode_version(resolved_binary, env)
        write_isolated_config(home)
        process, handle = start_server(
            resolved_binary, project, reserve_port(), env, log_path
        )
        wait_for_server(process, log_path, timeout)
        base_url = f"http://127.0.0.1:{process.args[process.args.index('--port') + 1]}"
        title = "Gateway execution status smoke"
        created = post_json(
            f"{base_url}/session?directory={quote(str(project), safe='')}",
            {"title": title},
            timeout,
        )
        session_id = created.get("id")
        if not isinstance(session_id, str) or not session_id.startswith("ses"):
            raise SmokeError("session_create_response_invalid")
        state_path = project / STATE_DIRECTORY / STATE_FILE
        wait_for_status(state_path, session_id, timeout)
        validate_private_state(state_path, session_id, title)
        if not audit_has_status_event(audit_path, session_id):
            raise SmokeError("execution_status_audit_missing")
        return {
            "result": "PASS",
            "opencode_version": version,
            "without_bun": without_bun,
            "state_directory_mode": "0700",
            "state_file_mode": "0600",
            "last": "Session ready",
            "next": "Begin execution",
            "model_requests": 0,
        }
    finally:
        stop_server(process)
        if handle is not None:
            handle.close()
        shutil.rmtree(work_dir, ignore_errors=True)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run a no-model live OpenCode execution-status smoke."
    )
    parser.add_argument("--opencode-bin", default=shutil.which("opencode") or "opencode")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--without-bun", action="store_true")
    parser.add_argument("--output", choices=("json", "text"), default="text")
    args = parser.parse_args(list(argv))
    try:
        payload = run(str(args.opencode_bin), max(1.0, args.timeout_seconds), args.without_bun)
    except (OSError, SmokeError, subprocess.SubprocessError) as error:
        payload = {"result": "FAIL", "reason": str(error) or type(error).__name__}

    if args.output == "json":
        print(json.dumps(payload, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0 if payload.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
