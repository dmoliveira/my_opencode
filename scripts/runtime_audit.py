#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_AUDIT_PATH",
        "~/.config/opencode/my_opencode/runtime/audit_log.json",
    )
).expanduser()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_audit(path: Path = DEFAULT_AUDIT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "events": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"version": 1, "events": []}
    events = raw.get("events") if isinstance(raw.get("events"), list) else []
    return {"version": int(raw.get("version", 1) or 1), "events": events}


def save_audit(payload: dict[str, Any], path: Path = DEFAULT_AUDIT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def append_event(
    command: str,
    action: str,
    result: str,
    details: dict[str, Any] | None = None,
    path: Path = DEFAULT_AUDIT_PATH,
) -> dict[str, Any]:
    state = load_audit(path)
    events = state.get("events") if isinstance(state.get("events"), list) else []
    entry = {
        "id": f"aud-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
        "at": now_iso(),
        "command": command,
        "action": action,
        "result": result,
        "details": details or {},
    }
    events.insert(0, entry)
    state["events"] = events[:500]
    save_audit(state, path)
    return entry
