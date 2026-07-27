#!/usr/bin/env python3
"""Canonical Playwright MCP/CLI contracts and exact migration helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PLAYWRIGHT_MCP_PACKAGE_NAME = "@playwright/mcp"
PLAYWRIGHT_MCP_VERSION = "0.0.78"
PLAYWRIGHT_MCP_PACKAGE_SPEC = "@playwright/mcp@0.0.78"
PLAYWRIGHT_MCP_LICENSE = "Apache-2.0"
PLAYWRIGHT_MCP_INTEGRITY = (
    "sha512-XLTUeA6mEN9sQ+hJ4dfG8EIkDbxS0K3Trc2RBkUJuf02TgE2FQRNTMtq/"
    "aJfhyRMINsRl/Ybc4sxcWLtFn4/TQ=="
)
PLAYWRIGHT_MCP_GIT_HEAD = "5f8fc00210b27b4407c375b59cda4838045d429c"
PLAYWRIGHT_MCP_TOOL_COUNT = 68
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

PLAYWRIGHT_CLI_PACKAGE_NAME = "@playwright/cli"
PLAYWRIGHT_CLI_VERSION = "0.1.17"
PLAYWRIGHT_CLI_PACKAGE_SPEC = (
    f"{PLAYWRIGHT_CLI_PACKAGE_NAME}@{PLAYWRIGHT_CLI_VERSION}"
)
PLAYWRIGHT_CLI_LICENSE = "Apache-2.0"
PLAYWRIGHT_CLI_INTEGRITY = (
    "sha512-VBw6y3p8eqOqmjKg07IkWSPGKJkpIhMRNDFI6DOYsDD6fAfcI1XYEWMLWyhSZQ0B/"
    "Oc2KN49eq4XqE64PUPHBg=="
)
PLAYWRIGHT_CLI_SHASUM = "abfd43bec9e9fca2628ba98f7061a81cde7ec6bb"
PLAYWRIGHT_CLI_SOURCE_REVISION = "v0.1.17"
PLAYWRIGHT_CLI_SOURCE_URL = (
    "https://github.com/microsoft/playwright-cli/releases/tag/v0.1.17"
)
PLAYWRIGHT_CLI_NODE_RANGE = ">=18"
PLAYWRIGHT_CLI_MIN_NODE_MAJOR = 18
PLAYWRIGHT_CLI_REGISTRY = "https://registry.npmjs.org/"
PLAYWRIGHT_CLI_COMMAND = ("npx", "--yes", PLAYWRIGHT_CLI_PACKAGE_SPEC)
PLAYWRIGHT_CLI_VERSION_COMMAND = (*PLAYWRIGHT_CLI_COMMAND, "--version")
PLAYWRIGHT_CLI_VERSION_OUTPUT = PLAYWRIGHT_CLI_VERSION
PLAYWRIGHT_CLI_METADATA_FIELDS = (
    "version",
    "license",
    "engines.node",
    "dist.integrity",
    "dist.shasum",
    "scripts",
)
PLAYWRIGHT_CLI_LIFECYCLE_SCRIPTS = (
    "preinstall",
    "install",
    "postinstall",
    "prepublish",
    "prepare",
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


def _nested_value(payload: Mapping[str, Any], key: str) -> Any:
    if key in payload:
        return payload.get(key)
    current: Any = payload
    for part in key.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def inspect_playwright_cli_metadata(payload: object) -> dict[str, Any]:
    """Return a safe exact-package provenance comparison."""
    metadata = payload if isinstance(payload, Mapping) else {}
    scripts = metadata.get("scripts")
    script_map = scripts if isinstance(scripts, Mapping) else {}
    lifecycle_scripts = sorted(
        name for name in PLAYWRIGHT_CLI_LIFECYCLE_SCRIPTS if script_map.get(name)
    )
    observed = {
        "version": metadata.get("version"),
        "license": metadata.get("license"),
        "node_range": _nested_value(metadata, "engines.node"),
        "integrity": _nested_value(metadata, "dist.integrity"),
        "shasum": _nested_value(metadata, "dist.shasum"),
        "lifecycle_scripts": lifecycle_scripts,
    }
    expected = {
        "version": PLAYWRIGHT_CLI_VERSION,
        "license": PLAYWRIGHT_CLI_LICENSE,
        "node_range": PLAYWRIGHT_CLI_NODE_RANGE,
        "integrity": PLAYWRIGHT_CLI_INTEGRITY,
        "shasum": PLAYWRIGHT_CLI_SHASUM,
        "lifecycle_scripts": [],
    }
    mismatches = [
        key for key, expected_value in expected.items() if observed[key] != expected_value
    ]
    return {
        "package_spec": PLAYWRIGHT_CLI_PACKAGE_SPEC,
        "source_revision": PLAYWRIGHT_CLI_SOURCE_REVISION,
        "source_url": PLAYWRIGHT_CLI_SOURCE_URL,
        "expected": expected,
        "observed": observed,
        "mismatches": mismatches,
        "verified": not mismatches,
    }


def playwright_cli_npm_environment(
    sandbox: Path,
    source_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the minimal npm/npx environment for verified CLI execution."""
    source = source_env if source_env is not None else os.environ
    env = {
        key: value
        for key in ("LANG", "LC_ALL", "PATH")
        if (value := source.get(key))
    }
    env.update(
        {
            "HOME": str(sandbox / "home"),
            "TMPDIR": str(sandbox / "tmp"),
            "XDG_CACHE_HOME": str(sandbox / "xdg-cache"),
            "XDG_CONFIG_HOME": str(sandbox / "xdg-config"),
            "CI": "true",
            "NO_COLOR": "1",
            "npm_config_cache": str(sandbox / "npm-cache"),
            "npm_config_userconfig": str(sandbox / "user.npmrc"),
            "npm_config_globalconfig": str(sandbox / "global.npmrc"),
            "npm_config_prefix": str(sandbox / "npm-prefix"),
            "npm_config_registry": PLAYWRIGHT_CLI_REGISTRY,
            "npm_config_ignore_scripts": "true",
            "npm_config_yes": "true",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "npm_config_update_notifier": "false",
            "npm_config_package_lock": "false",
            "PWTEST_SOCKETS_DIR": str(sandbox / "s"),
        }
    )
    return env


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
