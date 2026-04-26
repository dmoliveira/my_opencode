#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = getattr(datetime, "UTC", timezone.utc)
VALID_CONCISE_MODES = ("off", "lite", "full", "ultra", "review", "commit")
DEFAULT_CONCISE_MODE = "off"
STATE_RELATIVE_PATH = Path(".opencode") / "gateway-core.state.json"
SIDECAR_RELATIVE_PATH = Path(".opencode") / "gateway-core.config.json"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_session_id() -> str:
    return str(
        os.environ.get("OPENCODE_SESSION_ID")
        or os.environ.get("MY_OPENCODE_SESSION_ID")
        or ""
    ).strip()


def normalize_mode(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_CONCISE_MODES else DEFAULT_CONCISE_MODE


def resolve_state_path(cwd: Path) -> Path:
    return cwd / STATE_RELATIVE_PATH


def resolve_sidecar_path(cwd: Path) -> Path:
    env_path = str(os.environ.get("MY_OPENCODE_GATEWAY_CONFIG_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    local = cwd / SIDECAR_RELATIVE_PATH
    if local.exists():
        return local
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    home_sidecar = home / ".config" / "opencode" / "my_opencode" / "gateway-core.config.json"
    if home_sidecar.exists():
        return home_sidecar
    return local


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_gateway_state(cwd: Path) -> dict[str, Any]:
    return load_json(resolve_state_path(cwd))


def save_gateway_state(cwd: Path, payload: dict[str, Any]) -> None:
    save_json(resolve_state_path(cwd), payload)


def load_sidecar_config(cwd: Path) -> tuple[dict[str, Any], Path]:
    path = resolve_sidecar_path(cwd)
    return load_json(path), path


def concise_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("conciseMode")
    return raw if isinstance(raw, dict) else {}


def concise_default_mode(config: dict[str, Any]) -> str:
    section = concise_config(config)
    if section.get("enabled") is not True:
        return DEFAULT_CONCISE_MODE
    return normalize_mode(section.get("defaultMode"))


def concise_active_state(cwd: Path) -> dict[str, Any] | None:
    state = load_gateway_state(cwd)
    raw = state.get("conciseMode")
    if not isinstance(raw, dict):
        return None
    mode = normalize_mode(raw.get("mode"))
    session_id = str(raw.get("sessionId") or "").strip()
    if not session_id:
        return None
    return {
        "mode": mode,
        "source": str(raw.get("source") or "state"),
        "sessionId": session_id,
        "activatedAt": str(raw.get("activatedAt") or ""),
        "updatedAt": str(raw.get("updatedAt") or state.get("lastUpdatedAt") or ""),
    }


def effective_concise_mode(cwd: Path) -> dict[str, Any]:
    config, sidecar_path = load_sidecar_config(cwd)
    stored_active = concise_active_state(cwd)
    session_id = current_session_id()
    default_mode = concise_default_mode(config)
    session_match = bool(stored_active and stored_active["sessionId"] == session_id)
    if session_match and stored_active:
        effective = stored_active["mode"]
        source = stored_active["source"] or "state"
    else:
        effective = default_mode
        source = "sidecar_default" if default_mode != DEFAULT_CONCISE_MODE else "default"
    return {
        "effective_mode": effective,
        "effective_source": source,
        "current_session_id": session_id or None,
        "default_mode": default_mode,
        "default_enabled": concise_config(config).get("enabled") is True,
        "sidecar_path": str(sidecar_path),
        "sidecar_exists": sidecar_path.exists(),
        "state_path": str(resolve_state_path(cwd)),
        "state_exists": resolve_state_path(cwd).exists(),
        "active_state": stored_active if session_match else None,
        "stored_active_state": stored_active,
        "session_match": session_match,
        "valid_modes": list(VALID_CONCISE_MODES),
    }


def set_active_mode(cwd: Path, mode: str, *, source: str, session_id: str) -> dict[str, Any]:
    normalized = normalize_mode(mode)
    state = load_gateway_state(cwd)
    activated_at = now_iso()
    existing = state.get("conciseMode")
    if (
        isinstance(existing, dict)
        and normalize_mode(existing.get("mode")) == normalized
        and str(existing.get("sessionId") or "") == session_id
    ):
        activated_at = str(existing.get("activatedAt") or activated_at)
    state["conciseMode"] = {
        "mode": normalized,
        "source": source,
        "sessionId": session_id,
        "activatedAt": activated_at,
        "updatedAt": now_iso(),
    }
    state["lastUpdatedAt"] = now_iso()
    if "activeLoop" not in state:
        state["activeLoop"] = None
    save_gateway_state(cwd, state)
    return effective_concise_mode(cwd)


def set_default_mode(cwd: Path, mode: str, *, enabled: bool = True) -> dict[str, Any]:
    normalized = normalize_mode(mode)
    config, path = load_sidecar_config(cwd)
    config["conciseMode"] = {
        "enabled": bool(enabled),
        "defaultMode": normalized,
    }
    save_json(path, config)
    return effective_concise_mode(cwd)


def concise_skill_candidates(cwd: Path) -> list[Path]:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    candidates = [
        cwd / "skills" / "concise-mode" / "SKILL.md",
        cwd.parent / "agents_md" / "skills" / "concise-mode" / "SKILL.md",
        cwd.parent / "agents.md" / "skills" / "concise-mode" / "SKILL.md",
        home / ".config" / "opencode" / "agents_md" / "skills" / "concise-mode" / "SKILL.md",
    ]
    try:
        for sibling in cwd.parent.glob("agents_md*/skills/concise-mode/SKILL.md"):
            candidates.append(sibling)
    except Exception:
        pass
    return candidates


def find_skill_path(cwd: Path) -> str | None:
    for candidate in concise_skill_candidates(cwd):
        if candidate.exists():
            return str(candidate)
    return None
