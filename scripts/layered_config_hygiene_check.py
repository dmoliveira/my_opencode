#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_LAYER_PATHS = [
    REPO_ROOT / ".opencode" / "my_opencode.json",
    REPO_ROOT / ".opencode" / "my_opencode.jsonc",
]
BLOCKED_TOP_LEVEL_KEYS = {
    "provider",
    "model",
    "llmDecisionRuntime",
    "kvforge",
    "policy",
    "stack_profile",
    "budget_runtime",
}

def _strip_jsonc(content: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False
    quote = ""
    escape = False
    while i < len(content):
        ch = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_string = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            i += 2
            while i < len(content) and content[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(content) and not (content[i] == "*" and content[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    stripped = "".join(out)
    result: list[str] = []
    i = 0
    in_string = False
    quote = ""
    escape = False
    while i < len(stripped):
        ch = stripped[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_string = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            quote = ch
            result.append(ch)
            i += 1
            continue
        if ch == ',':
            j = i + 1
            while j < len(stripped) and stripped[j].isspace():
                j += 1
            if j < len(stripped) and stripped[j] in ']}':
                i += 1
                continue
        result.append(ch)
        i += 1
    return "".join(result)

def _load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    payload = json.loads(_strip_jsonc(text))
    if not isinstance(payload, dict):
        raise ValueError(f"Config root must be object: {path}")
    return payload

def _find_abs_paths(value: Any, trail: tuple[str, ...] = ()) -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                hits.extend(_find_abs_paths(child, trail + (key,)))
        return hits
    if isinstance(value, list):
        for idx, child in enumerate(value):
            hits.extend(_find_abs_paths(child, trail + (str(idx),)))
        return hits
    if isinstance(value, str) and value.startswith("/"):
        hits.append(".".join(trail) or "<root>")
    return hits

def main() -> int:
    findings: list[str] = []
    for path in PROJECT_LAYER_PATHS:
        if not path.exists():
            continue
        payload = _load(path)
        blocked = sorted(BLOCKED_TOP_LEVEL_KEYS.intersection(payload.keys()))
        for key in blocked:
            findings.append(f"{path.relative_to(REPO_ROOT)} uses blocked top-level key: {key}")
        for trail in _find_abs_paths(payload):
            findings.append(f"{path.relative_to(REPO_ROOT)} contains absolute-path value at: {trail}")
    if findings:
        print("layered-config-hygiene-check: FAIL")
        for item in findings:
            print(f"- {item}")
        return 1
    print("layered-config-hygiene-check: PASS")
    checked = [str(p.relative_to(REPO_ROOT)) for p in PROJECT_LAYER_PATHS if p.exists()]
    print(f"checked_files: {len(checked)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
