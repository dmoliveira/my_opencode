from __future__ import annotations

import copy
import json
import os
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bounded_subprocess import BoundedCommandError, run_bounded
from task_graph_runtime import (
    PROJECTION_SCHEMA_VERSION,
    StrictState,
    is_codememory_managed,
    load_strict_state,
    now_iso,
    projection_fingerprint,
    projection_health,
    projection_task_semantic,
    with_locked_projection_state,
)

SOURCE_STATUSES = (
    "not-started",
    "doing",
    "blocked",
    "done",
    "failed",
    "canceled",
)
STATUS_MAP = {
    "not-started": "pending",
    "doing": "in_progress",
    "blocked": "blocked",
    "done": "completed",
    "failed": "failed",
    "canceled": "canceled",
}
SOURCE_MAX_RECORDS = 10_000
SOURCE_FETCH_LIMIT = SOURCE_MAX_RECORDS + 1
FIXED_TASK_TIMESTAMP = "1970-01-01T00:00:00Z"
TASK_ID_MAX_CHARS = 256


class ProjectionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


Runner = Callable[[list[str], str], dict[str, Any]]


@dataclass(frozen=True)
class SourceTask:
    id: str
    title: str
    kind: str
    status: str


@dataclass(frozen=True)
class SourceLink:
    id: str
    edge_type: str
    from_id: str
    to_id: str


@dataclass(frozen=True)
class SourceIndex:
    tasks: tuple[SourceTask, ...]
    links: tuple[SourceLink, ...]


@dataclass(frozen=True)
class SourceSnapshot:
    scope_key: str
    tasks: tuple[SourceTask, ...]
    dependencies: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TaskGraphProjection:
    scope_key: str
    fingerprint: str
    revision: str
    tasks: tuple[dict[str, Any], ...]


def _text(value: Any, *, field: str, max_chars: int = 4096) -> str:
    if not isinstance(value, str):
        raise ProjectionError(
            "task_projection_source_invalid", f"{field} must be a string"
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > max_chars
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise ProjectionError("task_projection_source_invalid", f"{field} is invalid")
    return normalized


def _json_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectionError(
            "task_projection_source_invalid", f"{label} must be an object"
        )
    return value


def make_oc_runner(*, oc_bin: str, config_path: Path | None, cwd: Path) -> Runner:
    def run(arguments: list[str], operation: str) -> dict[str, Any]:
        command = [oc_bin]
        if config_path is not None:
            command.extend(["--config", str(config_path.expanduser())])
        command.extend(arguments)
        try:
            if operation == "task_projection_codememory_list":
                completed = run_bounded(
                    command,
                    operation="task_projection_codememory_list",
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                )
            elif operation == "task_projection_codememory_get":
                completed = run_bounded(
                    command,
                    operation="task_projection_codememory_get",
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                )
            else:
                raise ProjectionError(
                    "task_projection_operation_invalid",
                    f"unsupported projection operation: {operation}",
                )
        except BoundedCommandError as exc:
            detail = exc.failure.stderr or exc.failure.detail
            raise ProjectionError(exc.reason_code, detail[:2000]) from exc
        stdout = str(completed.stdout or "").strip()
        stderr = str(completed.stderr or "").strip()
        if completed.returncode != 0:
            raise ProjectionError(
                f"{operation}_failed",
                (stderr or stdout or f"command exited {completed.returncode}")[:2000],
            )
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ProjectionError(
                f"{operation}_invalid_json", "Codememory returned invalid JSON"
            ) from exc
        return _json_object(payload, label="Codememory response")

    return run


def _list_records(
    runner: Runner,
    *,
    entity: str,
    scope: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    arguments = [
        "list",
        entity,
        "--scope",
        scope,
        "--limit",
        str(SOURCE_FETCH_LIMIT),
        "--format",
        "json",
    ]
    if status is not None:
        arguments.extend(["--status", status])
    payload = runner(arguments, "task_projection_codememory_list")
    if (
        payload.get("type") != "list_result"
        or payload.get("entity_type") != entity
        or payload.get("scope_key") != scope
        or not isinstance(payload.get("items"), list)
        or isinstance(payload.get("count"), bool)
        or not isinstance(payload.get("count"), int)
        or payload["count"] != len(payload["items"])
    ):
        raise ProjectionError(
            "task_projection_source_invalid",
            f"Codememory returned an invalid {entity} listing",
        )
    if len(payload["items"]) >= SOURCE_FETCH_LIMIT:
        raise ProjectionError(
            "task_projection_source_too_large",
            f"Codememory {entity} listing exceeds {SOURCE_MAX_RECORDS} records",
        )
    return [
        _json_object(item, label=f"Codememory {entity} item")
        for item in payload["items"]
    ]


def _task_from_item(item: dict[str, Any], status: str) -> SourceTask:
    task_id = _text(item.get("id"), field="task id", max_chars=TASK_ID_MAX_CHARS)
    title = _text(item.get("display"), field=f"task {task_id} title")
    kind = _text(item.get("kind"), field=f"task {task_id} kind", max_chars=64)
    return SourceTask(id=task_id, title=title, kind=kind, status=status)


def _task_index(runner: Runner, scope: str) -> tuple[SourceTask, ...]:
    all_items = _list_records(runner, entity="task", scope=scope)
    all_by_id: dict[str, tuple[str, str]] = {}
    for item in all_items:
        task = _task_from_item(item, SOURCE_STATUSES[0])
        if task.id in all_by_id:
            raise ProjectionError(
                "task_projection_source_duplicate",
                f"Codememory returned duplicate task id {task.id}",
            )
        all_by_id[task.id] = (task.title, task.kind)

    categorized: dict[str, SourceTask] = {}
    for status in SOURCE_STATUSES:
        for item in _list_records(runner, entity="task", scope=scope, status=status):
            task = _task_from_item(item, status)
            if task.id in categorized:
                raise ProjectionError(
                    "task_projection_source_changed",
                    f"Codememory task {task.id} appeared in multiple statuses",
                )
            if all_by_id.get(task.id) != (task.title, task.kind):
                raise ProjectionError(
                    "task_projection_source_changed",
                    f"Codememory task {task.id} changed during listing",
                )
            categorized[task.id] = task
    if set(categorized) != set(all_by_id):
        missing = sorted(set(all_by_id) - set(categorized))
        raise ProjectionError(
            "task_projection_source_status_unknown",
            "Codememory tasks have unsupported or unstable statuses: "
            + ", ".join(missing[:20]),
        )
    return tuple(sorted(categorized.values(), key=lambda task: task.id))


def _link_index(runner: Runner, scope: str) -> tuple[SourceLink, ...]:
    links: dict[str, SourceLink] = {}
    for item in _list_records(runner, entity="link", scope=scope):
        link_id = _text(item.get("id"), field="link id", max_chars=256)
        if link_id in links:
            raise ProjectionError(
                "task_projection_source_duplicate",
                f"Codememory returned duplicate link id {link_id}",
            )
        payload = runner(
            ["get", link_id, "--view", "full", "--format", "json"],
            "task_projection_codememory_get",
        )
        if payload.get("id") != link_id or payload.get("type") != "link":
            raise ProjectionError(
                "task_projection_source_invalid",
                f"Codememory returned invalid detail for link {link_id}",
            )
        links[link_id] = SourceLink(
            id=link_id,
            edge_type=_text(
                payload.get("edge_type"),
                field=f"link {link_id} edge_type",
                max_chars=64,
            ),
            from_id=_text(
                payload.get("from_id"), field=f"link {link_id} from_id", max_chars=256
            ),
            to_id=_text(
                payload.get("to_id"), field=f"link {link_id} to_id", max_chars=256
            ),
        )
    return tuple(sorted(links.values(), key=lambda link: link.id))


def _scan_source_index(runner: Runner, scope: str) -> SourceIndex:
    return SourceIndex(
        tasks=_task_index(runner, scope), links=_link_index(runner, scope)
    )


def load_source_snapshot(runner: Runner, scope: str) -> SourceSnapshot:
    normalized_scope = _text(scope, field="scope", max_chars=256)
    before = _scan_source_index(runner, normalized_scope)
    task_ids = {task.id for task in before.tasks}
    dependencies: set[tuple[str, str]] = set()
    for link in before.links:
        if link.edge_type == "blocked-by" and link.from_id in task_ids:
            raise ProjectionError(
                "task_projection_source_unsupported_edge",
                "Codememory link "
                f"{link.id} uses blocked-by from projected task {link.from_id}",
            )
        if link.edge_type != "depends-on":
            continue
        if (
            link.from_id not in task_ids
            or link.to_id not in task_ids
            or link.from_id == link.to_id
        ):
            raise ProjectionError(
                "task_projection_source_invalid",
                f"task dependency link {link.id} has invalid endpoints",
            )
        dependency = (link.from_id, link.to_id)
        if dependency in dependencies:
            raise ProjectionError(
                "task_projection_source_duplicate",
                f"duplicate task dependency {link.from_id} -> {link.to_id}",
            )
        dependencies.add(dependency)
    after = _scan_source_index(runner, normalized_scope)
    if before != after:
        raise ProjectionError(
            "task_projection_source_changed",
            "Codememory changed while the projection snapshot was read",
        )
    return SourceSnapshot(
        scope_key=normalized_scope,
        tasks=before.tasks,
        dependencies=tuple(sorted(dependencies)),
    )


def build_projection(snapshot: SourceSnapshot) -> TaskGraphProjection:
    blocked_by: dict[str, list[str]] = {task.id: [] for task in snapshot.tasks}
    for task_id, dependency_id in snapshot.dependencies:
        blocked_by[task_id].append(dependency_id)
    tasks: list[dict[str, Any]] = []
    for source in snapshot.tasks:
        tasks.append(
            {
                "id": source.id,
                "subject": source.title,
                "description": "",
                "status": STATUS_MAP[source.status],
                "activeForm": source.title,
                "blockedBy": sorted(set(blocked_by[source.id])),
                "blocks": [],
                "owner": "codememory",
                "metadata": {
                    "command_family": "codememory",
                    "codememory": {
                        "managed": True,
                        "schema_version": PROJECTION_SCHEMA_VERSION,
                        "scope_key": snapshot.scope_key,
                        "task_id": source.id,
                        "source_status": source.status,
                        "kind": source.kind,
                    },
                },
                "completionGates": {},
                "requiredArtifacts": [],
                "threadID": "",
                "created_at": FIXED_TASK_TIMESTAMP,
                "updated_at": FIXED_TASK_TIMESTAMP,
            }
        )
    tasks.sort(key=lambda task: task["id"])
    fingerprint = projection_fingerprint(snapshot.scope_key, tasks)
    return TaskGraphProjection(
        scope_key=snapshot.scope_key,
        fingerprint=fingerprint,
        revision=f"sha256:{fingerprint}",
        tasks=tuple(tasks),
    )


def _projection_header(
    projection: TaskGraphProjection, projected_at: str
) -> dict[str, Any]:
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "source": "codememory",
        "scope_key": projection.scope_key,
        "revision": projection.revision,
        "fingerprint": projection.fingerprint,
        "managed_task_count": len(projection.tasks),
        "projected_at": projected_at,
    }


def projection_drift(
    strict_state: StrictState, projection: TaskGraphProjection
) -> dict[str, Any]:
    state = strict_state.state
    existing_tasks = {
        str(task.get("id") or ""): task
        for task in state.get("tasks", [])
        if isinstance(task, dict)
    }
    expected_tasks = {task["id"]: task for task in projection.tasks}
    managed_tasks = {
        task_id: task
        for task_id, task in existing_tasks.items()
        if is_codememory_managed(task)
    }
    managed_scopes = {
        str(task.get("metadata", {}).get("codememory", {}).get("scope_key") or "")
        for task in managed_tasks.values()
    }
    header = (
        state.get("projection") if isinstance(state.get("projection"), dict) else {}
    )
    header_scope = str(header.get("scope_key") or "")
    scope_mismatch = sorted(
        scope
        for scope in managed_scopes | ({header_scope} if header_scope else set())
        if scope and scope != projection.scope_key
    )
    collisions = sorted(
        task_id
        for task_id in expected_tasks
        if task_id in existing_tasks and task_id not in managed_tasks
    )
    missing = sorted(
        task_id
        for task_id in expected_tasks
        if task_id not in existing_tasks and task_id not in collisions
    )
    extra = sorted(set(managed_tasks) - set(expected_tasks))
    changed: list[str] = []
    dependency_changed: list[str] = []
    for task_id in sorted(set(managed_tasks) & set(expected_tasks)):
        actual = projection_task_semantic(managed_tasks[task_id])
        expected = projection_task_semantic(expected_tasks[task_id])
        if actual.get("blockedBy") != expected.get("blockedBy"):
            dependency_changed.append(task_id)
        if actual != expected:
            changed.append(task_id)

    raw_tasks = strict_state.raw_state.get("tasks", [])
    raw_ids = {
        str(task.get("id") or "") for task in raw_tasks if isinstance(task, dict)
    }
    retained_references: list[dict[str, str]] = []
    invalid_references: list[dict[str, str]] = []
    for task in raw_tasks:
        if not isinstance(task, dict) or is_codememory_managed(task):
            continue
        task_id = str(task.get("id") or "")
        for dependency_id in task.get("blockedBy", []):
            if dependency_id in extra:
                retained_references.append(
                    {"task_id": task_id, "dependency_id": dependency_id}
                )
            elif dependency_id not in raw_ids and dependency_id not in expected_tasks:
                invalid_references.append(
                    {"task_id": task_id, "dependency_id": dependency_id}
                )

    expected_header = _projection_header(
        projection, str(header.get("projected_at") or "")
    )
    metadata_drift = any(
        header.get(key) != expected_header[key]
        for key in (
            "schema_version",
            "source",
            "scope_key",
            "revision",
            "fingerprint",
            "managed_task_count",
        )
    ) or not isinstance(header.get("projected_at"), str)
    drifted = (
        any(
            (
                scope_mismatch,
                collisions,
                missing,
                extra,
                changed,
                dependency_changed,
                retained_references,
                invalid_references,
            )
        )
        or metadata_drift
    )
    return {
        "drifted": drifted,
        "scope_mismatch": scope_mismatch,
        "collisions": collisions,
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "dependency_changed": dependency_changed,
        "retained_references": retained_references,
        "invalid_references": invalid_references,
        "metadata_drift": metadata_drift,
    }


def _blocking_drift(report: dict[str, Any]) -> bool:
    return any(
        report.get(key)
        for key in (
            "scope_mismatch",
            "collisions",
            "retained_references",
            "invalid_references",
        )
    )


def check_projection(
    write_path: Path, projection: TaskGraphProjection
) -> dict[str, Any]:
    strict_state = load_strict_state(write_path)
    return projection_drift(strict_state, projection)


def apply_projection(
    write_path: Path, projection: TaskGraphProjection
) -> tuple[dict[str, Any], bool, Path]:
    report_holder: dict[str, Any] = {}

    def mutate(strict_state: StrictState) -> dict[str, Any]:
        report = projection_drift(strict_state, projection)
        report_holder.update(report)
        if _blocking_drift(report):
            raise ProjectionError(
                "task_projection_apply_blocked",
                "projection apply blocked by scope, collision, "
                "or retained-reference drift",
            )
        if not report["drifted"]:
            return strict_state.state
        unmanaged = [
            copy.deepcopy(task)
            for task in strict_state.state.get("tasks", [])
            if isinstance(task, dict) and not is_codememory_managed(task)
        ]
        next_state = dict(strict_state.state)
        next_state["tasks"] = unmanaged + [
            copy.deepcopy(task) for task in projection.tasks
        ]
        next_state["projection"] = _projection_header(projection, now_iso())
        return next_state

    locked = with_locked_projection_state(write_path, mutate)
    return report_holder, locked.changed, locked.runtime_path


def projection_local_health(state: dict[str, Any]) -> dict[str, Any]:
    return projection_health(state)


def default_oc_bin() -> str:
    return os.environ.get("MY_OPENCODE_CODEMEMORY_BIN", "oc").strip() or "oc"


def default_oc_config() -> Path | None:
    configured = os.environ.get("MY_OPENCODE_CODEMEMORY_CONFIG", "").strip()
    return Path(configured).expanduser() if configured else None
