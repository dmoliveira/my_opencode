#!/usr/bin/env python3

from __future__ import annotations

import difflib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from config_layering import load_layered_config  # type: ignore
from lsp_rpc_client import LspClient, choose_server_for_path, uri_to_path  # type: ignore
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
        "usage: /lsp status [--json] | /lsp doctor [--verbose] [--json] | "
        "/lsp goto-definition --symbol <name> --scope <glob[,glob...]> [--json] | "
        "/lsp find-references --symbol <name> --scope <glob[,glob...]> [--json] | "
        "/lsp symbols --view <document|workspace> [--file <path>] [--query <name>] [--scope <glob[,glob...]>] [--json] | "
        "/lsp prepare-rename --symbol <old> --new-name <new> --scope <glob[,glob...]> [--json] | "
        "/lsp rename --symbol <old> --new-name <new> --scope <glob[,glob...]> [--allow-text-fallback] [--allow-rename-file-ops] [--allow-create-file-ops] [--allow-delete-file-ops] [--max-diff-files <n>] [--max-diff-lines <n>] [--apply] [--json]"
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


def _resolve_symbol_anchor(
    symbol: str, files: list[Path], root: Path
) -> dict[str, Any] | None:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines, start=1):
            matched = pattern.search(line)
            if matched:
                return {
                    "path": path,
                    "line": index,
                    "character": matched.start(),
                    "path_relative": str(path.relative_to(root)),
                }
    return None


def _location_payload(item: dict[str, Any], root: Path) -> dict[str, Any] | None:
    uri = str(item.get("uri") or item.get("targetUri") or "").strip()
    if not uri:
        return None
    path = uri_to_path(uri)
    if path is None:
        return None
    range_payload = item.get("range") or item.get("targetRange")
    if not isinstance(range_payload, dict):
        return None
    start = range_payload.get("start")
    if not isinstance(start, dict):
        return None
    line0 = int(start.get("line", 0))
    char0 = int(start.get("character", 0))
    try:
        relative = str(path.resolve().relative_to(root))
    except Exception:
        relative = str(path)
    return {
        "path": relative,
        "line": line0 + 1,
        "character": char0,
    }


def _offset_for_position(text: str, line0: int, char0: int) -> int:
    if line0 < 0:
        return 0
    lines = text.splitlines(keepends=True)
    if line0 >= len(lines):
        return len(text)
    offset = sum(len(lines[index]) for index in range(line0))
    line_text = lines[line0]
    clamped_char = max(0, min(char0, len(line_text)))
    return offset + clamped_char


def _apply_text_edits(text: str, edits: list[dict[str, Any]]) -> str:
    normalized: list[dict[str, Any]] = []
    for edit in edits:
        range_payload = edit.get("range")
        if not isinstance(range_payload, dict):
            continue
        start = range_payload.get("start")
        end = range_payload.get("end")
        if not isinstance(start, dict) or not isinstance(end, dict):
            continue
        start_line = int(start.get("line", 0))
        start_char = int(start.get("character", 0))
        end_line = int(end.get("line", 0))
        end_char = int(end.get("character", 0))
        start_offset = _offset_for_position(text, start_line, start_char)
        end_offset = _offset_for_position(text, end_line, end_char)
        normalized.append(
            {
                "start": start_offset,
                "end": end_offset,
                "new_text": str(edit.get("newText", "")),
            }
        )
    normalized.sort(
        key=lambda item: (int(item["start"]), int(item["end"])), reverse=True
    )
    output = text
    for edit in normalized:
        start = int(edit["start"])
        end = int(edit["end"])
        output = output[:start] + str(edit["new_text"]) + output[end:]
    return output


def _workspace_edit_text_changes(
    workspace_edit: dict[str, Any],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    by_uri: dict[str, list[dict[str, Any]]] = {}
    resource_operations: list[dict[str, Any]] = []
    change_annotations: dict[str, dict[str, Any]] = {}

    annotations_payload = workspace_edit.get("changeAnnotations")
    if isinstance(annotations_payload, dict):
        for annotation_id, raw in annotations_payload.items():
            if not isinstance(raw, dict):
                continue
            change_annotations[str(annotation_id)] = {
                "label": str(raw.get("label") or "").strip(),
                "description": str(raw.get("description") or "").strip() or None,
                "needs_confirmation": bool(raw.get("needsConfirmation", False)),
            }

    changes = workspace_edit.get("changes")
    if isinstance(changes, dict):
        for uri, edits in changes.items():
            if not isinstance(edits, list):
                continue
            key = str(uri)
            bucket = by_uri.setdefault(key, [])
            bucket.extend(item for item in edits if isinstance(item, dict))

    document_changes = workspace_edit.get("documentChanges")
    if isinstance(document_changes, list):
        for item in document_changes:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            if kind in {
                "rename",
                "renamefile",
                "create",
                "createfile",
                "delete",
                "deletefile",
            }:
                resource_operations.append(
                    {
                        "kind": kind,
                        "uri": str(item.get("uri") or "").strip() or None,
                        "old_uri": str(item.get("oldUri") or "").strip() or None,
                        "new_uri": str(item.get("newUri") or "").strip() or None,
                    }
                )
                continue
            text_document = item.get("textDocument")
            edits = item.get("edits")
            if not isinstance(text_document, dict) or not isinstance(edits, list):
                continue
            uri = str(text_document.get("uri") or "").strip()
            if not uri:
                continue
            bucket = by_uri.setdefault(uri, [])
            bucket.extend(edit for edit in edits if isinstance(edit, dict))

    return by_uri, resource_operations, change_annotations


def _edit_plan_from_workspace_edit(
    workspace_edit: dict[str, Any],
    root: Path,
    symbol: str,
    new_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    plan: list[dict[str, Any]] = []
    by_uri, resource_operations, change_annotations = _workspace_edit_text_changes(
        workspace_edit
    )
    used_annotation_ids: set[str] = set()
    for uri, edits in by_uri.items():
        target_path = uri_to_path(str(uri))
        if target_path is None:
            continue
        before = target_path.read_text(encoding="utf-8", errors="replace")
        after = _apply_text_edits(before, edits)
        if before == after:
            continue
        validation = validate_changed_references(before, after, symbol, new_name)
        try:
            relative_path = str(target_path.resolve().relative_to(root))
        except Exception:
            relative_path = str(target_path)
        annotation_ids = [
            str(edit.get("annotationId"))
            for edit in edits
            if isinstance(edit, dict) and str(edit.get("annotationId") or "").strip()
        ]
        used_annotation_ids.update(annotation_ids)
        plan.append(
            {
                "path": relative_path,
                "edits": len(edits),
                "validation": validation,
                "annotation_ids": sorted(set(annotation_ids)),
                "before": before,
                "after": after,
            }
        )
    used_annotations: dict[str, dict[str, Any]] = {}
    for annotation_id in sorted(used_annotation_ids):
        if annotation_id in change_annotations:
            used_annotations[annotation_id] = change_annotations[annotation_id]
    return plan, resource_operations, used_annotations


def _backend_details(
    *,
    backend: str,
    reason_code: str,
    server: dict[str, Any] | None,
    attempted_protocol: bool,
    lsp_error: str,
) -> dict[str, Any]:
    return {
        "backend": backend,
        "reason_code": reason_code,
        "attempted_protocol": attempted_protocol,
        "server_id": str(server.get("id")) if isinstance(server, dict) else None,
        "server_command": list(server.get("command", []))
        if isinstance(server, dict)
        else [],
        "server_binary": str(server.get("binary"))
        if isinstance(server, dict)
        else None,
        "server_source": str(server.get("source"))
        if isinstance(server, dict)
        else None,
        "error": lsp_error or None,
    }


def _build_diff_preview(path: str, before: str, after: str) -> list[str]:
    return list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )


def _resource_kind(kind: str) -> str:
    lowered = kind.strip().lower()
    if lowered in {"rename", "renamefile"}:
        return "renamefile"
    if lowered in {"create", "createfile"}:
        return "createfile"
    if lowered in {"delete", "deletefile"}:
        return "deletefile"
    return lowered


def _split_resource_operations(
    resource_operations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rename_ops: list[dict[str, Any]] = []
    blocked_ops: list[dict[str, Any]] = []
    for operation in resource_operations:
        kind = _resource_kind(str(operation.get("kind") or ""))
        normalized = dict(operation)
        normalized["kind"] = kind
        if kind == "renamefile":
            if normalized.get("old_uri") and normalized.get("new_uri"):
                rename_ops.append(normalized)
            else:
                blocked_ops.append(normalized)
            continue
        if kind not in {"createfile", "deletefile"}:
            blocked_ops.append(normalized)
    return rename_ops, blocked_ops


def _group_resource_operations(
    resource_operations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "renamefile": [],
        "createfile": [],
        "deletefile": [],
        "other": [],
    }
    for operation in resource_operations:
        normalized = dict(operation)
        kind = _resource_kind(str(operation.get("kind") or ""))
        normalized["kind"] = kind
        if kind in {"renamefile", "createfile", "deletefile"}:
            grouped[kind].append(normalized)
        else:
            grouped["other"].append(normalized)
    return grouped


def _apply_renamefile_operations(
    root: Path,
    operations: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[str]]:
    applied: list[dict[str, str]] = []
    blockers: list[str] = []
    prepared: list[tuple[Path, Path]] = []
    root_resolved = root.resolve()
    for operation in operations:
        old_uri = str(operation.get("old_uri") or "")
        new_uri = str(operation.get("new_uri") or "")
        old_path = uri_to_path(old_uri)
        new_path = uri_to_path(new_uri)
        if old_path is None or new_path is None:
            blockers.append("renamefile operation has invalid file URI")
            continue
        old_resolved = old_path.resolve()
        new_resolved = new_path.resolve()
        try:
            old_resolved.relative_to(root_resolved)
            new_resolved.relative_to(root_resolved)
        except Exception:
            blockers.append("renamefile operation points outside repository root")
            continue
        if not old_resolved.exists():
            blockers.append(f"renamefile source missing: {old_resolved}")
            continue
        if new_resolved.exists() and old_resolved != new_resolved:
            blockers.append(f"renamefile target already exists: {new_resolved}")
            continue
        prepared.append((old_resolved, new_resolved))

    if blockers:
        return [], blockers

    for old_resolved, new_resolved in prepared:
        new_resolved.parent.mkdir(parents=True, exist_ok=True)
        old_resolved.rename(new_resolved)
        applied.append(
            {
                "from": str(old_resolved.relative_to(root_resolved)),
                "to": str(new_resolved.relative_to(root_resolved)),
            }
        )
    return applied, blockers


def _validate_renamefile_operations(
    root: Path,
    operations: list[dict[str, Any]],
) -> list[str]:
    validation_errors: list[str] = []
    seen_targets: set[str] = set()
    root_resolved = root.resolve()
    for operation in operations:
        old_uri = str(operation.get("old_uri") or "")
        new_uri = str(operation.get("new_uri") or "")
        old_path = uri_to_path(old_uri)
        new_path = uri_to_path(new_uri)
        if old_path is None or new_path is None:
            validation_errors.append("renamefile operation has invalid file URI")
            continue
        old_resolved = old_path.resolve()
        new_resolved = new_path.resolve()
        try:
            old_resolved.relative_to(root_resolved)
            new_resolved.relative_to(root_resolved)
        except Exception:
            validation_errors.append(
                "renamefile operation points outside repository root"
            )
            continue
        if not old_resolved.exists():
            validation_errors.append(f"renamefile source missing: {old_resolved}")
            continue
        if new_resolved.exists() and old_resolved != new_resolved:
            validation_errors.append(
                f"renamefile target already exists: {new_resolved}"
            )
            continue
        target_key = str(new_resolved)
        if target_key in seen_targets:
            validation_errors.append(
                f"renamefile target collides with another operation: {new_resolved}"
            )
            continue
        seen_targets.add(target_key)
    return validation_errors


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
    servers, _ = _collect_servers()
    anchor = _resolve_symbol_anchor(symbol, files, root)
    lsp_error = ""
    definitions: list[dict[str, Any]] = []
    backend = "text"
    reason_code = "lsp_text_fallback_used"
    attempted_protocol = False
    selected_server: dict[str, Any] | None = None

    if anchor is not None:
        server = choose_server_for_path(Path(anchor["path"]), servers)
        if server is not None:
            attempted_protocol = True
            selected_server = server
            try:
                with LspClient(command=list(server["command"]), root=root) as client:
                    capability_ok, capability_reason = _preflight_server_capability(
                        client.server_capabilities, "goto-definition"
                    )
                    if capability_ok:
                        raw_locations = client.goto_definition(
                            path=Path(anchor["path"]),
                            line0=int(anchor["line"]) - 1,
                            char0=int(anchor["character"]),
                        )
                    else:
                        raw_locations = []
                        reason_code = capability_reason
                parsed = [
                    location
                    for location in (
                        _location_payload(item, root)
                        for item in raw_locations
                        if isinstance(item, dict)
                    )
                    if location is not None
                ]
                if parsed:
                    definitions = parsed
                    backend = "lsp"
                    reason_code = "lsp_protocol_success"
            except Exception as exc:
                lsp_error = str(exc)

    if not definitions:
        definitions = _scan_definitions(symbol, files, root)

    report = {
        "result": "PASS" if definitions else "WARN",
        "backend": backend,
        "reason_code": reason_code,
        "symbol": symbol,
        "scope": scope_patterns,
        "scanned_files": len(files),
        "definitions": definitions,
        "lsp_error": lsp_error or None,
        "backend_details": _backend_details(
            backend=backend,
            reason_code=reason_code,
            server=selected_server,
            attempted_protocol=attempted_protocol,
            lsp_error=lsp_error,
        ),
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
    servers, _ = _collect_servers()
    anchor = _resolve_symbol_anchor(symbol, files, root)
    lsp_error = ""
    references: list[dict[str, Any]] = []
    backend = "text"
    reason_code = "lsp_text_fallback_used"
    attempted_protocol = False
    selected_server: dict[str, Any] | None = None

    if anchor is not None:
        server = choose_server_for_path(Path(anchor["path"]), servers)
        if server is not None:
            attempted_protocol = True
            selected_server = server
            try:
                with LspClient(command=list(server["command"]), root=root) as client:
                    capability_ok, capability_reason = _preflight_server_capability(
                        client.server_capabilities, "find-references"
                    )
                    if capability_ok:
                        raw_locations = client.find_references(
                            path=Path(anchor["path"]),
                            line0=int(anchor["line"]) - 1,
                            char0=int(anchor["character"]),
                        )
                    else:
                        raw_locations = []
                        reason_code = capability_reason
                parsed = [
                    location
                    for location in (
                        _location_payload(item, root)
                        for item in raw_locations
                        if isinstance(item, dict)
                    )
                    if location is not None
                ]
                if parsed:
                    references = parsed
                    backend = "lsp"
                    reason_code = "lsp_protocol_success"
            except Exception as exc:
                lsp_error = str(exc)

    if not references:
        references = _scan_references(symbol, files, root)

    report = {
        "result": "PASS" if references else "WARN",
        "backend": backend,
        "reason_code": reason_code,
        "symbol": symbol,
        "scope": scope_patterns,
        "scanned_files": len(files),
        "references": references,
        "lsp_error": lsp_error or None,
        "backend_details": _backend_details(
            backend=backend,
            reason_code=reason_code,
            server=selected_server,
            attempted_protocol=attempted_protocol,
            lsp_error=lsp_error,
        ),
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
    servers, _ = _collect_servers()
    if view == "document":
        if not file_value:
            return usage()
        target = (root / file_value).resolve()
        if not target.exists() or not target.is_file():
            payload = {
                "result": "WARN",
                "backend": "text",
                "reason_code": "lsp_symbols_file_not_found",
                "file": file_value,
                "symbols": [],
                "backend_details": _backend_details(
                    backend="text",
                    reason_code="lsp_symbols_file_not_found",
                    server=None,
                    attempted_protocol=False,
                    lsp_error="",
                ),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"result: WARN\nfile: {file_value}")
            return 0

        symbols = _extract_symbols(target, root)
        backend = "text"
        reason_code = "lsp_text_fallback_used"
        lsp_error = ""
        server = choose_server_for_path(target, servers)
        attempted_protocol = False
        selected_server: dict[str, Any] | None = None
        if server is not None:
            attempted_protocol = True
            selected_server = server
            try:
                with LspClient(command=list(server["command"]), root=root) as client:
                    capability_ok, capability_reason = _preflight_server_capability(
                        client.server_capabilities, "symbols-document"
                    )
                    raw_symbols = (
                        client.document_symbols(target) if capability_ok else []
                    )
                    if not capability_ok:
                        reason_code = capability_reason
                parsed: list[dict[str, Any]] = []
                for item in raw_symbols:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    location = item.get("location")
                    if isinstance(location, dict):
                        payload = _location_payload(location, root)
                        line_value = payload["line"] if payload else 1
                        path_value = (
                            payload["path"]
                            if payload
                            else str(target.relative_to(root))
                        )
                    else:
                        line_value = 1
                        path_value = str(target.relative_to(root))
                    parsed.append(
                        {
                            "name": name,
                            "path": path_value,
                            "line": line_value,
                            "text": "",
                        }
                    )
                if parsed:
                    symbols = parsed
                    backend = "lsp"
                    reason_code = "lsp_protocol_success"
            except Exception as exc:
                lsp_error = str(exc)

        report = {
            "result": "PASS" if symbols else "WARN",
            "backend": backend,
            "reason_code": reason_code,
            "view": "document",
            "file": file_value,
            "symbols": symbols,
            "lsp_error": lsp_error or None,
            "backend_details": _backend_details(
                backend=backend,
                reason_code=reason_code,
                server=selected_server,
                attempted_protocol=attempted_protocol,
                lsp_error=lsp_error,
            ),
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
        backend = "text"
        reason_code = "lsp_text_fallback_used"
        lsp_error = ""
        workspace_symbols = filtered
        anchor = files[0] if files else None
        attempted_protocol = False
        selected_server: dict[str, Any] | None = None
        if anchor is not None:
            server = choose_server_for_path(anchor, servers)
            if server is not None:
                attempted_protocol = True
                selected_server = server
                try:
                    with LspClient(
                        command=list(server["command"]), root=root
                    ) as client:
                        capability_ok, capability_reason = _preflight_server_capability(
                            client.server_capabilities, "symbols-workspace"
                        )
                        raw_symbols = (
                            client.workspace_symbols(query) if capability_ok else []
                        )
                        if not capability_ok:
                            reason_code = capability_reason
                    parsed: list[dict[str, Any]] = []
                    for item in raw_symbols:
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("name") or "").strip()
                        if not name:
                            continue
                        payload = _location_payload(item.get("location", {}), root)
                        if payload is None:
                            continue
                        parsed.append(
                            {
                                "name": name,
                                "path": payload["path"],
                                "line": payload["line"],
                                "text": "",
                            }
                        )
                    if parsed:
                        workspace_symbols = parsed
                        backend = "lsp"
                        reason_code = "lsp_protocol_success"
                except Exception as exc:
                    lsp_error = str(exc)

        report = {
            "result": "PASS" if workspace_symbols else "WARN",
            "backend": backend,
            "reason_code": reason_code,
            "view": "workspace",
            "query": query,
            "scope": scope_patterns,
            "scanned_files": len(files),
            "symbols": workspace_symbols,
            "lsp_error": lsp_error or None,
            "backend_details": _backend_details(
                backend=backend,
                reason_code=reason_code,
                server=selected_server,
                attempted_protocol=attempted_protocol,
                lsp_error=lsp_error,
            ),
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
) -> tuple[str, str, list[str], bool, bool, bool, bool, int, int, bool, bool] | None:
    as_json = "--json" in args
    allow_text_fallback = "--allow-text-fallback" in args
    allow_rename_file_ops = "--allow-rename-file-ops" in args
    allow_create_file_ops = "--allow-create-file-ops" in args
    allow_delete_file_ops = "--allow-delete-file-ops" in args
    max_diff_files = 25
    max_diff_lines = 1200
    apply_changes = "--apply" in args
    symbol = ""
    new_name = ""
    scope_patterns: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token in {
            "--json",
            "--allow-text-fallback",
            "--allow-rename-file-ops",
            "--allow-create-file-ops",
            "--allow-delete-file-ops",
        }:
            index += 1
            continue
        if token == "--max-diff-files":
            if index + 1 >= len(args):
                return None
            try:
                max_diff_files = max(0, int(args[index + 1]))
            except ValueError:
                return None
            index += 2
            continue
        if token == "--max-diff-lines":
            if index + 1 >= len(args):
                return None
            try:
                max_diff_lines = max(0, int(args[index + 1]))
            except ValueError:
                return None
            index += 2
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
    return (
        symbol,
        new_name,
        scope_patterns,
        allow_text_fallback,
        allow_rename_file_ops,
        allow_create_file_ops,
        allow_delete_file_ops,
        max_diff_files,
        max_diff_lines,
        apply_changes,
        as_json,
    )


def command_prepare_rename(args: list[str]) -> int:
    parsed = _parse_rename_args(args, allow_apply_flags=False)
    if parsed is None:
        return usage()
    symbol, new_name, scope_patterns, _, _, _, _, _, _, _, as_json = parsed

    root = Path.cwd()
    files = _discover_files(root, scope_patterns)
    definitions = _scan_definitions(symbol, files, root)
    references = _scan_references(symbol, files, root)
    servers, _ = _collect_servers()
    backend = "text"
    reason_code = "lsp_text_fallback_used"
    lsp_error = ""
    attempted_protocol = False
    selected_server: dict[str, Any] | None = None

    anchor = _resolve_symbol_anchor(symbol, files, root)
    if anchor is not None:
        server = choose_server_for_path(Path(anchor["path"]), servers)
        if server is not None:
            attempted_protocol = True
            selected_server = server
            try:
                with LspClient(command=list(server["command"]), root=root) as client:
                    capability_ok, capability_reason = _preflight_server_capability(
                        client.server_capabilities, "prepare-rename"
                    )
                    if capability_ok:
                        prepare_payload = client.prepare_rename(
                            path=Path(anchor["path"]),
                            line0=int(anchor["line"]) - 1,
                            char0=int(anchor["character"]),
                        )
                    else:
                        prepare_payload = None
                        reason_code = capability_reason
                if prepare_payload is not None:
                    backend = "lsp"
                    reason_code = "lsp_protocol_success"
            except Exception as exc:
                lsp_error = str(exc)

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
        "backend": backend,
        "reason_code": reason_code,
        "symbol": symbol,
        "new_name": new_name,
        "scope": scope_patterns,
        "scanned_files": len(files),
        "definitions": definitions,
        "references": len(references),
        "issues": issues,
        "can_rename": not issues,
        "lsp_error": lsp_error or None,
        "backend_details": _backend_details(
            backend=backend,
            reason_code=reason_code,
            server=selected_server,
            attempted_protocol=attempted_protocol,
            lsp_error=lsp_error,
        ),
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
    (
        symbol,
        new_name,
        scope_patterns,
        allow_text_fallback,
        allow_rename_file_ops,
        allow_create_file_ops,
        allow_delete_file_ops,
        max_diff_files,
        max_diff_lines,
        apply_changes,
        as_json,
    ) = parsed

    root = Path.cwd()
    files = _discover_files(root, scope_patterns)
    references = _scan_references(symbol, files, root)
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    servers, _ = _collect_servers()
    backend = "text"
    reason_code = "lsp_text_fallback_used"
    lsp_error = ""
    edit_plan: list[dict[str, Any]] = []
    resource_operations: list[dict[str, Any]] = []
    change_annotations: dict[str, dict[str, Any]] = {}
    attempted_protocol = False
    selected_server: dict[str, Any] | None = None

    anchor = _resolve_symbol_anchor(symbol, files, root)
    if anchor is not None:
        server = choose_server_for_path(Path(anchor["path"]), servers)
        if server is not None:
            attempted_protocol = True
            selected_server = server
            try:
                with LspClient(command=list(server["command"]), root=root) as client:
                    capability_ok, capability_reason = _preflight_server_capability(
                        client.server_capabilities, "rename"
                    )
                    if capability_ok:
                        workspace_edit = client.rename(
                            path=Path(anchor["path"]),
                            line0=int(anchor["line"]) - 1,
                            char0=int(anchor["character"]),
                            new_name=new_name,
                        )
                    else:
                        workspace_edit = None
                        reason_code = capability_reason
                if isinstance(workspace_edit, dict):
                    edit_plan, resource_operations, change_annotations = (
                        _edit_plan_from_workspace_edit(
                            workspace_edit=workspace_edit,
                            root=root,
                            symbol=symbol,
                            new_name=new_name,
                        )
                    )
                    if edit_plan:
                        backend = "lsp"
                        reason_code = "lsp_protocol_success"
            except Exception as exc:
                lsp_error = str(exc)

    if not edit_plan:
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

    renamefile_operations, blocked_resource_ops = _split_resource_operations(
        resource_operations
    )
    grouped_resource_ops = _group_resource_operations(resource_operations)
    diff_preview = [
        {
            "path": str(row["path"]),
            "diff": _build_diff_preview(
                path=str(row["path"]),
                before=str(row.get("before", "")),
                after=str(row.get("after", "")),
            ),
        }
        for row in edit_plan
    ]
    diff_file_count = len(diff_preview)
    diff_line_count = sum(len(item.get("diff", [])) for item in diff_preview)

    blockers: list[str] = []
    if backend == "text" and not allow_text_fallback:
        blockers.append("text fallback requires --allow-text-fallback")
    if not references:
        blockers.append("symbol has no references in scope")
    if symbol == new_name:
        blockers.append("new name must differ from current symbol")
    if blocked_resource_ops:
        blockers.append("workspace edit includes unsupported resource operations")
    if renamefile_operations and not allow_rename_file_ops:
        blockers.append("renamefile operations require --allow-rename-file-ops")
    if grouped_resource_ops["createfile"] and not allow_create_file_ops:
        blockers.append("createfile operations require --allow-create-file-ops")
    if grouped_resource_ops["deletefile"] and not allow_delete_file_ops:
        blockers.append("deletefile operations require --allow-delete-file-ops")
    if apply_changes and grouped_resource_ops["createfile"]:
        blockers.append("createfile operations are not supported for apply")
    if apply_changes and grouped_resource_ops["deletefile"]:
        blockers.append("deletefile operations are not supported for apply")
    if any(
        bool(annotation.get("needs_confirmation", False))
        for annotation in change_annotations.values()
    ):
        blockers.append("change annotations require confirmation; apply is blocked")
    if renamefile_operations:
        blockers.extend(_validate_renamefile_operations(root, renamefile_operations))
    if apply_changes and diff_file_count > max_diff_files:
        blockers.append(
            f"diff review threshold exceeded: files {diff_file_count}>{max_diff_files}"
        )
    if apply_changes and diff_line_count > max_diff_lines:
        blockers.append(
            f"diff review threshold exceeded: lines {diff_line_count}>{max_diff_lines}"
        )
    for row in edit_plan:
        if row["validation"].get("result") != "PASS":
            blockers.append(f"validation failed for {row['path']}")

    applied_files: list[str] = []
    applied_edits = 0
    applied_resource_operations: list[dict[str, str]] = []
    if apply_changes and not blockers:
        for row in edit_plan:
            path = root / str(row["path"])
            path.write_text(str(row["after"]), encoding="utf-8")
            applied_files.append(str(row["path"]))
            applied_edits += int(row["edits"])
        applied_resource_operations, _ = _apply_renamefile_operations(
            root=root,
            operations=renamefile_operations,
        )

    result = "PASS" if not blockers else "WARN"
    report = {
        "result": result,
        "backend": backend,
        "reason_code": reason_code,
        "symbol": symbol,
        "new_name": new_name,
        "scope": scope_patterns,
        "allow_rename_file_ops": allow_rename_file_ops,
        "allow_create_file_ops": allow_create_file_ops,
        "allow_delete_file_ops": allow_delete_file_ops,
        "max_diff_files": max_diff_files,
        "max_diff_lines": max_diff_lines,
        "diff_file_count": diff_file_count,
        "diff_line_count": diff_line_count,
        "apply_requested": apply_changes,
        "applied": bool(apply_changes and not blockers),
        "planned_files": len(edit_plan),
        "planned_edits": sum(int(row["edits"]) for row in edit_plan),
        "applied_files": applied_files,
        "applied_edits": applied_edits,
        "applied_resource_operations": applied_resource_operations,
        "blockers": sorted(set(blockers)),
        "validation": [
            {"path": row["path"], "validation": row["validation"]} for row in edit_plan
        ],
        "diff_preview": diff_preview,
        "change_annotations": change_annotations,
        "renamefile_operations": renamefile_operations,
        "createfile_operations": grouped_resource_ops["createfile"],
        "deletefile_operations": grouped_resource_ops["deletefile"],
        "resource_operation_summary": {
            "total": len(resource_operations),
            "renamefile": len(grouped_resource_ops["renamefile"]),
            "createfile": len(grouped_resource_ops["createfile"]),
            "deletefile": len(grouped_resource_ops["deletefile"]),
            "other": len(grouped_resource_ops["other"]),
        },
        "blocked_resource_operations": blocked_resource_ops,
        "resource_operations": resource_operations,
        "lsp_error": lsp_error or None,
        "backend_details": _backend_details(
            backend=backend,
            reason_code=reason_code,
            server=selected_server,
            attempted_protocol=attempted_protocol,
            lsp_error=lsp_error,
        ),
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


CAPABILITY_MATRIX: list[tuple[str, str]] = [
    ("definitionProvider", "goto-definition"),
    ("referencesProvider", "find-references"),
    ("documentSymbolProvider", "symbols(document)"),
    ("workspaceSymbolProvider", "symbols(workspace)"),
    ("renameProvider", "rename"),
    ("prepareRenameProvider", "prepare-rename"),
]

COMMAND_CAPABILITY_REQUIREMENTS: dict[str, str] = {
    "goto-definition": "definitionProvider",
    "find-references": "referencesProvider",
    "symbols-document": "documentSymbolProvider",
    "symbols-workspace": "workspaceSymbolProvider",
    "prepare-rename": "prepareRenameProvider",
    "rename": "renameProvider",
}


def _truthy_capability(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (dict, list, str)):
        return True
    return False


def _extract_prepare_rename_provider(capabilities: dict[str, Any]) -> Any:
    explicit = capabilities.get("prepareRenameProvider")
    if explicit is not None:
        return explicit
    rename_provider = capabilities.get("renameProvider")
    if isinstance(rename_provider, dict):
        return rename_provider.get("prepareProvider")
    return None


def _required_capability_value(capabilities: dict[str, Any], key: str) -> Any:
    if key == "prepareRenameProvider":
        return _extract_prepare_rename_provider(capabilities)
    return capabilities.get(key)


def _capability_reason_code(key: str) -> str:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    slug = re.sub(r"[^a-z0-9]+", "_", snake.lower()).strip("_")
    return f"lsp_capability_missing_{slug}"


def _preflight_server_capability(
    capabilities: dict[str, Any], command: str
) -> tuple[bool, str]:
    required = COMMAND_CAPABILITY_REQUIREMENTS.get(command)
    if not required:
        return True, ""
    value = _required_capability_value(capabilities, required)
    if _truthy_capability(value):
        return True, ""
    return False, _capability_reason_code(required)


def _capability_matrix(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for key, label in CAPABILITY_MATRIX:
        raw_value: Any = capabilities.get(key)
        if key == "prepareRenameProvider":
            raw_value = _extract_prepare_rename_provider(capabilities)
        supported = _truthy_capability(raw_value)
        matrix.append(
            {
                "capability": key,
                "label": label,
                "supported": supported,
                "raw": raw_value,
            }
        )
    return matrix


def _probe_server_capabilities(root: Path, server: dict[str, Any]) -> dict[str, Any]:
    if not bool(server.get("installed")):
        return {
            "server_id": server["id"],
            "status": "missing_binary",
            "installed": False,
            "matrix": [],
            "supported": 0,
            "total": len(CAPABILITY_MATRIX),
            "error": None,
            "capabilities": {},
        }
    try:
        with LspClient(command=list(server["command"]), root=root) as client:
            capabilities = dict(client.server_capabilities)
        matrix = _capability_matrix(capabilities)
        supported = sum(1 for row in matrix if row["supported"])
        return {
            "server_id": server["id"],
            "status": "ok",
            "installed": True,
            "matrix": matrix,
            "supported": supported,
            "total": len(matrix),
            "error": None,
            "capabilities": capabilities,
        }
    except Exception as exc:
        return {
            "server_id": server["id"],
            "status": "probe_failed",
            "installed": True,
            "matrix": [],
            "supported": 0,
            "total": len(CAPABILITY_MATRIX),
            "error": str(exc),
            "capabilities": {},
        }


def _doctor_capability_probe(
    root: Path, servers: list[dict[str, Any]]
) -> dict[str, Any]:
    server_probes = [
        _probe_server_capabilities(root=root, server=row) for row in servers
    ]
    summary: list[dict[str, Any]] = []
    for key, label in CAPABILITY_MATRIX:
        supported = 0
        total = 0
        for probe in server_probes:
            if probe["status"] != "ok":
                continue
            total += 1
            for item in probe["matrix"]:
                if item["capability"] == key and item["supported"]:
                    supported += 1
                    break
        summary.append(
            {
                "capability": key,
                "label": label,
                "supported_servers": supported,
                "probed_servers": total,
            }
        )
    return {
        "enabled": True,
        "servers": server_probes,
        "summary": summary,
    }


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
        "backend_details": _backend_details(
            backend="diagnostic",
            reason_code="status_inventory",
            server=None,
            attempted_protocol=False,
            lsp_error="",
        ),
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
    if any(arg not in ("--json", "--verbose") for arg in args):
        return usage()
    as_json = "--json" in args
    verbose = "--verbose" in args

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

    capability_probing: dict[str, Any] = {
        "enabled": False,
        "servers": [],
        "summary": [],
    }
    if verbose:
        capability_probing = _doctor_capability_probe(root=Path.cwd(), servers=servers)
        for probe in capability_probing["servers"]:
            if probe["status"] == "probe_failed" and probe["error"]:
                warnings.append(
                    f"capability probe failed for {probe['server_id']}: {probe['error']}"
                )

    report = {
        "result": "PASS" if not problems else "WARN",
        "installed": len(installed),
        "total": len(servers),
        "warnings": warnings,
        "problems": problems,
        "servers": servers,
        "capability_probing": capability_probing,
        "config": config_info,
        "backend_details": _backend_details(
            backend="diagnostic",
            reason_code="doctor_inventory",
            server=None,
            attempted_protocol=False,
            lsp_error="",
        ),
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
        if verbose:
            print("capability probing:")
            for probe in capability_probing["servers"]:
                if probe["status"] == "ok":
                    states = ", ".join(
                        f"{item['label']}={'yes' if item['supported'] else 'no'}"
                        for item in probe["matrix"]
                    )
                    print(
                        f"- {probe['server_id']}: status=ok supported={probe['supported']}/{probe['total']} {states}"
                    )
                elif probe["status"] == "missing_binary":
                    print(
                        f"- {probe['server_id']}: status=missing_binary supported=0/{probe['total']}"
                    )
                else:
                    print(
                        f"- {probe['server_id']}: status=probe_failed error={probe['error']}"
                    )
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
