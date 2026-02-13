#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


VALID_EVENTS = ("PreToolUse", "PostToolUse", "Stop")


@dataclass(frozen=True)
class HookRegistration:
    hook_id: str
    event: str
    priority: int = 100


def normalize_hook_config(raw: Any) -> dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    disabled: set[str] = set()
    for value in cfg.get("disabled", []):
        if isinstance(value, str):
            item = value.strip()
            if item:
                disabled.add(item)

    order: list[str] = []
    seen: set[str] = set()
    for value in cfg.get("order", []):
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item and item not in seen:
            seen.add(item)
            order.append(item)

    enabled = cfg.get("enabled", False)
    return {
        "enabled": isinstance(enabled, bool) and enabled,
        "disabled": sorted(disabled),
        "order": order,
    }


def _validate_registrations(hooks: Iterable[HookRegistration]) -> None:
    seen_ids: set[str] = set()
    for hook in hooks:
        if not hook.hook_id:
            raise ValueError("hook_id must be non-empty")
        if hook.hook_id in seen_ids:
            raise ValueError(f"duplicate hook_id: {hook.hook_id}")
        seen_ids.add(hook.hook_id)
        if hook.event not in VALID_EVENTS:
            raise ValueError(f"invalid hook event for {hook.hook_id}: {hook.event}")
        if not isinstance(hook.priority, int):
            raise ValueError(f"priority must be int for {hook.hook_id}")


def resolve_event_plan(
    event: str,
    hooks: Iterable[HookRegistration],
    config: dict[str, Any] | None,
) -> list[HookRegistration]:
    if event not in VALID_EVENTS:
        raise ValueError(f"unsupported event: {event}")

    all_hooks = list(hooks)
    _validate_registrations(all_hooks)

    cfg = normalize_hook_config(config)
    disabled = set(cfg["disabled"])
    order_index = {hook_id: idx for idx, hook_id in enumerate(cfg["order"])}

    selected = [
        hook
        for hook in all_hooks
        if hook.event == event and hook.hook_id not in disabled
    ]
    selected.sort(
        key=lambda hook: (
            order_index.get(hook.hook_id, 10_000),
            hook.priority,
            hook.hook_id,
        )
    )
    return selected
