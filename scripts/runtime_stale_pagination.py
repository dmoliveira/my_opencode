from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

STALE_FINDING_CLASSES = (
    "parent_child_mismatch",
    "silent_parent_after_delegation_abort",
    "stale_delegated_child_runtime_recovery_missed",
    "stale_running_tool",
    "generic_stale_incomplete_assistant",
)
PARENT_CHILD_FINDING_CLASSES = frozenset(STALE_FINDING_CLASSES[:3])
STALE_FINDINGS_PER_CLASS_LIMIT = 20
STALE_FINDINGS_LOOKAHEAD_LIMIT = STALE_FINDINGS_PER_CLASS_LIMIT + 1
STALE_FINDINGS_PAGE_SIZE = (
    len(STALE_FINDING_CLASSES) * STALE_FINDINGS_PER_CLASS_LIMIT
)

STALE_CURSOR_VERSION = 1
STALE_CURSOR_ORDER_VERSION = 1
STALE_CURSOR_MAX_ENCODED_BYTES = 4096
STALE_CURSOR_MAX_DECODED_BYTES = 3072
STALE_CURSOR_MAX_ID_BYTES = 1024
STALE_CURSOR_MAX_STALE_SECONDS = 2**31 - 1
STALE_CURSOR_FUTURE_TOLERANCE_MS = 5 * 60 * 1000
STALE_CURSOR_REASON_CODE = "runtime_stale_cursor_invalid"

_CURSOR_KEYS = {
    "classes",
    "db",
    "now_ms",
    "order",
    "page_size",
    "stale_seconds",
    "v",
}
_CLASS_STATE_KEYS = {"after", "exhausted"}


class RuntimeStaleCursorError(ValueError):
    reason_code = STALE_CURSOR_REASON_CODE


def _invalid_cursor() -> RuntimeStaleCursorError:
    return RuntimeStaleCursorError("stale findings cursor is invalid or incompatible")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise _invalid_cursor()
        output[key] = value
    return output


def _strict_int(value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid_cursor()
    if value < minimum or value > maximum:
        raise _invalid_cursor()
    return value


def _strict_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid_cursor()
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _invalid_cursor() from exc
    if len(encoded) > STALE_CURSOR_MAX_ID_BYTES:
        raise _invalid_cursor()
    return value


def _normalize_class_states(raw_classes: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_classes, Mapping) or set(raw_classes) != set(
        STALE_FINDING_CLASSES
    ):
        raise _invalid_cursor()
    classes: dict[str, dict[str, Any]] = {}
    for issue_type in STALE_FINDING_CLASSES:
        state = raw_classes[issue_type]
        if not isinstance(state, Mapping) or set(state) != _CLASS_STATE_KEYS:
            raise _invalid_cursor()
        exhausted = state["exhausted"]
        if not isinstance(exhausted, bool):
            raise _invalid_cursor()
        after = state["after"]
        expected_arity = 3 if issue_type in PARENT_CHILD_FINDING_CLASSES else 2
        if after is None:
            if not exhausted:
                raise _invalid_cursor()
            normalized_after = None
        else:
            if not isinstance(after, list) or len(after) != expected_arity:
                raise _invalid_cursor()
            timestamp = _strict_int(after[0], minimum=0, maximum=2**63 - 1)
            normalized_after = [
                timestamp,
                *(_strict_id(value) for value in after[1:]),
            ]
        classes[issue_type] = {
            "after": normalized_after,
            "exhausted": exhausted,
        }
    return classes


def runtime_stale_database_hash(db_path: Path) -> str:
    normalized = str(db_path.expanduser().resolve())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def initial_runtime_stale_class_states() -> dict[str, dict[str, Any]]:
    return {
        issue_type: {"after": None, "exhausted": False}
        for issue_type in STALE_FINDING_CLASSES
    }


def runtime_stale_row_key(
    issue_type: str,
    row: Mapping[str, Any],
) -> tuple[int, str] | tuple[int, str, str]:
    try:
        if issue_type in PARENT_CHILD_FINDING_CLASSES:
            return (
                int(row["parent_time_updated"]),
                str(row["parent_session_id"]),
                str(row["child_session_id"]),
            )
        if issue_type in STALE_FINDING_CLASSES:
            return (int(row["session_time_updated"]), str(row["session_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid stale finding row for {issue_type}") from exc
    raise ValueError(f"unknown stale finding class: {issue_type}")


def materialize_runtime_stale_class_page(
    issue_type: str,
    rows: Sequence[Mapping[str, Any]],
    previous_state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    materialized = [
        dict(row) for row in rows[:STALE_FINDINGS_PER_CLASS_LIMIT]
    ]
    has_more = len(rows) > STALE_FINDINGS_PER_CLASS_LIMIT
    previous_after = previous_state.get("after")
    after: list[Any] | None = (
        list(runtime_stale_row_key(issue_type, materialized[-1]))
        if materialized
        else (list(previous_after) if isinstance(previous_after, list) else None)
    )
    return materialized, {"after": after, "exhausted": not has_more}


def _canonical_cursor_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def encode_runtime_stale_cursor(
    *,
    now_ms: int,
    stale_seconds: int,
    db_path: Path,
    classes: Mapping[str, Mapping[str, Any]],
) -> str:
    normalized_now_ms = _strict_int(now_ms, minimum=1, maximum=2**63 - 1)
    normalized_stale_seconds = _strict_int(
        stale_seconds,
        minimum=1,
        maximum=STALE_CURSOR_MAX_STALE_SECONDS,
    )
    normalized_classes = _normalize_class_states(classes)
    payload = {
        "v": STALE_CURSOR_VERSION,
        "order": STALE_CURSOR_ORDER_VERSION,
        "page_size": STALE_FINDINGS_PAGE_SIZE,
        "now_ms": normalized_now_ms,
        "stale_seconds": normalized_stale_seconds,
        "db": runtime_stale_database_hash(db_path),
        "classes": {
            issue_type: {
                "after": normalized_classes[issue_type]["after"],
                "exhausted": normalized_classes[issue_type]["exhausted"],
            }
            for issue_type in STALE_FINDING_CLASSES
        },
    }
    raw = _canonical_cursor_bytes(payload)
    if len(raw) > STALE_CURSOR_MAX_DECODED_BYTES:
        raise ValueError("stale findings cursor payload exceeds internal limit")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if len(token.encode("ascii")) > STALE_CURSOR_MAX_ENCODED_BYTES:
        raise ValueError("stale findings cursor exceeds internal limit")
    return token


def decode_runtime_stale_cursor(
    token: str,
    *,
    db_path: Path,
    explicit_stale_seconds: int | None,
    validation_now_ms: int | None = None,
) -> dict[str, Any]:
    try:
        encoded = token.encode("ascii")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise _invalid_cursor() from exc
    if (
        not encoded
        or len(encoded) > STALE_CURSOR_MAX_ENCODED_BYTES
        or b"=" in encoded
        or any(
            byte not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for byte in encoded
        )
    ):
        raise _invalid_cursor()
    padding = b"=" * ((4 - len(encoded) % 4) % 4)
    try:
        raw = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _invalid_cursor() from exc
    if not raw or len(raw) > STALE_CURSOR_MAX_DECODED_BYTES:
        raise _invalid_cursor()
    if encoded != base64.urlsafe_b64encode(raw).rstrip(b"="):
        raise _invalid_cursor()
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RuntimeStaleCursorError) as exc:
        raise _invalid_cursor() from exc
    if not isinstance(payload, dict) or set(payload) != _CURSOR_KEYS:
        raise _invalid_cursor()
    if _canonical_cursor_bytes(payload) != raw:
        raise _invalid_cursor()

    if _strict_int(payload["v"], minimum=1, maximum=1) != STALE_CURSOR_VERSION:
        raise _invalid_cursor()
    if (
        _strict_int(payload["order"], minimum=1, maximum=1)
        != STALE_CURSOR_ORDER_VERSION
    ):
        raise _invalid_cursor()
    if (
        _strict_int(
            payload["page_size"],
            minimum=STALE_FINDINGS_PAGE_SIZE,
            maximum=STALE_FINDINGS_PAGE_SIZE,
        )
        != STALE_FINDINGS_PAGE_SIZE
    ):
        raise _invalid_cursor()
    wall_now_ms = (
        int(time.time() * 1000)
        if validation_now_ms is None
        else int(validation_now_ms)
    )
    cursor_now_ms = _strict_int(
        payload["now_ms"],
        minimum=1,
        maximum=max(1, wall_now_ms + STALE_CURSOR_FUTURE_TOLERANCE_MS),
    )
    stale_seconds = _strict_int(
        payload["stale_seconds"],
        minimum=1,
        maximum=STALE_CURSOR_MAX_STALE_SECONDS,
    )
    if explicit_stale_seconds is not None and stale_seconds != explicit_stale_seconds:
        raise _invalid_cursor()
    db_hash = payload["db"]
    if (
        not isinstance(db_hash, str)
        or len(db_hash) != 64
        or any(char not in "0123456789abcdef" for char in db_hash)
        or db_hash != runtime_stale_database_hash(db_path)
    ):
        raise _invalid_cursor()

    classes = _normalize_class_states(payload["classes"])

    return {
        "v": STALE_CURSOR_VERSION,
        "order": STALE_CURSOR_ORDER_VERSION,
        "page_size": STALE_FINDINGS_PAGE_SIZE,
        "now_ms": cursor_now_ms,
        "stale_seconds": stale_seconds,
        "db": db_hash,
        "classes": classes,
    }


def empty_runtime_stale_pagination(
    *,
    cursor_applied: bool,
) -> dict[str, Any]:
    return {
        "stale_findings_page_size": STALE_FINDINGS_PAGE_SIZE,
        "stale_findings_page_count": 0,
        "stale_findings_page_counts": {
            issue_type: 0 for issue_type in STALE_FINDING_CLASSES
        },
        "stale_findings_has_more": False,
        "stale_findings_truncated": False,
        "stale_findings_next_cursor": None,
        "stale_findings_cursor_applied": cursor_applied,
        "stale_findings_pagination_complete": False,
    }
