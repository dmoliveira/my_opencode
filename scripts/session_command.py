#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shlex
import sqlite3
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from session_metadata_index import SessionIndexError, load_session_index  # type: ignore


DEFAULT_INDEX_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SESSION_INDEX_PATH", "~/.config/opencode/sessions/index.json"
    )
).expanduser()

DEFAULT_DIGEST_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_DIGEST_PATH", "~/.config/opencode/digests/last-session.json"
    )
).expanduser()

def _runtime_db_candidates() -> list[Path]:
    configured = os.environ.get("MY_OPENCODE_RUNTIME_DB_PATH", "").strip()
    if configured:
        return [Path(configured).expanduser()]

    home = Path.home()
    candidates: list[Path] = []
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        candidates.append(Path(xdg_data_home).expanduser() / "opencode" / "opencode.db")
    candidates.append(home / ".local" / "share" / "opencode" / "opencode.db")

    if sys.platform == "darwin":
        candidates.insert(0, home / "Library" / "Application Support" / "opencode" / "opencode.db")
    elif sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        appdata = os.environ.get("APPDATA", "").strip()
        if local_appdata:
            candidates.insert(0, Path(local_appdata) / "opencode" / "opencode.db")
        if appdata:
            candidates.append(Path(appdata) / "opencode" / "opencode.db")

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.expanduser())
        if normalized and normalized not in seen:
            deduped.append(Path(normalized))
            seen.add(normalized)
    return deduped


def _default_runtime_db_path() -> Path:
    candidates = _runtime_db_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path("~/.local/share/opencode/opencode.db").expanduser()


DEFAULT_RUNTIME_DB_PATH = _default_runtime_db_path()
MAX_RUNTIME_STALE_FINDINGS = 100
RUNTIME_DB_SIZE_WARN_BYTES = max(
    1, int(os.environ.get("MY_OPENCODE_RUNTIME_DB_SIZE_WARN_BYTES", str(1024**3)))
)
RUNTIME_DB_SCAN_WARN_MS = max(
    1, int(os.environ.get("MY_OPENCODE_RUNTIME_DB_SCAN_WARN_MS", "1000"))
)
RUNTIME_DB_SCAN_TIMEOUT_MS = max(
    1, int(os.environ.get("MY_OPENCODE_RUNTIME_DB_SCAN_TIMEOUT_MS", "5000"))
)
RUNTIME_DB_BUSY_TIMEOUT_MS = min(5_000, RUNTIME_DB_SCAN_TIMEOUT_MS)
RUNTIME_DB_PROGRESS_OPCODES = 1_000

DEFAULT_STALE_SESSION_SECONDS = max(
    60,
    int(os.environ.get("MY_OPENCODE_STUCK_SESSION_THRESHOLD_SECONDS", "300") or "300"),
)

DEFAULT_GENERIC_STALE_PROBLEM_THRESHOLD = max(
    1,
    int(os.environ.get("MY_OPENCODE_GENERIC_STALE_PROBLEM_THRESHOLD", "25") or "25"),
)


def _usage() -> int:
    print(
        "usage: /session current [--json] | /session list [--limit <n>] [--json] | /session show <id> [--json] "
        "| /session search <query> [--limit <n>] [--json] | /session handoff [--id <session_id>] [--launch-cwd <path>] [--fork] [--json] | /session doctor [--db-path <path>] [--stale-seconds <n>] [--generic-stale-problem-threshold <n>] [--json] | /session repair-stale [--db-path <path>] [--stale-seconds <n>] [--session-id <id>] [--include-generic --confirm-generic] [--apply] [--json]"
    )
    return 2


def _parse_limit(argv: list[str], default: int = 10) -> int:
    if "--limit" not in argv:
        return default
    idx = argv.index("--limit")
    if idx + 1 >= len(argv):
        raise ValueError("missing limit value")
    try:
        return max(1, int(argv[idx + 1]))
    except ValueError as exc:
        raise ValueError("invalid limit value") from exc


def _parse_positive_int_option(argv: list[str], name: str, default: int) -> int:
    if name not in argv:
        return default
    idx = argv.index(name)
    if idx + 1 >= len(argv):
        raise ValueError(f"missing value for {name}")
    try:
        value = int(argv[idx + 1])
    except ValueError as exc:
        raise ValueError(f"invalid value for {name}") from exc
    if value <= 0:
        raise ValueError(f"invalid value for {name}")
    return value


def _parse_text_option(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    idx = argv.index(name)
    if idx + 1 >= len(argv) or not argv[idx + 1].strip():
        raise ValueError(f"missing value for {name}")
    return argv[idx + 1]


def _parse_path_option(argv: list[str], name: str, default: Path) -> Path:
    if name not in argv:
        return default
    idx = argv.index(name)
    if idx + 1 >= len(argv):
        raise ValueError(f"missing value for {name}")
    return Path(argv[idx + 1]).expanduser()


def _load_index(path: Path) -> dict:
    return load_session_index(path)


def _index_failure_fields(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, SessionIndexError):
        fields: dict[str, Any] = {
            "reason_code": exc.reason_code,
            "error": str(exc),
        }
        if exc.corruption_kind:
            fields["corruption_kind"] = exc.corruption_kind
        return fields
    return {
        "reason_code": "session_index_unavailable",
        "error": "session index is unavailable",
    }


def _session_row_timestamp_sort_key(row: dict) -> tuple[bool, float]:
    value = row.get("last_event_at")
    if not isinstance(value, str) or not value:
        return (False, 0.0)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return (False, 0.0)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (True, parsed.timestamp())


def _session_rows(index: dict) -> list[dict]:
    rows: list[dict] = []
    for item in index.get("sessions", []):
        if isinstance(item, dict):
            rows.append(item)
    rows.sort(key=_session_row_timestamp_sort_key, reverse=True)
    return rows


def _stale_cause_details(finding: dict) -> tuple[str, str]:
    issue_type = str(finding.get("issue_type") or "")
    if issue_type == "parent_child_mismatch":
        return (
            "child_completed_parent_tool_still_running",
            "delegated child finished, but the parent task tool still appears to be running",
        )
    if issue_type == "silent_parent_after_delegation_abort":
        return (
            "delegated_abort_not_reconciled_to_parent_text",
            "delegated child finished with parent abort/error state, but no parent text completion/recovery was recorded",
        )
    if issue_type == "stale_delegated_child_runtime_recovery_missed":
        return (
            "delegated_child_still_active_without_parent_recovery",
            "delegated child is still stale and incomplete while the parent task tool remains running",
        )
    if issue_type == "stale_running_tool":
        last_tool = str(finding.get("last_tool") or "")
        if last_tool == "question":
            return (
                "question_lifecycle_not_closed",
                "question tool is still marked running after the session went stale, suggesting the reply/cleanup path did not close it",
            )
        if last_tool == "apply_patch":
            return (
                "apply_patch_lifecycle_not_closed",
                "apply_patch tool is still marked running after the session went stale, suggesting the completion/error path did not close it",
            )
        return (
            "running_tool_not_closed",
            "a running tool remained open after the session went stale",
        )
    if issue_type == "generic_stale_incomplete_assistant":
        last_part_type = str(finding.get("last_part_type") or "none")
        if last_part_type == "step-start":
            return (
                "assistant_step_started_without_terminal_message",
                "assistant started a step but never recorded a terminal completion or error for the message",
            )
        if last_part_type == "text":
            return (
                "assistant_text_emitted_without_terminal_message",
                "assistant emitted text but never recorded a terminal completion or error for the message",
            )
        if last_part_type == "tool":
            return (
                "assistant_tool_state_left_incomplete",
                "assistant last recorded a tool-related part, but the message never reached a terminal completion or error",
            )
        if last_part_type == "none":
            return (
                "assistant_message_missing_parts_or_terminal_state",
                "assistant message has no terminal completion/error and no final part was recorded",
            )
        return (
            "assistant_incomplete_without_terminal_state",
            "assistant message never reached a terminal completion or error state",
        )
    return (
        "unknown_stale_cause",
        "session appears stale, but no specialized stale-cause summary is available",
    )


def _annotate_stale_findings(findings: list[dict]) -> list[dict]:
    annotated: list[dict] = []
    for finding in findings:
        item = dict(finding)
        cause_code, cause_summary = _stale_cause_details(item)
        item["stale_cause_code"] = cause_code
        item["stale_cause_summary"] = cause_summary
        annotated.append(item)
    return annotated


def _emit(payload: dict, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1
    command = payload.get("command")
    if payload.get("redacted") is True and command in {"search", "handoff"}:
        if payload.get("result") != "PASS":
            print(f"error_code: {payload.get('error_code', 'session_redacted_failure')}")
            return 1
        print(f"session {command} (redacted)")
        print("--------------------------")
        if command == "search":
            print(f"count: {payload.get('count', 0)}")
            for row in payload.get("sessions", []):
                print(
                    "- "
                    f"started={row.get('started_at')} "
                    f"last={row.get('last_event_at')} "
                    f"events={row.get('event_count')}"
                )
        else:
            print(f"started_at: {payload.get('started_at')}")
            print(f"last_event_at: {payload.get('last_event_at')}")
            print(f"event_count: {payload.get('event_count')}")
        return 0
    if payload.get("result") != "PASS" and command not in {
        "doctor",
        "repair-stale",
    }:
        print("result: FAIL")
        if payload.get("reason_code"):
            print(f"reason_code: {payload.get('reason_code')}")
        print(f"error: {payload.get('error', 'session command failed')}")
        return 1
    if payload.get("command") == "current":
        row = payload.get("session", {})
        print(f"session_id: {row.get('session_id')}")
        print(f"source: {payload.get('source')}")
        if row.get("cwd"):
            print(f"cwd: {row.get('cwd')}")
        if row.get("last_event_at"):
            print(f"last_event_at: {row.get('last_event_at')}")
        return 0
    if payload.get("command") == "list":
        print(f"index: {payload.get('index_path')}")
        print(f"count: {payload.get('count')}")
        for row in payload.get("sessions", []):
            print(
                f"- {row.get('session_id')} | last={row.get('last_event_at')} "
                f"| reason={row.get('last_reason')} | events={row.get('event_count')}"
            )
        return 0
    if payload.get("command") == "show":
        row = payload.get("session", {})
        print(f"session_id: {row.get('session_id')}")
        print(f"cwd: {row.get('cwd')}")
        print(f"started_at: {row.get('started_at')}")
        print(f"last_event_at: {row.get('last_event_at')}")
        print(f"event_count: {row.get('event_count')}")
        print(f"last_reason: {row.get('last_reason')}")
        return 0
    if payload.get("command") == "search":
        print(f"query: {payload.get('query')}")
        print(f"count: {payload.get('count')}")
        for row in payload.get("sessions", []):
            print(
                f"- {row.get('session_id')} | last={row.get('last_event_at')} "
                f"| reason={row.get('last_reason')}"
            )
        return 0
    if payload.get("command") == "doctor":
        print("session doctor")
        print("--------------")
        print(f"index: {payload.get('index_path')}")
        if payload.get("runtime_db_path"):
            print(f"runtime_db: {payload.get('runtime_db_path')}")
        print(f"exists: {'yes' if payload.get('exists') else 'no'}")
        if payload.get("reason_code"):
            print(f"reason_code: {payload.get('reason_code')}")
        if payload.get("error"):
            print(f"error: {payload.get('error')}")
        if payload.get("warnings"):
            print("warnings:")
            for warning in payload.get("warnings", []):
                print(f"- {warning}")
        if payload.get("problems"):
            print("problems:")
            for problem in payload.get("problems", []):
                print(f"- {problem}")
        findings = payload.get("stuck_findings") or []
        if findings:
            print("stuck_findings:")
            for finding in findings[:10]:
                issue_type = str(finding.get("issue_type") or "stuck")
                cause_summary = str(finding.get("stale_cause_summary") or "unknown")
                if issue_type == "parent_child_mismatch":
                    print(
                        "- "
                        f"type={issue_type} parent={finding.get('parent_session_id')} "
                        f"child={finding.get('child_session_id')} "
                        f"age={finding.get('parent_stale_seconds')}s "
                        f"parent_tool={finding.get('parent_last_tool') or 'none'} "
                        f"child_state={finding.get('child_state')} "
                        f"cause={cause_summary}"
                    )
                elif issue_type == "stale_delegated_child_runtime_recovery_missed":
                    print(
                        "- "
                        f"type={issue_type} parent={finding.get('parent_session_id')} "
                        f"child={finding.get('child_session_id')} "
                        f"parent_age={finding.get('parent_stale_seconds')}s "
                        f"child_age={finding.get('child_stale_seconds')}s "
                        f"child_last_part={finding.get('child_last_part_type') or 'none'} "
                        f"cause={cause_summary}"
                    )
                else:
                    print(
                        "- "
                        f"type={issue_type} session={finding.get('session_id')} "
                        f"age={finding.get('stale_seconds')}s "
                        f"tool={finding.get('last_tool') or 'none'} "
                        f"status={finding.get('last_tool_status') or 'unknown'} "
                        f"cause={cause_summary}"
                    )
        generic_findings = payload.get("generic_stale_findings") or []
        if generic_findings:
            print("generic_stale_findings:")
            for finding in generic_findings[:10]:
                print(
                    "- "
                    f"type={finding.get('issue_type') or 'generic_stale'} "
                    f"session={finding.get('session_id')} "
                    f"age={finding.get('stale_seconds')}s "
                    f"last_part={finding.get('last_part_type') or 'none'} "
                    f"cause={finding.get('stale_cause_summary') or 'unknown'}"
                )
        print(f"result: {payload.get('result')}")
        return 0 if payload.get("result") == "PASS" else 1
    if payload.get("command") == "repair-stale":
        print("session repair-stale")
        print("--------------------")
        print(f"runtime_db: {payload.get('runtime_db_path')}")
        print(f"stale_seconds: {payload.get('stale_seconds')}")
        print(f"apply: {'yes' if payload.get('apply') else 'no'}")
        print(f"include_generic: {'yes' if payload.get('include_generic') else 'no'}")
        if payload.get("warnings"):
            print("warnings:")
            for warning in payload.get("warnings", []):
                print(f"- {warning}")
        if payload.get("problems"):
            print("problems:")
            for problem in payload.get("problems", []):
                print(f"- {problem}")
        print(f"candidate_count: {payload.get('candidate_count', 0)}")
        print(f"repaired_count: {payload.get('repaired_count', 0)}")
        for item in payload.get("repairs", [])[:10]:
            print(
                "- "
                f"type={item.get('issue_type')} "
                f"session={item.get('session_id') or item.get('parent_session_id')} "
                f"tool={item.get('tool') or item.get('parent_last_tool') or 'none'}"
            )
        if payload.get("quick_fixes"):
            print("quick_fixes:")
            for fix in payload.get("quick_fixes", []):
                print(f"- {fix}")
        print(f"result: {payload.get('result')}")
        return 0 if payload.get("result") == "PASS" else 1
    if payload.get("command") == "handoff":
        print("session handoff")
        print("---------------")
        print(f"session_id: {payload.get('session_id')}")
        print(f"cwd: {payload.get('cwd')}")
        if payload.get("launch_cwd"):
            print(f"launch_cwd: {payload.get('launch_cwd')}")
        print(f"last_event_at: {payload.get('last_event_at')}")
        print(f"event_count: {payload.get('event_count')}")
        print(f"last_reason: {payload.get('last_reason')}")
        if payload.get("git_branch"):
            print(f"git_branch: {payload.get('git_branch')}")
        if payload.get("launch_command"):
            print(f"launch_command: {payload.get('launch_command')}")
        if payload.get("resume_command"):
            print(f"resume_command: {payload.get('resume_command')}")
        if isinstance(payload.get("next_actions"), list) and payload.get(
            "next_actions"
        ):
            print("next_actions:")
            for action in payload.get("next_actions", []):
                print(f"- {action}")
        return 0
    return 0


def _load_digest(path: Path) -> dict:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _connect_runtime_database_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the upstream runtime history without creating or modifying it."""
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute(f"PRAGMA busy_timeout = {RUNTIME_DB_BUSY_TIMEOUT_MS}")
    return connection


class _RuntimeScanBudget:
    def __init__(self, timeout_ms: int) -> None:
        self.deadline = time.monotonic() + (max(1, timeout_ms) / 1000.0)
        self.timed_out = False

    def progress(self) -> int:
        if time.monotonic() < self.deadline:
            return 0
        self.timed_out = True
        return 1




_INDEXED_PARENT_CHILD_FROM_SQL = """
    FROM session p
    JOIN session c ON c.parent_id = p.id
    JOIN message pm ON pm.id = (
      SELECT latest_parent.id
      FROM message latest_parent
      WHERE latest_parent.session_id = p.id
      ORDER BY latest_parent.time_created DESC, latest_parent.id DESC
      LIMIT 1
    )
    LEFT JOIN part pp ON pp.id = (
      SELECT latest_parent_part.id
      FROM part latest_parent_part
      WHERE latest_parent_part.message_id = pm.id
      ORDER BY latest_parent_part.time_created DESC, latest_parent_part.id DESC
      LIMIT 1
    )
    LEFT JOIN message cm ON cm.id = (
      SELECT latest_child.id
      FROM message latest_child
      WHERE latest_child.session_id = c.id
      ORDER BY latest_child.time_created DESC, latest_child.id DESC
      LIMIT 1
    )
    LEFT JOIN part cp ON cp.id = (
      SELECT latest_child_part.id
      FROM part latest_child_part
      WHERE latest_child_part.message_id = cm.id
      ORDER BY latest_child_part.time_created DESC, latest_child_part.id DESC
      LIMIT 1
    )
    WHERE p.time_updated <= ?
      AND c.time_updated <= ?
"""

_INDEXED_PARENT_CHILD_SELECT_SQL = """
    SELECT
      p.id AS parent_session_id,
      pm.id AS parent_message_id,
      pp.id AS parent_part_id,
      p.title AS parent_title,
      c.id AS child_session_id,
      cm.id AS child_message_id,
      c.title AS child_title,
      p.time_updated AS parent_time_updated,
      c.time_updated AS child_time_updated,
      CAST(((_runtime_scan_now_ms() - p.time_updated) / 1000) AS INT) AS parent_stale_seconds,
      CAST(((_runtime_scan_now_ms() - c.time_updated) / 1000) AS INT) AS child_stale_seconds,
      COALESCE(json_extract(pp.data,'$.type'),'none') AS parent_last_part_type,
      COALESCE(json_extract(pp.data,'$.tool'),'') AS parent_last_tool,
      COALESCE(json_extract(pp.data,'$.state.status'),'') AS parent_last_tool_status,
      COALESCE(
        json_extract(pm.data,'$.error.message'),
        json_extract(pm.data,'$.error.data.message'),
        ''
      ) AS parent_error_message,
      COALESCE(json_extract(cp.data,'$.type'),'none') AS child_last_part_type,
      COALESCE(json_extract(cp.data,'$.tool'),'') AS child_last_tool,
      COALESCE(json_extract(cp.data,'$.state.status'),'') AS child_last_tool_status,
      CASE
        WHEN json_extract(cm.data,'$.time.completed') IS NOT NULL THEN 'completed'
        WHEN json_extract(cm.data,'$.error') IS NOT NULL THEN 'failed'
        ELSE 'active_or_unknown'
      END AS child_state
"""

_INDEXED_SINGLE_SESSION_FROM_SQL = """
    FROM session s
    JOIN message m ON m.id = (
      SELECT latest_message.id
      FROM message latest_message
      WHERE latest_message.session_id = s.id
      ORDER BY latest_message.time_created DESC, latest_message.id DESC
      LIMIT 1
    )
    LEFT JOIN part p ON p.id = (
      SELECT latest_part.id
      FROM part latest_part
      WHERE latest_part.message_id = m.id
      ORDER BY latest_part.time_created DESC, latest_part.id DESC
      LIMIT 1
    )
    WHERE s.time_updated <= ?
"""

_INDEXED_GENERIC_WHERE_SQL = """
      AND json_extract(m.data,'$.role') = 'assistant'
      AND json_extract(m.data,'$.time.completed') IS NULL
      AND json_extract(m.data,'$.error') IS NULL
      AND s.parent_id IS NULL
      AND NOT EXISTS (
        SELECT 1
        FROM session child
        WHERE child.parent_id = s.id
      )
      AND NOT (
        COALESCE(json_extract(p.data,'$.type'),'') = 'tool'
        AND COALESCE(json_extract(p.data,'$.state.status'),'') = 'running'
        AND COALESCE(json_extract(p.data,'$.tool'),'') IN ('question', 'apply_patch')
      )
"""

INDEXED_RUNTIME_STALE_SESSION_QUERIES = {
    "parent_child_mismatch": f"""
        {_INDEXED_PARENT_CHILD_SELECT_SQL}
        {_INDEXED_PARENT_CHILD_FROM_SQL}
          AND json_extract(pm.data,'$.role') = 'assistant'
          AND json_extract(pm.data,'$.time.completed') IS NULL
          AND COALESCE(json_extract(pp.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(pp.data,'$.tool'),'') = 'task'
          AND COALESCE(json_extract(pp.data,'$.state.status'),'') = 'running'
          AND c.time_updated > p.time_updated
          AND (
            json_extract(cm.data,'$.time.completed') IS NOT NULL
            OR json_extract(cm.data,'$.error') IS NOT NULL
          )
        ORDER BY p.time_updated DESC, p.id DESC, c.id DESC
        LIMIT 20
    """,
    "silent_parent_after_delegation_abort": f"""
        {_INDEXED_PARENT_CHILD_SELECT_SQL}
        {_INDEXED_PARENT_CHILD_FROM_SQL}
          AND json_extract(pm.data,'$.role') = 'assistant'
          AND json_extract(pm.data,'$.error') IS NOT NULL
          AND (
            COALESCE(json_extract(pm.data,'$.error.name'),'') = 'MessageAbortedError'
            OR COALESCE(
              json_extract(pm.data,'$.error.data.message'),
              json_extract(pm.data,'$.error.message'),
              ''
            ) = 'The operation was aborted.'
          )
          AND COALESCE(json_extract(pp.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(pp.data,'$.tool'),'') = 'task'
          AND COALESCE(json_extract(pp.data,'$.state.status'),'') IN ('error', 'failed')
          AND NOT EXISTS (
            SELECT 1
            FROM part parent_text
            WHERE parent_text.message_id = pm.id
              AND COALESCE(json_extract(parent_text.data,'$.type'),'') = 'text'
          )
          AND (
            json_extract(cm.data,'$.time.completed') IS NOT NULL
            OR json_extract(cm.data,'$.error') IS NOT NULL
          )
        ORDER BY p.time_updated DESC, p.id DESC, c.id DESC
        LIMIT 20
    """,
    "stale_delegated_child_runtime_recovery_missed": f"""
        {_INDEXED_PARENT_CHILD_SELECT_SQL}
        {_INDEXED_PARENT_CHILD_FROM_SQL}
          AND json_extract(pm.data,'$.role') = 'assistant'
          AND json_extract(pm.data,'$.time.completed') IS NULL
          AND COALESCE(json_extract(pp.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(pp.data,'$.tool'),'') = 'task'
          AND COALESCE(json_extract(pp.data,'$.state.status'),'') = 'running'
          AND json_extract(cm.data,'$.role') = 'assistant'
          AND json_extract(cm.data,'$.time.completed') IS NULL
          AND json_extract(cm.data,'$.error') IS NULL
          AND c.time_updated > p.time_updated
        ORDER BY p.time_updated DESC, p.id DESC, c.id DESC
        LIMIT 20
    """,
    "stale_running_tool": f"""
        SELECT
          s.id AS session_id,
          m.id AS message_id,
          p.id AS part_id,
          s.title AS session_title,
          s.time_updated AS session_time_updated,
          CAST(((_runtime_scan_now_ms() - s.time_updated) / 1000) AS INT) AS stale_seconds,
          COALESCE(json_extract(p.data,'$.type'),'none') AS last_part_type,
          COALESCE(json_extract(p.data,'$.tool'),'') AS last_tool,
          COALESCE(json_extract(p.data,'$.state.status'),'') AS last_tool_status
        {_INDEXED_SINGLE_SESSION_FROM_SQL}
          AND json_extract(m.data,'$.role') = 'assistant'
          AND json_extract(m.data,'$.time.completed') IS NULL
          AND COALESCE(json_extract(p.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(p.data,'$.state.status'),'') = 'running'
          AND COALESCE(json_extract(p.data,'$.tool'),'') IN ('question', 'apply_patch')
        ORDER BY s.time_updated DESC, s.id DESC
        LIMIT 20
    """,
    "generic_stale_rows": f"""
        SELECT
          s.id AS session_id,
          m.id AS message_id,
          p.id AS part_id,
          s.title AS session_title,
          s.time_updated AS session_time_updated,
          CAST(((_runtime_scan_now_ms() - s.time_updated) / 1000) AS INT) AS stale_seconds,
          COALESCE(json_extract(p.data,'$.type'),'none') AS last_part_type,
          COALESCE(json_extract(p.data,'$.tool'),'') AS last_tool,
          COALESCE(json_extract(p.data,'$.state.status'),'') AS last_tool_status
        {_INDEXED_SINGLE_SESSION_FROM_SQL}
        {_INDEXED_GENERIC_WHERE_SQL}
        ORDER BY s.time_updated DESC, s.id DESC
        LIMIT 20
    """,
    "generic_stale_count": f"""
        SELECT COUNT(*)
        {_INDEXED_SINGLE_SESSION_FROM_SQL}
        {_INDEXED_GENERIC_WHERE_SQL}
    """,
}

REQUIRED_RUNTIME_INDEX_PREFIXES: dict[str, tuple[str, ...]] = {
    "session": ("parent_id",),
    "message": ("session_id", "time_created", "id"),
    "part": ("message_id",),
}


def _runtime_index_columns(
    conn: sqlite3.Connection, table: str
) -> dict[str, list[str]]:
    indexes: dict[str, list[str]] = {}
    for row in conn.execute(f"PRAGMA index_list({table})"):
        index_name = str(row[1])
        quoted_name = index_name.replace('"', '""')
        indexes[index_name] = [
            str(index_row[2])
            for index_row in conn.execute(f'PRAGMA index_info("{quoted_name}")')
        ]
    return indexes


def _has_index_prefix(
    indexes: dict[str, list[str]], required_prefix: tuple[str, ...]
) -> bool:
    return any(
        tuple(columns[: len(required_prefix)]) == required_prefix
        for columns in indexes.values()
    )


def _missing_runtime_index_prefixes(
    index_columns: dict[str, dict[str, list[str]]],
) -> list[str]:
    return [
        f"{table}({','.join(prefix)})"
        for table, prefix in REQUIRED_RUNTIME_INDEX_PREFIXES.items()
        if not _has_index_prefix(index_columns.get(table, {}), prefix)
    ]


def _scan_runtime_stuck_sessions_indexed_queries(
    conn: sqlite3.Connection,
    *,
    stale_seconds: int,
    now_ms: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    cutoff_ms = now_ms - stale_seconds * 1000
    parent_params = (cutoff_ms, cutoff_ms)

    def bounded_rows(
        query_name: str,
        params: tuple[int, ...],
        *,
        drop: tuple[str, ...] = (),
        issue_type: str | None = None,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for row in conn.execute(
            INDEXED_RUNTIME_STALE_SESSION_QUERIES[query_name], params
        ).fetchall():
            item = dict(row)
            for key in drop:
                item.pop(key, None)
            item["issue_type"] = issue_type or query_name
            output.append(item)
        return output

    parent_child = bounded_rows(
        "parent_child_mismatch",
        parent_params,
        drop=("parent_error_message", "child_last_tool", "child_last_tool_status"),
    )
    silent_abort = bounded_rows(
        "silent_parent_after_delegation_abort",
        parent_params,
        drop=("child_last_tool", "child_last_tool_status"),
    )
    stale_delegated_child = bounded_rows(
        "stale_delegated_child_runtime_recovery_missed",
        parent_params,
        drop=("parent_error_message",),
    )
    stale_tool = bounded_rows("stale_running_tool", (cutoff_ms,))
    generic_stale_findings = bounded_rows(
        "generic_stale_rows",
        (cutoff_ms,),
        issue_type="generic_stale_incomplete_assistant",
    )
    generic_stale_count = int(
        conn.execute(
            INDEXED_RUNTIME_STALE_SESSION_QUERIES["generic_stale_count"],
            (cutoff_ms,),
        ).fetchone()[0]
    )
    findings = parent_child + silent_abort + stale_delegated_child + stale_tool
    return findings, generic_stale_findings, generic_stale_count


def _scan_runtime_stuck_sessions_legacy_queries(
    conn: sqlite3.Connection,
    stale_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    findings: list[dict[str, Any]] = []
    generic_stale_findings: list[dict[str, Any]] = []
    parent_child_rows = conn.execute(
        """
        WITH parent_last_msg AS (
          SELECT id, session_id FROM (
            SELECT id, session_id,
              ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY time_created DESC, id DESC) AS row_number
            FROM message
          ) WHERE row_number = 1
        ),
        child_last_msg AS (
          SELECT id, session_id FROM (
            SELECT id, session_id,
              ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY time_created DESC, id DESC) AS row_number
            FROM message
          ) WHERE row_number = 1
        )
        SELECT
          p.id AS parent_session_id,
          pm.id AS parent_message_id,
          pp.id AS parent_part_id,
          p.title AS parent_title,
          c.id AS child_session_id,
          cm.id AS child_message_id,
          c.title AS child_title,
          p.time_updated AS parent_time_updated,
          c.time_updated AS child_time_updated,
          CAST(((_runtime_scan_now_ms() - p.time_updated) / 1000) AS INT) AS parent_stale_seconds,
          CAST(((_runtime_scan_now_ms() - c.time_updated) / 1000) AS INT) AS child_stale_seconds,
          COALESCE(json_extract(pp.data,'$.type'),'none') AS parent_last_part_type,
          COALESCE(json_extract(pp.data,'$.tool'),'') AS parent_last_tool,
          COALESCE(json_extract(pp.data,'$.state.status'),'') AS parent_last_tool_status,
          COALESCE(json_extract(cp.data,'$.type'),'none') AS child_last_part_type,
          CASE
            WHEN json_extract(cm.data,'$.time.completed') IS NOT NULL THEN 'completed'
            WHEN json_extract(cm.data,'$.error') IS NOT NULL THEN 'failed'
            ELSE 'active_or_unknown'
          END AS child_state
        FROM session p
        JOIN session c ON c.parent_id = p.id
        JOIN parent_last_msg plm ON plm.session_id = p.id
        JOIN message pm ON pm.id = plm.id
        LEFT JOIN part pp ON pp.id = (
          SELECT id FROM part WHERE message_id = pm.id ORDER BY time_created DESC, id DESC LIMIT 1
        )
        LEFT JOIN child_last_msg clm ON clm.session_id = c.id
        LEFT JOIN message cm ON cm.id = clm.id
        LEFT JOIN part cp ON cp.id = (
          SELECT id FROM part WHERE message_id = cm.id ORDER BY time_created DESC, id DESC LIMIT 1
        )
        WHERE json_extract(pm.data,'$.role') = 'assistant'
          AND json_extract(pm.data,'$.time.completed') IS NULL
          AND p.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND c.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND COALESCE(json_extract(pp.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(pp.data,'$.tool'),'') = 'task'
          AND COALESCE(json_extract(pp.data,'$.state.status'),'') = 'running'
          AND c.time_updated > p.time_updated
          AND (
            json_extract(cm.data,'$.time.completed') IS NOT NULL
            OR json_extract(cm.data,'$.error') IS NOT NULL
          )
        ORDER BY p.time_updated DESC
        LIMIT 20
        """,
        (stale_seconds, stale_seconds),
    ).fetchall()
    for row in parent_child_rows:
        item = dict(row)
        item["issue_type"] = "parent_child_mismatch"
        findings.append(item)

    silent_abort_rows = conn.execute(
        """
        WITH parent_last_msg AS (
          SELECT session_id, MAX(time_created) AS max_time FROM message GROUP BY session_id
        ),
        child_last_msg AS (
          SELECT session_id, MAX(time_created) AS max_time FROM message GROUP BY session_id
        )
        SELECT
          p.id AS parent_session_id,
          pm.id AS parent_message_id,
          pp.id AS parent_part_id,
          p.title AS parent_title,
          c.id AS child_session_id,
          cm.id AS child_message_id,
          c.title AS child_title,
          p.time_updated AS parent_time_updated,
          c.time_updated AS child_time_updated,
          CAST(((_runtime_scan_now_ms() - p.time_updated) / 1000) AS INT) AS parent_stale_seconds,
          CAST(((_runtime_scan_now_ms() - c.time_updated) / 1000) AS INT) AS child_stale_seconds,
          COALESCE(json_extract(pp.data,'$.type'),'none') AS parent_last_part_type,
          COALESCE(json_extract(pp.data,'$.tool'),'') AS parent_last_tool,
          COALESCE(json_extract(pp.data,'$.state.status'),'') AS parent_last_tool_status,
          COALESCE(
            json_extract(pm.data,'$.error.message'),
            json_extract(pm.data,'$.error.data.message'),
            ''
          ) AS parent_error_message,
          COALESCE(json_extract(cp.data,'$.type'),'none') AS child_last_part_type,
          CASE
            WHEN json_extract(cm.data,'$.time.completed') IS NOT NULL THEN 'completed'
            WHEN json_extract(cm.data,'$.error') IS NOT NULL THEN 'failed'
            ELSE 'active_or_unknown'
          END AS child_state
        FROM session p
        JOIN session c ON c.parent_id = p.id
        JOIN parent_last_msg plm ON plm.session_id = p.id
        JOIN message pm ON pm.session_id = p.id AND pm.time_created = plm.max_time
        LEFT JOIN part pp ON pp.message_id = pm.id AND pp.time_created = (
          SELECT MAX(time_created) FROM part WHERE message_id = pm.id
        )
        LEFT JOIN child_last_msg clm ON clm.session_id = c.id
        LEFT JOIN message cm ON cm.session_id = c.id AND cm.time_created = clm.max_time
        LEFT JOIN part cp ON cp.message_id = cm.id AND cp.time_created = (
          SELECT MAX(time_created) FROM part WHERE message_id = cm.id
        )
        WHERE json_extract(pm.data,'$.role') = 'assistant'
          AND json_extract(pm.data,'$.error') IS NOT NULL
          AND (
            COALESCE(json_extract(pm.data,'$.error.name'),'') = 'MessageAbortedError'
            OR COALESCE(
              json_extract(pm.data,'$.error.data.message'),
              json_extract(pm.data,'$.error.message'),
              ''
            ) = 'The operation was aborted.'
          )
          AND p.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND c.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND COALESCE(json_extract(pp.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(pp.data,'$.tool'),'') = 'task'
          AND COALESCE(json_extract(pp.data,'$.state.status'),'') IN ('error', 'failed')
          AND NOT EXISTS (
            SELECT 1
            FROM part ptext
            WHERE ptext.message_id = pm.id
              AND COALESCE(json_extract(ptext.data,'$.type'),'') = 'text'
          )
          AND (
            json_extract(cm.data,'$.time.completed') IS NOT NULL
            OR json_extract(cm.data,'$.error') IS NOT NULL
          )
        ORDER BY p.time_updated DESC
        LIMIT 20
        """,
        (stale_seconds, stale_seconds),
    ).fetchall()
    for row in silent_abort_rows:
        item = dict(row)
        item["issue_type"] = "silent_parent_after_delegation_abort"
        findings.append(item)

    stale_delegated_child_rows = conn.execute(
        """
        WITH parent_last_msg AS (
          SELECT session_id, MAX(time_created) AS max_time FROM message GROUP BY session_id
        ),
        child_last_msg AS (
          SELECT session_id, MAX(time_created) AS max_time FROM message GROUP BY session_id
        )
        SELECT
          p.id AS parent_session_id,
          pm.id AS parent_message_id,
          pp.id AS parent_part_id,
          p.title AS parent_title,
          c.id AS child_session_id,
          cm.id AS child_message_id,
          c.title AS child_title,
          p.time_updated AS parent_time_updated,
          c.time_updated AS child_time_updated,
          CAST(((_runtime_scan_now_ms() - p.time_updated) / 1000) AS INT) AS parent_stale_seconds,
          CAST(((_runtime_scan_now_ms() - c.time_updated) / 1000) AS INT) AS child_stale_seconds,
          COALESCE(json_extract(pp.data,'$.type'),'none') AS parent_last_part_type,
          COALESCE(json_extract(pp.data,'$.tool'),'') AS parent_last_tool,
          COALESCE(json_extract(pp.data,'$.state.status'),'') AS parent_last_tool_status,
          COALESCE(json_extract(cp.data,'$.type'),'none') AS child_last_part_type,
          COALESCE(json_extract(cp.data,'$.tool'),'') AS child_last_tool,
          COALESCE(json_extract(cp.data,'$.state.status'),'') AS child_last_tool_status,
          CASE
            WHEN json_extract(cm.data,'$.time.completed') IS NOT NULL THEN 'completed'
            WHEN json_extract(cm.data,'$.error') IS NOT NULL THEN 'failed'
            ELSE 'active_or_unknown'
          END AS child_state
        FROM session p
        JOIN session c ON c.parent_id = p.id
        JOIN parent_last_msg plm ON plm.session_id = p.id
        JOIN message pm ON pm.session_id = p.id AND pm.time_created = plm.max_time
        LEFT JOIN part pp ON pp.message_id = pm.id AND pp.time_created = (
          SELECT MAX(time_created) FROM part WHERE message_id = pm.id
        )
        JOIN child_last_msg clm ON clm.session_id = c.id
        JOIN message cm ON cm.session_id = c.id AND cm.time_created = clm.max_time
        LEFT JOIN part cp ON cp.message_id = cm.id AND cp.time_created = (
          SELECT MAX(time_created) FROM part WHERE message_id = cm.id
        )
        WHERE json_extract(pm.data,'$.role') = 'assistant'
          AND json_extract(pm.data,'$.time.completed') IS NULL
          AND p.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND c.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND COALESCE(json_extract(pp.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(pp.data,'$.tool'),'') = 'task'
          AND COALESCE(json_extract(pp.data,'$.state.status'),'') = 'running'
          AND json_extract(cm.data,'$.role') = 'assistant'
          AND json_extract(cm.data,'$.time.completed') IS NULL
          AND json_extract(cm.data,'$.error') IS NULL
          AND c.time_updated > p.time_updated
        ORDER BY p.time_updated DESC
        LIMIT 20
        """,
        (stale_seconds, stale_seconds),
    ).fetchall()
    for row in stale_delegated_child_rows:
        item = dict(row)
        item["issue_type"] = "stale_delegated_child_runtime_recovery_missed"
        findings.append(item)

    stale_tool_rows = conn.execute(
        """
        WITH last_msg AS (
          SELECT session_id, MAX(time_created) AS max_time FROM message GROUP BY session_id
        )
        SELECT
          s.id AS session_id,
          m.id AS message_id,
          p.id AS part_id,
          s.title AS session_title,
          s.time_updated AS session_time_updated,
          CAST(((_runtime_scan_now_ms() - s.time_updated) / 1000) AS INT) AS stale_seconds,
          COALESCE(json_extract(p.data,'$.type'),'none') AS last_part_type,
          COALESCE(json_extract(p.data,'$.tool'),'') AS last_tool,
          COALESCE(json_extract(p.data,'$.state.status'),'') AS last_tool_status
        FROM session s
        JOIN last_msg lm ON lm.session_id = s.id
        JOIN message m ON m.session_id = s.id AND m.time_created = lm.max_time
        LEFT JOIN part p ON p.message_id = m.id AND p.time_created = (
          SELECT MAX(time_created) FROM part WHERE message_id = m.id
        )
        WHERE json_extract(m.data,'$.role') = 'assistant'
          AND json_extract(m.data,'$.time.completed') IS NULL
          AND s.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND COALESCE(json_extract(p.data,'$.type'),'') = 'tool'
          AND COALESCE(json_extract(p.data,'$.state.status'),'') = 'running'
          AND COALESCE(json_extract(p.data,'$.tool'),'') IN ('question', 'apply_patch')
        ORDER BY s.time_updated DESC
        LIMIT 20
        """,
        (stale_seconds,),
    ).fetchall()
    for row in stale_tool_rows:
        item = dict(row)
        item["issue_type"] = "stale_running_tool"
        findings.append(item)

    generic_stale_with_sql = """
        WITH last_msg AS (
          SELECT session_id, MAX(time_created) AS max_time FROM message GROUP BY session_id
        ),
        last_part AS (
          SELECT message_id, MAX(time_created) AS max_time FROM part GROUP BY message_id
        )
    """
    generic_stale_from_sql = """
        FROM session s
        JOIN last_msg lm ON lm.session_id = s.id
        JOIN message m ON m.session_id = s.id AND m.time_created = lm.max_time
        LEFT JOIN last_part lp ON lp.message_id = m.id
        LEFT JOIN part p ON p.message_id = m.id AND p.time_created = lp.max_time
        WHERE json_extract(m.data,'$.role') = 'assistant'
          AND json_extract(m.data,'$.time.completed') IS NULL
          AND json_extract(m.data,'$.error') IS NULL
          AND s.parent_id IS NULL
          AND s.time_updated <= (_runtime_scan_now_ms() - (? * 1000))
          AND NOT EXISTS (
            SELECT 1
            FROM session c
            WHERE c.parent_id = s.id
          )
          AND NOT (
            COALESCE(json_extract(p.data,'$.type'),'') = 'tool'
            AND COALESCE(json_extract(p.data,'$.state.status'),'') = 'running'
            AND COALESCE(json_extract(p.data,'$.tool'),'') IN ('question', 'apply_patch')
          )
    """

    generic_stale_rows = conn.execute(
        f"""
        {generic_stale_with_sql}
        SELECT
          s.id AS session_id,
          m.id AS message_id,
          p.id AS part_id,
          s.title AS session_title,
          s.time_updated AS session_time_updated,
          CAST(((_runtime_scan_now_ms() - s.time_updated) / 1000) AS INT) AS stale_seconds,
          COALESCE(json_extract(p.data,'$.type'),'none') AS last_part_type,
          COALESCE(json_extract(p.data,'$.tool'),'') AS last_tool,
          COALESCE(json_extract(p.data,'$.state.status'),'') AS last_tool_status
        {generic_stale_from_sql}
        ORDER BY s.time_updated DESC
        LIMIT 20
        """,
        (stale_seconds,),
    ).fetchall()
    generic_stale_findings: list[dict] = []
    for row in generic_stale_rows:
        item = dict(row)
        item["issue_type"] = "generic_stale_incomplete_assistant"
        generic_stale_findings.append(item)

    generic_stale_count = int(
        conn.execute(
            f"""
            {generic_stale_with_sql}
            SELECT COUNT(*)
            {generic_stale_from_sql}
            """,
            (stale_seconds,),
        ).fetchone()[0]
    )
    return findings, generic_stale_findings, generic_stale_count


def _scan_runtime_stuck_sessions(
    db_path: Path,
    stale_seconds: int,
    generic_stale_problem_threshold: int = DEFAULT_GENERIC_STALE_PROBLEM_THRESHOLD,
    *,
    now_ms: int | None = None,
) -> dict:
    started_at = time.perf_counter()
    scan_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    warnings: list[str] = []
    problems: list[str] = []
    remediation_codes: list[str] = []
    runtime_db_size_bytes = db_path.stat().st_size if db_path.exists() else 0
    runtime_db_wal_path = Path(f"{db_path}-wal")
    runtime_db_wal_bytes = (
        runtime_db_wal_path.stat().st_size if runtime_db_wal_path.exists() else 0
    )
    if runtime_db_size_bytes + runtime_db_wal_bytes >= RUNTIME_DB_SIZE_WARN_BYTES:
        warnings.append(
            f"runtime database footprint exceeds configured budget {RUNTIME_DB_SIZE_WARN_BYTES} bytes"
        )
        remediation_codes.append("runtime_storage_budget_exceeded")

    findings: list[dict] = []
    generic_stale_findings: list[dict] = []
    generic_stale_count = 0
    runtime_db_journal_mode: str | None = None
    runtime_db_sqlite_version: str | None = None
    runtime_db_missing_tables: list[str] = []
    runtime_db_json1_available = False
    runtime_db_json1_checked = False
    runtime_db_indexes: dict[str, list[str]] = {}
    runtime_db_index_columns: dict[str, dict[str, list[str]]] = {}
    runtime_db_scan_mode = "unavailable"
    runtime_db_query_only = False
    runtime_db_snapshot_started = False
    runtime_db_scan_complete = False

    def add_remediation(code: str) -> None:
        if code not in remediation_codes:
            remediation_codes.append(code)

    def result() -> dict:
        runtime_db_scan_duration_ms = round(
            (time.perf_counter() - started_at) * 1000, 2
        )
        latency_warning = (
            f"runtime diagnostic scan exceeds configured latency budget {RUNTIME_DB_SCAN_WARN_MS} ms"
        )
        if (
            runtime_db_scan_duration_ms >= RUNTIME_DB_SCAN_WARN_MS
            and latency_warning not in warnings
        ):
            warnings.append(latency_warning)
        return {
            "warnings": warnings,
            "problems": problems,
            "remediation_codes": remediation_codes,
            "stuck_findings": findings,
            "generic_stale_findings": generic_stale_findings,
            "generic_stale_count": generic_stale_count,
            "generic_stale_problem_threshold": generic_stale_problem_threshold,
            "runtime_db_busy_timeout_ms": RUNTIME_DB_BUSY_TIMEOUT_MS,
            "runtime_db_scan_timeout_ms": RUNTIME_DB_SCAN_TIMEOUT_MS,
            "runtime_db_query_only": runtime_db_query_only,
            "runtime_db_snapshot_started": runtime_db_snapshot_started,
            "runtime_db_scan_complete": runtime_db_scan_complete,
            "runtime_db_journal_mode": runtime_db_journal_mode,
            "runtime_db_sqlite_version": runtime_db_sqlite_version,
            "runtime_db_missing_tables": runtime_db_missing_tables,
            "runtime_db_json1_available": runtime_db_json1_available,
            "runtime_db_indexes": runtime_db_indexes,
            "runtime_db_index_columns": runtime_db_index_columns,
            "runtime_db_scan_mode": runtime_db_scan_mode,
            "runtime_db_size_bytes": runtime_db_size_bytes,
            "runtime_db_wal_bytes": runtime_db_wal_bytes,
            "runtime_db_size_warn_bytes": RUNTIME_DB_SIZE_WARN_BYTES,
            "runtime_db_scan_duration_ms": runtime_db_scan_duration_ms,
        }

    if not db_path.exists():
        warnings.append("runtime session database does not exist yet")
        return result()

    budget: _RuntimeScanBudget | None = None
    try:
        conn = _connect_runtime_database_readonly(db_path)
    except Exception as exc:
        problems.append(f"failed to open runtime session database: {exc}")
        add_remediation("runtime_db_open_failed")
        return result()

    try:
        try:
            conn.execute("PRAGMA query_only = ON")
            query_only_row = conn.execute("PRAGMA query_only").fetchone()
            runtime_db_query_only = bool(
                query_only_row is not None and int(query_only_row[0]) == 1
            )
        except Exception as exc:
            problems.append(f"failed to enable query-only runtime diagnosis: {exc}")
            add_remediation("runtime_query_only_unavailable")
            return result()
        if not runtime_db_query_only:
            problems.append("runtime database query-only mode could not be verified")
            add_remediation("runtime_query_only_unavailable")
            return result()

        budget = _RuntimeScanBudget(RUNTIME_DB_SCAN_TIMEOUT_MS)
        conn.set_progress_handler(budget.progress, RUNTIME_DB_PROGRESS_OPCODES)
        conn.execute("BEGIN")
        runtime_db_snapshot_started = True
        conn.row_factory = sqlite3.Row

        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        journal_row = conn.execute("PRAGMA journal_mode").fetchone()
        runtime_db_journal_mode = str(journal_row[0]) if journal_row else None
        version_row = conn.execute("SELECT sqlite_version()").fetchone()
        runtime_db_sqlite_version = str(version_row[0]) if version_row else None
        runtime_db_missing_tables = sorted({"session", "message", "part"} - tables)
        runtime_db_indexes = {
            table: [str(row[1]) for row in conn.execute(f"PRAGMA index_list({table})")]
            for table in ("session", "message", "part")
            if table in tables
        }
        runtime_db_index_columns = {
            table: _runtime_index_columns(conn, table)
            for table in ("session", "message", "part")
            if table in tables
        }
        conn.create_function(
            "_runtime_scan_now_ms",
            0,
            lambda: scan_now_ms,
            deterministic=True,
        )
        try:
            json1_row = conn.execute("SELECT json_valid('{}')").fetchone()
            runtime_db_json1_checked = True
            runtime_db_json1_available = bool(json1_row and json1_row[0])
        except sqlite3.OperationalError as exc:
            if "no such function" not in str(exc).lower() or "json_valid" not in str(exc).lower():
                raise
            runtime_db_json1_checked = True
            runtime_db_json1_available = False

        if runtime_db_missing_tables:
            problems.append(
                "runtime session database is missing required table(s): "
                + ", ".join(runtime_db_missing_tables)
            )
            add_remediation("runtime_schema_incompatible")
        if runtime_db_json1_checked and not runtime_db_json1_available:
            problems.append("runtime session database SQLite build lacks JSON1 support")
            add_remediation("runtime_json1_unavailable")

        if runtime_db_missing_tables or not runtime_db_json1_available:
            runtime_db_scan_mode = "incompatible"
        else:
            missing_index_prefixes = _missing_runtime_index_prefixes(
                runtime_db_index_columns
            )
            if missing_index_prefixes:
                runtime_db_scan_mode = "legacy_fallback"
                warnings.append(
                    "runtime diagnostic indexed snapshot unavailable; using compatibility scan "
                    f"(missing index prefixes: {', '.join(missing_index_prefixes)})"
                )
                findings, generic_stale_findings, generic_stale_count = (
                    _scan_runtime_stuck_sessions_legacy_queries(conn, stale_seconds)
                )
            else:
                runtime_db_scan_mode = "indexed_snapshot"
                findings, generic_stale_findings, generic_stale_count = (
                    _scan_runtime_stuck_sessions_indexed_queries(
                        conn,
                        stale_seconds=stale_seconds,
                        now_ms=scan_now_ms,
                    )
                )
            runtime_db_scan_complete = True
    except sqlite3.DatabaseError as exc:
        findings = []
        generic_stale_findings = []
        generic_stale_count = 0
        if budget is not None and budget.timed_out:
            runtime_db_scan_mode = "timeout"
            problems.append(
                f"runtime session database scan exceeded {RUNTIME_DB_SCAN_TIMEOUT_MS} ms execution budget"
            )
            add_remediation("runtime_scan_timeout")
        else:
            runtime_db_scan_mode = "query_failed"
            problems.append(f"failed to query runtime session database: {exc}")
            add_remediation("runtime_query_failed")
    except Exception as exc:
        findings = []
        generic_stale_findings = []
        generic_stale_count = 0
        runtime_db_scan_mode = "query_failed"
        problems.append(f"failed to query runtime session database: {exc}")
        add_remediation("runtime_query_failed")
    finally:
        try:
            conn.set_progress_handler(None, 0)
        except Exception:
            pass
        try:
            if conn.in_transaction:
                conn.rollback()
        finally:
            conn.close()

    findings = _annotate_stale_findings(findings)
    generic_stale_findings = _annotate_stale_findings(generic_stale_findings)
    findings_truncated = max(0, len(findings) - MAX_RUNTIME_STALE_FINDINGS)
    generic_findings_truncated = max(
        0, len(generic_stale_findings) - MAX_RUNTIME_STALE_FINDINGS
    )
    if findings_truncated or generic_findings_truncated:
        warnings.append(
            "runtime stale findings were capped; use scoped repair or raise diagnostic limits deliberately"
        )
    findings = findings[:MAX_RUNTIME_STALE_FINDINGS]
    generic_stale_findings = generic_stale_findings[:MAX_RUNTIME_STALE_FINDINGS]

    if runtime_db_scan_complete and findings:
        problems.append(
            f"detected {len(findings)} stuck session health finding(s) older than {stale_seconds}s"
        )
    elif runtime_db_scan_complete and generic_stale_count > 0:
        generic_stale_message = f"detected {generic_stale_count} stale incomplete assistant session(s) older than {stale_seconds}s"
        if generic_stale_count >= generic_stale_problem_threshold:
            problems.append(
                f"{generic_stale_message}; exceeds backlog threshold {generic_stale_problem_threshold}"
            )
        else:
            warnings.append(generic_stale_message)

    return result()

def _repair_message_and_tool(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    message_id: str,
    part_id: str,
    expected_session_time_updated: int,
    tool_name: str,
    reason_code: str,
) -> bool:
    if (
        not session_id
        or not message_id
        or not part_id
        or expected_session_time_updated <= 0
    ):
        return False

    session_row = conn.execute(
        "SELECT time_updated FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None or int(session_row["time_updated"] or 0) != int(
        expected_session_time_updated
    ):
        return False

    message_row = conn.execute(
        "SELECT data FROM message WHERE id = ? AND session_id = ?",
        (message_id, session_id),
    ).fetchone()
    part_row = conn.execute(
        "SELECT data FROM part WHERE id = ? AND session_id = ? AND message_id = ?",
        (part_id, session_id, message_id),
    ).fetchone()
    if message_row is None or part_row is None:
        return False

    now_ms = int(
        conn.execute("SELECT CAST(strftime('%s','now') * 1000 AS INT)").fetchone()[0]
    )
    message_data = json.loads(message_row["data"] or "{}")
    if not isinstance(message_data, dict):
        message_data = {}
    existing_time_payload = message_data.get("time")
    if (
        isinstance(existing_time_payload, dict)
        and existing_time_payload.get("completed") is not None
    ):
        return False
    time_payload = message_data.get("time")
    if not isinstance(time_payload, dict):
        time_payload = {}
    time_payload["completed"] = now_ms
    message_data["time"] = time_payload
    if message_data.get("error") is None:
        message_data["error"] = {
            "name": "RecoveredStaleSession",
            "message": reason_code,
        }

    part_data = json.loads(part_row["data"] or "{}")
    if not isinstance(part_data, dict):
        part_data = {}
    state_payload = part_data.get("state")
    if not isinstance(state_payload, dict):
        state_payload = {}
    if str(state_payload.get("status") or "").lower() != "running":
        return False
    state_payload["status"] = "failed"
    state_payload["reason"] = reason_code
    part_data["state"] = state_payload
    if tool_name and not part_data.get("tool"):
        part_data["tool"] = tool_name

    message_update = conn.execute(
        "UPDATE message SET data = ? WHERE id = ? AND session_id = ? AND json_extract(data,'$.time.completed') IS NULL",
        (json.dumps(message_data, separators=(",", ":")), message_id, session_id),
    )
    if message_update.rowcount != 1:
        return False
    part_update = conn.execute(
        "UPDATE part SET data = ? WHERE id = ? AND session_id = ? AND COALESCE(json_extract(data,'$.state.status'),'') = 'running'",
        (json.dumps(part_data, separators=(",", ":")), part_id, session_id),
    )
    if part_update.rowcount != 1:
        return False
    session_update = conn.execute(
        "UPDATE session SET time_updated = ? WHERE id = ? AND time_updated = ?",
        (now_ms, session_id, expected_session_time_updated),
    )
    return session_update.rowcount == 1


def _repair_stale_assistant_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    message_id: str,
    expected_session_time_updated: int,
    reason_code: str,
    part_id: str = "",
    expected_running_tool: bool = False,
) -> bool:
    if not session_id or not message_id or expected_session_time_updated <= 0:
        return False
    session_row = conn.execute(
        "SELECT time_updated FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None or int(session_row["time_updated"] or 0) != int(
        expected_session_time_updated
    ):
        return False
    message_row = conn.execute(
        "SELECT data FROM message WHERE id = ? AND session_id = ?",
        (message_id, session_id),
    ).fetchone()
    if message_row is None:
        return False
    message_data = json.loads(message_row["data"] or "{}")
    if not isinstance(message_data, dict):
        return False
    time_payload = message_data.get("time")
    if isinstance(time_payload, dict) and time_payload.get("completed") is not None:
        return False
    now_ms = int(
        conn.execute("SELECT CAST(strftime('%s','now') * 1000 AS INT)").fetchone()[0]
    )
    if not isinstance(time_payload, dict):
        time_payload = {}
    time_payload["completed"] = now_ms
    message_data["time"] = time_payload
    if message_data.get("error") is None:
        message_data["error"] = {
            "name": "RecoveredStaleSession",
            "message": reason_code,
        }
    message_update = conn.execute(
        "UPDATE message SET data = ? WHERE id = ? AND session_id = ? AND json_extract(data,'$.time.completed') IS NULL",
        (json.dumps(message_data, separators=(",", ":")), message_id, session_id),
    )
    if message_update.rowcount != 1:
        return False
    if expected_running_tool and part_id:
        part_row = conn.execute(
            "SELECT data FROM part WHERE id = ? AND session_id = ? AND message_id = ?",
            (part_id, session_id, message_id),
        ).fetchone()
        if part_row is None:
            return False
        part_data = json.loads(part_row["data"] or "{}")
        if not isinstance(part_data, dict):
            return False
        state_payload = part_data.get("state")
        if not isinstance(state_payload, dict):
            state_payload = {}
        if str(state_payload.get("status") or "").lower() != "running":
            return False
        state_payload["status"] = "failed"
        state_payload["reason"] = reason_code
        part_data["state"] = state_payload
        part_update = conn.execute(
            "UPDATE part SET data = ? WHERE id = ? AND session_id = ? AND message_id = ? AND COALESCE(json_extract(data,'$.state.status'),'') = 'running'",
            (
                json.dumps(part_data, separators=(",", ":")),
                part_id,
                session_id,
                message_id,
            ),
        )
        if part_update.rowcount != 1:
            return False
    session_update = conn.execute(
        "UPDATE session SET time_updated = ? WHERE id = ? AND time_updated = ?",
        (now_ms, session_id, expected_session_time_updated),
    )
    return session_update.rowcount == 1


def _repair_silent_parent_after_delegation_abort(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    message_id: str,
    part_id: str,
    expected_session_time_updated: int,
    tool_name: str,
    reason_code: str,
) -> bool:
    if (
        not session_id
        or not message_id
        or not part_id
        or expected_session_time_updated <= 0
    ):
        return False
    session_row = conn.execute(
        "SELECT time_updated FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None or int(session_row["time_updated"] or 0) != int(
        expected_session_time_updated
    ):
        return False
    message_row = conn.execute(
        "SELECT data FROM message WHERE id = ? AND session_id = ?",
        (message_id, session_id),
    ).fetchone()
    part_row = conn.execute(
        "SELECT data FROM part WHERE id = ? AND session_id = ? AND message_id = ?",
        (part_id, session_id, message_id),
    ).fetchone()
    if message_row is None or part_row is None:
        return False

    message_data = json.loads(message_row["data"] or "{}")
    if not isinstance(message_data, dict) or message_data.get("error") is None:
        return False
    existing_text = conn.execute(
        "SELECT 1 FROM part WHERE message_id = ? AND session_id = ? AND COALESCE(json_extract(data,'$.type'),'') = 'text' LIMIT 1",
        (message_id, session_id),
    ).fetchone()
    if existing_text is not None:
        return False

    part_data = json.loads(part_row["data"] or "{}")
    if not isinstance(part_data, dict):
        return False
    if (
        str(part_data.get("tool") or "").strip().lower()
        != str(tool_name or "task").strip().lower()
    ):
        return False
    state_payload = part_data.get("state")
    if not isinstance(state_payload, dict):
        state_payload = {}
    if str(state_payload.get("status") or "").lower() not in {"error", "failed"}:
        return False
    state_payload["reason"] = reason_code
    part_data["state"] = state_payload

    now_ms = int(
        conn.execute("SELECT CAST(strftime('%s','now') * 1000 AS INT)").fetchone()[0]
    )
    time_payload = message_data.get("time")
    if not isinstance(time_payload, dict):
        time_payload = {}
    time_payload["completed"] = now_ms
    message_data["time"] = time_payload

    message_update = conn.execute(
        "UPDATE message SET data = ? WHERE id = ? AND session_id = ?",
        (json.dumps(message_data, separators=(",", ":")), message_id, session_id),
    )
    if message_update.rowcount != 1:
        return False
    part_update = conn.execute(
        "UPDATE part SET data = ? WHERE id = ? AND session_id = ? AND message_id = ?",
        (
            json.dumps(part_data, separators=(",", ":")),
            part_id,
            session_id,
            message_id,
        ),
    )
    if part_update.rowcount != 1:
        return False
    text_part_id = f"prt_{uuid.uuid4().hex[:24]}"
    text_part_data = {
        "type": "text",
        "text": "[recovered stale delegated abort after child completion]",
        "synthetic": True,
    }
    part_columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(part)").fetchall()
    }
    if "time_updated" in part_columns:
        conn.execute(
            "INSERT INTO part (id, session_id, message_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            (
                text_part_id,
                session_id,
                message_id,
                now_ms,
                now_ms,
                json.dumps(text_part_data, separators=(",", ":")),
            ),
        )
    else:
        conn.execute(
            "INSERT INTO part (id, session_id, message_id, time_created, data) VALUES (?, ?, ?, ?, ?)",
            (
                text_part_id,
                session_id,
                message_id,
                now_ms,
                json.dumps(text_part_data, separators=(",", ":")),
            ),
        )
    session_update = conn.execute(
        "UPDATE session SET time_updated = ? WHERE id = ? AND time_updated = ?",
        (now_ms, session_id, expected_session_time_updated),
    )
    return session_update.rowcount == 1


def _child_session_still_terminal(
    conn: sqlite3.Connection,
    *,
    parent_session_id: str,
    child_session_id: str,
    child_message_id: str,
    expected_child_time_updated: int,
) -> bool:
    if (
        not parent_session_id
        or not child_session_id
        or not child_message_id
        or expected_child_time_updated <= 0
    ):
        return False
    session_row = conn.execute(
        "SELECT time_updated FROM session WHERE id = ? AND parent_id = ?",
        (child_session_id, parent_session_id),
    ).fetchone()
    if session_row is None or int(session_row["time_updated"] or 0) != int(
        expected_child_time_updated
    ):
        return False
    message_row = conn.execute(
        "SELECT data FROM message WHERE id = ? AND session_id = ?",
        (child_message_id, child_session_id),
    ).fetchone()
    if message_row is None:
        return False
    message_data = json.loads(message_row["data"] or "{}")
    if not isinstance(message_data, dict):
        return False
    time_payload = message_data.get("time")
    return bool(
        (isinstance(time_payload, dict) and time_payload.get("completed") is not None)
        or message_data.get("error") is not None
    )


def _child_session_still_stale_incomplete(
    conn: sqlite3.Connection,
    *,
    parent_session_id: str,
    child_session_id: str,
    child_message_id: str,
    expected_child_time_updated: int,
) -> bool:
    if (
        not parent_session_id
        or not child_session_id
        or not child_message_id
        or expected_child_time_updated <= 0
    ):
        return False
    session_row = conn.execute(
        "SELECT time_updated FROM session WHERE id = ? AND parent_id = ?",
        (child_session_id, parent_session_id),
    ).fetchone()
    if session_row is None or int(session_row["time_updated"] or 0) != int(
        expected_child_time_updated
    ):
        return False
    message_row = conn.execute(
        "SELECT data FROM message WHERE id = ? AND session_id = ?",
        (child_message_id, child_session_id),
    ).fetchone()
    if message_row is None:
        return False
    message_data = json.loads(message_row["data"] or "{}")
    if not isinstance(message_data, dict):
        return False
    if message_data.get("error") is not None:
        return False
    time_payload = message_data.get("time")
    return not (
        isinstance(time_payload, dict) and time_payload.get("completed") is not None
    )


def _backup_runtime_database(db_path: Path) -> Path:
    """Create a transactionally consistent SQLite backup before runtime repair."""
    backup_path = db_path.with_name(f"{db_path.name}.pre-repair-{uuid.uuid4().hex}.sqlite3")
    source = _connect_runtime_database_readonly(db_path)
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
    except Exception:
        destination.close()
        backup_path.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        return backup_path
    finally:
        source.close()


def _repair_runtime_stuck_sessions(
    db_path: Path,
    stale_seconds: int,
    apply_changes: bool,
    include_generic: bool,
    scope_session_id: str | None = None,
) -> dict:
    repairs: list[dict] = []
    repairable_issue_types = {
        "parent_child_mismatch",
        "silent_parent_after_delegation_abort",
        "stale_delegated_child_runtime_recovery_missed",
        "stale_running_tool",
    }
    scan = _scan_runtime_stuck_sessions(db_path, stale_seconds)

    def collect_candidates(current_scan: dict) -> list[dict]:
        current_candidates = [
            finding
            for finding in (current_scan["stuck_findings"] or [])
            if str(finding.get("issue_type") or "") in repairable_issue_types
        ]
        if include_generic:
            current_candidates.extend(current_scan.get("generic_stale_findings") or [])
        if scope_session_id:
            current_candidates = [
                finding
                for finding in current_candidates
                if scope_session_id
                in {
                    str(finding.get("session_id") or ""),
                    str(finding.get("parent_session_id") or ""),
                    str(finding.get("child_session_id") or ""),
                }
            ]
        deduplicated: dict[tuple[str, str, str, str], dict] = {}
        parent_issue_types = {
            "parent_child_mismatch",
            "silent_parent_after_delegation_abort",
            "stale_delegated_child_runtime_recovery_missed",
        }
        for finding in current_candidates:
            issue_type = str(finding.get("issue_type") or "")
            if issue_type in parent_issue_types:
                key = (
                    "parent",
                    str(finding.get("parent_session_id") or ""),
                    str(finding.get("parent_message_id") or ""),
                    str(finding.get("parent_part_id") or ""),
                )
            else:
                key = (
                    "session",
                    str(finding.get("session_id") or ""),
                    str(finding.get("message_id") or ""),
                    str(finding.get("part_id") or ""),
                )
            deduplicated.setdefault(key, finding)
        return list(deduplicated.values())

    candidate_findings = collect_candidates(scan)
    base_problems = [] if scope_session_id else scan["problems"]
    if not apply_changes or not candidate_findings or not db_path.exists():
        return {
            "warnings": scan["warnings"],
            "problems": base_problems,
            "candidate_count": len(candidate_findings),
            "repaired_count": 0,
            "repairs": repairs,
            "preview": candidate_findings,
            "backup_path": None,
        }

    try:
        backup_path = _backup_runtime_database(db_path)
    except sqlite3.DatabaseError as exc:
        return {
            "warnings": scan["warnings"],
            "problems": [*base_problems, f"failed to back up runtime session database: {exc}"],
            "candidate_count": len(candidate_findings),
            "repaired_count": 0,
            "repairs": repairs,
            "preview": candidate_findings,
            "backup_path": None,
        }
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        remaining_candidates = candidate_findings
        for _round in range(20):
            if not remaining_candidates:
                break
            progress_this_round = 0
            conn.execute("BEGIN IMMEDIATE")
            for finding in remaining_candidates:
                # Savepoint identifiers cannot be bound parameters; keep them internal and fixed-format.
                savepoint_name = f"repair_{len(repairs)}"
                conn.execute(f"SAVEPOINT {savepoint_name}")
                repaired = False
                issue_type = str(finding.get("issue_type") or "")
                if issue_type == "parent_child_mismatch":
                    session_id = str(finding.get("parent_session_id") or "")
                    if not _child_session_still_terminal(
                        conn,
                        parent_session_id=session_id,
                        child_session_id=str(finding.get("child_session_id") or ""),
                        child_message_id=str(finding.get("child_message_id") or ""),
                        expected_child_time_updated=int(
                            finding.get("child_time_updated") or 0
                        ),
                    ):
                        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                        continue
                    repaired = _repair_message_and_tool(
                        conn,
                        session_id=session_id,
                        message_id=str(finding.get("parent_message_id") or ""),
                        part_id=str(finding.get("parent_part_id") or ""),
                        expected_session_time_updated=int(
                            finding.get("parent_time_updated") or 0
                        ),
                        tool_name=str(finding.get("parent_last_tool") or "task"),
                        reason_code="stale_parent_reconciled_from_child_completion",
                    )
                    if repaired:
                        repairs.append(
                            {
                                "issue_type": issue_type,
                                "parent_session_id": session_id,
                                "child_session_id": finding.get("child_session_id"),
                                "tool": finding.get("parent_last_tool") or "task",
                            }
                        )
                elif issue_type == "silent_parent_after_delegation_abort":
                    session_id = str(finding.get("parent_session_id") or "")
                    if not _child_session_still_terminal(
                        conn,
                        parent_session_id=session_id,
                        child_session_id=str(finding.get("child_session_id") or ""),
                        child_message_id=str(finding.get("child_message_id") or ""),
                        expected_child_time_updated=int(
                            finding.get("child_time_updated") or 0
                        ),
                    ):
                        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                        continue
                    repaired = _repair_silent_parent_after_delegation_abort(
                        conn,
                        session_id=session_id,
                        message_id=str(finding.get("parent_message_id") or ""),
                        part_id=str(finding.get("parent_part_id") or ""),
                        expected_session_time_updated=int(
                            finding.get("parent_time_updated") or 0
                        ),
                        tool_name=str(finding.get("parent_last_tool") or "task"),
                        reason_code="silent_parent_after_delegation_abort_repaired",
                    )
                    if repaired:
                        repairs.append(
                            {
                                "issue_type": issue_type,
                                "parent_session_id": session_id,
                                "child_session_id": finding.get("child_session_id"),
                                "tool": finding.get("parent_last_tool") or "task",
                            }
                        )
                elif issue_type == "stale_delegated_child_runtime_recovery_missed":
                    session_id = str(finding.get("parent_session_id") or "")
                    if not _child_session_still_stale_incomplete(
                        conn,
                        parent_session_id=session_id,
                        child_session_id=str(finding.get("child_session_id") or ""),
                        child_message_id=str(finding.get("child_message_id") or ""),
                        expected_child_time_updated=int(
                            finding.get("child_time_updated") or 0
                        ),
                    ):
                        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                        continue
                    repaired = _repair_message_and_tool(
                        conn,
                        session_id=session_id,
                        message_id=str(finding.get("parent_message_id") or ""),
                        part_id=str(finding.get("parent_part_id") or ""),
                        expected_session_time_updated=int(
                            finding.get("parent_time_updated") or 0
                        ),
                        tool_name=str(finding.get("parent_last_tool") or "task"),
                        reason_code="stale_delegated_child_runtime_recovery_missed",
                    )
                    if repaired:
                        repairs.append(
                            {
                                "issue_type": issue_type,
                                "parent_session_id": session_id,
                                "child_session_id": finding.get("child_session_id"),
                                "tool": finding.get("parent_last_tool") or "task",
                            }
                        )
                elif issue_type == "stale_running_tool":
                    session_id = str(finding.get("session_id") or "")
                    repaired = _repair_message_and_tool(
                        conn,
                        session_id=session_id,
                        message_id=str(finding.get("message_id") or ""),
                        part_id=str(finding.get("part_id") or ""),
                        expected_session_time_updated=int(
                            finding.get("session_time_updated") or 0
                        ),
                        tool_name=str(finding.get("last_tool") or ""),
                        reason_code="stale_running_tool_repaired",
                    )
                    if repaired:
                        repairs.append(
                            {
                                "issue_type": issue_type,
                                "session_id": session_id,
                                "tool": finding.get("last_tool") or "",
                            }
                        )
                elif issue_type == "generic_stale_incomplete_assistant":
                    session_id = str(finding.get("session_id") or "")
                    repaired = _repair_stale_assistant_session(
                        conn,
                        session_id=session_id,
                        message_id=str(finding.get("message_id") or ""),
                        expected_session_time_updated=int(
                            finding.get("session_time_updated") or 0
                        ),
                        reason_code="generic_stale_incomplete_assistant_repaired",
                        part_id=str(finding.get("part_id") or ""),
                        expected_running_tool=bool(
                            str(finding.get("last_part_type") or "") == "tool"
                            and str(finding.get("last_tool_status") or "") == "running"
                        ),
                    )
                    if repaired:
                        repairs.append(
                            {
                                "issue_type": issue_type,
                                "session_id": session_id,
                                "tool": finding.get("last_tool") or "",
                            }
                        )
                if not repaired:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                else:
                    progress_this_round += 1
                conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            conn.commit()
            if progress_this_round <= 0:
                break
            scan = _scan_runtime_stuck_sessions(db_path, stale_seconds)
            remaining_candidates = collect_candidates(scan)
    except sqlite3.DatabaseError as exc:
        conn.rollback()
        return {
            "warnings": scan["warnings"],
            "problems": [
                *scan["problems"],
                f"failed to repair runtime session database: {exc}",
            ],
            "candidate_count": len(candidate_findings),
            "repaired_count": len(repairs),
            "repairs": repairs,
            "preview": candidate_findings,
            "backup_path": str(backup_path),
        }
    finally:
        conn.close()

    problems = []
    if len(repairs) != len(candidate_findings):
        problems.append(
            f"repaired {len(repairs)} of {len(candidate_findings)} stale finding(s); rerun doctor before trusting the result"
        )

    return {
        "warnings": scan["warnings"],
        "problems": problems,
        "candidate_count": len(candidate_findings),
        "repaired_count": len(repairs),
        "repairs": repairs,
        "preview": candidate_findings,
        "backup_path": str(backup_path),
    }


def _resolve_current_session(rows: list[dict]) -> tuple[dict | None, str]:
    explicit = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    cwd = str(Path.cwd())
    cwd_rows = [row for row in rows if str(row.get("cwd") or "") == cwd]

    if explicit:
        selected = next(
            (row for row in cwd_rows if str(row.get("session_id") or "") == explicit),
            None,
        )
        if selected is None:
            selected = next(
                (row for row in rows if str(row.get("session_id") or "") == explicit),
                None,
            )
        if isinstance(selected, dict):
            return selected, "env+index"
        return {"session_id": explicit, "cwd": cwd}, "env_only"
    if cwd_rows:
        return cwd_rows[0], "cwd_latest"
    if rows:
        return rows[0], "index_latest"
    return None, ""


def _command_current(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    args = [arg for arg in argv if arg != "--json"]
    if args:
        return _usage()

    cwd = str(Path.cwd())
    try:
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "current",
                "index_path": str(index_path),
                **_index_failure_fields(exc),
            },
            json_output,
        )

    selected, source = _resolve_current_session(rows)
    if not isinstance(selected, dict):
        return _emit(
            {
                "result": "FAIL",
                "command": "current",
                "error": "no indexed session found for current workspace",
                "index_path": str(index_path),
                "cwd": cwd,
            },
            json_output,
        )

    return _emit(
        {
            "result": "PASS",
            "command": "current",
            "index_path": str(index_path),
            "source": source,
            "session": selected,
        },
        json_output,
    )


def _command_list(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    try:
        limit = _parse_limit(argv)
        rows = _session_rows(_load_index(index_path))[:limit]
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "list",
                "index_path": str(index_path),
                **_index_failure_fields(exc),
            },
            json_output,
        )
    return _emit(
        {
            "result": "PASS",
            "command": "list",
            "index_path": str(index_path),
            "count": len(rows),
            "sessions": rows,
        },
        json_output,
    )


def _command_show(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    args = [arg for arg in argv if arg != "--json"]
    if not args:
        return _usage()
    target_id = args[0]
    try:
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "show",
                "index_path": str(index_path),
                **_index_failure_fields(exc),
            },
            json_output,
        )
    match = next((row for row in rows if row.get("session_id") == target_id), None)
    if not isinstance(match, dict):
        return _emit(
            {
                "result": "FAIL",
                "command": "show",
                "error": f"session not found: {target_id}",
                "index_path": str(index_path),
            },
            json_output,
        )
    return _emit(
        {
            "result": "PASS",
            "command": "show",
            "index_path": str(index_path),
            "session": match,
        },
        json_output,
    )


def _redaction_enabled(argv: list[str]) -> bool:
    return "--redact" in argv or os.environ.get(
        "MY_OPENCODE_SESSION_REDACT_DEFAULT", ""
    ).lower() in {"1", "true", "yes"}


def _redacted_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _redacted_event_count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _redact_session_record(record: dict) -> dict:
    return {
        "started_at": _redacted_timestamp(record.get("started_at")),
        "last_event_at": _redacted_timestamp(record.get("last_event_at")),
        "event_count": _redacted_event_count(record.get("event_count")),
    }


def _redacted_failure(command: str, error_code: str) -> dict:
    return {
        "result": "FAIL",
        "command": command,
        "redacted": True,
        "error_code": error_code,
    }


def _command_search(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    redact = _redaction_enabled(argv)
    args = [arg for arg in argv if arg not in {"--json", "--redact"}]
    if not args:
        if redact:
            return _emit(
                _redacted_failure("search", "session_search_query_required"),
                json_output,
            )
        return _usage()
    query = args[0].strip().lower()
    try:
        limit = _parse_limit(argv)
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        if redact:
            return _emit(
                _redacted_failure("search", "session_index_unavailable"),
                json_output,
            )
        return _emit(
            {
                "result": "FAIL",
                "command": "search",
                "index_path": str(index_path),
                **_index_failure_fields(exc),
            },
            json_output,
        )
    matches = [
        row
        for row in rows
        if query in str(row.get("session_id", "")).lower()
        or query in str(row.get("cwd", "")).lower()
        or query in str(row.get("last_reason", "")).lower()
    ][:limit]
    if redact:
        return _emit(
            {
                "result": "PASS",
                "command": "search",
                "redacted": True,
                "count": len(matches),
                "sessions": [_redact_session_record(row) for row in matches],
            },
            json_output,
        )
    return _emit(
        {
            "result": "PASS",
            "command": "search",
            "index_path": str(index_path),
            "query": query,
            "count": len(matches),
            "redacted": False,
            "sessions": matches,
        },
        json_output,
    )


def _command_doctor(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    try:
        db_path = _parse_path_option(argv, "--db-path", DEFAULT_RUNTIME_DB_PATH)
        stale_seconds = _parse_positive_int_option(
            argv, "--stale-seconds", DEFAULT_STALE_SESSION_SECONDS
        )
        generic_stale_problem_threshold = _parse_positive_int_option(
            argv,
            "--generic-stale-problem-threshold",
            DEFAULT_GENERIC_STALE_PROBLEM_THRESHOLD,
        )
    except ValueError:
        return _usage()
    warnings: list[str] = []
    problems: list[str] = []
    exists = index_path.exists()
    index_permission_mode = (index_path.stat().st_mode & 0o777) if exists else None
    if exists and index_permission_mode != 0o600:
        warnings.append("session index permissions should be 0600")
    if not exists:
        warnings.append("session index does not exist yet; run /digest run first")
        runtime = _scan_runtime_stuck_sessions(
            db_path, stale_seconds, generic_stale_problem_threshold
        )
        warnings.extend(runtime["warnings"])
        problems.extend(runtime["problems"])
        return _emit(
            {
                "result": "PASS" if not problems else "FAIL",
                "command": "doctor",
                "index_path": str(index_path),
                "runtime_db_path": str(db_path),
                "runtime_db_candidates": [str(candidate) for candidate in _runtime_db_candidates()],
                "exists": False,
                "index_permission_mode": index_permission_mode,
                "warnings": warnings,
                "problems": problems,
                "remediation_codes": runtime.get("remediation_codes", []),
                "stuck_findings": runtime["stuck_findings"],
                "generic_stale_findings": runtime["generic_stale_findings"],
                "generic_stale_count": runtime["generic_stale_count"],
                "generic_stale_problem_threshold": runtime[
                    "generic_stale_problem_threshold"
                ],
                "runtime_db_busy_timeout_ms": runtime["runtime_db_busy_timeout_ms"],
                "runtime_db_scan_timeout_ms": runtime["runtime_db_scan_timeout_ms"],
                "runtime_db_query_only": runtime["runtime_db_query_only"],
                "runtime_db_snapshot_started": runtime["runtime_db_snapshot_started"],
                "runtime_db_scan_complete": runtime["runtime_db_scan_complete"],
                "runtime_db_journal_mode": runtime["runtime_db_journal_mode"],
                "runtime_db_sqlite_version": runtime["runtime_db_sqlite_version"],
                "runtime_db_missing_tables": runtime["runtime_db_missing_tables"],
                "runtime_db_json1_available": runtime["runtime_db_json1_available"],
                "runtime_db_indexes": runtime["runtime_db_indexes"],
                "runtime_db_index_columns": runtime["runtime_db_index_columns"],
                "runtime_db_scan_mode": runtime["runtime_db_scan_mode"],
                "runtime_db_size_bytes": runtime["runtime_db_size_bytes"],
                "runtime_db_wal_bytes": runtime["runtime_db_wal_bytes"],
                "runtime_db_size_warn_bytes": runtime["runtime_db_size_warn_bytes"],
                "runtime_db_scan_duration_ms": runtime["runtime_db_scan_duration_ms"],
                "count": 0,
                "stale_seconds": stale_seconds,
                "quick_fixes": [],
            },
            json_output,
        )
    try:
        index = _load_index(index_path)
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "doctor",
                "index_path": str(index_path),
                "runtime_db_path": str(db_path),
                "runtime_db_candidates": [str(candidate) for candidate in _runtime_db_candidates()],
                "exists": True,
                "index_permission_mode": index_permission_mode,
                "warnings": warnings,
                "problems": problems,
                "count": 0,
                "stuck_findings": [],
                "generic_stale_findings": [],
                "generic_stale_count": 0,
                "generic_stale_problem_threshold": generic_stale_problem_threshold,
                "stale_seconds": stale_seconds,
                "quick_fixes": [],
                **_index_failure_fields(exc),
            },
            json_output,
        )
    rows = _session_rows(index)
    if not rows:
        warnings.append("session index exists but no sessions are recorded yet")
    runtime = _scan_runtime_stuck_sessions(
        db_path, stale_seconds, generic_stale_problem_threshold
    )
    warnings.extend(runtime["warnings"])
    problems.extend(runtime["problems"])
    return _emit(
        {
            "result": "PASS" if not problems else "FAIL",
            "command": "doctor",
            "index_path": str(index_path),
            "runtime_db_path": str(db_path),
            "runtime_db_candidates": [str(candidate) for candidate in _runtime_db_candidates()],
            "exists": True,
            "index_permission_mode": index_permission_mode,
            "warnings": warnings,
            "problems": problems,
            "remediation_codes": runtime.get("remediation_codes", []),
            "count": len(rows),
            "stuck_findings": runtime["stuck_findings"],
            "generic_stale_findings": runtime["generic_stale_findings"],
            "generic_stale_count": runtime["generic_stale_count"],
            "generic_stale_problem_threshold": runtime[
                "generic_stale_problem_threshold"
            ],
            "runtime_db_busy_timeout_ms": runtime["runtime_db_busy_timeout_ms"],
            "runtime_db_scan_timeout_ms": runtime["runtime_db_scan_timeout_ms"],
            "runtime_db_query_only": runtime["runtime_db_query_only"],
            "runtime_db_snapshot_started": runtime["runtime_db_snapshot_started"],
            "runtime_db_scan_complete": runtime["runtime_db_scan_complete"],
            "runtime_db_journal_mode": runtime["runtime_db_journal_mode"],
            "runtime_db_sqlite_version": runtime["runtime_db_sqlite_version"],
            "runtime_db_missing_tables": runtime["runtime_db_missing_tables"],
            "runtime_db_json1_available": runtime["runtime_db_json1_available"],
            "runtime_db_indexes": runtime["runtime_db_indexes"],
            "runtime_db_index_columns": runtime["runtime_db_index_columns"],
            "runtime_db_scan_mode": runtime["runtime_db_scan_mode"],
            "runtime_db_size_bytes": runtime["runtime_db_size_bytes"],
            "runtime_db_wal_bytes": runtime["runtime_db_wal_bytes"],
            "runtime_db_size_warn_bytes": runtime["runtime_db_size_warn_bytes"],
            "runtime_db_scan_duration_ms": runtime["runtime_db_scan_duration_ms"],
            "stale_seconds": stale_seconds,
            "quick_fixes": [
                "/doctor run",
                f"/session doctor --db-path {shlex.quote(str(db_path))} --stale-seconds {stale_seconds} --generic-stale-problem-threshold {generic_stale_problem_threshold} --json",
                f"/session repair-stale --db-path {shlex.quote(str(db_path))} --stale-seconds {stale_seconds} --apply --json",
                f"/session repair-stale --db-path {shlex.quote(str(db_path))} --stale-seconds {stale_seconds} --include-generic --apply --json",
            ]
            if problems
            else [],
        },
        json_output,
    )


def _command_handoff(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    redact = _redaction_enabled(argv)
    args = [arg for arg in argv if arg not in {"--json", "--redact"}]
    target_id: str | None = None
    launch_cwd: str | None = None
    fork = False
    cursor = 0
    while cursor < len(args):
        token = args[cursor]
        if token == "--id":
            if cursor + 1 >= len(args):
                if redact:
                    return _emit(
                        _redacted_failure(
                            "handoff", "session_handoff_arguments_invalid"
                        ),
                        json_output,
                    )
                return _usage()
            target_id = args[cursor + 1]
            cursor += 2
            continue
        if token == "--launch-cwd":
            if cursor + 1 >= len(args):
                if redact:
                    return _emit(
                        _redacted_failure(
                            "handoff", "session_handoff_arguments_invalid"
                        ),
                        json_output,
                    )
                return _usage()
            launch_cwd = args[cursor + 1]
            cursor += 2
            continue
        if token == "--fork":
            fork = True
            cursor += 1
            continue
        if redact:
            return _emit(
                _redacted_failure("handoff", "session_handoff_arguments_invalid"),
                json_output,
            )
        return _usage()

    try:
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        if redact:
            return _emit(
                _redacted_failure("handoff", "session_index_unavailable"),
                json_output,
            )
        return _emit(
            {
                "result": "FAIL",
                "command": "handoff",
                "index_path": str(index_path),
                **_index_failure_fields(exc),
            },
            json_output,
        )

    if not rows and not target_id:
        if redact:
            return _emit(
                _redacted_failure("handoff", "session_index_empty"),
                json_output,
            )
        return _emit(
            {
                "result": "FAIL",
                "command": "handoff",
                "error": "no indexed sessions found; run /digest run first",
                "index_path": str(index_path),
            },
            json_output,
        )
    selected, source = _resolve_current_session(rows)
    if target_id:
        selected_match = next(
            (row for row in rows if str(row.get("session_id")) == target_id),
            None,
        )
        if not isinstance(selected_match, dict):
            if redact:
                return _emit(
                    _redacted_failure("handoff", "session_not_found"),
                    json_output,
                )
            return _emit(
                {
                    "result": "FAIL",
                    "command": "handoff",
                    "error": f"session not found: {target_id}",
                    "index_path": str(index_path),
                },
                json_output,
            )
        selected = selected_match
    else:
        if source == "env_only":
            if redact:
                return _emit(
                    _redacted_failure("handoff", "session_not_indexed"),
                    json_output,
                )
            return _emit(
                {
                    "result": "FAIL",
                    "command": "handoff",
                    "error": "active runtime session is not indexed yet; run /digest run first",
                    "index_path": str(index_path),
                },
                json_output,
            )
        if not isinstance(selected, dict):
            selected = rows[0] if rows else {}

    if redact:
        projected = _redact_session_record(selected)
        return _emit(
            {
                "result": "PASS",
                "command": "handoff",
                "redacted": True,
                **projected,
            },
            json_output,
        )

    digest = _load_digest(DEFAULT_DIGEST_PATH)
    raw_git = digest.get("git")
    git: dict = raw_git if isinstance(raw_git, dict) else {}
    raw_plan = digest.get("plan_execution")
    plan: dict = raw_plan if isinstance(raw_plan, dict) else {}
    plan_status = str(plan.get("status") or "idle")

    next_actions = [
        "/doctor run",
        "/session show <session_id> --json",
    ]
    if plan_status not in {"idle", "completed"}:
        next_actions.insert(0, "/autoflow status --json")

    resolved_launch_cwd = launch_cwd or selected.get("cwd")
    launch_command = ""
    resume_command = ""
    if isinstance(resolved_launch_cwd, str) and resolved_launch_cwd.strip():
        quoted_cwd = shlex.quote(resolved_launch_cwd)
        launch_command = f"opencode {quoted_cwd}"
        resume_command = f"opencode {quoted_cwd} --session {shlex.quote(str(selected.get('session_id') or ''))}"
        if fork:
            resume_command = f"{resume_command} --fork"
        next_actions.insert(0, launch_command)
        next_actions.insert(1, resume_command)

    payload = {
        "result": "PASS",
        "command": "handoff",
        "redacted": False,
        "session_id": selected.get("session_id"),
        "cwd": selected.get("cwd"),
        "launch_cwd": resolved_launch_cwd,
        "started_at": selected.get("started_at"),
        "last_event_at": selected.get("last_event_at"),
        "event_count": selected.get("event_count"),
        "last_reason": selected.get("last_reason"),
        "digest_path": str(DEFAULT_DIGEST_PATH),
        "git_branch": git.get("branch"),
        "git_status_count": git.get("status_count"),
        "plan_status": plan_status,
        "launch_command": launch_command,
        "resume_command": resume_command,
        "fork": fork,
        "next_actions": next_actions,
    }
    return _emit(payload, json_output)

def _command_repair_stale(argv: list[str], index_path: Path) -> int:
    del index_path
    json_output = "--json" in argv
    apply_changes = "--apply" in argv
    include_generic = "--include-generic" in argv
    confirm_generic = "--confirm-generic" in argv
    args = [
        arg
        for arg in argv
        if arg not in {"--json", "--apply", "--include-generic", "--confirm-generic"}
    ]
    try:
        session_id = _parse_text_option(args, "--session-id")
        if session_id:
            session_index = args.index("--session-id")
            del args[session_index : session_index + 2]
        db_path = _parse_path_option(args, "--db-path", DEFAULT_RUNTIME_DB_PATH)
        stale_seconds = _parse_positive_int_option(
            args, "--stale-seconds", DEFAULT_STALE_SESSION_SECONDS
        )
    except ValueError:
        return _usage()

    if apply_changes and include_generic and not confirm_generic:
        return _emit(
            {
                "result": "FAIL",
                "command": "repair-stale",
                "runtime_db_path": str(db_path),
                "apply": apply_changes,
                "include_generic": include_generic,
                "confirm_generic": confirm_generic,
                "session_id": session_id,
                "warnings": [],
                "problems": [
                    "generic stale-session repair requires --confirm-generic with --include-generic --apply"
                ],
                "candidate_count": 0,
                "repaired_count": 0,
                "repairs": [],
                "preview": [],
                "backup_path": None,
                "quick_fixes": [],
            },
            json_output,
        )

    repair = _repair_runtime_stuck_sessions(
        db_path, stale_seconds, apply_changes, include_generic, session_id
    )
    result = "PASS"
    if repair["problems"]:
        result = "FAIL"
    elif not apply_changes and repair["candidate_count"]:
        result = "FAIL"
    payload = {
        "result": result,
        "command": "repair-stale",
        "runtime_db_path": str(db_path),
        "stale_seconds": stale_seconds,
        "apply": apply_changes,
        "include_generic": include_generic,
        "confirm_generic": confirm_generic,
        "session_id": session_id,
        "warnings": repair["warnings"],
        "problems": repair["problems"],
        "candidate_count": repair["candidate_count"],
        "repaired_count": repair["repaired_count"],
        "repairs": repair["repairs"],
        "preview": repair["preview"],
        "backup_path": repair["backup_path"],
        "quick_fixes": []
        if apply_changes or not repair["candidate_count"]
        else [
            f"/session repair-stale --db-path {shlex.quote(str(db_path))} --stale-seconds {stale_seconds}{f' --session-id {shlex.quote(session_id)}' if session_id else ''}{' --include-generic --confirm-generic' if include_generic else ''} --apply --json"
        ],
    }
    return _emit(payload, json_output)


def main(argv: list[str]) -> int:
    if not argv:
        return _usage()
    command = argv[0]
    rest = argv[1:]
    index_path = DEFAULT_INDEX_PATH

    if command == "help":
        return _usage()
    if command == "current":
        return _command_current(rest, index_path)
    if command == "list":
        return _command_list(rest, index_path)
    if command == "show":
        return _command_show(rest, index_path)
    if command == "search":
        return _command_search(rest, index_path)
    if command == "handoff":
        return _command_handoff(rest, index_path)
    if command == "doctor":
        return _command_doctor(rest, index_path)
    if command == "repair-stale":
        return _command_repair_stale(rest, index_path)
    return _usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
