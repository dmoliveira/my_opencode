#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
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
        choices=("direct", "tuple", "contract", "path", "tarball", "both", "all"),
        default="direct",
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
    parser.add_argument(
        "--aggregate-timeout-seconds",
        type=int,
        default=100,
        help="Shared deadline for contract-mode probes.",
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


def safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def safe_reason(value: Any, fallback: str) -> str:
    reason = str(value or "").strip().lower()
    return reason if re.fullmatch(r"[a-z0-9_]{1,128}", reason) else fallback


def project_contract_result(
    value: dict[str, Any], *, mode: str, artifacts_cleaned: bool
) -> dict[str, Any]:
    result = str(value.get("result") or "FAIL").strip().upper()
    if result not in {"PASS", "FAIL", "SKIP"}:
        result = "FAIL"
    if not artifacts_cleaned:
        result = "FAIL"
    return {
        "mode": mode,
        "result": result,
        "reason": (
            "contract_artifact_cleanup_failed"
            if not artifacts_cleaned
            else safe_reason(value.get("reason"), "contract_probe_failed")
        ),
        "run_exit": safe_int(value.get("run_exit"), 1),
        "audit_exists": bool(value.get("audit_exists")),
        "bootstrap_seen": bool(value.get("bootstrap_seen")),
        "plugin_install_failed": bool(value.get("plugin_install_failed")),
        "plugin_resolve_failed": bool(value.get("plugin_resolve_failed")),
        "artifacts_cleaned": artifacts_cleaned,
    }


def audit_has_reason_code(audit_log: str, reason_code: str) -> bool:
    for raw_line in audit_log.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("reason_code") == reason_code:
            return True
    return False


def isolated_probe_env(home_dir: Path, audit_path: Path) -> dict[str, str]:
    env = {
        key: value
        for key in (
            "LANG",
            "LC_ALL",
            "LOGNAME",
            "PATH",
            "SHELL",
            "TMPDIR",
            "USER",
        )
        if (value := os.environ.get(key))
    }
    env.update(
        {
            "HOME": str(home_dir),
            "XDG_CONFIG_HOME": str(home_dir / ".config"),
            "XDG_CACHE_HOME": str(home_dir / ".cache"),
            "XDG_DATA_HOME": str(home_dir / ".local" / "share"),
            "XDG_STATE_HOME": str(home_dir / ".local" / "state"),
            "CI": "true",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GCM_INTERACTIVE": "never",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_path),
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT": "1",
        }
    )
    runtime_session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    if runtime_session_id:
        env["OPENCODE_SESSION_ID"] = runtime_session_id
    return env


def collect_direct_result(work_dir: Path, run_timeout: int) -> dict[str, Any]:
    home_dir = work_dir / "home"
    project_dir = work_dir / "project"
    config_dir = home_dir / ".config" / "opencode"
    plugin_dir = project_dir / ".opencode" / "plugins"
    config_dir.mkdir(parents=True, exist_ok=True)
    plugin_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        config_dir / "opencode.json",
        {"$schema": "https://opencode.ai/config.json", "plugin": []},
    )
    dist_entry = (PLUGIN_DIR / "dist" / "index.js").resolve()
    plugin_spec = dist_entry.as_uri()
    shim_path = plugin_dir / "gateway-core.js"
    shim_path.write_text(
        "export { default as GatewayCorePlugin } from "
        + json.dumps(plugin_spec)
        + ";\n",
        encoding="utf-8",
    )

    audit_path = work_dir / "gateway-direct-events.jsonl"
    log_path = work_dir / "debug-direct.log"
    run_log = work_dir / "debug-direct.json"
    try:
        run_result = run_command(
            ["opencode", "debug", "config", "--print-logs", "--log-level", "INFO"],
            cwd=project_dir,
            env=isolated_probe_env(home_dir, audit_path),
            timeout=run_timeout,
        )
    except subprocess.TimeoutExpired as error:
        stdout = coerce_text(error.stdout)
        stderr = coerce_text(error.stderr)
        run_result = subprocess.CompletedProcess(error.cmd, 124, stdout, stderr)
    run_log.write_text(coerce_text(run_result.stdout), encoding="utf-8")
    log_path.write_text(coerce_text(run_result.stderr), encoding="utf-8")
    audit_log = (
        audit_path.read_text(encoding="utf-8", errors="replace")
        if audit_path.exists()
        else ""
    )
    bootstrap_seen = audit_has_reason_code(audit_log, "gateway_runtime_bootstrap")
    passed = run_result.returncode == 0 and bootstrap_seen
    return {
        "mode": "direct",
        "plugin_spec": plugin_spec,
        "shim_path": str(shim_path),
        "port": None,
        "work_dir": str(work_dir),
        "run_exit": run_result.returncode,
        "audit_exists": audit_path.exists(),
        "bootstrap_seen": bootstrap_seen,
        "continuation_seen": False,
        "llm_continuation_seen": False,
        "plugin_install_failed": False,
        "plugin_resolve_failed": not bootstrap_seen and "Cannot find module" in coerce_text(run_result.stderr),
        "server_log": str(log_path),
        "audit_log": str(audit_path),
        "run_log": str(run_log),
        "result": "PASS" if passed else "FAIL",
        "reason": (
            "runtime_bootstrap_seen"
            if passed
            else "debug_config_nonzero_exit"
            if run_result.returncode != 0
            else "runtime_bootstrap_missing"
        ),
    }



def collect_tuple_result(work_dir: Path, run_timeout: int) -> dict[str, Any]:
    option_sentinel = "WAVE3_PRIVATE_PLUGIN_OPTION"
    home_dir = work_dir / "home"
    project_dir = work_dir / "project"
    config_dir = home_dir / ".config" / "opencode"
    audit_path = work_dir / "gateway-tuple-events.jsonl"
    config_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    dist_entry = (PLUGIN_DIR / "dist" / "index.js").resolve()
    write_json(
        config_dir / "opencode.json",
        {
            "$schema": "https://opencode.ai/config.json",
            "plugin": [
                [
                    dist_entry.as_uri(),
                    {
                        "hooks": {"enabled": False},
                        "wave3OptionSentinel": option_sentinel,
                    },
                ]
            ],
        },
    )
    result: dict[str, Any]
    try:
        try:
            run_result = run_command(
                ["opencode", "debug", "config", "--print-logs", "--log-level", "INFO"],
                cwd=project_dir,
                env=isolated_probe_env(home_dir, audit_path),
                timeout=run_timeout,
            )
        except subprocess.TimeoutExpired as error:
            run_result = subprocess.CompletedProcess(
                error.cmd,
                124,
                coerce_text(error.stdout),
                coerce_text(error.stderr),
            )
        stdout = coerce_text(run_result.stdout)
        stderr = coerce_text(run_result.stderr)
        audit_log = (
            audit_path.read_text(encoding="utf-8", errors="replace")
            if audit_path.exists()
            else ""
        )
        bootstrap_events: list[dict[str, Any]] = []
        for raw_line in audit_log.splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(event, dict)
                and event.get("reason_code") == "gateway_runtime_bootstrap"
            ):
                bootstrap_events.append(event)
        bootstrap_seen = len(bootstrap_events) == 1
        hooks_disabled = bootstrap_seen and bootstrap_events[0].get("hooks_enabled") is False
        audit_is_sanitized = option_sentinel not in audit_log
        shim_count = len(list(project_dir.glob(".opencode/plugins/*")))
        passed = (
            run_result.returncode == 0
            and bootstrap_seen
            and hooks_disabled
            and audit_is_sanitized
            and shim_count == 0
        )
        result = {
            "mode": "tuple",
            "plugin_spec": "candidate-dist",
            "run_exit": run_result.returncode,
            "audit_exists": audit_path.exists(),
            "bootstrap_seen": bootstrap_seen,
            "hooks_enabled": False if hooks_disabled else None,
            "continuation_seen": False,
            "llm_continuation_seen": False,
            "plugin_install_failed": "failed to install plugin" in stderr,
            "plugin_resolve_failed": "Cannot find module" in stderr,
            "server_log": "",
            "audit_log": "",
            "run_log": "",
            "shim_count": shim_count,
            "raw_option_echo_seen": option_sentinel in stdout or option_sentinel in stderr,
            "audit_sanitized": audit_is_sanitized,
            "artifacts_cleaned": True,
            "result": "PASS" if passed else "FAIL",
            "reason": "tuple_options_applied" if passed else "tuple_options_probe_failed",
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return result


def collect_contract_results(
    run_timeout: int,
    aggregate_timeout: int,
) -> list[dict[str, Any]]:
    outer_root = Path(
        tempfile.mkdtemp(prefix="my-opencode-gateway-contract-")
    ).resolve()
    started_at = time.monotonic()
    raw_results: list[tuple[str, dict[str, Any]]] = []
    try:
        for mode in ("direct", "tuple"):
            remaining = float(aggregate_timeout) - (time.monotonic() - started_at)
            if remaining < 1:
                raw_results.append(
                    (
                        mode,
                        {
                            "result": "FAIL",
                            "reason": "contract_aggregate_timeout",
                            "run_exit": 124,
                        },
                    )
                )
                continue
            timeout = max(1, min(max(1, run_timeout), int(remaining)))
            work_dir = outer_root / mode
            try:
                result = (
                    collect_direct_result(work_dir, timeout)
                    if mode == "direct"
                    else collect_tuple_result(work_dir, timeout)
                )
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                result = {
                    "result": "FAIL",
                    "reason": "contract_probe_exception",
                    "run_exit": 1,
                }
            raw_results.append((mode, result))
    finally:
        shutil.rmtree(outer_root, ignore_errors=True)

    artifacts_cleaned = not outer_root.exists()
    return [
        project_contract_result(
            value,
            mode=mode,
            artifacts_cleaned=artifacts_cleaned,
        )
        for mode, value in raw_results
    ]

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
    repo_config_path = REPO_ROOT / "opencode.json"
    allowed_keys = set(json.loads(repo_config_path.read_text(encoding="utf-8")))
    if config_path.exists():
        try:
            copied_config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            copied_config = {}
        sanitized_config = {
            key: value
            for key, value in copied_config.items()
            if key in allowed_keys
        } if isinstance(copied_config, dict) else {}
    else:
        sanitized_config = {}
    sanitized_config.setdefault("$schema", "https://opencode.ai/config.json")
    sanitized_config["plugin"] = [
        "file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core"
    ]
    write_json(config_path, sanitized_config)
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
        "bootstrap_seen": audit_has_reason_code(
            audit_log, "gateway_runtime_bootstrap"
        ),
        "continuation_seen": "todo_continuation_" in audit_log,
        "llm_continuation_seen": "llm_todo_continuation_" in audit_log,
        "plugin_install_failed": "failed to install plugin" in server_log,
        "plugin_resolve_failed": "Cannot find module" in server_log,
        "server_log": str(log_path),
        "audit_log": str(audit_path),
        "run_log": str(run_log),
        "result": "PASS"
        if audit_path.exists()
        and audit_has_reason_code(audit_log, "gateway_runtime_bootstrap")
        else "FAIL",
        "reason": "runtime_bootstrap_seen"
        if audit_path.exists()
        and audit_has_reason_code(audit_log, "gateway_runtime_bootstrap")
        else "runtime_bootstrap_missing",
    }


def print_text(results: list[dict[str, Any]]) -> None:
    for result in results:
        print(f"mode: {result.get('mode')}")
        print(f"result: {result.get('result')}")
        print(f"reason: {result.get('reason')}")
        print(f"run_exit: {result.get('run_exit')}")
        print(f"audit_exists: {result.get('audit_exists')}")
        print(f"bootstrap_seen: {result.get('bootstrap_seen')}")
        print(f"continuation_seen: {result.get('continuation_seen')}")
        print(f"llm_continuation_seen: {result.get('llm_continuation_seen')}")
        print(f"plugin_install_failed: {result.get('plugin_install_failed')}")
        print(f"plugin_resolve_failed: {result.get('plugin_resolve_failed')}")
        print(f"artifacts_cleaned: {result.get('artifacts_cleaned')}")
        print(f"server_log: {result.get('server_log')}")
        print(f"audit_log: {result.get('audit_log')}")
        print(f"run_log: {result.get('run_log')}")
        print()


def main() -> int:
    args = parse_args()
    if args.mode == "contract":
        results = collect_contract_results(
            max(1, args.run_timeout_seconds),
            max(1, args.aggregate_timeout_seconds),
        )
        if args.output == "json":
            print(json.dumps({"results": results}, indent=2))
        else:
            print_text(results)
        return 1 if any(item.get("result") != "PASS" for item in results) else 0

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="smoke-", dir=RUNTIME_ROOT))
    if args.mode == "both":
        modes = ["path", "tarball"]
    elif args.mode == "all":
        modes = ["direct", "tuple", "path", "tarball"]
    else:
        modes = [args.mode]
    results: list[dict[str, Any]] = []
    for index, mode in enumerate(modes):
        if mode == "direct":
            direct_work_dir = Path(
                tempfile.mkdtemp(prefix="my-opencode-gateway-direct-")
            ).resolve()
            results.append(
                collect_direct_result(direct_work_dir, args.run_timeout_seconds)
            )
            continue
        if mode == "tuple":
            tuple_work_dir = Path(
                tempfile.mkdtemp(prefix="my-opencode-gateway-tuple-")
            ).resolve()
            results.append(
                collect_tuple_result(tuple_work_dir, args.run_timeout_seconds)
            )
            continue
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
