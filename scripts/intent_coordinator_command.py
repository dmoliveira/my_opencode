#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atomic_json_state import (  # type: ignore
    atomic_write_json,
    json_state_write_lock,
)
from bounded_subprocess import (  # type: ignore
    BoundedCommandError,
    run_bounded,
)

FORMAT_VERSION = 1
MAX_CHANGES = 10
MAX_PROPOSAL_BYTES = 256 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
TITLE_LOOKUP_LIMIT = 100
_configured_state_dir = os.environ.get(
    "MY_OPENCODE_INTENT_COORDINATOR_STATE_DIR", ""
).strip()
DEFAULT_STATE_DIR = Path(
    _configured_state_dir or "~/.config/opencode/my_opencode/runtime/intent-coordinator"
).expanduser()
DEFAULT_OC_BIN = os.environ.get("MY_OPENCODE_CODEMEMORY_BIN", "").strip() or "oc"
_configured_oc_config = os.environ.get("MY_OPENCODE_CODEMEMORY_CONFIG", "").strip()
DEFAULT_OC_CONFIG = (
    Path(_configured_oc_config).expanduser() if _configured_oc_config else None
)
DEFAULT_ACTOR = (
    os.environ.get("MY_OPENCODE_INTENT_COORDINATOR_ACTOR", "").strip()
    or "intent-coordinator"
)

ENTITY_TYPES = ("task", "epic", "memory", "doc")
ALLOWED_EDGES = ("parent-of", "depends-on", "about", "doc-for")
ALLOWED_EDGE_SHAPES = {
    "parent-of": frozenset({("task", "task"), ("epic", "task")}),
    "depends-on": frozenset({("task", "task")}),
    "doc-for": frozenset({("doc", "task"), ("doc", "epic"), ("doc", "memory")}),
    "about": frozenset({("memory", "task"), ("memory", "epic"), ("memory", "doc")}),
}
SOURCE_KINDS = ("user", "agent", "system")
PRIORITIES = ("P0", "P1", "P2", "P3")
PROPOSAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9._:-]{0,111}$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

TOP_LEVEL_KEYS = {"version", "proposal_id", "scope", "source", "records", "links"}
SOURCE_KEYS = {"kind", "id", "summary", "content_sha256", "session_id"}
COMMON_RECORD_KEYS = {"key", "entity_type", "title", "summary", "labels"}
TASK_EPIC_KEYS = COMMON_RECORD_KEYS | {"kind", "priority", "goal"}
MEMORY_KEYS = COMMON_RECORD_KEYS | {"kind", "body"}
DOC_KEYS = COMMON_RECORD_KEYS | {"doc_type", "ref"}
LINK_KEYS = {"from", "edge", "to"}

Runner = Callable[[list[str], str], dict[str, Any]]


class CoordinatorError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        detail: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail
        self.context = context or {}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoordinatorError("intent_schema_invalid", f"{name} must be an object")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise CoordinatorError("intent_schema_invalid", f"{name} must be an array")
    return value


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CoordinatorError(
            "intent_schema_unknown_field",
            f"{name} contains unknown fields: {', '.join(unknown)}",
        )


def _require_text(
    value: Any,
    name: str,
    *,
    max_chars: int,
    max_words: int | None = None,
) -> str:
    if not isinstance(value, str):
        raise CoordinatorError("intent_schema_invalid", f"{name} must be a string")
    normalized = _normalize_text(value)
    if not normalized:
        raise CoordinatorError("intent_schema_invalid", f"{name} must not be empty")
    if len(normalized) > max_chars:
        raise CoordinatorError(
            "intent_schema_limit_exceeded",
            f"{name} exceeds {max_chars} characters",
        )
    if max_words is not None and len(normalized.split()) > max_words:
        raise CoordinatorError(
            "intent_schema_limit_exceeded",
            f"{name} exceeds {max_words} words",
        )
    return normalized


def _optional_text(
    value: dict[str, Any],
    key: str,
    name: str,
    *,
    max_chars: int,
    max_words: int | None = None,
) -> str | None:
    if key not in value or value[key] is None:
        return None
    return _require_text(value[key], name, max_chars=max_chars, max_words=max_words)


def _normalize_labels(value: Any, name: str) -> list[str]:
    labels = _require_list(value, name)
    if len(labels) > 10:
        raise CoordinatorError(
            "intent_schema_limit_exceeded", f"{name} exceeds 10 labels"
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for index, label in enumerate(labels):
        item = _require_text(label, f"{name}[{index}]", max_chars=64)
        if not TOKEN_PATTERN.fullmatch(item):
            raise CoordinatorError(
                "intent_schema_invalid", f"{name}[{index}] has invalid characters"
            )
        if item not in seen:
            seen.add(item)
            normalized.append(item)
    return normalized


def _normalize_source(value: Any) -> dict[str, Any]:
    source = _require_object(value, "source")
    _reject_unknown_keys(source, SOURCE_KEYS, "source")
    kind = _require_text(source.get("kind"), "source.kind", max_chars=16)
    if kind not in SOURCE_KINDS:
        raise CoordinatorError(
            "intent_schema_invalid",
            f"source.kind must be one of: {', '.join(SOURCE_KINDS)}",
        )
    normalized: dict[str, Any] = {
        "kind": kind,
        "id": _require_text(source.get("id"), "source.id", max_chars=256),
        "summary": _require_text(
            source.get("summary"), "source.summary", max_chars=1000
        ),
    }
    digest = _optional_text(
        source,
        "content_sha256",
        "source.content_sha256",
        max_chars=64,
    )
    if digest is not None:
        if not SHA256_PATTERN.fullmatch(digest):
            raise CoordinatorError(
                "intent_schema_invalid",
                "source.content_sha256 must be lowercase SHA-256",
            )
        normalized["content_sha256"] = digest
    session_id = _optional_text(
        source, "session_id", "source.session_id", max_chars=256
    )
    if session_id is not None:
        normalized["session_id"] = session_id
    return normalized


def _normalize_record(value: Any, index: int) -> dict[str, Any]:
    record = _require_object(value, f"records[{index}]")
    entity_type = _require_text(
        record.get("entity_type"), f"records[{index}].entity_type", max_chars=16
    )
    if entity_type not in ENTITY_TYPES:
        raise CoordinatorError(
            "intent_schema_invalid",
            f"records[{index}].entity_type must be one of: {', '.join(ENTITY_TYPES)}",
        )
    allowed = {
        "task": TASK_EPIC_KEYS,
        "epic": TASK_EPIC_KEYS,
        "memory": MEMORY_KEYS,
        "doc": DOC_KEYS,
    }[entity_type]
    _reject_unknown_keys(record, allowed, f"records[{index}]")
    key = _require_text(record.get("key"), f"records[{index}].key", max_chars=128)
    if not KEY_PATTERN.fullmatch(key):
        raise CoordinatorError(
            "intent_schema_invalid", f"records[{index}].key has invalid format"
        )
    normalized: dict[str, Any] = {
        "key": key,
        "entity_type": entity_type,
        "title": _require_text(
            record.get("title"),
            f"records[{index}].title",
            max_chars=200,
            max_words=8,
        ),
    }
    summary = _optional_text(
        record,
        "summary",
        f"records[{index}].summary",
        max_chars=500,
        max_words=20,
    )
    if summary is not None:
        normalized["summary"] = summary
    if "labels" in record:
        normalized["labels"] = _normalize_labels(
            record["labels"], f"records[{index}].labels"
        )
    if entity_type in {"task", "epic"}:
        kind = _optional_text(record, "kind", f"records[{index}].kind", max_chars=64)
        if kind is not None:
            if not TOKEN_PATTERN.fullmatch(kind):
                raise CoordinatorError(
                    "intent_schema_invalid",
                    f"records[{index}].kind has invalid characters",
                )
            normalized["kind"] = kind
        priority = _optional_text(
            record, "priority", f"records[{index}].priority", max_chars=2
        )
        if priority is not None:
            if priority not in PRIORITIES:
                raise CoordinatorError(
                    "intent_schema_invalid",
                    f"records[{index}].priority must be one of: {', '.join(PRIORITIES)}",
                )
            normalized["priority"] = priority
        goal = _optional_text(
            record,
            "goal",
            f"records[{index}].goal",
            max_chars=500,
            max_words=16,
        )
        if goal is not None:
            normalized["goal"] = goal
    elif entity_type == "memory":
        kind = _require_text(record.get("kind"), f"records[{index}].kind", max_chars=64)
        if not TOKEN_PATTERN.fullmatch(kind):
            raise CoordinatorError(
                "intent_schema_invalid",
                f"records[{index}].kind has invalid characters",
            )
        normalized["kind"] = kind
        normalized["body"] = _require_text(
            record.get("body"), f"records[{index}].body", max_chars=4000
        )
    else:
        doc_type = _require_text(
            record.get("doc_type"), f"records[{index}].doc_type", max_chars=64
        )
        if not TOKEN_PATTERN.fullmatch(doc_type):
            raise CoordinatorError(
                "intent_schema_invalid",
                f"records[{index}].doc_type has invalid characters",
            )
        normalized["doc_type"] = doc_type
        normalized["ref"] = _require_text(
            record.get("ref"), f"records[{index}].ref", max_chars=1024
        )
    return normalized


def _normalize_link(
    value: Any,
    index: int,
    record_types: dict[str, str],
) -> dict[str, str]:
    link = _require_object(value, f"links[{index}]")
    _reject_unknown_keys(link, LINK_KEYS, f"links[{index}]")
    source = _require_text(link.get("from"), f"links[{index}].from", max_chars=128)
    target = _require_text(link.get("to"), f"links[{index}].to", max_chars=128)
    edge = _require_text(link.get("edge"), f"links[{index}].edge", max_chars=32)
    if source not in record_types or target not in record_types:
        raise CoordinatorError(
            "intent_schema_unknown_reference",
            f"links[{index}] must reference proposal record keys",
        )
    if source == target:
        raise CoordinatorError(
            "intent_schema_invalid", f"links[{index}] must not be a self-link"
        )
    if edge not in ALLOWED_EDGES:
        raise CoordinatorError(
            "intent_schema_unsupported_edge",
            f"links[{index}].edge must be one of: {', '.join(ALLOWED_EDGES)}",
        )
    shape = (record_types[source], record_types[target])
    if shape not in ALLOWED_EDGE_SHAPES[edge]:
        raise CoordinatorError(
            "intent_schema_invalid_edge_shape",
            (f"links[{index}] {edge} does not support {shape[0]} -> {shape[1]}"),
        )
    return {"from": source, "edge": edge, "to": target}


def normalize_proposal(value: Any) -> dict[str, Any]:
    proposal = _require_object(value, "proposal")
    _reject_unknown_keys(proposal, TOP_LEVEL_KEYS, "proposal")
    if (
        type(proposal.get("version")) is not int
        or proposal["version"] != FORMAT_VERSION
    ):
        raise CoordinatorError(
            "intent_schema_version_unsupported",
            f"version must be {FORMAT_VERSION}",
        )
    proposal_id = _require_text(
        proposal.get("proposal_id"), "proposal_id", max_chars=128
    )
    if not PROPOSAL_ID_PATTERN.fullmatch(proposal_id):
        raise CoordinatorError(
            "intent_schema_invalid", "proposal_id has invalid format"
        )
    records_raw = _require_list(proposal.get("records"), "records")
    links_raw = _require_list(proposal.get("links"), "links")
    if not records_raw:
        raise CoordinatorError(
            "intent_schema_invalid", "records must contain at least one item"
        )
    if len(records_raw) + len(links_raw) > MAX_CHANGES:
        raise CoordinatorError(
            "intent_schema_limit_exceeded",
            f"combined records and links exceed {MAX_CHANGES}",
        )
    records = [_normalize_record(item, index) for index, item in enumerate(records_raw)]
    keys = [str(item["key"]) for item in records]
    if len(keys) != len(set(keys)):
        raise CoordinatorError(
            "intent_schema_duplicate_key", "record keys must be unique"
        )
    titles = [(str(item["entity_type"]), str(item["title"])) for item in records]
    if len(titles) != len(set(titles)):
        raise CoordinatorError(
            "intent_schema_duplicate_title",
            "record entity-type and title pairs must be unique",
        )
    record_types = {
        str(record["key"]): str(record["entity_type"]) for record in records
    }
    links = [
        _normalize_link(item, index, record_types)
        for index, item in enumerate(links_raw)
    ]
    link_keys = [(item["from"], item["edge"], item["to"]) for item in links]
    if len(link_keys) != len(set(link_keys)):
        raise CoordinatorError("intent_schema_duplicate_link", "links must be unique")
    return {
        "version": FORMAT_VERSION,
        "proposal_id": proposal_id,
        "scope": _require_text(proposal.get("scope"), "scope", max_chars=200),
        "source": _normalize_source(proposal.get("source")),
        "records": records,
        "links": links,
    }


def load_proposal(path: Path) -> dict[str, Any]:
    descriptor = -1
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CoordinatorError(
                "intent_proposal_unsafe", "proposal must be a regular file"
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            contents = handle.read(MAX_PROPOSAL_BYTES + 1)
    except CoordinatorError:
        raise
    except OSError as exc:
        raise CoordinatorError("intent_proposal_unreadable", str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(contents) > MAX_PROPOSAL_BYTES:
        raise CoordinatorError(
            "intent_schema_limit_exceeded",
            f"proposal exceeds {MAX_PROPOSAL_BYTES} bytes",
        )
    try:
        raw = json.loads(contents.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CoordinatorError("intent_proposal_invalid_json", str(exc)) from exc
    return normalize_proposal(raw)


def canonical_json(proposal: dict[str, Any]) -> str:
    return json.dumps(
        proposal,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def proposal_fingerprint(proposal: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(proposal).encode("utf-8")).hexdigest()


def request_id(proposal: dict[str, Any]) -> str:
    identity = f"{proposal['scope']}\0{proposal['proposal_id']}".encode()
    return f"intent_coord_{hashlib.sha256(identity).hexdigest()[:24]}"


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _emit_optional(lines: list[str], key: str, record: dict[str, Any]) -> None:
    value = record.get(key)
    if isinstance(value, str):
        lines.append(f"    {key}: {_yaml_scalar(value)}")


def build_manifest(proposal: dict[str, Any]) -> str:
    sections = {
        "epic": "epics",
        "task": "tasks",
        "memory": "memories",
        "doc": "docs",
    }
    lines = [f"scope: {_yaml_scalar(str(proposal['scope']))}"]
    records = proposal["records"]
    for entity_type in ("epic", "task", "memory", "doc"):
        selected = [item for item in records if item["entity_type"] == entity_type]
        if not selected:
            continue
        lines.append(f"{sections[entity_type]}:")
        for record in selected:
            lines.append(f"  - key: {_yaml_scalar(str(record['key']))}")
            lines.append(f"    title: {_yaml_scalar(str(record['title']))}")
            if entity_type in {"task", "epic"}:
                for key in ("kind", "priority", "goal", "summary"):
                    _emit_optional(lines, key, record)
            elif entity_type == "memory":
                lines.append(f"    kind: {_yaml_scalar(str(record['kind']))}")
                lines.append(f"    body: {_yaml_scalar(str(record['body']))}")
                _emit_optional(lines, "summary", record)
            else:
                lines.append(f"    type: {_yaml_scalar(str(record['doc_type']))}")
                lines.append(f"    ref: {_yaml_scalar(str(record['ref']))}")
                _emit_optional(lines, "summary", record)
            labels = record.get("labels")
            if isinstance(labels, list):
                rendered = ", ".join(_yaml_scalar(str(item)) for item in labels)
                lines.append(f"    labels: [{rendered}]")
    links = proposal["links"]
    if links:
        lines.append("links:")
        for link in links:
            lines.append(f"  - from: {_yaml_scalar(str(link['from']))}")
            lines.append(f"    edge: {_yaml_scalar(str(link['edge']))}")
            lines.append(f"    to: {_yaml_scalar(str(link['to']))}")
    return "\n".join(lines) + "\n"


def _state_dir(path: Path | None) -> Path:
    return (path or DEFAULT_STATE_DIR).expanduser()


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise CoordinatorError(
            "intent_state_path_unsafe",
            "coordinator state directory must not be a symlink",
        )
    if path.exists() and not path.is_dir():
        raise CoordinatorError(
            "intent_state_path_unsafe", "coordinator state path must be a directory"
        )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError as exc:
        raise CoordinatorError("intent_state_path_unwritable", str(exc)) from exc


def _scope_digest(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:20]


def _receipt_path(state_dir: Path, proposal: dict[str, Any]) -> Path:
    identity = f"{proposal['scope']}\0{proposal['proposal_id']}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:32]
    return (
        state_dir
        / "receipts"
        / _scope_digest(str(proposal["scope"]))
        / f"{digest}.json"
    )


def _scope_lock_state(state_dir: Path, scope: str) -> Path:
    return state_dir / "locks" / f"scope-{_scope_digest(scope)}.json"


def _load_receipt(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise CoordinatorError(
            "intent_receipt_unsafe", "receipt path is not a regular file"
        )
    if path.stat().st_size > MAX_RECEIPT_BYTES:
        raise CoordinatorError("intent_receipt_invalid", "receipt exceeds size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoordinatorError("intent_receipt_invalid", str(exc)) from exc
    if not isinstance(payload, dict):
        raise CoordinatorError("intent_receipt_invalid", "receipt must be an object")
    return payload


def make_oc_runner(*, oc_bin: str, config_path: Path | None, cwd: Path) -> Runner:
    def run(arguments: list[str], operation: str) -> dict[str, Any]:
        command = [oc_bin]
        if config_path is not None:
            command.extend(["--config", str(config_path.expanduser())])
        command.extend(arguments)
        try:
            run_options = {"cwd": cwd, "capture_output": True, "text": True}
            if operation == "intent_codememory_doctor":
                completed = run_bounded(
                    command, operation="intent_codememory_doctor", **run_options
                )
            elif operation == "intent_codememory_find":
                completed = run_bounded(
                    command, operation="intent_codememory_find", **run_options
                )
            elif operation == "intent_codememory_apply":
                completed = run_bounded(
                    command, operation="intent_codememory_apply", **run_options
                )
            else:
                raise ValueError(f"unsupported Codememory operation: {operation}")
        except BoundedCommandError as exc:
            detail = exc.failure.stderr or exc.failure.detail
            raise CoordinatorError(exc.reason_code, detail[:2000]) from exc
        stdout = str(completed.stdout or "").strip()
        stderr = str(completed.stderr or "").strip()
        if completed.returncode != 0:
            raise CoordinatorError(
                f"{operation}_failed",
                (stderr or stdout or f"command exited {completed.returncode}")[:2000],
            )
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise CoordinatorError(
                f"{operation}_invalid_json", "Codememory returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise CoordinatorError(
                f"{operation}_invalid_json", "Codememory returned a non-object payload"
            )
        return payload

    return run


def _doctor(runner: Runner) -> dict[str, Any]:
    report = runner(
        ["config", "--doctor", "--format", "json"], "intent_codememory_doctor"
    )
    if report.get("status") != "ok" or not report.get("runtime_ready"):
        raise CoordinatorError(
            "intent_codememory_unavailable", "Codememory doctor is not ready"
        )
    return report


def _title_collisions(proposal: dict[str, Any], runner: Runner) -> list[dict[str, str]]:
    collisions: list[dict[str, str]] = []
    for record in proposal["records"]:
        report = runner(
            [
                "find",
                str(record["title"]),
                "--type",
                str(record["entity_type"]),
                "--scope",
                str(proposal["scope"]),
                "--limit",
                str(TITLE_LOOKUP_LIMIT),
                "--format",
                "json",
            ],
            "intent_codememory_find",
        )
        items = report.get("items")
        if not isinstance(items, list):
            raise CoordinatorError(
                "intent_codememory_find_invalid",
                "Codememory find returned invalid items",
            )
        if len(items) >= TITLE_LOOKUP_LIMIT:
            raise CoordinatorError(
                "intent_title_lookup_saturated",
                "Codememory title lookup reached its result limit",
                context={
                    "key": str(record["key"]),
                    "entity_type": str(record["entity_type"]),
                    "title": str(record["title"]),
                    "result_count": len(items),
                    "limit": TITLE_LOOKUP_LIMIT,
                },
            )
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("display") or "") == record["title"]:
                collisions.append(
                    {
                        "key": str(record["key"]),
                        "entity_type": str(record["entity_type"]),
                        "title": str(record["title"]),
                        "existing_id": str(item.get("id") or ""),
                    }
                )
                break
    return collisions


def preview_proposal(proposal: dict[str, Any], runner: Runner) -> dict[str, Any]:
    _doctor(runner)
    collisions = _title_collisions(proposal, runner)
    manifest = build_manifest(proposal)
    result = "PASS" if not collisions else "FAIL"
    return {
        "result": result,
        "command": "preview",
        "reason_code": "intent_preview_ready"
        if not collisions
        else "intent_title_collision",
        "proposal_id": proposal["proposal_id"],
        "scope": proposal["scope"],
        "fingerprint": proposal_fingerprint(proposal),
        "request_id": request_id(proposal),
        "manifest_sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
        "record_count": len(proposal["records"]),
        "link_count": len(proposal["links"]),
        "collisions": collisions,
    }


def _write_manifest_file(state_dir: Path, manifest: str) -> Path:
    _ensure_private_directory(state_dir / "tmp")
    descriptor, name = tempfile.mkstemp(
        prefix="intent-manifest-", suffix=".yaml", dir=state_dir / "tmp"
    )
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            handle.write(manifest)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _apply_manifest(
    *,
    manifest: str,
    request: str,
    actor: str,
    state_dir: Path,
    runner: Runner,
) -> dict[str, Any]:
    path = _write_manifest_file(state_dir, manifest)
    try:
        report = runner(
            [
                "batch",
                "plan",
                "--file",
                str(path),
                "--request-id",
                request,
                "--actor",
                actor,
                "--format",
                "json",
            ],
            "intent_codememory_apply",
        )
    finally:
        path.unlink(missing_ok=True)
    return report


def _validate_apply_result(proposal: dict[str, Any], report: dict[str, Any]) -> None:
    if report.get("type") != "batch_plan_result":
        raise CoordinatorError(
            "intent_codememory_apply_invalid",
            "Codememory returned an unexpected result",
        )
    if report.get("scope_key") != proposal["scope"]:
        raise CoordinatorError(
            "intent_codememory_apply_invalid",
            "Codememory returned the wrong scope",
        )
    expected_count = len(proposal["records"]) + len(proposal["links"])
    if type(report.get("count")) is not int or report["count"] != expected_count:
        raise CoordinatorError(
            "intent_codememory_apply_invalid",
            "Codememory returned the wrong change count",
        )
    records = report.get("records")
    links = report.get("links")
    if not isinstance(records, list) or not isinstance(links, list):
        raise CoordinatorError(
            "intent_codememory_apply_invalid",
            "Codememory returned invalid record or link collections",
        )
    if len(records) != len(proposal["records"]) or len(links) != len(proposal["links"]):
        raise CoordinatorError(
            "intent_codememory_apply_invalid",
            "Codememory returned incomplete records or links",
        )

    expected_records = {str(item["key"]): item for item in proposal["records"]}
    ids_by_key: dict[str, str] = {}
    created_ids: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned an invalid record item",
            )
        key = item.get("key")
        created_id = item.get("id")
        if not isinstance(key, str) or key not in expected_records:
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned an unknown record key",
            )
        expected = expected_records[key]
        if (
            item.get("entity_type") != expected["entity_type"]
            or item.get("title") != expected["title"]
        ):
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned mismatched record metadata",
            )
        if (
            not isinstance(created_id, str)
            or not created_id
            or created_id in created_ids
        ):
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned an invalid or duplicate record ID",
            )
        if key in ids_by_key:
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned a duplicate record key",
            )
        ids_by_key[key] = created_id
        created_ids.add(created_id)
    if set(ids_by_key) != set(expected_records):
        raise CoordinatorError(
            "intent_codememory_apply_invalid",
            "Codememory omitted a proposed record",
        )

    expected_links = {
        (
            str(item["edge"]),
            ids_by_key[str(item["from"])],
            ids_by_key[str(item["to"])],
        )
        for item in proposal["links"]
    }
    actual_links: set[tuple[str, str, str]] = set()
    link_ids: set[str] = set()
    for item in links:
        if not isinstance(item, dict):
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned an invalid link item",
            )
        link_id = item.get("id")
        if not isinstance(link_id, str) or not link_id or link_id in link_ids:
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned an invalid or duplicate link ID",
            )
        link = (item.get("edge_type"), item.get("from_id"), item.get("to_id"))
        if not all(isinstance(value, str) and value for value in link):
            raise CoordinatorError(
                "intent_codememory_apply_invalid",
                "Codememory returned invalid link metadata",
            )
        actual_links.add(link)
        link_ids.add(link_id)
    if actual_links != expected_links or len(actual_links) != len(links):
        raise CoordinatorError(
            "intent_codememory_apply_invalid",
            "Codememory returned mismatched links",
        )


def _applied_report(receipt: dict[str, Any], *, replayed: bool) -> dict[str, Any]:
    result = receipt.get("result")
    if not isinstance(result, dict):
        raise CoordinatorError(
            "intent_receipt_invalid", "applied receipt has no result"
        )
    return {
        "result": "PASS",
        "command": "apply",
        "reason_code": "intent_apply_replayed"
        if replayed
        else "intent_apply_completed",
        "proposal_id": receipt.get("proposal_id"),
        "scope": receipt.get("scope"),
        "fingerprint": receipt.get("fingerprint"),
        "request_id": receipt.get("request_id"),
        "actor": receipt.get("actor"),
        "source": receipt.get("source"),
        "receipt_status": "applied",
        "replayed": replayed,
        "record_count": len(result.get("records") or []),
        "link_count": len(result.get("links") or []),
        "records": result.get("records") or [],
        "links": result.get("links") or [],
    }


def apply_proposal(
    proposal: dict[str, Any],
    runner: Runner,
    *,
    state_dir: Path,
    actor: str,
) -> dict[str, Any]:
    state_dir = _state_dir(state_dir)
    normalized_actor = _require_text(actor, "actor", max_chars=128)
    fingerprint = proposal_fingerprint(proposal)
    request = request_id(proposal)
    manifest = build_manifest(proposal)
    receipt_path = _receipt_path(state_dir, proposal)
    lock_state = _scope_lock_state(state_dir, str(proposal["scope"]))
    try:
        for directory in (
            state_dir,
            state_dir / "locks",
            state_dir / "receipts",
            receipt_path.parent,
            state_dir / "tmp",
        ):
            _ensure_private_directory(directory)
        lock_path = lock_state.with_name(f"{lock_state.name}.lock")
        if lock_path.is_symlink():
            raise CoordinatorError(
                "intent_state_path_unsafe", "coordinator lock must not be a symlink"
            )
        with json_state_write_lock(lock_state):
            receipt = _load_receipt(receipt_path)
            if receipt is not None:
                if receipt.get("fingerprint") != fingerprint:
                    raise CoordinatorError(
                        "intent_proposal_id_conflict",
                        "proposal_id already exists with different content",
                    )
                if (
                    receipt.get("request_id") != request
                    or receipt.get("manifest") != manifest
                    or receipt.get("source") != proposal["source"]
                ):
                    raise CoordinatorError(
                        "intent_receipt_conflict",
                        "stored receipt does not match the deterministic proposal",
                    )
                stored_actor = receipt.get("actor")
                if not isinstance(stored_actor, str) or not stored_actor:
                    raise CoordinatorError(
                        "intent_receipt_invalid", "receipt has no valid actor"
                    )
                if receipt.get("status") == "applied":
                    result = receipt.get("result")
                    if not isinstance(result, dict):
                        raise CoordinatorError(
                            "intent_receipt_invalid", "applied receipt has no result"
                        )
                    _validate_apply_result(proposal, result)
                    return _applied_report(receipt, replayed=True)
                if receipt.get("status") != "prepared":
                    raise CoordinatorError(
                        "intent_receipt_invalid", "receipt has an unsupported status"
                    )
            else:
                _doctor(runner)
                collisions = _title_collisions(proposal, runner)
                if collisions:
                    raise CoordinatorError(
                        "intent_title_collision",
                        "proposal collides with existing Codememory records",
                        context={"collisions": collisions},
                    )
                stored_actor = normalized_actor
                receipt = {
                    "version": FORMAT_VERSION,
                    "proposal_id": proposal["proposal_id"],
                    "scope": proposal["scope"],
                    "source": proposal["source"],
                    "fingerprint": fingerprint,
                    "request_id": request,
                    "actor": stored_actor,
                    "status": "prepared",
                    "manifest": manifest,
                    "manifest_sha256": hashlib.sha256(
                        manifest.encode("utf-8")
                    ).hexdigest(),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "result": None,
                }
                atomic_write_json(receipt_path, receipt)
            _doctor(runner)
            result = _apply_manifest(
                manifest=manifest,
                request=request,
                actor=stored_actor,
                state_dir=state_dir,
                runner=runner,
            )
            _validate_apply_result(proposal, result)
            receipt["status"] = "applied"
            receipt["updated_at"] = now_iso()
            receipt["result"] = result
            atomic_write_json(receipt_path, receipt)
            return _applied_report(receipt, replayed=False)
    except OSError as exc:
        raise CoordinatorError("intent_state_io_failed", str(exc)) from exc


def schema_report() -> dict[str, Any]:
    return {
        "result": "PASS",
        "command": "schema",
        "version": FORMAT_VERSION,
        "max_changes": MAX_CHANGES,
        "entity_types": list(ENTITY_TYPES),
        "allowed_edges": list(ALLOWED_EDGES),
        "source_kinds": list(SOURCE_KINDS),
        "fresh_add_only": True,
        "raw_prompt_field_allowed": False,
    }


def doctor_report(runner: Runner, state_dir: Path) -> dict[str, Any]:
    report = _doctor(runner)
    state_dir = _state_dir(state_dir)
    prepared = 0
    applied = 0
    if state_dir.exists():
        for path in (state_dir / "receipts").glob("*/*.json"):
            try:
                receipt = _load_receipt(path)
            except CoordinatorError:
                continue
            if receipt and receipt.get("status") == "prepared":
                prepared += 1
            elif receipt and receipt.get("status") == "applied":
                applied += 1
    return {
        "result": "PASS",
        "command": "doctor",
        "codememory_status": report.get("status"),
        "codememory_backend": report.get("backend"),
        "state_dir": str(state_dir),
        "prepared_receipts": prepared,
        "applied_receipts": applied,
        "max_changes": MAX_CHANGES,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="/intent", description="Reconcile typed intent proposals into Codememory"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")

    preview = subparsers.add_parser("preview", parents=[common])
    preview.add_argument("--file", type=Path, required=True)

    apply = subparsers.add_parser("apply", parents=[common])
    apply.add_argument("--file", type=Path, required=True)

    subparsers.add_parser("doctor", parents=[common])
    schema = subparsers.add_parser("schema")
    schema.add_argument("--json", action="store_true")
    return parser


def _emit(report: dict[str, Any], json_output: bool) -> int:
    if json_output:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"result: {report.get('result')}")
        print(f"command: {report.get('command')}")
        if report.get("reason_code"):
            print(f"reason_code: {report.get('reason_code')}")
        if report.get("proposal_id"):
            print(f"proposal_id: {report.get('proposal_id')}")
        if "record_count" in report:
            print(f"records: {report.get('record_count')}")
        if "link_count" in report:
            print(f"links: {report.get('link_count')}")
        if report.get("detail"):
            print(f"detail: {report.get('detail')}")
    return 0 if report.get("result") == "PASS" else 1


def main(argv: list[str]) -> int:
    json_output = "--json" in argv
    try:
        args = _parser().parse_args(argv)
        json_output = bool(getattr(args, "json", False))
        if args.command == "schema":
            return _emit(schema_report(), json_output)
        runner = make_oc_runner(
            oc_bin=DEFAULT_OC_BIN,
            config_path=DEFAULT_OC_CONFIG,
            cwd=Path.cwd(),
        )
        if args.command == "doctor":
            return _emit(doctor_report(runner, DEFAULT_STATE_DIR), json_output)
        proposal = load_proposal(args.file.expanduser())
        if args.command == "preview":
            return _emit(preview_proposal(proposal, runner), json_output)
        if args.command == "apply":
            return _emit(
                apply_proposal(
                    proposal,
                    runner,
                    state_dir=DEFAULT_STATE_DIR,
                    actor=DEFAULT_ACTOR,
                ),
                json_output,
            )
        raise CoordinatorError("intent_command_invalid", "unsupported command")
    except CoordinatorError as exc:
        report = {
            "result": "FAIL",
            "command": "intent",
            "reason_code": exc.reason_code,
            "detail": exc.detail,
            **exc.context,
        }
        return _emit(report, json_output)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
