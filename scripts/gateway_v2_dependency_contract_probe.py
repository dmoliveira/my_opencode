"""Measure a native V2 shell boundary; never issue dependency authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import selectors
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = "opencode v2.2.5"
CASES = ("baseline", "nonzero", "late-tool", "late-shell", "late-after-error")
COMMANDS = {
    name: f"printf 'PROBE_{name.upper()}\\n' > witness; "
    + ("false" if name == "nonzero" else f"printf 'PROBE_{name.upper()}\\n'")
    for name in ("baseline", "nonzero", "tool", "shell")
}
MAX_OUTPUT = 128 * 1024
MAX_REQUEST = 1024 * 1024
MAX_TRACE = 64 * 1024
MAX_ROWS = 64
MAX_REQUESTS = 8
TIMEOUT = 60
CALL_ID = "call_boundary_probe"
MANAGERS = ("npm", "npx", "pnpm", "yarn", "bun", "bunx", "uv", "pip", "pip3")


class ProbeFailure(Exception):
    """A finite, public-safe reason code; never include native error text."""


def preflight(parent: Path) -> None:
    """Reject discovered configuration rather than suppressing managed policy."""
    if not parent.is_dir() or parent.is_symlink():
        raise ProbeFailure("temporary_parent_unavailable")
    for ancestor in (parent, *parent.parents):
        for name in ("opencode.json", "opencode.jsonc", ".opencode"):
            path = ancestor / name
            if path.exists() or path.is_symlink():
                raise ProbeFailure("ancestor_configuration_present")
    username = pwd.getpwuid(os.getuid()).pw_name
    system_paths = (
        Path("/etc/opencode"),
        Path("/Library/Application Support/opencode"),
        Path("/Library/Managed Preferences/ai.opencode.managed.plist"),
        Path("/Library/Managed Preferences") / username / "ai.opencode.managed.plist",
    )
    if any(path.exists() or path.is_symlink() for path in system_paths):
        raise ProbeFailure("system_configuration_present")


def child_env(root: Path) -> dict[str, str]:
    """Do not inherit credentials, service/session/DB overrides or loader paths."""
    home = root / "home"
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "TMPDIR": str(root / "tmp"),
        "OPENCODE_DB": str(root / "runtime.sqlite"),
        "PATH": f"{root / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
        "SHELL": "/bin/sh",
        "LANG": "en_US.UTF-8",
        "CI": "true",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_EDITOR": "true",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
    }


def write_fixture(root: Path, relative: str, text: str, *, executable: bool = False) -> None:
    """All provisioned files belong to this fresh, private temporary root."""
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ProbeFailure("fixture_path_outside_root")
    if root.is_symlink() or path.exists() or path.is_symlink():
        raise ProbeFailure("fixture_path_not_fresh")
    for ancestor in path.parents:
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ProbeFailure("fixture_parent_is_symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o700 if executable else 0o600)


@contextmanager
def owned_fixture(parent: Path):
    root = Path(tempfile.mkdtemp(prefix="v2-boundary-", dir=parent))
    identity = root.lstat()
    try:
        yield root
    finally:
        current = root.lstat()
        if not stat.S_ISDIR(current.st_mode) or (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
            # Preserve unexpected replacement state; never delete through it.
            raise ProbeFailure("fixture_identity_changed")
        shutil.rmtree(root)


def darwin_zombie_group(pid: int) -> bool:
    """XNU reports EPERM for an existing group with only zombie members."""
    if sys.platform != "darwin":
        return False
    # The caller still owns an unreaped leader. Require its zombie state in the
    # complete group snapshot; os.waitid is absent in some macOS Python builds.
    snapshot = subprocess.run(
        ["/bin/ps", "-x", "-g", str(pid), "-o", "pid=,pgid=,state="],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=2, check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    if snapshot.returncode != 0 or len(snapshot.stdout) > MAX_OUTPUT:
        return False
    rows = [line.split() for line in snapshot.stdout.decode("ascii").splitlines()]
    return bool(rows) and all(
        len(row) == 3 and row[1] == str(pid) and row[2].startswith("Z") for row in rows
    ) and any(row[0] == str(pid) for row in rows)


def stop_group(process: subprocess.Popen[bytes]) -> None:
    # Do not reap before signalling: the unreaped leader reserves the group ID.
    try:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                if not darwin_zombie_group(process.pid):
                    raise ProbeFailure("owned_group_signal_denied") from None
            if sig == signal.SIGTERM:
                threading.Event().wait(0.15)
    finally:
        process.wait(timeout=5)


def run_child(command: list[str], project: Path, env: dict[str, str], *, timeout: float = TIMEOUT) -> tuple[int, bytes, bytes]:
    """Bound both pipes, kill only the owned group, and always reap it."""
    process = subprocess.Popen(
        command, cwd=project, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    streams = (process.stdout, process.stderr)
    output = [bytearray(), bytearray()]
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for index, stream in enumerate(streams):
                assert stream is not None
                selector.register(stream, selectors.EVENT_READ, index)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeFailure("child_timeout")
                for key, _ in selector.select(min(remaining, 0.2)):
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    output[key.data].extend(data)
                    if len(output[key.data]) > MAX_OUTPUT:
                        raise ProbeFailure("child_output_limit")
            # EOF is not process completion. Keep the leader unreaped until cleanup.
    finally:
        try:
            stop_group(process)
        finally:
            for stream in streams:
                if stream is not None:
                    stream.close()
    return process.returncode, bytes(output[0]), bytes(output[1])


def schema_summary(schema: Any, depth: int = 0) -> Any:
    """Keep the native structural schema, not descriptions or arbitrary values."""
    if depth > 12:
        raise ProbeFailure("schema_depth_limit")
    if not isinstance(schema, dict):
        raise ProbeFailure("invalid_shell_schema")
    result = {}
    for key in ("type", "required", "additionalProperties", "enum"):
        if key in schema:
            result[key] = schema[key]
    if "properties" in schema:
        result["properties"] = {
            key: schema_summary(value, depth + 1)
            for key, value in schema["properties"].items()
        }
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            result[key] = [schema_summary(value, depth + 1) for value in schema[key]]
    if "items" in schema:
        result["items"] = schema_summary(schema["items"], depth + 1)
    return result


def native_input(schema: dict[str, Any], command: str, project: Path) -> dict[str, Any]:
    properties = schema.get("properties", {})
    if properties.get("command", {}).get("type") != "string":
        raise ProbeFailure("native_shell_command_schema_missing")
    values = {"command": command, "workdir": str(project), "description": "Synthetic boundary observation", "background": False}
    if set(schema.get("required", [])) - values.keys():
        raise ProbeFailure("unsupported_native_shell_required_fields")
    return {key: value for key, value in values.items() if key in properties}


@dataclass
class ProviderState:
    project: Path
    command: str
    requests: int = 0
    dispatched: int = 0
    continued: bool = False
    schema: dict[str, Any] | None = None
    schema_sha256: str | None = None
    tool_outcome: dict[str, Any] | None = None
    failure: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def response(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        with self.lock:
            self.requests += 1
            if self.requests > MAX_REQUESTS:
                raise ProbeFailure("provider_request_limit")
            messages = payload.get("messages", [])
            replies = [item for item in messages if item.get("role") == "tool"]
            if replies:
                if len(replies) != 1 or replies[0].get("tool_call_id") != CALL_ID or self.dispatched != 1:
                    raise ProbeFailure("provider_tool_correlation_failed")
                content = json.dumps(replies[0].get("content"))
                self.tool_outcome = {
                    "call_id": CALL_ID,
                    "content_type": type(replies[0].get("content")).__name__,
                    "baseline_marker": "PROBE_BASELINE" in content,
                    "late_error_marker": "PROBE_LATE_AFTER_ERROR" in content,
                }
                self.continued = True
            if self.continued:
                return {"role": "assistant", "content": "PROBE_FINISHED"}, "stop"
            # Auxiliary requests are not invited by this fixture.
            if self.dispatched:
                raise ProbeFailure("unexpected_provider_request")
            shell = [item["function"] for item in payload.get("tools", []) if item.get("function", {}).get("name") == "shell"]
            if len(shell) != 1:
                raise ProbeFailure("native_shell_not_exposed")
            raw_schema = shell[0].get("parameters")
            self.schema = schema_summary(raw_schema)
            self.schema_sha256 = hashlib.sha256(json.dumps(raw_schema, sort_keys=True).encode()).hexdigest()
            arguments = native_input(self.schema, self.command, self.project)
            self.dispatched += 1
            return {
                "role": "assistant", "tool_calls": [{
                    "index": 0, "id": CALL_ID, "type": "function",
                    "function": {"name": "shell", "arguments": json.dumps(arguments)},
                }],
            }, "tool_calls"


class BoundedProvider(ThreadingHTTPServer):
    daemon_threads = False
    request_queue_size = 4

    def __init__(self, state: ProviderState):
        self.state = state
        self.admitted: list[socket.socket] = []
        self.admissions = 0
        super().__init__(("127.0.0.1", 0), ProviderHandler)

    def verify_request(self, request: socket.socket, client_address: Any) -> bool:
        self.admissions += 1
        request.settimeout(2)
        if self.admissions > MAX_REQUESTS:
            self.state.failure = "provider_connection_limit"
            return False
        self.admitted.append(request)
        return True

    def close_connections(self) -> None:
        # Unblock partial headers/bodies before server_close joins workers.
        for connection in self.admitted:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def handle_error(self, request: Any, client_address: Any) -> None:
        self.state.failure = self.state.failure or "provider_handler_error"


class ProviderHandler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(2)

    def log_message(self, format: str, *args: object) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self.server.state.failure = self.server.state.failure or "provider_http_error"  # type: ignore[attr-defined]
        super().send_error(code, message, explain)

    def do_POST(self) -> None:
        state: ProviderState = self.server.state  # type: ignore[attr-defined]
        try:
            if self.path != "/v1/chat/completions":
                raise ProbeFailure("unexpected_provider_path")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST:
                raise ProbeFailure("provider_request_size")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ProbeFailure("provider_request_incomplete")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("model") != "mock":
                raise ProbeFailure("unexpected_provider_payload")
            delta, reason = state.response(payload)
            chunks = [{
                "id": "chatcmpl-boundary", "object": "chat.completion.chunk",
                "created": 1, "model": "mock",
                "choices": [{"index": 0, "delta": value, "finish_reason": finish}],
            } for value, finish in ((delta, None), ({}, reason))]
            body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (ProbeFailure, ValueError, KeyError, TypeError, OSError) as error:
            state.failure = str(error) if isinstance(error, ProbeFailure) else "provider_protocol_error"
            self.send_error(400)


# These plugins observe documented hooks only. They never wrap/replace execute.
COMMON_PLUGIN = r'''
import { Plugin } from "@opencode/plugin"
import { appendFileSync, existsSync, readFileSync } from "node:fs"
const settings = SETTINGS
const known = Object.entries(settings.commands)
const label = command => known.find(([, value]) => value === command)?.[0] ?? "unknown"
const keys = value => value && typeof value === "object" ? Object.keys(value).sort().slice(0, 48) : []
const shape = (value, depth = 0) => {
  if (value === null) return "null"
  if (typeof value !== "object") return typeof value
  if (depth >= 3) return Array.isArray(value) ? "array" : "object"
  return Object.fromEntries(keys(value).map(key => [key, shape(value[key], depth + 1)]))
}
const exits = (value, path = "result", depth = 0) => {
  if (!value || typeof value !== "object" || depth > 3) return []
  return keys(value).flatMap(key => {
    const item = value[key], next = `${path}.${key}`
    return /exit/i.test(key) && typeof item === "number" && Number.isFinite(item)
      ? [{ path: next, value: item }] : exits(item, next, depth + 1)
  })
}
let rows = 0
const emit = row => {
  if (++rows > 32 || (existsSync(settings.trace) && readFileSync(settings.trace).length > 60000)) throw new Error("PROBE_TRACE_LIMIT")
  appendFileSync(settings.trace, JSON.stringify(row) + "\n", { mode: 0o600 })
}
const identity = event => Object.fromEntries(["sessionID", "messageID", "id", "agent", "tool"].map(key => [key,
  typeof event[key] === "string" && /^[a-zA-Z0-9_.-]{1,160}$/.test(event[key]) ? event[key] : null]))
'''

OBSERVER_PLUGIN = COMMON_PLUGIN + r'''
export default Plugin.define({ id: "boundary-observer", async setup(ctx) {
  emit({ phase: "observer.setup", version: ctx.app.version })
  await ctx.tool.transform(editor => {
    const shell = editor.get("shell")
    emit({ phase: "native.definition", present: !!shell, id: shell?.id, name: shell?.name, shape: shape(shell), executeType: typeof shell?.execute })
  })
  await ctx.session.hook("title", event => { event.result = "Synthetic boundary probe" })
  await ctx.tool.hook("execute.before", async event => {
    if (event.tool !== "shell") throw new Error("PROBE_UNEXPECTED_TOOL")
    const session = await ctx.session.get({ sessionID: event.sessionID })
    emit({ phase: "observer.before", keys: keys(event), identity: identity(event), command: label(event.input?.command), directoryMatches: session.location.directory === settings.project })
  })
  await ctx.shell.hook("create.before", event => {
    emit({ phase: "observer.shell", keys: keys(event), command: label(event.command), directoryMatches: event.cwd === settings.project, shellMatches: event.shell === "/bin/sh" })
  })
  await ctx.tool.hook("execute.after", event => {
    emit({ phase: "observer.after", keys: keys(event), identity: identity(event), status: event.status, command: label(event.input?.command),
      shape: shape(event.status === "completed" ? event.result : event.error), exits: exits(event.result) })
  })
} })
'''

LATE_PLUGIN = COMMON_PLUGIN + r'''
export default Plugin.define({ id: "boundary-late", async setup(ctx) {
  emit({ phase: "late.setup" })
  await ctx.tool.hook("execute.before", event => {
    if (settings.case === "late-tool") event.input.command = settings.commands.tool
    emit({ phase: "late.before", command: label(event.input?.command) })
  })
  await ctx.shell.hook("create.before", event => {
    if (settings.case === "late-shell") event.command = settings.commands.shell
    emit({ phase: "late.shell", command: label(event.command) })
    // Fixture safety allowlist, NOT a production authorization boundary.
    if (label(event.command) === "unknown" || event.cwd !== settings.project || event.shell !== "/bin/sh") throw new Error("PROBE_FIXTURE_COMMAND_REJECTED")
    event.timeout = Math.min(event.timeout, 10000)
  })
  await ctx.tool.hook("execute.after", event => {
    emit({ phase: "late.after", status: event.status })
    if (settings.case === "late-after-error" && event.status === "completed") {
      emit({ phase: "late.throw" })
      throw new Error("PROBE_LATE_AFTER_ERROR")
    }
  })
} })
'''


def fixture_config(project: Path, port: int) -> dict[str, Any]:
    rules = [
        {"action": "*", "resource": "*", "effect": "deny"},
        {"action": "shell", "resource": "printf *", "effect": "allow"},
        {"action": "shell", "resource": "false", "effect": "allow"},
    ]
    return {
        "$schema": "https://opencode.ai/config.json", "model": "boundary/mock",
        "default_agent": "build", "shell": "/bin/sh", "snapshots": False,
        "formatter": False, "permissions": rules,
        "agents": {"build": {"permissions": rules}},
        "plugins": [str(project / "observer"), str(project / "late")],
        "providers": {"boundary": {
            "name": "Local synthetic boundary provider",
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "synthetic-only"},
            "models": {"mock": {"name": "mock", "capabilities": {"tools": True}}},
        }},
    }


def read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_TRACE:
        raise ProbeFailure("trace_missing_or_oversized")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if len(rows) > MAX_ROWS or any(not isinstance(row, dict) for row in rows):
        raise ProbeFailure("trace_rows_invalid")
    return rows


def assess(case: str, rows: list[dict[str, Any]], witness: str | None, state: ProviderState, returncode: int, finished: bool) -> dict[str, Any]:
    phases = [row.get("phase") for row in rows]
    required = ("observer.setup", "late.setup", "native.definition", "observer.before", "late.before", "observer.shell", "late.shell", "observer.after", "late.after")
    if any(phase not in phases for phase in required):
        raise ProbeFailure("required_observation_missing")
    before = next(row for row in rows if row["phase"] == "observer.before")
    definition = next(row for row in rows if row["phase"] == "native.definition")
    if not definition.get("present") or definition.get("executeType") != "function" or definition.get("id") != "shell" or definition.get("name") != "shell" or not isinstance(definition.get("shape"), dict) or definition["shape"].get("execute") != "function":
        raise ProbeFailure("native_shell_definition_unidentified")
    identity = before.get("identity", {})
    if not before.get("directoryMatches") or identity.get("id") != CALL_ID or identity.get("tool") != "shell" or not all(identity.get(key) for key in ("sessionID", "messageID", "agent")) or not {"input", *identity}.issubset(before.get("keys", [])):
        raise ProbeFailure("native_before_identity_missing")
    if any(phases.count(phase) != 1 for phase in ("observer.setup", "late.setup", "observer.before", "late.before", "observer.shell", "late.shell")):
        raise ProbeFailure("fixture_observation_count_mismatch")
    if next(row for row in rows if row["phase"] == "observer.setup").get("version") != "2.2.5":
        raise ProbeFailure("fixture_host_version_mismatch")
    if phases.index("observer.before") >= phases.index("late.before") or phases.index("observer.shell") >= phases.index("late.shell"):
        raise ProbeFailure("fixture_hook_order_mismatch")
    if not phases.index("late.before") < phases.index("observer.shell") < phases.index("late.shell") < phases.index("observer.after"):
        raise ProbeFailure("fixture_hook_order_mismatch")
    initial = "nonzero" if case == "nonzero" else "baseline"
    expected_commands = {
        "observer.before": initial,
        "late.before": "tool" if case == "late-tool" else initial,
        "observer.shell": "tool" if case == "late-tool" else initial,
        "late.shell": "shell" if case == "late-shell" else "tool" if case == "late-tool" else initial,
    }
    for phase, command in expected_commands.items():
        row = next(row for row in rows if row["phase"] == phase)
        if row.get("command") != command:
            raise ProbeFailure("command_observation_mismatch")
        if phase == "observer.shell" and (not row.get("directoryMatches") or not row.get("shellMatches") or not {"command", "cwd", "shell", "timeout", "env"}.issubset(row.get("keys", []))):
            raise ProbeFailure("shell_observation_mismatch")
    for row in (row for row in rows if row["phase"] == "observer.after"):
        if row.get("status") not in ("completed", "error") or "shape" not in row or row["shape"] == "undefined" or not isinstance(row.get("keys"), list) or "status" not in row["keys"] or not isinstance(row.get("exits"), list) or not isinstance(row.get("identity"), dict) or set(row["identity"]) != set(identity):
            raise ProbeFailure("after_observation_incomplete")
        for key, value in row.get("identity", {}).items():
            if value is not None and value != identity.get(key):
                raise ProbeFailure("after_identity_mismatch")
    if any(row.get("status") not in ("completed", "error") for row in rows if row["phase"] == "late.after"):
        raise ProbeFailure("late_after_observation_incomplete")
    expected = {"late-tool": "tool", "late-shell": "shell", "nonzero": "nonzero"}.get(case, "baseline")
    if witness != f"PROBE_{expected.upper()}\n":
        raise ProbeFailure("native_witness_mismatch")
    if state.failure or state.dispatched != 1 or not state.continued or not state.schema or not state.tool_outcome or state.tool_outcome.get("call_id") != CALL_ID or not {"content_type", "baseline_marker", "late_error_marker"}.issubset(state.tool_outcome) or not finished or returncode != 0:
        raise ProbeFailure(state.failure or "native_run_incomplete")
    if case == "late-after-error" and (phases.count("late.throw") != 1 or phases.index("observer.after") >= phases.index("late.throw")):
        raise ProbeFailure("late_error_not_exercised")
    return {
        "case": case, "measurement": "PASS", "witness": expected,
        "provider_requests": state.requests, "returncode": returncode,
        "consumer_tool_outcome": state.tool_outcome,
        "native_schema": state.schema, "native_schema_sha256": state.schema_sha256,
        "observations": rows,
    }


def run_case(root: Path, case: str, binary: str) -> dict[str, Any]:
    project = root / "project"
    trace = root / "trace.jsonl"
    command = COMMANDS["nonzero" if case == "nonzero" else "baseline"]
    state = ProviderState(project, command)
    server = BoundedProvider(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    evidence: dict[str, Any] = {"case": case, "measurement": "FAIL"}
    try:
        settings = json.dumps({"project": str(project), "trace": str(trace), "commands": COMMANDS, "case": case})
        write_fixture(root, "project/observer/index.ts", OBSERVER_PLUGIN.replace("SETTINGS", settings))
        write_fixture(root, "project/late/index.ts", LATE_PLUGIN.replace("SETTINGS", settings))
        write_fixture(root, "project/opencode.json", json.dumps(fixture_config(project, server.server_port)))
        write_fixture(root, "home/.config/opencode/opencode.json", json.dumps({"$schema": "https://opencode.ai/config.json", "update": "disable"}))
        write_fixture(root, "tmp/.owned", "synthetic\n")
        for manager in MANAGERS:
            write_fixture(root, f"bin/{manager}", f"#!/bin/sh\nprintf 'INSTALLER_REQUESTED\\n' >> {shlex.quote(str(root / 'installer-requested'))}\nexit 97\n", executable=True)
        env = child_env(root)
        code, stdout, stderr = run_child([binary, "run", "--standalone", "--model", "boundary/mock", "--title", "Synthetic boundary probe", "Measure the single synthetic shell call."], project, env)
        evidence.update({"returncode": code, "stdout_bytes": len(stdout), "stderr_bytes": len(stderr), "provider_requests": state.requests})
        if (root / "installer-requested").exists():
            raise ProbeFailure("installer_requested")
        rows = read_trace(trace)
        evidence["observations"] = rows
        witness = project / "witness"
        observed = witness.read_text() if witness.is_file() and witness.stat().st_size < 128 else None
        return assess(case, rows, observed, state, code, b"PROBE_FINISHED" in stdout)
    except ProbeFailure as error:
        evidence["reason"] = str(error)
        return evidence
    finally:
        server.shutdown()
        server.close_connections()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise ProbeFailure("provider_cleanup_failed")


def probe(binary: str, parent: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1, "result": "FAIL", "authority": "disabled-unqualified",
        "meaning": "measurement only; not an authorization or installation receipt",
        "unproven": ["terminal immutable binding", "authoritative raw numeric exit", "exactly-once observation", "later-error revocation", "cancellation", "compaction", "session deletion", "plugin unload", "captured executor snapshots"],
        "cases": [],
    }
    try:
        preflight(parent)
        with owned_fixture(parent) as root:
            code, stdout, _ = run_child([binary, "--version"], root, child_env(root), timeout=10)
            if code != 0 or stdout.decode().strip() != VERSION:
                raise ProbeFailure("unsupported_host_version")
        report["host"] = VERSION
        for case in CASES:
            with owned_fixture(parent) as root:
                observed = run_case(root, case, binary)
                report["cases"].append(observed)
                if observed["measurement"] != "PASS":
                    raise ProbeFailure(observed["reason"])
        report["result"] = "PASS"
    except (ProbeFailure, OSError, ValueError, subprocess.SubprocessError) as error:
        report["reason"] = str(error) if isinstance(error, ProbeFailure) else "probe_internal_error"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode-bin", default="opencode")
    temporary = Path(tempfile.gettempdir())
    preferred = temporary / "opencode"
    parser.add_argument("--temp-parent", type=Path, default=preferred if preferred.is_dir() else temporary)
    args = parser.parse_args()
    binary = shutil.which(args.opencode_bin)
    if not binary or os.name != "posix":
        parser.error("an installed POSIX OpenCode 2.2.5 host is required")
    report = probe(str(Path(binary).resolve()), args.temp_parent.resolve())
    print(json.dumps(report, sort_keys=True))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
