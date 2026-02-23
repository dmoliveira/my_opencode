#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_MEMORY_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_MEMORY_LIFECYCLE_PATH",
        "~/.config/opencode/my_opencode/runtime/memory_store.json",
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /memory-lifecycle stats [--json] | /memory-lifecycle cleanup [--older-days <n>] [--json] | "
        "/memory-lifecycle compress [--json] | /memory-lifecycle export --path <file> [--json] | "
        "/memory-lifecycle import --path <file> [--json] | /memory-lifecycle doctor [--json]"
    )
    return 2


def load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": [], "archive": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"version": 1, "entries": [], "archive": []}
    entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
    archive = raw.get("archive") if isinstance(raw.get("archive"), list) else []
    return {
        "version": int(raw.get("version", 1) or 1),
        "entries": entries,
        "archive": archive,
    }


def save_store(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'memory-lifecycle failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("entry_count") is not None:
            print(f"entry_count: {payload.get('entry_count')}")
    return 0 if payload.get("result") == "PASS" else 1


def cmd_stats(argv: list[str]) -> int:
    as_json = "--json" in argv
    store = load_store(DEFAULT_MEMORY_PATH)
    entries = store.get("entries") if isinstance(store.get("entries"), list) else []
    archive = store.get("archive") if isinstance(store.get("archive"), list) else []
    return emit(
        {
            "result": "PASS",
            "command": "stats",
            "path": str(DEFAULT_MEMORY_PATH),
            "entry_count": len(entries),
            "archive_count": len(archive),
        },
        as_json,
    )


def cmd_cleanup(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    older_days = 30
    try:
        raw = parse_flag_value(argv, "--older-days")
        if raw is not None:
            older_days = max(1, int(raw))
    except (ValueError, TypeError):
        return usage()
    store = load_store(DEFAULT_MEMORY_PATH)
    entries = store.get("entries") if isinstance(store.get("entries"), list) else []
    archive = store.get("archive") if isinstance(store.get("archive"), list) else []
    cutoff = datetime.now(UTC) - timedelta(days=older_days)
    kept: list[dict[str, Any]] = []
    moved = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        when_raw = str(entry.get("updated_at") or entry.get("created_at") or "")
        try:
            when = datetime.fromisoformat(when_raw.replace("Z", "+00:00"))
        except ValueError:
            kept.append(entry)
            continue
        if when < cutoff:
            archive.append(entry)
            moved += 1
        else:
            kept.append(entry)
    store["entries"] = kept
    store["archive"] = archive
    save_store(DEFAULT_MEMORY_PATH, store)
    return emit(
        {
            "result": "PASS",
            "command": "cleanup",
            "moved": moved,
            "entry_count": len(kept),
            "archive_count": len(archive),
        },
        as_json,
    )


def cmd_compress(argv: list[str]) -> int:
    as_json = "--json" in argv
    store = load_store(DEFAULT_MEMORY_PATH)
    entries = store.get("entries") if isinstance(store.get("entries"), list) else []
    dedup: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("id") or entry.get("title") or entry.get("summary") or "")
        if not key:
            key = json.dumps(entry, sort_keys=True)
        dedup[key] = entry
    before = len(entries)
    after = len(dedup)
    store["entries"] = list(dedup.values())
    save_store(DEFAULT_MEMORY_PATH, store)
    return emit(
        {
            "result": "PASS",
            "command": "compress",
            "before": before,
            "after": after,
            "removed": max(0, before - after),
        },
        as_json,
    )


def cmd_export(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        path_arg = parse_flag_value(argv, "--path")
    except ValueError:
        return usage()
    if not path_arg:
        return usage()
    target = Path(path_arg).expanduser()
    store = load_store(DEFAULT_MEMORY_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return emit(
        {
            "result": "PASS",
            "command": "export",
            "path": str(target),
            "entry_count": len(store.get("entries", [])),
        },
        as_json,
    )


def cmd_import(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        path_arg = parse_flag_value(argv, "--path")
    except ValueError:
        return usage()
    if not path_arg:
        return usage()
    source = Path(path_arg).expanduser()
    if not source.exists():
        return emit(
            {
                "result": "FAIL",
                "command": "import",
                "error": f"file not found: {source}",
            },
            as_json,
        )
    incoming = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(incoming, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "import",
                "error": "invalid memory export format",
            },
            as_json,
        )
    store = load_store(DEFAULT_MEMORY_PATH)
    current = store.get("entries") if isinstance(store.get("entries"), list) else []
    new_entries = (
        incoming.get("entries") if isinstance(incoming.get("entries"), list) else []
    )
    merged = current + [entry for entry in new_entries if isinstance(entry, dict)]
    store["entries"] = merged
    save_store(DEFAULT_MEMORY_PATH, store)
    return emit(
        {
            "result": "PASS",
            "command": "import",
            "imported": len(new_entries),
            "entry_count": len(merged),
        },
        as_json,
    )


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    store = load_store(DEFAULT_MEMORY_PATH)
    entries = store.get("entries") if isinstance(store.get("entries"), list) else []
    warnings: list[str] = []
    if not entries:
        warnings.append("memory store has no entries yet")
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "path": str(DEFAULT_MEMORY_PATH),
            "entry_count": len(entries),
            "warnings": warnings,
            "quick_fixes": [
                "/learn capture --json",
                "/memory-lifecycle stats --json",
            ],
        },
        as_json,
    )


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "-h", "--help"}:
        return usage()
    if command == "stats":
        return cmd_stats(rest)
    if command == "cleanup":
        return cmd_cleanup(rest)
    if command == "compress":
        return cmd_compress(rest)
    if command == "export":
        return cmd_export(rest)
    if command == "import":
        return cmd_import(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
