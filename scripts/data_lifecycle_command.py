"""Local-data workflow planning, summaries and bounded snapshot inventory.

The offline preview and summary do not inspect sources, execute owner commands,
or write files. The separate inventory reads one explicitly selected source;
no subcommand implements source mutation or authorizes deletion.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

# Set before local imports, including when invoked through the slash wrapper.
sys.dont_write_bytecode = True

from session_sidecar_security import SidecarSecurityError, read_private_bytes

STORES = ("runtime_history", "session_sidecars", "shared_memory", "codememory")
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 50_000
MAX_NUMBER_CHARS = 128
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}\Z")
MAX_SIDECAR_FALLBACK_ID_CHARS = 8192
UUID4_HEX_PATTERN = re.compile(r"[0-9a-f]{32}\Z")


class LifecycleError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def reject(code: str = "data_lifecycle_schema_invalid") -> None:
    raise LifecycleError(code)


class PrivateParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's normal errors echo unknown arguments and private filenames.
        reject("data_lifecycle_arguments_invalid")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            reject("data_lifecycle_duplicate_key")
        value[key] = item
    return value


def _number(text: str) -> int | float:
    if len(text) > MAX_NUMBER_CHARS:
        reject("data_lifecycle_number_limit")
    if any(char in text for char in ".eE"):
        number = float(text)
        if not math.isfinite(number):
            reject("data_lifecycle_number_invalid")
        return number
    return int(text)


def _constant(_text: str) -> None:
    reject("data_lifecycle_number_invalid")


def _preflight(text: str) -> None:
    depth = tokens = number_chars = 0
    quoted = escaped = in_scalar = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char in " \t\r\n,:}]":
            in_scalar = False
            number_chars = 0
        if char in "[{":
            depth += 1
            tokens += 1
            if depth > MAX_DEPTH:
                reject("data_lifecycle_depth_limit")
        elif char in "}]":
            depth -= 1
        elif char == '"':
            quoted = True
            tokens += 1
        elif char not in " \t\r\n,:" and not in_scalar:
            in_scalar = True
            tokens += 1
        if in_scalar:
            number_chars += 1
            if number_chars > MAX_NUMBER_CHARS:
                reject("data_lifecycle_number_limit")
        if tokens > MAX_NODES:
            reject("data_lifecycle_node_limit")


def structure(value: Any) -> dict[str, Any]:
    """Keys count as string nodes, but neither keys nor topology are returned."""
    counts = dict.fromkeys(
        ("object", "array", "string", "number", "boolean", "null"), 0
    )
    stack = [(value, 0)]
    total = depth = 0
    while stack:
        item, level = stack.pop()
        total += 1
        depth = max(depth, level)
        if total > MAX_NODES or level > MAX_DEPTH:
            reject("data_lifecycle_structure_limit")
        if isinstance(item, dict):
            kind = "object"
            stack.extend((key, level + 1) for key in item)
            stack.extend((child, level + 1) for child in item.values())
        elif isinstance(item, list):
            kind = "array"
            stack.extend((child, level + 1) for child in item)
        elif isinstance(item, str):
            kind = "string"
            try:
                item.encode("utf-8")
            except UnicodeError:
                reject("data_lifecycle_unicode_invalid")
        elif item is None:
            kind = "null"
        elif type(item) is bool:
            kind = "boolean"
        else:
            kind = "number"
        counts[kind] += 1
    return {"node_count": total, "maximum_depth": depth, "type_counts": counts}


def parse_json(raw: bytes) -> Any:
    if len(raw) > MAX_INPUT_BYTES:
        reject("data_lifecycle_input_limit")
    try:
        text = raw.decode("utf-8")
        _preflight(text)
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_int=_number,
            parse_float=_number,
            parse_constant=_constant,
        )
        structure(value)
        return value
    except (UnicodeError, ValueError, RecursionError):
        reject("data_lifecycle_json_invalid")


def load_json(path: Path) -> Any:
    try:
        path = path.expanduser()
    except (RuntimeError, ValueError, UnicodeError):
        reject("data_lifecycle_input_unsafe_or_unavailable")
    try:
        loaded = read_private_bytes(path, max_bytes=MAX_INPUT_BYTES)
    except (ValueError, UnicodeError):
        reject("data_lifecycle_input_unsafe_or_unavailable")
    if loaded is None:
        reject("data_lifecycle_input_unavailable")
    return parse_json(loaded.data)


def exact(value: Any, keys: set[str]) -> dict:
    if not isinstance(value, dict) or value.keys() != keys:
        reject()
    return value


def text(value: Any, *, identifier: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("-")
        or value != value.strip()
        or len(value) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or (identifier and not ID_PATTERN.fullmatch(value))
    ):
        reject()
    return value


def sidecar_session_id(value: Any) -> str:
    """Recognize safe selector syntax without asserting provenance or existence."""
    if isinstance(value, str) and ID_PATTERN.fullmatch(value):
        return text(value, identifier=True)
    if (
        not isinstance(value, str)
        or len(value) > MAX_SIDECAR_FALLBACK_ID_CHARS
        or not value.startswith("/")
        or not value.isprintable()
    ):
        reject()
    parts = value.rsplit("::", 2)
    if len(parts) != 3:
        reject()
    cwd, timestamp, token = parts
    if not cwd.startswith("/") or not UUID4_HEX_PATTERN.fullmatch(token):
        reject()
    try:
        parsed = datetime.fromisoformat(timestamp)
        valid = (
            parsed.utcoffset() is not None
            and parsed.isoformat() == timestamp
            and UUID(hex=token).version == 4
        )
    except (ValueError, OverflowError):
        reject()
    if not valid:
        reject()
    return value


def command(purpose: str, argv: list[str]) -> dict:
    return {
        "purpose": purpose,
        "argv": argv,
        "executed": False,
        "owner_may_write_diagnostics_or_cache": True,
    }


def preview(value: Any) -> dict:
    value = exact(value, {"version", "store", "action", "selector"})
    if type(value["version"]) is not int or value["version"] != 1:
        reject()
    store, action = value["store"], value["action"]
    if store not in STORES or action not in ("removal", "redaction"):
        reject()
    selector = value["selector"]
    suggestions = []
    boundaries = []
    if store == "runtime_history":
        selector = exact(selector, {"session_id", "cli_family"})
        session = text(selector["session_id"], identifier=True)
        if selector["cli_family"] != "opencode-v2":
            reject("data_lifecycle_owner_version_unsupported")
        suggestions.append(
            command("inspect_cli_contract", ["opencode", "session", "export", "--help"])
        )
        suggestions.append(
            command(
                "export_selected_session", ["opencode", "session", "export", session]
            )
        )
        if action == "redaction":
            suggestions.append(
                command(
                    "export_sanitized_copy",
                    ["opencode", "session", "export", session, "--sanitize"],
                )
            )
        boundaries += [
            "Native session deletion cascades to children; this plan does not enumerate descendants.",
            "CLI family is caller asserted, not detected. Inspect installed help before use.",
            "Sanitized export does not redact the source database and is not a verified recovery backup.",
        ]
    elif store == "session_sidecars":
        selector = exact(selector, {"session_id"})
        session = sidecar_session_id(selector["session_id"])
        suggestions.append(
            command(
                "inspect_indexed_session",
                ["python3", "scripts/session_command.py", "show", session, "--json"],
            )
        )
        suggestions.append(
            command(
                "inspect_sidecar_health",
                ["python3", "scripts/session_command.py", "doctor", "--json"],
            )
        )
        boundaries += [
            "Index inspection does not inventory every digest, handoff, transcript or shared-memory reference.",
            "Owner show selects one match and does not establish that duplicate IDs are absent.",
            "Malformed sidecars must be preserved, not silently rebuilt or removed.",
        ]
    elif store == "shared_memory":
        selector = exact(selector, {"scope", "namespace", "older_days"})
        scope, namespace = text(selector["scope"]), text(selector["namespace"])
        if scope not in ("session", "repo", "shared"):
            reject()
        days = selector["older_days"]
        if type(days) is not int or not 1 <= days <= 36500:
            reject()
        suggestions.append(
            command(
                "inspect_owner",
                ["python3", "scripts/memory_lifecycle_command.py", "stats", "--json"],
            )
        )
        if action == "removal":
            suggestions.append(
                command(
                    "owner_archive_preview",
                    [
                        "python3",
                        "scripts/memory_lifecycle_command.py",
                        "cleanup",
                        "--scope",
                        scope,
                        "--namespace",
                        namespace,
                        "--older-days",
                        str(days),
                        "--dry-run",
                        "--json",
                    ],
                )
            )
        boundaries += [
            "Age is a moving predicate, not a revision-bound candidate inventory.",
            "Cleanup archives unpinned records; it neither erases content nor sanitizes exports/FTS/backups.",
        ]
    else:
        selector = exact(selector, {"scope", "artifact_kind", "record_id", "config"})
        text(selector["scope"])
        kind, record_id = (
            selector["artifact_kind"],
            text(selector["record_id"], identifier=True),
        )
        config = text(selector["config"])
        prefix = (
            {"memory": "memory_", "document": "doc_"}.get(kind)
            if isinstance(kind, str)
            else None
        )
        if prefix is None or not re.fullmatch(
            re.escape(prefix) + r"[1-9][0-9]*", record_id
        ):
            reject()
        if not config.startswith("/") or ".." in Path(config).parts:
            reject()
        base = ["oc", "--config", config]
        suggestions.append(
            command(
                "inspect_artifact_and_verify_scope",
                [*base, "get", record_id, "--view", "full", "--format", "json"],
            )
        )
        if action == "removal":
            suggestions.append(
                command(
                    "owner_archive_preview",
                    [
                        *base,
                        "archive",
                        record_id,
                        "--reason",
                        "explicit operator lifecycle review",
                        "--format",
                        "json",
                    ],
                )
            )
        boundaries += [
            "Scope is expected context; compare it with native full-record scope before any owner mutation.",
            "Archive is reversible and reference-checked; it is not physical deletion or erasure of operation history.",
        ]
    return {
        "schema_version": 1,
        "kind": "offline_workflow_plan",
        "result": "PASS",
        "status": "blocked",
        "source_inspected": False,
        "apply_supported": False,
        "store": store,
        "action": action,
        "selector": selector,
        "affected_count": None,
        "suggested_owner_steps": suggestions,
        "prerequisites": {
            "source_authorization": "not_checked",
            "owner_quiescence": "not_checked",
            "verified_private_recovery_backup": "not_checked",
            "exact_revision_bound_inventory": "capability_missing",
            "cross_store_retry_and_partial_failure_contract": "capability_missing",
        },
        "limitations": boundaries
        + [
            "This is a workflow preview, not an affected-data or deletion preview.",
            "No suggested command was executed. Plans are local-sensitive and are not authorization tokens.",
            "No destructive apply command or cross-store transaction is provided.",
        ],
    }


def summarize(value: Any, store: str) -> dict:
    if store not in STORES:
        reject()
    if not isinstance(value, (dict, list)):
        reject("data_lifecycle_export_container_required")
    return {
        "result": "PASS",
        "schema_version": 1,
        "kind": "counts_only_export_summary",
        "store_label": store,
        "store_provenance_verified": False,
        "source_modified": False,
        "restorable": False,
        "content_included": False,
        "structure": structure(value),
        "limitations": [
            "Structural counts remain metadata; review before sharing.",
            "Keys, scalar values, hashes and object topology are omitted, not redacted in the source.",
            "This is not a sanitized restorable export or proof of secret removal.",
        ],
    }


def main(argv: list[str]) -> int:
    if argv and argv[0] == "inventory-shared-memory":
        from shared_memory_inventory import main as inventory_main

        return inventory_main(argv[1:])
    try:
        parser = PrivateParser(description=__doc__, allow_abbrev=False)
        commands = parser.add_subparsers(
            dest="command", required=True, parser_class=PrivateParser
        )
        for name in ("preview", "summarize-export"):
            sub = commands.add_parser(name, allow_abbrev=False)
            sub.add_argument("--file", type=Path, required=True)
            if name == "summarize-export":
                sub.add_argument("--store", required=True)
        commands.add_parser(
            "inventory-shared-memory", help="read-only scoped candidate snapshot"
        )
        args = parser.parse_args(argv)
        value = load_json(args.file)
        report = (
            preview(value)
            if args.command == "preview"
            else summarize(value, args.store)
        )
        print(json.dumps(report, sort_keys=True, ensure_ascii=True))
        return 0
    except LifecycleError as exc:
        code = exc.code
    except (SidecarSecurityError, OSError):
        code = "data_lifecycle_input_unsafe_or_unavailable"
    print(json.dumps({"result": "FAIL", "reason_code": code}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
