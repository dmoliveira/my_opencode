#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from config_layering import load_layered_config  # type: ignore
from safe_edit_adapters import validate_changed_references  # type: ignore


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
    print(
        "usage: /lsp status [--json] | /lsp doctor [--json] | "
        "/lsp goto-definition --symbol <name> --scope <glob[,glob...]> [--json] | "
        "/lsp find-references --symbol <name> --scope <glob[,glob...]> [--json] | "
        "/lsp symbols --view <document|workspace> [--file <path>] [--query <name>] [--scope <glob[,glob...]>] [--json] | "
        "/lsp prepare-rename --symbol <old> --new-name <new> --scope <glob[,glob...]> [--json] | "
        "/lsp rename --symbol <old> --new-name <new> --scope <glob[,glob...]> [--allow-text-fallback] [--apply] [--json]"
    )
    return 2


SUPPORTED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
}

IGNORED_DIRS = {".git", ".beads", "node_modules", "__pycache__", ".ruff_cache"}


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


def _split_scope(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _discover_files(root: Path, patterns: list[str]) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            resolved = path.resolve()
            seen[str(resolved)] = resolved
    return sorted(seen.values(), key=lambda item: str(item))


def _definition_patterns(symbol: str, suffix: str) -> list[re.Pattern[str]]:
    escaped = re.escape(symbol)
    if suffix == ".py":
        return [
            re.compile(rf"^\s*def\s+{escaped}\s*\("),
            re.compile(rf"^\s*class\s+{escaped}\b"),
        ]
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        return [
            re.compile(rf"^\s*function\s+{escaped}\s*\("),
            re.compile(rf"^\s*(export\s+)?(const|let|var)\s+{escaped}\b"),
            re.compile(rf"^\s*class\s+{escaped}\b"),
        ]
    if suffix == ".go":
        return [
            re.compile(rf"^\s*func\s+{escaped}\s*\("),
            re.compile(rf"^\s*type\s+{escaped}\b"),
        ]
    if suffix == ".rs":
        return [
            re.compile(rf"^\s*fn\s+{escaped}\s*\("),
            re.compile(rf"^\s*(pub\s+)?(struct|enum|trait|type)\s+{escaped}\b"),
        ]
    return [re.compile(rf"\b{escaped}\b")]


def _scan_definitions(
    symbol: str, files: list[Path], root: Path
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in files:
        patterns = _definition_patterns(symbol, path.suffix.lower())
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for idx, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in patterns):
                results.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": idx,
                        "text": line.strip(),
                    }
                )
    return results


def _scan_references(
    symbol: str, files: list[Path], root: Path
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for idx, line in enumerate(lines, start=1):
            if pattern.search(line):
                results.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": idx,
                        "text": line.strip(),
                    }
                )
    return results


def _symbol_patterns(suffix: str) -> list[re.Pattern[str]]:
    if suffix == ".py":
        return [
            re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
            re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
        ]
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        return [
            re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
            re.compile(
                r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
            ),
            re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
        ]
    if suffix == ".go":
        return [
            re.compile(r"^\s*func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
            re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
        ]
    if suffix == ".rs":
        return [
            re.compile(r"^\s*fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
            re.compile(
                r"^\s*(?:pub\s+)?(?:struct|enum|trait|type)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
            ),
        ]
    return []


def _extract_symbols(path: Path, root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    patterns = _symbol_patterns(path.suffix.lower())
    if not patterns:
        return results
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for idx, line in enumerate(lines, start=1):
        for pattern in patterns:
            matched = pattern.search(line)
            if matched:
                results.append(
                    {
                        "name": matched.group(1),
                        "path": str(path.relative_to(root)),
                        "line": idx,
                        "text": line.strip(),
                    }
                )
                break
    return results


def _parse_symbol_scope_args(args: list[str]) -> tuple[str, list[str], bool] | None:
    as_json = "--json" in args
    symbol = ""
    scope_patterns: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--symbol":
            if index + 1 >= len(args):
                return None
            symbol = args[index + 1].strip()
            index += 2
            continue
        if token == "--scope":
            if index + 1 >= len(args):
                return None
            scope_patterns = _split_scope(args[index + 1])
            index += 2
            continue
        return None

    if not symbol or not scope_patterns:
        return None
    return symbol, scope_patterns, as_json


def command_goto_definition(args: list[str]) -> int:
    parsed = _parse_symbol_scope_args(args)
    if parsed is None:
        return usage()
    symbol, scope_patterns, as_json = parsed

    root = Path.cwd()
    files = _discover_files(root, scope_patterns)
    definitions = _scan_definitions(symbol, files, root)
    report = {
        "result": "PASS" if definitions else "WARN",
        "backend": "text",
        "reason_code": "lsp_text_fallback_used",
        "symbol": symbol,
        "scope": scope_patterns,
        "scanned_files": len(files),
        "definitions": definitions,
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"symbol: {symbol}")
        print(f"definitions: {len(definitions)}")
        for row in definitions[:20]:
            print(f"- {row['path']}:{row['line']} {row['text']}")
    return 0


def command_find_references(args: list[str]) -> int:
    parsed = _parse_symbol_scope_args(args)
    if parsed is None:
        return usage()
    symbol, scope_patterns, as_json = parsed

    root = Path.cwd()
    files = _discover_files(root, scope_patterns)
    references = _scan_references(symbol, files, root)
    report = {
        "result": "PASS" if references else "WARN",
        "backend": "text",
        "reason_code": "lsp_text_fallback_used",
        "symbol": symbol,
        "scope": scope_patterns,
        "scanned_files": len(files),
        "references": references,
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"symbol: {symbol}")
        print(f"references: {len(references)}")
        for row in references[:40]:
            print(f"- {row['path']}:{row['line']} {row['text']}")
    return 0


def command_symbols(args: list[str]) -> int:
    as_json = "--json" in args
    view = ""
    file_value = ""
    query = ""
    scope_patterns: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            index += 1
            continue
        if token == "--view":
            if index + 1 >= len(args):
                return usage()
            view = args[index + 1].strip()
            index += 2
            continue
        if token == "--file":
            if index + 1 >= len(args):
                return usage()
            file_value = args[index + 1].strip()
            index += 2
            continue
        if token == "--query":
            if index + 1 >= len(args):
                return usage()
            query = args[index + 1].strip()
            index += 2
            continue
        if token == "--scope":
            if index + 1 >= len(args):
                return usage()
            scope_patterns = _split_scope(args[index + 1])
            index += 2
            continue
        return usage()

    root = Path.cwd()
    if view == "document":
        if not file_value:
            return usage()
        target = (root / file_value).resolve()
        if not target.exists() or not target.is_file():
            payload = {
                "result": "WARN",
                "reason_code": "lsp_symbols_file_not_found",
                "file": file_value,
                "symbols": [],
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"result: WARN\nfile: {file_value}")
            return 0

        symbols = _extract_symbols(target, root)
        report = {
            "result": "PASS" if symbols else "WARN",
            "backend": "text",
            "reason_code": "lsp_text_fallback_used",
            "view": "document",
            "file": file_value,
            "symbols": symbols,
        }
    elif view == "workspace":
        if not query or not scope_patterns:
            return usage()
        files = _discover_files(root, scope_patterns)
        symbols: list[dict[str, Any]] = []
        for path in files:
            symbols.extend(_extract_symbols(path, root))
        lowered = query.lower()
        filtered = [
            row for row in symbols if lowered in str(row.get("name", "")).lower()
        ]
        report = {
            "result": "PASS" if filtered else "WARN",
            "backend": "text",
            "reason_code": "lsp_text_fallback_used",
            "view": "workspace",
            "query": query,
            "scope": scope_patterns,
            "scanned_files": len(files),
            "symbols": filtered,
        }
    else:
        return usage()

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"symbols: {len(report.get('symbols', []))}")
        for row in report.get("symbols", [])[:30]:
            print(f"- {row['name']} {row['path']}:{row['line']}")
    return 0


def _parse_rename_args(
    args: list[str], *, allow_apply_flags: bool
) -> tuple[str, str, list[str], bool, bool, bool] | None:
    as_json = "--json" in args
    allow_text_fallback = "--allow-text-fallback" in args
    apply_changes = "--apply" in args
    symbol = ""
    new_name = ""
    scope_patterns: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--json", "--allow-text-fallback"}:
            index += 1
            continue
        if token == "--apply" and allow_apply_flags:
            index += 1
            continue
        if token == "--symbol":
            if index + 1 >= len(args):
                return None
            symbol = args[index + 1].strip()
            index += 2
            continue
        if token == "--new-name":
            if index + 1 >= len(args):
                return None
            new_name = args[index + 1].strip()
            index += 2
            continue
        if token == "--scope":
            if index + 1 >= len(args):
                return None
            scope_patterns = _split_scope(args[index + 1])
            index += 2
            continue
        return None

    if not symbol or not new_name or not scope_patterns:
        return None
    return symbol, new_name, scope_patterns, allow_text_fallback, apply_changes, as_json


def command_prepare_rename(args: list[str]) -> int:
    parsed = _parse_rename_args(args, allow_apply_flags=False)
    if parsed is None:
        return usage()
    symbol, new_name, scope_patterns, _, _, as_json = parsed

    root = Path.cwd()
    files = _discover_files(root, scope_patterns)
    definitions = _scan_definitions(symbol, files, root)
    references = _scan_references(symbol, files, root)

    issues: list[str] = []
    if not references:
        issues.append("symbol has no references in scope")
    if len(definitions) == 0:
        issues.append("symbol definition not found in scope")
    if len(definitions) > 1:
        issues.append("symbol definition is ambiguous in scope")
    if symbol == new_name:
        issues.append("new name must differ from current symbol")

    report = {
        "result": "PASS" if not issues else "WARN",
        "backend": "text",
        "reason_code": "lsp_text_fallback_used",
        "symbol": symbol,
        "new_name": new_name,
        "scope": scope_patterns,
        "scanned_files": len(files),
        "definitions": definitions,
        "references": len(references),
        "issues": issues,
        "can_rename": not issues,
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"can_rename: {report['can_rename']}")
        for issue in issues:
            print(f"- issue: {issue}")
    return 0


def command_rename(args: list[str]) -> int:
    parsed = _parse_rename_args(args, allow_apply_flags=True)
    if parsed is None:
        return usage()
    symbol, new_name, scope_patterns, allow_text_fallback, apply_changes, as_json = (
        parsed
    )

    root = Path.cwd()
    files = _discover_files(root, scope_patterns)
    references = _scan_references(symbol, files, root)
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    edit_plan: list[dict[str, Any]] = []

    for path in files:
        before = path.read_text(encoding="utf-8", errors="replace")
        replaced, count = pattern.subn(new_name, before)
        if count == 0:
            continue
        validation = validate_changed_references(before, replaced, symbol, new_name)
        edit_plan.append(
            {
                "path": str(path.relative_to(root)),
                "edits": count,
                "validation": validation,
                "before": before,
                "after": replaced,
            }
        )

    blockers: list[str] = []
    if not allow_text_fallback:
        blockers.append("text fallback requires --allow-text-fallback")
    if not references:
        blockers.append("symbol has no references in scope")
    if symbol == new_name:
        blockers.append("new name must differ from current symbol")
    for row in edit_plan:
        if row["validation"].get("result") != "PASS":
            blockers.append(f"validation failed for {row['path']}")

    applied_files: list[str] = []
    applied_edits = 0
    if apply_changes and not blockers:
        for row in edit_plan:
            path = root / str(row["path"])
            path.write_text(str(row["after"]), encoding="utf-8")
            applied_files.append(str(row["path"]))
            applied_edits += int(row["edits"])

    result = "PASS" if not blockers else "WARN"
    report = {
        "result": result,
        "backend": "text",
        "reason_code": "lsp_text_fallback_used",
        "symbol": symbol,
        "new_name": new_name,
        "scope": scope_patterns,
        "apply_requested": apply_changes,
        "applied": bool(apply_changes and not blockers),
        "planned_files": len(edit_plan),
        "planned_edits": sum(int(row["edits"]) for row in edit_plan),
        "applied_files": applied_files,
        "applied_edits": applied_edits,
        "blockers": sorted(set(blockers)),
        "validation": [
            {"path": row["path"], "validation": row["validation"]} for row in edit_plan
        ],
    }

    for row in edit_plan:
        row.pop("before", None)
        row.pop("after", None)

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"result: {report['result']}")
        print(f"applied: {report['applied']}")
        print(f"planned_files: {report['planned_files']}")
        print(f"planned_edits: {report['planned_edits']}")
        for blocker in report["blockers"]:
            print(f"- blocker: {blocker}")
    return 0


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
    if command == "goto-definition":
        return command_goto_definition(rest)
    if command == "find-references":
        return command_find_references(rest)
    if command == "symbols":
        return command_symbols(rest)
    if command == "prepare-rename":
        return command_prepare_rename(rest)
    if command == "rename":
        return command_rename(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
