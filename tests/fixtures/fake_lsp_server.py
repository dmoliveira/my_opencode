from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def read_message() -> dict[str, Any] | None:
    content_length = 0
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if decoded.lower().startswith("content-length:"):
            content_length = int(decoded.split(":", 1)[1].strip())
    if content_length <= 0:
        return None
    body = sys.stdin.buffer.read(content_length)
    if len(body) != content_length:
        return None
    parsed = json.loads(body.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else None


def frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def write_bytes(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def write_message(payload: dict[str, Any], scenario: str) -> None:
    data = frame(payload)
    if scenario == "fragmented":
        for index in range(0, len(data), 3):
            write_bytes(data[index : index + 3])
            time.sleep(0.002)
        return
    write_bytes(data)


def write_broken_response(scenario: str) -> None:
    if scenario == "stall-header":
        write_bytes(b"Content-Length: 100\r\n")
        time.sleep(30)
        return
    if scenario == "stall-body":
        write_bytes(b"Content-Length: 100\r\n\r\n{")
        time.sleep(30)
        return
    if scenario == "malformed-length":
        write_bytes(b"Content-Length: nope\r\n\r\n{}")
        return
    if scenario == "conflicting-length":
        write_bytes(b"Content-Length: 2\r\nContent-Length: 3\r\n\r\n{}")
        return
    if scenario == "oversized-length":
        write_bytes(b"Content-Length: 33554432\r\n\r\n")
        return
    if scenario == "truncated-body":
        write_bytes(b"Content-Length: 100\r\n\r\n{}")
        return
    raise RuntimeError(f"unknown broken scenario: {scenario}")


def response_result(method: str) -> Any:
    if method == "initialize":
        return {"capabilities": {"documentSymbolProvider": True}}
    if method == "textDocument/documentSymbol":
        return [{"name": "main", "kind": 12}]
    if method in {"workspace/symbol", "textDocument/definition", "textDocument/references"}:
        return []
    return None


def run(scenario: str) -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        method = str(message.get("method") or "")
        request_id = message.get("id")
        if method == "exit":
            return 0
        if request_id is None:
            continue
        if method == "initialize":
            if scenario == "abrupt-exit":
                return 3
            if scenario == "stderr-flood":
                sys.stderr.buffer.write(b"x" * (2 * 1024 * 1024))
                sys.stderr.buffer.flush()
            if scenario in {
                "stall-header",
                "stall-body",
                "malformed-length",
                "conflicting-length",
                "oversized-length",
                "truncated-body",
            }:
                write_broken_response(scenario)
                return 0
            if scenario == "wrong-id":
                write_message({"jsonrpc": "2.0", "id": 99999, "result": {}}, scenario)
            if scenario == "server-request":
                write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 900,
                        "method": "workspace/configuration",
                        "params": {},
                    },
                    "normal",
                )
                reply = read_message()
                marker = os.environ.get("FAKE_LSP_RESULT_PATH", "")
                if marker:
                    Path(marker).write_text(json.dumps(reply), encoding="utf-8")
            write_message(
                {"jsonrpc": "2.0", "id": request_id, "result": response_result(method)},
                scenario,
            )
            if scenario == "stop-reading-after-initialize":
                time.sleep(30)
                return 0
            continue
        if method == "shutdown" and scenario == "ignore-shutdown":
            time.sleep(30)
            return 0
        write_message(
            {"jsonrpc": "2.0", "id": request_id, "result": response_result(method)},
            scenario,
        )


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"
    return run(scenario)


if __name__ == "__main__":
    raise SystemExit(main())
