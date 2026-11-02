"""Deterministic qualification fixtures, not a graph writer or execution engine."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from codememory_task_graph_projection import (
    SourceSnapshot,
    SourceTask,
    build_projection,
)
from intent_coordinator_command import normalize_proposal
from task_graph_runtime import bounded_frontier

SIZES = (50, 250, 1000)


class QualificationError(RuntimeError):
    pass


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise QualificationError(detail)


def fragments(size: int) -> list[dict[str, Any]]:
    require(type(size) is int and 1 <= size <= 1000, "fixture size must be 1..1000")
    result = []
    for offset in range(0, size, 3):
        root = f"epic:group{offset:05}"
        records = [
            {
                "key": root,
                "entity_type": "epic",
                "title": f"qual-{size:04}-group-{offset:05}",
                "goal": "Deliver one bounded requirement group",
                "summary": "Foundation and dependent implementation slices",
            }
        ]
        links = []
        for number in range(offset, min(offset + 3, size)):
            key = f"task:r{number:05}"
            records.append(
                {
                    "key": key,
                    "entity_type": "task",
                    "title": f"qual-{size:04}-task-{number:05}",
                    "goal": f"Satisfy requirement-{number:05}",
                    "summary": "Implement and validate this independently tracked requirement",
                }
            )
            parent = root if number == offset else f"task:r{offset:05}"
            links.append({"from": parent, "edge": "parent-of", "to": key})
            if number != offset:
                links.append({"from": key, "edge": "depends-on", "to": parent})
        result.append(
            normalize_proposal(
                {
                    "version": 1,
                    "proposal_id": f"qual-{size:04}-{offset:05}",
                    "scope": f"qualification/rolling-{size}",
                    "source": {
                        "kind": "agent",
                        "id": f"fixture-{size}-{offset}",
                        "summary": "Qualify bounded decomposition against independent requirement inventory",
                    },
                    "records": records,
                    "links": links,
                }
            )
        )
    return result


def coverage(
    proposals: list[dict], assignments: list[tuple[str, str]], size: int
) -> dict:
    # Independent expected inventory: never infer expected requirements from the
    # same proposals being checked, so dropped records cannot redefine success.
    expected = {f"requirement-{i:05}" for i in range(size)}
    require(len(assignments) == size, "coverage assignment count mismatch")
    require(
        {atom for atom, _ in assignments} == expected,
        "missing or duplicate requirement atom",
    )
    require(len({key for _, key in assignments}) == size, "duplicate requirement owner")
    records = [
        record
        for proposal in proposals
        for record in normalize_proposal(proposal)["records"]
    ]
    require(
        len({record["key"] for record in records}) == len(records),
        "duplicate record key",
    )
    require(
        len({(record["entity_type"], record["title"]) for record in records})
        == len(records),
        "duplicate record title",
    )
    tasks = {record["key"] for record in records if record["entity_type"] == "task"}
    roots = {record["key"] for record in records if record["entity_type"] == "epic"}
    require(
        len(tasks) == size and len(roots) == (size + 2) // 3,
        "task or epic count mismatch",
    )
    require(
        {key for _, key in assignments} == tasks,
        "coverage owners do not equal tracked tasks",
    )
    parents = {}
    dependencies = set()
    for proposal in proposals:
        for link in proposal["links"]:
            if link["edge"] == "parent-of":
                require(link["to"] not in parents, "duplicate hierarchy parent")
                parents[link["to"]] = link["from"]
            elif link["edge"] == "depends-on":
                pair = (link["from"], link["to"])
                require(pair not in dependencies, "duplicate dependency")
                dependencies.add(pair)
    require(set(parents) == tasks, "missing hierarchy edge")
    max_depth = 0
    for key in tasks:
        seen = set()
        while key not in roots:
            require(key in parents and key not in seen, "broken or cyclic hierarchy")
            seen.add(key)
            key = parents[key]
        max_depth = max(max_depth, len(seen))
    require(len(dependencies) == size - len(roots), "dependency count mismatch")
    require(
        all(source in tasks and target in tasks for source, target in dependencies),
        "dependency endpoint missing",
    )
    return {
        "task_count": len(tasks),
        "epic_count": len(roots),
        "covered_requirements": len(expected),
        "hierarchy_edges": len(parents),
        "dependency_edges": len(dependencies),
        "max_task_depth": max_depth,
    }


def assignments(size: int) -> list[tuple[str, str]]:
    return [(f"requirement-{i:05}", f"task:r{i:05}") for i in range(size)]


def model_snapshot(
    proposals: list[dict], status: dict[str, str] | None = None
) -> SourceSnapshot:
    records = [r for p in proposals for r in p["records"] if r["entity_type"] == "task"]
    return SourceSnapshot(
        scope_key=proposals[0]["scope"],
        tasks=tuple(
            SourceTask(
                r["key"],
                r["title"],
                "feature",
                (status or {}).get(r["key"], "not-started"),
            )
            for r in records
        ),
        dependencies=tuple(
            (link["from"], link["to"])
            for p in proposals
            for link in p["links"]
            if link["edge"] == "depends-on"
        ),
    )


def rolling_model(
    snapshot: SourceSnapshot, checkpoint: Path, *, seconds: float = 30
) -> dict:
    deadline = time.monotonic() + seconds
    tasks = copy.deepcopy(list(build_projection(snapshot).tasks))
    expected = {task["id"] for task in tasks}
    completed = set()
    waves = peak = 0
    checkpoint_recovered = False
    while len(completed) < len(expected):
        require(time.monotonic() < deadline, "rolling model latency budget exceeded")
        selected = bounded_frontier(tasks)["tasks"]
        require(bool(selected), "rolling model deadlocked before complete coverage")
        waves += 1
        peak = max(peak, len(selected))
        selected_ids = {task["id"] for task in selected}
        require(not selected_ids & completed, "completed task selected twice")
        for task in selected:
            task["status"] = "in_progress"
            task["metadata"]["codememory"]["source_status"] = "doing"
        require(
            bounded_frontier(tasks)["selected_count"] == 0 or len(selected) == 1,
            "active work did not consume frontier capacity",
        )
        if not checkpoint_recovered and waves == 2:
            statuses = {
                task["id"]: {
                    "pending": "not-started",
                    "in_progress": "doing",
                    "completed": "done",
                }[task["status"]]
                for task in tasks
            }
            checkpoint.write_text(json.dumps(statuses, sort_keys=True))
            restored = json.loads(checkpoint.read_text())
            require(restored == statuses, "checkpoint changed")
            before = bounded_frontier(tasks)
            resumed = SourceSnapshot(
                snapshot.scope_key,
                tuple(
                    SourceTask(task.id, task.title, task.kind, restored[task.id])
                    for task in snapshot.tasks
                ),
                snapshot.dependencies,
            )
            tasks = copy.deepcopy(list(build_projection(resumed).tasks))
            require(
                bounded_frontier(tasks) == before,
                "checkpoint reload changed next frontier",
            )
            checkpoint_recovered = True
        # Fixture-only authoritative completions: no production lifecycle writes,
        # process attempts, or uncertain external effects are simulated as done.
        for task in tasks:
            if task["id"] in selected_ids:
                task["status"] = "completed"
                task["metadata"]["codememory"]["source_status"] = "done"
        completed.update(selected_ids)
    require(
        completed == expected and peak <= 2, "rolling coverage or frontier bound failed"
    )
    return {
        "completed_task_count": len(completed),
        "wave_count": waves,
        "peak_frontier": peak,
        "checkpoint_recovered": checkpoint_recovered,
        "execution_model": "fixture-completions-not-processes",
    }
