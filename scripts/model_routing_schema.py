#!/usr/bin/env python3

from __future__ import annotations

from typing import Any


DEFAULT_CATEGORY = "quick"
SYSTEM_DEFAULTS = {
    "model": "openai/gpt-5.3-codex",
    "temperature": 0.2,
    "reasoning": "medium",
    "verbosity": "medium",
}


def default_schema() -> dict[str, Any]:
    return {
        "default_category": DEFAULT_CATEGORY,
        "fallback": {
            "on_missing_category": "use_default_category",
            "on_unavailable_model": "use_default_category",
        },
        "categories": {
            "quick": {
                "description": "Fast responses for routine operational tasks",
                "model": "openai/gpt-5-mini",
                "temperature": 0.1,
                "reasoning": "low",
                "verbosity": "low",
            },
            "deep": {
                "description": "Higher-reliability analysis for complex engineering work",
                "model": "openai/gpt-5.3-codex",
                "temperature": 0.1,
                "reasoning": "high",
                "verbosity": "medium",
            },
            "visual": {
                "description": "UI/UX tasks with higher detail and output richness",
                "model": "openai/gpt-5.3-codex",
                "temperature": 0.2,
                "reasoning": "medium",
                "verbosity": "high",
            },
            "writing": {
                "description": "Documentation and communication with richer language style",
                "model": "openai/gpt-5.3-codex",
                "temperature": 0.6,
                "reasoning": "medium",
                "verbosity": "high",
            },
        },
    }


def validate_schema(schema: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    categories = schema.get("categories")
    if not isinstance(categories, dict) or not categories:
        return ["categories must be a non-empty object"]

    default_category = schema.get("default_category")
    if not isinstance(default_category, str) or default_category not in categories:
        problems.append("default_category must reference a defined category")

    for name, cfg in categories.items():
        if not isinstance(cfg, dict):
            problems.append(f"category {name} must be an object")
            continue
        for field in ("description", "model", "reasoning", "verbosity"):
            if not isinstance(cfg.get(field), str) or not str(cfg.get(field)).strip():
                problems.append(f"category {name} is missing non-empty {field}")
        temp = cfg.get("temperature")
        if not isinstance(temp, (int, float)):
            problems.append(f"category {name} temperature must be numeric")
    return problems


def resolve_category(
    schema: dict[str, Any],
    requested_category: str | None,
    available_models: set[str] | None = None,
) -> dict[str, Any]:
    categories = schema.get("categories")
    if not isinstance(categories, dict):
        raise ValueError("invalid schema: categories must be object")

    default_category = schema.get("default_category")
    if not isinstance(default_category, str) or default_category not in categories:
        raise ValueError("invalid schema: default_category is missing")

    choice = (
        requested_category if requested_category in categories else default_category
    )
    reason = (
        "requested_category"
        if requested_category and requested_category in categories
        else "fallback_missing_category"
    )

    selected = categories[choice]
    if available_models is not None and selected.get("model") not in available_models:
        choice = default_category
        selected = categories[choice]
        reason = "fallback_unavailable_model"

    return {
        "category": choice,
        "settings": selected,
        "reason": reason,
    }


def resolve_model_settings(
    schema: dict[str, Any],
    requested_category: str | None,
    user_overrides: dict[str, Any] | None = None,
    system_defaults: dict[str, Any] | None = None,
    available_models: set[str] | None = None,
) -> dict[str, Any]:
    overrides = user_overrides if isinstance(user_overrides, dict) else {}
    base_system = dict(SYSTEM_DEFAULTS)
    if isinstance(system_defaults, dict):
        for key in ("model", "temperature", "reasoning", "verbosity"):
            if key in system_defaults:
                base_system[key] = system_defaults[key]

    category_result = resolve_category(
        schema=schema,
        requested_category=requested_category,
        available_models=available_models,
    )
    category_settings = category_result.get("settings", {})
    if not isinstance(category_settings, dict):
        category_settings = {}

    resolved = dict(base_system)
    trace = [
        {
            "step": 1,
            "source": "system_default",
            "reason": "base_defaults",
            "applied": dict(base_system),
        }
    ]

    for field in ("model", "temperature", "reasoning", "verbosity"):
        if field in category_settings:
            resolved[field] = category_settings[field]
    trace.append(
        {
            "step": 2,
            "source": "category_default",
            "reason": category_result.get("reason"),
            "category": category_result.get("category"),
            "applied": {
                field: category_settings.get(field)
                for field in ("model", "temperature", "reasoning", "verbosity")
                if field in category_settings
            },
        }
    )

    override_applied: dict[str, Any] = {}
    for field in ("model", "temperature", "reasoning", "verbosity"):
        if field in overrides and overrides[field] is not None:
            resolved[field] = overrides[field]
            override_applied[field] = overrides[field]
    trace.append(
        {
            "step": 3,
            "source": "user_override",
            "reason": "explicit_override" if override_applied else "none",
            "applied": override_applied,
        }
    )

    if available_models is not None and resolved.get("model") not in available_models:
        fallback_model = category_settings.get("model")
        fallback_reason = "fallback_unavailable_model_to_category"
        if fallback_model not in available_models:
            fallback_model = base_system.get("model")
            fallback_reason = "fallback_unavailable_model_to_system_default"
        resolved["model"] = fallback_model
        trace.append(
            {
                "step": 4,
                "source": "availability_fallback",
                "reason": fallback_reason,
                "applied": {"model": fallback_model},
            }
        )

    return {
        "category": category_result.get("category"),
        "settings": resolved,
        "trace": trace,
    }
