"""Exercise the experimental V2 shell guards in an isolated OpenCode run."""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from gateway_secret_redaction_live_smoke import (
    CaptureHandler,
    CaptureState,
    isolated_env,
)

ROOT = Path(__file__).resolve().parent.parent
CANARY = "V2ToolOutputSyntheticSecret_123456789"


class ToolHandler(CaptureHandler):
    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
        payload = json.loads(raw)
        self.state.record(self.path, payload, [], False)
        messages = payload.get("messages", [])
        tools = payload.get("tools", [])
        tool_names = [item.get("function", {}).get("name") for item in tools]
        user_text = json.dumps(messages)
        finished = any(item.get("role") == "tool" for item in messages)
        safe = "SAFE_SHELL_PROBE" in user_text
        blocked = "BLOCK_SHELL_PROBE" in user_text
        target = self.server.safe_marker if safe else self.server.blocked_marker
        if "shell" in tool_names and (safe or blocked) and not finished:
            word = "ALLOWED_SYNTHETIC" if safe else "BLOCKED_SYNTHETIC"
            command = (
                f"cat {shlex.quote(str(self.server.secret_file))}; "
                f"printf {word} > {shlex.quote(str(target))}"
                if safe
                else f"printf {word} > {shlex.quote(str(target))}"
            )
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_synthetic",
                        "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": json.dumps({"command": command}),
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
                "id": "chatcmpl-v2",
                "object": "chat.completion.chunk",
                "created": now,
                "model": "mock",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-v2",
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


def main() -> int:
    dist = ROOT / "plugin/gateway-core/dist/v2/shell-guards.js"
    output_dist = ROOT / "plugin/gateway-core/dist/v2/tool-output-redaction.js"
    redactor_dist = ROOT / "plugin/gateway-core/dist/hooks/shared/secret-redaction.js"
    if not all(path.is_file() for path in (dist, output_dist, redactor_dist)):
        print("FAIL: build gateway-core first")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), ToolHandler)
    state = CaptureState()
    server.capture_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="gateway-v2-shell-") as temp:
            root = Path(temp)
            project = root / "project"
            plugin = project / "v2-probe"
            plugin.mkdir(parents=True)
            server.safe_marker = project / "safe-marker"
            server.blocked_marker = project / "blocked-marker"
            server.secret_file = project / "synthetic-tool-output.txt"
            server.secret_file.write_text(CANARY, encoding="utf-8")
            (plugin / "index.ts").write_text(
                'import { Plugin } from "@opencode/plugin"\n'
                f"import {{ registerV2ShellGuards }} from {json.dumps(dist.as_uri())}\n"
                f"import {{ registerV2ToolOutputRedaction }} from {json.dumps(output_dist.as_uri())}\n"
                f"import {{ createSecretRedactor }} from {json.dumps(redactor_dist.as_uri())}\n"
                'export default Plugin.define({ id: "v2-shell-probe", async setup(ctx) {\n'
                f'  const redactor = createSecretRedactor({{ patterns: [{json.dumps(CANARY)}], redactionToken: "[REDACTED]", limits: {{ maxDepth: 32, maxNodes: 10000, maxChars: 1000000 }} }})\n'
                "  const disposeOutput = await registerV2ToolOutputRedaction(ctx.tool, redactor)\n"
                "  const disposeShell = await registerV2ShellGuards(ctx.tool, async (sessionID) => (await ctx.session.get({ sessionID })).location.directory, {\n"
                "    directory: ctx.location.directory, noninteractive: { enabled: true, injectEnvPrefix: false, envPrefixes: [], prefixCommands: [], blockedPatterns: [] },\n"
                '    dangerous: { enabled: true, blockedPatterns: ["BLOCKED_SYNTHETIC"] }\n'
                "  })\n  return async () => { await disposeShell(); await disposeOutput() }\n} })\n",
                encoding="utf-8",
            )
            config = {
                "model": "capture/mock",
                "plugins": [str(plugin)],
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
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
            env = isolated_env(root / "home", root / "audit.jsonl")
            env.pop("OPENCODE_SESSION_ID", None)
            results = []
            for prompt in ("SAFE_SHELL_PROBE", "BLOCK_SHELL_PROBE"):
                results.append(
                    subprocess.run(
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
                )
            with state.lock:
                requests = list(state.requests)
            captured = json.dumps(requests)
            tool_names = sorted(
                {
                    item.get("function", {}).get("name", "")
                    for request in requests
                    for item in request.get("tools", [])
                }
            )
            allowed = (
                server.safe_marker.is_file()
                and server.safe_marker.read_text() == "ALLOWED_SYNTHETIC"
            )
            blocked = not server.blocked_marker.exists() and "Blocked dangerous" in (
                results[1].stdout + results[1].stderr
            )
            output_redacted = CANARY not in captured and "[REDACTED]" in captured
            passed = allowed and blocked and output_redacted and "shell" in tool_names
            print(
                json.dumps(
                    {
                        "result": "PASS" if passed else "FAIL",
                        "allowed_executed": allowed,
                        "unsafe_blocked": blocked,
                        "tool_output_redacted": output_redacted,
                        "exposed_tools": tool_names,
                        "returncodes": [item.returncode for item in results],
                    }
                )
            )
            if not passed:
                for result in results:
                    print(
                        (result.stderr + "\n" + result.stdout).replace(
                            CANARY, "[CANARY]"
                        )[-4000:]
                    )
            return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
