#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path  # type: ignore
from knowledge_capture_pipeline import (  # type: ignore
    ENTRY_TYPES,
    collect_pr_signals,
    collect_task_digest_signals,
    generate_draft_entries,
    load_entries,
    save_entries,
    transition_entry,
    update_entry,
)


def usage() -> int:
    print(
        "usage: /learn [capture|review|publish|search|doctor] [--json] "
        "| /learn capture [--repo <path>] [--digest-dir <path>] [--limit <n>] [--json] "
        "| /learn review --entry-id <id> [--summary <text>] [--confidence <0-100>] [--risk <low|medium|high>] [--json] "
        "| /learn publish --entry-id <id> --approved-by <name> [--json] "
        "| /learn search [--query <text>] [--status <state>] [--type <entry_type>] [--limit <n>] [--json]"
    )
    return 2


def pop_flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def pop_value(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag not in args:
        return default
    idx = args.index(flag)
    if idx + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    value = args[idx + 1]
    del args[idx : idx + 2]
    return value


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def runtime_entries_path() -> Path:
    write_path = resolve_write_path()
    return write_path.parent / "my_opencode" / "runtime" / "knowledge_entries.json"


def _published_first_sort_key(entry: dict[str, Any]) -> tuple[int, int, str]:
    status = str(entry.get("status", "draft"))
    confidence = int(entry.get("confidence_score", 0) or 0)
    updated = str(entry.get("updated_at", ""))
    return (1 if status == "published" else 0, confidence, updated)


def _is_stale(entry: dict[str, Any], *, now: datetime, stale_days: int = 30) -> bool:
    updated_at = str(entry.get("updated_at", "")).strip()
    confidence = int(entry.get("confidence_score", 0) or 0)
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return confidence < 60
    return ts < (now - timedelta(days=stale_days)) or confidence < 60


def _merge_drafts(
    existing: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    existing_map = {str(item.get("entry_id", "")): dict(item) for item in existing}
    for draft in drafts:
        entry_id = str(draft.get("entry_id", "")).strip()
        if not entry_id:
            continue
        prior = existing_map.get(entry_id)
        if not prior:
            existing_map[entry_id] = draft
            continue
        merged_sources = sorted(
            {
                *[str(item) for item in prior.get("evidence_sources", [])],
                *[str(item) for item in draft.get("evidence_sources", [])],
            }
        )
        status = str(prior.get("status", "draft"))
        updated = dict(prior)
        updated["summary"] = draft.get("summary", prior.get("summary"))
        updated["evidence_sources"] = merged_sources
        updated["confidence_score"] = max(
            int(prior.get("confidence_score", 0) or 0),
            int(draft.get("confidence_score", 0) or 0),
        )
        if status == "archived":
            updated["status"] = "archived"
        updated["updated_at"] = draft.get("updated_at", prior.get("updated_at"))
        existing_map[entry_id] = updated
    return sorted(existing_map.values(), key=lambda item: str(item.get("entry_id", "")))


def command_capture(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        repo_raw = pop_value(args, "--repo")
        digest_raw = pop_value(args, "--digest-dir")
        limit_raw = pop_value(args, "--limit", "40") or "40"
    except ValueError:
        return usage()
    if args:
        return usage()

    try:
        limit = max(1, int(limit_raw))
    except ValueError:
        return usage()

    repo = Path(repo_raw).expanduser().resolve() if repo_raw else Path.cwd()
    if not repo.exists():
        emit(
            {
                "result": "FAIL",
                "reason_code": "repo_not_found",
                "repo": str(repo),
            },
            as_json=as_json,
        )
        return 1

    _, _ = load_layered_config()
    write_path = resolve_write_path()
    digest_dir = (
        Path(digest_raw).expanduser().resolve()
        if digest_raw
        else write_path.parent / "digests"
    )

    pr_signals = collect_pr_signals(repo, limit=limit)
    digest_signals = collect_task_digest_signals(digest_dir, limit=limit)
    drafts = generate_draft_entries(pr_signals + digest_signals)

    entries_path = runtime_entries_path()
    existing = load_entries(entries_path)
    merged = _merge_drafts(existing, drafts)
    save_entries(entries_path, merged)

    payload = {
        "result": "PASS",
        "captured": {
            "pr_signals": len(pr_signals),
            "digest_signals": len(digest_signals),
            "draft_entries": len(drafts),
        },
        "total_entries": len(merged),
        "entries_path": str(entries_path),
        "entries": merged[: min(10, len(merged))],
    }
    emit(payload, as_json=as_json)
    return 0


def command_review(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        entry_id = pop_value(args, "--entry-id")
        summary = pop_value(args, "--summary")
        confidence_raw = pop_value(args, "--confidence")
        risk = pop_value(args, "--risk")
    except ValueError:
        return usage()
    if args or not entry_id:
        return usage()

    entries_path = runtime_entries_path()
    entries = load_entries(entries_path)
    target = next(
        (item for item in entries if str(item.get("entry_id")) == entry_id), None
    )
    if not target:
        emit(
            {
                "result": "FAIL",
                "reason_code": "entry_not_found",
                "entry_id": entry_id,
                "entries_path": str(entries_path),
            },
            as_json=as_json,
        )
        return 1

    updated = dict(target)
    changes: dict[str, Any] = {}
    if summary:
        changes["summary"] = summary
    if confidence_raw is not None:
        try:
            confidence = max(0, min(100, int(confidence_raw)))
        except ValueError:
            return usage()
        changes["confidence_score"] = confidence
    if risk:
        if risk not in {"low", "medium", "high"}:
            return usage()
        tags = dict(updated.get("tags", {}))
        tags["risk"] = risk
        changes["tags"] = tags
    if changes:
        updated = update_entry(updated, **changes)

    failures: list[str] = []
    if str(updated.get("status", "draft")) == "draft":
        updated, failures = transition_entry(updated, target_status="review")

    if failures:
        emit(
            {
                "result": "FAIL",
                "reason_codes": sorted(set(failures)),
                "entry": updated,
            },
            as_json=as_json,
        )
        return 1

    rewritten = []
    for item in entries:
        rewritten.append(updated if str(item.get("entry_id")) == entry_id else item)
    save_entries(entries_path, rewritten)
    emit(
        {
            "result": "PASS",
            "entry_id": entry_id,
            "status": updated.get("status"),
            "entry": updated,
            "entries_path": str(entries_path),
        },
        as_json=as_json,
    )
    return 0


def _integration_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    published = [item for item in entries if str(item.get("status", "")) == "published"]
    published_sorted = sorted(published, key=_published_first_sort_key, reverse=True)
    rule_candidates = [
        {
            "entry_id": str(item.get("entry_id", "")),
            "title": str(item.get("title", "")),
            "confidence_score": int(item.get("confidence_score", 0) or 0),
        }
        for item in published_sorted
        if str(item.get("entry_type", "")) == "rule_candidate"
        or "rule" in str(item.get("summary", "")).lower()
    ]
    autoflow_guidance = [
        {
            "entry_id": str(item.get("entry_id", "")),
            "title": str(item.get("title", "")),
            "stage": str(item.get("tags", {}).get("stage", ["implement"])[0])
            if isinstance(item.get("tags", {}).get("stage", []), list)
            else str(item.get("tags", {}).get("stage", "implement")),
            "hint": str(item.get("summary", ""))[:200],
        }
        for item in published_sorted[:5]
    ]
    now = datetime.now(UTC)
    stale_candidates = [
        {
            "entry_id": str(item.get("entry_id", "")),
            "status": str(item.get("status", "")),
            "confidence_score": int(item.get("confidence_score", 0) or 0),
            "updated_at": str(item.get("updated_at", "")),
        }
        for item in entries
        if _is_stale(item, now=now)
    ]
    return {
        "rule_injector_candidates": rule_candidates,
        "autoflow_guidance": autoflow_guidance,
        "stale_maintenance_candidates": stale_candidates,
    }


def command_publish(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        entry_id = pop_value(args, "--entry-id")
        approved_by = pop_value(args, "--approved-by")
    except ValueError:
        return usage()
    if args or not entry_id or not approved_by:
        return usage()

    entries_path = runtime_entries_path()
    entries = load_entries(entries_path)
    target = next(
        (item for item in entries if str(item.get("entry_id")) == entry_id), None
    )
    if not target:
        emit(
            {
                "result": "FAIL",
                "reason_code": "entry_not_found",
                "entry_id": entry_id,
                "entries_path": str(entries_path),
            },
            as_json=as_json,
        )
        return 1

    working = dict(target)
    failures: list[str] = []
    if str(working.get("status", "draft")) == "draft":
        working, failures = transition_entry(working, target_status="review")
    if not failures:
        working, failures = transition_entry(
            working,
            target_status="published",
            approved_by=approved_by,
        )
    if failures:
        rewritten = []
        for item in entries:
            rewritten.append(working if str(item.get("entry_id")) == entry_id else item)
        save_entries(entries_path, rewritten)
        emit(
            {
                "result": "FAIL",
                "reason_codes": sorted(set(failures)),
                "entry": working,
            },
            as_json=as_json,
        )
        return 1

    rewritten = []
    for item in entries:
        rewritten.append(working if str(item.get("entry_id")) == entry_id else item)
    save_entries(entries_path, rewritten)

    integrations = _integration_payload(rewritten)
    emit(
        {
            "result": "PASS",
            "entry_id": entry_id,
            "status": working.get("status"),
            "entry": working,
            "integrations": integrations,
            "entries_path": str(entries_path),
        },
        as_json=as_json,
    )
    return 0


def command_search(args: list[str]) -> int:
    as_json = pop_flag(args, "--json")
    try:
        query = (pop_value(args, "--query", "") or "").strip().lower()
        status = (pop_value(args, "--status") or "").strip().lower()
        entry_type = (pop_value(args, "--type") or "").strip().lower()
        limit_raw = pop_value(args, "--limit", "10") or "10"
    except ValueError:
        return usage()
    if args:
        return usage()
    if entry_type and entry_type not in ENTRY_TYPES:
        return usage()
    try:
        limit = max(1, int(limit_raw))
    except ValueError:
        return usage()

    entries_path = runtime_entries_path()
    entries = load_entries(entries_path)
    filtered = []
    for item in entries:
        text_blob = " ".join(
            [
                str(item.get("entry_id", "")),
                str(item.get("title", "")),
                str(item.get("summary", "")),
                " ".join(str(src) for src in item.get("evidence_sources", [])),
            ]
        ).lower()
        if query and query not in text_blob:
            continue
        if status and str(item.get("status", "")).lower() != status:
            continue
        if entry_type and str(item.get("entry_type", "")).lower() != entry_type:
            continue
        filtered.append(item)

    filtered = sorted(filtered, key=_published_first_sort_key, reverse=True)
    payload = {
        "result": "PASS",
        "count": len(filtered),
        "entries": filtered[:limit],
        "entries_path": str(entries_path),
        "integrations": _integration_payload(filtered),
    }
    emit(payload, as_json=as_json)
    return 0


def command_doctor(args: list[str]) -> int:
    if any(arg not in ("--json",) for arg in args):
        return usage()
    as_json = "--json" in args
    entries_path = runtime_entries_path()
    report = {
        "result": "PASS"
        if (SCRIPT_DIR / "knowledge_capture_pipeline.py").exists()
        and (
            SCRIPT_DIR.parent / "instructions" / "knowledge_capture_policy_contract.md"
        ).exists()
        else "FAIL",
        "pipeline_exists": (SCRIPT_DIR / "knowledge_capture_pipeline.py").exists(),
        "policy_exists": (
            SCRIPT_DIR.parent / "instructions" / "knowledge_capture_policy_contract.md"
        ).exists(),
        "entries_path": str(entries_path),
        "entries_path_exists": entries_path.exists(),
        "warnings": []
        if entries_path.exists()
        else ["knowledge entry store not initialized; run /learn capture"],
        "problems": []
        if (SCRIPT_DIR / "knowledge_capture_pipeline.py").exists()
        else ["missing scripts/knowledge_capture_pipeline.py"],
        "quick_fixes": [
            "/learn capture --json",
            "/learn search --query rule --json",
            "/learn doctor --json",
        ],
    }
    if not report["policy_exists"]:
        report["warnings"].append(
            "missing instructions/knowledge_capture_policy_contract.md"
        )
    emit(report, as_json=as_json)
    return 0 if report["result"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if not argv:
        return command_capture(["--json"])
    cmd, *rest = argv
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "capture":
        return command_capture(rest)
    if cmd == "review":
        return command_review(rest)
    if cmd == "publish":
        return command_publish(rest)
    if cmd == "search":
        return command_search(rest)
    if cmd == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
