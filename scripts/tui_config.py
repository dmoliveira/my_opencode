#!/usr/bin/env python3

"""Safely add the managed execution-sidebar TUI plugin without replacing user config."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote, urlparse

from config_layering import (
    ConfigFileParticipant,
    ConfigTransactionError,
    ConfigTransactionResult,
    edit_config_batch,
)


TUI_SCHEMA = "https://opencode.ai/tui.json"
_MANAGED_PLUGIN_SUFFIX = ("plugin", "gateway-sidebar")
_MANAGED_REPOSITORY_NAME = "my_opencode"
_MANAGED_WORKTREE_PREFIX = "my_opencode-wt-"


def _plugin_source(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, list) and entry and isinstance(entry[0], str):
        return entry[0]
    return None


def _managed_plugin_path(source: str) -> Path | None:
    """Return a normalized local path when source names our managed sidebar."""
    if not source.lower().startswith("file:"):
        return None

    home = os.environ.get("HOME", str(Path.home()))
    expanded = source.replace("{env:HOME}", home)
    parsed = urlparse(expanded)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None

    candidate = Path(unquote(parsed.path)).expanduser().resolve(strict=False)
    if candidate.parts[-len(_MANAGED_PLUGIN_SUFFIX) :] != _MANAGED_PLUGIN_SUFFIX:
        return None
    return candidate


def _is_managed_sidebar(source: str, current_plugin: Path) -> bool:
    candidate = _managed_plugin_path(source)
    if candidate is None:
        return False
    if candidate == current_plugin:
        return True
    repository_directory = candidate.parts[-len(_MANAGED_PLUGIN_SUFFIX) - 1]
    return (
        repository_directory == _MANAGED_REPOSITORY_NAME
        or repository_directory.startswith(_MANAGED_WORKTREE_PREFIX)
    )


def _with_plugin_source(entry: Any, plugin_uri: str) -> Any:
    if isinstance(entry, str):
        return plugin_uri
    if isinstance(entry, list):
        return [plugin_uri, *entry[1:]]
    raise ValueError("managed TUI plugin entry has no source")


def ensure_execution_sidebar(
    config_path: Path,
    plugin_path: Path,
) -> ConfigTransactionResult:
    resolved_plugin = plugin_path.expanduser().resolve(strict=True)
    if not resolved_plugin.is_dir():
        raise ValueError(f"TUI plugin path is not a directory: {resolved_plugin}")
    plugin_uri = resolved_plugin.as_uri()

    def mutate(config: dict[str, Any]) -> None:
        plugins = config.get("plugin")
        if plugins is None:
            plugins = []
            config["plugin"] = plugins
        if not isinstance(plugins, list):
            raise ValueError("tui.json plugin must be an array")
        managed_indices = [
            index
            for index, entry in enumerate(plugins)
            if (source := _plugin_source(entry)) is not None
            and _is_managed_sidebar(source, resolved_plugin)
        ]
        if managed_indices:
            first = managed_indices[0]
            plugins[first] = _with_plugin_source(plugins[first], plugin_uri)
            for index in reversed(managed_indices[1:]):
                del plugins[index]
        else:
            plugins.append([plugin_uri, {}])
        config.setdefault("$schema", TUI_SCHEMA)

    return edit_config_batch((ConfigFileParticipant(config_path.expanduser(), mutate),))


def _result_payload(
    result: ConfigTransactionResult,
    config_path: Path,
    plugin_path: Path,
) -> dict[str, Any]:
    return {
        "result": "PASS",
        "changed": result.changed,
        "config": str(config_path.expanduser()),
        "plugin": str(plugin_path.expanduser().resolve(strict=True)),
    }


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="tui_config.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ensure = subparsers.add_parser("ensure-execution-sidebar")
    ensure.add_argument("--config", required=True)
    ensure.add_argument("--plugin-path", required=True)
    ensure.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))

    config_path = Path(args.config)
    plugin_path = Path(args.plugin_path)
    try:
        result = ensure_execution_sidebar(config_path, plugin_path)
    except (ConfigTransactionError, OSError, ValueError) as error:
        print(f"error: unable to configure OpenCode TUI plugin: {error}", file=sys.stderr)
        return 2

    payload = _result_payload(result, config_path, plugin_path)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"TUI config: {payload['config']}")
        print(f"Execution sidebar: {payload['plugin']}")
        print(f"Changed: {'yes' if result.changed else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
