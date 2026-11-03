"""Denial-only qualification of an isolated native V2 profile, never authority."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
import re
import secrets
import selectors
import shlex
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from gateway_v2_dependency_contract_probe import (
    MANAGERS,
    MAX_OUTPUT,
    ProbeFailure,
    child_env,
    native_input,
    preflight,
    run_child,
    schema_summary,
    stop_group,
    write_fixture,
)

AUTHORITY = "disabled-unqualified"
SOURCE_COMMIT = "9bbb8ce18c80f099e0e448775f59d965ead40a21"
ARCHIVE_SHA256 = "25ba9908979fa7d764792c82589b4b5768ab1511154e0317d98aa77d216ce767"
CASES = (
    "baseline", "rogue-blocked", "rogue-unrestricted-control", "owned-missing",
    "owned-failed", "topology-change", "permission-after-shell", "bind-cwd",
    "bind-executable", "bind-env", "after-critical", "after-tolerated",
    "after-rejection", "after-interrupted", "captured-dispose", "captured-reload",
    "running-dispose", "stale-completion-reuse",
)
PREDISPATCH = {"rogue-blocked", "rogue-unrestricted-control", "owned-missing", "owned-failed", "topology-change"}
CAPTURED = {"captured-dispose", "captured-reload"}
PAUSED_AFTER = {"after-interrupted", "running-dispose", "stale-completion-reuse"}
PRIMARY_SECONDS = 50
CLEANUP_SECONDS = 10
MAX_REQUEST = 1024 * 1024
MAX_CONNECTIONS = 16
MAX_TRACE = 128 * 1024
MAX_ROWS = 128
CALL_ID = "call_profile_probe"
REUSE_ID = "call_profile_probe_reuse"
BASELINE = "printf PROFILE_BASELINE > witness; printf PROFILE_BASELINE"
CHANGED = "printf PROFILE_CHANGED > witness; printf PROFILE_CHANGED"
REUSE = "printf PROFILE_REUSE > reuse-witness; printf PROFILE_REUSE"


@dataclass
class Barrier:
    arrived: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)
    value: str = "continue"

    def hold(self, deadline: float, stopped: threading.Event) -> str:
        self.arrived.set()
        if not self.released.wait(max(0, min(10, deadline - time.monotonic()))):
            raise ProbeFailure("barrier_timeout")
        if stopped.is_set():
            raise ProbeFailure("controller_stopped")
        return self.value

    def release(self, value: str = "continue") -> None:
        self.value = value
        self.released.set()


@dataclass
class ProfileState:
    case: str
    root: Path
    deadline: float
    control_key: str = field(default_factory=lambda: secrets.token_hex(24))
    lock: threading.Lock = field(default_factory=threading.Lock)
    stopped: threading.Event = field(default_factory=threading.Event)
    model: Barrier = field(default_factory=Barrier)
    callback: Barrier = field(default_factory=Barrier)
    control: Barrier = field(default_factory=Barrier)
    failure: str | None = None
    requests: int = 0
    dispatched: int = 0
    continued: bool = False
    schema: dict[str, Any] | None = None
    consumer: dict[str, Any] | None = None
    controller_notes: list[str] = field(default_factory=list)
    handlers: int = 0
    expected_callback_disconnect: bool = False
    reuse_started: bool = False
    reuse_continued: bool = False
    reuse_consumer: dict[str, Any] | None = None

    def stop(self) -> None:
        self.stopped.set()
        for barrier in (self.model, self.callback, self.control):
            barrier.release("stop")

    def answer(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        with self.lock:
            self.requests += 1
            if self.requests > MAX_CONNECTIONS:
                raise ProbeFailure("provider_request_limit")
            replies = [item for item in payload.get("messages", []) if item.get("role") == "tool"]
            call_id = REUSE_ID if self.reuse_started else CALL_ID
            attempt = 2 if self.reuse_started else 1
            allowed_ids = {CALL_ID, REUSE_ID} if self.reuse_started else {CALL_ID}
            if any(item.get("tool_call_id") not in allowed_ids for item in replies):
                raise ProbeFailure("tool_correlation_failed")
            current_replies = [item for item in replies if item.get("tool_call_id") == call_id]
            if current_replies:
                if len(current_replies) != 1 or self.dispatched != attempt:
                    raise ProbeFailure("tool_correlation_failed")
                content = json.dumps(current_replies[0].get("content"))
                consumer = {
                    "baseline": "PROFILE_BASELINE" in content,
                    "changed": "PROFILE_CHANGED" in content,
                    "closed": "PROFILE_CLOSED" in content,
                    "owned_error": "PROFILE_OWNED" in content,
                    "reuse": "PROFILE_REUSE" in content,
                }
                if self.reuse_started:
                    self.reuse_consumer, self.reuse_continued = consumer, True
                else:
                    self.consumer, self.continued = consumer, True
                return {"role": "assistant", "content": "PROFILE_FINISHED"}, "stop"
            if self.dispatched != attempt - 1:
                raise ProbeFailure("unexpected_provider_request")
            tools = [item["function"] for item in payload.get("tools", []) if item.get("function", {}).get("name") == "shell"]
            if len(tools) != 1:
                raise ProbeFailure("native_shell_missing")
            schema = schema_summary(tools[0].get("parameters"))
            if self.schema and schema != self.schema:
                raise ProbeFailure("native_schema_changed")
            self.schema = schema
            arguments = native_input(self.schema, REUSE if self.reuse_started else BASELINE, self.root / "project")
            self.dispatched += 1
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": call_id, "type": "function", "function": {"name": "shell", "arguments": json.dumps(arguments)}}]}
        # A real request/tool snapshot is held, never a fabricated executor call.
        if self.case in CAPTURED:
            self.model.hold(self.deadline, self.stopped)
        return delta, "tool_calls"


class ProfileProvider(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 4

    def __init__(self, state: ProfileState):
        self.state = state
        self.admitted: list[socket.socket] = []
        self.admissions = 0
        self.workers: list[threading.Thread] = []
        super().__init__(("127.0.0.1", 0), ProfileHandler)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        worker = threading.Thread(target=self.process_request_thread, args=(request, client_address), daemon=True)
        worker.start()
        self.workers.append(worker)

    def verify_request(self, request: socket.socket, client_address: Any) -> bool:
        if self.state.stopped.is_set():
            return False
        self.admissions += 1
        request.settimeout(2)
        if self.admissions > MAX_CONNECTIONS:
            self.state.failure = "provider_connection_limit"
            return False
        self.admitted.append(request)
        return True

    def close_connections(self) -> None:
        for connection in self.admitted:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def handle_error(self, request: Any, client_address: Any) -> None:
        if not self.state.stopped.is_set():
            self.state.failure = self.state.failure or "provider_handler_error"


class ProfileHandler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(2)

    def log_message(self, format: str, *args: object) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        state: ProfileState = self.server.state  # type: ignore[attr-defined]
        if not state.stopped.is_set():
            state.failure = state.failure or "provider_http_error"
        super().send_error(code, message, explain)

    def started(self) -> ProfileState:
        state: ProfileState = self.server.state  # type: ignore[attr-defined]
        with state.lock:
            state.handlers += 1
        return state

    def reply(self, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        state = self.started()
        try:
            if self.headers.get("Authorization") != f"Bearer {state.control_key}":
                raise ProbeFailure("control_authentication_failed")
            barriers = {"/callback": state.callback, "/control": state.control}
            if self.path not in barriers:
                raise ProbeFailure("unexpected_control_path")
            value = barriers[self.path].hold(state.deadline, state.stopped)
            self.reply(json.dumps({"command": value}).encode())
        except ProbeFailure as error:
            if not (state.stopped.is_set() and str(error) == "controller_stopped"):
                state.failure = state.failure or str(error)
        except OSError:
            expected = state.expected_callback_disconnect and self.path == "/callback"
            if not state.stopped.is_set() and not expected:
                state.failure = "control_protocol_error"

    def do_POST(self) -> None:
        state = self.started()
        try:
            if self.path != "/v1/chat/completions":
                raise ProbeFailure("unexpected_provider_path")
            if self.headers.get("Authorization") != "Bearer synthetic-only":
                raise ProbeFailure("provider_authentication_failed")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST:
                raise ProbeFailure("provider_request_size")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ProbeFailure("provider_request_incomplete")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("model") != "mock":
                raise ProbeFailure("unexpected_provider_payload")
            delta, reason = state.answer(payload)
            chunks = [{"id": "chatcmpl-profile", "object": "chat.completion.chunk", "created": 1, "model": "mock", "choices": [{"index": 0, "delta": part, "finish_reason": finish}]} for part, finish in ((delta, None), ({}, reason))]
            body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
            self.reply(body, "text/event-stream")
        except (ProbeFailure, ValueError, TypeError, KeyError, OSError) as error:
            expected_stop = state.stopped.is_set() and (isinstance(error, OSError) or isinstance(error, ProbeFailure) and str(error) == "controller_stopped")
            if not expected_stop:
                state.failure = state.failure or (str(error) if isinstance(error, ProbeFailure) else "provider_protocol_error")


class PrivateRuntime:
    """Authenticated, PID-checked private server with continuously bounded pipes."""

    def __init__(self, binary: str, root: Path, deadline: float):
        self.root, self.deadline = root, deadline
        self.binary = binary
        self.process: subprocess.Popen[bytes] | None = None
        self.password = secrets.token_hex(24)
        self.authorization = "Basic " + base64.b64encode(f"opencode:{self.password}".encode()).decode()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.connections: list[http.client.HTTPConnection] = []
        self.sockets: list[socket.socket] = []
        self.connection_lock = threading.Lock()
        self.cancelled = threading.Event()
        self.readers: list[threading.Thread] = []
        self.reader_stop = threading.Event()
        self.output = [bytearray(), bytearray()]
        self.fault: str | None = None
        self.verified = False
        self.api_count = 0

    def start(self) -> None:
        # The caller already owns this object, including the handle if a later
        # thread fails to start. Never spawn inside a fallible constructor.
        env = child_env(self.root)
        env["OPENCODE_PASSWORD"] = self.password
        self.process = subprocess.Popen(
            [self.binary, "serve", "--hostname", "127.0.0.1", "--port", str(self.port)],
            cwd=self.root / "project", env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        for index, stream in enumerate((self.process.stdout, self.process.stderr)):
            assert stream is not None
            reader = threading.Thread(target=self._read, args=(stream, index), daemon=True)
            reader.start()
            self.readers.append(reader)

    def _read(self, stream: Any, index: int) -> None:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(stream, selectors.EVENT_READ)
                while not self.reader_stop.is_set():
                    for _, _mask in selector.select(0.1):
                        data = os.read(stream.fileno(), 4096)
                        if not data:
                            return
                        remaining = MAX_OUTPUT - len(self.output[index])
                        self.output[index].extend(data[:max(0, remaining)])
                        if len(data) > remaining:
                            self.fault = "runtime_output_limit"
        except OSError:
            if not self.reader_stop.is_set():
                self.fault = "runtime_output_reader_error"

    def request(self, method: str, path: str, body: Any = None) -> Any:
        if method != "GET" and not self.verified:
            raise ProbeFailure("runtime_owner_unverified")
        if self.fault:
            raise ProbeFailure(self.fault)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self.cancelled.is_set():
            raise ProbeFailure("case_timeout")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=min(5, remaining))
        try:
            connection.connect()
            self.api_count += 1
            if self.api_count > 24:
                raise ProbeFailure("native_api_request_limit")
            with self.connection_lock:
                if self.cancelled.is_set():
                    raise ProbeFailure("case_timeout")
                self.connections.append(connection)
                assert connection.sock is not None
                self.sockets.append(connection.sock)
            encoded = None if body is None else json.dumps(body).encode()
            connection.request(method, path, encoded, {"Authorization": self.authorization, "Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(MAX_REQUEST + 1)
            if self.cancelled.is_set() or time.monotonic() >= self.deadline:
                raise ProbeFailure("case_timeout")
            if len(data) > MAX_REQUEST:
                raise ProbeFailure("native_api_response_limit")
            if response.status not in (200, 204):
                raise ProbeFailure(f"native_api_status_{response.status}")
            return json.loads(data) if data else None
        finally:
            connection.close()

    def verify_owner(self) -> None:
        if self.process is None:
            raise ProbeFailure("runtime_not_started")
        info = self.request("GET", "/api/info")
        if not isinstance(info, dict) or info.get("pid") != self.process.pid:
            raise ProbeFailure("runtime_pid_mismatch")
        self.observed_pid = info["pid"]
        self.verified = True

    def mutate(self, method: str, path: str, body: Any = None) -> Any:
        self.verify_owner()
        return self.request(method, path, body)

    def ready(self) -> None:
        deadline = min(self.deadline, time.monotonic() + 10)
        for _attempt in range(32):
            if time.monotonic() >= deadline:
                break
            try:
                self.verify_owner()
                return
            except ProbeFailure as error:
                # The pinned server listens during database bootstrap. Only
                # this readiness GET may retry 503; activation/control errors
                # and authentication/PID mismatches remain fatal.
                if str(error) != "native_api_status_503":
                    raise
                threading.Event().wait(max(0, min(1, deadline - time.monotonic())))
            except (ConnectionError, OSError, http.client.HTTPException):
                threading.Event().wait(0.1)
        raise ProbeFailure("runtime_readiness_timeout")

    def close(self, deadline: float) -> None:
        self.abort_connections()
        try:
            if self.process is not None:
                stop_group(self.process)
        finally:
            # Drain to EOF after group settlement; stopping first could hide a
            # final output overflow that arrived after the last API response.
            for reader in self.readers:
                reader.join(max(0, min(1, deadline - time.monotonic())))
            self.reader_stop.set()
            for reader in self.readers:
                reader.join(max(0, deadline - time.monotonic()))
            streams = (self.process.stdout, self.process.stderr) if self.process is not None else ()
            for stream in streams:
                if stream is not None:
                    stream.close()
        if any(reader.is_alive() for reader in self.readers):
            raise ProbeFailure("runtime_reader_cleanup_failed")
        if self.fault:
            raise ProbeFailure(self.fault)

    def abort_connections(self) -> None:
        self.cancelled.set()
        with self.connection_lock:
            for connection in self.sockets:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            for connection in self.connections:
                connection.close()


PLUGIN = r'''
import { Plugin } from "@opencode/plugin/effect"
import { Error as ToolError } from "@opencode/plugin/promise/tool"
import { Effect, Exit } from "effect"
import { appendFileSync, existsSync, readFileSync } from "node:fs"
import { randomUUID } from "node:crypto"
const s = SETTINGS
export default Plugin.define({ id: "profile-owned", effect: ctx => Effect.gen(function* () {
const owner = { id: randomUUID(), live: true, epoch: 1 }
const pending = new Map()
let sequence = 0
const emit = data => {
  if (++sequence > 100 || (existsSync(s.trace) && readFileSync(s.trace).length > 120000)) throw new Error("PROFILE_TRACE_LIMIT")
  appendFileSync(s.trace, JSON.stringify({ ...data, owner: owner.id, epoch: owner.epoch }) + "\n", { mode: 0o600 })
}
const identity = event => Object.fromEntries(["sessionID", "messageID", "id", "agent"].map(key => [key, typeof event[key] === "string" && /^[a-zA-Z0-9_.-]{1,160}$/.test(event[key]) ? event[key] : null]))
const label = command => command === s.baseline ? "baseline" : command === s.changed ? "changed" : "unknown"
const pause = path => Effect.promise(async signal => {
  const response = await fetch(s.control + path, { headers: { Authorization: "Bearer " + s.controlKey }, signal })
  if (!response.ok) throw new Error("PROFILE_CONTROL_STATUS")
  return response.json()
})
const foreign = () => JSON.parse(readFileSync(s.foreign, "utf8")).id
const revoke = (context, why) => Effect.sync(() => {
  pending.delete(context.sessionID)
  emit({ phase: "revoked", identity: identity(context), why, targetPending: pending.has(context.sessionID), foreignPending: pending.has(foreign()), foreignSessionID: foreign() })
})
const closeOwner = why => {
  if (!owner.live) return
  owner.live = false
  owner.epoch++
  pending.clear()
  emit({ phase: "owner.closed", why, pendingCount: pending.size })
}
  emit({ phase: "setup", version: ctx.app.version })
  if (s.case === "owned-failed") {
    emit({ phase: "owned.failed" })
    yield* Effect.die(new Error("PROFILE_OWNED_FAILED"))
  }
  const registrations = []
  registrations.push(yield* ctx.tool.transform(editor => {
    const tool = editor.get("shell")
    if (!tool || typeof tool.execute !== "function") throw new Error("PROFILE_NATIVE_SHELL_MISSING")
    const execute = tool.execute
    editor.update("shell", draft => {
      draft.execute = (input, context) => Effect.suspend(() => {
        emit({ phase: "executor.entry", identity: identity(context), live: owner.live, command: label(input.command) })
        if (!owner.live) return Effect.fail(new ToolError({ message: "PROFILE_CLOSED" }))
        const epoch = owner.epoch
        pending.set(context.sessionID, { id: context.id, epoch })
        pending.set(foreign(), { foreign: true })
        return execute(input, context).pipe(
          Effect.tap(result => Effect.sync(() => {
            if (!owner.live || owner.epoch !== epoch) throw new Error("PROFILE_CLOSED")
            emit({ phase: "raw", identity: identity(context), exit: result.output?.exit ?? null, metadataExit: result.metadata?.exit ?? null })
          })),
          Effect.onExit(exit => Exit.isFailure(exit) ? revoke(context, "executor-failure") : Effect.void),
        )
      })
    })
    emit({ phase: "native.wrapped", name: tool.name, nativeID: tool.id, executeType: typeof execute })
  }))
  registrations.push(yield* ctx.session.hook("title", event => Effect.sync(() => { event.result = "Profile qualification" })))
  registrations.push(yield* ctx.tool.hook("execute.before", event => Effect.sync(() => {
    emit({ phase: "before", identity: identity(event), tool: event.tool, command: label(event.input?.command) })
    if (!owner.live || event.tool !== "shell" || label(event.input?.command) !== "baseline") throw new Error("PROFILE_CLOSED")
  })))
  let shellStart
  registrations.push(yield* ctx.shell.hook("create.before", event => Effect.sync(() => {
    shellStart = { command: event.command, cwd: event.cwd, shell: event.shell, env: JSON.stringify(Object.entries(event.env).sort()) }
    emit({ phase: "shell.entry", command: label(event.command), cwdMatches: event.cwd === s.project, shellMatches: event.shell === "/bin/sh" })
    if (s.case === "permission-after-shell") event.command = s.changed
    if (s.case === "bind-cwd") event.cwd = s.alternate
    if (s.case === "bind-executable") event.shell = "/bin/bash"
    if (s.case === "bind-env") event.env.PROFILE_SYNTHETIC = "changed"
  })))
  registrations.push(yield* ctx.shell.hook("create.before", event => Effect.sync(() => {
    const matches = { cwd: event.cwd === shellStart.cwd, shell: event.shell === shellStart.shell, env: JSON.stringify(Object.entries(event.env).sort()) === shellStart.env }
    emit({ phase: "shell.binding", command: label(event.command), matches })
    if (!owner.live || shellStart.cwd !== s.project || shellStart.shell !== "/bin/sh" || !Object.values(matches).every(Boolean) || ![s.baseline, s.changed].includes(event.command)) throw new Error("PROFILE_BINDING_REJECTED")
    event.timeout = Math.min(event.timeout, 10000)
  })))
  registrations.push(yield* ctx.permission.hook("evaluate", event => Effect.sync(() => {
    const resources = event.resources.map(value => value.includes("PROFILE_CHANGED") ? "changed" : value.includes("PROFILE_BASELINE") ? "baseline" : "other")
    emit({ phase: "permission", sessionID: event.sessionID, action: event.action, source: event.source ? { type: event.source.type, messageID: event.source.messageID, id: event.source.id } : null, resources })
    if (!owner.live || (s.case === "permission-after-shell" && resources.includes("changed"))) event.effect = "deny"
  })))
  registrations.push(yield* ctx.tool.hook("execute.after", event => {
    const epoch = owner.epoch
    const body = Effect.gen(function* () {
      emit({ phase: "after.entry", identity: identity(event), status: event.status, pending: pending.has(event.sessionID) })
      if (event.status !== "completed") { yield* revoke(event, "native-error"); return }
      if (s.case === "after-critical") yield* Effect.die(new Error("PROFILE_OWNED_CRITICAL"))
      if (s.case === "after-rejection" || s.case === "after-tolerated") {
        const failed = Effect.promise(() => Promise.reject(new Error("PROFILE_OWNED_REJECTION")))
        if (s.case === "after-tolerated") {
          yield* Effect.exit(failed)
          yield* revoke(event, "tolerated")
        } else yield* failed
      }
      if (["after-interrupted", "running-dispose", "stale-completion-reuse"].includes(s.case)) {
        emit({ phase: "after.suspended", identity: identity(event) })
        yield* pause("/callback")
      }
      if (!owner.live || owner.epoch !== epoch) {
        emit({ phase: "stale.rejected", identity: identity(event), pending: pending.has(event.sessionID) })
        yield* Effect.die(new Error("PROFILE_CLOSED"))
      }
      emit({ phase: "after.continue", identity: identity(event), pending: pending.has(event.sessionID), foreignPending: pending.has(foreign()) })
    })
    return body.pipe(Effect.onExit(exit => Exit.isFailure(exit) ? revoke(event, "owned-after-failure") : Effect.void))
  }))
  yield* pause("/control").pipe(
    Effect.flatMap(command => Effect.gen(function* () {
      if (command.command === "dispose") {
        closeOwner("explicit-disposal")
        for (const registration of registrations) yield* registration.dispose
        emit({ phase: "registrations.disposed" })
      }
    })),
    Effect.forkScoped,
  )
  yield* Effect.addFinalizer(() => Effect.sync(() => closeOwner("scope-finalizer")))
  emit({ phase: "ready" })
}) })
'''


def make_config(root: Path, port: int, case: str) -> dict[str, Any]:
    project = root / "project"
    plugins = [] if case == "owned-missing" else [str(project / "owned")]
    if case in ("rogue-blocked", "rogue-unrestricted-control"):
        plugins.append(str(project / "rogue"))
    rules = [{"action": "*", "resource": "*", "effect": "deny"}, {"action": "shell", "resource": "printf *", "effect": "allow"}]
    policies = [{"action": "provider.use", "resource": "*", "effect": "deny"}, {"action": "provider.use", "resource": "profile", "effect": "allow"}]
    if case != "rogue-unrestricted-control":
        policies.extend([{"action": "plugin.use", "resource": "*", "effect": "deny"}, {"action": "plugin.use", "resource": "opencode.*", "effect": "allow"}, {"action": "plugin.use", "resource": str(project / "owned"), "effect": "allow"}])
    return {
        "$schema": "https://opencode.ai/config.json", "model": "profile/mock", "shell": "/bin/sh",
        "snapshots": False, "formatter": False, "plugins": plugins, "policies": policies,
        "permissions": rules, "agents": {"build": {"permissions": rules}},
        "providers": {"profile": {"name": "Synthetic profile provider", "package": "@opencode/ai/providers/openai-compatible", "settings": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "synthetic-only", "timeout": 20000}, "models": {"mock": {"name": "mock", "capabilities": {"tools": True}}}}},
    }


def rewrite_config(root: Path, config: dict[str, Any]) -> None:
    target = root / "project/opencode.json"
    assert target.is_file() and not target.is_symlink() and target.stat().st_uid == os.getuid()
    write_fixture(root, "replacement-config.json", json.dumps(config))
    os.replace(root / "replacement-config.json", target)


def traces(root: Path) -> list[dict[str, Any]]:
    path = root / "trace.jsonl"
    if not path.exists():
        return []
    if path.is_symlink() or path.stat().st_size > MAX_TRACE:
        raise ProbeFailure("trace_size_or_identity")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if len(rows) > MAX_ROWS or any(not isinstance(row, dict) or not isinstance(row.get("phase"), str) for row in rows):
        raise ProbeFailure("trace_rows_invalid")
    return rows


def wait_until(predicate: Any, state: ProfileState, reason: str) -> None:
    deadline = min(state.deadline, time.monotonic() + 10)
    while time.monotonic() < deadline:
        if state.failure:
            raise ProbeFailure(state.failure)
        if predicate():
            return
        state.stopped.wait(0.025)
    raise ProbeFailure(reason)


def phase(root: Path, name: str) -> bool:
    return any(row["phase"] == name for row in traces(root))


def prepare_fixture(root: Path, state: ProfileState, port: int) -> dict[str, Any]:
    settings = {"case": state.case, "project": str(root / "project"), "alternate": str(root / "project/alternate"), "trace": str(root / "trace.jsonl"), "foreign": str(root / "foreign.json"), "control": f"http://127.0.0.1:{port}", "controlKey": state.control_key, "baseline": BASELINE, "changed": CHANGED}
    write_fixture(root, "project/owned/index.ts", PLUGIN.replace("SETTINGS", json.dumps(settings)))
    rogue = r'import {Plugin} from "@opencode/plugin"; import{appendFileSync}from"node:fs"; export default Plugin.define({id:"profile-rogue",setup(){appendFileSync(TRACE,JSON.stringify({phase:"rogue.setup"})+"\n",{mode:0o600})}})'
    rogue_source = rogue.replace("TRACE", json.dumps(str(root / "trace.jsonl")))
    write_fixture(root, "project/rogue/index.ts", rogue_source)
    write_fixture(root, "project/alternate/.owned", "synthetic\n")
    write_fixture(root, "tmp/.owned", "synthetic\n")
    write_fixture(root, "home/.config/opencode/opencode.json", json.dumps({"$schema": "https://opencode.ai/config.json", "update": "disable"}))
    config = make_config(root, port, state.case)
    write_fixture(root, "project/opencode.json", json.dumps(config))
    # A genuine foreign native session replaces this before any tool is admitted.
    write_fixture(root, "foreign.json", json.dumps({"id": "uninitialized-no-authority"}))
    for manager in (*MANAGERS, "corepack", "pnpx", "yarnpkg", "pipx", "uvx"):
        write_fixture(root, f"bin/{manager}", f"#!/bin/sh\nprintf 'INSTALLER_REQUESTED\\n' >> {shlex.quote(str(root / 'installer-requested'))}\nexit 97\n", executable=True)
    return config


def set_foreign(root: Path, session_id: str) -> None:
    path = root / "foreign.json"
    assert path.is_file() and not path.is_symlink()
    path.write_text(json.dumps({"id": session_id}))


def plugin_list(runtime: PrivateRuntime, root: Path) -> list[dict[str, Any]]:
    value = runtime.request("GET", "/api/plugin?" + urlencode({"location[directory]": str(root / "project")}))
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise ProbeFailure("native_plugin_response_invalid")
    return value["data"]


def native_id(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value) is None:
        raise ProbeFailure("native_identifier_invalid")
    return value


def native_outcome(value: Any) -> str:
    # Reject arbitrary native payloads before the control record is preserved.
    if not isinstance(value, str) or value not in ("succeeded", "failed", "interrupted"):
        raise ProbeFailure("native_outcome_invalid")
    return value


def terminal_tools(context: Any, session_id: str, call_id: str = CALL_ID) -> list[dict[str, Any]]:
    if not isinstance(context, dict) or not isinstance(context.get("data"), list):
        raise ProbeFailure("native_context_schema_invalid")
    tools = []
    for message in context["data"]:
        if not isinstance(message, dict) or message.get("type") != "assistant":
            continue
        for part in message.get("content", []):
            if isinstance(part, dict) and part.get("type") == "tool":
                allowed = {CALL_ID, REUSE_ID} if call_id == REUSE_ID else {CALL_ID}
                if part.get("id") not in allowed or part.get("name") != "shell" or part.get("state", {}).get("status") not in ("completed", "error"):
                    raise ProbeFailure("native_terminal_tool_invalid")
                if part["id"] == call_id:
                    tools.append({"sessionID": session_id, "messageID": native_id(message.get("id")), "id": part["id"], "name": part["name"], "status": part["state"]["status"]})
    if len(tools) != 1:
        raise ProbeFailure("native_terminal_tool_missing")
    return tools


def inventory(listing: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    result = []
    for item in listing:
        source, status = item.get("source", {}), item.get("state", {}).get("status")
        if source.get("type") not in ("builtin", "local") or status not in ("active", "failed"):
            raise ProbeFailure("unexpected_loader_source_or_status")
        kind = "builtin"
        if source["type"] == "local":
            path = Path(source.get("path", "")).resolve()
            kind = next((name for name in ("owned", "rogue") if path in (root / "project" / name, root / "project" / name / "index.ts")), "unexpected")
            if kind == "unexpected":
                raise ProbeFailure("unexpected_loader_source_or_status")
        plugin_id = item.get("id")
        if plugin_id is not None:
            plugin_id = native_id(plugin_id)
        if status == "active" and (not isinstance(plugin_id, str) or (kind in ("owned", "rogue") and plugin_id != f"profile-{kind}")):
            raise ProbeFailure("owned_plugin_source_mismatch")
        result.append({"id": plugin_id, "source": kind, "status": status})
    return result


def activated_inventory(runtime: PrivateRuntime, root: Path) -> list[dict[str, Any]]:
    # Both initial boot and reload publish registry snapshots asynchronously.
    runtime.request("GET", "/api/agent?" + urlencode({"location[directory]": str(root / "project")}))
    return inventory(plugin_list(runtime, root), root)


def read_witness(path: Path) -> str | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1 or metadata.st_size >= 128:
        raise ProbeFailure("witness_invalid")
    value = path.read_text()
    return value if value in {"PROFILE_BASELINE", "PROFILE_CHANGED", "PROFILE_REUSE"} else "unrecognized-witness"


def admission(config: dict[str, Any], items: list[dict[str, Any]], root: Path) -> str:
    owned = [item for item in items if item["source"] == "owned" and item["status"] == "active"]
    if not owned:
        return "owned-unavailable"
    if len(owned) != 1 or not phase(root, "ready"):
        return "owned-not-ready"
    if config.get("plugins") != [str(root / "project/owned")] or any(item["status"] == "active" and item["source"] not in ("builtin", "owned") for item in items):
        return "unexpected-plugin-topology"
    return "owned-exclusive-ready"


def control_case(root: Path, state: ProfileState, runtime: PrivateRuntime, config: dict[str, Any]) -> dict[str, Any]:
    runtime.ready()
    # plugin.list is a registry snapshot, not an activation barrier. The pinned
    # agent handler awaits location activation (five-second native bound).
    items = activated_inventory(runtime, root)
    if state.case not in ("owned-missing", "owned-failed"):
        wait_until(lambda: phase(root, "ready"), state, "owned_plugin_not_ready")
    ready = [row for row in traces(root) if row["phase"] == "ready"]
    owner = ready[0]["owner"] if ready else None
    initial_items = items
    if state.case == "topology-change":
        config["plugins"].append(str(root / "project/rogue"))
        rewrite_config(root, config)
        runtime.mutate("POST", "/api/location/reload")
        wait_until(lambda: any(row["phase"] == "owner.closed" and row.get("owner") == owner for row in traces(root)), state, "reload_cleanup_unobserved")
        items = activated_inventory(runtime, root)
        wait_until(lambda: any(row["phase"] == "ready" and row.get("owner") != owner for row in traces(root)), state, "replacement_owner_not_ready")
    gate = admission(config, items, root)
    result: dict[str, Any] = {"inventory": items, "initial_inventory": initial_items, "owner_id": owner, "loader_checked": True, "admission": {"admitted": gate == "owned-exclusive-ready", "reason": gate}}
    if state.case in PREDISPATCH:
        result["refused"] = gate != "owned-exclusive-ready"
        return result
    if gate != "owned-exclusive-ready":
        raise ProbeFailure("profile_admission_refused")
    body = {"location": {"directory": str(root / "project")}, "model": {"providerID": "profile", "id": "mock"}, "agent": "build", "title": "Synthetic profile call"}
    session = native_id(runtime.mutate("POST", "/api/session", body)["data"]["id"])
    other = native_id(runtime.mutate("POST", "/api/session", {**body, "title": "Foreign synthetic marker"})["data"]["id"])
    if session == other or not isinstance(session, str) or not isinstance(other, str):
        raise ProbeFailure("native_session_identity_invalid")
    set_foreign(root, other)
    runtime.mutate("POST", f"/api/session/{session}/prompt", {"text": "Run the single fixed synthetic profile tool call."})
    if state.case in CAPTURED:
        wait_until(state.model.arrived.is_set, state, "model_barrier_not_arrived")
        if state.case == "captured-reload":
            config["plugins"] = []
            rewrite_config(root, config)
            runtime.mutate("POST", "/api/location/reload")
            wait_until(lambda: phase(root, "owner.closed"), state, "reload_cleanup_unobserved")
        else:
            state.control.release("dispose")
            wait_until(lambda: phase(root, "registrations.disposed"), state, "registration_disposal_unobserved")
        state.controller_notes.append("closed-before-model-release")
        state.model.release()
    if state.case in PAUSED_AFTER:
        wait_until(state.callback.arrived.is_set, state, "callback_barrier_not_arrived")
        if state.case == "after-interrupted":
            state.expected_callback_disconnect = True
            reply = runtime.mutate("POST", f"/api/session/{session}/interrupt?resume=false")
            state.controller_notes.append("interrupt-ack" if reply.get("interrupted") else "interrupt-not-acknowledged")
        else:
            state.control.release("dispose")
            wait_until(lambda: phase(root, "registrations.disposed"), state, "running_disposal_unobserved")
        state.callback.release()
    runtime.mutate("POST", f"/api/experimental/session/{session}/wait")
    outcome = native_outcome(runtime.request("GET", f"/api/session/{session}")["data"].get("outcome"))
    context = runtime.request("GET", f"/api/session/{session}/context")
    if state.case == "stale-completion-reuse":
        if not phase(root, "stale.rejected"):
            raise ProbeFailure("reuse_owner_not_closed")
        # Deliberately test a fresh genuine model request after registration
        # disposal. If it escapes the removed wrapper, report the counterexample.
        state.reuse_started = True
        runtime.mutate("POST", f"/api/session/{session}/prompt", {"text": "Run the second fixed harmless reuse witness."})
        runtime.mutate("POST", f"/api/experimental/session/{session}/wait")
        reuse_outcome = native_outcome(runtime.request("GET", f"/api/session/{session}")["data"].get("outcome"))
        reuse_context = runtime.request("GET", f"/api/session/{session}/context")
        reuse_path = root / "project/reuse-witness"
        result["reuse"] = {"outcome": reuse_outcome, "terminal_tools": terminal_tools(reuse_context, session, REUSE_ID), "witness": read_witness(reuse_path)}
        state.controller_notes.append("fresh-native-reuse-attempt-settled")
    terminal = terminal_tools(context, session)
    result.update({"session_id": session, "foreign_session_id": other, "outcome": outcome, "terminal_tool_states": terminal, "wait_completed": True})
    return result


def assess(state: ProfileState, control: dict[str, Any], rows: list[dict[str, Any]], witness: str | None) -> tuple[bool, list[str]]:
    """Complete counterexamples remain measurements, never qualified profiles."""
    violations: list[str] = []

    def require(value: Any, reason: str) -> None:
        if not value:
            raise ProbeFailure(reason)

    def one(name: str, subset: list[dict[str, Any]] = rows) -> dict[str, Any]:
        found = [row for row in subset if row["phase"] == name]
        require(len(found) == 1, "required_observation_missing:" + name)
        return found[0]

    def epoch(row: dict[str, Any], expected: int) -> None:
        require(type(row.get("epoch")) is int, "owner_generation_collection_missing")
        if row["epoch"] != expected:
            violations.append("owner-generation-fence")

    ownership = control.get("ownership", {})
    require(type(ownership.get("expected_pid")) is int and ownership["expected_pid"] > 0 and ownership.get("observed_pid") == ownership["expected_pid"] and control.get("loader_checked"), "native_ownership_collection_missing")
    require(isinstance(control.get("inventory"), list) and isinstance(control.get("admission"), dict), "loader_admission_collection_missing")
    items = control["inventory"]
    owner_id = control.get("owner_id")
    owned_rows = [row for row in rows if row.get("owner") == owner_id] if owner_id else []

    def closure(why: str) -> dict[str, Any]:
        closed = one("owner.closed", owned_rows)
        require(closed.get("why") == why and closed.get("epoch") == 2 and type(closed.get("pendingCount")) is int, "owner_closure_provenance_missing")
        if closed["pendingCount"] != 0:
            violations.append("owner-state-not-cleared")
        return closed

    if state.case in PREDISPATCH:
        expected_gate = "owned-unavailable" if state.case in ("owned-missing", "owned-failed") else "unexpected-plugin-topology"
        require(control["admission"].get("reason") == expected_gate, "refusal_gate_collection_missing")
        if state.dispatched or state.requests or witness is not None or not control.get("refused") or control["admission"].get("admitted") is not False:
            violations.append("pre-dispatch-refusal")
        rogue_loaded = any(row["phase"] == "rogue.setup" for row in rows)
        rogue_active = any(item.get("source") == "rogue" and item.get("status") == "active" for item in items)
        require(rogue_loaded == rogue_active, "rogue_loader_collection_missing")
        if state.case in ("rogue-blocked", "topology-change") and rogue_loaded:
            violations.append("plugin-policy")
        if state.case == "rogue-unrestricted-control":
            require(rogue_loaded, "rogue_negative_control_missing")
        if state.case == "owned-missing":
            require(not any(item["source"] == "owned" for item in items) and not rows, "missing_owner_collection_invalid")
        elif state.case == "owned-failed":
            require(any(item["source"] == "owned" and item["status"] == "failed" for item in items) and any(row["phase"] == "owned.failed" for row in rows) and not any(row["phase"] == "ready" for row in rows), "failed_owner_collection_missing")
        else:
            require(owner_id and one("ready", owned_rows).get("epoch") == 1 and any(item["source"] == "owned" and item["status"] == "active" for item in items), "ready_owner_collection_missing")
        if state.case == "topology-change":
            closure("scope-finalizer")
            require(any(row["phase"] == "ready" and row.get("owner") != owner_id for row in rows) and control.get("initial_inventory") is not None, "refreshed_topology_collection_missing")
        return not violations, violations
    require(control["admission"] == {"admitted": True, "reason": "owned-exclusive-ready"}, "admission_collection_invalid")
    require(owner_id and one("ready", owned_rows).get("epoch") == 1, "ready_owner_collection_missing")
    setup = one("setup", owned_rows)
    # Tool transforms can replay when the host rebuilds its catalog. Each
    # observation must identify the native executor; this is not the number
    # of native calls, whose entry and terminal identities are checked below.
    wrapped = [row for row in rows if row["phase"] == "native.wrapped"]
    require(setup.get("version") == "2.2.5" and wrapped, "native_wrapper_collection_missing")
    epoch(setup, 1)
    for definition in wrapped:
        if definition.get("owner") != owner_id:
            violations.append("native-definition-owner")
        require(definition.get("nativeID") == "shell" and definition.get("executeType") == "function", "native_wrapper_collection_missing")
        epoch(definition, 1)
    call_rows = [row for row in owned_rows if row.get("identity", {}).get("id") == CALL_ID]
    entry = one("executor.entry", call_rows)
    if not any(rows.index(definition) < rows.index(entry) for definition in wrapped):
        violations.append("native-definition-order")
    identity = entry.get("identity", {})
    require(all(isinstance(identity.get(key), str) and identity[key] for key in ("sessionID", "messageID", "id", "agent")) and identity["agent"] == "build" and identity["sessionID"] == control.get("session_id"), "native_executor_identity_missing")
    require(all(row["identity"] == identity for row in call_rows), "native_observation_identity_mismatch")
    terminal = control.get("terminal_tool_states", [])
    require(len(terminal) == 1 and all(terminal[0].get(key) == identity[key] for key in ("messageID", "sessionID", "id")) and terminal[0].get("status") in ("completed", "error"), "native_terminal_identity_mismatch")
    require(state.dispatched == (2 if state.case == "stale-completion-reuse" else 1) and state.schema and control.get("outcome") in ("succeeded", "failed", "interrupted"), "native_terminal_collection_missing")
    require(control.get("wait_completed"), "native_wait_collection_missing")
    require(control["outcome"] != "succeeded" or state.continued and state.consumer, "native_consumer_collection_missing")
    require(type(entry.get("live")) is bool and entry.get("command") == "baseline", "executor_entry_collection_missing")
    epoch(entry, 2 if state.case in CAPTURED else 1)
    raw = [row for row in call_rows if row["phase"] == "raw"]
    for result in raw:
        require(type(result.get("exit")) in (int, float) and math.isfinite(result["exit"]), "native_numeric_exit_collection_missing")
        epoch(result, 1)
    if state.case not in CAPTURED:
        before = one("before", call_rows)
        require(before.get("epoch") == 1 and before.get("tool") == "shell" and before.get("command") == "baseline" and rows.index(before) < rows.index(entry), "native_before_collection_missing")
        shell, binding = one("shell.entry", owned_rows), one("shell.binding", owned_rows)
        require(type(shell.get("cwdMatches")) is bool and type(shell.get("shellMatches")) is bool and shell.get("command") == "baseline", "shell_entry_collection_missing")
        require(set(binding.get("matches", {})) == {"cwd", "shell", "env"} and all(type(value) is bool for value in binding["matches"].values()), "binding_mutation_collection_missing")
        require(rows.index(entry) < rows.index(shell) < rows.index(binding), "shell_order_collection_missing")
        epoch(shell, 1);epoch(binding, 1)
        expected_command = "changed" if state.case == "permission-after-shell" else "baseline"
        require(isinstance(binding.get("command"), str), "binding_command_collection_missing")
        if binding["command"] != expected_command:
            violations.append("owned-shell-command-binding")
        expected_false = {"bind-cwd": "cwd", "bind-executable": "shell", "bind-env": "env"}.get(state.case)
        if any(value != (key != expected_false) for key, value in binding["matches"].items()):
            violations.append("owned-shell-field-binding")
        if not shell["cwdMatches"] or not shell["shellMatches"]:
            violations.append("initial-shell-binding")

        def permission(resource: str) -> None:
            matching = [row for row in owned_rows if row["phase"] == "permission" and row.get("action") == "shell" and resource in row.get("resources", []) and row.get("source", {}).get("id") == CALL_ID and row["source"].get("messageID") == identity["messageID"] and row.get("sessionID") == identity["sessionID"]]
            require(matching, "post-shell-native-permission-missing" if resource == "changed" else "native_permission_collection_missing")
            for observed in matching:
                require(isinstance(observed["source"].get("type"), str), "native_permission_source_missing")
                epoch(observed, 1)
                if observed["source"]["type"] != "tool":
                    violations.append("native-permission-source")
                if rows.index(observed) <= rows.index(binding):
                    violations.append("native-permission-order")
    if state.case in CAPTURED:
        closed = closure("scope-finalizer" if state.case == "captured-reload" else "explicit-disposal")
        if state.case == "captured-dispose":
            require(rows.index(closed) < rows.index(one("registrations.disposed", owned_rows)) < rows.index(entry), "registration_disposal_collection_missing")
        require("closed-before-model-release" in state.controller_notes and rows.index(closed) < rows.index(entry), "captured_barrier_collection_missing")
        if witness is not None or entry["live"] or raw or terminal[0]["status"] != "error" or not (state.consumer or {}).get("closed"):
            violations.append("captured-executor-revocation")
    elif state.case.startswith("bind-") or state.case == "permission-after-shell":
        if witness is not None or raw or terminal[0]["status"] != "error":
            violations.append("binding-denial")
        if state.case == "permission-after-shell":
            permission("changed")
        else:
            key = {"bind-cwd": "cwd", "bind-executable": "shell", "bind-env": "env"}[state.case]
            require(binding["matches"][key] is False, "binding_mutation_collection_missing")
    else:
        require(len(raw) == 1, "native_raw_collection_missing")
        if witness != "PROFILE_BASELINE" or raw[0].get("exit") != 0:
            violations.append("native-raw-baseline")
        after = one("after.entry", call_rows)
        require(after.get("status") == "completed" and type(after.get("pending")) is bool and after.get("epoch") == 1, "owned_after_collection_missing")
        permission("baseline")
        if rows.index(raw[0]) >= rows.index(after):
            violations.append("raw-before-owned-presentation")
        if state.case == "baseline":
            one("after.continue", call_rows)
            if terminal[0]["status"] != "completed" or control["outcome"] != "succeeded" or not (state.consumer or {}).get("baseline"):
                violations.append("baseline-terminal-consumer")
        if state.case.startswith("after-") or state.case in ("running-dispose", "stale-completion-reuse"):
            revoked = one("revoked", call_rows)
            epoch(revoked, 2 if state.case in ("running-dispose", "stale-completion-reuse") else 1)
            require(type(revoked.get("targetPending")) is bool and type(revoked.get("foreignPending")) is bool and revoked.get("foreignSessionID") == control.get("foreign_session_id"), "targeted_revocation_collection_missing")
            if revoked["targetPending"]:
                violations.append("targeted-revocation")
            if state.case not in ("running-dispose", "stale-completion-reuse") and not revoked["foreignPending"]:
                violations.append("foreign-session-isolation")
            if state.case == "after-tolerated":
                continued = one("after.continue", call_rows)
                if continued.get("pending") is not False or rows.index(revoked) >= rows.index(continued) or terminal[0]["status"] != "completed" or not (state.consumer or {}).get("baseline"):
                    violations.append("tolerated-continuation-before-revocation")
            else:
                if any(row["phase"] == "after.continue" for row in call_rows) or terminal[0]["status"] != "error" or control["outcome"] != ("interrupted" if state.case == "after-interrupted" else "failed"):
                    violations.append("failed-handler-terminal-settlement")
        if state.case in ("running-dispose", "stale-completion-reuse"):
            closed, suspended, stale = closure("explicit-disposal"), one("after.suspended", call_rows), one("stale.rejected", call_rows)
            disposed = one("registrations.disposed", owned_rows)
            epoch(stale, 2);epoch(disposed, 2)
            require(rows.index(suspended) < rows.index(closed) < rows.index(disposed) < rows.index(stale), "running_disposal_order_missing")
            require(type(stale.get("pending")) is bool, "stale_state_collection_missing")
            if stale["pending"]:
                violations.append("stale-completion-recreated-state")
    if state.case == "stale-completion-reuse":
        reuse = control.get("reuse", {})
        tools = reuse.get("terminal_tools", [])
        require(state.reuse_started and len(tools) == 1 and tools[0].get("id") == REUSE_ID and tools[0].get("sessionID") == identity["sessionID"] and tools[0].get("messageID") != identity["messageID"] and reuse.get("outcome") in ("succeeded", "failed", "interrupted"), "native_reuse_collection_missing")
        require(reuse["outcome"] != "succeeded" or state.reuse_continued and state.reuse_consumer, "native_reuse_consumer_missing")
        if reuse.get("witness") == "PROFILE_REUSE" and tools[0].get("status") == "completed" and (state.reuse_consumer or {}).get("reuse"):
            violations.append("fresh-executor-escaped-disposal-fence")
        elif reuse.get("witness") is not None or tools[0].get("status") != "error" or not (state.reuse_consumer or {}).get("closed"):
            raise ProbeFailure("native_reuse_refusal_collection_missing")
    return not violations, violations


def owned_fixture(root: Path, identity: os.stat_result) -> bool:
    try:
        current = root.lstat()
        if not stat.S_ISDIR(current.st_mode) or current.st_uid != os.getuid() or current.st_mode & 0o077 or (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
            return False
        count = 0
        for directory, directories, files in os.walk(root, followlinks=False):
            for name in (*directories, *files):
                entry = (Path(directory) / name).lstat()
                count += 1
                if count > 4096 or entry.st_uid != os.getuid() or stat.S_ISLNK(entry.st_mode) or not (stat.S_ISDIR(entry.st_mode) or stat.S_ISREG(entry.st_mode)):
                    return False
        return True
    except OSError:
        return False


def run_case(binary: str, parent: Path, case: str) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="v2-profile-", dir=parent))
    identity = root.lstat()
    state = ProfileState(case, root, time.monotonic() + PRIMARY_SECONDS)
    provider: ProfileProvider | None = None
    provider_thread: threading.Thread | None = None
    provider_started = False
    runtime: PrivateRuntime | None = None
    report: dict[str, Any] = {"case": case, "measurement": "FAIL", "witnesses_pass": False}
    cleanup_safe = True

    def expire() -> None:
        state.failure = state.failure or "case_timeout"
        state.stop()
        if provider is not None:
            provider.close_connections()
        if runtime is not None:
            runtime.abort_connections()

    watchdog = threading.Timer(max(0, state.deadline - time.monotonic()), expire)
    watchdog.daemon = True
    try:
        watchdog.start()
        provider = ProfileProvider(state)
        provider_thread = threading.Thread(target=provider.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cleanup_safe = False
        provider_thread.start()
        provider_started = True
        config = prepare_fixture(root, state, provider.server_port)
        runtime = PrivateRuntime(binary, root, state.deadline)
        runtime.start()
        control = control_case(root, state, runtime, config)
        control["ownership"] = {"expected_pid": runtime.process.pid, "observed_pid": runtime.observed_pid}
        report["control"] = control
        if (root / "installer-requested").exists():
            raise ProbeFailure("installer_requested")
        rows = traces(root)
        witness_path = root / "project/witness"
        witness = read_witness(witness_path)
        report.update({"observations": rows, "witness": witness, "provider_requests": state.requests, "provider_dispatched": state.dispatched, "native_schema": state.schema, "consumer": state.consumer, "reuse_consumer": state.reuse_consumer, "controller_notes": state.controller_notes, "barriers": {"model_arrived": state.model.arrived.is_set(), "callback_arrived": state.callback.arrived.is_set()}})
        passed, violations = assess(state, control, rows, witness)
        report.update({"measurement": "PASS", "witnesses_pass": passed, "violations": violations, "control": control, "observations": rows, "witness": witness, "provider_requests": state.requests, "provider_dispatched": state.dispatched, "native_schema": state.schema, "consumer": state.consumer, "reuse_consumer": state.reuse_consumer, "controller_notes": state.controller_notes, "barriers": {"model_arrived": state.model.arrived.is_set(), "callback_arrived": state.callback.arrived.is_set()}})
    except (ProbeFailure, OSError, ValueError, KeyError, TypeError, RuntimeError, http.client.HTTPException) as error:
        report["reason"] = str(error) if isinstance(error, ProbeFailure) else "profile_protocol_error"
        try:
            report["observations"] = traces(root)
        except (ProbeFailure, ValueError):
            report["observations"] = []
    finally:
        cleanup_deadline = time.monotonic() + CLEANUP_SECONDS
        watchdog.cancel()
        if watchdog.ident is not None:
            watchdog.join(max(0, cleanup_deadline - time.monotonic()))
        state.stop()
        cleanup_errors = []
        if provider is not None:
            try:
                if provider_started:
                    provider.shutdown()
                provider.close_connections()
            except OSError:
                cleanup_errors.append("provider-stop")
        if runtime is not None:
            try:
                runtime.close(cleanup_deadline)
            except (ProbeFailure, OSError, subprocess.SubprocessError):
                cleanup_errors.append("runtime-stop")
        if provider is not None:
            try:
                provider.server_close()
            except OSError:
                cleanup_errors.append("provider-close")
            for worker in provider.workers:
                worker.join(max(0, cleanup_deadline - time.monotonic()))
                if worker.is_alive():
                    cleanup_errors.append("provider-worker")
            if provider.admissions != state.handlers:
                state.failure = state.failure or "unhandled_provider_connection"
        if provider_thread is not None and provider_started:
            provider_thread.join(max(0, cleanup_deadline - time.monotonic()))
            if provider_thread.is_alive():
                cleanup_errors.append("provider-thread")
        if watchdog.is_alive() or time.monotonic() > cleanup_deadline:
            cleanup_errors.append("deadline-teardown")
        cleanup_safe = not cleanup_errors
        if cleanup_errors or state.failure:
            report.update({"measurement": "FAIL", "witnesses_pass": False, "reason": state.failure or "profile_cleanup_failed", "cleanup_failures": cleanup_errors})
        if not owned_fixture(root, identity):
            cleanup_safe = False
            report.update({"measurement": "FAIL", "witnesses_pass": False, "reason": "fixture_identity_changed"})
        if cleanup_safe:
            try:
                shutil.rmtree(root)
            except OSError:
                cleanup_safe = False
                report.update({"measurement": "FAIL", "witnesses_pass": False, "reason": "fixture_cleanup_failed"})
        if not cleanup_safe:
            report["retained_fixture"] = root.name
        report["cleanup_complete"] = cleanup_safe
    return report


def probe(binary: str, parent: Path, selected: tuple[str, ...] = CASES) -> dict[str, Any]:
    report: dict[str, Any] = {"schema_version": 1, "measurement": "FAIL", "profile_qualification": "UNQUALIFIED", "qualification_scope": "owned-synthetic-child-only", "authority": AUTHORITY, "cases": [], "source_commit": SOURCE_COMMIT, "release_archive_sha256": ARCHIVE_SHA256}
    try:
        if not selected or len(selected) > len(CASES) or len(set(selected)) != len(selected) or any(case not in CASES for case in selected):
            raise ProbeFailure("invalid_case_selection")
        preflight(parent)
        path = Path(binary)
        initial = path.stat()
        if not stat.S_ISREG(initial.st_mode) or initial.st_size > 1024 * 1024 * 1024:
            raise ProbeFailure("binary_identity_invalid")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        report["binary_identity"] = {"sha256": digest, "device": initial.st_dev, "inode": initial.st_ino, "bytes": initial.st_size}
        with tempfile.TemporaryDirectory(prefix="v2-profile-version-", dir=parent) as temporary:
            root = Path(temporary)
            code, output, _ = run_child([binary, "--version"], root, child_env(root), timeout=10)
            if code != 0 or output.decode().strip() != "opencode v2.2.5":
                raise ProbeFailure("unsupported_host_version")
        for case in selected:
            observed = run_case(binary, parent, case)
            report["cases"].append(observed)
            if observed["measurement"] != "PASS":
                raise ProbeFailure(observed.get("reason", "case_collection_failed"))
        current = path.stat()
        with path.open("rb") as stream:
            unchanged = hashlib.file_digest(stream, "sha256").hexdigest() == digest
        if not unchanged or (initial.st_dev, initial.st_ino, initial.st_size) != (current.st_dev, current.st_ino, current.st_size):
            raise ProbeFailure("binary_identity_changed")
        if selected != CASES:
            raise ProbeFailure("incomplete_case_selection")
        report["measurement"] = "PASS"
        if all(case["witnesses_pass"] and case["cleanup_complete"] for case in report["cases"]):
            report["profile_qualification"] = "QUALIFIED"
    except (ProbeFailure, OSError, ValueError, subprocess.SubprocessError) as error:
        report["reason"] = str(error) if isinstance(error, ProbeFailure) else "profile_internal_error"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode-bin", default="opencode")
    parent = Path(tempfile.gettempdir())
    preferred = parent / "opencode"
    parser.add_argument("--temp-parent", type=Path, default=preferred if preferred.is_dir() else parent)
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args()
    binary = shutil.which(args.opencode_bin)
    if not binary or os.name != "posix":
        parser.error("an installed POSIX OpenCode2.2.5 host is required")
    result = probe(str(Path(binary).resolve()), args.temp_parent.resolve(), tuple(args.case) if args.case else CASES)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["measurement"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
