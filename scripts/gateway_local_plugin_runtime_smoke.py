#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_HOME = Path.home() / ".config" / "opencode"
PLUGIN_DIR = REPO_ROOT / "plugin" / "gateway-core"
WRAPPER = REPO_ROOT / "scripts" / "opencode_session.sh"
RUNTIME_ROOT = REPO_ROOT / ".opencode" / "runtime-plugin-smoke"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce local gateway plugin runtime loading issues.",
    )
    parser.add_argument(
        "--mode",
        choices=("path", "tarball", "both"),
        default="both",
        help="Plugin loading mode to test.",
    )
    parser.add_argument(
        "--output",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--run-timeout-seconds",
        type=int,
        default=90,
        help="Timeout for the attached run command.",
    )
    return parser.parse_args()


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def prepare_home(base_dir: Path) -> Path:
    config_dir = base_dir / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "opencode.json",
        "opencode-model-routing.json",
        "opencode-observability.json",
    ):
        source = DEFAULT_CONFIG_HOME / name
        if source.exists():
            shutil.copy2(source, config_dir / name)
    config_path = config_dir / "opencode.json"
    if not config_path.exists():
        write_json(
            config_path,
            {
                "$schema": "https://opencode.ai/config.json",
                "plugin": [
                    "file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core"
                ],
            },
        )
    node_modules = DEFAULT_CONFIG_HOME / "node_modules"
    if node_modules.exists():
        os.symlink(node_modules, config_dir / "node_modules")
    os.symlink(REPO_ROOT, config_dir / "my_opencode")
    plugin_root = config_dir / "my_opencode" / "plugin"
    plugin_root.mkdir(parents=True, exist_ok=True)
    gateway_core = plugin_root / "gateway-core"
    gateway_latest = plugin_root / "gateway-core@latest"
    if not gateway_core.exists():
        os.symlink(PLUGIN_DIR, gateway_core)
    if not gateway_latest.exists():
        os.symlink(gateway_core, gateway_latest)
    return base_dir


def prepare_plugin_spec(mode: str, config_path: Path) -> str:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if mode == "path":
        spec = "file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core"
    else:
        pack = subprocess.run(
            ["npm", "pack"],
            cwd=PLUGIN_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        if pack.returncode != 0:
            raise RuntimeError(f"npm pack failed: {pack.stderr.strip()}")
        tarball = pack.stdout.strip().splitlines()[-1].strip()
        spec = f"file:{(PLUGIN_DIR / tarball).resolve()}"
    payload["plugin"] = [spec]
    write_json(config_path, payload)
    return spec


def start_server(
    home_dir: Path, port: int, audit_path: Path, log_path: Path
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "CI": "true",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GCM_INTERACTIVE": "never",
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_path),
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT": "1",
        }
    )
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(WRAPPER),
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(port),
            "--print-logs",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    for _ in range(100):
        if log_path.exists() and "server listening" in log_path.read_text(
            encoding="utf-8", errors="replace"
        ):
            return process
        if process.poll() is not None:
            return process
        time.sleep(0.2)
    return process


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
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


def run_attached_session(
    home_dir: Path, port: int, run_log: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "CI": "true",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GCM_INTERACTIVE": "never",
        }
    )
    command = [
        "opencode",
        "run",
        "--attach",
        f"http://127.0.0.1:{port}",
        "--dir",
        str(REPO_ROOT),
        "--format",
        "json",
        "--title",
        "Gateway Plugin Smoke",
        "Create a one-item todo list, run `git status --short --branch`, report the result briefly, and stop as soon as that single task is complete. Do not look for issues or additional work.",
    ]
    result = run_command(command, cwd=REPO_ROOT, env=env, timeout=timeout)
    run_log.write_text(result.stdout, encoding="utf-8")
    return result


def collect_result(
    mode: str, plugin_spec: str, work_dir: Path, port: int, run_timeout: int
) -> dict[str, Any]:
    home_dir = prepare_home(work_dir / "home")
    config_path = home_dir / ".config" / "opencode" / "opencode.json"
    plugin_spec = prepare_plugin_spec(mode, config_path)
    audit_path = work_dir / f"gateway-{mode}-events.jsonl"
    log_path = work_dir / f"server-{mode}.log"
    run_log = work_dir / f"run-{mode}.jsonl"
    server = start_server(home_dir, port, audit_path, log_path)
    try:
        run_result = run_attached_session(home_dir, port, run_log, run_timeout)
    except subprocess.TimeoutExpired as error:
        stdout = coerce_text(error.stdout)
        stderr = coerce_text(error.stderr)
        run_log.write_text(stdout, encoding="utf-8")
        run_result = subprocess.CompletedProcess(error.cmd, 124, stdout, stderr)
    finally:
        stop_server(server)
    server_log = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.exists()
        else ""
    )
    audit_log = (
        audit_path.read_text(encoding="utf-8", errors="replace")
        if audit_path.exists()
        else ""
    )
    if run_result.returncode != 0:
        return {
            "mode": mode,
            "plugin_spec": plugin_spec,
            "port": port,
            "work_dir": str(work_dir),
            "run_exit": run_result.returncode,
            "audit_exists": audit_path.exists(),
            "bootstrap_seen": False,
            "continuation_seen": False,
            "llm_continuation_seen": False,
            "plugin_install_failed": "failed to install plugin" in server_log,
            "plugin_resolve_failed": "Cannot find module" in server_log,
            "server_log": str(log_path),
            "audit_log": str(audit_path),
            "run_log": str(run_log),
            "result": "FAIL",
            "reason": "run_nonzero_exit",
        }
    return {
        "mode": mode,
        "plugin_spec": plugin_spec,
        "port": port,
        "work_dir": str(work_dir),
        "run_exit": run_result.returncode,
        "audit_exists": audit_path.exists(),
        "bootstrap_seen": "gateway_runtime_bootstrap" in audit_log,
        "continuation_seen": "todo_continuation_" in audit_log,
        "llm_continuation_seen": "llm_todo_continuation_" in audit_log,
        "plugin_install_failed": "failed to install plugin" in server_log,
        "plugin_resolve_failed": "Cannot find module" in server_log,
        "server_log": str(log_path),
        "audit_log": str(audit_path),
        "run_log": str(run_log),
        "result": "PASS"
        if audit_path.exists() and "gateway_runtime_bootstrap" in audit_log
        else "FAIL",
        "reason": "runtime_bootstrap_seen"
        if audit_path.exists() and "gateway_runtime_bootstrap" in audit_log
        else "runtime_bootstrap_missing",
    }


def print_text(results: list[dict[str, Any]]) -> None:
    for result in results:
        print(f"mode: {result['mode']}")
        print(f"plugin_spec: {result['plugin_spec']}")
        print(f"run_exit: {result['run_exit']}")
        print(f"audit_exists: {result['audit_exists']}")
        print(f"bootstrap_seen: {result['bootstrap_seen']}")
        print(f"continuation_seen: {result['continuation_seen']}")
        print(f"llm_continuation_seen: {result['llm_continuation_seen']}")
        print(f"plugin_install_failed: {result['plugin_install_failed']}")
        print(f"plugin_resolve_failed: {result['plugin_resolve_failed']}")
        print(f"server_log: {result['server_log']}")
        print(f"audit_log: {result['audit_log']}")
        print(f"run_log: {result['run_log']}")
        print()


def main() -> int:
    args = parse_args()
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="smoke-", dir=RUNTIME_ROOT))
    modes = [args.mode] if args.mode != "both" else ["path", "tarball"]
    results: list[dict[str, Any]] = []
    for index, mode in enumerate(modes):
        results.append(
            collect_result(
                mode,
                "",
                work_dir / mode,
                reserve_port() + index,
                args.run_timeout_seconds,
            )
        )
    if args.output == "json":
        print(json.dumps({"results": results}, indent=2))
    else:
        print_text(results)
    failed = any(
        isinstance(item, dict)
        and str(item.get("result") or "").strip().upper() != "PASS"
        for item in results
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
