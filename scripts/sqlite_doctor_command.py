#!/usr/bin/env python3
"""Inspect the local stores that make up the OpenCode SQLite surface."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from shared_memory_runtime import (  # type: ignore
    DEFAULT_DB_PATH,
    connect_readonly,
    doctor_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEMEMORY_DEFAULT_CONFIG = REPO_ROOT / ".codememory" / "config.sqlite.yaml"
DEFAULT_SCOPE = "dmoliveira/my_opencode"
CHILD_TIMEOUT_SECONDS = 60.0
MAX_CHILD_OUTPUT_BYTES = 64 * 1024
SHARED_MEMORY_WORKER_MEMORY_BYTES = 512 * 1024 * 1024
STORE_ORDER = (
    "runtime_history",
    "session_sidecars",
    "shared_memory",
    "codememory",
)
SEVERITY_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}
RUNTIME_MESSAGE_MARKERS = (
    "database",
    "generic stale",
    "json1",
    "query-only",
    "runtime",
    "scan",
    "sqlite",
    "stale",
    "wal",
)
SIDECAR_MESSAGE_MARKERS = (
    "digest",
    "index",
    "sidecar",
)


def _append_unique(values: list[str], value: Any) -> None:
    if isinstance(value, str) and value and value not in values:
        values.append(value)


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return list(value)


def _severity(warnings: list[str], problems: list[str]) -> str:
    if problems:
        return "FAIL"
    if warnings:
        return "WARN"
    return "PASS"


def _config_path() -> Path:
    configured = os.environ.get("CODEMEMORY_CONFIG_PATH", "").strip()
    return Path(configured).expanduser() if configured else CODEMEMORY_DEFAULT_CONFIG


def _config_value(config_path: Path, key: str, default: str) -> str:
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return default
    prefix = f"{key}:"
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip().strip("'\"")
        if value:
            return value
    return default


def _codememory_scope(config_path: Path) -> str:
    return os.environ.get(
        "CODEMEMORY_SCOPE",
        _config_value(config_path, "scope_key", DEFAULT_SCOPE),
    ).strip() or DEFAULT_SCOPE


def _codememory_db_path(config_path: Path) -> Path:
    raw_path = _config_value(config_path, "path", ".codememory/codememory.sqlite3")
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    config_root = (
        config_path.parent.parent
        if config_path.parent.name == ".codememory"
        else config_path.parent
    )
    return config_root / path


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _run_bounded_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float = CHILD_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_CHILD_OUTPUT_BYTES,
) -> dict[str, Any]:
    try:
        process = subprocess.Popen(
            [str(item) for item in command],
            cwd=str(cwd),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError:
        return {"kind": "missing_command", "exit_code": None}
    except OSError:
        return {"kind": "spawn_failed", "exit_code": None}

    selector = selectors.DefaultSelector()
    streams = {
        process.stdout: "stdout",
        process.stderr: "stderr",
    }
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    captured_bytes = 0
    failure: str | None = None
    deadline = time.monotonic() + timeout_seconds
    try:
        for stream, name in streams.items():
            if stream is not None:
                selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "timeout"
                _terminate_process(process)
                break
            events = selector.select(min(remaining, 0.1))
            for key, _ in events:
                try:
                    chunk = os.read(key.fd, 8192)
                except OSError:
                    chunk = b""
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except (KeyError, ValueError):
                        pass
                    continue
                captured_bytes += len(chunk)
                if captured_bytes > max_output_bytes:
                    failure = "output_limit"
                    _terminate_process(process)
                    break
                buffers[str(key.data)].extend(chunk)
            if failure:
                break
        if failure is None:
            try:
                exit_code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                failure = "timeout"
                _terminate_process(process)
                exit_code = process.returncode
        else:
            exit_code = process.returncode
    finally:
        selector.close()
        if process.poll() is None:
            _terminate_process(process)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    return {
        "kind": failure or "completed",
        "exit_code": exit_code,
        "stdout": bytes(buffers["stdout"]),
        "stderr": bytes(buffers["stderr"]),
    }


def _decode_json_output(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if raw.get("kind") != "completed":
        return None, str(raw.get("kind") or "child_failed")
    try:
        text = bytes(raw.get("stdout") or b"").decode("utf-8")
    except UnicodeDecodeError:
        return None, "invalid_utf8"
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "json_root_not_object"
    return payload, None


def _child_failure_report(
    *,
    name: str,
    path: str | None,
    failure: str,
    exit_code: int | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "result": "FAIL",
        "path": path,
        "warnings": [],
        "problems": [f"{name} diagnostic failed: {failure}"],
        "quick_fixes": [],
        "diagnostic_error": failure,
    }
    if exit_code is not None:
        report["exit_code"] = exit_code
    return report


def _run_json_child(
    command: Sequence[str],
    *,
    name: str,
    path: str | None,
    allow_missing: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    raw = _run_bounded_command(command, cwd=REPO_ROOT)
    if raw.get("kind") == "missing_command" and allow_missing:
        return None, "missing_command"
    report, failure = _decode_json_output(raw)
    if failure:
        return _child_failure_report(
            name=name,
            path=path,
            failure=failure,
            exit_code=raw.get("exit_code"),
        ), None
    assert report is not None
    result = str(report.get("result") or "").upper()
    if result not in SEVERITY_RANK:
        return _child_failure_report(
            name=name,
            path=path,
            failure="result_missing_or_invalid",
            exit_code=raw.get("exit_code"),
        ), None
    exit_code = raw.get("exit_code")
    expected_failure = result == "FAIL"
    if (exit_code == 0) == expected_failure:
        return _child_failure_report(
            name=name,
            path=path,
            failure="exit_code_contradicts_result",
            exit_code=exit_code,
        ), None
    return report, None


def _message_subset(messages: list[str], markers: tuple[str, ...]) -> list[str]:
    return [
        message
        for message in messages
        if any(marker in message.lower() for marker in markers)
    ]


def _runtime_store(session: dict[str, Any] | None) -> dict[str, Any]:
    if session is None:
        return _child_failure_report(
            name="session",
            path=None,
            failure="session_diagnostic_unavailable",
        )
    if session.get("diagnostic_error"):
        return _child_failure_report(
            name="runtime_history",
            path=str(session.get("runtime_db_path") or "") or None,
            failure=str(session["diagnostic_error"]),
            exit_code=session.get("exit_code"),
        )
    try:
        warnings = _string_list(session.get("warnings"), "session warnings")
        problems = _string_list(session.get("problems"), "session problems")
        runtime_warnings = _message_subset(warnings, RUNTIME_MESSAGE_MARKERS)
        runtime_problems = _message_subset(problems, RUNTIME_MESSAGE_MARKERS)
        missing_tables = session.get("runtime_db_missing_tables") or []
        if not isinstance(missing_tables, list) or not all(
            isinstance(item, str) for item in missing_tables
        ):
            raise ValueError("runtime_db_missing_tables must be a list of strings")
        if missing_tables:
            runtime_problems.append(
                "runtime database is missing required table(s): "
                + ", ".join(missing_tables)
            )
        scan_mode = str(session.get("runtime_db_scan_mode") or "")
        if scan_mode not in {
            "",
            "unavailable",
            "incompatible",
            "legacy_fallback",
            "indexed_snapshot",
            "timeout",
            "query_failed",
            "cursor_invalid",
        }:
            runtime_problems.append("runtime database scan mode is invalid")
        if scan_mode in {"query_failed", "timeout", "cursor_invalid"}:
            runtime_problems.append(f"runtime database scan failed: {scan_mode}")
        elif scan_mode in {"unavailable", ""}:
            runtime_warnings.append("runtime database scan is unavailable")
        permission_status = str(session.get("runtime_permission_status") or "")
        if permission_status not in {"", "private", "missing", "repair_required", "blocked"}:
            runtime_problems.append("runtime database permission status is invalid")
        if permission_status == "blocked":
            runtime_problems.append("runtime database permission safety check failed")
        elif permission_status in {"repair_required", "missing"}:
            runtime_warnings.append(
                "runtime database permissions need attention"
                if permission_status == "repair_required"
                else "runtime database does not exist yet"
            )
        if session.get("stuck_findings"):
            runtime_problems.append("runtime diagnostics found stuck session health findings")
        try:
            generic_count = int(session.get("generic_stale_count") or 0)
            generic_threshold = int(
                session.get("generic_stale_problem_threshold") or 0
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("generic stale counts must be integers") from exc
        if generic_count:
            message = f"runtime diagnostics found {generic_count} generic stale session(s)"
            if generic_threshold and generic_count >= generic_threshold:
                runtime_problems.append(message)
            else:
                runtime_warnings.append(message)
        quick_fixes = [
            value
            for value in _string_list(session.get("quick_fixes"), "session quick_fixes")
            if any(marker in value.lower() for marker in RUNTIME_MESSAGE_MARKERS)
        ]
        details = {
            key: session.get(key)
            for key in (
                "runtime_db_path",
                "runtime_db_candidates",
                "exists",
                "runtime_db_size_bytes",
                "runtime_db_wal_bytes",
                "runtime_db_size_warn_bytes",
                "runtime_db_scan_duration_ms",
                "runtime_db_scan_timeout_ms",
                "runtime_db_scan_mode",
                "runtime_db_scan_complete",
                "runtime_db_query_only",
                "runtime_db_snapshot_started",
                "runtime_db_journal_mode",
                "runtime_db_sqlite_version",
                "runtime_db_missing_tables",
                "runtime_db_json1_available",
                "runtime_permission_status",
                "runtime_permission_reason_code",
                "runtime_permission_findings",
                "stuck_findings",
                "generic_stale_count",
                "generic_stale_problem_threshold",
                "stale_findings_page_count",
                "stale_findings_page_counts",
                "stale_findings_has_more",
                "stale_findings_next_cursor",
            )
        }
        runtime_result = _severity(runtime_warnings, runtime_problems)
        if runtime_result != "PASS" and "/session doctor --json" not in quick_fixes:
            quick_fixes.append("/session doctor --json")
        return {
            "result": runtime_result,
            "path": session.get("runtime_db_path"),
            "warnings": list(dict.fromkeys(runtime_warnings)),
            "problems": list(dict.fromkeys(runtime_problems)),
            "quick_fixes": list(dict.fromkeys(quick_fixes)),
            "diagnostics": details,
        }
    except ValueError as exc:
        return _child_failure_report(
            name="runtime_history",
            path=str(session.get("runtime_db_path") or "") or None,
            failure=str(exc),
        )


def _sidecar_store(session: dict[str, Any] | None) -> dict[str, Any]:
    if session is None:
        return _child_failure_report(
            name="session",
            path=None,
            failure="session_diagnostic_unavailable",
        )
    if session.get("diagnostic_error"):
        return _child_failure_report(
            name="session_sidecars",
            path=str(session.get("index_path") or "") or None,
            failure=str(session["diagnostic_error"]),
            exit_code=session.get("exit_code"),
        )
    try:
        warnings = _string_list(session.get("warnings"), "session warnings")
        problems = _string_list(session.get("problems"), "session problems")
        sidecar_warnings = _message_subset(warnings, SIDECAR_MESSAGE_MARKERS)
        sidecar_problems = _message_subset(problems, SIDECAR_MESSAGE_MARKERS)
        findings = session.get("sidecar_findings")
        if not isinstance(findings, list) or not all(
            isinstance(item, dict) for item in findings
        ):
            raise ValueError("sidecar_findings must be a list of objects")
        for finding in findings:
            target = str(finding.get("target") or "sidecar")
            state = str(finding.get("state") or "")
            if state == "blocked":
                sidecar_problems.append(f"{target} sidecar safety check failed")
            elif state in {"repairable", "missing"}:
                sidecar_warnings.append(f"{target} sidecar requires attention")
            elif state not in {"private", "present", "repaired", "safe", ""}:
                sidecar_problems.append(f"{target} sidecar has invalid state: {state}")
        if session.get("corruption_kind") or (
            session.get("error") and session.get("result") == "FAIL"
        ):
            sidecar_problems.append(
                str(session.get("error") or "session sidecar diagnostic failed")
            )
        quick_fixes = [
            value
            for value in _string_list(session.get("quick_fixes"), "session quick_fixes")
            if any(marker in value.lower() for marker in SIDECAR_MESSAGE_MARKERS)
        ]
        if any(
            str(finding.get("state") or "") == "repairable" for finding in findings
        ) and "/session repair-sidecars --json" not in quick_fixes:
            quick_fixes.append("/session repair-sidecars --json")
        details = {
            key: session.get(key)
            for key in (
                "index_path",
                "index_permission_mode",
                "sidecar_findings",
                "sidecar_reason_code",
                "count",
                "corruption_kind",
                "reason_code",
                "error",
            )
        }
        sidecar_result = _severity(sidecar_warnings, sidecar_problems)
        if sidecar_result != "PASS" and "/session doctor --json" not in quick_fixes:
            quick_fixes.append("/session doctor --json")
        return {
            "result": sidecar_result,
            "path": session.get("index_path"),
            "warnings": list(dict.fromkeys(sidecar_warnings)),
            "problems": list(dict.fromkeys(sidecar_problems)),
            "quick_fixes": list(dict.fromkeys(quick_fixes)),
            "diagnostics": details,
        }
    except ValueError as exc:
        return _child_failure_report(
            name="session_sidecars",
            path=str(session.get("index_path") or "") or None,
            failure=str(exc),
        )


def _session_reports() -> tuple[dict[str, Any], dict[str, Any]]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "session_command.py"),
        "doctor",
        "--json",
    ]
    session, missing = _run_json_child(command, name="session", path=None)
    if missing:
        failure = _child_failure_report(
            name="session",
            path=None,
            failure=missing,
        )
        return failure, failure.copy()
    assert session is not None
    return _runtime_store(session), _sidecar_store(session)


def _apply_worker_memory_limit() -> str | None:
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = SHARED_MEMORY_WORKER_MEMORY_BYTES
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        if soft == resource.RLIM_INFINITY or soft > limit:
            resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
        return None
    except (ImportError, OSError, ValueError) as exc:
        return f"shared-memory worker memory limit unavailable: {type(exc).__name__}"


def _inspect_shared_memory() -> dict[str, Any]:
    path = Path(DEFAULT_DB_PATH).expanduser()
    base = {"path": str(path), "quick_fixes": []}
    if not path.exists():
        return {
            **base,
            "result": "WARN",
            "warnings": ["shared-memory database does not exist yet"],
            "problems": [],
            "quick_fixes": ["/memory doctor --json", "/memory-lifecycle stats --json"],
            "diagnostics": {"exists": False},
        }
    connection = None
    try:
        connection = connect_readonly(path)
        if connection is None:
            raise FileNotFoundError(path)
        report = doctor_report(connection, path)
        result = str(report.get("result") or "").upper()
        if result not in {"PASS", "WARN"}:
            raise ValueError("shared-memory doctor returned an invalid result")
        warnings = _string_list(report.get("warnings"), "shared-memory warnings")
        return {
            **base,
            "result": _severity(warnings, []),
            "warnings": warnings,
            "problems": [],
            "diagnostics": report,
        }
    except FileNotFoundError:
        return {
            **base,
            "result": "WARN",
            "warnings": ["shared-memory database does not exist yet"],
            "problems": [],
            "quick_fixes": ["/memory doctor --json", "/memory-lifecycle stats --json"],
            "diagnostics": {"exists": False},
        }
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        return {
            **base,
            "result": "FAIL",
            "warnings": [],
            "problems": [
                "shared-memory read-only inspection failed: " + type(exc).__name__
            ],
            "quick_fixes": ["/memory doctor --json"],
            "diagnostics": {"exists": True},
        }
    finally:
        if connection is not None:
            try:
                if connection.in_transaction:
                    connection.rollback()
            finally:
                connection.close()


def _shared_memory_store() -> dict[str, Any]:
    raw = _run_bounded_command(
        [sys.executable, str(Path(__file__).resolve()), "--shared-memory-worker"],
        cwd=REPO_ROOT,
    )
    report, failure = _decode_json_output(raw)
    if failure:
        return _child_failure_report(
            name="shared_memory",
            path=str(Path(DEFAULT_DB_PATH).expanduser()),
            failure=failure,
            exit_code=raw.get("exit_code"),
        )
    assert report is not None
    try:
        result = str(report.get("result") or "").upper()
        if result not in {"PASS", "WARN", "FAIL"}:
            raise ValueError("shared-memory result is invalid")
        warnings = _string_list(report.get("warnings"), "shared-memory warnings")
        problems = _string_list(report.get("problems"), "shared-memory problems")
        if result != _severity(warnings, problems):
            raise ValueError("shared-memory result contradicts its findings")
    except ValueError as exc:
        return _child_failure_report(
            name="shared_memory",
            path=str(Path(DEFAULT_DB_PATH).expanduser()),
            failure=str(exc),
            exit_code=raw.get("exit_code"),
        )
    exit_code = raw.get("exit_code")
    if (exit_code == 0) != (result != "FAIL"):
        return _child_failure_report(
            name="shared_memory",
            path=str(Path(DEFAULT_DB_PATH).expanduser()),
            failure="exit_code_contradicts_result",
            exit_code=exit_code,
        )
    return report


def _codememory_store() -> dict[str, Any]:
    config_path = _config_path()
    scope = _codememory_scope(config_path)
    db_path = _codememory_db_path(config_path)
    command_name = os.environ.get("MY_OPENCODE_CODEMEMORY_BIN", "oc")
    executable = shutil.which(command_name)
    base = {
        "path": str(db_path),
        "quick_fixes": [],
        "diagnostics": {"config_path": str(config_path), "scope": scope},
    }
    plan_fix = f"oc plan doctor --scope {scope} --format json"
    if not db_path.exists():
        return {
            **base,
            "result": "WARN",
            "warnings": ["Codememory database does not exist yet"],
            "problems": [],
            "quick_fixes": ["oc db migrate"],
        }
    if executable is None:
        return {
            **base,
            "result": "WARN",
            "warnings": ["Codememory oc command is unavailable"],
            "problems": [],
            "quick_fixes": [plan_fix],
        }
    command = [executable]
    if config_path.exists():
        command.extend(["--config", str(config_path)])
    command.extend(["plan", "doctor", "--scope", scope, "--format", "json"])
    raw = _run_bounded_command(command, cwd=REPO_ROOT)
    if raw.get("kind") == "missing_command":
        return {
            **base,
            "result": "WARN",
            "warnings": ["Codememory oc command is unavailable"],
            "problems": [],
            "quick_fixes": [plan_fix],
        }
    report, failure = _decode_json_output(raw)
    if failure:
        return {
            **base,
            "result": "FAIL",
            "warnings": [],
            "problems": [f"Codememory plan doctor failed: {failure}"],
            "quick_fixes": [plan_fix],
            "diagnostics": {**base["diagnostics"], "error": failure},
        }
    assert report is not None
    status = str(report.get("status") or "").lower()
    declared_result = (
        "PASS"
        if status == "ok"
        else "WARN"
        if status in {"warn", "warning"}
        else "FAIL"
        if status in {"fail", "failed", "error"}
        else None
    )
    if declared_result is None:
        return {
            **base,
            "result": "FAIL",
            "warnings": [],
            "problems": ["Codememory plan doctor returned an unknown status"],
            "quick_fixes": [plan_fix],
            "diagnostics": {**base["diagnostics"], "report": report},
        }
    try:
        warnings = _string_list(report.get("warnings"), "Codememory warnings")
        problems = _string_list(report.get("problems"), "Codememory problems")
    except ValueError as exc:
        return {
            **base,
            "result": "FAIL",
            "warnings": [],
            "problems": [f"Codememory plan doctor returned invalid fields: {exc}"],
            "quick_fixes": [plan_fix],
            "diagnostics": {**base["diagnostics"], "report": report},
        }
    result = _severity(warnings, problems)
    if SEVERITY_RANK[declared_result] > SEVERITY_RANK[result]:
        result = declared_result
    exit_code = raw.get("exit_code")
    if (exit_code == 0) != (result != "FAIL"):
        return {
            **base,
            "result": "FAIL",
            "warnings": [],
            "problems": ["Codememory plan doctor exit code contradicts its status"],
            "quick_fixes": [plan_fix],
            "diagnostics": {**base["diagnostics"], "report": report},
        }
    return {
        **base,
        "result": result,
        "warnings": warnings,
        "problems": problems,
        "diagnostics": {**base["diagnostics"], "report": report},
    }


def build_report() -> dict[str, Any]:
    runtime_history, session_sidecars = _session_reports()
    stores = {
        "runtime_history": runtime_history,
        "session_sidecars": session_sidecars,
        "shared_memory": _shared_memory_store(),
        "codememory": _codememory_store(),
    }
    warnings: list[str] = []
    problems: list[str] = []
    quick_fixes: list[str] = []
    result = "PASS"
    for name in STORE_ORDER:
        store = stores[name]
        store_result = str(store.get("result") or "FAIL").upper()
        if store_result not in SEVERITY_RANK:
            store_result = "FAIL"
            store["result"] = store_result
            _append_unique(store.setdefault("problems", []), "store result is invalid")
        if SEVERITY_RANK[store_result] > SEVERITY_RANK[result]:
            result = store_result
        for warning in store.get("warnings", []):
            _append_unique(warnings, f"{name}: {warning}")
        for problem in store.get("problems", []):
            _append_unique(problems, f"{name}: {problem}")
        for quick_fix in store.get("quick_fixes", []):
            _append_unique(quick_fixes, quick_fix)
    return {
        "result": result,
        "command": "sqlite-doctor",
        "schema_version": 1,
        "store_order": list(STORE_ORDER),
        "stores": stores,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": quick_fixes,
    }


def _usage() -> int:
    print("usage: /doctor sqlite [--json]")
    return 2


def _emit(report: dict[str, Any], json_output: bool) -> int:
    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] in {"PASS", "WARN"} else 1
    print("sqlite doctor")
    print("------------")
    for name in STORE_ORDER:
        store = report["stores"][name]
        print(f"- {name}: {store['result']} (path={store.get('path')})")
    if report["warnings"]:
        print("\nwarnings:")
        for warning in report["warnings"]:
            print(f"- {warning}")
    if report["problems"]:
        print("\nproblems:")
        for problem in report["problems"]:
            print(f"- {problem}")
    if report["quick_fixes"]:
        print("\nquick_fixes:")
        for quick_fix in report["quick_fixes"]:
            print(f"- {quick_fix}")
    print(f"\nresult: {report['result']}")
    return 0 if report["result"] in {"PASS", "WARN"} else 1


def main(argv: list[str]) -> int:
    if "--shared-memory-worker" in argv:
        limit_error = _apply_worker_memory_limit()
        report = (
            _child_failure_report(
                name="shared_memory",
                path=str(Path(DEFAULT_DB_PATH).expanduser()),
                failure=limit_error,
            )
            if limit_error
            else _inspect_shared_memory()
        )
        print(json.dumps(report, indent=2))
        return 0 if report["result"] in {"PASS", "WARN"} else 1
    json_output = "--json" in argv
    args = [item for item in argv if item != "--json"]
    if not args or args == ["run"]:
        return _emit(build_report(), json_output)
    if args in (["help"], ["-h"], ["--help"]):
        return _usage() - 2
    return _usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
