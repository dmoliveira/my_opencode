#!/usr/bin/env python3

import argparse
import json
import os
import secrets
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import fcntl
except ImportError as exc:  # pragma: no cover
    raise SystemExit(f"error: unsupported platform for file locking: {exc}")


BG_ROOT = Path(
    os.environ.get("MY_OPENCODE_BG_DIR", "~/.config/opencode/my_opencode/bg")
).expanduser()
JOBS_PATH = BG_ROOT / "jobs.json"
LOCK_PATH = BG_ROOT / "jobs.lock"
RUNS_DIR = BG_ROOT / "runs"

DEFAULT_MAX_CONCURRENCY = 2
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_STALE_AFTER_SECONDS = 3600
DEFAULT_RETENTION_DAYS = 14
DEFAULT_MAX_TERMINAL = 200

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_store() -> None:
    BG_ROOT.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if not JOBS_PATH.exists():
        initial = {"version": 1, "updated_at": to_iso(now_utc()), "jobs": []}
        _atomic_write_json(JOBS_PATH, initial)


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        json.dump(payload, tmp, indent=2)
        tmp.write("\n")
        temp_name = tmp.name
    Path(temp_name).replace(path)


@contextmanager
def locked_jobs(writeback: bool = True):
    ensure_store()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        data = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
        data.setdefault("version", 1)
        data.setdefault("jobs", [])
        try:
            yield data
        finally:
            if writeback:
                data["updated_at"] = to_iso(now_utc())
                _atomic_write_json(JOBS_PATH, data)


def new_job_id() -> str:
    stamp = now_utc().strftime("%Y%m%d_%H%M%S")
    return f"bg_{stamp}_{secrets.token_hex(3)}"


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate_pid(pid: int, grace_seconds: float = 1.0) -> str:
    if not is_pid_alive(pid):
        return "already-stopped"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return "not-found"
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not is_pid_alive(pid):
            return "terminated"
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return "terminated"
    return "killed"


def find_job(data: dict, job_id: str) -> dict | None:
    for job in data.get("jobs", []):
        if job.get("id") == job_id:
            return job
    return None


def job_sort_key(job: dict) -> str:
    return str(job.get("created_at") or "")


def cleanup_jobs(
    data: dict,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_terminal: int = DEFAULT_MAX_TERMINAL,
) -> dict:
    now = now_utc()
    stale_cancelled = 0
    pruned = 0
    deleted_files = 0

    for job in data.get("jobs", []):
        if job.get("status") != "running":
            continue
        baseline = parse_iso(job.get("started_at")) or parse_iso(job.get("created_at"))
        if baseline is None:
            continue
        stale_after = int(job.get("stale_after_seconds") or DEFAULT_STALE_AFTER_SECONDS)
        if now <= baseline + timedelta(seconds=stale_after):
            continue
        pid = int(job.get("pid") or 0)
        action = terminate_pid(pid) if pid else "none"
        job["status"] = "cancelled"
        job["ended_at"] = to_iso(now)
        job["summary"] = f"stale-timeout exceeded ({stale_after}s, pid_action={action})"
        job["pid"] = None
        stale_cancelled += 1

    cutoff = now - timedelta(days=max(retention_days, 0))
    terminal_jobs: list[dict] = []
    keep: list[dict] = []
    for job in data.get("jobs", []):
        if job.get("status") in TERMINAL_STATUSES:
            terminal_jobs.append(job)
        else:
            keep.append(job)

    keep_terminal: list[dict] = []
    prune_terminal: list[dict] = []
    for job in terminal_jobs:
        ended = parse_iso(job.get("ended_at")) or parse_iso(job.get("created_at"))
        if ended is not None and ended < cutoff:
            prune_terminal.append(job)
        else:
            keep_terminal.append(job)

    if max_terminal >= 0 and len(keep_terminal) > max_terminal:
        ordered = sorted(keep_terminal, key=job_sort_key)
        extra = len(keep_terminal) - max_terminal
        prune_terminal.extend(ordered[:extra])
        keep_terminal = ordered[extra:]

    for job in prune_terminal:
        for key in ("log_path", "meta_path"):
            path_text = job.get(key)
            if not isinstance(path_text, str) or not path_text:
                continue
            path = Path(path_text)
            if path.exists():
                try:
                    path.unlink()
                    deleted_files += 1
                except OSError:
                    pass

    pruned = len(prune_terminal)
    data["jobs"] = keep + keep_terminal
    data["jobs"].sort(key=job_sort_key)
    return {
        "stale_cancelled": stale_cancelled,
        "pruned": pruned,
        "deleted_files": deleted_files,
        "remaining": len(data.get("jobs", [])),
    }


def command_enqueue(args: argparse.Namespace) -> int:
    job = enqueue_job(
        list(args.cmd or []),
        cwd_value=args.cwd,
        labels=list(args.label or []),
        timeout_seconds=int(args.timeout_seconds),
        stale_after_seconds=int(args.stale_after_seconds),
    )
    if job is None:
        return 2

    print(f"id: {job['id']}")
    print("status: queued")
    print(f"command: {job['command']}")
    print(f"cwd: {job['cwd']}")
    return 0


def enqueue_job(
    command_tokens: list[str],
    cwd_value: str,
    labels: list[str],
    timeout_seconds: int,
    stale_after_seconds: int,
) -> dict | None:
    tokens = list(command_tokens)
    if tokens and tokens[0] == "--":
        tokens = tokens[1:]
    if not tokens:
        print("error: enqueue requires a command; use: enqueue -- <command>")
        return None

    cwd = Path(cwd_value).expanduser().resolve()
    if not cwd.exists() or not cwd.is_dir():
        print(f"error: cwd does not exist: {cwd}")
        return None

    command = shlex.join(tokens)
    job_id = new_job_id()
    job = {
        "id": job_id,
        "command": command,
        "cwd": str(cwd),
        "created_at": to_iso(now_utc()),
        "started_at": None,
        "ended_at": None,
        "status": "queued",
        "exit_code": None,
        "timeout_seconds": timeout_seconds,
        "stale_after_seconds": stale_after_seconds,
        "labels": labels,
        "summary": None,
        "pid": None,
        "log_path": str(RUNS_DIR / f"{job_id}.log"),
        "meta_path": str(RUNS_DIR / f"{job_id}.meta.json"),
    }

    with locked_jobs(writeback=True) as data:
        cleanup_jobs(data)
        data.setdefault("jobs", []).append(job)
        data["jobs"].sort(key=job_sort_key)
    return job


def command_start(args: argparse.Namespace) -> int:
    job = enqueue_job(
        list(args.cmd or []),
        cwd_value=args.cwd,
        labels=list(args.label or []),
        timeout_seconds=int(args.timeout_seconds),
        stale_after_seconds=int(args.stale_after_seconds),
    )
    if job is None:
        return 2

    worker = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "run", "--id", str(job["id"])],
        cwd=str(Path(job["cwd"])),
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    print(f"id: {job['id']}")
    print("status: queued")
    print(f"worker_pid: {worker.pid}")
    print(f"next: /bg status {job['id']}")
    return 0


def _write_meta(job: dict, timed_out: bool, duration_seconds: float) -> None:
    meta = {
        "id": job.get("id"),
        "status": job.get("status"),
        "command": job.get("command"),
        "cwd": job.get("cwd"),
        "started_at": job.get("started_at"),
        "ended_at": job.get("ended_at"),
        "exit_code": job.get("exit_code"),
        "timed_out": timed_out,
        "duration_seconds": round(duration_seconds, 3),
        "timeout_seconds": job.get("timeout_seconds"),
    }
    meta_path = Path(str(job.get("meta_path")))
    _atomic_write_json(meta_path, meta)


def _run_single_job(job: dict) -> tuple[str, int | None]:
    started = now_utc()
    timed_out = False
    job["status"] = "running"
    job["started_at"] = to_iso(started)
    job["summary"] = None

    with locked_jobs(writeback=True) as data:
        current = find_job(data, str(job.get("id")))
        if current is None:
            return "missing", None
        current.update(job)

    log_path = Path(str(job.get("log_path")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            job["command"],
            shell=True,
            cwd=job["cwd"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            executable="/bin/bash",
            text=True,
        )
        with locked_jobs(writeback=True) as data:
            current = find_job(data, str(job.get("id")))
            if current is None:
                terminate_pid(process.pid)
                return "missing", None
            current["pid"] = process.pid

        exit_code: int | None
        try:
            process.wait(
                timeout=int(job.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
            )
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_pid(process.pid)
            process.wait(timeout=2)
            exit_code = None

    ended = now_utc()
    duration = (ended - started).total_seconds()
    if timed_out:
        status = "failed"
        summary = f"timed out after {job.get('timeout_seconds')}s"
    elif exit_code == 0:
        status = "completed"
        summary = "completed successfully"
    else:
        status = "failed"
        summary = f"exited with code {exit_code}"

    with locked_jobs(writeback=True) as data:
        current = find_job(data, str(job.get("id")))
        if current is None:
            return "missing", exit_code
        current["status"] = status
        current["exit_code"] = exit_code
        current["ended_at"] = to_iso(ended)
        current["summary"] = summary
        current["pid"] = None
        snapshot = dict(current)

    _write_meta(snapshot, timed_out=timed_out, duration_seconds=duration)
    return status, exit_code


def command_run(args: argparse.Namespace) -> int:
    with locked_jobs(writeback=True) as data:
        cleanup = cleanup_jobs(data)
        queued = [j for j in data.get("jobs", []) if j.get("status") == "queued"]
        if args.id:
            queued = [j for j in queued if j.get("id") == args.id]

    if not queued:
        print("no queued jobs")
        return 0

    max_jobs = len(queued)
    if args.max_jobs is not None:
        max_jobs = min(max_jobs, max(0, int(args.max_jobs)))
    jobs_to_run = sorted(queued, key=job_sort_key)[:max_jobs]

    completed = 0
    failed = 0
    for job in jobs_to_run:
        status, exit_code = _run_single_job(job)
        if status == "completed":
            completed += 1
        elif status in ("failed", "cancelled"):
            failed += 1
        line = f"- {job.get('id')}: {status}"
        if exit_code is not None:
            line += f" (exit_code={exit_code})"
        print(line)

    print(f"ran: {len(jobs_to_run)}")
    print(f"completed: {completed}")
    print(f"failed: {failed}")
    print(f"stale_cancelled: {cleanup.get('stale_cancelled', 0)}")
    return 0 if failed == 0 else 1


def command_list(args: argparse.Namespace) -> int:
    statuses = set(args.status or [])
    with locked_jobs(writeback=False) as data:
        jobs = list(data.get("jobs", []))

    jobs.sort(key=job_sort_key, reverse=True)
    if statuses:
        jobs = [job for job in jobs if job.get("status") in statuses]
    if args.limit is not None:
        jobs = jobs[: max(0, int(args.limit))]

    if args.json:
        print(json.dumps({"jobs": jobs, "count": len(jobs)}, indent=2))
        return 0

    if not jobs:
        print("no jobs")
        return 0

    for job in jobs:
        print(
            f"- {job.get('id')} [{job.get('status')}] command={job.get('command')} created_at={job.get('created_at')}"
        )
    print(f"count: {len(jobs)}")
    return 0


def tail_text(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-max(0, lines) :])


def command_read(args: argparse.Namespace) -> int:
    with locked_jobs(writeback=False) as data:
        job = find_job(data, args.id)
        if job is None:
            print(f"error: job not found: {args.id}")
            return 1
        snapshot = dict(job)

    log_path = Path(str(snapshot.get("log_path") or ""))
    meta_path = Path(str(snapshot.get("meta_path") or ""))
    log_tail = tail_text(log_path, args.tail)

    if args.json:
        payload = {
            "job": snapshot,
            "log_tail": log_tail,
            "meta_exists": meta_path.exists(),
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"id: {snapshot.get('id')}")
    print(f"status: {snapshot.get('status')}")
    print(f"command: {snapshot.get('command')}")
    print(f"cwd: {snapshot.get('cwd')}")
    print(f"created_at: {snapshot.get('created_at')}")
    print(f"started_at: {snapshot.get('started_at')}")
    print(f"ended_at: {snapshot.get('ended_at')}")
    print(f"exit_code: {snapshot.get('exit_code')}")
    print(f"summary: {snapshot.get('summary')}")
    print(f"log_path: {log_path}")
    print(f"meta_path: {meta_path}")
    if log_tail:
        print("log_tail:")
        print(log_tail)
    return 0


def command_cancel(args: argparse.Namespace) -> int:
    with locked_jobs(writeback=True) as data:
        cleanup_jobs(data)
        job = find_job(data, args.id)
        if job is None:
            print(f"error: job not found: {args.id}")
            return 1

        status = str(job.get("status"))
        if status in TERMINAL_STATUSES:
            print(f"id: {args.id}")
            print(f"status: {status}")
            print("note: already terminal")
            return 0

        action = "none"
        pid = int(job.get("pid") or 0)
        if status == "running" and pid:
            action = terminate_pid(pid)

        job["status"] = "cancelled"
        job["ended_at"] = to_iso(now_utc())
        job["summary"] = f"cancelled by user (pid_action={action})"
        job["pid"] = None

    print(f"id: {args.id}")
    print("status: cancelled")
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    with locked_jobs(writeback=True) as data:
        result = cleanup_jobs(
            data,
            retention_days=int(args.retention_days),
            max_terminal=int(args.max_terminal),
        )

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"stale_cancelled: {result['stale_cancelled']}")
    print(f"pruned: {result['pruned']}")
    print(f"deleted_files: {result['deleted_files']}")
    print(f"remaining: {result['remaining']}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    if args.id:
        return command_read(argparse.Namespace(id=args.id, tail=40, json=False))

    with locked_jobs(writeback=False) as data:
        jobs = list(data.get("jobs", []))

    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for job in jobs:
        status = str(job.get("status"))
        if status in counts:
            counts[status] += 1

    print(f"root: {BG_ROOT}")
    print(f"jobs_total: {len(jobs)}")
    print(f"queued: {counts['queued']}")
    print(f"running: {counts['running']}")
    print(f"completed: {counts['completed']}")
    print(f"failed: {counts['failed']}")
    print(f"cancelled: {counts['cancelled']}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    with locked_jobs(writeback=False) as data:
        jobs = list(data.get("jobs", []))

    now = now_utc()
    warnings: list[str] = []
    problems: list[str] = []
    statuses = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}

    for job in jobs:
        status = str(job.get("status"))
        if status not in statuses:
            problems.append(f"unknown job status for {job.get('id')}: {status}")
            continue
        statuses[status] += 1
        if status == "running":
            baseline = parse_iso(job.get("started_at")) or parse_iso(
                job.get("created_at")
            )
            stale_after = int(
                job.get("stale_after_seconds") or DEFAULT_STALE_AFTER_SECONDS
            )
            if baseline and now > baseline + timedelta(seconds=stale_after):
                warnings.append(
                    f"job {job.get('id')} exceeds stale threshold ({stale_after}s)"
                )

    report = {
        "result": "PASS" if not problems else "FAIL",
        "root": str(BG_ROOT),
        "jobs_path": str(JOBS_PATH),
        "jobs_total": len(jobs),
        "active_jobs": statuses["queued"] + statuses["running"],
        "terminal_jobs": statuses["completed"]
        + statuses["failed"]
        + statuses["cancelled"],
        "counts": statuses,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/bg cleanup",
            "/bg list --status running",
            "/bg status <job-id>",
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print(f"result: {report['result']}")
    print(f"jobs_total: {report['jobs_total']}")
    print(f"active_jobs: {report['active_jobs']}")
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if problems:
        print("problems:")
        for problem in problems:
            print(f"- {problem}")
    return 0 if report["result"] == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="/bg-manager",
        description="Minimal background task manager backend",
    )
    sub = parser.add_subparsers(dest="subcommand")

    enqueue = sub.add_parser("enqueue", help="enqueue command for background execution")
    enqueue.add_argument("--cwd", default=str(Path.cwd()))
    enqueue.add_argument("--label", action="append")
    enqueue.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    enqueue.add_argument(
        "--stale-after-seconds", type=int, default=DEFAULT_STALE_AFTER_SECONDS
    )
    enqueue.add_argument("cmd", nargs=argparse.REMAINDER)

    start = sub.add_parser("start", help="enqueue job and start worker immediately")
    start.add_argument("--cwd", default=str(Path.cwd()))
    start.add_argument("--label", action="append")
    start.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    start.add_argument(
        "--stale-after-seconds", type=int, default=DEFAULT_STALE_AFTER_SECONDS
    )
    start.add_argument("cmd", nargs=argparse.REMAINDER)

    run = sub.add_parser("run", help="run queued jobs")
    run.add_argument("--id")
    run.add_argument("--max-jobs", type=int)

    list_parser = sub.add_parser("list", help="list jobs")
    list_parser.add_argument(
        "--status",
        action="append",
        choices=["queued", "running", "completed", "failed", "cancelled"],
    )
    list_parser.add_argument("--limit", type=int)
    list_parser.add_argument("--json", action="store_true")

    read = sub.add_parser("read", help="show one job")
    read.add_argument("id")
    read.add_argument("--tail", type=int, default=40)
    read.add_argument("--json", action="store_true")

    cancel = sub.add_parser("cancel", help="cancel queued/running job")
    cancel.add_argument("id")

    cleanup = sub.add_parser("cleanup", help="cleanup stale/retained jobs")
    cleanup.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    cleanup.add_argument("--max-terminal", type=int, default=DEFAULT_MAX_TERMINAL)
    cleanup.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="show background task summary")
    status.add_argument("id", nargs="?")

    doctor = sub.add_parser("doctor", help="run background task diagnostics")
    doctor.add_argument("--json", action="store_true")

    sub.add_parser("help", help="show usage")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand in (None, "help"):
        parser.print_help()
        return 0 if args.subcommand == "help" else 2

    if args.subcommand == "enqueue":
        if args.timeout_seconds <= 0 or args.stale_after_seconds <= 0:
            print("error: timeout and stale-after must be greater than zero")
            return 1
        return command_enqueue(args)
    if args.subcommand == "start":
        if args.timeout_seconds <= 0 or args.stale_after_seconds <= 0:
            print("error: timeout and stale-after must be greater than zero")
            return 1
        return command_start(args)
    if args.subcommand == "run":
        return command_run(args)
    if args.subcommand == "list":
        return command_list(args)
    if args.subcommand == "status":
        return command_status(args)
    if args.subcommand == "read":
        return command_read(args)
    if args.subcommand == "cancel":
        return command_cancel(args)
    if args.subcommand == "cleanup":
        return command_cleanup(args)
    if args.subcommand == "doctor":
        return command_doctor(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
