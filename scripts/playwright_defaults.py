#!/usr/bin/env python3
"""Canonical Playwright MCP defaults and exact legacy migration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

PLAYWRIGHT_MCP_PACKAGE_NAME = "@playwright/mcp"
PLAYWRIGHT_MCP_PACKAGE_SPEC = "@playwright/mcp@0.0.78"
PLAYWRIGHT_MCP_CAPABILITIES = (
    "testing",
    "network",
    "storage",
    "vision",
    "devtools",
    "pdf",
)
PLAYWRIGHT_MCP_CAPS_FLAG = "--caps=" + ",".join(PLAYWRIGHT_MCP_CAPABILITIES)
PLAYWRIGHT_MCP_COMMAND = (
    "npx",
    "-y",
    PLAYWRIGHT_MCP_PACKAGE_SPEC,
    "--isolated",
    PLAYWRIGHT_MCP_CAPS_FLAG,
)
PLAYWRIGHT_BROWSER_COMMAND = "npx"
PLAYWRIGHT_BROWSER_ARGS = (
    PLAYWRIGHT_MCP_PACKAGE_SPEC,
    "--isolated",
    PLAYWRIGHT_MCP_CAPS_FLAG,
)

_LEGACY_PACKAGE_SPEC = "@playwright/mcp@latest"
_LEGACY_MCP_COMMANDS = (
    ("npx", "-y", _LEGACY_PACKAGE_SPEC),
    ("npx", "-y", _LEGACY_PACKAGE_SPEC, PLAYWRIGHT_MCP_CAPS_FLAG),
)
_LEGACY_BROWSER_INVOCATIONS = (
    (PLAYWRIGHT_BROWSER_COMMAND, (_LEGACY_PACKAGE_SPEC,)),
    (
        PLAYWRIGHT_BROWSER_COMMAND,
        (_LEGACY_PACKAGE_SPEC, PLAYWRIGHT_MCP_CAPS_FLAG),
    ),
)


def parse_playwright_capabilities(arguments: Sequence[object]) -> list[str]:
    """Return unique capability names from Playwright CLI arguments."""
    capabilities: list[str] = []
    for argument in arguments:
        text = str(argument)
        if not text.startswith("--caps="):
            continue
        capabilities.extend(
            item.strip() for item in text.split("=", 1)[1].split(",") if item.strip()
        )
    return list(dict.fromkeys(capabilities))


def inspect_playwright_invocation(arguments: Sequence[object]) -> dict[str, Any]:
    """Describe pinning, isolation, and capabilities without mutating arguments."""
    parts = [str(argument) for argument in arguments]
    package_spec = next(
        (
            part
            for part in parts
            if part == PLAYWRIGHT_MCP_PACKAGE_NAME
            or part.startswith(f"{PLAYWRIGHT_MCP_PACKAGE_NAME}@")
        ),
        "",
    )
    package_version = (
        package_spec.removeprefix(f"{PLAYWRIGHT_MCP_PACKAGE_NAME}@")
        if package_spec.startswith(f"{PLAYWRIGHT_MCP_PACKAGE_NAME}@")
        else ""
    )
    capabilities = parse_playwright_capabilities(parts)
    canonical_forms = {
        PLAYWRIGHT_MCP_COMMAND,
        (PLAYWRIGHT_BROWSER_COMMAND, *PLAYWRIGHT_BROWSER_ARGS),
    }
    legacy_forms = {
        *_LEGACY_MCP_COMMANDS,
        *(
            (legacy_command, *legacy_args)
            for legacy_command, legacy_args in _LEGACY_BROWSER_INVOCATIONS
        ),
    }
    return {
        "package_spec": package_spec,
        "package_version": package_version,
        "pinned": bool(package_version and package_version != "latest"),
        "isolated": "--isolated" in parts,
        "legacy_arguments": [
            part for part in parts if part == _LEGACY_PACKAGE_SPEC
        ],
        "capabilities": capabilities,
        "recommended_capabilities": list(PLAYWRIGHT_MCP_CAPABILITIES),
        "missing_capabilities": [
            capability
            for capability in PLAYWRIGHT_MCP_CAPABILITIES
            if capability not in capabilities
        ],
        "canonical": tuple(parts) in canonical_forms,
        "known_legacy": tuple(parts) in legacy_forms,
    }


def migrate_known_mcp_command(command: list[Any]) -> tuple[list[Any], bool]:
    """Migrate only exact historical bundled MCP commands."""
    if any(command == list(legacy) for legacy in _LEGACY_MCP_COMMANDS):
        return list(PLAYWRIGHT_MCP_COMMAND), True
    return list(command), False


def migrate_known_browser_invocation(
    command: object,
    args: list[Any],
) -> tuple[object, list[Any], bool]:
    """Migrate only exact historical bundled browser-provider invocations."""
    if any(
        command == legacy_command and args == list(legacy_args)
        for legacy_command, legacy_args in _LEGACY_BROWSER_INVOCATIONS
    ):
        return PLAYWRIGHT_BROWSER_COMMAND, list(PLAYWRIGHT_BROWSER_ARGS), True
    return command, list(args), False
