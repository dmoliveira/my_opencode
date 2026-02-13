#!/usr/bin/env python3

from __future__ import annotations

import re
from typing import Any


PRECEDENCE = ["safe-apply", "deep-analyze", "parallel-research", "ulw"]
KEYWORDS = {
    "ulw": {
        "description": "Ultra-lightweight low-latency mode",
        "flags": {
            "analysis_depth": "low",
            "response_style": "concise",
            "exploration_mode": "minimal",
        },
    },
    "deep-analyze": {
        "description": "High-depth analysis mode",
        "flags": {
            "analysis_depth": "high",
            "response_style": "detailed",
            "verification_level": "strong",
            "reasoning_trace": "required",
        },
    },
    "parallel-research": {
        "description": "Parallel-safe research mode",
        "flags": {
            "parallel_research": "enabled",
            "exploration_mode": "parallel",
        },
    },
    "safe-apply": {
        "description": "Conservative edit/apply mode",
        "flags": {
            "edit_strategy": "conservative",
            "verification_level": "strict",
            "pre_apply_checks": "required",
        },
    },
}


def default_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "disabled_keywords": [],
        "active_modes": [],
        "effective_flags": {},
        "last_prompt": None,
    }


def normalize_disabled_keywords(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    return {
        str(item).strip().lower()
        for item in raw
        if isinstance(item, str) and str(item).strip().lower() in KEYWORDS
    }


def tokenize_prompt(prompt: str) -> list[str]:
    if not prompt:
        return []
    cleaned = re.sub(r"```[\s\S]*?```", " ", prompt)
    cleaned = re.sub(r"`[^`]*`", " ", cleaned)
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", cleaned)]


def resolve_prompt_modes(
    prompt: str,
    *,
    enabled: bool,
    disabled_keywords: set[str],
) -> dict[str, Any]:
    tokens = tokenize_prompt(prompt)
    if not enabled:
        return {
            "enabled": False,
            "matched_keywords": [],
            "effective_flags": {},
            "conflicts": [],
            "request_opt_out": "global_disabled",
            "tokens": tokens,
        }

    if "no-keyword-mode" in tokens:
        return {
            "enabled": True,
            "matched_keywords": [],
            "effective_flags": {},
            "conflicts": [],
            "request_opt_out": "no-keyword-mode",
            "tokens": tokens,
        }

    request_disabled = {
        token[3:]
        for token in tokens
        if token.startswith("no-") and token[3:] in KEYWORDS
    }
    blocked = set(disabled_keywords) | request_disabled

    matched = [
        keyword
        for keyword in PRECEDENCE
        if keyword in tokens and keyword not in blocked
    ]

    effective_flags: dict[str, Any] = {}
    flag_sources: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    for keyword in matched:
        keyword_flags = KEYWORDS[keyword]["flags"]
        for flag_name, flag_value in keyword_flags.items():
            if (
                flag_name in effective_flags
                and effective_flags[flag_name] != flag_value
            ):
                conflicts.append(
                    {
                        "flag": flag_name,
                        "kept_keyword": flag_sources[flag_name],
                        "kept_value": effective_flags[flag_name],
                        "discarded_keyword": keyword,
                        "discarded_value": flag_value,
                    }
                )
                continue
            effective_flags[flag_name] = flag_value
            flag_sources[flag_name] = keyword

    request_opt_out = "none"
    if request_disabled:
        request_opt_out = "keyword_scoped"

    return {
        "enabled": True,
        "matched_keywords": matched,
        "effective_flags": effective_flags,
        "conflicts": conflicts,
        "request_opt_out": request_opt_out,
        "blocked_keywords": sorted(blocked),
        "tokens": tokens,
    }
