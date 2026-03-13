#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shlex
import sqlite3
import sys
import uuid
from pathlib import Path


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

DEFAULT_RUNTIME_DB_PATH = Path(
    os.environ.get("MY_OPENCODE_RUNTIME_DB_PATH", "~/.local/share/opencode/opencode.db")
).expanduser()

DEFAULT_STALE_SESSION_SECONDS = max(
    60,
    int(os.environ.get("MY_OPENCODE_STUCK_SESSION_THRESHOLD_SECONDS", "300") or "300"),
)


def _usage() -> int:
    print(
        "usage: /session current [--json] | /session list [--limit <n>] [--json] | /session show <id> [--json] "
        "| /session search <query> [--limit <n>] [--json] | /session handoff [--id <session_id>] [--launch-cwd <path>] [--fork] [--json] | /session doctor [--db-path <path>] [--stale-seconds <n>] [--json] | /session repair-stale [--db-path <path>] [--stale-seconds <n>] [--include-generic] [--apply] [--json]"
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


def _parse_path_option(argv: list[str], name: str, default: Path) -> Path:
    if name not in argv:
        return default
    idx = argv.index(name)
    if idx + 1 >= len(argv):
        raise ValueError(f"missing value for {name}")
    return Path(argv[idx + 1]).expanduser()


def _load_index(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "generated_at": None, "sessions": []}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("session index root must be object")
    sessions = loaded.get("sessions")
    if sessions is not None and not isinstance(sessions, list):
        raise ValueError("session index sessions must be list")
    return {
        "version": loaded.get("version", 1),
        "generated_at": loaded.get("generated_at"),
        "sessions": sessions if isinstance(sessions, list) else [],
    }


def _session_rows(index: dict) -> list[dict]:
    rows: list[dict] = []
    for item in index.get("sessions", []):
        if isinstance(item, dict):
            rows.append(item)
    rows.sort(key=lambda row: str(row.get("last_event_at") or ""), reverse=True)
    return rows


def _emit(payload: dict, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1
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
                if issue_type == "parent_child_mismatch":
                    print(
                        "- "
                        f"type={issue_type} parent={finding.get('parent_session_id')} "
                        f"child={finding.get('child_session_id')} "
                        f"age={finding.get('parent_stale_seconds')}s "
                        f"parent_tool={finding.get('parent_last_tool') or 'none'} "
                        f"child_state={finding.get('child_state')}"
                    )
                elif issue_type == "stale_delegated_child_runtime_recovery_missed":
                    print(
                        "- "
                        f"type={issue_type} parent={finding.get('parent_session_id')} "
                        f"child={finding.get('child_session_id')} "
                        f"parent_age={finding.get('parent_stale_seconds')}s "
                        f"child_age={finding.get('child_stale_seconds')}s "
                        f"child_last_part={finding.get('child_last_part_type') or 'none'}"
                    )
                else:
                    print(
                        "- "
                        f"type={issue_type} session={finding.get('session_id')} "
                        f"age={finding.get('stale_seconds')}s "
                        f"tool={finding.get('last_tool') or 'none'} "
                        f"status={finding.get('last_tool_status') or 'unknown'}"
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
    if payload.get("result") != "PASS":
        print(f"error: {payload.get('error', 'session command failed')}")
        return 1
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


def _scan_runtime_stuck_sessions(db_path: Path, stale_seconds: int) -> dict:
    warnings: list[str] = []
    problems: list[str] = []
    findings: list[dict] = []
    generic_stale_findings: list[dict] = []
    if not db_path.exists():
        warnings.append("runtime session database does not exist yet")
        return {
            "warnings": warnings,
            "problems": problems,
            "stuck_findings": findings,
            "generic_stale_count": 0,
        }

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        problems.append(f"failed to open runtime session database: {exc}")
        return {
            "warnings": warnings,
            "problems": problems,
            "stuck_findings": findings,
            "generic_stale_count": 0,
        }

    try:
        parent_child_rows = conn.execute(
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
              CAST((strftime('%s','now') - (p.time_updated / 1000)) AS INT) AS parent_stale_seconds,
              CAST((strftime('%s','now') - (c.time_updated / 1000)) AS INT) AS child_stale_seconds,
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
              AND json_extract(pm.data,'$.time.completed') IS NULL
              AND p.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
              AND c.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
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
              CAST((strftime('%s','now') - (p.time_updated / 1000)) AS INT) AS parent_stale_seconds,
              CAST((strftime('%s','now') - (c.time_updated / 1000)) AS INT) AS child_stale_seconds,
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
              AND p.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
              AND c.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
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
              CAST((strftime('%s','now') - (p.time_updated / 1000)) AS INT) AS parent_stale_seconds,
              CAST((strftime('%s','now') - (c.time_updated / 1000)) AS INT) AS child_stale_seconds,
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
              AND p.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
              AND c.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
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
              CAST((strftime('%s','now') - (s.time_updated / 1000)) AS INT) AS stale_seconds,
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
              AND s.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
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
              AND s.time_updated <= (strftime('%s','now') * 1000 - (? * 1000))
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
              CAST((strftime('%s','now') - (s.time_updated / 1000)) AS INT) AS stale_seconds,
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
    except sqlite3.DatabaseError as exc:
        problems.append(f"failed to query runtime session database: {exc}")
        generic_stale_count = 0
    finally:
        conn.close()

    if findings:
        problems.append(
            f"detected {len(findings)} stuck session health finding(s) older than {stale_seconds}s"
        )
    elif generic_stale_count > 0:
        warnings.append(
            f"detected {generic_stale_count} stale incomplete assistant session(s) older than {stale_seconds}s"
        )

    return {
        "warnings": warnings,
        "problems": problems,
        "stuck_findings": findings,
        "generic_stale_findings": generic_stale_findings,
        "generic_stale_count": generic_stale_count,
    }


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


def _repair_runtime_stuck_sessions(
    db_path: Path, stale_seconds: int, apply_changes: bool, include_generic: bool
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
        return current_candidates

    candidate_findings = collect_candidates(scan)
    if not apply_changes or not candidate_findings or not db_path.exists():
        return {
            "warnings": scan["warnings"],
            "problems": scan["problems"],
            "candidate_count": len(candidate_findings),
            "repaired_count": 0,
            "repairs": repairs,
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
                savepoint_name = (
                    f"repair_{len(repairs)}_{str(finding.get('issue_type') or 'item')}"
                )
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
                "error": str(exc),
                "index_path": str(index_path),
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
                "error": str(exc),
                "index_path": str(index_path),
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
                "error": str(exc),
                "index_path": str(index_path),
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


def _command_search(argv: list[str], index_path: Path) -> int:
    json_output = "--json" in argv
    args = [arg for arg in argv if arg not in {"--json"}]
    if not args:
        return _usage()
    query = args[0].strip().lower()
    try:
        limit = _parse_limit(argv)
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "search",
                "error": str(exc),
                "index_path": str(index_path),
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
    return _emit(
        {
            "result": "PASS",
            "command": "search",
            "index_path": str(index_path),
            "query": query,
            "count": len(matches),
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
    except ValueError:
        return _usage()
    warnings: list[str] = []
    problems: list[str] = []
    exists = index_path.exists()
    if not exists:
        warnings.append("session index does not exist yet; run /digest run first")
        runtime = _scan_runtime_stuck_sessions(db_path, stale_seconds)
        warnings.extend(runtime["warnings"])
        problems.extend(runtime["problems"])
        return _emit(
            {
                "result": "PASS" if not problems else "FAIL",
                "command": "doctor",
                "index_path": str(index_path),
                "runtime_db_path": str(db_path),
                "exists": False,
                "warnings": warnings,
                "problems": problems,
                "stuck_findings": runtime["stuck_findings"],
                "stale_seconds": stale_seconds,
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
                "error": f"failed to parse index: {exc}",
                "index_path": str(index_path),
                "runtime_db_path": str(db_path),
                "exists": True,
                "warnings": warnings,
                "problems": problems,
            },
            json_output,
        )
    rows = _session_rows(index)
    if not rows:
        warnings.append("session index exists but no sessions are recorded yet")
    runtime = _scan_runtime_stuck_sessions(db_path, stale_seconds)
    warnings.extend(runtime["warnings"])
    problems.extend(runtime["problems"])
    return _emit(
        {
            "result": "PASS" if not problems else "FAIL",
            "command": "doctor",
            "index_path": str(index_path),
            "runtime_db_path": str(db_path),
            "exists": True,
            "warnings": warnings,
            "problems": problems,
            "count": len(rows),
            "stuck_findings": runtime["stuck_findings"],
            "generic_stale_count": runtime["generic_stale_count"],
            "stale_seconds": stale_seconds,
            "quick_fixes": [
                "/doctor run",
                f"/session doctor --db-path {shlex.quote(str(db_path))} --stale-seconds {stale_seconds} --json",
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
    args = [arg for arg in argv if arg != "--json"]
    target_id: str | None = None
    launch_cwd: str | None = None
    fork = False
    cursor = 0
    while cursor < len(args):
        token = args[cursor]
        if token == "--id":
            if cursor + 1 >= len(args):
                return _usage()
            target_id = args[cursor + 1]
            cursor += 2
            continue
        if token == "--launch-cwd":
            if cursor + 1 >= len(args):
                return _usage()
            launch_cwd = args[cursor + 1]
            cursor += 2
            continue
        if token == "--fork":
            fork = True
            cursor += 1
            continue
        return _usage()

    try:
        rows = _session_rows(_load_index(index_path))
    except Exception as exc:
        return _emit(
            {
                "result": "FAIL",
                "command": "handoff",
                "error": f"failed to load session index: {exc}",
                "index_path": str(index_path),
            },
            json_output,
        )

    if not rows and not target_id:
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
    args = [
        arg for arg in argv if arg not in {"--json", "--apply", "--include-generic"}
    ]
    try:
        db_path = _parse_path_option(args, "--db-path", DEFAULT_RUNTIME_DB_PATH)
        stale_seconds = _parse_positive_int_option(
            args, "--stale-seconds", DEFAULT_STALE_SESSION_SECONDS
        )
    except ValueError:
        return _usage()

    repair = _repair_runtime_stuck_sessions(
        db_path, stale_seconds, apply_changes, include_generic
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
        "warnings": repair["warnings"],
        "problems": repair["problems"],
        "candidate_count": repair["candidate_count"],
        "repaired_count": repair["repaired_count"],
        "repairs": repair["repairs"],
        "quick_fixes": []
        if apply_changes or not repair["candidate_count"]
        else [
            f"/session repair-stale --db-path {shlex.quote(str(db_path))} --stale-seconds {stale_seconds}{' --include-generic' if include_generic else ''} --apply --json"
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
