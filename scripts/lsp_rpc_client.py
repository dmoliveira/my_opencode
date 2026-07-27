#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self
from urllib.parse import unquote, urlparse


MAX_HEADER_BYTES = 64 * 1024
MAX_BODY_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
STDOUT_QUEUE_CHUNKS = 32
WRITE_QUEUE_ITEMS = 4
STDERR_TAIL_BYTES = 64 * 1024
_STDOUT_EOF = object()
_WRITER_STOP = object()


@dataclass
class _PumpFailure:
    error: BaseException


@dataclass
class _WriteRequest:
    data: bytes
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


class LspTransportError(RuntimeError):
    pass


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
        if timeout_seconds <= 0:
            raise ValueError("LSP timeout must be positive")
        self.command = command
        self.root = root
        self.timeout_seconds = timeout_seconds
        self._proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._opened: set[str] = set()
        self.server_capabilities: dict[str, Any] = {}
        self._stdout_queue: queue.Queue[bytes | _PumpFailure | object] = queue.Queue(
            maxsize=STDOUT_QUEUE_CHUNKS
        )
        self._write_queue: queue.Queue[_WriteRequest | object] = queue.Queue(
            maxsize=WRITE_QUEUE_ITEMS
        )
        self._stdout_buffer = bytearray()
        self._stderr_chunks: deque[bytes] = deque()
        self._stderr_size = 0
        self._stderr_lock = threading.Lock()
        self._stop_pumps = threading.Event()
        self._close_lock = threading.Lock()
        self._transport_closed = False
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._writer_thread: threading.Thread | None = None

    def __enter__(self) -> Self:
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.root,
            bufsize=0,
        )
        self._start_pumps()
        try:
            self._initialize()
        except BaseException:
            self._finish_process(force=True)
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if not self._transport_closed:
            try:
                self._request("shutdown", None)
            except Exception:  # noqa: BLE001,S110 - shutdown is best effort.
                pass
            try:
                self._notify("exit", None)
            except Exception:  # noqa: BLE001,S110 - exit notify is best effort.
                pass
        self._finish_process(force=False)

    def _start_pumps(self) -> None:
        self._stdout_thread = threading.Thread(
            target=self._stdout_pump,
            name="lsp-stdout-pump",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_pump,
            name="lsp-stderr-pump",
            daemon=True,
        )
        self._writer_thread = threading.Thread(
            target=self._writer_pump,
            name="lsp-stdin-pump",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._writer_thread.start()

    def _queue_stdout(self, item: bytes | _PumpFailure | object) -> None:
        while not self._stop_pumps.is_set():
            try:
                self._stdout_queue.put(item, timeout=0.05)
                return
            except queue.Full:
                continue

    def _stdout_pump(self) -> None:
        try:
            proc = self._proc
            if proc is None or proc.stdout is None:
                raise LspTransportError("LSP stdout unavailable")
            fd = proc.stdout.fileno()
            while not self._stop_pumps.is_set():
                chunk = os.read(fd, READ_CHUNK_BYTES)
                if not chunk:
                    self._queue_stdout(_STDOUT_EOF)
                    return
                self._queue_stdout(chunk)
        except Exception as error:  # noqa: BLE001 - pump reports transport failure.
            if not self._stop_pumps.is_set():
                self._queue_stdout(_PumpFailure(error))

    def _append_stderr(self, chunk: bytes) -> None:
        with self._stderr_lock:
            self._stderr_chunks.append(chunk)
            self._stderr_size += len(chunk)
            while self._stderr_size > STDERR_TAIL_BYTES and self._stderr_chunks:
                overflow = self._stderr_size - STDERR_TAIL_BYTES
                first = self._stderr_chunks[0]
                if len(first) <= overflow:
                    self._stderr_chunks.popleft()
                    self._stderr_size -= len(first)
                else:
                    self._stderr_chunks[0] = first[overflow:]
                    self._stderr_size -= overflow

    def _stderr_pump(self) -> None:
        try:
            proc = self._proc
            if proc is None or proc.stderr is None:
                return
            fd = proc.stderr.fileno()
            while not self._stop_pumps.is_set():
                chunk = os.read(fd, READ_CHUNK_BYTES)
                if not chunk:
                    return
                self._append_stderr(chunk)
        except (OSError, ValueError):
            return

    def _writer_pump(self) -> None:
        while not self._stop_pumps.is_set():
            try:
                item = self._write_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if item is _WRITER_STOP:
                return
            if not isinstance(item, _WriteRequest):
                continue
            try:
                proc = self._proc
                if proc is None or proc.stdin is None:
                    raise LspTransportError("LSP stdin unavailable")
                remaining = memoryview(item.data)
                while remaining:
                    written = proc.stdin.write(remaining)
                    if written is None or written <= 0:
                        raise RuntimeError("LSP stdin write returned no progress")
                    remaining = remaining[written:]
                proc.stdin.flush()
            except Exception as error:  # noqa: BLE001 - writer reports through request.
                item.error = error
            finally:
                item.done.set()

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
        if isinstance(init_result, dict):
            capabilities = init_result.get("capabilities")
            if isinstance(capabilities, dict):
                self.server_capabilities = capabilities
        self._notify("initialized", {})

    def _require_proc(self) -> subprocess.Popen[bytes]:
        if self._transport_closed or self._proc is None:
            raise LspTransportError("LSP process is not running")
        if self._proc.stdin is None or self._proc.stdout is None:
            raise LspTransportError("LSP process is not running")
        if self._proc.poll() is not None:
            raise LspTransportError("LSP process exited")
        return self._proc

    def _remaining(self, deadline: float, message: str) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(message)
        return remaining

    def _send(self, payload: dict[str, Any], deadline: float) -> None:
        self._require_proc()
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_BODY_BYTES:
            raise LspTransportError("LSP outgoing message exceeds body limit")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        item = _WriteRequest(header + body)
        try:
            self._write_queue.put(
                item,
                timeout=self._remaining(deadline, "LSP write timeout"),
            )
            if not item.done.wait(self._remaining(deadline, "LSP write timeout")):
                raise TimeoutError("LSP write timeout")
        except (queue.Full, TimeoutError) as error:
            self._finish_process(force=True)
            raise TimeoutError("LSP write timeout") from error
        if item.error is not None:
            self._finish_process(force=True)
            raise LspTransportError("LSP write failed") from item.error

    def _notify(self, method: str, params: Any) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        self._send(
            {"jsonrpc": "2.0", "method": method, "params": params},
            deadline,
        )

    def _request(self, method: str, params: Any) -> Any:
        request_id = self._next_id
        self._next_id += 1
        deadline = time.monotonic() + self.timeout_seconds
        try:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                deadline,
            )
            while True:
                message = self._read_message(deadline)
                if "method" in message and "id" in message:
                    self._send(
                        {
                            "jsonrpc": "2.0",
                            "id": message.get("id"),
                            "error": {
                                "code": -32601,
                                "message": "Method not found",
                            },
                        },
                        deadline,
                    )
                    continue
                if "id" not in message or message.get("id") != request_id:
                    continue
                if message.get("error"):
                    response_error = message["error"]
                    raise RuntimeError(f"LSP error {method}: {response_error}")
                return message.get("result")
        except TimeoutError as error:
            self._finish_process(force=True)
            raise TimeoutError(f"LSP request timeout: {method}") from error
        except LspTransportError:
            self._finish_process(force=True)
            raise

    def _parse_buffered_message(self) -> dict[str, Any] | None:
        crlf_index = self._stdout_buffer.find(b"\r\n\r\n")
        lf_index = self._stdout_buffer.find(b"\n\n")
        candidates = [
            (index, delimiter)
            for index, delimiter in ((crlf_index, 4), (lf_index, 2))
            if index >= 0
        ]
        if not candidates:
            if len(self._stdout_buffer) > MAX_HEADER_BYTES:
                raise LspTransportError("LSP response header exceeds limit")
            return None
        header_end, delimiter_size = min(candidates, key=lambda item: item[0])
        if header_end > MAX_HEADER_BYTES:
            raise LspTransportError("LSP response header exceeds limit")
        header = bytes(self._stdout_buffer[:header_end])
        lengths: list[int] = []
        for raw_line in header.splitlines():
            if b":" not in raw_line:
                continue
            name, value = raw_line.split(b":", 1)
            if name.strip().lower() != b"content-length":
                continue
            try:
                lengths.append(int(value.strip().decode("ascii")))
            except (UnicodeDecodeError, ValueError) as error:
                raise LspTransportError("LSP message has invalid content length") from error
        if not lengths:
            raise LspTransportError("LSP message missing content length")
        if len(set(lengths)) != 1:
            raise LspTransportError("LSP message has conflicting content length")
        content_length = lengths[0]
        if content_length <= 0:
            raise LspTransportError("LSP message missing content length")
        if content_length > MAX_BODY_BYTES:
            raise LspTransportError("LSP response body exceeds limit")
        body_start = header_end + delimiter_size
        body_end = body_start + content_length
        if len(self._stdout_buffer) < body_end:
            return None
        body = bytes(self._stdout_buffer[body_start:body_end])
        del self._stdout_buffer[:body_end]
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LspTransportError("LSP message body is invalid JSON") from error
        if not isinstance(parsed, dict):
            raise LspTransportError("LSP message must be JSON object")
        return parsed

    def _read_message(self, deadline: float) -> dict[str, Any]:
        while True:
            parsed = self._parse_buffered_message()
            if parsed is not None:
                return parsed
            try:
                item = self._stdout_queue.get(
                    timeout=self._remaining(deadline, "LSP response timeout")
                )
            except queue.Empty as error:
                raise TimeoutError("LSP response timeout") from error
            if item is _STDOUT_EOF:
                raise LspTransportError("LSP server closed stdout")
            if isinstance(item, _PumpFailure):
                raise LspTransportError("LSP stdout reader failed") from item.error
            if isinstance(item, bytes):
                self._stdout_buffer.extend(item)

    def stderr_tail(self) -> str:
        with self._stderr_lock:
            return b"".join(self._stderr_chunks).decode("utf-8", errors="replace")

    def transport_threads_alive(self) -> list[str]:
        return [
            thread.name
            for thread in (self._stdout_thread, self._stderr_thread, self._writer_thread)
            if thread is not None and thread.is_alive()
        ]

    def _finish_process(self, force: bool) -> None:
        with self._close_lock:
            if self._transport_closed:
                return
            self._transport_closed = True
            self._stop_pumps.set()
            proc = self._proc
            if proc is not None and proc.poll() is None:
                try:
                    if force:
                        proc.kill()
                    else:
                        proc.terminate()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            if proc is not None:
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
            try:
                self._write_queue.put_nowait(_WRITER_STOP)
            except queue.Full:
                pass
            threads = [
                thread
                for thread in (self._stdout_thread, self._stderr_thread, self._writer_thread)
                if thread is not None and thread is not threading.current_thread()
            ]
        for thread in threads:
            thread.join(timeout=1)

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

    def document_diagnostics(self, path: Path) -> list[dict[str, Any]]:
        self.ensure_open(path)
        result = self._request(
            "textDocument/diagnostic",
            {
                "textDocument": {"uri": path_to_uri(path)},
            },
        )
        if isinstance(result, dict):
            items = result.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    def code_actions(
        self,
        path: Path,
        line0: int,
        char0: int,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_open(path)
        result = self._request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "range": {
                    "start": {"line": line0, "character": char0},
                    "end": {"line": line0, "character": char0},
                },
                "context": {
                    "diagnostics": diagnostics or [],
                },
            },
        )
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]
