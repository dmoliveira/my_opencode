#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/"):
        path = path[1:]
    return Path(path)


def language_id_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if suffix == ".go":
        return "go"
    if suffix == ".rs":
        return "rust"
    return "plaintext"


def choose_server_for_path(
    path: Path, servers: list[dict[str, Any]]
) -> dict[str, Any] | None:
    suffix = path.suffix.lower()
    for server in servers:
        if not bool(server.get("installed")):
            continue
        exts = [str(item).lower() for item in server.get("extensions", [])]
        if suffix in exts:
            return server
    return None


class LspClient:
    def __init__(
        self, command: list[str], root: Path, timeout_seconds: float = 4.0
    ) -> None:
        self.command = command
        self.root = root
        self.timeout_seconds = timeout_seconds
        self._proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._opened: set[str] = set()

    def __enter__(self) -> "LspClient":
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.root,
        )
        self._initialize()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            self._request("shutdown", None)
        except Exception:
            pass
        try:
            self._notify("exit", None)
        except Exception:
            pass
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1)
            except Exception:
                self._proc.kill()

    def _initialize(self) -> None:
        init_result = self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": path_to_uri(self.root),
                "capabilities": {},
                "workspaceFolders": [
                    {
                        "uri": path_to_uri(self.root),
                        "name": self.root.name,
                    }
                ],
            },
        )
        _ = init_result
        self._notify("initialized", {})

    def _require_proc(self) -> subprocess.Popen[bytes]:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("LSP process is not running")
        return self._proc

    def _send(self, payload: dict[str, Any]) -> None:
        proc = self._require_proc()
        stdin = proc.stdin
        if stdin is None:
            raise RuntimeError("LSP stdin unavailable")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        stdin.write(header + body)
        stdin.flush()

    def _notify(self, method: str, params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: Any) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )

        deadline = time.time() + self.timeout_seconds
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"LSP request timeout: {method}")
            message = self._read_message(remaining)
            if "id" not in message:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message and message["error"]:
                err = message["error"]
                raise RuntimeError(f"LSP error {method}: {err}")
            return message.get("result")

    def _read_message(self, timeout_seconds: float) -> dict[str, Any]:
        proc = self._require_proc()
        stdout = proc.stdout
        if stdout is None:
            raise RuntimeError("LSP stdout unavailable")

        fd = stdout.fileno()
        ready, _, _ = select.select([fd], [], [], timeout_seconds)
        if not ready:
            raise TimeoutError("LSP response timeout")

        content_length = 0
        while True:
            line = stdout.readline()
            if not line:
                raise RuntimeError("LSP server closed stdout")
            if line in {b"\r\n", b"\n"}:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded.lower().startswith("content-length:"):
                content_length = int(decoded.split(":", 1)[1].strip())
        if content_length <= 0:
            raise RuntimeError("LSP message missing content length")

        body = stdout.read(content_length)
        if body is None or len(body) != content_length:
            raise RuntimeError("LSP message body truncated")
        parsed = json.loads(body.decode("utf-8", errors="replace"))
        if not isinstance(parsed, dict):
            raise RuntimeError("LSP message must be JSON object")
        return parsed

    def ensure_open(self, path: Path) -> None:
        uri = path_to_uri(path)
        if uri in self._opened:
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id_for_path(path),
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened.add(uri)

    def goto_definition(
        self, path: Path, line0: int, char0: int
    ) -> list[dict[str, Any]]:
        self.ensure_open(path)
        result = self._request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line0, "character": char0},
            },
        )
        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    def find_references(
        self, path: Path, line0: int, char0: int
    ) -> list[dict[str, Any]]:
        self.ensure_open(path)
        result = self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line0, "character": char0},
                "context": {"includeDeclaration": True},
            },
        )
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    def document_symbols(self, path: Path) -> list[dict[str, Any]]:
        self.ensure_open(path)
        result = self._request(
            "textDocument/documentSymbol", {"textDocument": {"uri": path_to_uri(path)}}
        )
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    def workspace_symbols(self, query: str) -> list[dict[str, Any]]:
        result = self._request("workspace/symbol", {"query": query})
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    def prepare_rename(
        self, path: Path, line0: int, char0: int
    ) -> dict[str, Any] | None:
        self.ensure_open(path)
        result = self._request(
            "textDocument/prepareRename",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line0, "character": char0},
            },
        )
        if isinstance(result, dict):
            return result
        return None

    def rename(
        self, path: Path, line0: int, char0: int, new_name: str
    ) -> dict[str, Any] | None:
        self.ensure_open(path)
        result = self._request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line0, "character": char0},
                "newName": new_name,
            },
        )
        if isinstance(result, dict):
            return result
        return None
