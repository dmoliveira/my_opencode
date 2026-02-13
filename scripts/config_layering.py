#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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
            while i + 1 < len(content) and not (
                content[i] == "*" and content[i + 1] == "/"
            ):
                i += 1
            i += 2
            continue

        out.append(ch)
        i += 1

    stripped = "".join(out)
    # Remove trailing commas before object/array close.
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

        if ch == ",":
            j = i + 1
            while j < len(stripped) and stripped[j].isspace():
                j += 1
            if j < len(stripped) and stripped[j] in "]}":
                i += 1
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def _load_json_or_jsonc(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    parsed = json.loads(_strip_jsonc(content))
    if not isinstance(parsed, dict):
        raise ValueError(f"Config root must be object: {path}")
    return parsed


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _candidate_paths() -> list[Path]:
    cwd = Path.cwd()
    home = Path("~").expanduser()
    return [
        cwd / ".opencode" / "my_opencode.jsonc",
        cwd / ".opencode" / "my_opencode.json",
        home / ".config" / "opencode" / "my_opencode.jsonc",
        home / ".config" / "opencode" / "my_opencode.json",
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".config" / "opencode" / "opencode.json",
    ]


def _base_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "opencode.json"


def resolve_write_path(env_var: str = "OPENCODE_CONFIG_PATH") -> Path:
    env_path = os.environ.get(env_var, "").strip()
    if env_path:
        return Path(env_path).expanduser()

    for path in _candidate_paths():
        if path.exists():
            return path

    return Path("~/.config/opencode/opencode.json").expanduser()


def load_layered_config(
    env_var: str = "OPENCODE_CONFIG_PATH",
) -> tuple[dict[str, Any], Path]:
    env_path = os.environ.get(env_var, "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        return _load_json_or_jsonc(path), path

    if not _base_config_path().exists():
        raise FileNotFoundError(f"Base config not found: {_base_config_path()}")

    merged = _load_json_or_jsonc(_base_config_path())
    for path in reversed(_candidate_paths()):
        if path.exists():
            merged = _deep_merge(merged, _load_json_or_jsonc(path))

    return merged, resolve_write_path(env_var=env_var)


def save_config(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
