#!/usr/bin/env python3

from __future__ import annotations

import fnmatch
import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from background_task_manager import enqueue_job  # type: ignore
from runtime_audit import append_event  # type: ignore
from governance_policy import check_operation  # type: ignore
from model_routing_command import resolve_for_entrypoint  # type: ignore
from task_graph_bridge import (  # type: ignore
    sync_workflow_run_to_task_graph,
    task_graph_status_snapshot,
    task_graph_runtime_path,
)


DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_WORKFLOW_STATE_PATH",
        "~/.config/opencode/my_opencode/runtime/workflow_state.json",
    )
).expanduser()

DEFAULT_TEMPLATE_DIR = Path(
    os.environ.get(
        "MY_OPENCODE_WORKFLOW_TEMPLATE_DIR",
        "~/.config/opencode/my_opencode/workflows",
    )
).expanduser()
DEFAULT_CLAIMS_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_CLAIMS_PATH",
        "~/.config/opencode/my_opencode/runtime/claims.json",
    )
).expanduser()
DEFAULT_AGENT_POOL_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_AGENT_POOL_PATH",
        "~/.config/opencode/my_opencode/runtime/agent_pool.json",
    )
).expanduser()
DEFAULT_RESERVATION_STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_RESERVATION_STATE_PATH",
        ".opencode/reservation-state.json",
    )
).expanduser()
DEFAULT_BG_DIR = Path(
    os.environ.get("MY_OPENCODE_BG_DIR", "~/.config/opencode/my_opencode/bg")
).expanduser()
SWARM_ROLE_SEQUENCE = ["discover", "implement", "review", "verify", "release-prep"]
ALLOWED_BG_PYTHON_SCRIPTS = {
    "scripts/doctor_command.py",
    "scripts/selftest.py",
}
ALLOWED_BG_MAKE_COMMANDS = {
    ("make", "install-test"),
    ("make", "selftest"),
    ("make", "validate"),
}


def entrypoint_model_routing() -> dict[str, Any]:
    return resolve_for_entrypoint("workflow")


def attach_model_routing(
    target: dict[str, Any], routing: dict[str, Any]
) -> dict[str, Any]:
    target["model_routing"] = routing
    return target


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def usage() -> int:
    print(
        "usage: /workflow run --file <path> [--execute] [--override] [--json] | /workflow validate --file <path> [--json] | "
        "/workflow list [--json] | /workflow status [--json] | /workflow resume --run-id <id> [--execute] [--override] [--json] | "
        "/workflow stop [--reason <text>] [--json] | /workflow swarm <plan|status|doctor|handoff|accept-handoff|complete-lane|fail-lane|reset-lane|retry-lane|reassign-lane|resolve-failure|rebalance|close> ... | /workflow template list [--json] | /workflow template init <name> [--json] | /workflow doctor [--json]"
    )
    return 2


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def save_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def history_list(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_history = state.get("history")
    if not isinstance(raw_history, list):
        state["history"] = []
        return state["history"]
    return [item for item in raw_history if isinstance(item, dict)]


def active_record(state: dict[str, Any]) -> dict[str, Any]:
    raw_active = state.get("active")
    if isinstance(raw_active, dict):
        return raw_active
    state["active"] = {}
    return state["active"]


def swarm_state(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("swarm")
    if isinstance(raw, dict):
        raw.setdefault("active", {})
        raw.setdefault("history", [])
        return raw
    state["swarm"] = {"active": {}, "history": []}
    return state["swarm"]


def swarm_history_list(state: dict[str, Any]) -> list[dict[str, Any]]:
    swarm = swarm_state(state)
    raw_history = swarm.get("history")
    if not isinstance(raw_history, list):
        swarm["history"] = []
        return swarm["history"]
    return [item for item in raw_history if isinstance(item, dict)]


def active_swarm_record(state: dict[str, Any]) -> dict[str, Any]:
    swarm = swarm_state(state)
    raw_active = swarm.get("active")
    if isinstance(raw_active, dict):
        return raw_active
    swarm["active"] = {}
    return swarm["active"]


def next_swarm_id(state: dict[str, Any]) -> str:
    max_seq = 0
    candidates: list[dict[str, Any]] = []
    active = active_swarm_record(state)
    if active:
        candidates.append(active)
    candidates.extend(swarm_history_list(state))
    prefix = "swarm-plan-"
    for item in candidates:
        raw = str(item.get("swarm_id") or "")
        if not raw.startswith(prefix):
            continue
        suffix = raw[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:06d}"


def next_run_id(state: dict[str, Any]) -> str:
    max_seq = 0
    candidates: list[dict[str, Any]] = []
    active = active_record(state)
    if active:
        candidates.append(active)
    candidates.extend(history_list(state))
    prefix = "wf-run-"
    for item in candidates:
        raw = str(item.get("run_id") or "")
        if not raw.startswith(prefix):
            continue
        suffix = raw[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:06d}"


def parse_flag_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [part.strip() for part in raw.replace(";", ",").split(",")]
    return [part for part in parts if part]


def load_claim_rows() -> dict[str, dict[str, Any]]:
    payload = load_json_file(DEFAULT_CLAIMS_PATH)
    claims = payload.get("claims")
    if not isinstance(claims, dict):
        return {}
    return {str(key): value for key, value in claims.items() if isinstance(value, dict)}


def load_pool_agents() -> list[dict[str, Any]]:
    payload = load_json_file(DEFAULT_AGENT_POOL_PATH)
    agents = payload.get("agents")
    if not isinstance(agents, list):
        return []
    return [item for item in agents if isinstance(item, dict)]


def load_reservation_snapshot() -> dict[str, Any]:
    payload = load_json_file(DEFAULT_RESERVATION_STATE_PATH)
    return {
        "reservationActive": bool(
            payload.get("reservationActive", payload.get("active", False))
        ),
        "writerCount": int(
            payload.get("writerCount", payload.get("writer_count", 0)) or 0
        ),
        "ownPaths": [
            str(item)
            for item in (payload.get("ownPaths") or payload.get("own_paths") or [])
            if str(item).strip()
        ],
        "activePaths": [
            str(item)
            for item in (
                payload.get("activePaths") or payload.get("active_paths") or []
            )
            if str(item).strip()
        ],
        "leaseId": str(payload.get("leaseId") or payload.get("lease_id") or "").strip()
        or None,
        "leaseOwner": str(
            payload.get("leaseOwner") or payload.get("lease_owner") or ""
        ).strip()
        or None,
        "leaseUpdatedAt": str(
            payload.get("leaseUpdatedAt") or payload.get("lease_updated_at") or ""
        ).strip()
        or None,
    }


def choose_agent_owner(
    agents: list[dict[str, Any]], lane_type: str, *, exclude_owner: str | None = None
) -> str | None:
    active = [item for item in agents if str(item.get("status") or "") == "active"]
    exact = [item for item in active if str(item.get("role") or "") == lane_type]
    candidates = exact or active
    if exclude_owner:
        candidates = [
            item
            for item in candidates
            if f"agent:{str(item.get('agent_id') or '').strip()}" != exclude_owner
        ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            int(item.get("load", 0) or 0),
            str(item.get("agent_id") or ""),
        )
    )
    agent_id = str(candidates[0].get("agent_id") or "").strip()
    return f"agent:{agent_id}" if agent_id else None


def valid_lane_owner(owner: str, agents: list[dict[str, Any]]) -> bool:
    text = owner.strip()
    if not text:
        return False
    if text.startswith("human:"):
        return True
    if text.startswith("agent:"):
        return text in active_agent_map(agents)
    return False


def build_swarm_lanes(
    *,
    objective: str,
    lane_count: int,
    claim_ids: list[str],
    writer_paths: list[str],
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lane_types = SWARM_ROLE_SEQUENCE[: max(1, lane_count)]
    lanes: list[dict[str, Any]] = []
    for idx, lane_type in enumerate(lane_types, start=1):
        lane_id = f"lane-{idx}"
        owner = choose_agent_owner(agents, lane_type)
        if lane_type == "discover":
            depends_on: list[str] = []
        elif lane_type == "implement":
            depends_on = ["lane-1"]
        elif lane_type == "review":
            depends_on = ["lane-2"]
        elif lane_type == "verify":
            depends_on = ["lane-2"]
        elif lane_type == "release-prep":
            depends_on = [
                str(lane.get("lane_id") or "")
                for lane in lanes
                if str(lane.get("lane_type") or "") in {"review", "verify"}
                and str(lane.get("lane_id") or "").strip()
            ]
        else:
            depends_on = [lanes[-1]["lane_id"]] if lanes else []
        lanes.append(
            {
                "lane_id": lane_id,
                "lane_type": lane_type,
                "objective": f"{lane_type} lane for {objective}",
                "owner": owner,
                "claim_ids": claim_ids,
                "depends_on": depends_on,
                "dependency_mode": "generated-v1",
                "writer_paths": writer_paths if lane_type == "implement" else [],
                "path_scopes": writer_paths if lane_type == "implement" else ["**/*"],
                "lease_identity": owner if lane_type == "implement" else None,
                "lease_identity_mode": "derived" if lane_type == "implement" else None,
                "access_mode": "write" if lane_type == "implement" else "read",
                "reservation_mode": "writer-reserved"
                if lane_type == "implement"
                else "reservation-safe-read",
                "status": "planned",
            }
        )
    return lanes


def load_swarm_graph(path: Path) -> tuple[list[dict[str, Any]] | None, list[str]]:
    if not path.exists():
        return None, [f"swarm graph file not found: {path}"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"invalid swarm graph json: {exc}"]
    if not isinstance(raw, dict):
        return None, ["swarm graph root must be object"]
    lanes = raw.get("lanes")
    if not isinstance(lanes, list):
        return None, ["swarm graph must include lanes array"]
    normalized = [lane for lane in lanes if isinstance(lane, dict)]
    return normalized, validate_swarm_graph(normalized)


def validate_swarm_graph(lanes: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    lane_ids: set[str] = set()
    for idx, lane in enumerate(lanes, start=1):
        lane_id = str(lane.get("lane_id") or "").strip()
        lane_type = str(lane.get("lane_type") or "").strip()
        if not lane_id:
            issues.append(f"lane {idx} missing lane_id")
            continue
        if lane_id in lane_ids:
            issues.append(f"duplicate lane_id: {lane_id}")
        lane_ids.add(lane_id)
        if not lane_type:
            issues.append(f"lane {lane_id} missing lane_type")
        depends = lane.get("depends_on")
        if depends is not None and not isinstance(depends, list):
            issues.append(f"lane {lane_id} depends_on must be list")
        writer_paths = lane.get("writer_paths")
        if writer_paths is not None and not isinstance(writer_paths, list):
            issues.append(f"lane {lane_id} writer_paths must be list")
        path_scopes = lane.get("path_scopes")
        if path_scopes is not None and not isinstance(path_scopes, list):
            issues.append(f"lane {lane_id} path_scopes must be list")
        lease_identity = lane.get("lease_identity")
        if lease_identity is not None and not isinstance(lease_identity, str):
            issues.append(f"lane {lane_id} lease_identity must be string")
        lease_identity_mode = lane.get("lease_identity_mode")
        if lease_identity_mode is not None and lease_identity_mode not in {
            "derived",
            "explicit",
        }:
            issues.append(
                f"lane {lane_id} lease_identity_mode must be derived|explicit"
            )
    if issues:
        return issues
    graph = {str(lane.get("lane_id") or ""): lane_dependencies(lane) for lane in lanes}
    for lane_id, deps in graph.items():
        for dep in deps:
            if dep not in graph:
                issues.append(f"lane {lane_id} depends on unknown lane {dep}")
    if issues:
        return issues
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visited:
            return True
        if node in visiting:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if not visit(dep):
                return False
        visiting.remove(node)
        visited.add(node)
        return True

    for node in graph:
        if not visit(node):
            issues.append("swarm graph dependency cycle detected")
            break
    return issues


def materialize_swarm_graph(
    *,
    objective: str,
    graph_lanes: list[dict[str, Any]],
    claim_ids: list[str],
    writer_paths: list[str],
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for lane in graph_lanes:
        lane_type = str(lane.get("lane_type") or "").strip()
        writer_paths_value = (
            [str(item) for item in lane.get("writer_paths", []) if str(item).strip()]
            if isinstance(lane.get("writer_paths"), list)
            else (writer_paths if lane_type == "implement" else [])
        )
        materialized = {
            "lane_id": str(lane.get("lane_id") or "").strip(),
            "lane_type": lane_type,
            "objective": str(
                lane.get("objective") or f"{lane_type} lane for {objective}"
            ),
            "owner": str(
                lane.get("owner") or choose_agent_owner(agents, lane_type) or ""
            ).strip()
            or None,
            "claim_ids": claim_ids,
            "depends_on": lane_dependencies(lane),
            "dependency_mode": "custom-v1",
            "writer_paths": writer_paths_value,
            "path_scopes": [
                str(item) for item in lane.get("path_scopes", []) if str(item).strip()
            ]
            if isinstance(lane.get("path_scopes"), list)
            else (writer_paths_value or ["**/*"]),
            "lease_identity": (str(lane.get("lease_identity") or "").strip() or None)
            if lane.get("lease_identity") is not None
            else (
                (
                    str(
                        lane.get("owner") or choose_agent_owner(agents, lane_type) or ""
                    ).strip()
                    or None
                )
                if writer_paths_value
                else None
            ),
            "lease_identity_mode": (
                "explicit"
                if lane.get("lease_identity") is not None
                else ("derived" if writer_paths_value else None)
            ),
            "access_mode": "read" if not writer_paths_value else "write",
            "reservation_mode": "reservation-safe-read"
            if not writer_paths_value
            else "writer-reserved",
            "status": "planned",
        }
        lanes.append(materialized)
    return lanes


def parse_command_tokens(raw_command: str) -> list[str]:
    return [token for token in shlex.split(raw_command) if str(token).strip()]


def validate_background_tokens(
    tokens: list[str], *, cwd_value: str
) -> tuple[bool, str | None]:
    if not tokens:
        return False, "background command is empty"
    executable = tokens[0]
    if executable not in {"python3", "make"}:
        return False, f"background executable not allowed: {executable}"
    if executable == "make":
        token_tuple = tuple(tokens)
        if token_tuple not in ALLOWED_BG_MAKE_COMMANDS:
            return False, "background make command must exactly match the allowlist"
    if executable == "python3":
        if len(tokens) != 2:
            return False, "background python3 command must exactly match the allowlist"
        script_target = tokens[1]
        if not script_target.startswith("scripts/"):
            return False, "background python3 command must target scripts/*"
        resolved_cwd = Path(cwd_value).expanduser().resolve()
        scripts_root = (resolved_cwd / "scripts").resolve()
        resolved_script = (resolved_cwd / script_target).resolve()
        try:
            resolved_script.relative_to(scripts_root)
        except ValueError:
            return False, "background python3 command must stay within scripts/"
        normalized_target = str(Path(script_target).as_posix())
        if normalized_target not in ALLOWED_BG_PYTHON_SCRIPTS:
            return (
                False,
                f"background python3 script not allowed: {normalized_target}",
            )
    return True, None


def start_background_job(
    *, tokens: list[str], cwd_value: str, labels: list[str]
) -> dict[str, Any] | None:
    job = enqueue_job(
        command_tokens=tokens,
        cwd_value=cwd_value,
        labels=labels,
        timeout_seconds=1200,
        stale_after_seconds=1800,
    )
    if job is None:
        return None
    worker = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "background_task_manager.py"),
            "run",
            "--id",
            str(job["id"]),
        ],
        cwd=str(Path(job["cwd"])),
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    job["worker_pid"] = worker.pid
    return job


def background_job_status(job_id: str) -> str | None:
    jobs_path = DEFAULT_BG_DIR / "jobs.json"
    payload = load_json_file(jobs_path)
    raw_jobs = payload.get("jobs")
    jobs: list[dict[str, Any]] = (
        [job for job in raw_jobs if isinstance(job, dict)]
        if isinstance(raw_jobs, list)
        else []
    )
    for job in jobs:
        if isinstance(job, dict) and str(job.get("id") or "") == job_id:
            return str(job.get("status") or "") or None
    return "unknown" if job_id.strip() else None


def lane_rows(active: dict[str, Any]) -> list[dict[str, Any]]:
    raw = active.get("lanes")
    if not isinstance(raw, list):
        active["lanes"] = []
        return active["lanes"]
    return [item for item in raw if isinstance(item, dict)]


def lane_map(active: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("lane_id") or ""): item
        for item in lane_rows(active)
        if str(item.get("lane_id") or "").strip()
    }


def lane_dependencies(lane: dict[str, Any]) -> list[str]:
    raw = lane.get("depends_on")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def lane_writer_paths(lane: dict[str, Any]) -> list[str]:
    raw = lane.get("writer_paths")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def lane_path_scopes(lane: dict[str, Any]) -> list[str]:
    raw = lane.get("path_scopes")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    writer_paths = lane_writer_paths(lane)
    if writer_paths:
        return writer_paths
    return ["**/*"] if is_read_only_lane(lane) else []


def scopes_overlap(left: list[str], right: list[str]) -> bool:
    left_set = {item.strip().replace("\\", "/") for item in left if item.strip()}
    right_set = {item.strip().replace("\\", "/") for item in right if item.strip()}
    if not left_set or not right_set:
        return False
    if "**/*" in left_set or "**/*" in right_set:
        return True
    if bool(left_set & right_set):
        return True

    def static_prefix(pattern: str) -> str:
        parts: list[str] = []
        for part in pattern.split("/"):
            if any(token in part for token in "*?["):
                break
            if not part:
                continue
            parts.append(part)
        return "/".join(parts)

    def is_literal(pattern: str) -> bool:
        return not any(token in pattern for token in "*?[")

    def prefix_overlap(a: str, b: str) -> bool:
        if not a or not b:
            return False
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")

    def literal_suffix(pattern: str) -> str | None:
        name = pattern.split("/")[-1]
        suffix = Path(name).suffix
        if not suffix or any(token in suffix for token in "*?["):
            return None
        return suffix

    for left_pattern in left_set:
        for right_pattern in right_set:
            left_prefix = static_prefix(left_pattern)
            right_prefix = static_prefix(right_pattern)
            if prefix_overlap(left_prefix, right_prefix):
                left_suffix = literal_suffix(left_pattern)
                right_suffix = literal_suffix(right_pattern)
                if left_suffix and right_suffix and left_suffix != right_suffix:
                    continue
                return True
            if is_literal(left_pattern) and fnmatch.fnmatch(
                left_pattern, right_pattern
            ):
                return True
            if is_literal(right_pattern) and fnmatch.fnmatch(
                right_pattern, left_pattern
            ):
                return True
    return False


def is_read_only_lane(lane: dict[str, Any]) -> bool:
    return not lane_writer_paths(lane)


def lane_access_mode(lane: dict[str, Any]) -> str:
    return "read" if is_read_only_lane(lane) else "write"


def lane_reservation_mode(lane: dict[str, Any]) -> str:
    return "reservation-safe-read" if is_read_only_lane(lane) else "writer-reserved"


def lane_lease_identity(lane: dict[str, Any]) -> str | None:
    value = str(lane.get("lease_identity") or "").strip()
    return value or None


def lane_lease_identity_mode(lane: dict[str, Any]) -> str | None:
    value = str(lane.get("lease_identity_mode") or "").strip()
    return value or None


def reservation_safe_read_enabled(active: dict[str, Any]) -> bool:
    reservation = active.get("reservation")
    if not isinstance(reservation, dict):
        return False
    if not bool(reservation.get("reservationActive")):
        return False
    active_paths = reservation.get("activePaths")
    if not isinstance(active_paths, list) or not any(
        str(item).strip() for item in active_paths
    ):
        return False
    return True


def reservation_lease_fresh(
    active: dict[str, Any], max_age_minutes: int = 30, max_future_minutes: int = 5
) -> bool:
    reservation = active.get("reservation")
    if not isinstance(reservation, dict):
        return False
    updated_at = str(reservation.get("leaseUpdatedAt") or "").strip()
    if not updated_at:
        return False
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if updated.tzinfo is None:
        return False
    now = datetime.now(UTC)
    if updated < now - timedelta(minutes=max_age_minutes):
        return False
    if updated > now + timedelta(minutes=max_future_minutes):
        return False
    return True


def reservation_writer_guarantees_enabled(active: dict[str, Any]) -> bool:
    reservation = active.get("reservation")
    if not isinstance(reservation, dict):
        return False
    if not bool(reservation.get("reservationActive")):
        return False
    if int(reservation.get("writerCount", 0) or 0) < 2:
        return False
    if not str(reservation.get("leaseId") or "").strip():
        return False
    if not str(reservation.get("leaseOwner") or "").strip():
        return False
    if not reservation_lease_fresh(active):
        return False
    if not reservation_covers_scopes(active, reservation_active_paths(active)):
        return False
    active_write_lanes = [
        lane
        for lane in lane_rows(active)
        if str(lane.get("status") or "") == "active" and not is_read_only_lane(lane)
    ]
    return all(
        reservation_covers_scopes(active, lane_path_scopes(lane))
        for lane in active_write_lanes
    ) and all(
        reservation_owner_covers_scopes(active, lane_path_scopes(lane))
        for lane in active_write_lanes
    )


def writer_lease_owner(active: dict[str, Any]) -> str | None:
    reservation = active.get("reservation")
    if not isinstance(reservation, dict):
        return None
    owner = str(reservation.get("leaseOwner") or "").strip()
    return owner or None


def active_write_owner_match(active: dict[str, Any], owner: str) -> bool:
    for lane in lane_rows(active):
        if str(lane.get("status") or "") != "active":
            continue
        if is_read_only_lane(lane):
            continue
        if str(lane.get("owner") or "").strip() != owner:
            return False
    return True


def writer_parallel_candidates(active: dict[str, Any]) -> list[str]:
    if not reservation_writer_guarantees_enabled(active):
        return []
    lanes = sorted(lane_rows(active), key=_lane_sort_key)
    lane_by_id = lane_map(active)
    active_write_lanes = [
        lane
        for lane in lanes
        if str(lane.get("status") or "") == "active" and not is_read_only_lane(lane)
    ]
    selected_scopes = [lane_path_scopes(lane) for lane in active_write_lanes]
    selected_ids = [str(lane.get("lane_id") or "") for lane in active_write_lanes]
    writer_count = (
        int(active.get("reservation", {}).get("writerCount", 0) or 0)
        if isinstance(active.get("reservation"), dict)
        else 0
    )
    remaining_capacity = max(0, writer_count - len(selected_ids))
    if remaining_capacity == 0:
        return []
    candidates: list[str] = []
    for lane in lanes:
        lane_id = str(lane.get("lane_id") or "")
        if not lane_id or lane_id in selected_ids:
            continue
        if is_read_only_lane(lane):
            continue
        if str(lane.get("lane_type") or "") != "implement":
            continue
        if str(lane.get("status") or "") not in {"planned", "handoff-pending"}:
            continue
        lane_lease_owner = lane_lease_identity(lane)
        if lane_lease_owner and lane_lease_owner != writer_lease_owner(active):
            continue
        if not reservation_covers_scopes(active, lane_path_scopes(lane)):
            continue
        if not reservation_owner_covers_scopes(active, lane_path_scopes(lane)):
            continue
        if not all(
            isinstance(lane_by_id.get(dep), dict)
            and str(lane_by_id[dep].get("status") or "") == "completed"
            for dep in lane_dependencies(lane)
        ):
            continue
        if any(
            scopes_overlap(lane_path_scopes(lane), scopes) for scopes in selected_scopes
        ):
            continue
        candidates.append(lane_id)
        selected_ids.append(lane_id)
        selected_scopes.append(lane_path_scopes(lane))
        if len(candidates) >= remaining_capacity:
            break
    return candidates


def reservation_active_paths(active: dict[str, Any]) -> list[str]:
    reservation = active.get("reservation")
    if not isinstance(reservation, dict):
        return []
    raw = reservation.get("activePaths")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def reservation_own_paths(active: dict[str, Any]) -> list[str]:
    reservation = active.get("reservation")
    if not isinstance(reservation, dict):
        return []
    raw = reservation.get("ownPaths")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def reservation_covers_scopes(active: dict[str, Any], scopes: list[str]) -> bool:
    return scopes_covered_by_paths(reservation_active_paths(active), scopes)


def reservation_owner_covers_scopes(active: dict[str, Any], scopes: list[str]) -> bool:
    return scopes_covered_by_paths(reservation_own_paths(active), scopes)


def scopes_covered_by_paths(paths: list[str], scopes: list[str]) -> bool:
    active_paths = [path for path in paths if str(path).strip()]
    if not active_paths:
        return False
    if "**/*" in active_paths:
        return True

    def is_literal(pattern: str) -> bool:
        return not any(token in pattern for token in "*?[")

    def static_prefix(pattern: str) -> str:
        parts: list[str] = []
        for part in pattern.split("/"):
            if any(token in part for token in "*?["):
                break
            if not part:
                continue
            parts.append(part)
        return "/".join(parts)

    def literal_suffix(pattern: str) -> str | None:
        name = pattern.split("/")[-1]
        suffix = Path(name).suffix
        if not suffix or any(token in suffix for token in "*?["):
            return None
        return suffix

    def scope_covered_by(reserved: str, scope: str) -> bool:
        reserved = reserved.strip().replace("\\", "/")
        scope = scope.strip().replace("\\", "/")
        if not reserved or not scope:
            return False
        if reserved == "**/*" or reserved == scope:
            return True
        if is_literal(scope):
            return fnmatch.fnmatch(scope, reserved)
        if is_literal(reserved):
            return False
        # Conservative: for wildcard-vs-wildcard coverage, only accept exact matches.
        return False

    for scope in scopes:
        if not scope.strip():
            continue
        if not any(
            scope_covered_by(active_path, scope) for active_path in active_paths
        ):
            return False
    return True


def sync_swarm_reservation(active: dict[str, Any]) -> None:
    active["reservation"] = load_reservation_snapshot()


def transitive_dependency_ids(active: dict[str, Any], lane_id: str) -> set[str]:
    lane_by_id = lane_map(active)
    seen: set[str] = set()
    stack = [lane_id]
    while stack:
        current = stack.pop()
        lane = lane_by_id.get(current)
        if not isinstance(lane, dict):
            continue
        for dep in lane_dependencies(lane):
            if dep in seen:
                continue
            seen.add(dep)
            stack.append(dep)
    return seen


def active_agent_map(agents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in agents:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") != "active":
            continue
        agent_id = str(item.get("agent_id") or "").strip()
        if not agent_id:
            continue
        result[f"agent:{agent_id}"] = item
    return result


def sync_swarm_history(state: dict[str, Any], active: dict[str, Any]) -> None:
    swarm = swarm_state(state)
    history = swarm_history_list(state)
    if history and history[0].get("swarm_id") == active.get("swarm_id"):
        history[0] = dict(active)
    else:
        history.insert(0, dict(active))
    swarm["history"] = history[:50]


def refresh_swarm_status(active: dict[str, Any]) -> None:
    lanes = lane_rows(active)
    statuses = {str(item.get("status") or "planned") for item in lanes}
    if not lanes:
        active["status"] = "idle"
        return
    if statuses == {"completed"}:
        active["status"] = "completed"
        return
    if "failed" in statuses:
        active["status"] = "failed"
        return
    if statuses == {"closed"}:
        active["status"] = "closed"
        return
    if "handoff-pending" in statuses:
        active["status"] = "handoff-pending"
        return
    if "active" in statuses:
        active["status"] = "active"
        return
    active["status"] = "planned"


def progression_summary(active: dict[str, Any]) -> dict[str, Any]:
    lanes = lane_rows(active)
    ordered = sorted(lanes, key=lambda lane: str(lane.get("lane_id") or ""))
    next_lane = next(
        (
            lane
            for lane in ordered
            if str(lane.get("status") or "planned")
            in {"planned", "handoff-pending", "active"}
        ),
        None,
    )
    completed = [
        lane for lane in ordered if str(lane.get("status") or "") == "completed"
    ]
    failed = [lane for lane in ordered if str(lane.get("status") or "") == "failed"]
    return {
        "completed_count": len(completed),
        "failed_count": len(failed),
        "next_lane_id": str(next_lane.get("lane_id") or "")
        if isinstance(next_lane, dict)
        else None,
        "all_completed": bool(ordered) and len(completed) == len(ordered),
    }


def update_swarm_progress(active: dict[str, Any]) -> None:
    summary = progression_summary(active)
    active["progress"] = summary
    if summary["all_completed"]:
        active["completed_at"] = now_iso()


def _lane_sort_key(lane: dict[str, Any]) -> tuple[int, str]:
    lane_id = str(lane.get("lane_id") or "")
    if lane_id.startswith("lane-"):
        suffix = lane_id[5:]
        if suffix.isdigit():
            return (int(suffix), lane_id)
    return (999999, lane_id)


def apply_swarm_followups(
    active: dict[str, Any], agents: list[dict[str, Any]], *, auto_progress: bool
) -> None:
    lanes = sorted(lane_rows(active), key=_lane_sort_key)
    followups: list[dict[str, Any]] = []
    if not lanes:
        active["followups"] = followups
        return
    failed_lane = next(
        (lane for lane in lanes if str(lane.get("status") or "") == "failed"), None
    )
    if isinstance(failed_lane, dict):
        followups.append(
            {
                "type": "resolve-failure",
                "lane_id": str(failed_lane.get("lane_id") or ""),
                "reason": str(failed_lane.get("failure_reason") or "lane failed"),
            }
        )
        active["followups"] = followups
        return
    active_or_pending = any(
        str(lane.get("status") or "") in {"active", "handoff-pending"} for lane in lanes
    )
    if active_or_pending:
        current_lane = next(
            (
                lane
                for lane in lanes
                if str(lane.get("status") or "") in {"active", "handoff-pending"}
            ),
            None,
        )
        if isinstance(current_lane, dict):
            followups.append(
                {
                    "type": "monitor-active-lane",
                    "lane_id": str(current_lane.get("lane_id") or ""),
                    "status": str(current_lane.get("status") or ""),
                }
            )
    if auto_progress and not active_or_pending:
        next_planned = next(
            (
                lane
                for lane in lanes
                if str(lane.get("status") or "") == "planned"
                and can_activate_lane(
                    active,
                    str(lane.get("lane_id") or ""),
                    str(lane.get("lane_type") or ""),
                )
            ),
            None,
        )
        if isinstance(next_planned, dict):
            owner = str(next_planned.get("owner") or "").strip()
            if not owner:
                owner = (
                    choose_agent_owner(agents, str(next_planned.get("lane_type") or ""))
                    or ""
                )
                if owner:
                    next_planned["owner"] = owner
            next_planned["status"] = "handoff-pending"
            next_planned["auto_progressed_at"] = now_iso()
            followups.append(
                {
                    "type": "accept-next-lane",
                    "lane_id": str(next_planned.get("lane_id") or ""),
                    "owner": owner or None,
                }
            )
    if (
        not followups
        and lanes
        and all(str(lane.get("status") or "") == "completed" for lane in lanes)
    ):
        followups.append({"type": "swarm-complete", "message": "all lanes completed"})
    active["followups"] = followups


def lane_failure_policy(
    active: dict[str, Any], failed_lane: dict[str, Any]
) -> dict[str, Any]:
    lanes = sorted(lane_rows(active), key=_lane_sort_key)
    lane_by_id = lane_map(active)
    failed_lane_id = str(failed_lane.get("lane_id") or "")
    failed_index = next(
        (
            idx
            for idx, lane in enumerate(lanes)
            if str(lane.get("lane_id") or "") == failed_lane_id
        ),
        -1,
    )
    blockers: list[str] = []
    for lane in lanes:
        lane_id = str(lane.get("lane_id") or "")
        if lane_id == failed_lane_id:
            continue
        if str(lane.get("status") or "") not in {
            "planned",
            "handoff-pending",
            "active",
        }:
            continue
        if failed_lane_id in lane_dependencies(lane):
            blockers.append(lane_id)
    retry_count = int(failed_lane.get("retry_count", 0) or 0)
    failure_reason = (
        str(failed_lane.get("failure_reason") or "lane failed").strip().lower()
    )
    recommended_action = "retry-lane"
    if retry_count >= 1:
        recommended_action = "reset-lane"
    if any(token in failure_reason for token in {"owner", "handoff", "assignee"}):
        recommended_action = "reassign-lane"
    return {
        "policy": "halt_downstream_on_failure",
        "failed_lane_id": failed_lane_id,
        "blocked_lane_ids": blockers,
        "dependency_map": {
            lane_id: lane_dependencies(lane_by_id[lane_id])
            for lane_id in blockers
            if lane_id in lane_by_id
        },
        "recommended_action": recommended_action,
        "allowed_actions": [
            "reset-lane",
            "retry-lane",
            "reassign-lane",
            "resolve-failure",
        ],
        "retry_count": retry_count,
    }


def apply_multi_lane_coordination(active: dict[str, Any]) -> None:
    lanes = sorted(lane_rows(active), key=_lane_sort_key)
    lane_by_id = lane_map(active)
    active_lanes = [lane for lane in lanes if str(lane.get("status") or "") == "active"]
    active_lane_ids = [str(lane.get("lane_id") or "") for lane in active_lanes]
    active_lane_types = {str(lane.get("lane_type") or "") for lane in active_lanes}
    active_write_lanes = [lane for lane in active_lanes if not is_read_only_lane(lane)]
    max_active_lanes = 1
    reservation_safe_read = reservation_safe_read_enabled(active)
    reservation_writer_guarantees = reservation_writer_guarantees_enabled(active)
    if (
        reservation_safe_read
        and active_lanes
        and all(is_read_only_lane(lane) for lane in active_lanes)
    ):
        max_active_lanes = 2
    if (
        reservation_writer_guarantees
        and active_write_lanes
        and all(
            str(lane.get("lane_type") or "") == "implement"
            for lane in active_write_lanes
        )
        and len(active_write_lanes) <= 2
        and not any(
            scopes_overlap(lane_path_scopes(lane), lane_path_scopes(other))
            for idx, lane in enumerate(active_write_lanes)
            for other in active_write_lanes[idx + 1 :]
        )
    ):
        max_active_lanes = max(max_active_lanes, 2)
    parallel_candidate_lane_ids = [
        str(lane.get("lane_id") or "")
        for lane in lanes
        if str(lane.get("lane_type") or "") in {"review", "verify"}
        and str(lane.get("status") or "") in {"planned", "handoff-pending"}
        and is_read_only_lane(lane)
        and reservation_safe_read
        and all(
            isinstance(lane_by_id.get(dep), dict)
            and str(lane_by_id[dep].get("status") or "") == "completed"
            for dep in lane_dependencies(lane)
        )
    ]
    write_parallel_candidate_lane_ids = writer_parallel_candidates(active)
    coordination = {
        "max_active_lanes": max_active_lanes,
        "active_lane_ids": active_lane_ids,
        "active_lane_types": sorted(active_lane_types),
        "parallel_mode": (
            "writer-safe"
            if max_active_lanes > 1 and active_write_lanes
            else ("read-only-safe" if max_active_lanes > 1 else "serialized")
        ),
        "parallel_candidate_lane_ids": parallel_candidate_lane_ids,
        "write_parallel_candidate_lane_ids": write_parallel_candidate_lane_ids,
        "reservation_safe_read": reservation_safe_read,
        "reservation_writer_guarantees": reservation_writer_guarantees,
        "reservation_covers_active_writers": all(
            reservation_covers_scopes(active, lane_path_scopes(lane))
            for lane in active_write_lanes
        )
        if active_write_lanes
        else True,
        "violations": [],
    }
    if len(active_lane_ids) > max_active_lanes:
        coordination["violations"].append("multiple_active_lanes")
    overlap_pairs: list[dict[str, Any]] = []
    for idx, lane in enumerate(active_lanes):
        lane_id = str(lane.get("lane_id") or "")
        lane_scopes = lane_path_scopes(lane)
        for other in active_lanes[idx + 1 :]:
            other_id = str(other.get("lane_id") or "")
            other_scopes = lane_path_scopes(other)
            if scopes_overlap(lane_scopes, other_scopes):
                overlap_pairs.append(
                    {
                        "lane_ids": [lane_id, other_id],
                        "shared_scopes": sorted(
                            set(lane_scopes).intersection(set(other_scopes)) or {"**/*"}
                        ),
                    }
                )
    if overlap_pairs:
        coordination["violations"].append("overlapping_path_scopes")
    coordination["overlap_pairs"] = overlap_pairs
    active["coordination"] = coordination


def other_active_lane_exists(active: dict[str, Any], lane_id: str) -> bool:
    for lane in lane_rows(active):
        current_lane_id = str(lane.get("lane_id") or "")
        if current_lane_id == lane_id:
            continue
        if str(lane.get("status") or "") == "active":
            return True
    return False


def can_activate_lane(active: dict[str, Any], lane_id: str, lane_type: str) -> bool:
    lanes = sorted(lane_rows(active), key=_lane_sort_key)
    lane_by_id = lane_map(active)
    target_index = next(
        (
            idx
            for idx, lane in enumerate(lanes)
            if str(lane.get("lane_id") or "") == lane_id
        ),
        -1,
    )
    if target_index == -1:
        return False
    target_lane = lane_by_id.get(lane_id)
    if not isinstance(target_lane, dict):
        return False
    for dependency_lane_id in lane_dependencies(target_lane):
        dependency_lane = lane_by_id.get(dependency_lane_id)
        if not isinstance(dependency_lane, dict):
            return False
        if str(dependency_lane.get("status") or "") != "completed":
            return False
    active_lanes = [
        lane
        for lane in lanes
        if str(lane.get("status") or "") == "active"
        and str(lane.get("lane_id") or "") != lane_id
    ]
    if not active_lanes:
        return True
    if not is_read_only_lane(target_lane):
        if lane_type != "implement":
            return False
        if not reservation_writer_guarantees_enabled(active):
            return False
        if not reservation_covers_scopes(active, lane_path_scopes(target_lane)):
            return False
        if not reservation_owner_covers_scopes(active, lane_path_scopes(target_lane)):
            return False
        if any(is_read_only_lane(lane) for lane in active_lanes):
            return False
        if any(
            str(lane.get("lane_type") or "") != "implement" for lane in active_lanes
        ):
            return False
        active_write_lanes = [
            lane for lane in active_lanes if not is_read_only_lane(lane)
        ]
        if len(active_write_lanes) >= 2:
            return False
        for active_lane in active_write_lanes:
            active_lane_id = str(active_lane.get("lane_id") or "")
            if not reservation_covers_scopes(active, lane_path_scopes(active_lane)):
                return False
            if not reservation_owner_covers_scopes(
                active, lane_path_scopes(active_lane)
            ):
                return False
            if scopes_overlap(
                lane_path_scopes(target_lane), lane_path_scopes(active_lane)
            ):
                return False
            if active_lane_id in transitive_dependency_ids(active, lane_id):
                return False
            if lane_id in transitive_dependency_ids(active, active_lane_id):
                return False
        return True
    if not reservation_safe_read_enabled(active):
        return False
    if lane_type not in {"review", "verify"}:
        return False
    if any(not is_read_only_lane(lane) for lane in active_lanes):
        return False
    if any(
        str(lane.get("lane_type") or "") not in {"review", "verify"}
        for lane in active_lanes
    ):
        return False
    if len(active_lanes) >= 2:
        return False
    for active_lane in active_lanes:
        active_lane_id = str(active_lane.get("lane_id") or "")
        if scopes_overlap(lane_path_scopes(target_lane), lane_path_scopes(active_lane)):
            return False
        if active_lane_id in transitive_dependency_ids(active, lane_id):
            return False
        if lane_id in transitive_dependency_ids(active, active_lane_id):
            return False
    return True


def reassign_failed_lane(
    *, active: dict[str, Any], target_lane: dict[str, Any], agents: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    current_owner = str(target_lane.get("owner") or "").strip() or None
    lane_type = str(target_lane.get("lane_type") or "")
    same_role_agents = [
        item
        for item in agents
        if str(item.get("status") or "") == "active"
        and str(item.get("role") or "") == lane_type
    ]
    reassigned_owner = choose_agent_owner(
        same_role_agents,
        lane_type,
        exclude_owner=current_owner,
    )
    if not reassigned_owner:
        return False, None
    for key in [
        "failed_at",
        "failure_reason",
        "accepted_at",
        "accepted_by",
        "bg_job_id",
        "bg_job_status",
        "bg_job_command",
    ]:
        target_lane.pop(key, None)
    target_lane["previous_owner"] = current_owner
    target_lane["owner"] = reassigned_owner
    if lane_lease_identity_mode(target_lane) == "derived":
        target_lane["lease_identity"] = reassigned_owner
    target_lane["status"] = "handoff-pending"
    target_lane["reassigned_at"] = now_iso()
    return True, reassigned_owner


def refresh_swarm_runtime(
    active: dict[str, Any], agents: list[dict[str, Any]], *, auto_progress: bool
) -> None:
    sync_swarm_reservation(active)
    refresh_swarm_status(active)
    update_swarm_progress(active)
    apply_swarm_followups(active, agents, auto_progress=auto_progress)
    failed_lane = next(
        (
            lane
            for lane in lane_rows(active)
            if str(lane.get("status") or "") == "failed"
        ),
        None,
    )
    active["failure_policy"] = (
        lane_failure_policy(active, failed_lane)
        if isinstance(failed_lane, dict)
        else None
    )
    apply_multi_lane_coordination(active)


def emit(payload: dict[str, Any], as_json: bool) -> int:
    attach_model_routing(payload, entrypoint_model_routing())
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if payload.get("result") != "PASS":
            print(f"error: {payload.get('error', 'workflow command failed')}")
            return 1
        print(f"result: {payload.get('result')}")
        if payload.get("run_id"):
            print(f"run_id: {payload.get('run_id')}")
        if payload.get("status"):
            print(f"status: {payload.get('status')}")
    return 0 if payload.get("result") == "PASS" else 1


def merge_step_results(
    ordered_steps: list[dict[str, Any]],
    previous_results: list[dict[str, Any]],
    current_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_by_id = {
        str(item.get("id") or "").strip(): item
        for item in previous_results
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    current_by_id = {
        str(item.get("id") or "").strip(): item
        for item in current_results
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for step in ordered_steps:
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            continue
        if step_id in current_by_id:
            merged.append(current_by_id[step_id])
        elif step_id in previous_by_id:
            merged.append(previous_by_id[step_id])
    return merged


def validate_workflow(workflow: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if (
        not isinstance(workflow.get("name"), str)
        or not str(workflow.get("name")).strip()
    ):
        issues.append("missing workflow name")
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps:
        issues.append("missing workflow steps")
    else:
        seen_ids: set[str] = set()
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                issues.append(f"step {idx} must be object")
                continue
            step_id = str(step.get("id") or "").strip()
            if not step_id:
                issues.append(f"step {idx} missing id")
            elif step_id in seen_ids:
                issues.append(f"duplicate step id: {step_id}")
            else:
                seen_ids.add(step_id)
            if (
                not isinstance(step.get("action"), str)
                or not str(step.get("action")).strip()
            ):
                issues.append(f"step {idx} missing action")
            depends_on = step.get("depends_on")
            if depends_on is not None and not isinstance(depends_on, list):
                issues.append(f"step {idx} depends_on must be list")
            when = step.get("when")
            if when is not None and str(when) not in {
                "always",
                "on_success",
                "on_failure",
            }:
                issues.append(f"step {idx} has invalid when value")
            retry = step.get("retry")
            if retry is not None:
                try:
                    if int(retry) < 0:
                        issues.append(f"step {idx} retry must be >= 0")
                except (TypeError, ValueError):
                    issues.append(f"step {idx} retry must be integer")
    return (not issues, issues)


def resolve_step_order(
    steps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id: dict[str, dict[str, Any]] = {}
    deps: dict[str, set[str]] = {}
    reverse_edges: dict[str, set[str]] = {}
    issues: list[str] = []
    order_index: dict[str, int] = {}

    for idx, step in enumerate(steps):
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            continue
        by_id[step_id] = step
        deps[step_id] = set()
        reverse_edges[step_id] = set()
        order_index[step_id] = idx

    for step_id, step in by_id.items():
        raw_depends = step.get("depends_on")
        if raw_depends is None:
            continue
        if not isinstance(raw_depends, list):
            issues.append(f"step {step_id} has invalid depends_on")
            continue
        for dep in raw_depends:
            dep_id = str(dep).strip()
            if not dep_id:
                continue
            if dep_id not in by_id:
                issues.append(f"step {step_id} depends on unknown step {dep_id}")
                continue
            deps[step_id].add(dep_id)
            reverse_edges[dep_id].add(step_id)

    if issues:
        return [], issues

    queue = sorted(
        (step_id for step_id, d in deps.items() if not d),
        key=lambda sid: order_index.get(sid, 0),
    )
    ordered_ids: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered_ids.append(current)
        for dependent in sorted(
            reverse_edges[current], key=lambda sid: order_index.get(sid, 0)
        ):
            if current in deps[dependent]:
                deps[dependent].remove(current)
            if (
                not deps[dependent]
                and dependent not in ordered_ids
                and dependent not in queue
            ):
                queue.append(dependent)

    if len(ordered_ids) != len(by_id):
        return [], ["workflow dependency cycle detected"]
    return [by_id[step_id] for step_id in ordered_ids], []


def run_command_step(step: dict[str, Any]) -> tuple[str, str | None, str, int | None]:
    raw_command = step.get("command")
    tokens: list[str]
    if isinstance(raw_command, list):
        tokens = [str(token) for token in raw_command if str(token).strip()]
    elif isinstance(raw_command, str):
        tokens = shlex.split(raw_command)
    else:
        return "failed", "invalid_command_step", "command field missing", None

    if not tokens:
        return "failed", "invalid_command_step", "empty command tokens", None

    executable = tokens[0]
    if executable not in {"python3", "make"}:
        return (
            "failed",
            "command_not_allowed",
            f"executable not allowed: {executable}",
            None,
        )
    if executable == "make":
        target = tokens[1] if len(tokens) > 1 else ""
        if target not in {"validate", "selftest", "install-test"}:
            return (
                "failed",
                "command_not_allowed",
                f"make target not allowed: {target}",
                None,
            )
    if executable == "python3" and len(tokens) > 1:
        script_target = tokens[1]
        if not script_target.startswith("scripts/"):
            return (
                "failed",
                "command_not_allowed",
                "python3 command must target scripts/*",
                None,
            )

    completed = subprocess.run(
        tokens, capture_output=True, text=True, check=False, timeout=120000
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr or completed.stdout or "command execution failed"
        ).strip()
        return "failed", "command_exit_nonzero", detail[:500], completed.returncode
    detail = (completed.stdout or "command executed").strip()
    return "passed", None, detail[:500], completed.returncode


def execute_steps(
    steps: list[dict[str, Any]],
    execute_commands: bool,
    on_step_settled: Any = None,
    interrupt_after_steps: int = 0,
    initial_step_statuses: dict[str, str] | None = None,
) -> tuple[str, list[dict[str, Any]], str | None]:
    results: list[dict[str, Any]] = []
    failed_step_id: str | None = None
    failure_seen = False
    results_by_id: dict[str, dict[str, Any]] = {}
    step_statuses: dict[str, str] = dict(initial_step_statuses or {})

    for step in steps:
        step_id = str(step.get("id") or "unknown-step")
        action = str(step.get("action") or "")
        when = str(step.get("when") or "always")
        started_at = now_iso()
        depends_on: list[str] = (
            [str(dep) for dep in step.get("depends_on", []) if str(dep).strip()]
            if isinstance(step.get("depends_on"), list)
            else []
        )

        blocked_dependency = next(
            (
                str(dep)
                for dep in depends_on
                if step_statuses.get(str(dep), "") != "passed"
            ),
            None,
        )
        if blocked_dependency:
            results.append(
                {
                    "id": step_id,
                    "action": action,
                    "status": "skipped",
                    "reason_code": "dependency_not_passed",
                    "detail": f"skipped because dependency did not pass: {blocked_dependency}",
                    "depends_on": depends_on,
                    "when": when,
                    "retry": int(step.get("retry", 0) or 0),
                    "attempts": 0,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                }
            )
            step_statuses[step_id] = "skipped"
            continue

        if when == "on_success" and failure_seen:
            results.append(
                {
                    "id": step_id,
                    "action": action,
                    "status": "skipped",
                    "reason_code": "skipped_on_failure",
                    "detail": "skipped because a previous step failed",
                    "depends_on": depends_on,
                    "when": when,
                    "retry": int(step.get("retry", 0) or 0),
                    "attempts": 0,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                }
            )
            results_by_id[step_id] = results[-1]
            if callable(on_step_settled):
                on_step_settled(results, step_id)
            if (
                interrupt_after_steps > 0
                and len(results) >= interrupt_after_steps
                and step != steps[-1]
            ):
                next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
                return "interrupted", results, next_step_id or None
            step_statuses[step_id] = "skipped"
            step_statuses[step_id] = "skipped"
            continue
        if when == "on_failure" and not failure_seen:
            results.append(
                {
                    "id": step_id,
                    "action": action,
                    "status": "skipped",
                    "reason_code": "skipped_on_success",
                    "detail": "skipped because no previous step failed",
                    "depends_on": depends_on,
                    "when": when,
                    "retry": int(step.get("retry", 0) or 0),
                    "attempts": 0,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                }
            )
            results_by_id[step_id] = results[-1]
            if callable(on_step_settled):
                on_step_settled(results, step_id)
            if (
                interrupt_after_steps > 0
                and len(results) >= interrupt_after_steps
                and step != steps[-1]
            ):
                next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
                return "interrupted", results, next_step_id or None
            continue

            step_statuses[step_id] = "skipped"
            results_by_id[step_id] = results[-1]
            if callable(on_step_settled):
                on_step_settled(results, step_id)
            if (
                interrupt_after_steps > 0
                and len(results) >= interrupt_after_steps
                and step != steps[-1]
            ):
                next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
                return "interrupted", results, next_step_id or None
            step_statuses[step_id] = "skipped"
            continue

        raw_depends_on = step.get("depends_on")
        depends_on: list[str] = (
            [str(dep).strip() for dep in raw_depends_on if str(dep).strip()]
            if isinstance(raw_depends_on, list)
            else []
        )
        unmet_dependency = next(
            (
                dep_id
                for dep_id in depends_on
                if step_statuses.get(
                    dep_id, str(results_by_id.get(dep_id, {}).get("status") or "")
                )
                != "passed"
            ),
            None,
        )
        if unmet_dependency:
            results.append(
                {
                    "id": step_id,
                    "action": action,
                    "status": "skipped",
                    "reason_code": "dependency_not_passed",
                    "detail": f"skipped because dependency did not pass: {unmet_dependency}",
                    "depends_on": depends_on,
                    "when": when,
                    "retry": int(step.get("retry", 0) or 0),
                    "attempts": 0,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                }
            )
            results_by_id[step_id] = results[-1]
            if callable(on_step_settled):
                on_step_settled(results, step_id)
            if (
                interrupt_after_steps > 0
                and len(results) >= interrupt_after_steps
                and step != steps[-1]
            ):
                next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
                return "interrupted", results, next_step_id or None
            step_statuses[step_id] = "skipped"
            continue

        retry_count = 0
        try:
            retry_count = max(0, int(step.get("retry", 0) or 0))
        except (TypeError, ValueError):
            retry_count = 0

        status = "passed"
        reason_code = None
        detail = "executed"
        attempts = 0
        for _ in range(retry_count + 1):
            attempts += 1
            status = "passed"
            reason_code = None
            detail = "executed"

            if not action:
                status = "failed"
                reason_code = "missing_step_action"
                detail = "step action is required"
            elif execute_commands and step.get("command") is not None:
                status, reason_code, detail, _ = run_command_step(step)
            elif (
                action in {"fail", "error"} or str(step.get("simulate") or "") == "fail"
            ):
                status = "failed"
                reason_code = "step_failed"
                detail = "step requested failure"
            elif str(step.get("simulate") or "") == "fail-once" and attempts == 1:
                status = "failed"
                reason_code = "step_failed_once"
                detail = "step requested one-time failure"
            elif step.get("command") is not None:
                detail = "dry-run command step (use --execute)"

            if status != "failed":
                break

        if status == "failed":
            failure_seen = True
            if failed_step_id is None:
                failed_step_id = step_id

        results.append(
            {
                "id": step_id,
                "action": action,
                "status": status,
                "reason_code": reason_code,
                "detail": detail,
                "depends_on": depends_on,
                "when": when,
                "retry": retry_count,
                "attempts": attempts,
                "started_at": started_at,
                "finished_at": now_iso(),
            }
        )
        results_by_id[step_id] = results[-1]
        if callable(on_step_settled):
            on_step_settled(results, step_id)
        if (
            interrupt_after_steps > 0
            and len(results) >= interrupt_after_steps
            and step != steps[-1]
        ):
            next_step_id = str(steps[steps.index(step) + 1].get("id") or "")
            return "interrupted", results, next_step_id or None
        step_statuses[step_id] = status
        step_statuses[step_id] = status

    if failed_step_id:
        return "failed", results, failed_step_id
    return "completed", results, None


def load_workflow_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [f"workflow file not found: {path}"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"invalid json: {exc}"]
    if not isinstance(raw, dict):
        return None, ["workflow root must be object"]
    ok, issues = validate_workflow(raw)
    return (raw, []) if ok else (raw, issues)


def cmd_validate(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        file_arg = parse_flag_value(argv, "--file")
    except ValueError:
        return usage()
    if not file_arg:
        return usage()
    workflow, issues = load_workflow_file(Path(file_arg).expanduser())
    if issues:
        return emit(
            {
                "result": "FAIL",
                "command": "validate",
                "issues": issues,
                "error": issues[0],
            },
            as_json,
        )
    return emit(
        {
            "result": "PASS",
            "command": "validate",
            "workflow": workflow,
            "issues": [],
        },
        as_json,
    )


def cmd_run(argv: list[str]) -> int:
    routing = entrypoint_model_routing()
    as_json = "--json" in argv
    execute_commands = "--execute" in argv
    override_flag = "--override" in argv
    argv = [a for a in argv if a not in {"--json", "--execute", "--override"}]
    try:
        file_arg = parse_flag_value(argv, "--file")
    except ValueError:
        return usage()
    if not file_arg:
        return usage()

    if execute_commands:
        guard = check_operation("workflow.execute", override_flag=override_flag)
        if not bool(guard.get("allowed")):
            return emit(
                {
                    "result": "FAIL",
                    "command": "run",
                    "error": "operation blocked by governance policy",
                    "reason_code": guard.get("reason_code"),
                    "governance": guard,
                },
                as_json,
            )

    workflow_path = Path(file_arg).expanduser()
    workflow, issues = load_workflow_file(workflow_path)
    if issues or not isinstance(workflow, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "run",
                "issues": issues,
                "error": issues[0],
            },
            as_json,
        )

    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if active and str(active.get("status") or "") == "running":
        return emit(
            {
                "result": "FAIL",
                "command": "run",
                "error": "workflow run already active",
                "reason_code": "workflow_already_running",
                "active_run_id": active.get("run_id"),
            },
            as_json,
        )

    raw_steps = workflow.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    normalized_steps = [step for step in steps if isinstance(step, dict)]
    ordered_steps, order_issues = resolve_step_order(normalized_steps)
    if order_issues:
        return emit(
            {
                "result": "FAIL",
                "command": "run",
                "error": order_issues[0],
                "issues": order_issues,
                "reason_code": "workflow_dependency_error",
            },
            as_json,
        )

    run_id = next_run_id(state)
    started_at = now_iso()
    interrupt_after_steps = 0
    try:
        interrupt_after_steps = max(
            0,
            int(os.environ.get("MY_OPENCODE_WORKFLOW_INTERRUPT_AFTER_STEP", "0") or 0),
        )
    except ValueError:
        interrupt_after_steps = 0
    active_run = {
        "run_id": run_id,
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": "running" if execute_commands else "dry-run",
        "execution_mode": "execute" if execute_commands else "dry-run",
        "step_count": len(ordered_steps),
        "completed_steps": 0,
        "failed_step_id": None,
        "ordered_step_ids": [str(step.get("id") or "") for step in ordered_steps],
        "steps": [],
        "started_at": started_at,
        "updated_at": started_at,
    }
    state["active"] = active_run
    save_json_file(DEFAULT_STATE_PATH, state)

    def persist_partial(step_results: list[dict[str, Any]], next_step_id: str) -> None:
        partial_state = load_json_file(DEFAULT_STATE_PATH)
        partial_active = active_record(partial_state)
        partial_active.update(
            {
                "run_id": run_id,
                "name": workflow.get("name"),
                "path": str(workflow_path),
                "status": "running",
                "execution_mode": "execute" if execute_commands else "dry-run",
                "step_count": len(ordered_steps),
                "completed_steps": sum(
                    1 for item in step_results if item.get("status") == "passed"
                ),
                "failed_step_id": next_step_id or None,
                "ordered_step_ids": [
                    str(step.get("id") or "") for step in ordered_steps
                ],
                "steps": step_results,
                "started_at": started_at,
                "updated_at": now_iso(),
            }
        )
        partial_state["active"] = partial_active
        save_json_file(DEFAULT_STATE_PATH, partial_state)
        if execute_commands:
            sync_workflow_run_to_task_graph(
                workflow_path=workflow_path,
                workflow=workflow,
                ordered_steps=ordered_steps,
                step_results=step_results,
                run_record=partial_active,
            )

    status, step_results, failed_step_id = execute_steps(
        ordered_steps,
        execute_commands,
        on_step_settled=persist_partial if execute_commands else None,
        interrupt_after_steps=interrupt_after_steps if execute_commands else 0,
    )
    run_record = {
        "run_id": run_id,
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": status,
        "execution_mode": "execute" if execute_commands else "dry-run",
        "step_count": len(ordered_steps),
        "completed_steps": sum(
            1 for step in step_results if step.get("status") == "passed"
        ),
        "failed_step_id": failed_step_id,
        "ordered_step_ids": [str(step.get("id") or "") for step in ordered_steps],
        "steps": step_results,
        "started_at": started_at,
        "finished_at": now_iso(),
    }
    if status == "interrupted":
        state = load_json_file(DEFAULT_STATE_PATH)
        state["active"] = run_record
        save_json_file(DEFAULT_STATE_PATH, state)
    else:
        history = history_list(state)
        history.insert(0, run_record)
        state["history"] = history[:50]
        state["active"] = {}
        save_json_file(DEFAULT_STATE_PATH, state)
    task_graph_path = task_graph_runtime_path()
    if execute_commands:
        task_graph_path = sync_workflow_run_to_task_graph(
            workflow_path=workflow_path,
            workflow=workflow,
            ordered_steps=ordered_steps,
            step_results=step_results,
            run_record=run_record,
        )
    append_event("workflow", "run", "PASS", {"run_id": run_id, "status": status})
    return emit(
        attach_model_routing(
            (
                {
                    "result": "PASS" if status != "interrupted" else "FAIL",
                    "command": "run",
                    **run_record,
                    **(
                        {
                            **task_graph_status_snapshot(),
                            "task_graph_path": str(task_graph_path),
                        }
                        if execute_commands
                        else {}
                    ),
                }
            ),
            routing,
        ),
        as_json,
    )


def cmd_resume(argv: list[str]) -> int:
    routing = entrypoint_model_routing()
    as_json = "--json" in argv
    execute_commands = "--execute" in argv
    override_flag = "--override" in argv
    argv = [a for a in argv if a not in {"--json", "--execute", "--override"}]
    try:
        run_id = parse_flag_value(argv, "--run-id")
    except ValueError:
        return usage()
    if not run_id:
        return usage()

    if execute_commands:
        guard = check_operation("workflow.resume_execute", override_flag=override_flag)
        if not bool(guard.get("allowed")):
            return emit(
                {
                    "result": "FAIL",
                    "command": "resume",
                    "error": "operation blocked by governance policy",
                    "reason_code": guard.get("reason_code"),
                    "governance": guard,
                },
                as_json,
            )

    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if active and str(active.get("status") or "") == "running":
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": "workflow run already active",
                "reason_code": "workflow_already_running",
                "active_run_id": active.get("run_id"),
            },
            as_json,
        )
    history = history_list(state)
    source_run = None
    if active and str(active.get("run_id") or "") == run_id:
        source_run = active
    if not isinstance(source_run, dict):
        source_run = next(
            (row for row in history if str(row.get("run_id") or "") == run_id), None
        )
    if not isinstance(source_run, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": f"run not found: {run_id}",
                "reason_code": "workflow_run_not_found",
            },
            as_json,
        )
    if str(source_run.get("status") or "") not in {"failed", "interrupted"}:
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": "run is not resumable",
                "reason_code": "workflow_resume_not_failed",
            },
            as_json,
        )

    workflow_path = Path(str(source_run.get("path") or "")).expanduser()
    workflow, issues = load_workflow_file(workflow_path)
    if issues or not isinstance(workflow, dict):
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": issues[0] if issues else "workflow load failed",
                "reason_code": "workflow_resume_load_failed",
            },
            as_json,
        )

    raw_steps = workflow.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    normalized_steps = [step for step in steps if isinstance(step, dict)]
    ordered_steps, order_issues = resolve_step_order(normalized_steps)
    if order_issues:
        return emit(
            {
                "result": "FAIL",
                "command": "resume",
                "error": order_issues[0],
                "issues": order_issues,
                "reason_code": "workflow_dependency_error",
            },
            as_json,
        )

    failed_step_id = str(source_run.get("failed_step_id") or "")
    start_index = 0
    found_failed_step = False
    if failed_step_id:
        for idx, step in enumerate(ordered_steps):
            if str(step.get("id") or "") == failed_step_id:
                start_index = idx
                found_failed_step = True
                break
        if not found_failed_step:
            return emit(
                {
                    "result": "FAIL",
                    "command": "resume",
                    "error": f"failed step no longer exists in workflow: {failed_step_id}",
                    "reason_code": "workflow_resume_failed_step_missing",
                    "failed_step_id": failed_step_id,
                },
                as_json,
            )
    resumed_steps = ordered_steps[start_index:]
    prior_step_statuses: dict[str, str] = {}
    raw_source_steps = source_run.get("steps")
    source_steps: list[dict[str, Any]] = (
        [step for step in raw_source_steps if isinstance(step, dict)]
        if isinstance(raw_source_steps, list)
        else []
    )
    source_step_map = {
        str(step.get("id") or ""): step
        for step in source_steps
        if isinstance(step, dict) and str(step.get("id") or "").strip()
    }
    for prior_step in ordered_steps[:start_index]:
        prior_step_id = str(prior_step.get("id") or "")
        if not prior_step_id:
            continue
        prior_status = str(source_step_map.get(prior_step_id, {}).get("status") or "")
        if prior_status:
            prior_step_statuses[prior_step_id] = prior_status

    started_at = now_iso()
    active_resume = {
        "run_id": next_run_id(state),
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": "running" if execute_commands else "dry-run",
        "execution_mode": "execute" if execute_commands else "dry-run",
        "resumed_from": run_id,
        "step_count": len(resumed_steps),
        "completed_steps": 0,
        "failed_step_id": None,
        "ordered_step_ids": [str(step.get("id") or "") for step in resumed_steps],
        "steps": [],
        "started_at": started_at,
        "updated_at": started_at,
    }
    state["active"] = active_resume
    save_json_file(DEFAULT_STATE_PATH, state)

    def persist_resumed_partial(
        step_results: list[dict[str, Any]], next_step_id: str
    ) -> None:
        partial_state = load_json_file(DEFAULT_STATE_PATH)
        partial_active = active_record(partial_state)
        partial_active.update(
            {
                **active_resume,
                "completed_steps": sum(
                    1 for item in step_results if item.get("status") == "passed"
                ),
                "failed_step_id": next_step_id or None,
                "steps": step_results,
                "updated_at": now_iso(),
            }
        )
        partial_state["active"] = partial_active
        save_json_file(DEFAULT_STATE_PATH, partial_state)
        if execute_commands:
            previous_step_results = [
                item for item in source_run.get("steps", []) if isinstance(item, dict)
            ]
            merged_step_results = merge_step_results(
                ordered_steps, previous_step_results, step_results
            )
            sync_workflow_run_to_task_graph(
                workflow_path=workflow_path,
                workflow=workflow,
                ordered_steps=ordered_steps,
                step_results=merged_step_results,
                run_record=partial_active,
            )

    interrupt_after_steps = 0
    try:
        interrupt_after_steps = max(
            0,
            int(os.environ.get("MY_OPENCODE_WORKFLOW_INTERRUPT_AFTER_STEP", "0") or 0),
        )
    except ValueError:
        interrupt_after_steps = 0
    status, step_results, new_failed = execute_steps(
        resumed_steps,
        execute_commands,
        initial_step_statuses=prior_step_statuses,
        on_step_settled=persist_resumed_partial if execute_commands else None,
        interrupt_after_steps=interrupt_after_steps if execute_commands else 0,
    )
    new_run_id = active_resume["run_id"]
    run_record = {
        "run_id": new_run_id,
        "name": workflow.get("name"),
        "path": str(workflow_path),
        "status": status,
        "execution_mode": "execute" if execute_commands else "dry-run",
        "resumed_from": run_id,
        "step_count": len(resumed_steps),
        "completed_steps": sum(
            1 for step in step_results if step.get("status") == "passed"
        ),
        "failed_step_id": new_failed,
        "ordered_step_ids": [str(step.get("id") or "") for step in resumed_steps],
        "steps": step_results,
        "started_at": started_at,
        "finished_at": now_iso(),
    }
    if status == "interrupted":
        state = load_json_file(DEFAULT_STATE_PATH)
        state["active"] = run_record
        save_json_file(DEFAULT_STATE_PATH, state)
    else:
        history.insert(0, run_record)
        state["history"] = history[:50]
        state["active"] = {}
        save_json_file(DEFAULT_STATE_PATH, state)
    task_graph_path = task_graph_runtime_path()
    if execute_commands:
        previous_step_results = [
            item for item in source_run.get("steps", []) if isinstance(item, dict)
        ]
        merged_step_results = merge_step_results(
            ordered_steps, previous_step_results, step_results
        )
        task_graph_path = sync_workflow_run_to_task_graph(
            workflow_path=workflow_path,
            workflow=workflow,
            ordered_steps=ordered_steps,
            step_results=merged_step_results,
            run_record=run_record,
        )
    append_event(
        "workflow",
        "resume",
        "PASS",
        {"run_id": new_run_id, "resumed_from": run_id, "status": status},
    )
    return emit(
        attach_model_routing(
            (
                {
                    "result": "PASS" if status != "interrupted" else "FAIL",
                    "command": "resume",
                    **run_record,
                    **(
                        {
                            **task_graph_status_snapshot(),
                            "task_graph_path": str(task_graph_path),
                        }
                        if execute_commands
                        else {}
                    ),
                }
            ),
            routing,
        ),
        as_json,
    )


def cmd_status(argv: list[str]) -> int:
    routing = entrypoint_model_routing()
    as_json = "--json" in argv
    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if not active:
        history = history_list(state)
        latest = history[0] if history and isinstance(history[0], dict) else {}
        return emit(
            attach_model_routing(
                {
                    "result": "PASS",
                    "command": "status",
                    "status": "idle",
                    "warnings": ["no active workflow run"],
                    "latest": latest,
                    **task_graph_status_snapshot(),
                },
                routing,
            ),
            as_json,
        )
    return emit(
        attach_model_routing(
            {
                "result": "PASS",
                "command": "status",
                **active,
                **task_graph_status_snapshot(),
            },
            routing,
        ),
        as_json,
    )


def cmd_stop(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    reason = "manual stop"
    try:
        reason_arg = parse_flag_value(argv, "--reason")
    except ValueError:
        return usage()
    if reason_arg:
        reason = reason_arg
    state = load_json_file(DEFAULT_STATE_PATH)
    active = active_record(state)
    if not active:
        return emit(
            {
                "result": "PASS",
                "command": "stop",
                "status": "idle",
                "warnings": ["no active workflow run"],
            },
            as_json,
        )
    active["status"] = "stopped"
    active["stopped_at"] = now_iso()
    active["stop_reason"] = reason
    state["active"] = {}
    history = history_list(state)
    if history and history[0].get("run_id") == active.get("run_id"):
        history[0] = active
    state["history"] = history
    save_json_file(DEFAULT_STATE_PATH, state)
    append_event(
        "workflow", "stop", "PASS", {"run_id": active.get("run_id"), "reason": reason}
    )
    return emit({"result": "PASS", "command": "stop", **active}, as_json)


def cmd_list(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_json_file(DEFAULT_STATE_PATH)
    history = history_list(state)
    return emit(
        {
            "result": "PASS",
            "command": "list",
            "count": len(history),
            "runs": history,
        },
        as_json,
    )


def cmd_swarm(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    subcommand = argv[0]
    rest = argv[1:]
    state = load_json_file(DEFAULT_STATE_PATH)
    swarm = swarm_state(state)
    if subcommand == "plan":
        try:
            objective = parse_flag_value(rest, "--objective")
            lanes_raw = parse_flag_value(rest, "--lanes") or "3"
            graph_arg = parse_flag_value(rest, "--graph-file")
            claim_ids = parse_csv(parse_flag_value(rest, "--claim-ids"))
            writer_paths = parse_csv(parse_flag_value(rest, "--writer-paths"))
            lane_count = max(1, min(len(SWARM_ROLE_SEQUENCE), int(lanes_raw)))
        except (TypeError, ValueError):
            return usage()
        if rest or not objective:
            return usage()
        claims = load_claim_rows()
        agents = load_pool_agents()
        reservation = load_reservation_snapshot()
        active_claims = [claims[item] for item in claim_ids if item in claims]
        writer_paths = (
            writer_paths
            or reservation.get("ownPaths", [])
            or reservation.get("activePaths", [])
        )
        swarm_id = next_swarm_id(state)
        graph_path = Path(graph_arg).expanduser() if graph_arg else None
        if graph_path is not None:
            graph_lanes, graph_issues = load_swarm_graph(graph_path)
            if graph_issues or graph_lanes is None:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-plan",
                        "error": graph_issues[0]
                        if graph_issues
                        else "swarm graph load failed",
                        "issues": graph_issues,
                    },
                    as_json,
                )
            lanes = materialize_swarm_graph(
                objective=objective,
                graph_lanes=graph_lanes,
                claim_ids=claim_ids,
                writer_paths=writer_paths,
                agents=agents,
            )
        else:
            lanes = build_swarm_lanes(
                objective=objective,
                lane_count=lane_count,
                claim_ids=claim_ids,
                writer_paths=writer_paths,
                agents=agents,
            )
        record = {
            "swarm_id": swarm_id,
            "objective": objective,
            "status": "planned",
            "created_at": now_iso(),
            "cwd": str(Path.cwd()),
            "lane_count": len(lanes),
            "lanes": lanes,
            "graph_mode": "custom-v1" if graph_path is not None else "generated-v1",
            "graph_file": str(graph_path) if graph_path is not None else None,
            "claim_ids": claim_ids,
            "claims_found": len(active_claims),
            "reservation": reservation,
            "writer_paths": writer_paths,
            "pool_summary": {
                "active_agents": sum(
                    1 for item in agents if str(item.get("status") or "") == "active"
                ),
                "roles": sorted(
                    {
                        str(item.get("role") or "")
                        for item in agents
                        if str(item.get("role") or "").strip()
                    }
                ),
            },
        }
        refresh_swarm_runtime(record, agents, auto_progress=False)
        swarm["active"] = record
        history = swarm_history_list(state)
        history.insert(0, record)
        swarm["history"] = history[:50]
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-plan",
            "PASS",
            {"swarm_id": swarm_id, "lane_count": len(lanes)},
        )
        return emit({"result": "PASS", "command": "swarm-plan", **record}, as_json)
    if subcommand == "status":
        if rest:
            return usage()
        active = active_swarm_record(state)
        if active:
            refresh_swarm_runtime(active, load_pool_agents(), auto_progress=False)
            sync_swarm_history(state, active)
            save_json_file(DEFAULT_STATE_PATH, state)
            return emit(
                {"result": "PASS", "command": "swarm-status", **active}, as_json
            )
        history = swarm_history_list(state)
        latest = history[0] if history else {}
        return emit(
            {
                "result": "PASS",
                "command": "swarm-status",
                "status": "idle",
                "warnings": ["no active swarm plan"],
                "latest": latest,
            },
            as_json,
        )
    if subcommand == "doctor":
        if rest:
            return usage()
        active = active_swarm_record(state)
        claims = load_claim_rows()
        agents = load_pool_agents()
        reservation = load_reservation_snapshot()
        warnings: list[str] = []
        if not active:
            warnings.append("no active swarm plan")
        raw_lanes = active.get("lanes")
        lanes: list[dict[str, Any]] = (
            [lane for lane in raw_lanes if isinstance(lane, dict)]
            if isinstance(raw_lanes, list)
            else []
        )
        if active and any(not str(lane.get("owner") or "").strip() for lane in lanes):
            warnings.append("one or more swarm lanes are unassigned")
        if any(str(lane.get("status") or "") == "handoff-pending" for lane in lanes):
            warnings.append("one or more swarm lanes are waiting on handoff acceptance")
        for claim_id in (
            active.get("claim_ids", [])
            if isinstance(active.get("claim_ids"), list)
            else []
        ):
            if claim_id not in claims:
                warnings.append(f"missing claim: {claim_id}")
        if (
            reservation.get("reservationActive")
            and int(reservation.get("writerCount", 0) or 0) > 1
            and not reservation.get("activePaths")
            and not reservation.get("ownPaths")
        ):
            warnings.append(
                "reservation active with multiple writers but no active paths"
            )
        if not any(str(item.get("status") or "") == "active" for item in agents):
            warnings.append("agent pool has no active agents")
        if any(
            str(lane.get("owner") or "").strip()
            and not valid_lane_owner(str(lane.get("owner") or ""), agents)
            for lane in lanes
        ):
            warnings.append("one or more swarm lanes have invalid owners")
        return emit(
            {
                "result": "PASS",
                "command": "swarm-doctor",
                "active_swarm": active,
                "warning_count": len(warnings),
                "warnings": warnings,
                "state_path": str(DEFAULT_STATE_PATH),
                "claims_path": str(DEFAULT_CLAIMS_PATH),
                "agent_pool_path": str(DEFAULT_AGENT_POOL_PATH),
                "reservation_path": str(DEFAULT_RESERVATION_STATE_PATH),
            },
            as_json,
        )
    if subcommand == "handoff":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
            target_owner = parse_flag_value(rest, "--to")
            next_status = parse_flag_value(rest, "--status") or "handoff-pending"
        except ValueError:
            return usage()
        if rest or not lane_id or not target_owner:
            return usage()
        if next_status not in {"planned", "handoff-pending"}:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-handoff",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        sync_swarm_reservation(active)
        agents = load_pool_agents()
        normalized_target = target_owner.strip()
        if not valid_lane_owner(normalized_target, agents):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-handoff",
                    "error": f"invalid handoff owner: {target_owner}",
                },
                as_json,
            )
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-handoff",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") in {"completed", "failed", "closed"}:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-handoff",
                    "error": f"lane is terminal and cannot be handed off: {lane_id}",
                },
                as_json,
            )
        lane_type = str(target_lane.get("lane_type") or "")
        lease_owner = writer_lease_owner(active)
        lane_lease_owner = lane_lease_identity(target_lane)
        if not is_read_only_lane(target_lane) and next_status == "handoff-pending":
            if lane_lease_owner and normalized_target != lane_lease_owner:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-handoff",
                        "error": f"lane lease identity must match handoff owner: {lane_lease_owner}",
                    },
                    as_json,
                )
        if (
            not is_read_only_lane(target_lane)
            and next_status == "handoff-pending"
            and reservation_writer_guarantees_enabled(active)
        ):
            if not lease_owner or normalized_target != lease_owner:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-handoff",
                        "error": f"writer lease owner must match handoff owner: {lease_owner or 'missing'}",
                    },
                    as_json,
                )
            if not active_write_owner_match(active, lease_owner):
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-handoff",
                        "error": "active writer owners do not match reservation lease owner",
                    },
                    as_json,
                )
        if next_status == "handoff-pending" and not can_activate_lane(
            active, lane_id, lane_type
        ):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-handoff",
                    "error": f"another lane is already active: {lane_id}",
                },
                as_json,
            )
        bg_job_id = str(target_lane.get("bg_job_id") or "").strip()
        if bg_job_id:
            current_bg_status = background_job_status(bg_job_id)
            target_lane["bg_job_status"] = current_bg_status
            if current_bg_status not in {"completed", "failed", "cancelled"}:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-handoff",
                        "error": f"lane has active background work: {lane_id}",
                    },
                    as_json,
                )
        previous_owner = str(target_lane.get("owner") or "") or None
        target_lane["owner"] = normalized_target
        target_lane["previous_owner"] = previous_owner
        target_lane["status"] = next_status
        target_lane["handoff_at"] = now_iso()
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, agents, auto_progress=False)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-handoff",
            "PASS",
            {
                "swarm_id": active.get("swarm_id"),
                "lane_id": lane_id,
                "to": target_owner,
            },
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-handoff",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "accept-handoff":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
            accepted_by = parse_flag_value(rest, "--by")
            bg_command = parse_flag_value(rest, "--bg-command")
            override_flag = "--override" in rest
        except ValueError:
            return usage()
        rest = [item for item in rest if item != "--override"]
        if rest or not lane_id:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-accept-handoff",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        sync_swarm_reservation(active)
        agents = load_pool_agents()
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-accept-handoff",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") != "handoff-pending":
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-accept-handoff",
                    "error": f"lane is not handoff-pending: {lane_id}",
                },
                as_json,
            )
        lane_type = str(target_lane.get("lane_type") or "")
        lease_owner = writer_lease_owner(active)
        lane_lease_owner = lane_lease_identity(target_lane)
        if not can_activate_lane(active, lane_id, lane_type):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-accept-handoff",
                    "error": f"another lane is already active: {lane_id}",
                },
                as_json,
            )
        owner = str(target_lane.get("owner") or "").strip()
        effective_acceptor = str(accepted_by or owner).strip()
        if accepted_by and effective_acceptor != owner:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-accept-handoff",
                    "error": f"accepting owner must match pending owner: {owner}",
                },
                as_json,
            )
        if not valid_lane_owner(effective_acceptor, agents):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-accept-handoff",
                    "error": f"invalid accepting owner: {effective_acceptor or accepted_by or owner}",
                },
                as_json,
            )
        if (
            not is_read_only_lane(target_lane)
            and lane_lease_owner
            and effective_acceptor != lane_lease_owner
        ):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-accept-handoff",
                    "error": f"lane lease identity must match accepting owner: {lane_lease_owner}",
                },
                as_json,
            )
        if not is_read_only_lane(target_lane) and reservation_writer_guarantees_enabled(
            active
        ):
            if not lease_owner or effective_acceptor != lease_owner:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-accept-handoff",
                        "error": f"writer lease owner must match accepting owner: {lease_owner or 'missing'}",
                    },
                    as_json,
                )
            if not active_write_owner_match(active, lease_owner):
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-accept-handoff",
                        "error": "active writer owners do not match reservation lease owner",
                    },
                    as_json,
                )
        bg_job: dict[str, Any] | None = None
        if bg_command:
            tokens = parse_command_tokens(bg_command)
            plan_cwd = str(active.get("cwd") or Path.cwd())
            allowed, reason = validate_background_tokens(tokens, cwd_value=plan_cwd)
            if not allowed:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-accept-handoff",
                        "error": reason or "background command not allowed",
                    },
                    as_json,
                )
            guard = check_operation(
                "workflow.swarm_accept_handoff_bg", override_flag=override_flag
            )
            if not bool(guard.get("allowed")):
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-accept-handoff",
                        "error": "operation blocked by governance policy",
                        "reason_code": guard.get("reason_code"),
                        "governance": guard,
                    },
                    as_json,
                )
            bg_job = start_background_job(
                tokens=tokens,
                cwd_value=plan_cwd,
                labels=[
                    "swarm",
                    f"swarm:{active.get('swarm_id')}",
                    f"lane:{lane_id}",
                    f"owner:{effective_acceptor}",
                ],
            )
            if bg_job is None:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-accept-handoff",
                        "error": "failed to enqueue background job",
                    },
                    as_json,
                )
            target_lane["bg_job_id"] = bg_job.get("id")
            target_lane["bg_job_status"] = bg_job.get("status")
            target_lane["bg_job_command"] = bg_job.get("command")
        target_lane["owner"] = effective_acceptor
        target_lane["status"] = "active"
        target_lane["accepted_at"] = now_iso()
        target_lane["accepted_by"] = effective_acceptor
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, agents, auto_progress=False)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-accept-handoff",
            "PASS",
            {
                "swarm_id": active.get("swarm_id"),
                "lane_id": lane_id,
                "accepted_by": effective_acceptor,
                "bg_job_id": bg_job.get("id") if isinstance(bg_job, dict) else None,
            },
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-accept-handoff",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "bg_job": bg_job,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "complete-lane":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
            summary = parse_flag_value(rest, "--summary") or "lane completed"
        except ValueError:
            return usage()
        if rest or not lane_id:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-complete-lane",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-complete-lane",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") != "active":
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-complete-lane",
                    "error": f"lane is not completable: {lane_id}",
                },
                as_json,
            )
        bg_job_id = str(target_lane.get("bg_job_id") or "").strip()
        if bg_job_id:
            current_bg_status = background_job_status(bg_job_id)
            target_lane["bg_job_status"] = current_bg_status
            if current_bg_status not in {"completed", "failed", "cancelled"}:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-complete-lane",
                        "error": f"background job still in progress for lane: {lane_id}",
                    },
                    as_json,
                )
            if current_bg_status in {"failed", "cancelled"}:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-complete-lane",
                        "error": f"background job did not complete successfully for lane: {lane_id}",
                    },
                    as_json,
                )
        target_lane["status"] = "completed"
        target_lane["completed_at"] = now_iso()
        target_lane["completion_summary"] = summary
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, load_pool_agents(), auto_progress=True)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-complete-lane",
            "PASS",
            {"swarm_id": active.get("swarm_id"), "lane_id": lane_id},
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-complete-lane",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "progress": active.get("progress"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "fail-lane":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
            reason = parse_flag_value(rest, "--reason") or "lane failed"
        except ValueError:
            return usage()
        if rest or not lane_id:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-fail-lane",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-fail-lane",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") != "active":
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-fail-lane",
                    "error": f"lane is not fail-able: {lane_id}",
                },
                as_json,
            )
        bg_job_id = str(target_lane.get("bg_job_id") or "").strip()
        if bg_job_id:
            current_bg_status = background_job_status(bg_job_id)
            target_lane["bg_job_status"] = current_bg_status
            if current_bg_status not in {"completed", "failed", "cancelled"}:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-fail-lane",
                        "error": f"background job still in progress for lane: {lane_id}",
                    },
                    as_json,
                )
        target_lane["status"] = "failed"
        target_lane["failed_at"] = now_iso()
        target_lane["failure_reason"] = reason
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, load_pool_agents(), auto_progress=True)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-fail-lane",
            "PASS",
            {"swarm_id": active.get("swarm_id"), "lane_id": lane_id},
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-fail-lane",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "progress": active.get("progress"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "reset-lane":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
        except ValueError:
            return usage()
        if rest or not lane_id:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-reset-lane",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-reset-lane",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") != "failed":
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-reset-lane",
                    "error": f"lane is not failed: {lane_id}",
                },
                as_json,
            )
        for key in [
            "failed_at",
            "failure_reason",
            "accepted_at",
            "accepted_by",
            "bg_job_id",
            "bg_job_status",
            "bg_job_command",
        ]:
            target_lane.pop(key, None)
        target_lane["status"] = "planned"
        target_lane["reset_at"] = now_iso()
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, load_pool_agents(), auto_progress=True)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-reset-lane",
            "PASS",
            {"swarm_id": active.get("swarm_id"), "lane_id": lane_id},
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-reset-lane",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "progress": active.get("progress"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "retry-lane":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
        except ValueError:
            return usage()
        if rest or not lane_id:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-retry-lane",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-retry-lane",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") != "failed":
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-retry-lane",
                    "error": f"lane is not failed: {lane_id}",
                },
                as_json,
            )
        for key in [
            "failed_at",
            "failure_reason",
            "accepted_at",
            "accepted_by",
            "bg_job_id",
            "bg_job_status",
            "bg_job_command",
        ]:
            target_lane.pop(key, None)
        target_lane["status"] = "handoff-pending"
        target_lane["retry_count"] = int(target_lane.get("retry_count", 0) or 0) + 1
        target_lane["retried_at"] = now_iso()
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, load_pool_agents(), auto_progress=False)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-retry-lane",
            "PASS",
            {"swarm_id": active.get("swarm_id"), "lane_id": lane_id},
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-retry-lane",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "progress": active.get("progress"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "reassign-lane":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
        except ValueError:
            return usage()
        if rest or not lane_id:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-reassign-lane",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-reassign-lane",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") != "failed":
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-reassign-lane",
                    "error": f"lane is not failed: {lane_id}",
                },
                as_json,
            )
        ok, new_owner = reassign_failed_lane(
            active=active, target_lane=target_lane, agents=load_pool_agents()
        )
        if not ok or not new_owner:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-reassign-lane",
                    "error": f"no alternate owner available for lane: {lane_id}",
                },
                as_json,
            )
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, load_pool_agents(), auto_progress=False)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-reassign-lane",
            "PASS",
            {
                "swarm_id": active.get("swarm_id"),
                "lane_id": lane_id,
                "new_owner": new_owner,
            },
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-reassign-lane",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "progress": active.get("progress"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "resolve-failure":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
        except ValueError:
            return usage()
        if rest or not lane_id:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-resolve-failure",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        lanes = lane_rows(active)
        target_lane = next(
            (lane for lane in lanes if str(lane.get("lane_id") or "") == lane_id), None
        )
        if not isinstance(target_lane, dict):
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-resolve-failure",
                    "error": f"lane not found: {lane_id}",
                },
                as_json,
            )
        if str(target_lane.get("status") or "") != "failed":
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-resolve-failure",
                    "error": f"lane is not failed: {lane_id}",
                },
                as_json,
            )
        policy = lane_failure_policy(active, target_lane)
        action = str(policy.get("recommended_action") or "retry-lane")
        if action == "reset-lane":
            for key in [
                "failed_at",
                "failure_reason",
                "accepted_at",
                "accepted_by",
                "bg_job_id",
                "bg_job_status",
                "bg_job_command",
            ]:
                target_lane.pop(key, None)
            target_lane["status"] = "planned"
            target_lane["reset_at"] = now_iso()
        elif action == "retry-lane":
            for key in [
                "failed_at",
                "failure_reason",
                "accepted_at",
                "accepted_by",
                "bg_job_id",
                "bg_job_status",
                "bg_job_command",
            ]:
                target_lane.pop(key, None)
            target_lane["status"] = "handoff-pending"
            target_lane["retry_count"] = int(target_lane.get("retry_count", 0) or 0) + 1
            target_lane["retried_at"] = now_iso()
        else:
            ok, reassigned_owner = reassign_failed_lane(
                active=active, target_lane=target_lane, agents=load_pool_agents()
            )
            if not ok or not reassigned_owner:
                return emit(
                    {
                        "result": "FAIL",
                        "command": "swarm-resolve-failure",
                        "error": f"no reassignment candidate for lane: {lane_id}",
                    },
                    as_json,
                )
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, load_pool_agents(), auto_progress=False)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-resolve-failure",
            "PASS",
            {"swarm_id": active.get("swarm_id"), "lane_id": lane_id, "action": action},
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-resolve-failure",
                "swarm_id": active.get("swarm_id"),
                "action": action,
                "status": active.get("status"),
                "progress": active.get("progress"),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "lane": target_lane,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "rebalance":
        try:
            lane_id = parse_flag_value(rest, "--lane-id")
        except ValueError:
            return usage()
        if rest:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "FAIL",
                    "command": "swarm-rebalance",
                    "error": "no active swarm plan",
                },
                as_json,
            )
        agents = load_pool_agents()
        active_agents = active_agent_map(agents)
        lanes = lane_rows(active)
        updated_lanes: list[dict[str, Any]] = []
        for lane in lanes:
            current_lane_id = str(lane.get("lane_id") or "")
            if lane_id and current_lane_id != lane_id:
                continue
            lane_status = str(lane.get("status") or "")
            if lane_status in {"completed", "failed", "closed"}:
                continue
            bg_job_id = str(lane.get("bg_job_id") or "").strip()
            if bg_job_id:
                current_bg_status = background_job_status(bg_job_id)
                lane["bg_job_status"] = current_bg_status
                if current_bg_status not in {"completed", "failed", "cancelled"}:
                    continue
            owner = str(lane.get("owner") or "").strip()
            should_reassign = (
                (not owner)
                or owner not in active_agents
                or lane_status == "handoff-pending"
            )
            if not should_reassign:
                continue
            replacement = choose_agent_owner(agents, str(lane.get("lane_type") or ""))
            if not replacement:
                continue
            if replacement == owner and lane_status != "handoff-pending":
                continue
            lane["previous_owner"] = owner or None
            lane["owner"] = replacement
            if lane_lease_identity_mode(lane) == "derived":
                lane["lease_identity"] = replacement
            lane["status"] = "planned"
            lane["rebalanced_at"] = now_iso()
            updated_lanes.append(dict(lane))
        active["updated_at"] = now_iso()
        refresh_swarm_runtime(active, agents, auto_progress=True)
        sync_swarm_history(state, active)
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-rebalance",
            "PASS",
            {"swarm_id": active.get("swarm_id"), "updated": len(updated_lanes)},
        )
        return emit(
            {
                "result": "PASS",
                "command": "swarm-rebalance",
                "swarm_id": active.get("swarm_id"),
                "status": active.get("status"),
                "updated_count": len(updated_lanes),
                "followups": active.get("followups", []),
                "failure_policy": active.get("failure_policy"),
                "coordination": active.get("coordination"),
                "updated_lanes": updated_lanes,
                "lanes": lanes,
            },
            as_json,
        )
    if subcommand == "close":
        try:
            reason = parse_flag_value(rest, "--reason") or "manual close"
        except ValueError:
            return usage()
        if rest:
            return usage()
        active = active_swarm_record(state)
        if not active:
            return emit(
                {
                    "result": "PASS",
                    "command": "swarm-close",
                    "status": "idle",
                    "warnings": ["no active swarm plan"],
                },
                as_json,
            )
        active["status"] = "closed"
        active["closed_at"] = now_iso()
        active["close_reason"] = reason
        history = swarm_history_list(state)
        if history and history[0].get("swarm_id") == active.get("swarm_id"):
            history[0] = active
        swarm["active"] = {}
        swarm["history"] = history
        save_json_file(DEFAULT_STATE_PATH, state)
        append_event(
            "workflow",
            "swarm-close",
            "PASS",
            {"swarm_id": active.get("swarm_id"), "reason": reason},
        )
        return emit({"result": "PASS", "command": "swarm-close", **active}, as_json)
    return usage()


def cmd_template(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        return usage()
    sub = argv[0]
    rest = argv[1:]
    DEFAULT_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    if sub == "list":
        templates = sorted(path.name for path in DEFAULT_TEMPLATE_DIR.glob("*.json"))
        return emit(
            {
                "result": "PASS",
                "command": "template-list",
                "count": len(templates),
                "templates": templates,
            },
            as_json,
        )
    if sub == "init":
        if not rest:
            return usage()
        name = rest[0].strip()
        if not name:
            return usage()
        path = DEFAULT_TEMPLATE_DIR / f"{name}.json"
        if path.exists():
            return emit(
                {
                    "result": "PASS",
                    "command": "template-init",
                    "path": str(path),
                    "status": "exists",
                },
                as_json,
            )
        template = {
            "name": name,
            "version": 1,
            "steps": [
                {"id": "prepare", "action": "gather-context"},
                {"id": "execute", "action": "implement"},
                {"id": "verify", "action": "run-validate"},
            ],
        }
        save_json_file(path, template)
        return emit(
            {
                "result": "PASS",
                "command": "template-init",
                "path": str(path),
                "status": "created",
            },
            as_json,
        )
    return usage()


def cmd_doctor(argv: list[str]) -> int:
    as_json = "--json" in argv
    state = load_json_file(DEFAULT_STATE_PATH)
    warnings: list[str] = []
    if not DEFAULT_TEMPLATE_DIR.exists():
        warnings.append("workflow template directory does not exist yet")
    history = history_list(state)
    return emit(
        {
            "result": "PASS",
            "command": "doctor",
            "state_path": str(DEFAULT_STATE_PATH),
            "template_dir": str(DEFAULT_TEMPLATE_DIR),
            "history_count": len(history),
            "warnings": warnings,
            "quick_fixes": [
                "/workflow template init baseline --json",
                "/workflow list --json",
            ],
        },
        as_json,
    )


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    command = argv[0]
    rest = argv[1:]
    if command in {"help", "-h", "--help"}:
        return usage()
    if command == "validate":
        return cmd_validate(rest)
    if command == "run":
        return cmd_run(rest)
    if command == "status":
        return cmd_status(rest)
    if command == "resume":
        return cmd_resume(rest)
    if command == "stop":
        return cmd_stop(rest)
    if command == "swarm":
        return cmd_swarm(rest)
    if command == "list":
        return cmd_list(rest)
    if command == "template":
        return cmd_template(rest)
    if command == "doctor":
        return cmd_doctor(rest)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
