"""Measure experimental V2 redaction with an owned synthetic provider.

This is evidence from private child runtimes, not gateway qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gateway_v2_dependency_contract_probe import (
    MANAGERS,
    ProbeFailure,
    child_env,
    preflight,
    run_child,
)
from gateway_v2_dependency_profile_probe import (
    CLEANUP_SECONDS,
    MAX_CONNECTIONS,
    PRIMARY_SECONDS,
    PrivateRuntime,
    ProfileHandler,
    ProfileProvider,
    ProfileState,
    activated_inventory,
    native_id,
    owned_fixture,
    wait_until,
)

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("context", "generate", "compaction", "title")
MODES = ("control", "protected")
SYSTEM_CANARY = "V2AuxSystemSecret_123456789"
MESSAGE_CANARY = "V2AuxMessageSecret_987654321"
MESSAGE_MARKER = "V2_AUX_MESSAGE_MARKER"
SYSTEM_MARKER = "V2_AUX_MARKER_"
REDACTION = "[REDACTED]"
MAX_TRACE_BYTES = 4096
MAX_TRACE_ROWS = 32
MAX_FIXTURE_BYTES = 1024 * 1024
INSTALLER_STUB = "#!/bin/sh\nexit 97\n"


def write_fixture(
    root: Path, relative: str, text: str, *, executable: bool = False
) -> None:
    """Create a new fixture file without truncating or following an existing entry."""
    path = Path(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise ProbeFailure("fixture_path_invalid")
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.open not in os.supports_dir_fd
        or os.mkdir not in os.supports_dir_fd
    ):
        raise ProbeFailure("fixture_primitives_unavailable")
    content = text.encode("utf-8")
    if len(content) > MAX_FIXTURE_BYTES:
        raise ProbeFailure("fixture_size_limit")
    before = root.lstat()
    if (
        not stat.S_ISDIR(before.st_mode)
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != 0o700
    ):
        raise ProbeFailure("fixture_root_invalid")
    directories: list[int] = []
    try:
        current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directories.append(current)
        opened = os.fstat(current)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ProbeFailure("fixture_root_changed")
        for part in path.parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=current)
            except FileExistsError:
                pass
            current = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current
            )
            directories.append(current)
            metadata = os.fstat(current)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ProbeFailure("fixture_parent_invalid")
        mode = 0o700 if executable else 0o600
        descriptor = os.open(
            path.parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=current,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_size != 0
            ):
                raise ProbeFailure("fixture_file_invalid")
            os.fchmod(descriptor, mode)
            remaining = memoryview(content)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise ProbeFailure("fixture_write_incomplete")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)
    finally:
        for directory in reversed(directories):
            os.close(directory)


@dataclass
class CaptureState(ProfileState):
    observations: list[dict[str, Any]] = field(default_factory=list)
    trace_rows: list[dict[str, Any]] = field(default_factory=list)
    provider_key: str = field(default_factory=lambda: secrets.token_hex(24))
    responses: int = 0

    def answer(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        text = json.dumps(payload, sort_keys=True)
        with self.lock:
            self.requests += 1
            if self.requests > MAX_CONNECTIONS:
                raise ProbeFailure("provider_request_limit")
            self.observations.append(
                {
                    "markers": [kind for kind in KINDS if SYSTEM_MARKER + kind in text],
                    "system_canary": SYSTEM_CANARY in text,
                    "message_canary": MESSAGE_CANARY in text,
                    "message_marker": MESSAGE_MARKER in text,
                    "redacted": REDACTION in text,
                }
            )
        return {"role": "assistant", "content": "SYNTHETIC_OK"}, "stop"


class CaptureHandler(ProfileHandler):
    def do_POST(self) -> None:
        if self.path != "/trace":
            state: CaptureState = self.server.state  # type: ignore[attr-defined]
            if self.headers.get("Authorization") != f"Bearer {state.provider_key}":
                self.started()
                state.failure = state.failure or "provider_authentication_failed"
                self.send_error(401)
                return
            # The reused synthetic provider handler expects its fixed fixture
            # token. Only adapt the header after our per-case check succeeds.
            self.headers.replace_header("Authorization", "Bearer synthetic-only")
            super().do_POST()
            return
        state: CaptureState = self.started()  # type: ignore[assignment]
        try:
            if self.headers.get("Authorization") != f"Bearer {state.control_key}":
                raise ProbeFailure("trace_authentication_failed")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_TRACE_BYTES:
                raise ProbeFailure("trace_request_size")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ProbeFailure("trace_request_incomplete")
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ProbeFailure("trace_schema_invalid")
            with state.lock:
                if len(state.trace_rows) >= MAX_TRACE_ROWS:
                    raise ProbeFailure("trace_row_limit")
                state.trace_rows.append(row)
            self.reply(b'{"ok":true}')
        except (ProbeFailure, ValueError, TypeError, OSError) as error:
            if not state.stopped.is_set():
                state.failure = state.failure or (
                    str(error)
                    if isinstance(error, ProbeFailure)
                    else "trace_protocol_error"
                )
                self.send_error(400)

    def do_GET(self) -> None:
        state = self.started()
        state.failure = "unexpected_provider_method"
        self.send_error(405)

    def reply(self, body: bytes, content_type: str = "application/json") -> None:
        super().reply(body, content_type)
        if self.path == "/v1/chat/completions":
            state: CaptureState = self.server.state  # type: ignore[attr-defined]
            with state.lock:
                state.responses += 1


class CaptureProvider(ProfileProvider):
    def __init__(self, state: CaptureState):
        super().__init__(state)
        self.RequestHandlerClass = CaptureHandler


def fixture_plugin(root: Path, port: int, key: str, *, protected: bool) -> str:
    dist = ROOT / "plugin" / "gateway-core" / "dist"
    values: dict[str, Any] = {
        "__BOUNDARY__": (dist / "v2" / "provider-boundary.js").as_uri(),
        "__REDACTOR__": (dist / "hooks" / "shared" / "secret-redaction.js").as_uri(),
        "__TRACE_URL__": f"http://127.0.0.1:{port}/trace",
        "__TRACE_KEY__": key,
        "__SYSTEM_CANARY__": SYSTEM_CANARY,
        "__MESSAGE_CANARY__": MESSAGE_CANARY,
        "__PROTECTED__": protected,
    }
    source = r"""
import { Plugin } from "@opencode/plugin"
import { registerV2ContextRedaction } from __BOUNDARY__
import { createSecretRedactor } from __REDACTOR__
const traceUrl = __TRACE_URL__
const traceKey = __TRACE_KEY__
const systemCanary = __SYSTEM_CANARY__
const messageCanary = __MESSAGE_CANARY__
const protectedMode = __PROTECTED__
const kinds = ["context", "generate", "compaction", "title"]
let traceRows = 0
const record = async row => {
  if (++traceRows > 32) throw new Error("AUX_TRACE_LIMIT")
  const response = await fetch(traceUrl, {method:"POST", headers:{"Authorization":`Bearer ${traceKey}`, "Content-Type":"application/json"}, body:JSON.stringify(row)})
  if (!response.ok) throw new Error("AUX_TRACE_FAILED")
}
export default Plugin.define({ id: "profile-owned", async setup(ctx) {
  for (const kind of kinds) await ctx.session.hook(kind, async event => {
    const valid = Array.isArray(event.system) && Array.isArray(event.messages)
    const messages = valid ? JSON.stringify(event.messages) : ""
    await record({ phase:"before", kind, valid, messageMarker:messages.includes("V2_AUX_MESSAGE_MARKER"), messageCanary:messages.includes(messageCanary) })
    if (valid) event.system.push({type:"text", text:`V2_AUX_MARKER_${kind} ${systemCanary}`})
  })
  const redactor = createSecretRedactor({ patterns:[systemCanary,messageCanary], redactionToken:"[REDACTED]", limits:{maxDepth:64,maxNodes:100000,maxChars:5000000} })
  const dispose = protectedMode ? await registerV2ContextRedaction(ctx.session, redactor) : async () => {}
  for (const kind of kinds) await ctx.session.hook(kind, async event => {
    const system = JSON.stringify(event.system), messages = JSON.stringify(event.messages)
    await record({ phase:"after", kind, systemMarker:system.includes(`V2_AUX_MARKER_${kind}`), messageMarker:messages.includes("V2_AUX_MESSAGE_MARKER"), systemCanary:system.includes(systemCanary), messageCanary:messages.includes(messageCanary), systemRedacted:system.includes("[REDACTED]"), messageRedacted:messages.includes("[REDACTED]") })
  })
  await record({phase:"ready", version:ctx.app.version})
  return dispose
} })
"""
    for placeholder, value in values.items():
        source = source.replace(placeholder, json.dumps(value))
    return source


def prepare_fixture(
    root: Path, port: int, key: str, provider_key: str, *, protected: bool
) -> dict[str, Any]:
    for name in ("home", "tmp", "bin"):
        (root / name).mkdir(mode=0o700)
    write_fixture(
        root,
        "project/owned/index.ts",
        fixture_plugin(root, port, key, protected=protected),
    )
    rules = [{"action": "*", "resource": "*", "effect": "deny"}]
    config = {
        "update": "disable",
        "model": "probe/mock",
        "default_agent": "build",
        "snapshots": False,
        "formatter": False,
        "permissions": rules,
        "agents": {
            "build": {"permissions": rules},
            "title": {"model": "probe/mock"},
            "compaction": {"model": "probe/mock"},
        },
        "plugins": [str(root / "project" / "owned")],
        "providers": {
            "probe": {
                "name": "Synthetic local provider",
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": f"http://127.0.0.1:{port}/v1",
                    "apiKey": provider_key,
                },
                "models": {"mock": {"name": "mock", "capabilities": {"tools": False}}},
            }
        },
    }
    write_fixture(root, "project/opencode.json", json.dumps(config))
    write_fixture(root, "home/.config/opencode/opencode.json", '{"update":"disable"}')
    for manager in (*MANAGERS, "corepack", "pnpx", "yarnpkg", "pipx", "uvx"):
        write_fixture(
            root,
            f"bin/{manager}",
            INSTALLER_STUB,
            executable=True,
        )
    return config


def assess(
    mode: str, rows: list[dict[str, Any]], requests: list[dict[str, Any]]
) -> dict[str, int]:
    """Require both pre-redaction controls and matching provider observations."""
    if mode not in MODES:
        raise ProbeFailure("invalid_case")
    if (
        not isinstance(rows, list)
        or not isinstance(requests, list)
        or any(not isinstance(row, dict) for row in rows)
        or any(not isinstance(request, dict) for request in requests)
    ):
        raise ProbeFailure("observation_schema_invalid")
    if len(rows) > MAX_TRACE_ROWS or len(requests) > MAX_CONNECTIONS:
        raise ProbeFailure("observation_limit")
    ready = [row for row in rows if row.get("phase") == "ready"]
    if ready != [{"phase": "ready", "version": "2.2.5"}]:
        raise ProbeFailure("plugin_ready_missing")
    before_keys = {"phase", "kind", "valid", "messageMarker", "messageCanary"}
    after_keys = {
        "phase",
        "kind",
        "systemMarker",
        "messageMarker",
        "systemCanary",
        "messageCanary",
        "systemRedacted",
        "messageRedacted",
    }
    for row in rows:
        phase = row.get("phase")
        if phase == "ready":
            continue
        keys = (
            before_keys
            if phase == "before"
            else after_keys
            if phase == "after"
            else set()
        )
        if set(row) != keys or row.get("kind") not in KINDS:
            raise ProbeFailure("trace_schema_invalid")
        if any(type(row[key]) is not bool for key in keys - {"phase", "kind"}):
            raise ProbeFailure("trace_schema_invalid")
    expected_canary = mode == "control"
    counts: dict[str, int] = {}
    for kind in KINDS:
        before = [
            row
            for row in rows
            if row.get("phase") == "before" and row.get("kind") == kind
        ]
        after = [
            row
            for row in rows
            if row.get("phase") == "after" and row.get("kind") == kind
        ]
        if (
            len(before) != 1
            or len(after) != 1
            or rows.index(before[0]) >= rows.index(after[0])
        ):
            raise ProbeFailure("hook_observation_incomplete")
        first, last = before[0], after[0]
        if not (first["valid"] and first["messageMarker"] and first["messageCanary"]):
            raise ProbeFailure("hook_input_control_missing")
        if not (last["systemMarker"] and last["messageMarker"]):
            raise ProbeFailure("hook_marker_missing")
        if (
            last["systemCanary"] is not expected_canary
            or last["messageCanary"] is not expected_canary
        ):
            raise ProbeFailure("hook_redaction_mismatch")
        if mode == "protected" and not (
            last["systemRedacted"] and last["messageRedacted"]
        ):
            raise ProbeFailure("hook_redaction_token_missing")
        counts[kind] = 0
    request_keys = {
        "markers",
        "system_canary",
        "message_canary",
        "message_marker",
        "redacted",
    }
    for request in requests:
        if set(request) != request_keys or not isinstance(request["markers"], list):
            raise ProbeFailure("provider_observation_invalid")
        if any(type(request[key]) is not bool for key in request_keys - {"markers"}):
            raise ProbeFailure("provider_observation_invalid")
        markers = request["markers"]
        if len(markers) != 1 or markers[0] not in KINDS:
            raise ProbeFailure("provider_request_ambiguous")
        if not request["message_marker"]:
            raise ProbeFailure("provider_message_marker_missing")
        if (
            request["system_canary"] is not expected_canary
            or request["message_canary"] is not expected_canary
        ):
            raise ProbeFailure("provider_redaction_mismatch")
        if mode == "protected" and not request["redacted"]:
            raise ProbeFailure("provider_redaction_token_missing")
        counts[markers[0]] += 1
    if any(count == 0 for count in counts.values()):
        raise ProbeFailure("provider_observation_incomplete")
    return counts


def exercise(
    runtime: PrivateRuntime, root: Path, config: dict[str, Any], state: CaptureState
) -> None:
    runtime.ready()
    inventory = activated_inventory(runtime, root)
    active = [
        item
        for item in inventory
        if item.get("source") == "owned" and item.get("status") == "active"
    ]
    if len(active) != 1 or config.get("plugins") != [str(root / "project" / "owned")]:
        raise ProbeFailure("fixture_plugin_not_active")
    if any(
        item.get("source") not in ("builtin", "owned")
        and item.get("status") == "active"
        for item in inventory
    ):
        raise ProbeFailure("unexpected_plugin_topology")
    created = runtime.mutate(
        "POST",
        "/api/session",
        {
            "location": {"directory": str(root / "project")},
            "model": {"providerID": "probe", "id": "mock"},
            "agent": "build",
        },
    )
    session = native_id(created["data"]["id"])
    runtime.mutate(
        "POST",
        f"/api/session/{session}/prompt",
        {"text": f"{MESSAGE_MARKER} {MESSAGE_CANARY}"},
    )
    runtime.mutate("POST", f"/api/experimental/session/{session}/wait")
    runtime.mutate(
        "POST",
        f"/api/session/{session}/generate",
        {"prompt": f"{MESSAGE_MARKER} {MESSAGE_CANARY}"},
    )
    runtime.mutate("POST", f"/api/session/{session}/compact", {})
    runtime.mutate("POST", f"/api/experimental/session/{session}/wait")

    def all_kinds_seen() -> bool:
        with state.lock:
            return {
                kind for item in state.observations for kind in item["markers"]
            } == set(KINDS) and state.responses == state.requests

    wait_until(all_kinds_seen, state, "provider_observation_incomplete")


def run_case(binary: str, parent: Path, mode: str) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="v2-aux-redaction-", dir=parent))
    identity = root.lstat()
    state = CaptureState(mode, root, time.monotonic() + PRIMARY_SECONDS)
    provider: CaptureProvider | None = None
    provider_thread: threading.Thread | None = None
    provider_started = False
    runtime: PrivateRuntime | None = None
    completed = False
    report: dict[str, Any] = {"case": mode, "measurement": "FAIL"}

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
        provider = CaptureProvider(state)
        provider_thread = threading.Thread(
            target=provider.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        provider_thread.start()
        provider_started = True
        config = prepare_fixture(
            root,
            provider.server_port,
            state.control_key,
            state.provider_key,
            protected=mode == "protected",
        )
        runtime = PrivateRuntime(binary, root, state.deadline)
        runtime.start()
        exercise(runtime, root, config, state)
        completed = True
    except (
        ProbeFailure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        http.client.HTTPException,
    ) as error:
        report["reason"] = (
            str(error) if isinstance(error, ProbeFailure) else "probe_protocol_error"
        )
    finally:
        deadline = time.monotonic() + CLEANUP_SECONDS
        watchdog.cancel()
        if watchdog.ident is not None:
            watchdog.join(max(0, deadline - time.monotonic()))
        state.stop()
        cleanup_errors: list[str] = []
        if provider is not None:
            try:
                if provider_started:
                    provider.shutdown()
                provider.close_connections()
            except OSError:
                cleanup_errors.append("provider-stop")
        if runtime is not None:
            try:
                runtime.close(deadline)
            except (ProbeFailure, OSError, subprocess.SubprocessError):
                cleanup_errors.append("runtime-stop")
        if provider is not None:
            try:
                provider.server_close()
            except OSError:
                cleanup_errors.append("provider-close")
            for worker in provider.workers:
                worker.join(max(0, deadline - time.monotonic()))
                if worker.is_alive():
                    cleanup_errors.append("provider-worker")
            if provider.admissions != state.handlers:
                state.failure = state.failure or "unhandled_provider_connection"
        if provider_thread is not None and provider_started:
            provider_thread.join(max(0, deadline - time.monotonic()))
            if provider_thread.is_alive():
                cleanup_errors.append("provider-thread")
        if watchdog.is_alive() or time.monotonic() > deadline:
            cleanup_errors.append("deadline-teardown")
        if not owned_fixture(root, identity):
            cleanup_errors.append("fixture-identity")
        if completed and not cleanup_errors and not state.failure:
            try:
                if state.responses != state.requests or state.requests != len(
                    state.observations
                ):
                    raise ProbeFailure("provider_response_incomplete")
                counts = assess(mode, state.trace_rows, state.observations)
                report.update(
                    {"measurement": "PASS", "provider_requests_by_kind": counts}
                )
            except ProbeFailure as error:
                report["reason"] = str(error)
            except (OSError, ValueError, TypeError):
                report["reason"] = "evidence_incomplete_or_mismatched"
        if cleanup_errors or state.failure:
            report.update(
                {
                    "measurement": "FAIL",
                    "reason": state.failure or "cleanup_failed",
                    "teardown_failures": cleanup_errors,
                }
            )
        # A same-UID actor can replace pathnames or move unrelated files into a
        # fixture after inspection. Retain it rather than recursively deleting
        # data whose provenance cannot be established by these checks.
        report["retained_fixture"] = root.name
        report["teardown_complete"] = not cleanup_errors
    return report


def probe(binary: str, parent: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "measurement": "FAIL",
        "scope": "owned-synthetic-child-only",
        "authority": "disabled-unqualified",
        "cases": [],
    }
    try:
        preflight(parent)
        for relative in ("v2/provider-boundary.js", "hooks/shared/secret-redaction.js"):
            if not (ROOT / "plugin" / "gateway-core" / "dist" / relative).is_file():
                raise ProbeFailure("gateway_build_missing")
        path = Path(binary)
        initial = path.stat()
        if not stat.S_ISREG(initial.st_mode) or initial.st_size > 1024 * 1024 * 1024:
            raise ProbeFailure("binary_identity_invalid")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        report["binary_sha256"] = digest
        home = Path(tempfile.mkdtemp(prefix="v2-aux-version-", dir=parent))
        report["version_fixture"] = home.name
        code, output, _ = run_child(
            [binary, "--version"], home, child_env(home), timeout=10
        )
        if code != 0 or output.decode().strip() != "opencode v2.2.5":
            raise ProbeFailure("unsupported_host_version")
        for mode in MODES:
            result = run_case(binary, parent, mode)
            report["cases"].append(result)
            counts = result.get("provider_requests_by_kind")
            if (
                result.get("case") != mode
                or result.get("measurement") != "PASS"
                or result.get("teardown_complete") is not True
                or not isinstance(counts, dict)
                or set(counts) != set(KINDS)
                or any(type(count) is not int or count < 1 for count in counts.values())
                or sum(counts.values()) > MAX_CONNECTIONS
            ):
                raise ProbeFailure("case_failed")
        current = path.stat()
        with path.open("rb") as stream:
            unchanged = hashlib.file_digest(stream, "sha256").hexdigest() == digest
        if not unchanged or (initial.st_dev, initial.st_ino, initial.st_size) != (
            current.st_dev,
            current.st_ino,
            current.st_size,
        ):
            raise ProbeFailure("binary_identity_changed")
        report["measurement"] = "PASS"
    except (ProbeFailure, OSError, ValueError, subprocess.SubprocessError) as error:
        report["reason"] = (
            str(error) if isinstance(error, ProbeFailure) else "probe_internal_error"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode-bin", default="opencode")
    parent = Path(tempfile.gettempdir())
    preferred = parent / "opencode"
    parser.add_argument(
        "--temp-parent", type=Path, default=preferred if preferred.is_dir() else parent
    )
    args = parser.parse_args()
    binary = shutil.which(args.opencode_bin)
    if not binary or os.name != "posix":
        parser.error("an installed POSIX OpenCode 2.2.5 host is required")
    result = probe(str(Path(binary).resolve()), args.temp_parent)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["measurement"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
