#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
USER_CANARY = "Wave2SyntheticCanary_123456789"
SYSTEM_CANARY = "Wave2SystemCanary_123456789"
USER_CONTROL = "wave2-user-control-marker"
SYSTEM_CONTROL = "wave2-system-control-marker"
REDACTION_TOKEN = "[REDACTED_SECRET]"
FAKE_API_KEY = "wave2-local-fake-key"


def prepare_private_output_dir(path: Path) -> None:
    if path.is_symlink():
        raise PermissionError("secret smoke output directory must not be a symlink")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise PermissionError("secret smoke output directory must be owner-controlled")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        path.chmod(0o700)
        metadata = path.lstat()
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise PermissionError("secret smoke output directory must be owner-only")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify gateway secret redaction against a captured localhost provider request."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "runtime" / "harness-wave-2" / "secret-redaction-live",
    )
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from iter_strings(item)


def safe_artifact_text(text: str) -> str:
    sanitized = text
    for value in (USER_CANARY, SYSTEM_CANARY, FAKE_API_KEY):
        sanitized = sanitized.replace(value, "[SYNTHETIC_VALUE_REMOVED]")
    return sanitized


class CaptureState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.header_names: list[list[str]] = []
        self.authorization_present: list[bool] = []

    def record(
        self,
        path: str,
        payload: dict[str, Any],
        header_names: list[str],
        authorization_present: bool,
    ) -> None:
        with self.lock:
            self.paths.append(path)
            self.requests.append(payload)
            self.header_names.append(header_names)
            self.authorization_present.append(authorization_present)


class CaptureHandler(BaseHTTPRequestHandler):
    server_version = "Wave2Capture/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    @property
    def state(self) -> CaptureState:
        return self.server.capture_state  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            body = json.dumps(
                {
                    "object": "list",
                    "data": [{"id": "mock", "object": "model", "owned_by": "wave2"}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return
        if not isinstance(payload, dict):
            self.send_error(400)
            return
        self.state.record(
            self.path,
            payload,
            sorted(str(name).lower() for name in self.headers),
            bool(self.headers.get("Authorization")),
        )

        now = int(time.time())
        chunks = [
            {
                "id": "chatcmpl-wave2",
                "object": "chat.completion.chunk",
                "created": now,
                "model": "mock",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "MOCK_OK"},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-wave2",
                "object": "chat.completion.chunk",
                "created": now,
                "model": "mock",
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "stop"}
                ],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        body += "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def isolated_env(home: Path, audit_path: Path) -> dict[str, str]:
    env = {
        key: value
        for key in ("LANG", "LC_ALL", "LOGNAME", "PATH", "SHELL", "TMPDIR", "USER")
        if (value := os.environ.get(key))
    }
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "CI": "true",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GCM_INTERACTIVE": "never",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT": "1",
            "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_path),
        }
    )
    session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    if session_id:
        env["OPENCODE_SESSION_ID"] = session_id
    return env


def local_persistence_observed(data_home: Path) -> bool | None:
    databases = list(data_home.rglob("opencode.db"))
    if not databases:
        return None
    for database in databases:
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            try:
                for table in ("message", "part"):
                    exists = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if not exists:
                        continue
                    for (raw,) in connection.execute(f"SELECT data FROM {table}"):
                        text = str(raw or "")
                        if USER_CANARY in text or SYSTEM_CANARY in text:
                            return True
            finally:
                connection.close()
        except sqlite3.Error:
            continue
    return False


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    dist_entry = repo_root / "plugin" / "gateway-core" / "dist" / "index.js"
    if not dist_entry.exists():
        return {"result": "FAIL", "reason": "gateway_dist_missing", "path": str(dist_entry)}
    if shutil.which("opencode") is None:
        return {"result": "FAIL", "reason": "opencode_missing"}

    output_dir = args.output_dir.resolve()
    prepare_private_output_dir(output_dir)
    audit_path = output_dir / "gateway-events.jsonl"
    stdout_path = output_dir / "opencode.stdout.jsonl"
    stderr_path = output_dir / "opencode.stderr.log"
    for path in (audit_path, stdout_path, stderr_path):
        if path.exists():
            path.unlink()

    port = reserve_port()
    state = CaptureState()
    server = ThreadingHTTPServer(("127.0.0.1", port), CaptureHandler)
    server.capture_state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    with tempfile.TemporaryDirectory(prefix="my-opencode-secret-smoke-") as raw_tmp:
        sandbox = Path(raw_tmp).resolve()
        home = sandbox / "home"
        project = sandbox / "project"
        config_dir = home / ".config" / "opencode"
        config_dir.mkdir(parents=True, exist_ok=True)
        project.mkdir(parents=True, exist_ok=True)
        (project / "AGENTS.md").write_text(
            f"# Synthetic smoke instructions\n\n{SYSTEM_CONTROL}\nsecret={SYSTEM_CANARY}\n",
            encoding="utf-8",
        )
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": "wave2/mock",
            "small_model": "wave2/mock",
            "default_agent": "build",
            "instructions": ["AGENTS.md"],
            "provider": {
                "wave2": {
                    "name": "Wave2 Local Capture",
                    "npm": "@ai-sdk/openai-compatible",
                    "options": {
                        "apiKey": FAKE_API_KEY,
                        "baseURL": f"http://127.0.0.1:{port}/v1",
                    },
                    "models": {"mock": {"name": "Wave2 Mock"}},
                }
            },
            "plugin": [dist_entry.as_uri()],
            "lsp": False,
            "formatter": False,
            "permission": "allow",
        }
        (config_dir / "opencode.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        prompt = (
            f"Reply with exactly MOCK_OK. {USER_CONTROL} "
            f"password={USER_CANARY}"
        )
        command = [
            "opencode",
            "run",
            "--model",
            "wave2/mock",
            "--agent",
            "build",
            "--format",
            "json",
            "--title",
            "Gateway secret redaction transport smoke",
            prompt,
        ]
        child_env = isolated_env(home, audit_path)
        sensitive_markers = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")
        host_sensitive_keys = {
            key
            for key in os.environ
            if any(marker in key.upper() for marker in sensitive_markers)
        }
        forwarded_host_sensitive_keys = sorted(host_sensitive_keys.intersection(child_env))
        try:
            completed = subprocess.run(
                command,
                cwd=project,
                env=child_env,
                text=True,
                capture_output=True,
                timeout=max(10, args.timeout_seconds),
                check=False,
            )
            return_code = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as error:
            return_code = 124
            stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
            stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        stdout_path.write_text(safe_artifact_text(stdout), encoding="utf-8")
        stderr_path.write_text(safe_artifact_text(stderr), encoding="utf-8")
        stdout_path.chmod(0o600)
        stderr_path.chmod(0o600)
        with state.lock:
            requests = list(state.requests)
            paths = list(state.paths)
            captured_header_names = list(state.header_names)
            authorization_present = any(state.authorization_present)
        captured_strings = [text for request in requests for text in iter_strings(request)]
        captured_text = "\n".join(captured_strings)
        audit_text = audit_path.read_text(encoding="utf-8", errors="replace") if audit_path.exists() else ""
        local_persistence = local_persistence_observed(home / ".local" / "share")

    canaries_absent = USER_CANARY not in captured_text and SYSTEM_CANARY not in captured_text
    controls_present = USER_CONTROL in captured_text and SYSTEM_CONTROL in captured_text
    redaction_present = REDACTION_TOKEN in captured_text
    audit_safe = USER_CANARY not in audit_text and SYSTEM_CANARY not in audit_text
    bootstrap_seen = "gateway_runtime_bootstrap" in audit_text
    redaction_audit_seen = "provider_boundary_secrets_redacted" in audit_text
    passed = all(
        (
            return_code == 0,
            bool(requests),
            canaries_absent,
            controls_present,
            redaction_present,
            audit_safe,
            bootstrap_seen,
            redaction_audit_seen,
            not forwarded_host_sensitive_keys,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "reason": "provider_request_redacted" if passed else "provider_request_validation_failed",
        "returncode": return_code,
        "request_count": len(requests),
        "request_paths": paths,
        "controls_present": controls_present,
        "canaries_absent": canaries_absent,
        "redaction_token_present": redaction_present,
        "bootstrap_seen": bootstrap_seen,
        "redaction_audit_seen": redaction_audit_seen,
        "audit_safe": audit_safe,
        "captured_header_names": captured_header_names,
        "authorization_header_present": authorization_present,
        "authorization_header_note": "The expected localhost-only fake provider key is sent; header values are never retained.",
        "forwarded_host_sensitive_env_keys": forwarded_host_sensitive_keys,
        "host_credentials_forwarded": bool(forwarded_host_sensitive_keys),
        "local_persistence_observed": local_persistence,
        "local_persistence_note": "Provider-boundary redaction does not scrub the isolated local runtime database.",
        "gateway_dist": str(dist_entry),
        "audit_path": str(audit_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def main() -> int:
    args = parse_args()
    report = run_probe(args)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
