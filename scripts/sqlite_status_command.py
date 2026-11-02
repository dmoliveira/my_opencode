"""Concise local SQLite status from existing owner diagnostics.

Filesystem measurements are metadata-only and not a privacy certification.
This command never repairs, archives, deletes or initializes a store.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

import memory_lifecycle_command
import session_metadata_index
import sqlite_doctor_command as doctor

STORE_ORDER = doctor.STORE_ORDER
VALID_HEALTH = {"PASS", "WARN", "FAIL"}
VALID_RUNTIME_PRIVACY = {"private", "missing", "repair_required", "blocked"}
VALID_SIDECAR_PRIVACY = {
    "private",
    "safe",
    "present",
    "repaired",
    "missing",
    "repairable",
    "blocked",
}


def _safe_path(value: Any) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        return None
    try:
        value.encode("utf-8")
        path = Path(value)
        return str(path) if path.is_absolute() else None
    except (ValueError, OSError, UnicodeError):
        return None


def _size(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _metadata(path: str | None) -> dict[str, Any]:
    """lstat the final component only; do not read file contents or follow it."""
    unknown = {
        "state": "unknown",
        "bytes": None,
        "mode": None,
        "owner_is_current_user": None,
        "link_count": None,
    }
    if path is None:
        return unknown
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        return {**unknown, "state": "missing"}
    except (OSError, ValueError, UnicodeError):
        return unknown
    if not stat.S_ISREG(value.st_mode):
        return {**unknown, "state": "non_regular"}
    return {
        "state": "regular",
        "bytes": int(value.st_size),
        "mode": f"{stat.S_IMODE(value.st_mode):04o}",
        "owner_is_current_user": value.st_uid == os.geteuid()
        if hasattr(os, "geteuid")
        else None,
        "link_count": int(value.st_nlink),
    }


def _metadata_needs_attention(value: dict[str, Any]) -> bool:
    if value["state"] == "non_regular":
        return True
    if value["state"] != "regular":
        return False
    return (
        int(value["mode"], 8) & 0o077 != 0
        or value["owner_is_current_user"] is False
        or value["link_count"] != 1
    )


def _owner_config() -> dict[str, Any]:
    """Resolve Codememory config without connecting or returning raw config."""
    try:
        return _query_owner_config()
    except (OSError, RuntimeError, ValueError, TypeError, RecursionError):
        return {"state": "unavailable", "backend": None, "path": None}


def _query_owner_config() -> dict[str, Any]:
    executable = shutil.which(os.environ.get("MY_OPENCODE_CODEMEMORY_BIN", "oc"))
    if not executable:
        return {"state": "unavailable", "backend": None, "path": None}
    config = doctor._config_path()
    command = [executable]
    if config.exists():
        command.extend(["--config", str(config)])
    command.extend(["config", "--format", "json"])
    raw = doctor._run_bounded_command(command, cwd=doctor.REPO_ROOT)
    if raw.get("exit_code") != 0:
        return {"state": "unavailable", "backend": None, "path": None}
    payload, failure = doctor._decode_json_output(raw)
    if failure or not payload or payload.get("type") != "config":
        return {"state": "unavailable", "backend": None, "path": None}
    database = payload.get("database")
    if not isinstance(database, dict):
        return {"state": "invalid", "backend": None, "path": None}
    backend = database.get("backend")
    if not isinstance(backend, str) or backend not in {"sqlite", "postgres"}:
        return {"state": "invalid", "backend": None, "path": None}
    path = _safe_path(database.get("path")) if backend == "sqlite" else None
    if backend == "sqlite" and path is None:
        return {"state": "invalid", "backend": "sqlite", "path": None}
    return {"state": "resolved", "backend": backend, "path": path}


def _health(store: Any) -> str:
    if not isinstance(store, dict):
        return "FAIL"
    value = store.get("result")
    return value if isinstance(value, str) and value in VALID_HEALTH else "FAIL"


def _retention() -> dict[str, dict[str, Any]]:
    try:
        policy = session_metadata_index._load_policy()
        allowed = (
            "max_sessions",
            "max_age_days",
            "max_events_per_session",
            "max_reasons_per_session",
            "max_plan_ids_per_session",
        )
        if not isinstance(policy, dict) or any(
            type(policy.get(key)) is not int or policy[key] <= 0 for key in allowed
        ):
            raise ValueError("invalid owner policy")
        sidecars = {
            "state": "effective_writer_policy_with_default_fallback",
            "values": {key: policy[key] for key in allowed},
        }
    except (OSError, ValueError, TypeError, KeyError):
        sidecars = {"state": "unknown", "values": None}
    try:
        _, _, days, _, _ = memory_lifecycle_command._parse_archive_options(
            [], cleanup=True
        )
        if type(days) is not int or days < 1:
            raise ValueError("invalid cleanup default")
        shared = {
            "state": "manual_archive_default",
            "older_days": days,
            "automatic_cleanup": "unknown",
            "pinned_excluded": True,
        }
    except (ValueError, TypeError):
        shared = {
            "state": "unknown",
            "older_days": None,
            "automatic_cleanup": "unknown",
            "pinned_excluded": None,
        }
    return {
        "runtime_history": {
            "state": "unknown",
            "automatic_deletion": "not_established",
        },
        "session_sidecars": sidecars,
        "shared_memory": shared,
        "codememory": {"state": "unknown", "automatic_deletion": "not_established"},
    }


def _sidecar_artifacts(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    findings = diagnostics.get("sidecar_findings")
    if not isinstance(findings, list):
        return []
    items = []
    for finding in findings[:16]:
        if not isinstance(finding, dict) or finding.get("target") not in (
            "index",
            "digest",
        ):
            continue
        path = _safe_path(finding.get("path"))
        state = finding.get("state")
        items.append(
            {
                "kind": finding["target"],
                "path": path,
                "owner_privacy_state": state
                if isinstance(state, str) and state in VALID_SIDECAR_PRIVACY
                else "unknown",
                "file_metadata": _metadata(path),
            }
        )
    return items


def build_status(
    doctor_report: dict[str, Any], owner_config: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(doctor_report, dict) or not isinstance(
        doctor_report.get("stores"), dict
    ):
        return {
            "result": "FAIL",
            "command": "sqlite-status",
            "schema_version": 1,
            "sensitivity": "local-sensitive",
            "stores": [],
            "reason_codes": ["sqlite_status_owner_report_invalid"],
        }
    owner_config = owner_config if isinstance(owner_config, dict) else {}
    retention = _retention()
    items = []
    reason_codes = []
    for name in STORE_ORDER:
        raw = doctor_report["stores"].get(name)
        raw = raw if isinstance(raw, dict) else {}
        diagnostics = (
            raw.get("diagnostics") if isinstance(raw.get("diagnostics"), dict) else {}
        )
        health = _health(raw)
        path = _safe_path(raw.get("path"))
        source = "owner_diagnostic" if path else "unknown"
        if name == "codememory":
            configured_path = _safe_path(owner_config.get("path"))
            backend = owner_config.get("backend")
            if (
                owner_config.get("state") != "resolved"
                or not isinstance(backend, str)
                or backend not in {"sqlite", "postgres"}
            ):
                configured_path = None
                reason_codes.append("codememory_config_unavailable")
                health = "FAIL" if health == "FAIL" else "WARN"
                source = "unknown"
            elif backend == "postgres":
                configured_path = None
                reason_codes.append("codememory_non_sqlite_backend")
                health = "FAIL" if health == "FAIL" else "WARN"
                source = "native_config_non_sqlite"
            else:
                source = "native_config"
                if configured_path != path:
                    reason_codes.append("codememory_doctor_path_mismatch")
                    health = "FAIL" if health == "FAIL" else "WARN"
            path = configured_path
        privacy = {"state": "unknown", "basis": "owner_diagnostic_unavailable"}
        if name == "runtime_history":
            state = diagnostics.get("runtime_permission_status")
            privacy = {
                "state": state
                if isinstance(state, str) and state in VALID_RUNTIME_PRIVACY
                else "unknown",
                "basis": "runtime_owner_diagnostic",
            }
        elif name == "session_sidecars":
            privacy = {
                "state": "see_artifacts",
                "basis": "owner_sidecar_findings_incomplete_inventory",
            }
        item = {
            "store": name,
            "health": health,
            "path": path,
            "path_source": source,
            "file_metadata": _metadata(path),
            "privacy": privacy,
            "retention": retention[name],
        }
        if name in {"runtime_history", "shared_memory", "codememory"}:
            item["wal_metadata"] = _metadata(path + "-wal" if path else None)
        if name == "runtime_history":
            item["owner_reported_database_bytes"] = _size(
                diagnostics.get("runtime_db_size_bytes")
            )
            item["owner_reported_wal_bytes"] = _size(
                diagnostics.get("runtime_db_wal_bytes")
            )
        if name == "session_sidecars":
            item["artifacts"] = _sidecar_artifacts(diagnostics)
            if not item["artifacts"]:
                item["privacy"]["state"] = "unknown"
        if name == "codememory":
            backend = owner_config.get("backend")
            item["backend"] = (
                backend
                if (
                    owner_config.get("state") == "resolved"
                    and isinstance(backend, str)
                    and backend in {"sqlite", "postgres"}
                )
                else None
            )
        metadata_checks = [item["file_metadata"]]
        if "wal_metadata" in item:
            metadata_checks.append(item["wal_metadata"])
        if name == "session_sidecars":
            metadata_checks.extend(
                artifact["file_metadata"] for artifact in item["artifacts"]
            )
        if any(_metadata_needs_attention(meta) for meta in metadata_checks):
            item["health"] = "FAIL" if item["health"] == "FAIL" else "WARN"
            reason_codes.append(f"{name}_file_metadata_attention")
            if item["privacy"]["state"] == "private":
                item["privacy"]["state"] = "inconsistent_samples"
            elif name in {"session_sidecars", "shared_memory", "codememory"}:
                item["privacy"]["state"] = "file_metadata_attention"
        items.append(item)
    declared = doctor_report.get("result")
    if not isinstance(declared, str) or declared not in VALID_HEALTH:
        declared = "FAIL"
        reason_codes.append("sqlite_status_owner_result_invalid")
    result = (
        "FAIL"
        if declared == "FAIL" or any(item["health"] == "FAIL" for item in items)
        else "WARN"
        if declared == "WARN" or any(item["health"] == "WARN" for item in items)
        else "PASS"
    )
    return {
        "result": result,
        "command": "sqlite-status",
        "schema_version": 1,
        "sensitivity": "local-sensitive",
        "stores": items,
        "reason_codes": reason_codes,
        "limitations": [
            "Metadata and owner diagnostics are sampled, not an atomic cross-store snapshot.",
            "Final-component mode and ownership do not establish ancestor, WAL, backup or data privacy.",
            "Unknown retention is not evidence that deletion or pruning is safe.",
        ],
    }


def _redact(report: dict[str, Any]) -> dict[str, Any]:
    report["sensitivity"] = "metadata-only-not-automatically-share-safe"
    for store in report["stores"]:
        store["path"] = None
        for item in store.get("artifacts", []):
            item["path"] = None
    return report


def _retention_text(value: dict[str, Any]) -> str:
    state = value["state"]
    if state == "manual_archive_default":
        return f"manual-archive-default:{value['older_days']}d;automatic=unknown"
    if state == "effective_writer_policy_with_default_fallback":
        policy = value["values"]
        return f"index-writer:{policy['max_age_days']}d/{policy['max_sessions']}-sessions;fallback-possible"
    return "unknown"


def main(argv: list[str]) -> int:
    if len(set(argv)) != len(argv) or any(
        value not in {"--json", "--redact"} for value in argv
    ):
        print("usage: /doctor sqlite status [--json] [--redact]")
        return 2
    try:
        report = build_status(doctor.build_report(), _owner_config())
    except Exception:  # noqa: BLE001 - owner failures must not echo sensitive paths or content
        report = build_status({}, {})
    if "--redact" in argv:
        report = _redact(report)
    if "--json" in argv:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print("SQLite status (local-sensitive metadata; not a privacy certificate)")
        for item in report["stores"]:
            path = item["path"] if item["path"] else "unknown or redacted"
            size = item["file_metadata"]["bytes"]
            mode = item["file_metadata"]["mode"] or "unknown"
            wal = item.get("wal_metadata", {}).get("bytes")
            print(
                f"- {item['store']}: {item['health']} path={json.dumps(path)} "
                f"bytes={size if size is not None else 'unknown'} wal_bytes={wal if wal is not None else 'unknown'} "
                f"final_mode={mode} privacy={item['privacy']['state']} retention={_retention_text(item['retention'])}"
            )
            for artifact in item.get("artifacts", []):
                artifact_path = artifact["path"] or "unknown or redacted"
                artifact_size = artifact["file_metadata"]["bytes"]
                print(
                    f"  {artifact['kind']}: path={json.dumps(artifact_path)} "
                    f"bytes={artifact_size if artifact_size is not None else 'unknown'} "
                    f"final_mode={artifact['file_metadata']['mode'] or 'unknown'} "
                    f"owner_privacy={artifact['owner_privacy_state']}"
                )
        for reason in report["reason_codes"]:
            print(f"warning: {reason}")
        print(f"result: {report['result']}")
    return 1 if report["result"] == "FAIL" else 0
