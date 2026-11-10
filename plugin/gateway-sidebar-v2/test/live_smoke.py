#!/usr/bin/env python3
"""Exercise the V2 sidebar in an isolated real OpenCode TUI without a model call."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

PLUGIN = Path(__file__).resolve().parents[1]
VERSION = "opencode v2.2.6"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opencode-bin", default="opencode")
    args = parser.parse_args()
    binary = shutil.which(args.opencode_bin)
    if not binary or not shutil.which("tmux"):
        raise RuntimeError("OpenCode and tmux are required")
    binary = str(Path(binary).resolve())
    name = "ai-oc-sidebar-v2-" + secrets.token_hex(5)

    with tempfile.TemporaryDirectory(prefix="gateway-sidebar-v2-live-") as raw:
        root = Path(raw)
        home, project = root / "home", root / "project"
        config = home / ".config" / "opencode"
        config.mkdir(parents=True)
        project.mkdir()
        (config / "opencode.json").write_text(
            json.dumps(
                {
                    "model": "capture/mock",
                    "providers": {
                        "capture": {
                            "name": "Local test",
                            "package": "@opencode/ai/providers/openai-compatible",
                            "settings": {
                                "baseURL": "http://127.0.0.1:1/v1",
                                "apiKey": "local-test-only",
                            },
                            "models": {"mock": {"name": "mock"}},
                        }
                    },
                }
            )
        )
        cli = config / "cli.json"

        def configure(plugins: list[str]) -> None:
            cli.write_text(
                json.dumps({"plugins": plugins, "session": {"sidebar": "auto"}})
            )

        configure([str(PLUGIN)])
        password = secrets.token_urlsafe(24)
        env = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "SHELL", "USER", "LOGNAME")
            if key in os.environ
        }
        env.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "TMPDIR": str(root),
                "CI": "1",
                "TERM": "xterm-256color",
                "OPENCODE_PASSWORD": password,
                "OPENCODE_DISABLE_MODELS_FETCH": "1",
                "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            }
        )
        version = subprocess.run(
            [binary, "--version"],
            env=env,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        if version.stdout.strip() != VERSION:
            raise RuntimeError("OpenCode 2.2.6 is required for this smoke")

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        authorization = base64.b64encode(("opencode:" + password).encode()).decode()
        opener = build_opener(ProxyHandler({}))

        def request(method: str, path: str, data: object = None) -> dict:
            body = json.dumps(data).encode() if data is not None else None
            req = Request(
                base + path,
                data=body,
                method=method,
                headers={
                    "Authorization": "Basic " + authorization,
                    "Content-Type": "application/json",
                },
            )
            with opener.open(req, timeout=2) as response:
                return json.load(response)

        with (root / "server.log").open("w") as log:
            server = subprocess.Popen(
                [binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                cwd=project,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            tmux_target: str | None = None
            try:
                for _ in range(100):
                    try:
                        if request("GET", "/api/info").get("pid") == server.pid:
                            break
                    except OSError:
                        pass
                    if server.poll() is not None:
                        raise RuntimeError("isolated server exited")
                    time.sleep(0.1)
                else:
                    raise RuntimeError("isolated server did not start")
                if request("GET", "/api/info").get("pid") != server.pid:
                    raise RuntimeError("isolated server identity changed")
                created = request(
                    "POST",
                    "/api/session",
                    {
                        "location": {"directory": str(project)},
                        "model": {"providerID": "capture", "id": "mock"},
                        "title": "Sidebar smoke",
                    },
                )
                session = created["data"]["id"]
                state = project / ".opencode"
                state.mkdir(mode=0o700)
                os.chmod(state, 0o700)

                def update(last: str) -> None:
                    temp = state / ".gateway-core.state.json.test"
                    temp.write_text(
                        json.dumps(
                            {
                                "executionStatus": {
                                    "version": 1,
                                    "sessions": {
                                        session: {
                                            "sessionId": session,
                                            "last": last,
                                            "next": "Review evidence",
                                            "updatedAt": datetime.now(UTC).isoformat(),
                                        },
                                    },
                                }
                            }
                        )
                    )
                    os.chmod(temp, 0o600)
                    temp.replace(state / "gateway-core.state.json")

                update("Initial milestone")
                created_tui = subprocess.run(
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
                    check=True,
                    capture_output=True,
                    text=True,
                )
                tmux_target = created_tui.stdout.strip()
                if not tmux_target.startswith("$") or not tmux_target[1:].isdigit():
                    raise RuntimeError("unexpected tmux session identity")

                def wait_for(needle: str, present: bool = True) -> str:
                    for _ in range(100):
                        time.sleep(0.15)
                        result = subprocess.run(
                            ["tmux", "capture-pane", "-t", tmux_target, "-p"],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if result.returncode:
                            raise RuntimeError("isolated TUI exited")
                        if (needle in result.stdout) == present:
                            return result.stdout
                    raise RuntimeError("sidebar did not reach the expected state")

                screen = wait_for("Initial milestone")
                if "Execution" not in screen or "Review evidence" not in screen:
                    raise RuntimeError("sidebar content incomplete")
                update("Validated milestone")
                wait_for("Validated milestone")
                configure([])
                wait_for("Validated milestone", present=False)
                configure([str(PLUGIN)])
                wait_for("Validated milestone")
                print(
                    "PASS: V2 sidebar rendered, refreshed, unloaded, and reloaded; no prompts submitted"
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
                        check=False,
                    )
                if server.poll() is None:
                    os.killpg(server.pid, signal.SIGTERM)
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(server.pid, signal.SIGKILL)
                        server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
