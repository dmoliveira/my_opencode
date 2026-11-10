"""Exercise experimental V2 error handling across permission and cancellation flows."""

from __future__ import annotations

import base64
import json
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from gateway_secret_redaction_live_smoke import CaptureState, isolated_env
from gateway_v2_tool_error_live_smoke import ErrorHandler, persisted_markers

ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_CANARY = "V2PermissionFeedbackSynthetic_123456789"
REDACTOR_CANARY = "V2PermissionRedactorSynthetic_123456789"
ABORT_CANARY = "V2CancellationSynthetic_123456789"
FORGED_CANARY = "V2ForgedPrototypeSynthetic_123456789"


def request(
    base: str,
    password: str,
    method: str,
    path: str,
    body: Any = None,
    *,
    timeout: int = 3,
) -> Any:
    data = None if body is None else json.dumps(body).encode()
    token = base64.b64encode(f"opencode:{password}".encode()).decode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Basic {token}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def wait_for(
    predicate: Callable[[], Any], process: subprocess.Popen[Any], *, timeout: int = 20
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("isolated OpenCode server exited")
        try:
            value = predicate()
            if value:
                return value
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise TimeoutError("isolated OpenCode probe timed out")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_case(
    capture: ThreadingHTTPServer,
    state: CaptureState,
    mode: str,
    feedback: bool,
    *,
    cancel: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gateway-v2-permission-rejection-") as temp:
        root = Path(temp)
        home, project = root / "home", root / "project"
        plugin = project / "v2-probe"
        plugin.mkdir(parents=True)
        marker = root / "redactor-called"
        identity_marker = root / "host-cause.json"
        quarantine_marker = root / "quarantine-enforced"
        settled_marker = root / "interrupt-settled"
        registered_marker = root / "guard-registered"
        started, aborted, after = root / "started", root / "aborted", root / "after"
        dist = ROOT / "plugin/gateway-core/dist"
        (plugin / "index.ts").write_text(
            'import { Plugin } from "@opencode/plugin"\n'
            'import { Schema } from "effect"\n'
            'import { Error as ToolError } from "@opencode/plugin/promise/tool"\n'
            'import { writeFileSync } from "node:fs"\n'
            'import { inspect } from "node:util"\n'
            f"import {{ registerV2ToolOutputRedaction, registerV2InterruptingToolOutputRedaction }} from {json.dumps((dist / 'v2/tool-output-redaction.js').as_uri())}\n"
            f"import {{ createSecretRedactor }} from {json.dumps((dist / 'hooks/shared/secret-redaction.js').as_uri())}\n"
            'export default Plugin.define({ id: "v2-permission-rejection-probe", async setup(ctx) {\n'
            '  if (!["2.2.5", "2.2.6"].includes(ctx.app.version)) throw new Error("fixture requires OpenCode 2.2.5 or 2.2.6")\n'
            '  let capturedDecline, registered = false, activeCase = false\n'
            '  await ctx.tool.hook("execute.after", async event => {\n'
            '    if (event.input?.kind === "bootstrap") return\n'
            f'    writeFileSync({json.dumps(str(after))}, "after")\n'
            '    if (event.tool !== "synthetic_probe" || event.status !== "error") return\n'
            '    const mode = process.env.V2_SMOKE_CONTROL\n'
            '    if (mode === "interrupt_fail_unprotected") {\n'
            '      event.error = new ToolError({ message: "synthetic rejection" })\n'
            f'      writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true }}))\n'
            f'      try {{ throw new Error({json.dumps(REDACTOR_CANARY)}) }} catch {{ throw new Error("Permission interruption failed") }}\n'
            '    }\n'
            '    if (mode === "drop_cause") {\n'
            '      event.error = new ToolError({ message: "synthetic rejection" })\n'
            f'      writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true }}))\n'
            '    }\n'
            '    if (mode === "throw_after") {\n'
            f'      writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true }}))\n'
            '      throw new Error("synthetic after-hook failure")\n'
            '    }\n'
            '    if (mode === "schema_clone") {\n'
            '      const LocalDecline = Schema.TaggedError()("Permission.DeclinedError", {})\n'
            '      const fresh = new LocalDecline()\n'
            '      const same = !!capturedDecline && fresh instanceof capturedDecline.constructor\n'
            '      event.error = new ToolError({ message: "synthetic rejection", error: fresh })\n'
            f'      writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true, same }}))\n'
            '    }\n'
            '    if (mode === "host_clone") {\n'
            '      const cause = Object.getOwnPropertyDescriptor(event.error, "error")?.value\n'
            '      const tag = capturedDecline && Object.getOwnPropertyDescriptor(capturedDecline, "_tag")?.value\n'
            '      const same = !!capturedDecline && cause === capturedDecline && tag === "Permission.DeclinedError"\n'
            '      if (!same) throw new Error("synthetic host identity not observed")\n'
            '      const clone = Object.create(Object.getPrototypeOf(capturedDecline))\n'
            '      Object.defineProperties(clone, { _tag: { value: "Permission.DeclinedError", enumerable: true }, message: { value: "" }, stack: { value: "" } })\n'
            '      event.error = new ToolError({ message: "synthetic rejection", error: clone })\n'
            f'      writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true, same }}))\n'
            '    }\n'
            '    if (mode === "forged" || mode === "forged_unprotected" || mode === "interrupt_forged") {\n'
            '      const base = Object.create(Error.prototype)\n'
            '      for (const key of ["constructor", "~effect/Effect", "pipe", "toJSON", "~effect/Effect/identifier", "~effect/Effect/evaluate", "~effect/Effect/successCont", "~effect/Effect/failureCont", "~effect/Effect/ensureCont", Symbol.for("nodejs.util.inspect.custom"), Symbol.iterator])\n'
            f'        Object.defineProperty(base, key, {{ value() {{ return {json.dumps(FORGED_CANARY)} }} }})\n'
            '      const schemaBase = Object.create(base, { constructor: { value() {} }, toJSON: { value() {} } })\n'
            '      const schema = Object.create(schemaBase, { constructor: { value() {} }, name: { value: "Permission.DeclinedError" }, "~effect/Schema/Class/Permission.DeclinedError": { get() { return true } } })\n'
            '      const prototype = Object.create(schema, { constructor: { value() {} } })\n'
            '      const forged = Object.create(prototype, { _tag: { value: "Permission.DeclinedError" } })\n'
            '      event.error = new ToolError({ message: "synthetic rejection", error: forged })\n'
            '    }\n'
            '  })\n'
            f'  const redactor = process.env.V2_SMOKE_REDACTOR_FAIL === "1" ? {{ async redactMutableValueAsync() {{ if (activeCase) writeFileSync({json.dumps(str(marker))}, "called"); throw new Error({json.dumps(REDACTOR_CANARY)}) }} }} : createSecretRedactor({{ patterns: {json.dumps([FEEDBACK_CANARY, ABORT_CANARY])}, redactionToken: "[REDACTED]", limits: {{ maxDepth: 32, maxNodes: 10000, maxChars: 1000000 }} }})\n'
            '  const mode = process.env.V2_SMOKE_CONTROL\n'
            '  if (["interrupt_plain", "interrupt_fail", "interrupt_forged", "interrupt_feedback"].includes(mode)) {\n'
            '    const session = {\n'
            '      hook: (name, callback) => ctx.session.hook(name, async event => {\n'
            f'        try {{ await callback(event) }} catch (error) {{ writeFileSync({json.dumps(str(quarantine_marker))} + "-" + name, "enforced"); if (name === "context") writeFileSync({json.dumps(str(quarantine_marker))}, "enforced"); throw error }}\n'
            '      }),\n'
            '      interrupt: async input => {\n'
            f'        writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true, phase: "before" }}))\n'
            f'        if (mode === "interrupt_fail") throw new Error({json.dumps(REDACTOR_CANARY)})\n'
            '        const result = await ctx.session.interrupt(input)\n'
            f'        writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true, phase: "after", result }}))\n'
            '        return result\n'
            '      },\n'
            f'      wait: async input => {{ await ctx.session.wait(input); writeFileSync({json.dumps(str(settled_marker))}, "settled") }},\n'
            '    }\n'
            '    await registerV2InterruptingToolOutputRedaction(session, ctx.tool, redactor, message => new ToolError({ message }), ctx.app.version)\n'
            f'    writeFileSync({json.dumps(str(registered_marker))}, "registered")\n'
            '  }\n'
            '  const inspectForged = event => {\n'
            '    const mode = process.env.V2_SMOKE_CONTROL\n'
            '    if ((mode !== "forged" && mode !== "forged_unprotected") || event.tool !== "synthetic_probe" || event.status !== "error" || event.input?.kind === "bootstrap") return\n'
            '    const cause = Object.getOwnPropertyDescriptor(event.error, "error")?.value\n'
            f'    const exposed = inspect(cause, {{ showHidden: true }}).includes({json.dumps(FORGED_CANARY)})\n'
            '    const same = !!capturedDecline && Object.getPrototypeOf(cause) === Object.getPrototypeOf(capturedDecline)\n'
            f'    writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true, same, exposed }}))\n'
            '  }\n'
            '  if (process.env.V2_SMOKE_GUARD === "off") await ctx.tool.hook("execute.after", inspectForged)\n'
            # Capture a trusted host decline through a fixture-owned assertion
            # before registering the adapter. This is not a production bootstrap.
            '  const registerGuard = async () => {\n'
            '    if (registered) return\n'
            '    await registerV2ToolOutputRedaction(ctx.tool, redactor, (message, cause) => new ToolError({ message, ...(cause === undefined ? {} : { error: cause }) }), ctx.app.version, () => capturedDecline)\n'
            '    await ctx.tool.hook("execute.after", inspectForged)\n'
            f'    registered = true; writeFileSync({json.dumps(str(registered_marker))}, "registered")\n'
            '  }\n'
            '  await ctx.tool.transform((editor) => editor.add({ name: "synthetic_probe", description: "permission rejection probe", options: { codemode: false }, input: { type: "object", properties: { kind: { type: "string" } }, required: ["kind"], additionalProperties: false }, async execute(input, tool) {\n'
            '    if (input.kind !== "bootstrap") activeCase = true\n'
            f'    if (process.env.V2_SMOKE_CANCEL === "1" && input.kind !== "bootstrap") {{ writeFileSync({json.dumps(str(started))}, "started"); await new Promise((_resolve, reject) => {{ const stop = () => {{ writeFileSync({json.dumps(str(aborted))}, "aborted"); reject(new Error({json.dumps(ABORT_CANARY)})) }}; if (tool.signal.aborted) stop(); else tool.signal.addEventListener("abort", stop, {{ once: true }}) }}); return {{ content: "CANCELLATION_BYPASSED" }} }}\n'
            '    try { await ctx.permission.assert({ sessionID: tool.sessionID, agent: tool.agent, source: { type: "tool", messageID: tool.messageID, id: tool.id }, action: "synthetic_ask", resources: ["synthetic-resource"], save: ["synthetic-resource"] }) } catch (error) { capturedDecline = error; if (input.kind === "bootstrap" && process.env.V2_SMOKE_GUARD !== "off") await registerGuard(); throw error }\n'
            '    return { content: "PERMISSION_BYPASSED" }\n'
            "  } }))\n} })\n",
            encoding="utf-8",
        )
        config = {
            "model": "capture/mock",
            "plugins": [str(plugin)],
            "permissions": [
                {"action": "*", "resource": "*", "effect": "allow"},
                {"action": "synthetic_ask", "resource": "*", "effect": "ask"},
            ],
            "providers": {
                "capture": {
                    "name": "Local capture",
                    "package": "@opencode/ai/providers/openai-compatible",
                    "settings": {
                        "baseURL": f"http://127.0.0.1:{capture.server_port}/v1",
                        "apiKey": "local-test-only",
                    },
                    "models": {
                        "mock": {"name": "mock", "capabilities": {"tools": True}}
                    },
                }
            },
        }
        (project / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
        env = isolated_env(home, root / "audit.jsonl")
        env.pop("OPENCODE_SESSION_ID", None)
        password = secrets.token_urlsafe(24)
        env["OPENCODE_PASSWORD"] = password
        if mode in {"baseline", "host_clone", "drop_cause", "throw_after", "forged_unprotected", "schema_clone", "interrupt_plain", "interrupt_fail", "interrupt_fail_unprotected", "interrupt_forged", "interrupt_feedback"}:
            env["V2_SMOKE_GUARD"] = "off"
        if mode in {"host_clone", "drop_cause", "throw_after", "forged", "forged_unprotected", "schema_clone", "interrupt_plain", "interrupt_fail", "interrupt_fail_unprotected", "interrupt_forged", "interrupt_feedback"}:
            env["V2_SMOKE_CONTROL"] = mode
        if mode == "redactor_failure":
            env["V2_SMOKE_REDACTOR_FAIL"] = "1"
        if cancel:
            env["V2_SMOKE_CANCEL"] = "1"
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        with (root / "server.log").open("wb") as log:
            process = subprocess.Popen(
                ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                cwd=project,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                info = wait_for(
                    lambda: request(base, password, "GET", "/api/info"), process
                )
                if info.get("pid") != process.pid:
                    raise RuntimeError("isolated server identity mismatch")
                session_body = {
                    "location": {"directory": str(project)},
                    "model": {"providerID": "capture", "id": "mock"},
                }
                if env.get("V2_SMOKE_GUARD") != "off":
                    bootstrap = request(base, password, "POST", "/api/session", session_body)["data"]["id"]
                    request(base, password, "POST", f"/api/session/{bootstrap}/prompt", {"text": "BOOTSTRAP_PERMISSION_PROBE"})
                    pending = wait_for(
                        lambda: request(base, password, "GET", f"/api/session/{bootstrap}/permission").get("data"),
                        process,
                    )
                    request(base, password, "POST", f"/api/session/{bootstrap}/permission/{pending[0]['id']}/reply", {"decision": "reject"})
                    request(base, password, "POST", f"/api/experimental/session/{bootstrap}/wait", timeout=25)
                    wait_for(lambda: registered_marker.is_file(), process)
                peer = peer_pending_id = None
                if mode in {"interrupt_plain", "interrupt_fail", "interrupt_forged"}:
                    peer = request(base, password, "POST", "/api/session", session_body)["data"]["id"]
                    request(base, password, "POST", f"/api/session/{peer}/prompt", {"text": "PEER_PERMISSION_PROBE"})
                    peer_pending = wait_for(
                        lambda: request(base, password, "GET", f"/api/session/{peer}/permission").get("data"), process
                    )
                    if len(peer_pending) != 1:
                        raise RuntimeError("unexpected peer permissions")
                    peer_pending_id = peer_pending[0]["id"]
                with state.lock:
                    start = len(state.requests)
                session = request(
                    base,
                    password,
                    "POST",
                    "/api/session",
                    session_body,
                )["data"]["id"]
                request(
                    base,
                    password,
                    "POST",
                    f"/api/session/{session}/prompt",
                    {"text": "SECRET_ERROR_PROBE"},
                )
                if cancel:
                    wait_for(lambda: started.is_file(), process)
                    interruption = request(
                        base,
                        password,
                        "POST",
                        f"/api/session/{session}/interrupt?resume=false",
                    )
                else:
                    pending = wait_for(
                        lambda: request(
                            base, password, "GET", f"/api/session/{session}/permission"
                        ).get("data"),
                        process,
                    )
                    reply = {"decision": "reject"}
                    if feedback:
                        reply["message"] = f"synthetic feedback {FEEDBACK_CANARY}"
                    request(
                        base,
                        password,
                        "POST",
                        f"/api/session/{session}/permission/{pending[0]['id']}/reply",
                        reply,
                    )
                request(
                    base,
                    password,
                    "POST",
                    f"/api/experimental/session/{session}/wait",
                    timeout=25,
                )
                with state.lock:
                    requests = list(state.requests[start:])
                wire = json.dumps(requests)
                info = request(base, password, "GET", f"/api/session/{session}")["data"]
                persisted = persisted_markers(
                    home, (ABORT_CANARY, FEEDBACK_CANARY, REDACTOR_CANARY, FORGED_CANARY)
                )
                server_log = (root / "server.log").read_text(
                    encoding="utf-8", errors="replace"
                )
                control_observation = (
                    json.loads(identity_marker.read_text(encoding="utf-8"))
                    if identity_marker.is_file()
                    else {}
                )
                peer_pending_preserved = peer_completed = None
                if peer is not None and peer_pending_id is not None:
                    pending_peer = request(base, password, "GET", f"/api/session/{peer}/permission").get("data", [])
                    peer_pending_preserved = len(pending_peer) == 1 and pending_peer[0].get("id") == peer_pending_id
                    if not peer_pending_preserved:
                        raise RuntimeError("other session's permission was affected")
                    with state.lock:
                        peer_start = len(state.requests)
                    request(base, password, "POST", f"/api/session/{peer}/permission/{peer_pending_id}/reply", {"decision": "once"})
                    request(base, password, "POST", f"/api/experimental/session/{peer}/wait", timeout=25)
                    with state.lock:
                        peer_requests = list(state.requests[peer_start:])
                    peer_completed = any(item.get("role") == "tool" for req in peer_requests for item in req.get("messages", []))
                retry_blocked = retry_completed = None
                auxiliary_blocked = None
                if mode == "interrupt_fail":
                    with state.lock:
                        retry_start = len(state.requests)
                    request(base, password, "POST", f"/api/session/{session}/prompt", {"text": "RETRY_PERMISSION_PROBE"})
                    request(base, password, "POST", f"/api/experimental/session/{session}/wait", timeout=25)
                    with state.lock:
                        retry_blocked = len(state.requests) == retry_start
                    auxiliary_blocked = {}
                    for kind, endpoint, body in (
                        ("generate", "generate", {"prompt": "AUXILIARY_QUARANTINE_PROBE"}),
                        ("compaction", "compact", {}),
                    ):
                        with state.lock:
                            auxiliary_start = len(state.requests)
                        try:
                            request(base, password, "POST", f"/api/session/{session}/{endpoint}", body, timeout=25)
                            if kind == "compaction":
                                request(base, password, "POST", f"/api/experimental/session/{session}/wait", timeout=25)
                        except urllib.error.HTTPError:
                            pass
                        with state.lock:
                            no_request = len(state.requests) == auxiliary_start
                        auxiliary_blocked[kind] = no_request and Path(str(quarantine_marker) + "-" + kind).is_file()
                if mode == "interrupt_plain":
                    wait_for(lambda: settled_marker.is_file(), process)
                    with state.lock:
                        retry_start = len(state.requests)
                    request(base, password, "POST", f"/api/session/{session}/prompt", {"text": "RETRY_PERMISSION_PROBE"})
                    request(base, password, "POST", f"/api/experimental/session/{session}/wait", timeout=25)
                    with state.lock:
                        retry_requests = list(state.requests[retry_start:])
                    retry_info = request(base, password, "GET", f"/api/session/{session}")["data"]
                    retry_completed = bool(retry_requests) and retry_info.get("outcome") == "succeeded"
                return {
                    "permission_requested": not cancel,
                    "tool_returned_to_model": any(
                        item.get("role") == "tool"
                        for req in requests
                        for item in req.get("messages", [])
                    ),
                    "permission_bypassed": "PERMISSION_BYPASSED" in wire
                    or "CANCELLATION_BYPASSED" in wire,
                    "feedback_on_wire": FEEDBACK_CANARY in wire,
                    "feedback_in_database": persisted[FEEDBACK_CANARY],
                    "feedback_in_server_log": FEEDBACK_CANARY in server_log,
                    "redacted_feedback_on_wire": "synthetic feedback [REDACTED]"
                    in wire,
                    "redactor_exception_on_wire": REDACTOR_CANARY in wire,
                    "redactor_exception_in_database": persisted[REDACTOR_CANARY],
                    "redactor_exception_in_server_log": REDACTOR_CANARY in server_log,
                    "redactor_called": marker.is_file(),
                    "interrupted": interruption.get("interrupted") if cancel else None,
                    "session_outcome": info.get("outcome"),
                    "abort_signal_seen": aborted.is_file(),
                    "after_hook_seen": after.is_file(),
                    "control_applied": control_observation.get("mode") == mode
                    and control_observation.get("applied") is True,
                    "interrupt_phase": control_observation.get("phase"),
                    "interrupt_result": control_observation.get("result"),
                    "quarantine_enforced": quarantine_marker.is_file(),
                    "peer_pending_preserved": peer_pending_preserved,
                    "peer_completed": peer_completed,
                    "retry_blocked": retry_blocked,
                    "auxiliary_blocked": auxiliary_blocked,
                    "retry_completed": retry_completed,
                    "interrupt_guard_registered": registered_marker.is_file(),
                    "host_cause_is_captured": control_observation.get("same"),
                    "forged_exposed_to_inspect": control_observation.get("exposed"),
                    "forged_canary_on_wire": FORGED_CANARY in wire,
                    "forged_canary_in_database": persisted[FORGED_CANARY],
                    "forged_canary_in_server_log": FORGED_CANARY in server_log,
                    "abort_canary_on_wire": ABORT_CANARY in wire,
                    "abort_canary_in_database": persisted[ABORT_CANARY],
                }
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def control_evidence_passed(controls: dict[str, dict[str, Any]]) -> bool:
    if set(controls) != {"host_clone", "drop_cause", "throw_after"}:
        return False
    for mode, row in controls.items():
        if not isinstance(row, dict):
            return False
        expected_tool_result = mode != "host_clone"
        if (
            row.get("permission_requested") is not True
            or row.get("after_hook_seen") is not True
            or row.get("control_applied") is not True
            or row.get("permission_bypassed") is not False
            or row.get("tool_returned_to_model") is not expected_tool_result
        ):
            return False
    return controls["host_clone"].get("host_cause_is_captured") is True


def interrupt_evidence_passed(rows: dict[str, dict[str, Any]]) -> bool:
    expected = {"plain", "failure", "unprotected", "forged", "feedback"}
    if set(rows) != expected or not all(isinstance(row, dict) for row in rows.values()):
        return False
    for row in rows.values():
        if any(row.get(field) is not True for field in ("permission_requested", "after_hook_seen")):
            return False
        if any(row.get(field) is not False for field in (
            "permission_bypassed", "redactor_exception_on_wire", "redactor_exception_in_database", "redactor_exception_in_server_log",
            "forged_canary_on_wire", "forged_canary_in_database", "forged_canary_in_server_log",
        )):
            return False
    for mode in ("plain", "forged"):
        row = rows[mode]
        result = row.get("interrupt_result")
        if (
            row.get("interrupt_guard_registered") is not True
            or row.get("control_applied") is not True
            or row.get("interrupt_phase") != "after"
            or not isinstance(result, dict)
            or result.get("interrupted") is not True
            or row.get("session_outcome") != "interrupted"
            or row.get("tool_returned_to_model") is not False
            or row.get("peer_pending_preserved") is not True
            or row.get("peer_completed") is not True
        ):
            return False
    failure = rows["failure"]
    auxiliary = failure.get("auxiliary_blocked")
    feedback = rows["feedback"]
    unprotected = rows["unprotected"]
    return (
        rows["plain"].get("retry_completed") is True
        and failure.get("interrupt_guard_registered") is True
        and failure.get("control_applied") is True
        and failure.get("session_outcome") == "failed"
        and failure.get("tool_returned_to_model") is False
        and failure.get("quarantine_enforced") is True
        and failure.get("retry_blocked") is True
        and isinstance(auxiliary, dict)
        and set(auxiliary) == {"generate", "compaction"}
        and all(auxiliary.get(kind) is True for kind in ("generate", "compaction"))
        and failure.get("peer_pending_preserved") is True
        and failure.get("peer_completed") is True
        and unprotected.get("control_applied") is True
        and unprotected.get("tool_returned_to_model") is True
        and feedback.get("interrupt_guard_registered") is True
        and feedback.get("control_applied") is False
        and feedback.get("tool_returned_to_model") is True
        and feedback.get("redacted_feedback_on_wire") is True
        and feedback.get("feedback_on_wire") is False
        and feedback.get("feedback_in_database") is False
        and feedback.get("feedback_in_server_log") is False
    )


def main() -> int:
    capture = ThreadingHTTPServer(("127.0.0.1", 0), ErrorHandler)
    state = CaptureState()
    capture.capture_state = state
    thread = threading.Thread(target=capture.serve_forever, daemon=True)
    thread.start()
    try:
        cases = {
            f"{mode}_{'feedback' if feedback else 'plain'}": run_case(
                capture, state, mode, feedback
            )
            for mode in ("baseline", "guarded", "redactor_failure")
            for feedback in (False, True)
        }
        cancellation = {
            mode: run_case(capture, state, mode, False, cancel=True)
            for mode in ("baseline", "guarded")
        }
        controls = {
            mode: run_case(capture, state, mode, False)
            for mode in ("host_clone", "drop_cause", "throw_after")
        }
        forged = {
            mode: run_case(capture, state, mode, False)
            for mode in ("forged", "forged_unprotected")
        }
        independent_schema = run_case(capture, state, "schema_clone", False)
        interrupt_cases = {
            name: run_case(capture, state, mode, feedback)
            for name, mode, feedback in (
                ("plain", "interrupt_plain", False),
                ("failure", "interrupt_fail", False),
                ("unprotected", "interrupt_fail_unprotected", False),
                ("forged", "interrupt_forged", False),
                ("feedback", "interrupt_feedback", True),
            )
        }
        passed = (
            all(
                row["permission_requested"]
                and not row["permission_bypassed"]
                and not row["redactor_exception_on_wire"]
                and not row["redactor_exception_in_database"]
                and not row["redactor_exception_in_server_log"]
                for row in cases.values()
            )
            and all(
                not cases[f"{mode}_plain"]["tool_returned_to_model"]
                for mode in ("baseline", "guarded", "redactor_failure")
            )
            and all(
                cases[f"{mode}_feedback"]["tool_returned_to_model"]
                for mode in ("baseline", "guarded", "redactor_failure")
            )
            and cases["baseline_feedback"]["feedback_on_wire"]
            and cases["baseline_feedback"]["feedback_in_database"]
            and not cases["guarded_feedback"]["feedback_on_wire"]
            and not cases["guarded_feedback"]["feedback_in_database"]
            and not cases["guarded_feedback"]["feedback_in_server_log"]
            and cases["guarded_feedback"]["redacted_feedback_on_wire"]
            and not cases["redactor_failure_feedback"]["feedback_on_wire"]
            and not cases["redactor_failure_feedback"]["feedback_in_database"]
            and not cases["redactor_failure_feedback"]["feedback_in_server_log"]
            and cases["redactor_failure_plain"]["redactor_called"]
            and cases["redactor_failure_feedback"]["redactor_called"]
            and all(
                row["interrupted"] is True
                and row["session_outcome"] == "interrupted"
                and row["abort_signal_seen"]
                and not row["after_hook_seen"]
                and not row["tool_returned_to_model"]
                and not row["permission_bypassed"]
                and not row["abort_canary_on_wire"]
                and not row["abort_canary_in_database"]
                for row in cancellation.values()
            )
            and control_evidence_passed(controls)
            and interrupt_evidence_passed(interrupt_cases)
            and forged["forged"]["control_applied"]
            and forged["forged"]["host_cause_is_captured"] is True
            and forged["forged"]["forged_exposed_to_inspect"] is False
            and not forged["forged"]["tool_returned_to_model"]
            and not forged["forged"]["forged_canary_on_wire"]
            and not forged["forged"]["forged_canary_in_database"]
            and not forged["forged"]["forged_canary_in_server_log"]
            and forged["forged_unprotected"]["control_applied"]
            and forged["forged_unprotected"]["host_cause_is_captured"] is False
            and forged["forged_unprotected"]["forged_exposed_to_inspect"] is True
            and independent_schema["control_applied"]
            and independent_schema["host_cause_is_captured"] is False
            and independent_schema["tool_returned_to_model"]
        )
        print(
            json.dumps(
                {
                    "result": "PASS" if passed else "FAIL",
                    "cases": cases,
                    "cancellation": cancellation,
                    "controls": controls,
                    "forged": forged,
                    "independent_schema": independent_schema,
                    "interrupt_cases": interrupt_cases,
                }
            )
        )
        return 0 if passed else 1
    finally:
        capture.shutdown()
        capture.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
