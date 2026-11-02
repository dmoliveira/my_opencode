"""Exercise V2 worktree guards with disposable Git worktrees and OpenCode."""

from __future__ import annotations

import json
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


class WriteHandler(CaptureHandler):
    def do_POST(self) -> None:
        payload = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length") or "0"))
        )
        self.state.record(self.path, payload, [], False)
        messages = payload.get("messages", [])
        tool_names = [
            item.get("function", {}).get("name") for item in payload.get("tools", [])
        ]
        text = json.dumps(messages)
        safe = "SAFE_WRITE_PROBE" in text
        blocked = "BLOCK_WRITE_PROBE" in text
        finished = any(item.get("role") == "tool" for item in messages)
        if "write" in tool_names and (safe or blocked) and not finished:
            target = self.server.safe_target if safe else self.server.blocked_target
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_synthetic",
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps(
                                {"path": str(target), "content": "synthetic content"}
                            ),
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
    dist = ROOT / "plugin/gateway-core/dist/v2/worktree-guards.js"
    if not dist.is_file():
        print("FAIL: build gateway-core first")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), WriteHandler)
    state = CaptureState()
    server.capture_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="gateway-v2-worktree-") as temp:
            root = Path(temp)
            project, linked = root / "main", root / "linked"
            project.mkdir()
            env = isolated_env(root / "home", root / "audit.jsonl")
            env.pop("OPENCODE_SESSION_ID", None)
            for command in (
                ["git", "init", "--initial-branch=main"],
                ["git", "add", "seed.txt"],
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                ["git", "worktree", "add", "-b", "probe", str(linked)],
            ):
                if command[:2] == ["git", "add"]:
                    (project / "seed.txt").write_text("seed", encoding="utf-8")
                subprocess.run(
                    command,
                    cwd=project,
                    env=env,
                    capture_output=True,
                    check=True,
                    timeout=30,
                )
            plugin = project / "v2-probe"
            plugin.mkdir()
            server.safe_target = linked / "safe-created.txt"
            server.blocked_target = project / "blocked-created.txt"
            (plugin / "index.ts").write_text(
                'import { Plugin } from "@opencode/plugin"\n'
                f"import {{ registerV2WorktreeGuards }} from {json.dumps(dist.as_uri())}\n"
                'export default Plugin.define({ id: "v2-worktree-probe", async setup(ctx) {\n'
                "  return await registerV2WorktreeGuards(ctx.tool, async (sessionID) => (await ctx.session.get({ sessionID })).location.directory, {\n"
                "    directory: ctx.location.directory, writeExisting: { enabled: true },\n"
                '    primary: { enabled: true, allowedBranches: ["main", "master"], blockEdits: true, blockBranchSwitches: true },\n'
                '    workflow: { enabled: true, protectedBranches: ["main", "master"], blockEditsOnProtectedBranches: true }\n'
                "  })\n} })\n",
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
            results = [
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
                for prompt in ("SAFE_WRITE_PROBE", "BLOCK_WRITE_PROBE")
            ]
            with state.lock:
                requests = list(state.requests)
            tools = sorted(
                {
                    item.get("function", {}).get("name", "")
                    for request in requests
                    for item in request.get("tools", [])
                }
            )
            allowed = (
                server.safe_target.is_file()
                and server.safe_target.read_text() == "synthetic content"
            )
            blocked = (
                not server.blocked_target.exists()
                and "blocked in the primary" in (results[1].stdout + results[1].stderr)
            )
            passed = allowed and blocked and "write" in tools
            print(
                json.dumps(
                    {
                        "result": "PASS" if passed else "FAIL",
                        "linked_write_allowed": allowed,
                        "primary_write_blocked": blocked,
                        "returncodes": [result.returncode for result in results],
                    }
                )
            )
            if not passed:
                for result in results:
                    print((result.stderr + "\n" + result.stdout)[-4000:])
            return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
