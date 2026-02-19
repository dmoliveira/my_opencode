#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from typing import Any


OPEN_DOCS: dict[str, str] = {}


def _send(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def _read_message() -> dict[str, Any] | None:
    content_length = 0
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("utf-8", errors="replace").strip()
        if decoded.lower().startswith("content-length:"):
            content_length = int(decoded.split(":", 1)[1].strip())
    if content_length <= 0:
        return None
    body = sys.stdin.buffer.read(content_length)
    if not body:
        return None
    parsed = json.loads(body.decode("utf-8", errors="replace"))
    if isinstance(parsed, dict):
        return parsed
    return None


def _word_at(text: str, line0: int, char0: int) -> str:
    lines = text.splitlines()
    if line0 < 0 or line0 >= len(lines):
        return ""
    line = lines[line0]
    if not line:
        return ""
    index = max(0, min(char0, max(len(line) - 1, 0)))
    if not re.match(r"[A-Za-z0-9_]", line[index]):
        return ""
    start = index
    while start > 0 and re.match(r"[A-Za-z0-9_]", line[start - 1]):
        start -= 1
    end = index + 1
    while end < len(line) and re.match(r"[A-Za-z0-9_]", line[end]):
        end += 1
    return line[start:end]


def _first_symbol_location(text: str, symbol: str) -> dict[str, Any]:
    lines = text.splitlines()
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    for line_index, line in enumerate(lines):
        matched = pattern.search(line)
        if matched:
            return {
                "start": {"line": line_index, "character": matched.start()},
                "end": {"line": line_index, "character": matched.end()},
            }
    return {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}


def _all_symbol_locations(text: str, symbol: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    out: list[dict[str, Any]] = []
    for line_index, line in enumerate(lines):
        for matched in pattern.finditer(line):
            out.append(
                {
                    "start": {"line": line_index, "character": matched.start()},
                    "end": {"line": line_index, "character": matched.end()},
                }
            )
    return out


def _reply(request_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _handle_request(method: str, params: dict[str, Any]) -> Any:
    if method == "initialize":
        return {
            "capabilities": {
                "renameProvider": True,
                "documentSymbolProvider": True,
                "codeActionProvider": True,
            }
        }

    if method == "shutdown":
        return None

    if method == "textDocument/definition":
        doc_uri = str(params.get("textDocument", {}).get("uri") or "")
        text = OPEN_DOCS.get(doc_uri, "")
        pos = params.get("position", {})
        symbol = _word_at(text, int(pos.get("line", 0)), int(pos.get("character", 0)))
        symbol_range = _first_symbol_location(text, symbol or "")
        return [{"uri": doc_uri, "range": symbol_range}]

    if method == "textDocument/references":
        doc_uri = str(params.get("textDocument", {}).get("uri") or "")
        text = OPEN_DOCS.get(doc_uri, "")
        pos = params.get("position", {})
        symbol = _word_at(text, int(pos.get("line", 0)), int(pos.get("character", 0)))
        ranges = _all_symbol_locations(text, symbol or "")
        return [{"uri": doc_uri, "range": item} for item in ranges]

    if method == "textDocument/documentSymbol":
        doc_uri = str(params.get("textDocument", {}).get("uri") or "")
        text = OPEN_DOCS.get(doc_uri, "")
        symbols: list[dict[str, Any]] = []
        for line_index, line in enumerate(text.splitlines()):
            if line.strip().startswith("def "):
                name = line.strip().split("def ", 1)[1].split("(", 1)[0].strip()
                symbols.append(
                    {
                        "name": name,
                        "kind": 12,
                        "location": {
                            "uri": doc_uri,
                            "range": {
                                "start": {"line": line_index, "character": 0},
                                "end": {"line": line_index, "character": len(line)},
                            },
                        },
                    }
                )
        return symbols

    if method == "workspace/symbol":
        query = str(params.get("query") or "").lower()
        out: list[dict[str, Any]] = []
        for uri, text in OPEN_DOCS.items():
            for line_index, line in enumerate(text.splitlines()):
                if line.strip().startswith("def "):
                    name = line.strip().split("def ", 1)[1].split("(", 1)[0].strip()
                    if query in name.lower():
                        out.append(
                            {
                                "name": name,
                                "kind": 12,
                                "location": {
                                    "uri": uri,
                                    "range": {
                                        "start": {"line": line_index, "character": 0},
                                        "end": {
                                            "line": line_index,
                                            "character": len(line),
                                        },
                                    },
                                },
                            }
                        )
        return out

    if method == "textDocument/prepareRename":
        doc_uri = str(params.get("textDocument", {}).get("uri") or "")
        text = OPEN_DOCS.get(doc_uri, "")
        pos = params.get("position", {})
        symbol = _word_at(text, int(pos.get("line", 0)), int(pos.get("character", 0)))
        return {"range": _first_symbol_location(text, symbol), "placeholder": symbol}

    if method == "textDocument/rename":
        doc_uri = str(params.get("textDocument", {}).get("uri") or "")
        text = OPEN_DOCS.get(doc_uri, "")
        pos = params.get("position", {})
        symbol = _word_at(text, int(pos.get("line", 0)), int(pos.get("character", 0)))
        new_name = str(params.get("newName") or "")
        edits = [
            {"range": item, "newText": new_name}
            for item in _all_symbol_locations(text, symbol)
        ]
        return {"changes": {doc_uri: edits}}

    if method == "textDocument/codeAction":
        doc_uri = str(params.get("textDocument", {}).get("uri") or "")
        text = OPEN_DOCS.get(doc_uri, "")
        lines = text.splitlines()
        if not lines:
            return []
        line0 = int(params.get("range", {}).get("start", {}).get("line", 0))
        line0 = max(0, min(line0, len(lines) - 1))
        line = lines[line0]
        if not line:
            return []
        replacement = f"# action: {line.strip()}"
        return [
            {
                "title": "Mock: comment selected line",
                "kind": "quickfix.mock",
                "isPreferred": True,
                "edit": {
                    "changes": {
                        doc_uri: [
                            {
                                "range": {
                                    "start": {"line": line0, "character": 0},
                                    "end": {
                                        "line": line0,
                                        "character": len(line),
                                    },
                                },
                                "newText": replacement,
                            }
                        ]
                    }
                },
            }
        ]

    return None


def main() -> int:
    while True:
        message = _read_message()
        if message is None:
            return 0
        method = str(message.get("method") or "")
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "exit":
            return 0
        if method == "initialized":
            continue
        if method == "textDocument/didOpen":
            doc = params.get("textDocument")
            if isinstance(doc, dict):
                uri = str(doc.get("uri") or "")
                text = str(doc.get("text") or "")
                if uri:
                    OPEN_DOCS[uri] = text
            continue

        if "id" in message:
            request_id = message.get("id")
            result = _handle_request(method, params)
            _reply(request_id, result)


if __name__ == "__main__":
    raise SystemExit(main())
