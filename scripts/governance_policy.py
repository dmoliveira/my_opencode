#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_POLICY_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_GOVERNANCE_POLICY_PATH",
        "~/.config/opencode/my_opencode/runtime/governance_policy.json",
    )
).expanduser()

GUARDED_OPERATIONS = {
    "workflow.execute",
    "workflow.resume_execute",
    "delivery.execute",
    "delivery.close",
    "agent-pool.drain",
}


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"profile": "balanced", "grants": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"profile": "balanced", "grants": {}}
    if str(raw.get("profile") or "") not in {"off", "balanced", "strict"}:
        raw["profile"] = "balanced"
    if not isinstance(raw.get("grants"), dict):
        raw["grants"] = {}
    return raw


def save_policy(payload: dict[str, Any], path: Path = DEFAULT_POLICY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def authorize_operation(
    operation: str, ttl_minutes: int = 30, path: Path = DEFAULT_POLICY_PATH
) -> dict[str, Any]:
    policy = load_policy(path)
    grants = policy.get("grants") if isinstance(policy.get("grants"), dict) else {}
    expires_at = (now_utc() + timedelta(minutes=max(1, ttl_minutes))).replace(
        microsecond=0
    )
    grants[operation] = expires_at.isoformat().replace("+00:00", "Z")
    policy["grants"] = grants
    save_policy(policy, path)
    return {"operation": operation, "expires_at": grants[operation]}


def revoke_operation(operation: str, path: Path = DEFAULT_POLICY_PATH) -> bool:
    policy = load_policy(path)
    grants = policy.get("grants") if isinstance(policy.get("grants"), dict) else {}
    existed = operation in grants
    if existed:
        del grants[operation]
        policy["grants"] = grants
        save_policy(policy, path)
    return existed


def check_operation(
    operation: str,
    override_flag: bool = False,
    path: Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    policy = load_policy(path)
    profile = str(policy.get("profile") or "balanced")
    if profile in {"off", "balanced"}:
        return {
            "allowed": True,
            "reason_code": "profile_allows_operation",
            "profile": profile,
        }

    if operation not in GUARDED_OPERATIONS:
        return {
            "allowed": True,
            "reason_code": "operation_not_guarded",
            "profile": profile,
        }

    if override_flag:
        return {"allowed": True, "reason_code": "override_flag", "profile": profile}

    grants = policy.get("grants") if isinstance(policy.get("grants"), dict) else {}
    now = now_utc()
    for key in (operation, "*"):
        raw_expiry = str(grants.get(key) or "")
        if not raw_expiry:
            continue
        expiry = parse_iso(raw_expiry)
        if expiry and expiry >= now:
            return {
                "allowed": True,
                "reason_code": "authorized_grant",
                "profile": profile,
                "grant": {"scope": key, "expires_at": raw_expiry},
            }

    return {
        "allowed": False,
        "reason_code": "governance_strict_requires_authorize",
        "profile": profile,
        "operation": operation,
        "quick_fix": f"/governance authorize {operation} --ttl-minutes 30",
    }
