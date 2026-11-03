"""Read-only, scoped observation of one shared-memory cleanup candidate set.

The fingerprint is not an authorization or an apply token. No deletion,
redaction, archive, backup, source write, or cross-store operation is provided.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

MAX_CANDIDATES = 10_000
MAX_COLUMNS = 128
MAX_COLUMN_NAME_CHARS = 256
MAX_ROW_BYTES = 1024 * 1024
MAX_SERIALIZED_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SQLITE_HEAP_BYTES = 128 * 1024 * 1024
MAX_WORKER_MEMORY_BYTES = 512 * 1024 * 1024
WORKER_TIMEOUT_SECONDS = 30.0
MAX_WORKER_OUTPUT_BYTES = 8192
VERSION_DOMAIN = b"my_opencode.shared_memory.cleanup_snapshot.v1\0"
FLAGS = frozenset({"--db-path", "--scope", "--namespace", "--cutoff"})
REASON_CODES = frozenset(
    {
        "shared_memory_inventory_invalid_arguments",
        "shared_memory_inventory_unavailable",
        "shared_memory_inventory_limits_exceeded",
        "shared_memory_inventory_worker_unavailable",
        "shared_memory_inventory_worker_timeout",
        "shared_memory_inventory_worker_invalid",
    }
)
USAGE = (
    "usage: python3 scripts/data_lifecycle_command.py inventory-shared-memory "
    "--db-path <absolute-path> "
    "--scope <session|repo|shared> --namespace <exact-name> "
    "--cutoff <YYYY-MM-DDTHH:MM:SSZ>"
)


class InventoryError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _safe_text(value: str, *, maximum: int) -> bool:
    if (
        not value
        or value != value.strip()
        or len(value) > maximum
        or value.startswith("-")
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _arguments(argv: list[str]) -> dict[str, str]:
    if len(argv) != len(FLAGS) * 2:
        raise InventoryError("shared_memory_inventory_invalid_arguments")
    pairs = list(zip(argv[::2], argv[1::2]))
    if {key for key, _ in pairs} != FLAGS or len({key for key, _ in pairs}) != len(
        FLAGS
    ):
        raise InventoryError("shared_memory_inventory_invalid_arguments")
    args = dict(pairs)
    path = args["--db-path"]
    namespace = args["--namespace"]
    cutoff = args["--cutoff"]
    if (
        not _safe_text(path, maximum=4096)
        or not Path(path).is_absolute()
        or ".." in Path(path).parts
        or args["--scope"] not in {"session", "repo", "shared"}
        or not _safe_text(namespace, maximum=256)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", cutoff)
    ):
        raise InventoryError("shared_memory_inventory_invalid_arguments")
    try:
        datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InventoryError("shared_memory_inventory_invalid_arguments") from exc
    return args


def _enforce_memory_limit() -> None:
    if not (sys.platform.startswith("darwin") or sys.platform.startswith("linux")):
        raise InventoryError("shared_memory_inventory_worker_unavailable")
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = MAX_WORKER_MEMORY_BYTES
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        if soft != resource.RLIM_INFINITY:
            limit = min(limit, soft)
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
            actual, _ = resource.getrlimit(resource.RLIMIT_AS)
            if actual == resource.RLIM_INFINITY or actual > MAX_WORKER_MEMORY_BYTES:
                raise ValueError("address-space limit was not enforced")
        except (OSError, ValueError):
            # Some Darwin kernels reject address-space limits. There the bounded
            # source-copy and SQLite-heap limits below still apply; they are not
            # a hard limit on all Python process memory.
            if not sys.platform.startswith("darwin"):
                raise
        probe = sqlite3.connect(":memory:")
        try:
            row = probe.execute(
                f"PRAGMA hard_heap_limit={MAX_SQLITE_HEAP_BYTES}"
            ).fetchone()
            if row is None or not 0 < int(row[0]) <= MAX_SQLITE_HEAP_BYTES:
                raise ValueError("SQLite heap limit was not enforced")
        finally:
            probe.close()
    except (ImportError, OSError, ValueError, sqlite3.Error, TypeError) as exc:
        raise InventoryError("shared_memory_inventory_worker_unavailable") from exc


def _add_frame(digest: Any, value: bytes) -> None:
    digest.update(struct.pack(">Q", len(value)))
    digest.update(value)


def _encode(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
    except (TypeError, UnicodeError, ValueError) as exc:
        raise InventoryError("shared_memory_inventory_unavailable") from exc


def _inventory(args: dict[str, str]) -> dict[str, Any]:
    from memory_lifecycle_command import _cleanup_where
    from shared_memory_runtime import connect_readonly

    conn = None
    try:
        conn = connect_readonly(
            Path(args["--db-path"]), max_source_bytes=MAX_SOURCE_BYTES
        )
        if (
            not hasattr(conn, "setlimit")
            or not hasattr(conn, "getlimit")
            or not hasattr(sqlite3, "SQLITE_LIMIT_LENGTH")
        ):
            raise InventoryError("shared_memory_inventory_worker_unavailable")
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_ROW_BYTES)
        if conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) > MAX_ROW_BYTES:
            raise InventoryError("shared_memory_inventory_worker_unavailable")
        where_sql, parameters = _cleanup_where(
            cutoff=args["--cutoff"],
            scope=args["--scope"],
            namespace=args["--namespace"],
        )
        count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM memories WHERE {where_sql}", parameters
            ).fetchone()[0]
        )
        if count > MAX_CANDIDATES:
            raise InventoryError("shared_memory_inventory_limits_exceeded")
        digest = hashlib.sha256(VERSION_DOMAIN)
        _add_frame(
            digest, _encode([args["--scope"], args["--namespace"], args["--cutoff"]])
        )
        cursor = conn.execute(
            f"SELECT * FROM memories WHERE {where_sql} ORDER BY id COLLATE BINARY",
            parameters,
        )
        columns = [item[0] for item in cursor.description]
        if (
            not columns
            or len(columns) > MAX_COLUMNS
            or any(
                not isinstance(name, str)
                or not name
                or len(name) > MAX_COLUMN_NAME_CHARS
                for name in columns
            )
        ):
            raise InventoryError("shared_memory_inventory_limits_exceeded")
        _add_frame(digest, _encode(columns))
        visited = total = 0
        for row in cursor:
            values = list(row)
            if (
                not isinstance(row["id"], str)
                or not row["id"]
                or any(
                    value is not None and type(value) not in (str, int)
                    for value in values
                )
            ):
                raise InventoryError("shared_memory_inventory_unavailable")
            encoded = _encode(values)
            total += len(encoded)
            visited += 1
            if total > MAX_SERIALIZED_BYTES or visited > MAX_CANDIDATES:
                raise InventoryError("shared_memory_inventory_limits_exceeded")
            _add_frame(digest, encoded)
        if visited != count:
            raise InventoryError("shared_memory_inventory_unavailable")
        return {
            "result": "PASS",
            "kind": "shared_memory_cleanup_snapshot_inventory",
            "schema_version": 1,
            "scope": args["--scope"],
            "cutoff": args["--cutoff"],
            "candidate_count": count,
            "candidate_snapshot_sha256": digest.hexdigest(),
            "source_inspected": True,
            "apply_supported": False,
            "source_mutation_supported": False,
            "source_identity_bound": False,
            "authorization_verified": False,
            "quiescence_verified": False,
            "recovery_verified": False,
            "cross_store_inventory_complete": False,
            "sensitivity": "local-sensitive",
        }
    except InventoryError:
        raise
    except sqlite3.DataError as exc:
        raise InventoryError("shared_memory_inventory_limits_exceeded") from exc
    except (
        OSError,
        sqlite3.Error,
        RuntimeError,
        ValueError,
        TypeError,
        MemoryError,
    ) as exc:
        raise InventoryError("shared_memory_inventory_unavailable") from exc
    finally:
        if conn is not None:
            conn.close()


def _failure(code: str) -> dict[str, str]:
    if code not in REASON_CODES:
        code = "shared_memory_inventory_worker_invalid"
    return {"result": "FAIL", "reason_code": code}


def _valid_report(value: Any, args: dict[str, str]) -> bool:
    if not isinstance(value, dict):
        return False
    expected = {
        "result": "PASS",
        "kind": "shared_memory_cleanup_snapshot_inventory",
        "schema_version": 1,
        "scope": args["--scope"],
        "cutoff": args["--cutoff"],
        "source_inspected": True,
        "apply_supported": False,
        "source_mutation_supported": False,
        "source_identity_bound": False,
        "authorization_verified": False,
        "quiescence_verified": False,
        "recovery_verified": False,
        "cross_store_inventory_complete": False,
        "sensitivity": "local-sensitive",
    }
    if value.keys() != expected.keys() | {
        "candidate_count",
        "candidate_snapshot_sha256",
    }:
        return False
    if any(
        type(value[key]) is not type(item) or value[key] != item
        for key, item in expected.items()
    ):
        return False
    count = value["candidate_count"]
    fingerprint = value["candidate_snapshot_sha256"]
    return (
        type(count) is int
        and 0 <= count <= MAX_CANDIDATES
        and isinstance(fingerprint, str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", fingerprint))
    )


def main(argv: list[str]) -> int:
    if argv == ["--help"]:
        print(USAGE)
        return 0
    worker = bool(argv and argv[0] == "--internal-worker")
    try:
        args = _arguments(argv[1:] if worker else argv)
        if worker:
            if __name__ != "__main__":
                raise InventoryError("shared_memory_inventory_invalid_arguments")
            _enforce_memory_limit()
            report = _inventory(args)
        else:
            from sqlite_doctor_command import _decode_json_output, _run_bounded_command

            raw = _run_bounded_command(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(Path(__file__).resolve()),
                    "--internal-worker",
                    *argv,
                ],
                cwd=SCRIPT_DIR.parent,
                timeout_seconds=WORKER_TIMEOUT_SECONDS,
                max_output_bytes=MAX_WORKER_OUTPUT_BYTES,
            )
            if raw.get("kind") == "timeout":
                raise InventoryError("shared_memory_inventory_worker_timeout")
            payload, failure = _decode_json_output(raw)
            if failure or not isinstance(payload, dict):
                raise InventoryError("shared_memory_inventory_worker_invalid")
            if raw.get("exit_code") != 0:
                code = (
                    payload.get("reason_code")
                    if payload.get("result") == "FAIL"
                    else None
                )
                raise InventoryError(
                    code
                    if isinstance(code, str)
                    else "shared_memory_inventory_worker_invalid"
                )
            if not _valid_report(payload, args):
                raise InventoryError("shared_memory_inventory_worker_invalid")
            report = payload
    except InventoryError as exc:
        print(json.dumps(_failure(exc.code), sort_keys=True))
        return 1
    except Exception:  # noqa: BLE001 - do not expose paths, SQLite errors or source contents
        print(
            json.dumps(_failure("shared_memory_inventory_unavailable"), sort_keys=True)
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
