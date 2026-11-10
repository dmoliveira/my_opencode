"""Exercise experimental V2 tool-error redaction against a localhost provider."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from gateway_secret_redaction_live_smoke import (
    CaptureHandler,
    CaptureState,
    isolated_env,
)

ROOT = Path(__file__).resolve().parent.parent
MESSAGE_CANARY = "V2ToolErrorMessageSynthetic_123456789"
METADATA_CANARY = "V2ToolErrorMetadataSynthetic_123456789"
CAUSE_CANARY = "V2ToolErrorCauseSynthetic_123456789"
REDACTOR_CANARY = "V2RedactorExceptionSynthetic_123456789"
CANARIES = (MESSAGE_CANARY, METADATA_CANARY, CAUSE_CANARY, REDACTOR_CANARY)


class ErrorHandler(CaptureHandler):
    def do_POST(self) -> None:
        payload = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length") or "0"))
        )
        self.state.record(self.path, payload, [], False)
        messages = payload.get("messages", [])
        names = [
            item.get("function", {}).get("name") for item in payload.get("tools", [])
        ]
        text = json.dumps(messages)
        finished = any(item.get("role") == "tool" for item in messages)
        if "synthetic_probe" in names and not finished:
            kind = (
                "bootstrap"
                if "BOOTSTRAP_PERMISSION_PROBE" in text
                else "safe"
                if "SAFE_ERROR_PROBE" in text
                else "completed"
                if "COMPLETED_FAILURE_PROBE" in text
                else "permission"
                if "PERMISSION_DENY_PROBE" in text
                else "message_only"
                if "MESSAGE_ONLY_PROBE" in text
                else "secret"
            )
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_synthetic",
                        "type": "function",
                        "function": {
                            "name": "synthetic_probe",
                            "arguments": json.dumps({"kind": kind}),
                        },
                    }
                ],
            }
            reason = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "MOCK_OK"}
            reason = "stop"
        now = int(time.time())
        chunks = [
            {
                "id": "chatcmpl-v2-error",
                "object": "chat.completion.chunk",
                "created": now,
                "model": "mock",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-v2-error",
                "object": "chat.completion.chunk",
                "created": now,
                "model": "mock",
                "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
            },
        ]
        body = (
            "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def persisted_markers(
    home: Path, extra_needles: tuple[str, ...] = ()
) -> dict[str, bool]:
    database = home / ".local" / "share" / "opencode" / "opencode.db"
    if not database.is_file():
        raise RuntimeError("isolated V2 session database missing")
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        needles = (
            *CANARIES,
            "error-control [REDACTED]",
            "safe-failure-control",
            *extra_needles,
        )
        found = dict.fromkeys(needles, False)
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            quoted_table = '"' + table.replace('"', '""') + '"'
            columns = [
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({quoted_table})")
            ]
            for column in columns:
                quoted_column = '"' + column.replace('"', '""') + '"'
                for needle in needles:
                    if not found[needle]:
                        found[needle] = (
                            connection.execute(
                                f"SELECT 1 FROM {quoted_table} WHERE instr(CAST({quoted_column} AS TEXT), ?) > 0 LIMIT 1",
                                (needle,),
                            ).fetchone()
                            is not None
                        )
        return found
    finally:
        connection.close()


def run_case(
    server: ThreadingHTTPServer, state: CaptureState, case: str
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gateway-v2-tool-error-") as temp:
        root = Path(temp)
        home, project = root / "home", root / "project"
        plugin = project / "v2-probe"
        plugin.mkdir(parents=True)
        unexpected_decline = root / "unexpected-plain-decline"
        dist = ROOT / "plugin/gateway-core/dist"
        (plugin / "index.ts").write_text(
            'import { Plugin } from "@opencode/plugin"\n'
            'import { Error as ToolError } from "@opencode/plugin/promise/tool"\n'
            'import { writeFileSync } from "node:fs"\n'
            f"import {{ registerV2ToolOutputRedaction }} from {json.dumps((dist / 'v2/tool-output-redaction.js').as_uri())}\n"
            f"import {{ createSecretRedactor }} from {json.dumps((dist / 'hooks/shared/secret-redaction.js').as_uri())}\n"
            'export default Plugin.define({ id: "v2-tool-error-probe", async setup(ctx) {\n'
            f'  const redactor = process.env.V2_SMOKE_REDACTOR_FAIL === "1" ? {{ async redactMutableValueAsync() {{ throw new Error({json.dumps(REDACTOR_CANARY)}) }} }} : createSecretRedactor({{ patterns: {json.dumps(list(CANARIES))}, redactionToken: "[REDACTED]", limits: {{ maxDepth: 32, maxNodes: 10000, maxChars: 1000000 }} }})\n'
            # This non-interactive fixture never exercises plain rejection.
            '  const fixtureOnlyDecline = Object.assign(new Error(), { _tag: "Permission.DeclinedError" })\n'
            f'  await ctx.tool.hook("execute.after", event => {{ if (event.status === "error" && Object.getOwnPropertyDescriptor(event.error, "error")?.value?._tag === "Permission.DeclinedError") writeFileSync({json.dumps(str(unexpected_decline))}, "unexpected") }})\n'
            '  if (process.env.V2_SMOKE_GUARD !== "off") await registerV2ToolOutputRedaction(ctx.tool, redactor, (message, cause) => new ToolError({ message, ...(cause === undefined ? {} : { error: cause }) }), ctx.app.version, () => fixtureOnlyDecline)\n'
            '  await ctx.tool.transform((editor) => editor.add({ name: "synthetic_probe", description: "synthetic error probe", options: { codemode: false }, input: { type: "object", properties: { kind: { type: "string" } }, required: ["kind"], additionalProperties: false }, async execute(input, tool) {\n'
            '    if (input.kind === "permission") { await ctx.permission.assert({ sessionID: tool.sessionID, agent: tool.agent, source: { type: "tool", messageID: tool.messageID, id: tool.id }, action: "synthetic_blocked_action", resources: ["synthetic-resource"], save: ["synthetic-resource"] }); return { content: "PERMISSION_BYPASSED" } }\n'
            f'    if (input.kind === "completed") return {{ content: "result-control {MESSAGE_CANARY}" }}\n'
            '    if (input.kind === "safe") throw new ToolError({ message: "safe-failure-control" })\n'
            f'    if (input.kind === "message_only") throw new ToolError({{ message: "error-control {MESSAGE_CANARY}" }})\n'
            f'    throw new ToolError({{ message: "error-control {MESSAGE_CANARY}", metadata: {{ detail: "{METADATA_CANARY}" }}, error: new Error("{CAUSE_CANARY}") }})\n'
            "  } }))\n} })\n",
            encoding="utf-8",
        )
        config = {
            "model": "capture/mock",
            "plugins": [str(plugin)],
            "permissions": [
                {"action": "*", "resource": "*", "effect": "allow"},
                {
                    "action": "synthetic_blocked_action",
                    "resource": "*",
                    "effect": "deny",
                },
            ],
            "providers": {
                "capture": {
                    "name": "Local capture",
                    "package": "@opencode/ai/providers/openai-compatible",
                    "settings": {
                        "baseURL": f"http://127.0.0.1:{server.server_port}/v1",
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
        if case in {"baseline", "baseline_message", "baseline_permission"}:
            env["V2_SMOKE_GUARD"] = "off"
        if case in {
            "error_redactor_failure",
            "completed_redactor_failure",
            "permission_redactor_failure",
        }:
            env["V2_SMOKE_REDACTOR_FAIL"] = "1"
        prompt = {
            "safe": "SAFE_ERROR_PROBE",
            "completed_redactor_failure": "COMPLETED_FAILURE_PROBE",
            "baseline_message": "MESSAGE_ONLY_PROBE",
            "secret_message": "MESSAGE_ONLY_PROBE",
            "baseline_permission": "PERMISSION_DENY_PROBE",
            "permission": "PERMISSION_DENY_PROBE",
            "permission_redactor_failure": "PERMISSION_DENY_PROBE",
        }.get(case, "SECRET_ERROR_PROBE")
        with state.lock:
            start = len(state.requests)
        result = subprocess.run(
            [
                "opencode",
                "run",
                "--standalone",
                "--auto",
                "--model",
                "capture/mock",
                prompt,
            ],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        with state.lock:
            requests = list(state.requests[start:])
        wire = json.dumps(requests)
        terminal = result.stdout + result.stderr
        persisted = persisted_markers(home)
        offered = any(
            item.get("function", {}).get("name") == "synthetic_probe"
            for request in requests
            for item in request.get("tools", [])
        )
        tool_returned = any(
            item.get("role") == "tool"
            for request in requests
            for item in request.get("messages", [])
        )
        case_result = {
            "returncode": result.returncode,
            "tool_offered": offered,
            "tool_returned": tool_returned,
            "message_on_wire": MESSAGE_CANARY in wire,
            "message_in_terminal": MESSAGE_CANARY in terminal,
            "message_in_database": persisted[MESSAGE_CANARY],
            "any_canary_on_wire": any(canary in wire for canary in CANARIES),
            "any_canary_in_terminal": any(canary in terminal for canary in CANARIES),
            "any_canary_in_database": any(persisted[canary] for canary in CANARIES),
            "redaction_on_wire": "error-control [REDACTED]" in wire,
            "redaction_in_terminal": "error-control [REDACTED]" in terminal,
            "redaction_in_database": persisted["error-control [REDACTED]"],
            "safe_message_on_wire": "safe-failure-control" in wire,
            "safe_message_in_terminal": "safe-failure-control" in terminal,
            "safe_message_in_database": persisted["safe-failure-control"],
            "error_withheld_on_wire": "Tool execution failed; details withheld by gateway"
            in wire,
            "output_withheld_on_wire": "Tool output withheld because redaction failed"
            in wire,
            "permission_denied_on_wire": "Permission denied: synthetic_blocked_action"
            in wire,
            "permission_denied_in_terminal": "Permission denied: synthetic_blocked_action"
            in terminal,
            "permission_bypassed": "PERMISSION_BYPASSED" in wire
            or "PERMISSION_BYPASSED" in terminal,
            "unexpected_plain_decline": unexpected_decline.is_file(),
        }
        return case_result


def main() -> int:
    dist = ROOT / "plugin/gateway-core/dist/v2/tool-output-redaction.js"
    if not dist.is_file():
        print("FAIL: build gateway-core first")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), ErrorHandler)
    state = CaptureState()
    server.capture_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cases = {
            name: run_case(server, state, name)
            for name in (
                "baseline",
                "baseline_message",
                "secret",
                "secret_message",
                "safe",
                "error_redactor_failure",
                "completed_redactor_failure",
                "baseline_permission",
                "permission",
                "permission_redactor_failure",
            )
        }
        active = lambda row: (
            row["returncode"] == 0 and row["tool_offered"] and row["tool_returned"]
        )
        clean = lambda row: (
            not any(
                row[key]
                for key in (
                    "any_canary_on_wire",
                    "any_canary_in_terminal",
                    "any_canary_in_database",
                )
            )
        )
        baseline = cases["baseline"]
        baseline_message = cases["baseline_message"]
        secret = cases["secret"]
        secret_message = cases["secret_message"]
        safe = cases["safe"]
        error_failure = cases["error_redactor_failure"]
        completed_failure = cases["completed_redactor_failure"]
        baseline_permission = cases["baseline_permission"]
        permission = cases["permission"]
        permission_failure = cases["permission_redactor_failure"]
        passed = (
            all(active(row) and not row["unexpected_plain_decline"] for row in cases.values())
            and all(
                baseline[key]
                for key in (
                    "any_canary_on_wire",
                    "any_canary_in_terminal",
                    "any_canary_in_database",
                )
            )
            and all(
                baseline_message[key]
                for key in (
                    "message_on_wire",
                    "message_in_terminal",
                    "message_in_database",
                )
            )
            and clean(secret_message)
            and all(
                secret_message[key]
                for key in (
                    "redaction_on_wire",
                    "redaction_in_terminal",
                    "redaction_in_database",
                )
            )
            and clean(secret)
            and all(
                secret[key]
                for key in (
                    "redaction_on_wire",
                    "redaction_in_terminal",
                    "redaction_in_database",
                )
            )
            and clean(safe)
            and all(
                safe[key]
                for key in (
                    "safe_message_on_wire",
                    "safe_message_in_terminal",
                    "safe_message_in_database",
                )
            )
            and clean(error_failure)
            and error_failure["error_withheld_on_wire"]
            and clean(completed_failure)
            and completed_failure["output_withheld_on_wire"]
            and all(
                row["permission_denied_on_wire"]
                and row["permission_denied_in_terminal"]
                for row in (baseline_permission, permission)
            )
            and all(
                clean(row)
                for row in (baseline_permission, permission, permission_failure)
            )
            and permission_failure["error_withheld_on_wire"]
            and not any(
                row["permission_bypassed"]
                for row in (baseline_permission, permission, permission_failure)
            )
        )
        print(json.dumps({"result": "PASS" if passed else "FAIL", "cases": cases}))
        return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
