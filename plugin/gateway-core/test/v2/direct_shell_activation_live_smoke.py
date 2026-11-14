"""Measure whether the V2 direct shell API waits for a configured plugin.

MEASURED means the tested hosts reproduced the observed behavior, not that
shell execution is guarded. Synthetic fixtures are retained on every outcome.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from gateway_v2_auxiliary_redaction_probe import (
    CaptureHandler,
    CaptureProvider,
    CaptureState,
    write_fixture,
)
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
WITNESS_OBSERVATION_SECONDS = 0.5
TRACE_EVENTS = {"setup", "ready", "hook", "blocked", "session-set"}
EXPECTED_TRACE = ["setup", "ready", "hook", "hook", "hook", "blocked"]


@dataclass
class DirectState(CaptureState):
    witness_key: str = field(default_factory=lambda: secrets.token_hex(24))
    witnesses: list[str] = field(default_factory=list)
    blocked_seen: threading.Event = field(default_factory=threading.Event)


class DirectHandler(CaptureHandler):
    def do_GET(self) -> None:
        state: DirectState = self.started()  # type: ignore[assignment]
        try:
            if self.path != "/gate":
                raise ProbeFailure("unexpected_control_path")
            if self.headers.get("Authorization") != f"Bearer {state.control_key}":
                raise ProbeFailure("control_authentication_failed")
            if state.control.hold(state.deadline, state.stopped) != "continue":
                raise ProbeFailure("control_refused")
            self.reply(b'{"ok":true}')
        except (ProbeFailure, OSError) as error:
            if not state.stopped.is_set():
                state.failure = state.failure or (
                    str(error)
                    if isinstance(error, ProbeFailure)
                    else "control_protocol_error"
                )
                self.send_error(400)

    def do_POST(self) -> None:
        if self.path == "/trace":
            super().do_POST()
            return
        state: DirectState = self.started()  # type: ignore[assignment]
        try:
            if self.path not in ("/witness/positive", "/witness/blocked"):
                raise ProbeFailure("unexpected_witness_path")
            if self.headers.get("Authorization") != f"Bearer {state.witness_key}":
                raise ProbeFailure("witness_authentication_failed")
            if self.headers.get("Content-Length") != "0":
                raise ProbeFailure("witness_request_invalid")
            with state.lock:
                if len(state.witnesses) >= 2:
                    raise ProbeFailure("witness_limit")
                witness = self.path.rsplit("/", 1)[-1]
                state.witnesses.append(witness)
                if witness == "blocked":
                    state.blocked_seen.set()
            self.reply(b'{"ok":true}')
        except (ProbeFailure, OSError) as error:
            if not state.stopped.is_set():
                state.failure = state.failure or (
                    str(error)
                    if isinstance(error, ProbeFailure)
                    else "witness_protocol_error"
                )
                self.send_error(400)


class DirectController(CaptureProvider):
    def __init__(self, state: DirectState):
        super().__init__(state)
        self.RequestHandlerClass = DirectHandler


def observations(state: DirectState) -> tuple[list[str], list[str]]:
    with state.lock:
        if state.failure:
            raise ProbeFailure(state.failure)
        rows = list(state.trace_rows)
        witnesses = list(state.witnesses)
    if any(
        not isinstance(row, dict)
        or set(row) != {"event"}
        or row.get("event") not in TRACE_EVENTS
        for row in rows
    ):
        raise ProbeFailure("trace_schema_invalid")
    return [row["event"] for row in rows], witnesses


def witness_command(port: int, key: str, kind: str) -> str:
    if kind not in ("positive", "blocked"):
        raise ProbeFailure("witness_kind_invalid")
    url = f"http://127.0.0.1:{port}/witness/{kind}"
    authorization = f"Bearer {key}"
    script = (
        "import urllib.request as u; "
        f"r=u.Request({url!r},data=b'',headers={{'Authorization':{authorization!r}}},method='POST'); "
        "u.build_opener(u.ProxyHandler({})).open(r,timeout=2).read()"
    )
    return shlex.join([sys.executable, "-I", "-B", "-c", script])


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
    runtime: PrivateRuntime, response: object, command: str, cwd: Path, expected: str
) -> None:
    """Correlate a successful exit and its bounded output; timeout is not settlement."""
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
        if (
            info.get("status") == "exited"
            and type(info.get("exit")) is int
            and info.get("exit") == 0
        ):
            output = runtime.request(
                "GET", f"/api/shell/{shell_id}/output?cursor=0&limit=128"
            )
            if not isinstance(output, dict) or not isinstance(output.get("data"), dict):
                raise ProbeFailure("shell_output_invalid")
            data = output["data"]
            size = len(expected.encode("utf-8"))
            if (
                data.get("output") != expected
                or type(data.get("cursor")) is not int
                or data.get("cursor") != size
                or type(data.get("size")) is not int
                or data.get("size") != size
                or data.get("truncated") is not False
            ):
                raise ProbeFailure("shell_output_mismatch")
            return
        if info.get("status") != "running":
            raise ProbeFailure("shell_exit_unsuccessful")
        threading.Event().wait(0.25)
    raise ProbeFailure("shell_settlement_unconfirmed")


def prepare(root: Path, port: int, state: DirectState, blocked_command: str) -> None:
    for name in ("home", "project", "tmp", "bin"):
        (root / name).mkdir(mode=0o700)
    base = f"http://127.0.0.1:{port}"
    plugin = f"""import {{ Plugin }} from "@opencode/plugin"
const base = {json.dumps(base)}, key = {json.dumps(state.control_key)}
const blockedCommand = {json.dumps(blocked_command)}
let tail = Promise.resolve(), count = 0
const record = event => {{
  if (++count > 32) throw new Error("PROBE_TRACE_LIMIT")
  tail = tail.then(async () => {{
    const response = await fetch(base + "/trace", {{ method: "POST", headers: {{ "Authorization": `Bearer ${{key}}`, "Content-Type": "application/json" }}, body: JSON.stringify({{ event }}) }})
    if (!response.ok) throw new Error("PROBE_TRACE_FAILED")
  }})
  return tail
}}
export default Plugin.define({{ id: "profile-owned", async setup(ctx) {{
  await record("setup")
  const release = await fetch(base + "/gate", {{ headers: {{ "Authorization": `Bearer ${{key}}` }} }})
  if (!release.ok) throw new Error("PROBE_SETUP_FAILED")
  await ctx.shell.hook("create.before", async event => {{
    await record("hook")
    if (event.command === blockedCommand) {{
      await record("blocked")
      throw new Error("PROBE_BLOCKED")
    }}
    let id = event.env.OPENCODE_SESSION_ID
    Object.defineProperty(event.env, "OPENCODE_SESSION_ID", {{
      enumerable: true, configurable: false, get() {{ return id }},
      set(value) {{ id = value; void record("session-set").catch(() => {{}}) }},
    }})
  }})
  await record("ready")
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
    state = DirectState("direct-shell", root, time.monotonic() + CASE_SECONDS)
    controller: DirectController | None = None
    controller_thread: threading.Thread | None = None
    controller_started = False
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
        controller = DirectController(state)
        controller_thread = threading.Thread(
            target=controller.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        controller_thread.start()
        controller_started = True
        blocked_command = witness_command(
            controller.server_port, state.witness_key, "blocked"
        )
        positive_command = witness_command(
            controller.server_port, state.witness_key, "positive"
        )
        prepare(root, controller.server_port, state, blocked_command)
        code, stdout, _ = run_child(
            [binary, "--version"], root / "project", child_env(root), timeout=10
        )
        version = stdout.decode("utf-8", errors="replace").strip()
        if code != 0 or version not in VERSIONS:
            raise ProbeFailure("unsupported_host_version")
        report["host"] = version
        runtime = PrivateRuntime(binary, root, state.deadline)
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
        wait_for(
            lambda: observations(state)[0] == ["setup"],
            runtime,
            "plugin_setup_not_observed",
        )
        shell_unsettled = True
        first = runtime.mutate(
            "POST",
            "/api/shell",
            {
                "command": "printf FIRST",
                "cwd": str(root / "project"),
                "timeout": 5000,
            },
        )
        wait_for_shell_exit(runtime, first, "printf FIRST", root / "project", "FIRST")
        shell_unsettled = False
        before_release, before_witnesses = observations(state)
        state.control.release()
        wait_for(
            lambda: "ready" in observations(state)[0],
            runtime,
            "plugin_ready_not_observed",
        )
        warm_thread.join(timeout=5)
        if warm_thread.is_alive() or not warm_complete.is_set():
            raise ProbeFailure("plugin_list_did_not_settle")
        inventory = activated_inventory(runtime, root)
        owned = [
            item.get("source") == "owned" and item.get("status") == "active"
            for item in inventory
        ]
        if sum(owned) != 1:
            raise ProbeFailure("fixture_plugin_not_active")
        shell_unsettled = True
        second = runtime.mutate(
            "POST",
            "/api/shell",
            {
                "command": "printf SECOND",
                "cwd": str(root / "project"),
                "timeout": 5000,
            },
        )
        wait_for_shell_exit(
            runtime, second, "printf SECOND", root / "project", "SECOND"
        )
        shell_unsettled = False

        shell_unsettled = True
        positive = runtime.mutate(
            "POST",
            "/api/shell",
            {
                "command": positive_command,
                "cwd": str(root / "project"),
                "timeout": 5000,
            },
        )
        wait_for_shell_exit(runtime, positive, positive_command, root / "project", "")
        shell_unsettled = False
        _events, positive_witnesses = observations(state)
        if positive_witnesses != ["positive"]:
            raise ProbeFailure("positive_witness_missing")

        blocked_status = None
        shell_unsettled = True
        # Only the create response itself can establish a refused request.
        runtime.verify_owner()
        try:
            blocked = runtime.request(
                "POST",
                "/api/shell",
                {
                    "command": blocked_command,
                    "cwd": str(root / "project"),
                    "timeout": 5000,
                },
            )
        except ProbeFailure as error:
            if str(error) != "native_api_status_500":
                raise
            blocked_status = str(error)
        else:
            # A later status/output failure is not rejection of the create request.
            wait_for_shell_exit(runtime, blocked, blocked_command, root / "project", "")
            shell_unsettled = False
        remaining = min(WITNESS_OBSERVATION_SECONDS, state.deadline - time.monotonic())
        if remaining <= 0:
            raise ProbeFailure("case_timeout")
        if state.blocked_seen.wait(remaining):
            raise ProbeFailure("blocked_witness_observed")
        lines, witnesses = observations(state)
        if blocked_status == "native_api_status_500" and lines[-2:] == [
            "hook",
            "blocked",
        ]:
            shell_unsettled = False
        report.update(
            {
                "first_response_created": isinstance(first, dict)
                and isinstance(first.get("data"), dict),
                "first_witness_before_plugin_ready": before_release == ["setup"]
                and before_witnesses == [],
                "configured_plugin_active": True,
                "second_response_created": isinstance(second, dict)
                and isinstance(second.get("data"), dict),
                "second_witness_after_plugin_ready": True,
                "post_activation_hook_seen": lines == EXPECTED_TRACE,
                "post_activation_host_session_set": "session-set" in lines,
                "post_activation_block_refused": blocked_status
                == "native_api_status_500"
                and "blocked" in lines,
                "positive_witness_control": witnesses == ["positive"],
                "blocked_witness_not_observed": "blocked" not in witnesses,
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
        deadline = time.monotonic() + CLEANUP_SECONDS
        state.stop()
        if shell_unsettled:
            cleanup_errors.append("shell_settlement_unconfirmed")
        if controller is not None:
            try:
                if controller_started:
                    controller.shutdown()
                controller.close_connections()
            except OSError:
                cleanup_errors.append("controller_stop_failed")
        if runtime is not None:
            try:
                runtime.close(deadline)
            except (ProbeFailure, OSError, RuntimeError, subprocess.SubprocessError):
                cleanup_errors.append("runtime_cleanup_failed")
        if warm_thread is not None and warm_started:
            warm_thread.join(max(0, deadline - time.monotonic()))
            if warm_thread.is_alive():
                cleanup_errors.append("plugin_list_thread_alive")
        if controller is not None:
            try:
                controller.server_close()
            except OSError:
                cleanup_errors.append("controller_close_failed")
            for worker in controller.workers:
                worker.join(max(0, deadline - time.monotonic()))
                if worker.is_alive():
                    cleanup_errors.append("controller_worker_alive")
            if controller.admissions != state.handlers:
                cleanup_errors.append("controller_request_unhandled")
        if controller_thread is not None and controller_started:
            controller_thread.join(max(0, deadline - time.monotonic()))
            if controller_thread.is_alive():
                cleanup_errors.append("controller_thread_alive")
        if time.monotonic() > deadline:
            cleanup_errors.append("teardown_deadline_exceeded")
        if report.get("post_activation_hook_seen") is True:
            with state.lock:
                final_trace = list(state.trace_rows)
                final_witnesses = list(state.witnesses)
            if final_trace != [{"event": event} for event in EXPECTED_TRACE]:
                cleanup_errors.append("trace_changed_during_teardown")
            if final_witnesses != ["positive"]:
                cleanup_errors.append("witness_changed_during_teardown")
        elif state.blocked_seen.is_set():
            cleanup_errors.append("blocked_witness_observed")
        if not owned_fixture(root, identity):
            cleanup_errors.append("fixture_identity_changed")
        report["retained_fixture"] = root.name
        report["teardown_complete"] = not cleanup_errors
        if cleanup_errors or state.failure:
            report["reason"] = state.failure or "teardown_failed"
            report["teardown_failures"] = cleanup_errors
    if measured(report):
        report["result"] = "MEASURED"
    return report


def measured(report: dict[str, object]) -> bool:
    """Success reproduces a measured limitation; it never grants authority."""
    retained = report.get("retained_fixture")
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
        and report.get("positive_witness_control") is True
        and report.get("blocked_witness_not_observed") is True
        and report.get("teardown_complete") is True
        and isinstance(retained, str)
        and re.fullmatch(r"v2-direct-shell-[A-Za-z0-9_-]+", retained) is not None
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
        report = run_probe(str(Path(binary).resolve()), args.temp_parent.absolute())
    except (ProbeFailure, OSError, ValueError, RuntimeError):
        report = {"result": "FAIL", "reason": "probe_preflight_failed"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("result") == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
