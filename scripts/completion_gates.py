#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

VALIDATION_CATEGORIES = {"lint", "test", "typecheck", "build", "security", "custom"}
EVIDENCE_MODES = {"ledger_only", "text_fallback", "hybrid"}


def _split_tokens(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        normalized = raw.replace(";", ",").replace("\n", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(item)
    return out


def marker_category(marker: str) -> str | None:
    value = marker.strip().lower()
    if not value:
        return None
    if "lint" in value:
        return "lint"
    if "test" in value:
        return "test"
    if any(token in value for token in ("type", "tsc", "mypy", "pyright")):
        return "typecheck"
    if any(token in value for token in ("build", "compile")):
        return "build"
    if any(token in value for token in ("security", "audit", "semgrep", "codeql")):
        return "security"
    return None


def derive_markers(
    required_validation: list[str], required_markers: list[str]
) -> list[str]:
    markers = [item.strip().lower() for item in required_markers if item.strip()]
    for category in required_validation:
        token = category.strip().lower()
        if token and token != "custom":
            markers.append(token)
    return _dedupe([item for item in markers if item])


def normalize_completion_gates(
    raw: Any, *, fallback_markers: list[str] | None = None
) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    required_validation = [
        item.lower()
        for item in _split_tokens(source.get("required_validation"))
        if item.lower() in VALIDATION_CATEGORIES
    ]
    required_markers = [
        item.lower() for item in _split_tokens(source.get("required_markers"))
    ]
    if fallback_markers:
        required_markers.extend(
            [item.lower() for item in fallback_markers if str(item).strip()]
        )
    required_markers = derive_markers(required_validation, required_markers)
    evidence_mode = str(source.get("evidence_mode") or "hybrid").strip().lower()
    if evidence_mode not in EVIDENCE_MODES:
        evidence_mode = "hybrid"
    return {
        "required_validation": _dedupe(required_validation),
        "required_markers": required_markers,
        "required_task_ids": _dedupe(
            [item for item in _split_tokens(source.get("required_task_ids"))]
        ),
        "required_owner": str(source.get("required_owner") or "").strip(),
        "allow_bypass": bool(source.get("allow_bypass", False)),
        "evidence_mode": evidence_mode,
    }


def validation_evidence_path(directory: Path) -> Path:
    storage_root = directory.resolve()
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(storage_root),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if root:
            storage_root = Path(root)
    except Exception:
        pass
    return storage_root / ".opencode" / "runtime" / "validation-evidence.json"


def worktree_evidence_key(directory: Path) -> str:
    cwd = str(directory.resolve())
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return f"{root}::{branch or cwd}"
    except Exception:
        return cwd


def load_validation_snapshot(directory: Path) -> dict[str, Any]:
    path = validation_evidence_path(directory)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    key = worktree_evidence_key(directory)
    worktrees = payload.get("worktrees")
    if not isinstance(worktrees, dict):
        return {}
    snapshot = worktrees.get(key)
    return snapshot if isinstance(snapshot, dict) else {}


def _missing_validation(
    snapshot: dict[str, Any], required_validation: list[str]
) -> list[str]:
    missing: list[str] = []
    for category in required_validation:
        if category == "custom":
            missing.append(category)
            continue
        if snapshot.get(category) is not True:
            missing.append(category)
    return missing


def evaluate_completion_gates(
    gates: dict[str, Any],
    *,
    directory: Path,
    completed_task_ids: list[str] | None = None,
    current_owner: str = "",
    completion_text: str = "",
) -> dict[str, Any]:
    normalized = normalize_completion_gates(gates)
    snapshot = load_validation_snapshot(directory)
    required_validation = list(normalized.get("required_validation") or [])
    required_markers = list(normalized.get("required_markers") or [])
    required_task_ids = list(normalized.get("required_task_ids") or [])
    required_owner = str(normalized.get("required_owner") or "").strip()
    evidence_mode = str(normalized.get("evidence_mode") or "hybrid").strip().lower()
    lower_text = completion_text.lower()
    missing_validation = _missing_validation(snapshot, required_validation)
    missing_markers: list[str] = []
    for marker in required_markers:
        category = marker_category(marker)
        if (
            category
            and category in required_validation
            and category not in missing_validation
        ):
            continue
        if evidence_mode in {"text_fallback", "hybrid"} and marker in lower_text:
            continue
        if (
            evidence_mode == "ledger_only"
            and category
            and snapshot.get(category) is True
        ):
            continue
        if category is None and evidence_mode == "ledger_only":
            missing_markers.append(marker)
            continue
        if marker not in missing_markers:
            missing_markers.append(marker)
    completed = set(completed_task_ids or [])
    missing_task_ids = [
        task_id for task_id in required_task_ids if task_id not in completed
    ]
    owner_mismatch = bool(
        required_owner
        and current_owner.strip()
        and required_owner != current_owner.strip()
    )
    blockers: list[str] = []
    blockers.extend([f"validation:{item}" for item in missing_validation])
    blockers.extend([f"marker:{item}" for item in missing_markers])
    blockers.extend([f"task:{item}" for item in missing_task_ids])
    if owner_mismatch:
        blockers.append(f"owner:{required_owner}")
    return {
        "result": "PASS" if not blockers else "FAIL",
        "reason_code": "completion_gates_satisfied"
        if not blockers
        else "completion_gates_blocked",
        "gates": normalized,
        "evidence": snapshot,
        "missing_validation": missing_validation,
        "missing_markers": missing_markers,
        "missing_task_ids": missing_task_ids,
        "owner_mismatch": owner_mismatch,
        "blockers": blockers,
    }
