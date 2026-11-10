"""Exercise the unconfigured V2 status writer with a private server and provider."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[4]
CANARY = "V2StatusOutputSynthetic_123456789"
MAX_REQUEST = 1024 * 1024


class Provider(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.lock = threading.Lock()
        self.requests = 0
        self.offered = False
        self.continued = False


class Handler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, _format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > MAX_REQUEST:
            self.send_error(400)
            return
        payload = json.loads(self.rfile.read(length))
        messages = payload.get("messages", [])
        offered = any(
            item.get("function", {}).get("name") == "shell"
            for item in payload.get("tools", [])
        )
        finished = any(item.get("role") == "tool" for item in messages)
        provider: Provider = self.server  # type: ignore[assignment]
        with provider.lock:
            provider.requests += 1
            provider.offered |= offered
            provider.continued |= finished
            if provider.requests > 8:
                self.send_error(429)
                return
        if offered and not finished:
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_status_probe",
                        "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": json.dumps({"command": "make validate"}),
                        },
                    }
                ],
            }
            reason = "tool_calls"
        else:
            delta, reason = (
                {"role": "assistant", "content": "STATUS_PROBE_DONE"},
                "stop",
            )
        chunks = [
            {
                "id": "status-probe",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "mock",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": "status-probe",
                "object": "chat.completion.chunk",
                "created": 1,
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode-bin", default="opencode")
    parser.add_argument("--with-tui", action="store_true")
    args = parser.parse_args()
    found = shutil.which(args.opencode_bin)
    if not found or (args.with_tui and not shutil.which("tmux")):
        raise RuntimeError("OpenCode and, for TUI testing, tmux are required")
    binary = str(Path(found).resolve())
    adapter = ROOT / "plugin/gateway-core/dist/v2/execution-status.js"
    sidebar = ROOT / "plugin/gateway-sidebar-v2"
    if not adapter.is_file():
        raise RuntimeError("build gateway-core before running the smoke")
    provider = Provider()
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="gateway-v2-status-live-") as raw:
            root = Path(raw)
            home, project, fake_bin = root / "home", root / "project", root / "bin"
            config, plugin = home / ".config/opencode", project / "status-probe"
            config.mkdir(parents=True)
            plugin.mkdir(parents=True)
            fake_bin.mkdir()
            make = fake_bin / "make"
            make.write_text(
                f"#!/bin/sh\n[ \"$#\" -eq 1 ] && [ \"$1\" = validate ] || exit 77\nprintf '%s\\n' '{CANARY}'\n"
            )
            make.chmod(0o700)
            (plugin / "index.ts").write_text(
                'import { Plugin } from "@opencode/plugin"\n'
                f"import {{ registerV2ExecutionStatus }} from {json.dumps(adapter.as_uri())}\n"
                'export default Plugin.define({ id: "v2-status-live-probe", async setup(ctx) {\n'
                "  return await registerV2ExecutionStatus(ctx, { enabled: true, maxSessions: 8, maxLabelChars: 80 })\n"
                "} })\n"
            )
            (project / "opencode.json").write_text(
                json.dumps(
                    {
                        "plugins": [str(plugin)],
                        "model": "capture/mock",
                        "permissions": [
                            {"action": "*", "resource": "*", "effect": "allow"}
                        ],
                        "providers": {
                            "capture": {
                                "name": "Local test",
                                "package": "@opencode/ai/providers/openai-compatible",
                                "settings": {
                                    "baseURL": f"http://127.0.0.1:{provider.server_port}/v1",
                                    "apiKey": "local-test-only",
                                },
                                "models": {
                                    "mock": {
                                        "name": "mock",
                                        "capabilities": {"tools": True},
                                    }
                                },
                            }
                        },
                    }
                )
            )
            if args.with_tui:
                (config / "cli.json").write_text(
                    json.dumps(
                        {"plugins": [str(sidebar)], "session": {"sidebar": "auto"}}
                    )
                )
            password = secrets.token_urlsafe(24)
            env = {
                key: os.environ[key]
                for key in ("USER", "LOGNAME", "LANG", "LC_ALL")
                if key in os.environ
            }
            env.update(
                {
                    "HOME": str(home),
                    "PATH": f"{fake_bin}:/usr/bin:/bin:/opt/homebrew/bin",
                    "SHELL": "/bin/sh",
                    "TMPDIR": str(root),
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "XDG_DATA_HOME": str(home / ".local/share"),
                    "XDG_CACHE_HOME": str(home / ".cache"),
                    "XDG_STATE_HOME": str(home / ".local/state"),
                    "CI": "1",
                    "TERM": "xterm-256color",
                    "OPENCODE_PASSWORD": password,
                    "OPENCODE_DISABLE_MODELS_FETCH": "1",
                    "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
                    "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
                }
            )
            version = subprocess.run(
                [binary, "--version"],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.strip()
            if version not in {"opencode v2.2.5", "opencode v2.2.6"} or (
                args.with_tui and version != "opencode v2.2.6"
            ):
                raise RuntimeError("unsupported OpenCode version for status smoke")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            auth = base64.b64encode(f"opencode:{password}".encode()).decode()
            opener = build_opener(ProxyHandler({}))

            def request(
                method: str, path: str, value: object = None, timeout: int = 3
            ) -> object:
                body = json.dumps(value).encode() if value is not None else None
                req = Request(
                    base + path,
                    data=body,
                    method=method,
                    headers={
                        "Authorization": "Basic " + auth,
                        "Content-Type": "application/json",
                    },
                )
                with opener.open(req, timeout=timeout) as response:
                    data = response.read(MAX_REQUEST + 1)
                if len(data) > MAX_REQUEST:
                    raise RuntimeError("private server response exceeded bound")
                return json.loads(data) if data else None

            with (root / "server.log").open("wb") as log:
                server = subprocess.Popen(
                    [binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                    cwd=project,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                tmux_target: str | None = None
                try:
                    for _ in range(100):
                        if server.poll() is not None:
                            raise RuntimeError("private server exited")
                        try:
                            if request("GET", "/api/info").get("pid") == server.pid:  # type: ignore[union-attr]
                                break
                        except (OSError, URLError):
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("private server did not become ready")

                    def mutate(
                        method: str, path: str, value: object = None, timeout: int = 3
                    ) -> object:
                        if (
                            server.poll() is not None
                            or request("GET", "/api/info").get("pid") != server.pid
                        ):  # type: ignore[union-attr]
                            raise RuntimeError("private server identity changed")
                        return request(method, path, value, timeout)

                    created = mutate(
                        "POST",
                        "/api/session",
                        {
                            "location": {"directory": str(project)},
                            "model": {"providerID": "capture", "id": "mock"},
                            "title": "Private status smoke",
                        },
                    )
                    session = created["data"]["id"]  # type: ignore[index]
                    if args.with_tui:
                        name = "ai-oc-v2-status-" + secrets.token_hex(5)
                        result = subprocess.run(
                            [
                                "tmux",
                                "new-session",
                                "-d",
                                "-P",
                                "-F",
                                "#{session_id}",
                                "-s",
                                name,
                                "-x",
                                "160",
                                "-y",
                                "45",
                                "-c",
                                str(project),
                                "env",
                                "-i",
                                *(f"{key}={value}" for key, value in env.items()),
                                binary,
                                "--server",
                                base,
                                "--session",
                                session,
                                str(project),
                            ],
                            capture_output=True,
                            text=True,
                            timeout=10,
                            check=True,
                        )
                        tmux_target = result.stdout.strip()
                        if (
                            not tmux_target.startswith("$")
                            or not tmux_target[1:].isdigit()
                        ):
                            raise RuntimeError("unexpected private tmux identity")
                    mutate(
                        "POST",
                        f"/api/session/{session}/prompt",
                        {"text": "Run the private validation fixture."},
                    )
                    mutate(
                        "POST", f"/api/experimental/session/{session}/wait", timeout=30
                    )
                    state_path = project / ".opencode/gateway-core.state.json"

                    def entries() -> object:
                        try:
                            return json.loads(state_path.read_text())[
                                "executionStatus"
                            ]["sessions"]
                        except (OSError, ValueError, KeyError, TypeError):
                            return None

                    for _ in range(100):
                        current = entries()
                        item = (
                            current.get(session) if isinstance(current, dict) else None
                        )
                        if (
                            isinstance(item, dict)
                            and item.get("last") == "Validation passed"
                            and item.get("next") == "Review changes"
                        ):
                            break
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("real V2 tool event did not update status")
                    if CANARY in state_path.read_text():
                        raise RuntimeError("tool output appeared in status state")
                    if (
                        state_path.is_symlink()
                        or state_path.parent.is_symlink()
                        or stat.S_IMODE(state_path.stat().st_mode) != 0o600
                        or stat.S_IMODE(state_path.parent.stat().st_mode) != 0o700
                    ):
                        raise RuntimeError("status state is not private")
                    if args.with_tui:
                        for _ in range(100):
                            screen = subprocess.run(
                                ["tmux", "capture-pane", "-t", tmux_target, "-p"],
                                capture_output=True,
                                text=True,
                                timeout=3,
                                check=True,
                            ).stdout
                            if (
                                "Validation passed" in screen
                                and "Review changes" in screen
                            ):
                                break
                            time.sleep(0.15)
                        else:
                            raise RuntimeError(
                                "V2 sidebar did not render the generated status"
                            )
                    with provider.lock:
                        if not provider.offered or not provider.continued:
                            raise RuntimeError(
                                "synthetic provider did not observe the shell round trip"
                            )
                    other = mutate(
                        "POST",
                        "/api/session",
                        {
                            "location": {"directory": str(project)},
                            "model": {"providerID": "capture", "id": "mock"},
                            "title": "Other private session",
                        },
                    )
                    other_id = other["data"]["id"]  # type: ignore[index]
                    if other_id == session:
                        raise RuntimeError("private session identities collided")
                    for _ in range(100):
                        current = entries()
                        other_entry = (
                            current.get(other_id) if isinstance(current, dict) else None
                        )
                        if (
                            isinstance(other_entry, dict)
                            and other_entry.get("last") == "Session ready"
                        ):
                            break
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("second session status was not created")
                    mutate("DELETE", f"/api/session/{session}")
                    for _ in range(100):
                        current = entries()
                        if (
                            isinstance(current, dict)
                            and session not in current
                            and current.get(other_id) == other_entry
                        ):
                            break
                        time.sleep(0.1)
                    else:
                        raise RuntimeError(
                            "deleted status remained or another session changed"
                        )
                    print(
                        json.dumps(
                            {
                                "result": "PASS",
                                "version": version,
                                "tool_status": True,
                                "deleted_status": True,
                                "tui_rendered": args.with_tui,
                            }
                        )
                    )
                    return 0
                finally:
                    if (
                        tmux_target
                        and tmux_target.startswith("$")
                        and tmux_target[1:].isdigit()
                    ):
                        subprocess.run(
                            ["tmux", "kill-session", "-t", tmux_target],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                            check=False,
                        )
                    if server.poll() is None:
                        os.killpg(server.pid, signal.SIGTERM)
                        try:
                            server.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(server.pid, signal.SIGKILL)
                            server.wait(timeout=5)
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
