#!/usr/bin/env python3

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


DEFAULT_PROFILE = "balanced"

PROFILE_LIMITS: dict[str, dict[str, int]] = {
    "conservative": {
        "wall_clock_seconds": 900,
        "tool_call_count": 80,
        "token_estimate": 80_000,
    },
    "balanced": {
        "wall_clock_seconds": 1800,
        "tool_call_count": 180,
        "token_estimate": 180_000,
    },
    "extended": {
        "wall_clock_seconds": 3600,
        "tool_call_count": 360,
        "token_estimate": 360_000,
    },
}

SOFT_RATIO: dict[str, float] = {
    "conservative": 0.75,
    "balanced": 0.80,
    "extended": 0.85,
}

DIMENSION_TO_REASON = {
    "wall_clock_seconds": "budget_wall_clock_exceeded",
    "tool_call_count": "budget_tool_call_exceeded",
    "token_estimate": "budget_token_estimate_exceeded",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def resolve_budget_policy(config: dict[str, Any]) -> dict[str, Any]:
    section_any = config.get("budget_runtime")
    section = section_any if isinstance(section_any, dict) else {}
    profile = str(section.get("profile") or DEFAULT_PROFILE)
    if profile not in PROFILE_LIMITS:
        profile = DEFAULT_PROFILE

    limits = dict(PROFILE_LIMITS[profile])
    overrides_any = section.get("overrides")
    overrides = overrides_any if isinstance(overrides_any, dict) else {}
    for key in ("wall_clock_seconds", "tool_call_count", "token_estimate"):
        raw_value = overrides.get(key)
        if isinstance(raw_value, int) and raw_value > 0:
            max_allowed = int(PROFILE_LIMITS[profile][key] * 2)
            limits[key] = min(raw_value, max_allowed)

    return {
        "profile": profile,
        "limits": limits,
        "soft_ratio": SOFT_RATIO[profile],
    }


def build_budget_state(
    started_at: str,
    *,
    tool_call_count: int,
    token_estimate: int,
    now_ts: str | None = None,
) -> dict[str, Any]:
    started = _parse_iso(started_at)
    current = _parse_iso(now_ts or now_iso())
    wall = 0
    if started is not None and current is not None:
        wall = max(0, int((current - started).total_seconds()))
    return {
        "wall_clock_seconds": wall,
        "tool_call_count": max(0, tool_call_count),
        "token_estimate": max(0, token_estimate),
        "captured_at": now_ts or now_iso(),
    }


def evaluate_budget(policy: dict[str, Any], counters: dict[str, Any]) -> dict[str, Any]:
    limits_any = policy.get("limits")
    limits = limits_any if isinstance(limits_any, dict) else {}
    soft_ratio = float(policy.get("soft_ratio") or 0.8)

    warnings: list[str] = []
    hard_reasons: list[str] = []
    usage: dict[str, float] = {}
    exceeded_dimensions: list[str] = []

    for key in ("wall_clock_seconds", "tool_call_count", "token_estimate"):
        limit = int(limits.get(key, 0) or 0)
        current = int(counters.get(key, 0) or 0)
        ratio = (current / limit) if limit > 0 else 0.0
        usage[key] = ratio
        if limit > 0 and current >= limit:
            exceeded_dimensions.append(key)
            hard_reasons.append(DIMENSION_TO_REASON[key])
            continue
        if limit > 0 and ratio >= soft_ratio:
            pct = int(ratio * 100)
            warnings.append(f"{key} is at {pct}% of configured budget")

    result = "PASS"
    if hard_reasons:
        result = "FAIL"
    elif warnings:
        result = "WARN"

    primary_reason = hard_reasons[0] if hard_reasons else "budget_within_limits"
    recommendations = [
        "reduce scope or split work into smaller checkpoints",
        "use conservative profile for tighter sessions or extended for larger runs",
        "apply temporary override with explicit reason when necessary",
    ]
    if result == "PASS":
        recommendations = ["budget usage is healthy; continue execution"]

    return {
        "result": result,
        "reason_code": primary_reason,
        "reason_codes": hard_reasons,
        "warnings": warnings,
        "exceeded_dimensions": exceeded_dimensions,
        "usage_ratio": usage,
        "recommendations": recommendations,
    }
