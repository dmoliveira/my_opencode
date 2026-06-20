#!/usr/bin/env python3

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROUTING_PROFILES_DATA_PATH = (
    Path(__file__).resolve().parent.parent
    / "plugin"
    / "gateway-core"
    / "routing-profiles.data.json"
)


def _provider_from_model(model: Any) -> str:
    value = str(model or "").strip()
    if "/" in value:
        return value.split("/", 1)[0]
    return "unknown"


@lru_cache(maxsize=1)
def _load_routing_profiles_data() -> dict[str, Any]:
    payload = json.loads(ROUTING_PROFILES_DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing profiles data must be a JSON object")
    return payload


def _categories_from_shared_data() -> dict[str, dict[str, Any]]:
    payload = _load_routing_profiles_data()
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("routing profiles data is missing profiles object")
    categories: dict[str, dict[str, Any]] = {}
    for name, raw in profiles.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        categories[name] = dict(raw)
    return categories


def _default_category_from_shared_data() -> str:
    payload = _load_routing_profiles_data()
    value = payload.get("default_category")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("routing profiles data is missing default_category")
    return value.strip()


def _system_defaults_from_shared_data() -> dict[str, Any]:
    categories = _categories_from_shared_data()
    default_category = _default_category_from_shared_data()
    profile = categories.get(default_category)
    if not isinstance(profile, dict):
        raise ValueError("routing profiles data default_category must reference a profile")
    return {
        "model": profile.get("model"),
        "temperature": profile.get("temperature"),
        "reasoning": profile.get("reasoning"),
        "verbosity": profile.get("verbosity"),
    }


DEFAULT_CATEGORY = _default_category_from_shared_data()
SYSTEM_DEFAULTS = _system_defaults_from_shared_data()


def default_schema() -> dict[str, Any]:
    return {
        "default_category": DEFAULT_CATEGORY,
        "fallback": {
            "on_missing_category": "use_default_category",
            "on_unavailable_model": "use_default_category",
        },
        "categories": _categories_from_shared_data(),
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

    choice = requested_category if requested_category in categories else default_category
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

    requested_model = overrides.get("model")
    if not isinstance(requested_model, str) or not requested_model.strip():
        requested_model = None

    category_model = category_settings.get("model")
    selected_model = resolved.get("model")
    fallback_reason = "none"
    if requested_model and selected_model != requested_model:
        fallback_reason = trace[-1].get("reason", "fallback_unavailable_model_to_category")
    elif category_model and selected_model != category_model:
        fallback_reason = trace[-1].get("reason", "fallback_unavailable_model")

    return {
        "category": category_result.get("category"),
        "settings": resolved,
        "trace": trace,
        "selected_model": resolved.get("model"),
        "selected_provider": _provider_from_model(resolved.get("model")),
        "fallback_reason": fallback_reason,
        "resolution_trace": {
            "requested": {
                "category": requested_category,
                "model": requested_model,
            },
            "attempted": {
                "category": category_result.get("category"),
                "model": category_model,
            },
            "selected": {
                "category": category_result.get("category"),
                "model": selected_model,
            },
        },
    }
