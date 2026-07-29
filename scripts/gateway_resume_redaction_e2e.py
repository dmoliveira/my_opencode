#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import threading
import time
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
EXPECTED_OPENCODE_VERSION = "1.18.5"
LEGACY_MAX_CHARS = 2_097_152
LARGE_HISTORY_CHARS = 2_120_000
MAX_REQUEST_BYTES = 8 * 1024 * 1024

BOOTSTRAP_CONTROL = "RESUME_E2E_BOOTSTRAP_CONTROL"
HISTORY_CONTROL = "RESUME_E2E_HISTORY_CONTROL"
REASONING_CONTROL = "RESUME_E2E_REASONING_CONTROL"
TOOL_INPUT_CONTROL = "RESUME_E2E_TOOL_INPUT_CONTROL"
TOOL_OUTPUT_CONTROL = "RESUME_E2E_TOOL_OUTPUT_CONTROL"
RESUME_CONTROL = "RESUME_E2E_TRANSPORT_CONTROL"
MUTABLE_SECRET = "MutableResumeSecret_123456"
UI_ONLY_CANARY = "sk-ui-only-patch-collision-1234567890"
UI_PREVIEW_CANARY = "token=UiOnlyResumeSecret_123456"
CIPHERTEXT = f"{'A' * 128}-sk-e2e-ciphertext-collision-1234567890"
REDACTION_TOKEN = "[REDACTED_SECRET]"
EXPECTED_PROVIDER_ERROR = "EXPECTED_RESUME_E2E_CAPTURE_400"
SEED_API_KEY = "resume-e2e-local-seed-key"
OPENAI_API_KEY = "resume-e2e-local-openai-key"
GOOGLE_KEY_COLLISION = f"AIza{'A' * 20}"


def png_chunk(chunk_type: str, data: bytes = b"") -> bytes:
    chunk_type_bytes = chunk_type.encode("ascii")
    checksum = binascii.crc32(chunk_type_bytes + data) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + chunk_type_bytes
        + data
        + struct.pack(">I", checksum)
    )


def build_png_collision_data_url() -> str:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    collision_bytes = base64.b64decode(GOOGLE_KEY_COLLISION, validate=True)
    if base64.b64encode(collision_bytes).decode("ascii") != GOOGLE_KEY_COLLISION:
        raise RuntimeError("png_collision_not_canonical_base64")
    png = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            png_chunk("IHDR", header),
            png_chunk("ruSt", b"\x00" + collision_bytes),
            png_chunk("IDAT", zlib.compress(b"\x00\x00\x00\x00\xff")),
            png_chunk("IEND"),
        ]
    )
    encoded = base64.b64encode(png).decode("ascii")
    if GOOGLE_KEY_COLLISION not in encoded:
        raise RuntimeError("png_collision_missing_from_transport")
    return f"data:image/png;base64,{encoded}"


PNG_ATTACHMENT_DATA_URL = build_png_collision_data_url()


def build_binary_collision_data_url(mime: str, prefix: bytes, suffix: bytes) -> str:
    if len(prefix) % 3 != 0:
        raise RuntimeError("binary_collision_prefix_unaligned")
    collision_bytes = base64.b64decode(GOOGLE_KEY_COLLISION, validate=True)
    encoded = base64.b64encode(prefix + collision_bytes + suffix).decode("ascii")
    if GOOGLE_KEY_COLLISION not in encoded:
        raise RuntimeError("binary_collision_missing_from_transport")
    return f"data:{mime};base64,{encoded}"


JPEG_ATTACHMENT_DATA_URL = build_binary_collision_data_url(
    "image/jpeg", b"\xff\xd8\xff", b"\xff\xd9"
)
PDF_ATTACHMENT_DATA_URL = build_binary_collision_data_url(
    "application/pdf", b"%PDF-1.7\n", b"\n%%EOF\n"
)
PRIVATE_FIXTURE_MARKERS = (
    CIPHERTEXT,
    MUTABLE_SECRET,
    UI_ONLY_CANARY,
    UI_PREVIEW_CANARY,
    SEED_API_KEY,
    OPENAI_API_KEY,
    GOOGLE_KEY_COLLISION,
    PNG_ATTACHMENT_DATA_URL,
    JPEG_ATTACHMENT_DATA_URL,
    PDF_ATTACHMENT_DATA_URL,
)


class HarnessFailure(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise HarnessFailure(reason)


def resolve_opencode_binary(value: Path) -> Path:
    expanded = value.expanduser()
    if not expanded.is_absolute() and expanded.parent == Path("."):
        resolved = shutil.which(str(expanded))
        return Path(resolved).resolve() if resolved else expanded.resolve()
    return expanded.resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise a large, problematic OpenCode session through import, forked "
            "resume, gateway finalization, native OpenAI conversion, and localhost dispatch."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--opencode-bin",
        type=Path,
        default=Path(
            os.environ.get("OPENCODE_BIN") or shutil.which("opencode") or "opencode"
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


@dataclass(frozen=True)
class ChildResult:
    returncode: int
    stdout: str
    stderr: str


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HarnessFailure("deadline_exceeded")
    return remaining


def run_child(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    deadline: float,
    stdout_file: TextIO | None = None,
) -> ChildResult:
    timeout = remaining_seconds(deadline)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=stdout_file if stdout_file is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process(process)
        raise HarnessFailure("command_timeout") from None
    except BaseException:
        terminate_process(process)
        raise
    return ChildResult(
        returncode=process.returncode,
        stdout=stdout or "",
        stderr=stderr or "",
    )


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def private_json_output(path: Path) -> TextIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def isolated_env(home: Path, audit_path: Path) -> tuple[dict[str, str], list[str]]:
    home.mkdir(parents=True, mode=0o700, exist_ok=True)
    home.chmod(0o700)
    sandbox_tmp = home / "tmp"
    sandbox_tmp.mkdir(mode=0o700, exist_ok=True)
    env = {
        key: value
        for key in ("LANG", "LC_ALL", "LOGNAME", "PATH", "SHELL", "USER")
        if (value := os.environ.get(key))
    }
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "TMPDIR": str(sandbox_tmp),
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
    sensitive_markers = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")
    host_sensitive = {
        key
        for key in os.environ
        if any(marker in key.upper() for marker in sensitive_markers)
    }
    return env, sorted(host_sensitive.intersection(env))


def write_runtime_config(
    *,
    home: Path,
    project: Path,
    dist_entry: Path,
    provider: str,
    port: int,
) -> None:
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True, mode=0o700)
    project_config_dir = project / ".opencode"
    project_config_dir.mkdir(mode=0o700)

    if provider == "seed":
        provider_config = {
            "seed": {
                "name": "Resume E2E Seed",
                "npm": "@ai-sdk/openai-compatible",
                "options": {
                    "apiKey": SEED_API_KEY,
                    "baseURL": f"http://127.0.0.1:{port}/v1",
                },
                "models": {
                    "mock": {
                        "name": "Resume E2E Seed Model",
                        "limit": {"context": 4_000_000, "output": 4096},
                    }
                },
            }
        }
        model = "seed/mock"
    elif provider == "openai":
        provider_config = {
            "openai": {
                "name": "Resume E2E Native OpenAI",
                "options": {
                    "apiKey": OPENAI_API_KEY,
                    "baseURL": f"http://127.0.0.1:{port}/v1",
                },
                "models": {
                    "mock": {
                        "name": "Resume E2E Native Model",
                        "limit": {"context": 4_000_000, "output": 4096},
                    }
                },
            }
        }
        model = "openai/mock"
    else:
        raise HarnessFailure("unknown_provider_fixture")

    config = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "model": model,
        "small_model": model,
        "default_agent": "build",
        "provider": provider_config,
        "plugin": [dist_entry.as_uri()],
        "lsp": False,
        "formatter": False,
        "permission": "allow",
    }
    config_path = config_dir / "opencode.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    config_path.chmod(0o600)
    gateway_config_path = project_config_dir / "gateway-core.config.json"
    gateway_config_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "enabled": False,
                    "order": [],
                    "disabled": ["secret-leak-guard"],
                },
                "secretLeakGuard": {
                    "enabled": True,
                    "providerBoundaryEnabled": True,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    gateway_config_path.chmod(0o600)


@dataclass(frozen=True)
class CapturedRequest:
    path: str
    payload: dict[str, Any]
    authorization_expected: bool
    peer_is_loopback: bool


class CaptureState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[CapturedRequest] = []
        self.attempts: list[tuple[str, str]] = []

    def record_attempt(self, method: str, path: str) -> None:
        with self.lock:
            self.attempts.append((method, path))

    def record(self, request: CapturedRequest) -> None:
        with self.lock:
            self.requests.append(request)

    def snapshot(self) -> list[CapturedRequest]:
        with self.lock:
            return list(self.requests)

    def attempts_snapshot(self) -> list[tuple[str, str]]:
        with self.lock:
            return list(self.attempts)


class CaptureHandler(BaseHTTPRequestHandler):
    server_version = "ResumeE2ECapture/1.0"
    expected_authorization = ""

    @property
    def state(self) -> CaptureState:
        return self.server.capture_state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        return

    def read_json_payload(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self.send_error(413)
            return None
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return None
        if not isinstance(payload, dict):
            self.send_error(400)
            return None
        self.state.record(
            CapturedRequest(
                path=self.path,
                payload=payload,
                authorization_expected=(
                    self.headers.get("Authorization") == self.expected_authorization
                ),
                peer_is_loopback=self.client_address[0] == "127.0.0.1",
            )
        )
        return payload

    def write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SeedHandler(CaptureHandler):
    expected_authorization = f"Bearer {SEED_API_KEY}"

    def do_GET(self) -> None:
        self.state.record_attempt("GET", self.path)
        if self.path.rstrip("/").endswith("/models"):
            self.write_json(
                200,
                {
                    "object": "list",
                    "data": [{"id": "mock", "object": "model", "owned_by": "e2e"}],
                },
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        self.state.record_attempt("POST", self.path)
        if self.read_json_payload() is None:
            return
        now = int(time.time())
        chunks = [
            {
                "id": "chatcmpl-resume-e2e",
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
                "id": "chatcmpl-resume-e2e",
                "object": "chat.completion.chunk",
                "created": now,
                "model": "mock",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        body += "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class NativeOpenAIRejectHandler(CaptureHandler):
    expected_authorization = f"Bearer {OPENAI_API_KEY}"

    def do_GET(self) -> None:
        self.state.record_attempt("GET", self.path)
        self.send_error(404)

    def do_POST(self) -> None:
        self.state.record_attempt("POST", self.path)
        if self.read_json_payload() is None:
            return
        self.write_json(
            400,
            {
                "error": {
                    "message": EXPECTED_PROVIDER_ERROR,
                    "type": "invalid_request_error",
                    "code": "resume_e2e_capture",
                }
            },
        )


@contextmanager
def capture_server(
    handler: type[CaptureHandler],
) -> Iterator[tuple[int, CaptureState]]:
    state = CaptureState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.capture_state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1]), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        require(not thread.is_alive(), "capture_server_cleanup_failed")


def load_json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), "json_payload_not_object")
    return payload


def session_list(
    opencode_bin: Path,
    *,
    cwd: Path,
    env: dict[str, str],
    deadline: float,
) -> list[dict[str, Any]]:
    result = run_child(
        [str(opencode_bin), "session", "list", "--format", "json"],
        cwd=cwd,
        env=env,
        deadline=deadline,
    )
    require(result.returncode == 0, "session_list_failed")
    if not result.stdout.strip():
        return []
    payload = json.loads(result.stdout)
    require(isinstance(payload, list), "session_list_not_array")
    return [row for row in payload if isinstance(row, dict)]


def export_session(
    opencode_bin: Path,
    session_id: str,
    output_path: Path,
    *,
    cwd: Path,
    env: dict[str, str],
    deadline: float,
) -> None:
    with private_json_output(output_path) as output:
        result = run_child(
            [str(opencode_bin), "export", session_id],
            cwd=cwd,
            env=env,
            deadline=deadline,
            stdout_file=output,
        )
    require(result.returncode == 0, "session_export_failed")
    require(stat.S_IMODE(output_path.stat().st_mode) == 0o600, "export_not_private")


def derive_part_id(existing: str, suffix: str) -> str:
    require(
        existing.startswith("prt_") and len(existing) > len(suffix),
        "invalid_seed_part_id",
    )
    return f"{existing[: -len(suffix)]}{suffix}"


def mutate_export(source_path: Path, fixture_path: Path) -> str:
    data = load_json_file(source_path)
    info = data.get("info")
    messages = data.get("messages")
    require(isinstance(info, dict), "source_info_missing")
    require(isinstance(messages, list), "source_messages_missing")
    user = next(
        (
            item
            for item in messages
            if isinstance(item, dict) and item.get("info", {}).get("role") == "user"
        ),
        None,
    )
    assistant = next(
        (
            item
            for item in messages
            if isinstance(item, dict)
            and item.get("info", {}).get("role") == "assistant"
        ),
        None,
    )
    require(isinstance(user, dict) and isinstance(assistant, dict), "seed_turn_missing")
    user_parts = user.get("parts")
    assistant_info = assistant.get("info")
    assistant_parts = assistant.get("parts")
    require(isinstance(user_parts, list) and user_parts, "seed_user_parts_missing")
    require(isinstance(assistant_info, dict), "seed_assistant_info_missing")
    require(
        isinstance(assistant_parts, list) and len(assistant_parts) >= 2,
        "seed_assistant_parts_missing",
    )
    text_part = next(
        (
            part
            for part in assistant_parts
            if isinstance(part, dict) and part.get("type") == "text"
        ),
        None,
    )
    require(isinstance(text_part, dict), "seed_assistant_text_missing")

    session_id = str(info.get("id") or "")
    message_id = str(assistant_info.get("id") or "")
    base_part_id = str(text_part.get("id") or "")
    require(session_id.startswith("ses_"), "seed_session_id_invalid")
    require(message_id.startswith("msg_"), "seed_message_id_invalid")

    first_user_part = user_parts[0]
    require(
        isinstance(first_user_part, dict) and first_user_part.get("type") == "text",
        "seed_user_text_missing",
    )
    first_user_part["text"] = (
        f"{HISTORY_CONTROL}\n{'Z' * LARGE_HISTORY_CHARS}\npassword={MUTABLE_SECRET}"
    )
    assistant_info["providerID"] = "openai"
    assistant_info["modelID"] = "mock"
    info["model"] = {"id": "mock", "providerID": "openai", "variant": "default"}

    now = int(time.time() * 1000)
    reasoning = {
        "type": "reasoning",
        "text": REASONING_CONTROL,
        "metadata": {
            "openai": {
                "reasoningEncryptedContent": CIPHERTEXT,
            }
        },
        "time": {"start": now, "end": now + 1},
        "id": derive_part_id(base_part_id, "r01"),
        "sessionID": session_id,
        "messageID": message_id,
    }
    tool = {
        "type": "tool",
        "tool": "bash",
        "callID": "call_resume_e2e_0123456789",
        "state": {
            "status": "completed",
            "input": {"command": f"echo {TOOL_INPUT_CONTROL}"},
            "output": TOOL_OUTPUT_CONTROL,
            "title": "Resume E2E tool",
            "metadata": {
                "files": [{"patch": UI_ONLY_CANARY}],
                "preview": UI_PREVIEW_CANARY,
            },
            "time": {"start": now, "end": now + 1},
            "attachments": [
                {
                    "type": "file",
                    "mime": "image/png",
                    "url": PNG_ATTACHMENT_DATA_URL,
                    "id": derive_part_id(base_part_id, "a01"),
                    "sessionID": session_id,
                    "messageID": message_id,
                },
                {
                    "type": "file",
                    "mime": "image/jpeg",
                    "url": JPEG_ATTACHMENT_DATA_URL,
                    "id": derive_part_id(base_part_id, "a02"),
                    "sessionID": session_id,
                    "messageID": message_id,
                },
                {
                    "type": "file",
                    "mime": "application/pdf",
                    "url": PDF_ATTACHMENT_DATA_URL,
                    "id": derive_part_id(base_part_id, "a03"),
                    "sessionID": session_id,
                    "messageID": message_id,
                },
            ],
        },
        "id": derive_part_id(base_part_id, "t01"),
        "sessionID": session_id,
        "messageID": message_id,
    }
    assistant_parts.insert(1, reasoning)
    assistant_parts.insert(-1, tool)

    descriptor = os.open(fixture_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as fixture:
        json.dump(data, fixture, separators=(",", ":"))
    require(stat.S_IMODE(fixture_path.stat().st_mode) == 0o600, "fixture_not_private")
    return session_id


def verify_fixture(data: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    messages = data.get("messages")
    require(isinstance(messages, list), "imported_messages_missing")
    large_text_found = False
    ciphertext_found = False
    ui_metadata_found = False
    png_attachment_found = False
    jpeg_attachment_found = False
    pdf_attachment_found = False
    mutable_secret_found = False
    coherent_references = True

    for message in messages:
        if not isinstance(message, dict):
            coherent_references = False
            continue
        message_info = message.get("info")
        parts = message.get("parts")
        if not isinstance(message_info, dict) or not isinstance(parts, list):
            coherent_references = False
            continue
        message_id = message_info.get("id")
        coherent_references &= message_info.get("sessionID") == session_id
        for part in parts:
            if not isinstance(part, dict):
                coherent_references = False
                continue
            coherent_references &= part.get("sessionID") == session_id
            coherent_references &= part.get("messageID") == message_id
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                text = part["text"]
                if HISTORY_CONTROL in text:
                    large_text_found = text.count("Z") == LARGE_HISTORY_CHARS
                    mutable_secret_found = MUTABLE_SECRET in text
            if part.get("type") == "reasoning":
                metadata = part.get("metadata")
                if isinstance(metadata, dict):
                    openai = metadata.get("openai")
                    if isinstance(openai, dict):
                        ciphertext_found = (
                            "itemId" not in openai
                            and openai.get("reasoningEncryptedContent") == CIPHERTEXT
                        )
            if part.get("type") == "tool":
                state = part.get("state")
                if isinstance(state, dict):
                    metadata = state.get("metadata")
                    metadata_text = json.dumps(metadata, separators=(",", ":"))
                    ui_metadata_found = all(
                        marker in metadata_text
                        for marker in (UI_ONLY_CANARY, UI_PREVIEW_CANARY)
                    )
                    attachments = state.get("attachments")
                    if isinstance(attachments, list):
                        png_attachment_found = any(
                            isinstance(attachment, dict)
                            and attachment.get("type") == "file"
                            and attachment.get("mime") == "image/png"
                            and attachment.get("url") == PNG_ATTACHMENT_DATA_URL
                            for attachment in attachments
                        )
                        jpeg_attachment_found = any(
                            isinstance(attachment, dict)
                            and attachment.get("type") == "file"
                            and attachment.get("mime") == "image/jpeg"
                            and attachment.get("url") == JPEG_ATTACHMENT_DATA_URL
                            for attachment in attachments
                        )
                        pdf_attachment_found = any(
                            isinstance(attachment, dict)
                            and attachment.get("type") == "file"
                            and attachment.get("mime") == "application/pdf"
                            and attachment.get("url") == PDF_ATTACHMENT_DATA_URL
                            for attachment in attachments
                        )

    require(coherent_references, "fixture_references_incoherent")
    require(large_text_found, "large_history_fixture_missing")
    require(ciphertext_found, "ciphertext_fixture_missing")
    require(ui_metadata_found, "ui_metadata_fixture_missing")
    require(png_attachment_found, "png_attachment_fixture_missing")
    require(jpeg_attachment_found, "jpeg_attachment_fixture_missing")
    require(pdf_attachment_found, "pdf_attachment_fixture_missing")
    require(mutable_secret_found, "mutable_secret_fixture_missing")
    return messages


def iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)


def validate_native_wire(
    payload: dict[str, Any], forbidden_session_ids: set[str]
) -> dict[str, int | bool]:
    input_items = payload.get("input")
    require(isinstance(input_items, list), "native_input_not_array")
    items = [item for item in input_items if isinstance(item, dict)]
    require(len(items) == len(input_items), "native_input_item_invalid")

    reasoning_items = [item for item in items if item.get("type") == "reasoning"]
    require(len(reasoning_items) == 1, "native_reasoning_item_count_invalid")
    reasoning = reasoning_items[0]
    require(
        set(reasoning) == {"type", "encrypted_content", "summary"},
        "native_reasoning_shape_invalid",
    )
    require(
        reasoning.get("encrypted_content") == CIPHERTEXT,
        "native_reasoning_ciphertext_invalid",
    )
    require(
        list(iter_strings(reasoning)).count(CIPHERTEXT) == 1,
        "native_reasoning_ciphertext_count_invalid",
    )
    require(
        reasoning.get("summary")
        == [{"type": "summary_text", "text": REASONING_CONTROL}],
        "native_reasoning_summary_invalid",
    )

    user_texts: list[str] = []
    for item in items:
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "input_text"
                and isinstance(part.get("text"), str)
            ):
                user_texts.append(part["text"])
    expected_history = (
        f"{HISTORY_CONTROL}\n{'Z' * LARGE_HISTORY_CHARS}\n{REDACTION_TOKEN}"
    )
    require(user_texts.count(expected_history) == 1, "native_history_text_invalid")
    require(user_texts.count(RESUME_CONTROL) == 1, "native_resume_prompt_invalid")

    function_calls = [item for item in items if item.get("type") == "function_call"]
    require(len(function_calls) == 1, "native_function_call_count_invalid")
    function_call = function_calls[0]
    require(
        function_call.get("call_id") == "call_resume_e2e_0123456789",
        "native_function_call_id_invalid",
    )
    require(function_call.get("name") == "bash", "native_function_name_invalid")
    arguments = function_call.get("arguments")
    require(isinstance(arguments, str), "native_function_arguments_invalid")
    require(
        json.loads(arguments) == {"command": f"echo {TOOL_INPUT_CONTROL}"},
        "native_function_input_invalid",
    )

    function_outputs = [
        item for item in items if item.get("type") == "function_call_output"
    ]
    require(len(function_outputs) == 1, "native_function_output_count_invalid")
    function_output = function_outputs[0]
    require(
        function_output.get("call_id") == "call_resume_e2e_0123456789",
        "native_function_output_id_invalid",
    )
    output_parts = function_output.get("output")
    require(isinstance(output_parts, list), "native_function_output_not_array")
    require(len(output_parts) == 4, "native_function_output_part_count_invalid")
    output_text = [
        part
        for part in output_parts
        if isinstance(part, dict) and part.get("type") == "input_text"
    ]
    output_images = [
        part
        for part in output_parts
        if isinstance(part, dict) and part.get("type") == "input_image"
    ]
    output_files = [
        part
        for part in output_parts
        if isinstance(part, dict) and part.get("type") == "input_file"
    ]
    require(
        output_text == [{"type": "input_text", "text": TOOL_OUTPUT_CONTROL}],
        "native_function_output_text_invalid",
    )
    require(len(output_images) == 2, "native_function_output_image_count_invalid")
    require(
        {json.dumps(item, sort_keys=True) for item in output_images}
        == {
            json.dumps(
                {"type": "input_image", "image_url": PNG_ATTACHMENT_DATA_URL},
                sort_keys=True,
            ),
            json.dumps(
                {"type": "input_image", "image_url": JPEG_ATTACHMENT_DATA_URL},
                sort_keys=True,
            ),
        },
        "native_function_output_image_invalid",
    )
    require(
        output_files
        == [
            {
                "type": "input_file",
                "filename": "data",
                "file_data": PDF_ATTACHMENT_DATA_URL,
            }
        ],
        "native_function_output_file_invalid",
    )
    for marker, reason in (
        (PNG_ATTACHMENT_DATA_URL, "native_png_attachment_count_invalid"),
        (JPEG_ATTACHMENT_DATA_URL, "native_jpeg_attachment_count_invalid"),
        (PDF_ATTACHMENT_DATA_URL, "native_pdf_attachment_count_invalid"),
    ):
        require(list(iter_strings(payload)).count(marker) == 1, reason)

    prompt_cache_key = payload.get("prompt_cache_key")
    require(isinstance(prompt_cache_key, str), "prompt_cache_key_missing")
    require(
        re.fullmatch(r"ocpc-v1:[a-f0-9]{24}:n1:s0", prompt_cache_key) is not None,
        "prompt_cache_key_shape_invalid",
    )
    require(
        prompt_cache_key not in forbidden_session_ids,
        "prompt_cache_key_uses_session_id",
    )

    wire_text = json.dumps(payload, separators=(",", ":"))
    return {
        "wire_chars": len(wire_text),
        "wire_exceeds_legacy_limit": len(wire_text) > LEGACY_MAX_CHARS,
        "ciphertext_preserved_on_wire": list(iter_strings(payload)).count(CIPHERTEXT)
        == 1,
        "large_history_preserved_on_wire": True,
        "mutable_secret_absent_on_wire": MUTABLE_SECRET not in wire_text,
        "redaction_token_present_on_wire": wire_text.count(REDACTION_TOKEN) == 1,
        "ui_only_metadata_absent_on_wire": not any(
            marker in wire_text for marker in (UI_ONLY_CANARY, UI_PREVIEW_CANARY)
        ),
        "provider_controls_present": True,
        "png_attachment_preserved_on_wire": True,
        "jpeg_attachment_preserved_on_wire": True,
        "pdf_attachment_preserved_on_wire": True,
        "reasoning_without_item_id_on_wire": "id" not in reasoning,
        "prompt_cache_key_stable": True,
    }


def parse_audit(path: Path) -> list[dict[str, Any]]:
    require(path.is_file(), "audit_file_missing")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, "audit_file_not_private")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise HarnessFailure("audit_json_invalid") from error
        require(isinstance(row, dict), "audit_row_not_object")
        rows.append(row)
    require(rows, "audit_rows_missing")
    return rows


def parse_json_lines(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "result": "FAIL",
        "reason": "not_started",
        "expected_opencode_version": EXPECTED_OPENCODE_VERSION,
        "opencode_version": "",
        "postflight_opencode_version": "",
        "bootstrap_request_count": 0,
        "resume_request_count": 0,
        "native_request_path": "",
        "wire_chars": 0,
        "wire_exceeds_legacy_limit": False,
        "ciphertext_preserved_on_wire": False,
        "large_history_preserved_on_wire": False,
        "mutable_secret_absent_on_wire": False,
        "redaction_token_present_on_wire": False,
        "ui_only_metadata_absent_on_wire": False,
        "provider_controls_present": False,
        "png_attachment_preserved_on_wire": False,
        "jpeg_attachment_preserved_on_wire": False,
        "pdf_attachment_preserved_on_wire": False,
        "reasoning_without_item_id_on_wire": False,
        "opaque_attachment_collision_omission_audit_seen": False,
        "prompt_cache_key_stable": False,
        "prompt_cache_routing_audit_seen": False,
        "prompt_cache_prefix_audit_seen": False,
        "runtime_bootstrap_seen": False,
        "redaction_audit_seen": False,
        "redaction_scanned_chars": 0,
        "dispatch_block_absent": False,
        "fork_created": False,
        "source_messages_unchanged": False,
        "host_credentials_forwarded": False,
        "sandbox_removed": False,
    }
    sandbox_path: Path | None = None

    try:
        repo_root = args.repo_root.resolve()
        dist_entry = repo_root / "plugin" / "gateway-core" / "dist" / "index.js"
        require(dist_entry.is_file(), "gateway_dist_missing")
        opencode_bin = resolve_opencode_binary(args.opencode_bin)
        require(opencode_bin.is_file(), "opencode_binary_missing")
        deadline = time.monotonic() + max(30, args.timeout_seconds)
        version_env = {
            key: value
            for key in ("LANG", "LC_ALL", "LOGNAME", "PATH", "SHELL", "TMPDIR", "USER")
            if (value := os.environ.get(key))
        }
        version_env.update({"CI": "true", "GIT_TERMINAL_PROMPT": "0"})
        version_result = run_child(
            [str(opencode_bin), "--version"],
            cwd=repo_root,
            env=version_env,
            deadline=deadline,
        )
        version = version_result.stdout.strip()
        report["opencode_version"] = version
        require(version_result.returncode == 0, "opencode_version_failed")
        require(version == EXPECTED_OPENCODE_VERSION, "opencode_version_mismatch")

        with tempfile.TemporaryDirectory(prefix="my-opencode-resume-e2e-") as raw_tmp:
            sandbox_path = Path(raw_tmp).resolve()
            home_a = sandbox_path / "home-a"
            project_a = sandbox_path / "project-a"
            project_a.mkdir(mode=0o700)
            seed_audit = sandbox_path / "seed-audit.jsonl"
            source_export = sandbox_path / "source-export.json"
            fixture_path = sandbox_path / "resume-fixture.json"

            with capture_server(SeedHandler) as (seed_port, seed_state):
                write_runtime_config(
                    home=home_a,
                    project=project_a,
                    dist_entry=dist_entry,
                    provider="seed",
                    port=seed_port,
                )
                env_a, forwarded_a = isolated_env(home_a, seed_audit)
                require(not forwarded_a, "host_sensitive_environment_forwarded")
                bootstrap = run_child(
                    [
                        str(opencode_bin),
                        "run",
                        "--model",
                        "seed/mock",
                        "--agent",
                        "build",
                        "--format",
                        "json",
                        "--title",
                        "Resume E2E seed session",
                        BOOTSTRAP_CONTROL,
                    ],
                    cwd=project_a,
                    env=env_a,
                    deadline=deadline,
                )
                require(bootstrap.returncode == 0, "bootstrap_run_failed")
                require(
                    not any(
                        marker in f"{bootstrap.stdout}\n{bootstrap.stderr}"
                        for marker in PRIVATE_FIXTURE_MARKERS
                    ),
                    "bootstrap_output_leaked_fixture",
                )
                seed_requests = seed_state.snapshot()
                report["bootstrap_request_count"] = len(seed_requests)
                require(len(seed_requests) == 1, "bootstrap_request_count_invalid")
                require(
                    seed_state.attempts_snapshot()
                    == [("POST", "/v1/chat/completions")],
                    "bootstrap_request_attempts_invalid",
                )
                require(
                    seed_requests[0].path == "/v1/chat/completions",
                    "bootstrap_request_path_invalid",
                )
                require(
                    seed_requests[0].authorization_expected,
                    "bootstrap_authorization_invalid",
                )
                require(
                    seed_requests[0].peer_is_loopback, "bootstrap_peer_not_loopback"
                )

            source_sessions = session_list(
                opencode_bin, cwd=project_a, env=env_a, deadline=deadline
            )
            require(len(source_sessions) == 1, "bootstrap_session_count_invalid")
            seed_session_id = str(source_sessions[0].get("id") or "")
            require(seed_session_id.startswith("ses_"), "bootstrap_session_id_invalid")
            export_session(
                opencode_bin,
                seed_session_id,
                source_export,
                cwd=project_a,
                env=env_a,
                deadline=deadline,
            )
            mutated_session_id = mutate_export(source_export, fixture_path)
            require(mutated_session_id == seed_session_id, "mutated_session_id_changed")

            home_b = sandbox_path / "home-b"
            project_b = sandbox_path / "project-b"
            project_b.mkdir(mode=0o700)
            native_audit = sandbox_path / "native-audit.jsonl"
            imported_export = sandbox_path / "imported-export.json"
            source_after_export = sandbox_path / "source-after-export.json"
            fork_export = sandbox_path / "fork-export.json"

            with capture_server(NativeOpenAIRejectHandler) as (
                native_port,
                native_state,
            ):
                write_runtime_config(
                    home=home_b,
                    project=project_b,
                    dist_entry=dist_entry,
                    provider="openai",
                    port=native_port,
                )
                env_b, forwarded_b = isolated_env(home_b, native_audit)
                forwarded = sorted(set(forwarded_a + forwarded_b))
                report["host_credentials_forwarded"] = bool(forwarded)
                require(not forwarded, "host_sensitive_environment_forwarded")

                imported = run_child(
                    [str(opencode_bin), "import", str(fixture_path)],
                    cwd=project_b,
                    env=env_b,
                    deadline=deadline,
                )
                require(imported.returncode == 0, "fixture_import_failed")
                require(
                    not any(
                        marker in f"{imported.stdout}\n{imported.stderr}"
                        for marker in PRIVATE_FIXTURE_MARKERS
                    ),
                    "import_output_leaked_fixture",
                )
                pre_sessions = session_list(
                    opencode_bin, cwd=project_b, env=env_b, deadline=deadline
                )
                require(len(pre_sessions) == 1, "imported_session_count_invalid")
                imported_session_id = str(pre_sessions[0].get("id") or "")
                require(
                    imported_session_id.startswith("ses_"),
                    "imported_session_id_invalid",
                )
                require(not native_state.snapshot(), "request_before_resume")
                require(
                    not native_state.attempts_snapshot(),
                    "request_attempt_before_resume",
                )

                export_session(
                    opencode_bin,
                    imported_session_id,
                    imported_export,
                    cwd=project_b,
                    env=env_b,
                    deadline=deadline,
                )
                imported_data = load_json_file(imported_export)
                source_messages_before = verify_fixture(
                    imported_data, imported_session_id
                )

                resume = run_child(
                    [
                        str(opencode_bin),
                        "run",
                        "--session",
                        imported_session_id,
                        "--fork",
                        "--model",
                        "openai/mock",
                        "--agent",
                        "build",
                        "--format",
                        "json",
                        RESUME_CONTROL,
                    ],
                    cwd=project_b,
                    env=env_b,
                    deadline=deadline,
                )
                require(resume.returncode == 1, "resume_returncode_unexpected")
                require(
                    EXPECTED_PROVIDER_ERROR in resume.stdout,
                    "expected_provider_error_missing",
                )
                require(
                    "immutable_match" not in resume.stdout, "immutable_match_recurred"
                )
                require("text_limit" not in resume.stdout, "text_limit_recurred")
                error_rows = [
                    row
                    for row in parse_json_lines(resume.stdout)
                    if row.get("type") == "error"
                ]
                require(len(error_rows) == 1, "resume_error_event_count_invalid")
                error_data = error_rows[0].get("error")
                require(isinstance(error_data, dict), "resume_error_shape_invalid")
                api_error = error_data.get("data")
                require(isinstance(api_error, dict), "resume_api_error_shape_invalid")
                require(
                    api_error.get("message") == EXPECTED_PROVIDER_ERROR,
                    "resume_error_message_invalid",
                )
                require(
                    api_error.get("statusCode") == 400, "resume_error_status_invalid"
                )
                require(
                    api_error.get("isRetryable") is False,
                    "resume_error_retryability_invalid",
                )
                resume_session_id = str(error_rows[0].get("sessionID") or "")
                require(
                    resume_session_id.startswith("ses_"), "resume_session_id_invalid"
                )
                require(
                    not any(
                        marker in f"{resume.stdout}\n{resume.stderr}"
                        for marker in PRIVATE_FIXTURE_MARKERS
                    ),
                    "resume_output_leaked_fixture",
                )

                requests = native_state.snapshot()
                report["resume_request_count"] = len(requests)
                require(len(requests) == 1, "resume_request_count_invalid")
                require(
                    native_state.attempts_snapshot() == [("POST", "/v1/responses")],
                    "resume_request_attempts_invalid",
                )
                request = requests[0]
                report["native_request_path"] = request.path
                require(request.path == "/v1/responses", "native_request_path_invalid")
                require(request.authorization_expected, "native_authorization_invalid")
                require(request.peer_is_loopback, "native_peer_not_loopback")
                require(request.payload.get("model") == "mock", "native_model_invalid")
                report.update(
                    validate_native_wire(
                        request.payload,
                        {imported_session_id, resume_session_id},
                    )
                )
                require(report["wire_exceeds_legacy_limit"], "wire_below_legacy_limit")
                require(
                    report["ciphertext_preserved_on_wire"], "ciphertext_missing_on_wire"
                )
                require(
                    report["large_history_preserved_on_wire"],
                    "large_history_missing_on_wire",
                )
                require(
                    report["mutable_secret_absent_on_wire"], "mutable_secret_on_wire"
                )
                require(
                    report["redaction_token_present_on_wire"],
                    "redaction_token_missing_on_wire",
                )
                require(
                    report["ui_only_metadata_absent_on_wire"], "ui_metadata_on_wire"
                )
                require(
                    report["provider_controls_present"], "provider_controls_missing"
                )
                require(report["prompt_cache_key_stable"], "prompt_cache_key_unstable")
                require(
                    report["png_attachment_preserved_on_wire"],
                    "png_attachment_missing_on_wire",
                )
                require(
                    report["jpeg_attachment_preserved_on_wire"],
                    "jpeg_attachment_missing_on_wire",
                )
                require(
                    report["pdf_attachment_preserved_on_wire"],
                    "pdf_attachment_missing_on_wire",
                )
                require(
                    report["reasoning_without_item_id_on_wire"],
                    "reasoning_item_id_unexpected_on_wire",
                )

                audit_rows = parse_audit(native_audit)
                report["runtime_bootstrap_seen"] = any(
                    row.get("reason_code") == "gateway_runtime_bootstrap"
                    for row in audit_rows
                )
                redaction_rows = [
                    row
                    for row in audit_rows
                    if row.get("reason_code") == "provider_boundary_secrets_redacted"
                    and row.get("surface") == "messages"
                ]
                attachment_omission_rows = [
                    row
                    for row in audit_rows
                    if row.get("reason_code")
                    == "provider_boundary_opaque_attachment_collision_omitted"
                    and row.get("surface") == "messages"
                ]
                report["redaction_audit_seen"] = len(redaction_rows) == 1
                report["opaque_attachment_collision_omission_audit_seen"] = (
                    len(attachment_omission_rows) == 1
                )
                report["redaction_scanned_chars"] = max(
                    (int(row.get("scanned_chars") or 0) for row in redaction_rows),
                    default=0,
                )
                report["dispatch_block_absent"] = not any(
                    row.get("reason_code")
                    == "provider_boundary_secret_dispatch_blocked"
                    for row in audit_rows
                )
                cache_routing_rows = [
                    row
                    for row in audit_rows
                    if row.get("reason_code") == "agent_runtime_model_observed"
                    and row.get("session_id") == resume_session_id
                    and row.get("prompt_cache_strategy") == "stable_sharded"
                ]
                cache_prefix_rows = [
                    row
                    for row in audit_rows
                    if row.get("reason_code") == "prompt_cache_prefix_observed"
                    and row.get("session_id") == resume_session_id
                ]
                report["prompt_cache_routing_audit_seen"] = len(cache_routing_rows) == 1
                report["prompt_cache_prefix_audit_seen"] = len(cache_prefix_rows) == 1
                audit_text = native_audit.read_text(encoding="utf-8", errors="strict")
                require(
                    not any(marker in audit_text for marker in PRIVATE_FIXTURE_MARKERS),
                    "private_fixture_value_leaked_to_audit",
                )
                require(
                    report["runtime_bootstrap_seen"], "runtime_bootstrap_audit_missing"
                )
                require(
                    report["prompt_cache_routing_audit_seen"],
                    "prompt_cache_routing_audit_missing",
                )
                require(
                    report["prompt_cache_prefix_audit_seen"],
                    "prompt_cache_prefix_audit_missing",
                )
                cache_routing = cache_routing_rows[0]
                require(
                    cache_routing.get("prompt_cache_shard_count") == 1
                    and cache_routing.get("prompt_cache_shard") == 0,
                    "prompt_cache_routing_audit_invalid",
                )
                cache_prefix = cache_prefix_rows[0]
                require(
                    re.fullmatch(
                        r"[a-f0-9]{64}",
                        str(cache_prefix.get("cacheable_system_prefix_sha256") or ""),
                    )
                    is not None,
                    "prompt_cache_prefix_fingerprint_invalid",
                )
                require(
                    int(cache_prefix.get("cacheable_system_prefix_entry_count") or 0)
                    > 0
                    and int(cache_prefix.get("cacheable_system_prefix_char_count") or 0)
                    > 0,
                    "prompt_cache_prefix_counts_invalid",
                )
                require(
                    cache_prefix.get("runtime_session_marker_present") is False,
                    "prompt_cache_prefix_marker_state_invalid",
                )
                forbidden_cache_fields = {
                    "prompt_cache_key",
                    "promptCacheKey",
                    "prompt_cache_scope",
                    "prompt_cache_scope_digest",
                    "directory",
                    "path",
                }
                require(
                    all(
                        forbidden_cache_fields.isdisjoint(row)
                        for row in (cache_routing, cache_prefix)
                    ),
                    "prompt_cache_audit_leaked_scope",
                )
                wire_cache_key = str(request.payload["prompt_cache_key"])
                scope_digest = wire_cache_key.split(":", 2)[1]
                require(
                    wire_cache_key not in audit_text, "prompt_cache_key_leaked_to_audit"
                )
                require(
                    scope_digest not in audit_text,
                    "prompt_cache_scope_digest_leaked_to_audit",
                )
                require(report["redaction_audit_seen"], "redaction_audit_missing")
                require(
                    report["opaque_attachment_collision_omission_audit_seen"],
                    "opaque_attachment_collision_omission_audit_missing",
                )
                require(
                    attachment_omission_rows[0].get("omitted_match_count") == 3,
                    "opaque_attachment_collision_omission_count_invalid",
                )
                redaction_row = redaction_rows[0]
                require(
                    redaction_row.get("session_id") == resume_session_id,
                    "redaction_audit_session_invalid",
                )
                require(
                    redaction_row.get("match_count") == 1,
                    "redaction_audit_match_count_invalid",
                )
                require(
                    redaction_row.get("redacted_field_count") == 1,
                    "redaction_audit_field_count_invalid",
                )
                require(
                    report["redaction_scanned_chars"] > LEGACY_MAX_CHARS,
                    "audit_scanned_chars_below_legacy_limit",
                )
                require(report["dispatch_block_absent"], "dispatch_block_audit_present")

                post_sessions = session_list(
                    opencode_bin, cwd=project_b, env=env_b, deadline=deadline
                )
                pre_ids = {str(row.get("id") or "") for row in pre_sessions}
                post_ids = {str(row.get("id") or "") for row in post_sessions}
                fork_ids = post_ids - pre_ids
                report["fork_created"] = (
                    len(post_sessions) == 2
                    and fork_ids == {resume_session_id}
                    and resume_session_id != imported_session_id
                )
                require(report["fork_created"], "fork_identity_invalid")

                export_session(
                    opencode_bin,
                    resume_session_id,
                    fork_export,
                    cwd=project_b,
                    env=env_b,
                    deadline=deadline,
                )
                fork_data = load_json_file(fork_export)
                fork_info = fork_data.get("info")
                require(isinstance(fork_info, dict), "fork_info_missing")
                require(
                    fork_info.get("id") == resume_session_id,
                    "fork_export_id_invalid",
                )
                verify_fixture(fork_data, resume_session_id)
                fork_text = json.dumps(fork_data.get("messages"), separators=(",", ":"))
                require(RESUME_CONTROL in fork_text, "fork_resume_prompt_missing")
                require(
                    str(fork_info.get("title") or "").endswith("(fork #1)"),
                    "fork_title_invalid",
                )

                export_session(
                    opencode_bin,
                    imported_session_id,
                    source_after_export,
                    cwd=project_b,
                    env=env_b,
                    deadline=deadline,
                )
                source_after = load_json_file(source_after_export)
                report["source_messages_unchanged"] = (
                    source_after.get("messages") == source_messages_before
                )
                require(report["source_messages_unchanged"], "source_messages_changed")

                for session_id in sorted(post_ids):
                    deleted = run_child(
                        [str(opencode_bin), "session", "delete", session_id],
                        cwd=project_b,
                        env=env_b,
                        deadline=deadline,
                    )
                    require(deleted.returncode == 0, "session_cleanup_failed")
                require(
                    not session_list(
                        opencode_bin, cwd=project_b, env=env_b, deadline=deadline
                    ),
                    "session_cleanup_incomplete",
                )
                require(
                    native_state.attempts_snapshot() == [("POST", "/v1/responses")],
                    "final_request_attempts_invalid",
                )
                require(
                    len(native_state.snapshot()) == 1,
                    "final_request_count_invalid",
                )

        postflight_version = run_child(
            [str(opencode_bin), "--version"],
            cwd=repo_root,
            env=version_env,
            deadline=deadline,
        )
        report["postflight_opencode_version"] = postflight_version.stdout.strip()
        require(postflight_version.returncode == 0, "postflight_version_failed")
        require(
            report["postflight_opencode_version"] == EXPECTED_OPENCODE_VERSION,
            "postflight_version_mismatch",
        )
        report["sandbox_removed"] = bool(sandbox_path and not sandbox_path.exists())
        require(report["sandbox_removed"], "sandbox_cleanup_incomplete")
        report["result"] = "PASS"
        report["reason"] = "resume_transport_regressions_covered"
    except HarnessFailure as error:
        report["reason"] = str(error)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        report["reason"] = "unexpected_harness_failure"
        report["failure_type"] = type(error).__name__
    finally:
        if sandbox_path is not None:
            report["sandbox_removed"] = not sandbox_path.exists()
    return report


def main() -> int:
    args = parse_args()
    report = run_probe(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
