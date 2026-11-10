"""Measure whether the V2 direct shell API waits for a configured plugin.

MEASURED means the pinned hosts reproduced the observed behavior, not that
shell execution is guarded. All commands run in owned disposable fixtures.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from gateway_v2_auxiliary_redaction_probe import write_fixture
from gateway_v2_dependency_contract_probe import (
    MANAGERS,
    ProbeFailure,
    child_env,
    preflight,
    run_child,
)
from gateway_v2_dependency_profile_probe import (
    PrivateRuntime,
    activated_inventory,
    owned_fixture,
)

VERSIONS = {"opencode v2.2.5", "opencode v2.2.6"}
CASE_SECONDS = 40
CLEANUP_SECONDS = 10


def read_owned(path: Path, limit: int = 4096) -> str | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_size > limit
        ):
            raise ProbeFailure("fixture_observation_invalid")
        content = os.read(descriptor, limit + 1)
        if len(content) > limit:
            raise ProbeFailure("fixture_observation_invalid")
        return content.decode("utf-8")
    finally:
        os.close(descriptor)


def wait_for(
    predicate: Callable[[], bool], runtime: PrivateRuntime, reason: str
) -> None:
    deadline = min(runtime.deadline, time.monotonic() + 8)
    while time.monotonic() < deadline:
        # Keep the process-group leader unreaped until PrivateRuntime.close()
        # signals its group; poll() would release that identity too early.
        if runtime.process is None:
            raise ProbeFailure("runtime_not_started")
        if predicate():
            return
        threading.Event().wait(0.025)
    raise ProbeFailure(reason)


def wait_for_shell_exit(
    runtime: PrivateRuntime, response: object, command: str, cwd: Path
) -> None:
    """Confirm an owned direct shell exited; a timeout status is not settlement."""
    if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise ProbeFailure("shell_response_invalid")
    shell_id = response["data"].get("id")
    if not isinstance(shell_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,160}", shell_id
    ):
        raise ProbeFailure("shell_identity_invalid")
    for _attempt in range(6):
        result = runtime.request("GET", f"/api/shell/{shell_id}")
        if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
            raise ProbeFailure("shell_status_invalid")
        info = result["data"]
        if (
            info.get("id") != shell_id
            or info.get("command") != command
            or info.get("cwd") != str(cwd)
            or info.get("shell") != "/bin/sh"
        ):
            raise ProbeFailure("shell_identity_mismatch")
        if info.get("status") == "exited" and info.get("exit") == 0:
            return
        if info.get("status") != "running":
            raise ProbeFailure("shell_exit_unsuccessful")
        threading.Event().wait(0.25)
    raise ProbeFailure("shell_settlement_unconfirmed")


def prepare(root: Path) -> None:
    for name in ("home", "project", "tmp", "bin"):
        (root / name).mkdir(mode=0o700)
    trace = root / "trace"
    gate = root / "release"
    plugin = f"""import {{ Plugin }} from "@opencode/plugin"
import {{ appendFileSync, existsSync, writeFileSync }} from "node:fs"
const trace = {json.dumps(str(trace))}, gate = {json.dumps(str(gate))}
const record = value => appendFileSync(trace, value + "\\n", {{ mode: 0o600 }})
export default Plugin.define({{ id: "profile-owned", async setup(ctx) {{
  writeFileSync(trace, "setup\\n", {{ mode: 0o600 }})
  const deadline = Date.now() + 15000
  while (!existsSync(gate)) {{
    if (Date.now() >= deadline) throw new Error("PROBE_SETUP_TIMEOUT")
    await new Promise(resolve => setTimeout(resolve, 20))
  }}
  await ctx.shell.hook("create.before", event => {{
    record("hook")
    if (event.command === "printf BLOCKED > blocked-witness") {{
      record("blocked")
      throw new Error("PROBE_BLOCKED")
    }}
    let id = event.env.OPENCODE_SESSION_ID
    Object.defineProperty(event.env, "OPENCODE_SESSION_ID", {{
      enumerable: true, configurable: false, get() {{ return id }},
      set(value) {{ record("session-set"); id = value }},
    }})
  }})
  record("ready")
}} }})
"""
    write_fixture(root, "project/owned/index.ts", plugin)
    config = {
        "plugins": [str(root / "project/owned")],
        "shell": "/bin/sh",
        "update": "disable",
        "snapshots": False,
        "formatter": False,
        "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
        "policies": [{"action": "tool.use", "resource": "shell:*", "effect": "deny"}],
    }
    write_fixture(root, "project/opencode.json", json.dumps(config))
    write_fixture(root, "home/.config/opencode/opencode.json", '{"update":"disable"}')
    for manager in (*MANAGERS, "corepack", "pnpx", "yarnpkg", "pipx", "uvx"):
        write_fixture(root, f"bin/{manager}", "#!/bin/sh\nexit 97\n", executable=True)


def run_probe(binary: str, parent: Path) -> dict[str, object]:
    preflight(parent)
    root = Path(tempfile.mkdtemp(prefix="v2-direct-shell-", dir=parent))
    identity = root.lstat()
    runtime: PrivateRuntime | None = None
    warm_thread: threading.Thread | None = None
    warm_started = False
    warm_complete = threading.Event()
    cleanup_errors: list[str] = []
    shell_unsettled = False
    report: dict[str, object] = {
        "result": "FAIL",
        "meaning": "measurement only; not protection",
    }
    try:
        prepare(root)
        code, stdout, _ = run_child(
            [binary, "--version"], root / "project", child_env(root), timeout=10
        )
        version = stdout.decode("utf-8", errors="replace").strip()
        if code != 0 or version not in VERSIONS:
            raise ProbeFailure("unsupported_host_version")
        report["host"] = version
        runtime = PrivateRuntime(binary, root, time.monotonic() + CASE_SECONDS)
        runtime.start()
        runtime.ready()

        def warm() -> None:
            try:
                runtime.request(
                    "GET",
                    "/api/plugin?"
                    + urlencode({"location[directory]": str(root / "project")}),
                )
            except (ProbeFailure, OSError, ValueError, http.client.HTTPException):
                return
            warm_complete.set()

        warm_thread = threading.Thread(target=warm, daemon=True)
        warm_thread.start()
        warm_started = True
        trace = root / "trace"
        wait_for(
            lambda: read_owned(trace) == "setup\n", runtime, "plugin_setup_not_observed"
        )
        shell_unsettled = True
        first = runtime.mutate(
            "POST",
            "/api/shell",
            {
                "command": "printf FIRST > first-witness",
                "cwd": str(root / "project"),
                "timeout": 5000,
            },
        )
        first_witness = root / "project/first-witness"
        wait_for(
            lambda: read_owned(first_witness) == "FIRST",
            runtime,
            "first_witness_missing",
        )
        wait_for_shell_exit(
            runtime, first, "printf FIRST > first-witness", root / "project"
        )
        shell_unsettled = False
        before_release = read_owned(trace)
        write_fixture(root, "release", "release\n")
        wait_for(
            lambda: "ready\n" in (read_owned(trace) or ""),
            runtime,
            "plugin_ready_not_observed",
        )
        warm_thread.join(timeout=5)
        if warm_thread.is_alive() or not warm_complete.is_set():
            raise ProbeFailure("plugin_list_did_not_settle")
        inventory = activated_inventory(runtime, root)
        if not any(
            item.get("source") == "owned" and item.get("status") == "active"
            for item in inventory
        ):
            raise ProbeFailure("fixture_plugin_not_active")
        shell_unsettled = True
        second = runtime.mutate(
            "POST",
            "/api/shell",
            {
                "command": "printf SECOND > second-witness",
                "cwd": str(root / "project"),
                "timeout": 5000,
            },
        )
        second_witness = root / "project/second-witness"
        wait_for(
            lambda: read_owned(second_witness) == "SECOND",
            runtime,
            "second_witness_missing",
        )
        wait_for_shell_exit(
            runtime, second, "printf SECOND > second-witness", root / "project"
        )
        shell_unsettled = False
        blocked_status = None
        shell_unsettled = True
        try:
            blocked = runtime.mutate(
                "POST",
                "/api/shell",
                {
                    "command": "printf BLOCKED > blocked-witness",
                    "cwd": str(root / "project"),
                    "timeout": 5000,
                },
            )
            wait_for_shell_exit(
                runtime, blocked, "printf BLOCKED > blocked-witness", root / "project"
            )
            shell_unsettled = False
        except ProbeFailure as error:
            if str(error) != "native_api_status_500":
                raise
            blocked_status = str(error)
        lines = (read_owned(trace) or "").splitlines()
        if blocked_status == "native_api_status_500" and lines[-2:] == [
            "hook",
            "blocked",
        ]:
            shell_unsettled = False
        report.update(
            {
                "first_response_created": isinstance(first, dict)
                and isinstance(first.get("data"), dict),
                "first_witness_before_plugin_ready": read_owned(first_witness)
                == "FIRST"
                and before_release == "setup\n",
                "configured_plugin_active": True,
                "second_response_created": isinstance(second, dict)
                and isinstance(second.get("data"), dict),
                "second_witness_after_plugin_ready": read_owned(second_witness)
                == "SECOND",
                "post_activation_hook_seen": lines
                == ["setup", "ready", "hook", "hook", "blocked"],
                "post_activation_host_session_set": "session-set" in lines,
                "post_activation_block_refused": blocked_status
                == "native_api_status_500"
                and "blocked" in lines,
            }
        )
    except (
        ProbeFailure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        http.client.HTTPException,
        subprocess.SubprocessError,
    ) as error:
        report["reason"] = (
            str(error) if isinstance(error, ProbeFailure) else "probe_failed"
        )
    finally:
        if shell_unsettled:
            cleanup_errors.append("shell_settlement_unconfirmed")
        if runtime is not None:
            try:
                runtime.close(time.monotonic() + CLEANUP_SECONDS)
            except (ProbeFailure, OSError, RuntimeError, subprocess.SubprocessError):
                cleanup_errors.append("runtime_cleanup_failed")
        if warm_thread is not None and warm_started:
            warm_thread.join(timeout=5)
            if warm_thread.is_alive():
                cleanup_errors.append("plugin_list_thread_alive")
        try:
            if read_owned(root / "project/blocked-witness") is not None:
                cleanup_errors.append("blocked_witness_present")
        except (ProbeFailure, OSError, UnicodeError):
            cleanup_errors.append("blocked_witness_invalid")
        if not owned_fixture(root, identity):
            cleanup_errors.append("fixture_identity_changed")
        if not cleanup_errors:
            try:
                shutil.rmtree(root)
            except OSError:
                cleanup_errors.append("fixture_removal_failed")
        report["cleanup_complete"] = not cleanup_errors
        if cleanup_errors:
            report["reason"] = "cleanup_failed"
    if measured(report):
        report["result"] = "MEASURED"
    return report


def measured(report: dict[str, object]) -> bool:
    """Success reproduces a measured limitation; it never grants authority."""
    return (
        "reason" not in report
        and report.get("host") in VERSIONS
        and report.get("first_response_created") is True
        and report.get("first_witness_before_plugin_ready") is True
        and report.get("configured_plugin_active") is True
        and report.get("second_response_created") is True
        and report.get("second_witness_after_plugin_ready") is True
        and report.get("post_activation_hook_seen") is True
        and report.get("post_activation_host_session_set") is False
        and report.get("post_activation_block_refused") is True
        and report.get("cleanup_complete") is True
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode-bin", default="opencode")
    parser.add_argument("--temp-parent", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    binary = shutil.which(args.opencode_bin)
    if not binary or os.name != "posix":
        parser.error("an installed POSIX OpenCode 2.2.5 or 2.2.6 is required")
    try:
        report = run_probe(str(Path(binary).resolve()), args.temp_parent.resolve())
    except (ProbeFailure, OSError, ValueError, RuntimeError):
        report = {"result": "FAIL", "reason": "probe_preflight_failed"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("result") == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
