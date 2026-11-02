"""Read-only research and admission for agent-authored intent proposals.

Synthesis belongs to the calling agent. This module grants no tools to that
agent and never invokes a provider, subprocess, Codememory, or state store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from intent_coordinator_command import (
    MAX_PROPOSAL_BYTES,
    PROPOSAL_ID_PATTERN,
    SHA256_PATTERN,
    TOKEN_PATTERN,
    CoordinatorError,
    _normalize_source,
    _require_text,
    canonical_json,
    normalize_proposal,
    proposal_fingerprint,
)

MAX_FILES = 8
MAX_WORKERS = 2
MAX_FILE_BYTES = 128 * 1024
MAX_EXCERPT_BYTES = 4096
MAX_RANGE_LINES = 100
DEADLINE_SECONDS = 5.0


def reject(reason: str, detail: str) -> None:
    raise CoordinatorError(f"intent_planner_{reason}", detail)


def object_fields(
    value: Any, required: set[str], optional: set[str] | None = None
) -> dict:
    if not isinstance(value, dict) or not required <= value.keys():
        reject("schema_invalid", "missing required object fields")
    if value.keys() - required - (optional or set()):
        reject("schema_invalid", "unknown object fields")
    return value


def version_one(value: Any) -> None:
    if type(value) is not int or value != 1:
        reject("schema_invalid", "version must be integer 1")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class Budget:
    def __init__(self, seconds: float = DEADLINE_SECONDS) -> None:
        self.deadline = time.monotonic() + seconds
        self.cancelled = threading.Event()

    def check(self) -> None:
        if self.cancelled.is_set():
            reject("cancelled", "research cancelled; no partial artifact emitted")
        if time.monotonic() >= self.deadline:
            reject(
                "deadline", "research deadline exceeded; no partial artifact emitted"
            )


@contextmanager
def cancellation(budget: Budget):
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda *_: budget.cancelled.set())
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def path_parts(value: Any) -> list[str]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or any(char in value for char in "\0\r\n\\:*?[]{}")
        or value.startswith(("/", "~"))
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        reject(
            "path_invalid", "research requires literal normalized relative file paths"
        )
    return value.split("/")


def open_file(root_fd: int, parts: list[str]) -> int:
    """Anchor every component against symlink traversal, not just the basename."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        reject("unsupported_platform", "no-follow directory opens are required")
    directory = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        return os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)


def signature(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_file(root_fd: int, parts: list[str], limit: int, budget: Budget) -> bytes:
    budget.check()
    descriptor = open_file(root_fd, parts)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            reject("file_invalid", "only regular files are admitted")
        if before.st_size > limit:
            reject("limit_exceeded", "file byte limit exceeded")
        chunks = []
        size = 0
        while True:
            budget.check()
            chunk = os.read(descriptor, min(16384, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                reject("limit_exceeded", "file byte limit exceeded")
        after = os.fstat(descriptor)
        current = open_file(root_fd, parts)
        try:
            if (
                signature(before) != signature(after)
                or signature(after) != signature(os.fstat(current))
                or size != before.st_size
            ):
                reject("evidence_changed", "file changed during research")
        finally:
            os.close(current)
        budget.check()
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def json_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            reject("schema_invalid", "duplicate JSON object key")
        result[key] = value
    return result


def validate_json_depth(text: str) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 32:
                reject("limit_exceeded", "JSON nesting exceeds 32 levels")
        elif char in "}]":
            depth -= 1


def invalid_constant(_value: str) -> None:
    reject("schema_invalid", "non-finite JSON values are forbidden")


def load_json(path: Path, budget: Budget) -> Any:
    # Explicit input files may be outside the repository, including an ingress
    # spool. The operator must name canonical paths; no symlinks are followed.
    absolute = path.expanduser().absolute()
    parts = path_parts(absolute.as_posix().lstrip("/"))
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        raw = read_file(root_fd, parts, MAX_PROPOSAL_BYTES, budget)
    finally:
        os.close(root_fd)
    try:
        text = raw.decode("utf-8")
        validate_json_depth(text)
        value = json.loads(
            text, object_pairs_hook=json_pairs, parse_constant=invalid_constant
        )
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                item.encode("utf-8")  # Reject lone surrogate escapes before hashing.
            elif isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return value
    except (UnicodeError, ValueError, RecursionError):
        reject("schema_invalid", "input must be bounded UTF-8 JSON")


def normalize_request(value: Any) -> dict:
    value = object_fields(
        value, {"version", "proposal_id", "scope", "source", "research"}
    )
    version_one(value["version"])
    proposal_id = _require_text(value["proposal_id"], "proposal_id", max_chars=128)
    if not PROPOSAL_ID_PATTERN.fullmatch(proposal_id):
        reject("schema_invalid", "invalid proposal_id")
    research = value["research"]
    if not isinstance(research, list) or not 1 <= len(research) <= MAX_FILES:
        reject("limit_exceeded", "research requires 1..8 file citations")
    citations = []
    ids = set()
    for item in research:
        item = object_fields(item, {"id", "path", "start_line", "end_line"})
        identity = item["id"]
        if (
            not isinstance(identity, str)
            or not TOKEN_PATTERN.fullmatch(identity)
            or identity == "source"
            or identity in ids
        ):
            reject(
                "schema_invalid", "research IDs must be unique tokens other than source"
            )
        ids.add(identity)
        path_parts(item["path"])
        start, end = item["start_line"], item["end_line"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 1 <= start <= end
            or end - start + 1 > MAX_RANGE_LINES
        ):
            reject(
                "limit_exceeded",
                "citations require 1-based ranges of at most 100 lines",
            )
        citations.append(dict(item))
    return {
        "version": 1,
        "proposal_id": proposal_id,
        "scope": _require_text(value["scope"], "scope", max_chars=200),
        "source": _normalize_source(value["source"]),
        "research": sorted(citations, key=lambda item: item["id"]),
    }


def ingress_digest(parts: list[str]) -> str:
    value = b"".join(
        str(len(part.encode("utf-8"))).encode() + b":" + part.encode("utf-8") + b"\0"
        for part in parts
    )
    return hashlib.sha256(value).hexdigest()


def bind_ingress(value: Any, source: dict, root: Path) -> dict:
    value = object_fields(
        value,
        {
            "version",
            "envelope_id",
            "project_digest",
            "observed_at",
            "source",
            "content",
        },
    )
    version_one(value["version"])
    origin = object_fields(value["source"], {"kind", "session_id", "message_id"})
    content = object_fields(
        value["content"],
        {"mode", "char_count", "sha256"},
        {"preview", "truncated", "redacted_fields", "omitted_reason"},
    )
    observed = value["observed_at"]
    try:
        if not isinstance(observed, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z",
            observed,
        ):
            raise ValueError("not canonical UTC")
        parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != observed:
            raise ValueError("noncanonical timestamp")
    except (AttributeError, TypeError, ValueError):
        reject(
            "schema_invalid", "ingress requires a canonical UTC millisecond timestamp"
        )
    if content["mode"] == "metadata":
        if {"preview", "truncated", "redacted_fields"} & content.keys() or content.get(
            "omitted_reason", "redaction_failed"
        ) != "redaction_failed":
            reject("schema_invalid", "invalid metadata envelope")
    elif (
        not isinstance(content.get("preview"), str)
        or len(content["preview"]) > 65536
        or type(content.get("truncated")) is not bool
        or type(content.get("redacted_fields")) is not int
        or content["redacted_fields"] < 0
        or "omitted_reason" in content
    ):
        reject("schema_invalid", "invalid preview envelope")
    for name in ("session_id", "message_id"):
        identity = origin[name]
        if (
            not isinstance(identity, str)
            or not identity
            or identity != identity.strip()
            or len(identity.encode("utf-16-le")) // 2 > 256
            or re.search(r"[\x00-\x1f\x7f]", identity)
        ):
            reject("schema_invalid", "invalid ingress source identifier")
    project = ingress_digest(["intent-ingress-project-v1", str(root)])[:32]
    if (
        origin["kind"] != "user"
        or source["kind"] != "user"
        or origin["message_id"] != source["id"]
        or origin["session_id"] != source.get("session_id")
        or content["sha256"] != source.get("content_sha256")
        or not isinstance(content["sha256"], str)
        or not SHA256_PATTERN.fullmatch(content["sha256"])
        or content["mode"] not in ("metadata", "redacted_preview")
        or type(content["char_count"]) is not int
        or not 1 <= content["char_count"] <= 1048576
        or value["project_digest"] != project
    ):
        reject(
            "source_mismatch", "ingress identity, content digest, or project mismatch"
        )
    envelope_id = (
        "intent_ingress_"
        + ingress_digest(
            [
                "intent-ingress-envelope-v1",
                project,
                origin["session_id"],
                origin["message_id"],
            ]
        )[:32]
    )
    if value["envelope_id"] != envelope_id:
        reject("source_mismatch", "ingress envelope identity mismatch")
    # No preview/observed_at is copied into output or used as authority.
    return {
        "envelope_id": envelope_id,
        "project_digest": project,
        "content_sha256": content["sha256"],
    }


def collect_citation(root_fd: int, item: dict, budget: Budget) -> dict:
    raw = read_file(root_fd, path_parts(item["path"]), MAX_FILE_BYTES, budget)
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        reject("file_invalid", "research files must be UTF-8 text")
    lines = text.splitlines(keepends=True)
    if item["end_line"] > len(lines):
        reject("range_invalid", "citation exceeds file line count")
    excerpt = "".join(lines[item["start_line"] - 1 : item["end_line"]])
    if len(excerpt.encode("utf-8")) > MAX_EXCERPT_BYTES:
        reject("limit_exceeded", "citation excerpt exceeds 4096 bytes")
    return {
        **item,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "excerpt": excerpt,
    }


def research(value: Any, root: Path, budget: Budget, ingress: Any = None) -> dict:
    request = normalize_request(value)
    root = root.resolve(strict=True)
    binding = (
        bind_ingress(ingress, request["source"], root) if ingress is not None else None
    )
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Only fixed reads run in workers: no executable callback/selected tool.
        # At most 1 MiB is read in a sweep, including bytes outside excerpts.
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [
                pool.submit(collect_citation, root_fd, item, budget)
                for item in request["research"]
            ]
            try:
                evidence = [future.result() for future in futures]
                budget.check()
            except BaseException:
                budget.cancelled.set()
                for future in futures:
                    future.cancel()
                raise
    finally:
        os.close(root_fd)
    return {
        "version": 1,
        "type": "intent_research",
        "request": request,
        "ingress": binding,
        "evidence": evidence,
    }


def targets(proposal: dict) -> set[str]:
    return {"record:" + item["key"] for item in proposal["records"]} | {
        "link:" + item["from"] + "|" + item["edge"] + "|" + item["to"]
        for item in proposal["links"]
    }


def quality(proposal: dict) -> None:
    for item in proposal["records"]:
        if item["entity_type"] in {"task", "epic"}:
            for name in ("goal", "summary"):
                _require_text(item.get(name), name, max_chars=1000)
    for edge in ("parent-of", "depends-on"):
        adjacency: dict[str, list[str]] = {}
        for link in proposal["links"]:
            if link["edge"] == edge:
                adjacency.setdefault(link["from"], []).append(link["to"])

        def visit(node: str, stack: set[str], graph: dict = adjacency) -> None:
            if node in stack:
                reject("quality_failed", "proposal hierarchy or dependency cycle")
            for child in graph.get(node, []):
                visit(child, stack | {node}, graph)

        for key in adjacency:
            visit(key, set())


def plan(value: Any, root: Path, budget: Budget, ingress: Any = None) -> dict:
    value = object_fields(
        value, {"version", "research", "proposal", "assessments", "unresolved"}
    )
    version_one(value["version"])
    if value["unresolved"] != []:
        reject(
            "quality_failed", "unresolved questions must be resolved before admission"
        )
    previous = object_fields(
        value["research"], {"version", "type", "request", "ingress", "evidence"}
    )
    proposal = normalize_proposal(value["proposal"])
    request = normalize_request(previous["request"])
    for key in ("proposal_id", "scope", "source"):
        if proposal[key] != request[key]:
            reject(
                "source_mismatch",
                "proposal must preserve research source, scope, and identity",
            )
    quality(proposal)
    expected = targets(proposal)
    assessments = value["assessments"]
    if not isinstance(assessments, list) or len(assessments) != len(expected):
        reject("quality_failed", "every record and link requires one assessment")
    allowed_evidence = {item["id"] for item in request["research"]} | {"source"}
    normalized = []
    seen = set()
    used = set()
    for assessment in assessments:
        assessment = object_fields(
            assessment, {"target", "evidence", "rationale", "acceptance"}
        )
        target = assessment["target"]
        citations = assessment["evidence"]
        if (
            not isinstance(target, str)
            or target not in expected
            or target in seen
            or not isinstance(citations, list)
            or not 1 <= len(citations) <= MAX_FILES + 1
            or any(
                not isinstance(item, str) or item not in allowed_evidence
                for item in citations
            )
            or len(set(citations)) != len(citations)
        ):
            reject("quality_failed", "invalid, duplicate, or unsupported assessment")
        seen.add(target)
        used.update(citations)
        normalized.append(
            {
                "target": target,
                "evidence": sorted(citations),
                "rationale": _require_text(
                    assessment["rationale"], "rationale", max_chars=1000
                ),
                "acceptance": _require_text(
                    assessment["acceptance"], "acceptance", max_chars=1000
                ),
            }
        )
    if not allowed_evidence - {"source"} <= used:
        reject("quality_failed", "every research citation must support an assessment")
    current = research(request, root, budget, ingress)
    if canonical_json(current) != canonical_json(previous):
        reject(
            "evidence_changed",
            "research packet changed or does not match current files/ingress",
        )
    budget.check()
    return {
        "version": 1,
        "type": "intent_plan",
        "authority": "proposal-only",
        "proposal": proposal,
        "proposal_sha256": proposal_fingerprint(proposal),
        "research_sha256": digest(current),
        "source": request["source"],
        "ingress": current["ingress"],
        "evidence": [
            {key: val for key, val in item.items() if key != "excerpt"}
            for item in current["evidence"]
        ],
        "assessments": sorted(normalized, key=lambda item: item["target"]),
        "gates": {
            name: True
            for name in (
                "schema",
                "source_binding",
                "fresh_evidence",
                "coverage",
                "no_unresolved",
            )
        },
        "limitations": [
            "Source identity and semantic assessments are caller-asserted.",
            "Target-graph collisions require coordinator preview; this artifact grants no write authority.",
        ],
    }


def command_report(args: Any) -> dict:
    budget = Budget()
    try:
        with cancellation(budget):
            value = load_json(args.file, budget)
            ingress = (
                load_json(args.ingress_file, budget) if args.ingress_file else None
            )
            operation = research if args.command == "research" else plan
            artifact = operation(value, args.root, budget, ingress)
            budget.check()
        return {"result": "PASS", "command": args.command, "artifact": artifact}
    except CoordinatorError as exc:
        return {
            "result": "FAIL",
            "command": args.command,
            "reason_code": exc.reason_code,
            "detail": exc.detail,
        }
    except OSError:
        return {
            "result": "FAIL",
            "command": args.command,
            "reason_code": "intent_planner_file_unreadable",
            "detail": "input or citation is unreadable or unsafe",
        }
