"""Qualify isolated SQLite intake, coverage, rolling advice and fenced execution."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codememory_task_graph_projection as projection
import intent_coordinator_command as coordinator
import intent_planner as planner
from bounded_subprocess import BoundedCommandError, resolve_timeout_seconds, run_bounded
from rolling_decomposition import (
    SIZES,
    QualificationError,
    assignments,
    coverage,
    fragments,
    require,
    rolling_model,
)
from task_graph_runtime import (
    TaskGraphStateError,
    bounded_frontier,
    load_state,
    lock_path,
    runtime_path,
)


def latency_budgets(size: int) -> dict[str, float]:
    groups = (size + 2) // 3
    links = 2 * size - groups
    # Nine-task calibration: 0.12 s/native launch on this host. Gate at
    # 0.20 s/operation plus one full process timeout reserve, never fitted after a run.
    return {
        "intake": 30 + 0.20 * (8 * groups + 16),
        "snapshot": max(30.0, 10 + 0.20 * (2 * links + 17)),
        "local": 30.0,
        "execution": 60.0,
    }


class LostReply(RuntimeError):
    pass


class NativeScope:
    def __init__(self, root: Path, binary: str):
        self.root = root
        self.binary = binary
        self.config = root / "config.sqlite.yaml"
        self.database = root / "graph.sqlite3"
        self.config.write_text(
            "\n".join(
                [
                    "version: 1",
                    "database:",
                    "  backend: sqlite",
                    "  url: ''",
                    "  path: " + json.dumps(str(self.database)),
                    "  max_connections: 1",
                    "cache:",
                    "  enabled: false",
                    "  dir: " + json.dumps(str(root / "cache")),
                    "  reuse_unchanged: false",
                    "  ttl_minutes: 60",
                    "defaults:",
                    "  scope_key: qualification/isolated",
                    "  canonicalize_worktree: true",
                    "  prefer_alias: true",
                    "session:",
                    "  stale_after_minutes: 30",
                    "  touch_on_write: true",
                    "",
                ]
            )
        )
        # No inherited config/SQLite overrides, provider keys, plugins or runtime
        # locations can redirect this standalone qualification into host state.
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(root),
            "LANG": "C.UTF-8",
            "XDG_CONFIG_HOME": str(root / "home-config"),
            "XDG_CACHE_HOME": str(root / "home-cache"),
            "XDG_DATA_HOME": str(root / "home-data"),
            "XDG_STATE_HOME": str(root / "home-state"),
            "CI": "true",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "MY_OPENCODE_BG_DIR": str(root / "bg"),
            "MY_OPENCODE_BG_NOTIFICATIONS_ENABLED": "0",
        }
        self.deadline = time.monotonic() + 60
        self.calls = 0
        self.batch_calls = 0
        self.links = {}
        self.stages = {}
        self.budgets = latency_budgets(9)
        self.invoke(["db", "migrate", "--format", "json"], mutation=True)
        doctor = self.invoke(["config", "--doctor", "--format", "json"])
        require(
            doctor.get("runtime_ready") is True and doctor.get("backend") == "sqlite",
            "isolated SQLite backend unavailable",
        )
        require(
            Path(doctor.get("database_path", "")).resolve() == self.database,
            "backend escaped isolated database",
        )

    @contextmanager
    def stage(self, name: str):
        started = time.monotonic()
        before = self.calls
        self.deadline = started + self.budgets[name]
        yield
        elapsed = time.monotonic() - started
        require(elapsed <= self.budgets[name], f"{name} latency budget exceeded")
        print(
            f"size={self.root.name} stage={name} elapsed={elapsed:.3f}s calls={self.calls - before}",
            file=sys.stderr,
            flush=True,
        )
        self.stages[name] = {
            "seconds": round(elapsed, 3),
            "budget_seconds": self.budgets[name],
            "subprocess_calls": self.calls - before,
        }

    def bounded(
        self, command: list[str], *, mutation: bool = False, cwd: Path | None = None
    ):
        operation = (
            "rolling_qualification_mutation" if mutation else "rolling_qualification_probe"
        )
        # Reserve the full existing process-policy timeout before admission. This
        # conservatively fails early rather than starting an operation that can
        # outlive the remaining aggregate stage budget.
        _, timeout = resolve_timeout_seconds(operation)
        require(
            self.deadline - time.monotonic() >= timeout,
            "insufficient aggregate deadline for bounded command",
        )
        self.calls += 1
        options = {"cwd": cwd or self.root, "env": self.env, "capture_output": True,
                   "text": True, "max_output_bytes": 2 * 1024 * 1024}
        if mutation:
            result = run_bounded(command, operation="rolling_qualification_mutation", **options)
        else:
            result = run_bounded(command, operation="rolling_qualification_probe", **options)
        require(time.monotonic() <= self.deadline, "aggregate stage deadline exceeded")
        require(
            result.returncode == 0,
            "isolated subprocess failed: "
            + str(result.stderr or result.stdout)[-1500:],
        )
        return result

    def invoke(
        self, arguments: list[str], *, mutation: bool = False, cwd: Path | None = None
    ) -> dict:
        result = self.bounded(
            [self.binary, "--config", str(self.config), *arguments],
            mutation=mutation,
            cwd=cwd,
        )
        value = json.loads(result.stdout)
        require(isinstance(value, dict), "native result is not an object")
        return value

    def __call__(self, arguments: list[str], operation: str) -> dict:
        allowed = {
            "intent_codememory_doctor",
            "intent_codememory_find",
            "intent_codememory_apply",
            "task_projection_codememory_list",
            "task_projection_codememory_get",
        }
        require(operation in allowed, "unsupported qualification operation")
        mutation = operation == "intent_codememory_apply"
        self.batch_calls += int(mutation)
        result = self.invoke(arguments, mutation=mutation)
        if operation == "task_projection_codememory_get":
            self.links[result["id"]] = result
        return result


def admit(proposal: dict, root: Path) -> dict:
    request = {
        key: proposal[key] for key in ("version", "proposal_id", "scope", "source")
    }
    request["research"] = [
        {"id": "contract", "path": "contract.md", "start_line": 1, "end_line": 1}
    ]
    research = planner.research(request, root, planner.Budget())
    wrapper = {
        "version": 1,
        "research": research,
        "proposal": proposal,
        "assessments": [
            {
                "target": target,
                "evidence": ["source", "contract"],
                "rationale": "Independent fixture inventory requires this bounded graph element",
                "acceptance": "Authoritative task, hierarchy and dependency inventory matches exactly",
            }
            for target in sorted(planner.targets(proposal))
        ],
        "unresolved": [],
    }
    return planner.plan(wrapper, root, planner.Budget())["proposal"]


def intake(proposals: list[dict], backend: NativeScope) -> dict[str, str]:
    state_dir = backend.root / "receipts"
    mapping = {}
    midpoint = len(proposals) // 2
    for index, proposal in enumerate(proposals):
        if index % 50 == 0:
            print(
                f"size={backend.root.name} intake_fragment={index}/{len(proposals)}",
                file=sys.stderr,
                flush=True,
            )
        admitted = admit(proposal, backend.root)
        if index == midpoint:

            def lose_reply(arguments, operation):
                result = backend(arguments, operation)
                if operation == "intent_codememory_apply":
                    raise LostReply(
                        "injected loss after native commit before receipt acknowledgement"
                    )
                return result

            try:
                coordinator.apply_proposal(
                    admitted, lose_reply, state_dir=state_dir, actor="qualification"
                )
            except LostReply:
                pass
            else:
                raise QualificationError("lost-reply failpoint did not execute")
            receipt = coordinator._load_receipt(
                coordinator._receipt_path(state_dir, admitted)
            )
            require(
                receipt is not None and receipt["status"] == "prepared",
                "uncertain reply did not preserve prepared receipt",
            )
        report = coordinator.apply_proposal(
            admitted, backend, state_dir=state_dir, actor="qualification"
        )
        for record in report["records"]:
            require(record["key"] not in mapping, "duplicate symbolic record")
            mapping[record["key"]] = record["id"]
        # Reopening the same state emulates process restart: no in-memory
        # receipt cache participates, and an applied replay calls no backend.
        before = backend.calls
        replay = coordinator.apply_proposal(
            copy.deepcopy(admitted),
            backend,
            state_dir=Path(str(state_dir)),
            actor="qualification",
        )
        require(
            replay["replayed"] is True
            and replay["records"] == report["records"]
            and replay["links"] == report["links"],
            "applied replay changed identities",
        )
        require(backend.calls == before, "applied replay invoked backend")
    changed = copy.deepcopy(proposals[0])
    changed["source"]["summary"] = "Conflicting replay content"
    before = backend.calls
    try:
        coordinator.apply_proposal(
            changed, backend, state_dir=state_dir, actor="qualification"
        )
    except coordinator.CoordinatorError as exc:
        require(
            exc.reason_code == "intent_proposal_id_conflict",
            "wrong conflicting replay rejection",
        )
    else:
        raise QualificationError("changed replay was admitted")
    require(backend.calls == before, "conflicting replay called backend")
    duplicate = copy.deepcopy(proposals[0])
    duplicate["proposal_id"] += "-duplicate"
    batches = backend.batch_calls
    try:
        coordinator.apply_proposal(
            duplicate, backend, state_dir=state_dir, actor="qualification"
        )
    except coordinator.CoordinatorError as exc:
        require(
            exc.reason_code == "intent_title_collision",
            "wrong duplicate-title rejection",
        )
    else:
        raise QualificationError("new-ID semantic duplicate was admitted")
    require(
        backend.batch_calls == batches,
        "duplicate-title rejection reached native mutation",
    )
    return mapping


def verify_source(proposals: list[dict], mapping: dict, backend: NativeScope):
    scope = proposals[0]["scope"]
    backend.links.clear()
    snapshot = projection.load_source_snapshot(backend, scope)
    expected_tasks = {
        mapping[r["key"]]
        for p in proposals
        for r in p["records"]
        if r["entity_type"] == "task"
    }
    expected_epics = {
        mapping[r["key"]]
        for p in proposals
        for r in p["records"]
        if r["entity_type"] == "epic"
    }
    require(
        {task.id for task in snapshot.tasks} == expected_tasks,
        "native task coverage mismatch",
    )
    epics = backend.invoke(
        ["list", "epic", "--scope", scope, "--limit", "10001", "--format", "json"]
    )
    require(
        epics.get("count") == len(expected_epics)
        and {item["id"] for item in epics["items"]} == expected_epics,
        "native epic inventory mismatch",
    )
    expected_links = {
        (mapping[link["from"]], link["edge"], mapping[link["to"]])
        for p in proposals
        for link in p["links"]
    }
    actual_links = {
        (link["from_id"], link["edge_type"], link["to_id"])
        for link in backend.links.values()
    }
    require(
        len(backend.links) == len(expected_links) and actual_links == expected_links,
        "authoritative hierarchy/dependency coverage mismatch",
    )
    require(
        set(snapshot.dependencies)
        == {
            (source, target)
            for source, edge, target in expected_links
            if edge == "depends-on"
        },
        "projected dependency direction mismatch",
    )
    return snapshot


@contextmanager
def isolated_projection_paths(root: Path, write_path: Path):
    runtime = write_path.parent / "my_opencode" / "runtime" / "task_graph.json"
    overrides = {
        "MY_OPENCODE_TASK_GRAPH_PATH": str(runtime),
        "MY_OPENCODE_TASK_GRAPH_LOCK_PATH": str(runtime.with_suffix(".lock")),
    }
    previous = {name: os.environ.get(name) for name in overrides}
    try:
        os.environ.update(overrides)
        require(
            runtime_path(write_path).resolve().is_relative_to(root.resolve()),
            "projection runtime escaped sandbox",
        )
        require(
            lock_path(write_path).resolve().is_relative_to(root.resolve()),
            "projection lock escaped sandbox",
        )
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def local_checks(snapshot, root: Path) -> dict:
    write_path = root / "projected-config" / "opencode.json"
    with isolated_projection_paths(root, write_path):
        return _local_checks(snapshot, root, write_path)


def _local_checks(snapshot, root: Path, write_path: Path) -> dict:
    projected = projection.build_projection(snapshot)
    _, changed, runtime = projection.apply_projection(write_path, projected)
    require(changed, "initial projection did not materialize")
    original = runtime.read_bytes()
    _, changed, _ = projection.apply_projection(write_path, projected)
    require(
        not changed and runtime.read_bytes() == original,
        "projection replay was not byte stable",
    )
    require(
        not projection.check_projection(write_path, projected)["drifted"],
        "fresh projection drifted",
    )
    tampered = json.loads(original)
    tampered["tasks"][0]["subject"] = "tampered"
    runtime.write_text(json.dumps(tampered))
    require(
        projection.check_projection(write_path, projected)["drifted"],
        "tampering did not produce drift",
    )
    try:
        load_state(write_path)
    except TaskGraphStateError:
        pass
    else:
        raise QualificationError("tampered projection was admitted")
    runtime.write_bytes(original)
    return rolling_model(snapshot, root / "restart-checkpoint.json")


def execution_smoke(snapshot, backend: NativeScope) -> dict:
    frontier = bounded_frontier(list(projection.build_projection(snapshot).tasks), 2)
    ready = [
        task
        for task in projection.build_projection(snapshot).tasks
        if not task["blockedBy"]
    ]
    require(
        len(ready) >= 3 and frontier["selected_count"] == 2,
        "execution fixture lacks two selected plus third-ready task",
    )
    selected = frontier["tasks"]
    selected_ids = {task["id"] for task in selected}
    third = next(task for task in ready if task["id"] not in selected_ids)
    blocked = next(
        task
        for task in projection.build_projection(snapshot).tasks
        if task["blockedBy"]
    )
    release = backend.root / "release-processes"
    workers = []
    bg_script = SCRIPT_DIR / "background_task_manager.py"
    for index, task in enumerate([*selected, third]):
        worker = backend.root / f"worker-{index}"
        worker.mkdir()
        workers.append(worker)
        session = backend.invoke(
            [
                "add",
                "session",
                f"isolated worker {index}",
                "--scope",
                snapshot.scope_key,
                "--task",
                task["id"],
                "--worktree",
                str(worker),
                "--format",
                "json",
            ],
            mutation=True,
            cwd=worker,
        )
        if index < 2:
            backend.invoke(
                [
                    "transition",
                    task["id"],
                    "doing",
                    "--reason",
                    "isolated qualification execution",
                    "--format",
                    "json",
                ],
                mutation=True,
                cwd=worker,
            )
        marker = worker / "started"
        code = (
            "import pathlib,time; p=pathlib.Path("
            + repr(str(release))
            + "); pathlib.Path("
            + repr(str(marker))
            + ").write_text('started'); deadline=time.monotonic()+15\nwhile not p.exists() and time.monotonic()<deadline: time.sleep(.02)\nraise SystemExit(0 if p.exists() else 1)"
        )
        command = [
            sys.executable,
            str(bg_script),
            "enqueue",
            "--cwd",
            str(worker),
            "--task-id",
            task["id"],
            "--session",
            session["id"],
            "--owner",
            "qualification",
            "--scope",
            snapshot.scope_key,
            "--codememory-config",
            str(backend.config),
            "--codememory-bin",
            backend.binary,
            "--lease-state-path",
            str(backend.root / "leases.json"),
            "--lease-ttl-seconds",
            "60",
            "--",
            sys.executable,
            "-c",
            code,
        ]
        result = backend.bounded(command, mutation=True)
        require("status: queued" in result.stdout, "background enqueue failed")
    run_command = [
        sys.executable,
        str(bg_script),
        "run",
        "--lease-max-concurrency",
        "2",
    ]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(backend.bounded, run_command, mutation=True)
        try:
            deadline = time.monotonic() + 10
            while not all((worker / "started").exists() for worker in workers[:2]):
                require(
                    time.monotonic() < deadline and not future.done(),
                    "two lease-backed processes did not start",
                )
                time.sleep(0.02)
            second = backend.bounded(run_command, mutation=True)
            require(
                "no queued jobs" in second.stdout,
                "concurrent runner admitted a third process",
            )
            persisted = json.loads((backend.root / "bg" / "jobs.json").read_text())[
                "jobs"
            ]
            require(
                sum(job["status"] == "running" for job in persisted) == 2,
                "active process frontier exceeded two",
            )
            require(
                sum(
                    job["status"] == "queued" and not job["attempts"]
                    for job in persisted
                )
                == 1,
                "third ready job was attempted",
            )
            require(
                not (workers[2] / "started").exists()
                and blocked["id"] not in selected_ids,
                "third or blocked task executed",
            )
        finally:
            release.write_text("settle")
            result = future.result(timeout=25)
    require(
        "completed: 2" in result.stdout and "failed: 0" in result.stdout,
        "lease-backed commands did not settle successfully",
    )
    return {
        "completed_processes": 2,
        "peak_processes": 2,
        "third_ready_deferred": True,
        "blocked_task_not_dispatched": True,
    }


def qualify(size: int, root: Path, binary: str, *, execute: bool = True) -> dict:
    proposals = fragments(size)
    oracle = coverage(proposals, assignments(size), size)
    (root / "contract.md").write_text(
        "Track every requirement exactly once; only the coordinator writes graph state.\n"
    )
    backend = NativeScope(root, binary)
    backend.budgets = latency_budgets(size)
    with backend.stage("intake"):
        mapping = intake(proposals, backend)
    with backend.stage("snapshot"):
        snapshot = verify_source(proposals, mapping, backend)
    with backend.stage("local"):
        model = local_checks(snapshot, root)
    execution = None
    if execute:
        with backend.stage("execution"):
            execution = execution_smoke(snapshot, backend)
    return {
        "size": size,
        "coverage": oracle,
        "fragment_count": len(proposals),
        "max_proposal_changes": max(
            len(p["records"]) + len(p["links"]) for p in proposals
        ),
        "recovery": {
            "prepared_reply_loss": True,
            "applied_replay_no_backend_calls": True,
            "conflicting_replay_rejected": True,
            "new_id_duplicate_rejected": True,
        },
        "rolling_model": model,
        "native_execution": execution,
        "stages": backend.stages,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes", nargs="+", type=int, choices=(9, *SIZES), default=list(SIZES)
    )
    args = parser.parse_args(argv)
    try:
        binary = shutil.which("oc")
        require(binary is not None, "native qualification requires installed oc")
        results = []
        with tempfile.TemporaryDirectory(prefix="rolling-qualification-") as temporary:
            root = Path(temporary).resolve()
            for size in args.sizes:
                scenario = root / str(size)
                scenario.mkdir(mode=0o700)
                results.append(qualify(size, scenario, str(Path(binary).resolve())))
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "backend": "native-sqlite",
                    "scenarios": results,
                    "temporary_root_removed": not root.exists(),
                },
                indent=2,
            )
        )
        return 0
    except (
        QualificationError,
        coordinator.CoordinatorError,
        projection.ProjectionError,
        BoundedCommandError,
        OSError,
        ValueError,
    ) as exc:
        print(json.dumps({"result": "FAIL", "detail": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
