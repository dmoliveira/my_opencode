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
        started, aborted, after = root / "started", root / "aborted", root / "after"
        dist = ROOT / "plugin/gateway-core/dist"
        (plugin / "index.ts").write_text(
            'import { Plugin } from "@opencode/plugin"\n'
            'import { Error as ToolError } from "@opencode/plugin/promise/tool"\n'
            'import { writeFileSync } from "node:fs"\n'
            f"import {{ registerV2ToolOutputRedaction }} from {json.dumps((dist / 'v2/tool-output-redaction.js').as_uri())}\n"
            f"import {{ createSecretRedactor }} from {json.dumps((dist / 'hooks/shared/secret-redaction.js').as_uri())}\n"
            'export default Plugin.define({ id: "v2-permission-rejection-probe", async setup(ctx) {\n'
            '  if (ctx.app.version !== "2.2.5") throw new Error("fixture requires OpenCode 2.2.5")\n'
            '  let capturedDecline\n'
            '  await ctx.tool.hook("execute.after", event => {\n'
            f'    writeFileSync({json.dumps(str(after))}, "after")\n'
            '    if (event.tool !== "synthetic_probe" || event.status !== "error") return\n'
            '    const mode = process.env.V2_SMOKE_CONTROL\n'
            '    if (mode === "drop_cause") {\n'
            '      event.error = new ToolError({ message: "synthetic rejection" })\n'
            f'      writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true }}))\n'
            '    }\n'
            '    if (mode === "throw_after") {\n'
            f'      writeFileSync({json.dumps(str(identity_marker))}, JSON.stringify({{ mode, applied: true }}))\n'
            '      throw new Error("synthetic after-hook failure")\n'
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
            '  })\n'
            f'  const redactor = process.env.V2_SMOKE_REDACTOR_FAIL === "1" ? {{ async redactMutableValueAsync() {{ writeFileSync({json.dumps(str(marker))}, "called"); throw new Error({json.dumps(REDACTOR_CANARY)}) }} }} : createSecretRedactor({{ patterns: {json.dumps([FEEDBACK_CANARY, ABORT_CANARY])}, redactionToken: "[REDACTED]", limits: {{ maxDepth: 32, maxNodes: 10000, maxChars: 1000000 }} }})\n'
            '  if (process.env.V2_SMOKE_GUARD !== "off") await registerV2ToolOutputRedaction(ctx.tool, redactor, (message, cause) => new ToolError({ message, ...(cause === undefined ? {} : { error: cause }) }), ctx.app.version)\n'
            '  await ctx.tool.transform((editor) => editor.add({ name: "synthetic_probe", description: "permission rejection probe", options: { codemode: false }, input: { type: "object", properties: { kind: { type: "string" } }, required: ["kind"], additionalProperties: false }, async execute(input, tool) {\n'
            f'    if (process.env.V2_SMOKE_CANCEL === "1") {{ writeFileSync({json.dumps(str(started))}, "started"); await new Promise((_resolve, reject) => {{ const stop = () => {{ writeFileSync({json.dumps(str(aborted))}, "aborted"); reject(new Error({json.dumps(ABORT_CANARY)})) }}; if (tool.signal.aborted) stop(); else tool.signal.addEventListener("abort", stop, {{ once: true }}) }}); return {{ content: "CANCELLATION_BYPASSED" }} }}\n'
            '    try { await ctx.permission.assert({ sessionID: tool.sessionID, agent: tool.agent, source: { type: "tool", messageID: tool.messageID, id: tool.id }, action: "synthetic_ask", resources: ["synthetic-resource"], save: ["synthetic-resource"] }) } catch (error) { capturedDecline = error; throw error }\n'
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
        if mode in {"baseline", "host_clone", "drop_cause", "throw_after"}:
            env["V2_SMOKE_GUARD"] = "off"
        if mode in {"host_clone", "drop_cause", "throw_after"}:
            env["V2_SMOKE_CONTROL"] = mode
        if mode == "redactor_failure":
            env["V2_SMOKE_REDACTOR_FAIL"] = "1"
        if cancel:
            env["V2_SMOKE_CANCEL"] = "1"
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        with state.lock:
            start = len(state.requests)
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
                session = request(
                    base,
                    password,
                    "POST",
                    "/api/session",
                    {
                        "location": {"directory": str(project)},
                        "model": {"providerID": "capture", "id": "mock"},
                    },
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
                    home, (ABORT_CANARY, FEEDBACK_CANARY, REDACTOR_CANARY)
                )
                server_log = (root / "server.log").read_text(
                    encoding="utf-8", errors="replace"
                )
                control_observation = (
                    json.loads(identity_marker.read_text(encoding="utf-8"))
                    if identity_marker.is_file()
                    else {}
                )
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
                    "host_cause_is_captured": control_observation.get("same"),
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
        )
        print(
            json.dumps(
                {
                    "result": "PASS" if passed else "FAIL",
                    "cases": cases,
                    "cancellation": cancellation,
                    "controls": controls,
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
