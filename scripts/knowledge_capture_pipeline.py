#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ENTRY_TYPES = {"pattern", "pitfall", "checklist", "rule_candidate"}
LIFECYCLE = {"draft", "review", "published", "archived"}
TRANSITIONS = {
    "draft": {"review"},
    "review": {"published"},
    "published": {"archived"},
    "archived": set(),
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_git(repo_root: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def collect_pr_signals(repo_root: Path, *, limit: int = 40) -> list[dict[str, Any]]:
    rc, out, _ = _run_git(
        repo_root,
        ["log", "--merges", f"--max-count={max(1, limit)}", "--pretty=%H%x1f%s%x1f%cI"],
    )
    if rc != 0 or not out:
        return []
    signals: list[dict[str, Any]] = []
    for row in out.splitlines():
        parts = row.split("\x1f")
        if len(parts) != 3:
            continue
        sha, subject, committed_at = parts
        pr_match = re.search(r"pull request #(\d+)", subject, flags=re.IGNORECASE)
        pr_number = int(pr_match.group(1)) if pr_match else None
        objective_match = re.search(r"\b(E\d+-T\d+)\b", subject)
        objective_key = objective_match.group(1).upper() if objective_match else None
        signals.append(
            {
                "signal_id": f"pr-{pr_number}" if pr_number else f"commit-{sha[:12]}",
                "signal_type": "merged_pr",
                "summary": subject,
                "objective_key": objective_key,
                "captured_at": committed_at,
                "source_link": f"pr:{pr_number}" if pr_number else f"commit:{sha}",
                "metadata": {"commit_sha": sha, "pr_number": pr_number},
            }
        )
    return signals


def collect_task_digest_signals(
    digest_dir: Path, *, limit: int = 40
) -> list[dict[str, Any]]:
    if not digest_dir.exists():
        return []
    files = sorted(
        [p for p in digest_dir.glob("*.json") if p.is_file()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[: max(1, limit)]
    signals: list[dict[str, Any]] = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        reason = str(payload.get("reason", "unknown"))
        branch = str(payload.get("branch", "unknown"))
        change_count = int(payload.get("changes", 0) or 0)
        objective_match = re.search(
            r"\b(E\d+-T\d+)\b", " ".join([reason, branch, str(payload.get("cwd", ""))])
        )
        objective_key = objective_match.group(1).upper() if objective_match else None
        signals.append(
            {
                "signal_id": f"digest-{path.stem}",
                "signal_type": "task_digest",
                "summary": f"Digest reason={reason} branch={branch} changes={change_count}",
                "objective_key": objective_key,
                "captured_at": str(payload.get("timestamp", utc_now())),
                "source_link": f"digest:{path.name}",
                "metadata": {
                    "reason": reason,
                    "branch": branch,
                    "changes": change_count,
                    "cwd": str(payload.get("cwd", "")),
                },
            }
        )
    return signals


def _classify_entry_type(summary_text: str) -> str:
    lowered = summary_text.lower()
    if any(
        term in lowered
        for term in ["hotfix", "incident", "failure", "error", "regress"]
    ):
        return "pitfall"
    if any(
        term in lowered
        for term in ["verify", "verification", "check", "smoke", "validate"]
    ):
        return "checklist"
    if any(term in lowered for term in ["rule", "policy", "contract", "guardrail"]):
        return "rule_candidate"
    return "pattern"


def _base_confidence(signal_types: set[str], source_count: int) -> int:
    score = 45 + min(25, source_count * 10)
    if "merged_pr" in signal_types:
        score += 20
    if "task_digest" in signal_types:
        score += 10
    return max(0, min(100, score))


def generate_draft_entries(
    signals: list[dict[str, Any]], *, now: str | None = None
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        key = str(signal.get("objective_key") or signal.get("signal_id") or "unscoped")
        groups.setdefault(key, []).append(signal)

    timestamp = now or utc_now()
    entries: list[dict[str, Any]] = []
    for key in sorted(groups.keys()):
        batch = groups[key]
        source_links = sorted(
            {
                str(item.get("source_link", ""))
                for item in batch
                if item.get("source_link")
            }
        )
        summaries = [str(item.get("summary", "")) for item in batch]
        combined_summary = " | ".join(item for item in summaries if item)
        signal_types = {str(item.get("signal_type", "unknown")) for item in batch}
        entry_type = _classify_entry_type(combined_summary)
        confidence = _base_confidence(signal_types, len(source_links))
        tags = {
            "domain": ["knowledge-capture"],
            "stage": ["ship", "operate"],
            "risk": "medium" if entry_type == "pitfall" else "low",
            "artifacts": sorted(
                {
                    str(item.get("objective_key", ""))
                    for item in batch
                    if item.get("objective_key")
                }
            ),
        }
        entry = {
            "entry_id": f"kc-{re.sub(r'[^a-z0-9]+', '-', key.lower()).strip('-') or 'entry'}",
            "entry_type": entry_type,
            "title": f"Knowledge capture draft: {key}",
            "summary": combined_summary or f"Captured from {len(batch)} signals",
            "evidence_sources": source_links,
            "confidence_score": confidence,
            "status": "draft",
            "approvals": [],
            "quality_gate_results": [],
            "tags": tags,
            "applies_to": sorted(signal_types),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        entries.append(entry)
    return entries


def evaluate_quality_gates(
    entry: dict[str, Any],
    *,
    target_status: str,
) -> list[dict[str, Any]]:
    sources = [str(item) for item in entry.get("evidence_sources", []) if str(item)]
    confidence = int(entry.get("confidence_score", 0) or 0)
    approvals = (
        entry.get("approvals", []) if isinstance(entry.get("approvals"), list) else []
    )
    high_risk = str(entry.get("tags", {}).get("risk", "low")) == "high"

    gates: list[dict[str, Any]] = []
    if target_status == "review":
        gates.append(
            {
                "gate_id": "review_sources_present",
                "passed": len(sources) >= 1,
                "reason_code": "missing_evidence_sources" if len(sources) < 1 else "ok",
            }
        )
        gates.append(
            {
                "gate_id": "review_confidence",
                "passed": confidence >= 50,
                "reason_code": "insufficient_confidence" if confidence < 50 else "ok",
            }
        )
    elif target_status == "published":
        gates.append(
            {
                "gate_id": "publish_sources_min_two",
                "passed": len(sources) >= 2,
                "reason_code": "missing_evidence_sources" if len(sources) < 2 else "ok",
            }
        )
        gates.append(
            {
                "gate_id": "publish_confidence",
                "passed": confidence >= 75,
                "reason_code": "insufficient_confidence" if confidence < 75 else "ok",
            }
        )
        gates.append(
            {
                "gate_id": "publish_approval",
                "passed": len(approvals) >= 1,
                "reason_code": "missing_reviewer_approval"
                if len(approvals) < 1
                else "ok",
            }
        )
        if high_risk:
            gates.append(
                {
                    "gate_id": "publish_high_risk_second_approval",
                    "passed": len(approvals) >= 2,
                    "reason_code": "high_risk_requires_second_approval"
                    if len(approvals) < 2
                    else "ok",
                }
            )
    elif target_status == "archived":
        archive_reason = str(entry.get("archive_reason", "")).strip()
        gates.append(
            {
                "gate_id": "archive_reason_present",
                "passed": bool(archive_reason),
                "reason_code": "stale_entry_detected" if not archive_reason else "ok",
            }
        )
    return gates


def update_entry(entry: dict[str, Any], **changes: Any) -> dict[str, Any]:
    updated = dict(entry)
    for key, value in changes.items():
        if value is not None:
            updated[key] = value
    updated["updated_at"] = utc_now()
    return updated


def transition_entry(
    entry: dict[str, Any],
    *,
    target_status: str,
    approved_by: str | None = None,
    archive_reason: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if target_status not in LIFECYCLE:
        return entry, ["invalid_target_status"]

    current_status = str(entry.get("status", "draft"))
    if target_status not in TRANSITIONS.get(current_status, set()):
        return entry, ["invalid_transition"]

    working = dict(entry)
    if approved_by:
        approvals = list(working.get("approvals", []))
        approvals.append({"approved_by": approved_by, "approved_at": utc_now()})
        working["approvals"] = approvals
    if archive_reason:
        working["archive_reason"] = archive_reason

    gate_results = evaluate_quality_gates(working, target_status=target_status)
    failures = [
        str(item.get("reason_code", "quality_gate_failed"))
        for item in gate_results
        if not bool(item.get("passed"))
    ]
    if failures:
        working["quality_gate_results"] = gate_results
        working["updated_at"] = utc_now()
        return working, failures

    working["quality_gate_results"] = gate_results
    working["status"] = target_status
    working["updated_at"] = utc_now()
    return working, []


def load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = sorted(entries, key=lambda item: str(item.get("entry_id", "")))
    path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
