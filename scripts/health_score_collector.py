#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from checkpoint_snapshot_manager import MAX_AGE_DAYS, list_snapshots  # type: ignore
from release_train_engine import (  # type: ignore
    branch_behind_remote,
    check_validation_targets,
    current_branch,
    is_clean_tree,
)


WEIGHTS_DEFAULT = {
    "validation_health": 35.0,
    "git_release_hygiene": 20.0,
    "runtime_policy_drift": 20.0,
    "automation_reliability": 15.0,
    "operational_freshness": 10.0,
}

STATUS_PENALTY = {"pass": 0.0, "warn": 0.5, "fail": 1.0}
SUPPRESSION_WINDOW_SECONDS = 24 * 60 * 60


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _runtime_dir(write_path: Path) -> Path:
    return write_path.parent / "my_opencode" / "runtime"


def _latest_snapshot_path(write_path: Path) -> Path:
    return _runtime_dir(write_path) / "health_score_latest.json"


def _history_path(write_path: Path) -> Path:
    return _runtime_dir(write_path) / "health_score_history.jsonl"


def _state_path(write_path: Path) -> Path:
    return _runtime_dir(write_path) / "health_score_state.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jobs_failed_count(write_path: Path) -> int:
    jobs_path = write_path.parent / "my_opencode" / "bg" / "jobs.json"
    payload = _read_json(jobs_path)
    jobs = as_list(payload.get("jobs"))
    return len([j for j in jobs if isinstance(j, dict) and j.get("status") == "failed"])


def _read_hotfix_overdue_followups(write_path: Path, now: datetime) -> int:
    runtime_path = _runtime_dir(write_path) / "hotfix_mode.json"
    state = _read_json(runtime_path)
    timeline = as_list(state.get("timeline"))
    overdue = 0
    for event in timeline:
        if not isinstance(event, dict) or event.get("event") != "closed":
            continue
        details = as_dict(event.get("details"))
        deferred = as_dict(details.get("deferred_validation"))
        due_raw = deferred.get("due")
        if not isinstance(due_raw, str):
            continue
        due_dt = _parse_iso(f"{due_raw}T00:00:00Z")
        if due_dt and due_dt < now:
            overdue += 1
    return overdue


def collect_subsystem_signals(
    repo_root: Path,
    config: dict[str, Any],
    write_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_now = now or datetime.now(UTC)
    branch = current_branch(repo_root)
    validations = check_validation_targets(repo_root)
    hooks_cfg = as_dict(config.get("hooks"))
    budget_cfg = as_dict(config.get("budget_runtime"))

    snapshots = list_snapshots(write_path)
    stale_cutoff = observed_now.timestamp() - (MAX_AGE_DAYS * 24 * 60 * 60)
    stale_snapshots = 0
    for snapshot in snapshots:
        snapshot_map = as_dict(snapshot)
        created = _parse_iso(str(snapshot_map.get("created_at") or ""))
        if created and created.timestamp() < stale_cutoff:
            stale_snapshots += 1

    return {
        "observed_at": observed_now.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "validation_targets": {
            "validate": bool(validations.get("validate")),
            "selftest": bool(validations.get("selftest")),
            "install_test": bool(validations.get("install-test")),
        },
        "git": {
            "branch": branch,
            "clean_worktree": is_clean_tree(repo_root),
            "behind_remote": bool(branch and branch_behind_remote(repo_root, branch)),
        },
        "runtime_policy": {
            "budget_profile": str(budget_cfg.get("profile") or "balanced"),
            "hooks_enabled": bool(hooks_cfg.get("enabled", False)),
            "disabled_hooks": as_list(hooks_cfg.get("disabled")),
        },
        "automation": {
            "bg_failed_jobs": _read_jobs_failed_count(write_path),
            "doctor_failed_count": 0,
        },
        "freshness": {
            "stale_checkpoints": stale_snapshots,
            "overdue_followups": _read_hotfix_overdue_followups(
                write_path, observed_now
            ),
            "stale_branches": 0,
        },
    }


def _indicator(
    indicator_id: str,
    status: str,
    weight: float,
    reason_codes: list[str],
    recommendations: list[str],
    observed_at: str,
) -> dict[str, Any]:
    return {
        "indicator_id": indicator_id,
        "status": status,
        "weight": weight,
        "reason_codes": sorted(set(reason_codes)),
        "recommendations": sorted(set(recommendations)),
        "observed_at": observed_at,
    }


def build_indicators(
    signals: dict[str, Any],
    *,
    expected_baselines: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    baseline = {
        "budget_profile": "balanced",
        "hooks_enabled": False,
        "disabled_hooks": [],
    }
    if isinstance(expected_baselines, dict):
        baseline.update(expected_baselines)
    resolved_weights, _ = normalize_weights(weights)
    observed_at = str(signals.get("observed_at") or now_iso())

    validations = as_dict(signals.get("validation_targets"))
    missing_validation = [
        name
        for name in ("validate", "selftest", "install_test")
        if not validations.get(name)
    ]
    validation_status = "pass" if not missing_validation else "fail"
    validation_indicator = _indicator(
        "validation_health",
        validation_status,
        resolved_weights["validation_health"],
        ["validation_suite_failed"] if missing_validation else [],
        ["ensure make validate, make selftest, and make install-test targets pass"]
        if missing_validation
        else [],
        observed_at,
    )

    git = as_dict(signals.get("git"))
    git_reasons: list[str] = []
    git_reco: list[str] = []
    if not git.get("clean_worktree", False):
        git_reasons.append("release_hygiene_failed")
        git_reco.append("commit or stash local changes")
    if git.get("behind_remote", False):
        git_reasons.append("release_hygiene_failed")
        git_reco.append("pull --rebase to sync branch with origin")
    git_indicator = _indicator(
        "git_release_hygiene",
        "pass" if not git_reasons else "fail",
        resolved_weights["git_release_hygiene"],
        git_reasons,
        git_reco,
        observed_at,
    )

    policy = as_dict(signals.get("runtime_policy"))
    drift_reasons: list[str] = []
    drift_reco: list[str] = []
    profile = str(policy.get("budget_profile") or "")
    if profile != str(baseline.get("budget_profile")):
        drift_reasons.append("policy_drift_detected")
        drift_reco.append("restore expected budget profile baseline")
    hooks_enabled = bool(policy.get("hooks_enabled", False))
    if hooks_enabled != bool(baseline.get("hooks_enabled", False)):
        drift_reasons.append("policy_drift_detected")
        drift_reco.append("align hooks enabled state with baseline")
    disabled_hooks = as_list(policy.get("disabled_hooks"))
    if sorted(str(x) for x in disabled_hooks) != sorted(
        str(x) for x in baseline.get("disabled_hooks", [])
    ):
        drift_reasons.append("policy_drift_detected")
        drift_reco.append("re-enable hooks disabled outside baseline policy")
    drift_status = "pass" if not drift_reasons else "warn"
    policy_indicator = _indicator(
        "runtime_policy_drift",
        drift_status,
        resolved_weights["runtime_policy_drift"],
        drift_reasons,
        drift_reco,
        observed_at,
    )

    automation = as_dict(signals.get("automation"))
    automation_reasons: list[str] = []
    automation_reco: list[str] = []
    if int(automation.get("bg_failed_jobs") or 0) > 0:
        automation_reasons.append("automation_failure_detected")
        automation_reco.append("inspect and rerun failed background jobs")
    if int(automation.get("doctor_failed_count") or 0) > 0:
        automation_reasons.append("automation_failure_detected")
        automation_reco.append("resolve failing doctor checks")
    automation_indicator = _indicator(
        "automation_reliability",
        "pass" if not automation_reasons else "fail",
        resolved_weights["automation_reliability"],
        automation_reasons,
        automation_reco,
        observed_at,
    )

    freshness = as_dict(signals.get("freshness"))
    freshness_reasons: list[str] = []
    freshness_reco: list[str] = []
    for key in ("stale_checkpoints", "overdue_followups", "stale_branches"):
        if int(freshness.get(key) or 0) > 0:
            freshness_reasons.append("freshness_stale_signal")
    if freshness_reasons:
        freshness_reco = [
            "prune stale checkpoints and clear aged follow-up debt",
            "close or refresh stale branches and deferred tasks",
        ]
    freshness_indicator = _indicator(
        "operational_freshness",
        "pass" if not freshness_reasons else "warn",
        resolved_weights["operational_freshness"],
        freshness_reasons,
        freshness_reco,
        observed_at,
    )

    return [
        validation_indicator,
        git_indicator,
        policy_indicator,
        automation_indicator,
        freshness_indicator,
    ]


def normalize_weights(
    weights: dict[str, float] | None = None,
) -> tuple[dict[str, float], bool]:
    merged = dict(WEIGHTS_DEFAULT)
    if isinstance(weights, dict):
        for key, value in weights.items():
            if key in merged:
                try:
                    merged[key] = float(value)
                except (TypeError, ValueError):
                    continue
    total = sum(value for value in merged.values() if value > 0)
    if total <= 0:
        return dict(WEIGHTS_DEFAULT), False
    normalized = {key: (value / total) * 100.0 for key, value in merged.items()}
    return normalized, abs(total - 100.0) > 1e-9


def evaluate_health(indicators: list[dict[str, Any]]) -> dict[str, Any]:
    score = 100.0
    reason_codes: set[str] = set()
    recommendations: list[str] = []
    fail_count = 0
    validation_failed = False
    for indicator in indicators:
        status = str(indicator.get("status") or "pass")
        weight = float(indicator.get("weight") or 0.0)
        penalty = STATUS_PENALTY.get(status, 1.0)
        score -= weight * penalty
        if status == "fail":
            fail_count += 1
        if indicator.get("indicator_id") == "validation_health" and status == "fail":
            validation_failed = True
        for code in as_list(indicator.get("reason_codes")):
            reason_codes.add(str(code))
        for item in as_list(indicator.get("recommendations")):
            text = str(item)
            if text and text not in recommendations:
                recommendations.append(text)

    score = max(0.0, min(100.0, round(score, 2)))
    if score >= 85.0:
        status = "healthy"
    elif score >= 60.0:
        status = "degraded"
    else:
        status = "critical"

    if validation_failed and status == "healthy":
        status = "degraded"
        reason_codes.add("critical_indicator_forced_status")
    if fail_count >= 2:
        status = "critical"
        reason_codes.add("critical_indicator_forced_status")

    return {
        "score": score,
        "status": status,
        "reason_codes": sorted(reason_codes),
        "next_actions": recommendations,
    }


def load_health_state(write_path: Path) -> dict[str, Any]:
    path = _state_path(write_path)
    if not path.exists():
        return {"suppression": {}, "updated_at": None}
    payload = _read_json(path)
    suppression = as_dict(payload.get("suppression"))
    return {"suppression": suppression, "updated_at": payload.get("updated_at")}


def save_health_state(write_path: Path, state: dict[str, Any]) -> None:
    path = _state_path(write_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def apply_suppression_window(
    indicators: list[dict[str, Any]],
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    window_seconds: int = SUPPRESSION_WINDOW_SECONDS,
    force_alert: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    observed = now or datetime.now(UTC)
    suppression = as_dict(state.get("suppression"))
    emitted = 0
    suppressed = 0

    for indicator in indicators:
        status = str(indicator.get("status") or "pass")
        if status == "pass":
            continue
        reason_codes = [str(code) for code in as_list(indicator.get("reason_codes"))]
        indicator_id = str(indicator.get("indicator_id") or "unknown")
        is_critical = status == "fail"
        for code in reason_codes:
            key = f"{indicator_id}:{code}"
            row = as_dict(suppression.get(key))
            first_seen = str(row.get("first_seen_at") or now_iso())
            last_emitted = _parse_iso(str(row.get("last_emitted_at") or ""))
            since_emit = (
                None
                if last_emitted is None
                else int((observed - last_emitted).total_seconds())
            )
            window_active = (
                False
                if force_alert or is_critical or last_emitted is None
                else since_emit is not None and since_emit < window_seconds
            )
            if window_active:
                suppressed += 1
                suppression[key] = {
                    "suppression_key": key,
                    "first_seen_at": first_seen,
                    "last_emitted_at": row.get("last_emitted_at"),
                    "suppressed_count": int(row.get("suppressed_count") or 0) + 1,
                    "window_seconds": window_seconds,
                }
                continue

            emitted += 1
            suppression[key] = {
                "suppression_key": key,
                "first_seen_at": first_seen,
                "last_emitted_at": observed.replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "suppressed_count": int(row.get("suppressed_count") or 0),
                "window_seconds": window_seconds,
            }

    next_state = {
        "suppression": suppression,
        "updated_at": observed.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    summary = {
        "active": suppressed > 0,
        "suppressed_count": suppressed,
        "emitted_count": emitted,
        "window_seconds": window_seconds,
    }
    return summary, next_state


def persist_health_snapshot(
    write_path: Path, snapshot: dict[str, Any]
) -> dict[str, str]:
    runtime_dir = _runtime_dir(write_path)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    latest_path = _latest_snapshot_path(write_path)
    history_path = _history_path(write_path)
    latest_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True) + "\n")
    return {"latest": str(latest_path), "history": str(history_path)}


def run_health_collection(
    repo_root: Path,
    config: dict[str, Any],
    write_path: Path,
    *,
    expected_baselines: dict[str, Any] | None = None,
    custom_weights: dict[str, float] | None = None,
    force_alert: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    signals = collect_subsystem_signals(repo_root, config, write_path, now=now)
    indicators = build_indicators(
        signals,
        expected_baselines=expected_baselines,
        weights=custom_weights,
    )
    score = evaluate_health(indicators)
    state = load_health_state(write_path)
    suppression, next_state = apply_suppression_window(
        indicators,
        state,
        now=now,
        force_alert=force_alert,
    )
    save_health_state(write_path, next_state)

    snapshot = {
        "observed_at": str(signals.get("observed_at") or now_iso()),
        "score": score.get("score"),
        "status": score.get("status"),
        "indicators": indicators,
        "reason_codes": score.get("reason_codes", []),
        "next_actions": score.get("next_actions", []),
        "suppression": suppression,
        "weight_normalized": normalize_weights(custom_weights)[1],
    }
    snapshot["paths"] = persist_health_snapshot(write_path, snapshot)
    return snapshot
