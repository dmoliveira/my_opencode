#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from config_layering import load_layered_config  # type: ignore


DEFAULT_LSP_SERVERS: list[dict[str, Any]] = [
    {
        "id": "typescript-language-server",
        "command": ["typescript-language-server", "--stdio"],
        "binary": "typescript-language-server",
        "language": "typescript/javascript",
        "extensions": [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"],
        "priority": -100,
        "source": "builtin",
        "install_hint": "npm install -g typescript typescript-language-server",
    },
    {
        "id": "pyright",
        "command": ["pyright-langserver", "--stdio"],
        "binary": "pyright-langserver",
        "language": "python",
        "extensions": [".py"],
        "priority": -100,
        "source": "builtin",
        "install_hint": "npm install -g pyright",
    },
    {
        "id": "rust-analyzer",
        "command": ["rust-analyzer"],
        "binary": "rust-analyzer",
        "language": "rust",
        "extensions": [".rs"],
        "priority": -100,
        "source": "builtin",
        "install_hint": "Install rust-analyzer via rustup/components or package manager",
    },
    {
        "id": "gopls",
        "command": ["gopls"],
        "binary": "gopls",
        "language": "go",
        "extensions": [".go"],
        "priority": -100,
        "source": "builtin",
        "install_hint": "go install golang.org/x/tools/gopls@latest",
    },
]


def usage() -> int:
    print("usage: /lsp status [--json] | /lsp doctor [--json]")
    return 2


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _infer_language(extensions: list[str]) -> str:
    ext_set = {ext.lower() for ext in extensions}
    if ext_set & {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        return "typescript/javascript"
    if ".py" in ext_set:
        return "python"
    if ".rs" in ext_set:
        return "rust"
    if ".go" in ext_set:
        return "go"
    return "custom"


def _resolve_servers() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config_info: dict[str, Any] = {
        "loaded": False,
        "path": None,
        "configured_servers": 0,
        "warnings": [],
    }
    disabled: set[str] = set()
    configured: dict[str, dict[str, Any]] = {}

    try:
        config, path = load_layered_config()
        config_info["loaded"] = True
        config_info["path"] = str(path)
        section = config.get("lsp")
        if section is None:
            section = {}
        if not isinstance(section, dict):
            config_info["warnings"].append(
                "ignoring invalid lsp config: expected object"
            )
            section = {}

        for server_id, raw_entry in section.items():
            if not isinstance(raw_entry, dict):
                config_info["warnings"].append(
                    f"ignoring lsp.{server_id}: expected object"
                )
                continue

            if bool(raw_entry.get("disabled", False)):
                disabled.add(str(server_id))
                continue

            command = _coerce_string_list(raw_entry.get("command"))
            extensions = _coerce_string_list(raw_entry.get("extensions"))
            if not command or not extensions:
                config_info["warnings"].append(
                    f"ignoring lsp.{server_id}: command and extensions are required"
                )
                continue

            priority_raw = raw_entry.get("priority", 0)
            try:
                priority = int(priority_raw)
            except (TypeError, ValueError):
                priority = 0

            binary = command[0]
            configured[str(server_id)] = {
                "id": str(server_id),
                "command": command,
                "binary": binary,
                "language": _infer_language(extensions),
                "extensions": extensions,
                "priority": priority,
                "source": "config",
                "env": raw_entry.get("env"),
                "initialization": raw_entry.get("initialization"),
                "install_hint": f"Install '{binary}' and ensure it is in PATH",
            }
    except Exception as exc:
        config_info["warnings"].append(f"failed to load layered config: {exc}")

    servers: list[dict[str, Any]] = []
    for server_id in sorted(
        configured.keys(),
        key=lambda item: (-int(configured[item].get("priority", 0)), item),
    ):
        servers.append(configured[server_id])

    for builtin in DEFAULT_LSP_SERVERS:
        server_id = str(builtin["id"])
        if server_id in disabled or server_id in configured:
            continue
        servers.append(dict(builtin))

    config_info["configured_servers"] = len(configured)
    config_info["disabled_servers"] = sorted(disabled)
    return servers, config_info


def _collect_servers() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved, config_info = _resolve_servers()
    servers: list[dict[str, Any]] = []
    for server in resolved:
        binary = str(server["binary"])
        installed = shutil.which(binary) is not None
        row = dict(server)
        row["installed"] = installed
        servers.append(row)
    return servers, config_info


def _group_by_language(servers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for server in servers:
        language = str(server["language"])
        state = grouped.setdefault(
            language,
            {
                "installed": 0,
                "total": 0,
                "servers": [],
            },
        )
        state["total"] = int(state["total"]) + 1
        if bool(server["installed"]):
            state["installed"] = int(state["installed"]) + 1
        state["servers"].append(server["id"])
    return grouped


def command_status(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args

    servers, config_info = _collect_servers()
    installed = [row for row in servers if row["installed"]]
    missing = [row for row in servers if not row["installed"]]
    report = {
        "result": "PASS",
        "installed": len(installed),
        "total": len(servers),
        "servers": servers,
        "languages": _group_by_language(servers),
        "missing_server_ids": [row["id"] for row in missing],
        "config": config_info,
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"installed: {report['installed']}/{report['total']}")
        for row in servers:
            state = "yes" if row["installed"] else "no"
            print(
                f"- {row['id']}: installed={state} source={row['source']} binary={row['binary']}"
            )
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args

    servers, config_info = _collect_servers()
    installed = [row for row in servers if row["installed"]]
    missing = [row for row in servers if not row["installed"]]
    warnings = [
        f"missing {row['id']} ({row['language']}): {row['install_hint']}"
        for row in missing
    ]
    warnings.extend(str(item) for item in config_info.get("warnings", []))

    problems: list[str] = []
    if not servers:
        problems.append("no LSP servers are configured")
    elif not installed:
        problems.append("no configured LSP server is installed")

    report = {
        "result": "PASS" if not problems else "WARN",
        "installed": len(installed),
        "total": len(servers),
        "warnings": warnings,
        "problems": problems,
        "servers": servers,
        "config": config_info,
        "quick_fixes": [
            "/lsp status --json",
            "configure lsp.<server>.command and lsp.<server>.extensions in .opencode/my_opencode.json",
            "install at least one language server used by your repository",
        ],
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"installed: {report['installed']}/{report['total']}")
        for warning in warnings:
            print(f"- warning: {warning}")
        for problem in problems:
            print(f"- problem: {problem}")

    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]

    if command in ("help", "--help", "-h"):
        return usage()
    if command == "status":
        return command_status(rest)
    if command == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
