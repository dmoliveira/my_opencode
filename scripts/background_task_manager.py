#!/usr/bin/env python3
# ruff: noqa: EXE001

import argparse
import hashlib
import json
import os
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config  # type: ignore
from task_lease_command import (  # type: ignore
    DEFAULT_OC_BIN,
    DEFAULT_OC_CONFIG,
    DEFAULT_SCOPE,
    LeaseIdentity,
    TaskLeaseError,
    check_lease,
    claim_lease,
    guarded_local_commit,
    heartbeat_lease,
    make_oc_runner,
    release_lease,
)
from task_lease_command import (  # type: ignore
    DEFAULT_STATE_PATH as DEFAULT_LEASE_STATE_PATH,
)

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
LEGACY_NOTIFY_PATH = Path(
    os.environ.get(
        "OPENCODE_NOTIFICATIONS_PATH", "~/.config/opencode/opencode-notifications.json"
    )
).expanduser()
BG_NOTIFY_ENV = "MY_OPENCODE_BG_NOTIFICATIONS_ENABLED"

DEFAULT_MAX_CONCURRENCY = 2
DEFAULT_LEASE_TTL_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_MAX_LOG_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_STALE_AFTER_SECONDS = 3600
DEFAULT_RETENTION_DAYS = 14
DEFAULT_MAX_TERMINAL = 200

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
LEASE_NONTERMINAL_STATUSES = {"queued", "running", "reconciling"}
LEASE_ACTIVE_ATTEMPT_STATUSES = {"acquiring", "starting", "running"}
LEASE_TERMINAL_ATTEMPT_STATUSES = {"succeeded", "failed", "cancelled", "unknown"}
LEASE_EXECUTION_ENABLED = True
RUNTIME_OWNER = {
    "model": "execution_backend",
    "execution_backend": "/bg",
    "observability_surface": "/agent-pool",
}


class BackgroundStoreError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


class AttemptSuperseded(RuntimeError):
    pass


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default


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


def default_notify_state() -> dict:
    return {
        "enabled": True,
        "sound": {"enabled": True},
        "visual": {"enabled": True},
        "events": {
            "complete": True,
            "error": True,
            "permission": True,
            "question": True,
        },
        "channels": {
            "complete": {"sound": True, "visual": True},
            "error": {"sound": True, "visual": True},
            "permission": {"sound": True, "visual": True},
            "question": {"sound": True, "visual": True},
        },
    }


def normalize_notify_state(raw: dict) -> dict:
    state = default_notify_state()
    if isinstance(raw.get("enabled"), bool):
        state["enabled"] = raw["enabled"]
    if isinstance(raw.get("sound"), dict) and isinstance(
        raw["sound"].get("enabled"), bool
    ):
        state["sound"]["enabled"] = raw["sound"]["enabled"]
    if isinstance(raw.get("visual"), dict) and isinstance(
        raw["visual"].get("enabled"), bool
    ):
        state["visual"]["enabled"] = raw["visual"]["enabled"]

    if isinstance(raw.get("events"), dict):
        for event in ("complete", "error", "permission", "question"):
            if isinstance(raw["events"].get(event), bool):
                state["events"][event] = raw["events"][event]

    if isinstance(raw.get("channels"), dict):
        for event in ("complete", "error", "permission", "question"):
            entry = raw["channels"].get(event)
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("sound"), bool):
                state["channels"][event]["sound"] = entry["sound"]
            if isinstance(entry.get("visual"), bool):
                state["channels"][event]["visual"] = entry["visual"]
    return state


def load_notify_state() -> dict:
    if "OPENCODE_NOTIFICATIONS_PATH" in os.environ and LEGACY_NOTIFY_PATH.exists():
        return normalize_notify_state(
            json.loads(LEGACY_NOTIFY_PATH.read_text(encoding="utf-8"))
        )

    try:
        layered, _ = load_layered_config()
        section = layered.get("notify")
        if isinstance(section, dict):
            return normalize_notify_state(section)
    except Exception:  # noqa: BLE001,S110 - optional notification fallback
        pass

    if LEGACY_NOTIFY_PATH.exists():
        return normalize_notify_state(
            json.loads(LEGACY_NOTIFY_PATH.read_text(encoding="utf-8"))
        )
    return default_notify_state()


def notify_event_for_status(status: str) -> str:
    if status == "completed":
        return "complete"
    return "error"


def emit_terminal_notification(job: dict) -> None:
    if not env_bool(BG_NOTIFY_ENV, True):
        return

    status = str(job.get("status") or "")
    if status not in TERMINAL_STATUSES:
        return

    state = load_notify_state()
    if not state.get("enabled", True):
        return

    event = notify_event_for_status(status)
    if not state.get("events", {}).get(event, True):
        return

    channels = state.get("channels", {}).get(event, {})
    sound_on = bool(state.get("sound", {}).get("enabled", True)) and bool(
        channels.get("sound", True)
    )
    visual_on = bool(state.get("visual", {}).get("enabled", True)) and bool(
        channels.get("visual", True)
    )

    if sound_on:
        sys.stderr.write("\a")
    if visual_on:
        sys.stderr.write(
            f"[bg notify][{event}] {job.get('id')}: {status} - {job.get('summary') or ''}\n"
        )
    if sound_on or visual_on:
        sys.stderr.flush()


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path: Path | None = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(path.parent), delete=False
        ) as tmp:
            temporary_path = Path(tmp.name)
            if hasattr(os, "fchmod"):
                os.fchmod(tmp.fileno(), 0o600)
            json.dump(payload, tmp, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        temporary_path.replace(path)
        replaced = True
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BackgroundStoreError:
        raise
    except OSError as exc:
        reason_code = (
            "bg_store_commit_indeterminate" if replaced else "bg_store_write_failed"
        )
        raise BackgroundStoreError(
            reason_code,
            f"could not durably publish {path.name}",
        ) from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


@contextmanager
def locked_jobs(writeback: bool = True):
    ensure_store()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        if hasattr(os, "fchmod"):
            os.fchmod(lock_file.fileno(), 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        data = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
        data.setdefault("version", 1)
        data.setdefault("jobs", [])
        completed = False
        try:
            yield data
            completed = True
        finally:
            if writeback and completed:
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


def is_process_group_alive(pgid: int) -> bool:
    if pgid <= 0 or not hasattr(os, "killpg"):
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except OSError:
        return False


def process_start_fingerprint(pid: int) -> str | None:
    if pid <= 0:
        return None
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.is_file():
        try:
            raw = proc_stat.read_text(encoding="utf-8")[:8192]
            fields = raw[raw.rfind(")") + 2 :].split()
            if len(fields) > 19:
                return _sha256_text(f"{pid}:proc:{fields[19]}")
        except OSError:
            return None
    try:
        completed = subprocess.run(
            ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    started = completed.stdout.strip()
    if completed.returncode != 0 or not started:
        return None
    return _sha256_text(f"{pid}:ps:{started}")


def process_identity_matches(pid: int, expected_fingerprint: str | None) -> bool:
    return bool(
        expected_fingerprint
        and is_pid_alive(pid)
        and secrets.compare_digest(
            process_start_fingerprint(pid) or "", expected_fingerprint
        )
    )


def process_group_identity_matches(
    pgid: int, expected_leader_fingerprint: str | None
) -> bool:
    if not is_process_group_alive(pgid):
        return False
    if not is_pid_alive(pgid):
        # A group with no leader still belongs to the original descendants.
        return True
    return process_identity_matches(pgid, expected_leader_fingerprint)


def terminate_process(
    pid: int,
    pgid: int | None = None,
    grace_seconds: float = 1.0,
    *,
    expected_start_fingerprint: str | None = None,
) -> str:
    target = int(pgid or pid)
    if pgid and hasattr(os, "killpg"):
        alive = lambda: is_process_group_alive(target)
        if not alive():
            return "already-stopped"
        if expected_start_fingerprint and not process_group_identity_matches(
            target, expected_start_fingerprint
        ):
            return "identity-mismatch"
    else:
        alive = lambda: is_pid_alive(pid)
        if not alive():
            return "already-stopped"
        if expected_start_fingerprint and not process_identity_matches(
            pid, expected_start_fingerprint
        ):
            return "identity-mismatch"
    try:
        if pgid and hasattr(os, "killpg"):
            os.killpg(target, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        return "not-found"
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not alive():
            return "terminated"
        time.sleep(0.05)
    try:
        if pgid and hasattr(os, "killpg"):
            os.killpg(target, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        return "terminated"
    kill_deadline = time.time() + max(0.1, grace_seconds)
    while time.time() < kill_deadline:
        if not alive():
            return "killed"
        time.sleep(0.05)
    return "kill-pending"


def terminate_pid(pid: int, grace_seconds: float = 1.0) -> str:
    return terminate_process(pid, grace_seconds=grace_seconds)


def find_job(data: dict, job_id: str) -> dict | None:
    for job in data.get("jobs", []):
        if job.get("id") == job_id:
            return job
    return None


def job_sort_key(job: dict) -> str:
    return str(job.get("created_at") or "")


def is_lease_job(job: dict) -> bool:
    return job.get("execution_mode") == "task_lease"


def current_attempt(job: dict) -> dict | None:
    attempt_id = str(job.get("current_attempt_id") or "")
    if not attempt_id:
        return None
    for attempt in job.get("attempts", []):
        if isinstance(attempt, dict) and attempt.get("id") == attempt_id:
            return attempt
    return None


def _attempt_matches(job: dict, attempt_id: str, statuses: set[str]) -> bool:
    attempt = current_attempt(job)
    return bool(
        is_lease_job(job)
        and job.get("status") == "running"
        and isinstance(attempt, dict)
        and attempt.get("id") == attempt_id
        and attempt.get("status") in statuses
    )


def _legacy_run_matches(job: dict, run_token: str) -> bool:
    return (
        not is_lease_job(job)
        and job.get("status") == "running"
        and secrets.compare_digest(str(job.get("run_token") or ""), run_token)
    )


def _legacy_gate_state(job: dict) -> str | None:
    marker, _ = _read_json_artifact(
        Path(str(job.get("gate_path") or "")), max_bytes=16 * 1024
    )
    if marker is None or marker.get("state") not in {
        "gate_aborted",
        "effect_possible",
    }:
        return None
    if (
        marker.get("job_id") != str(job.get("id"))
        or marker.get("attempt_id") != str(job.get("gate_attempt_id") or "")
    ):
        return None
    pid = job.get("pid")
    if pid is None:
        return "gate_aborted" if marker.get("state") == "gate_aborted" else None
    expected = {
        "pid": pid,
        "pgid": job.get("pgid"),
        "process_start_fingerprint": job.get("process_start_fingerprint"),
    }
    if any(marker.get(key) != value for key, value in expected.items()):
        return None
    return str(marker["state"])


def _publish_legacy_process(
    job_id: str,
    run_token: str,
    process: subprocess.Popen[Any],
    process_start: str | None,
) -> bool:
    with locked_jobs(writeback=True) as data:
        current = find_job(data, job_id)
        if current is None or not _legacy_run_matches(current, run_token):
            return False
        current["pid"] = process.pid
        current["pgid"] = process.pid
        current["process_start_fingerprint"] = process_start
        return True


def _settle_rejected_legacy_gate(job_id: str, run_token: str) -> str:
    snapshot = _snapshot_job(job_id)
    gate_aborted = bool(
        snapshot is not None
        and snapshot.get("run_token") == run_token
        and _legacy_gate_state(snapshot) == "gate_aborted"
    )
    with locked_jobs(writeback=True) as data:
        current = find_job(data, job_id)
        if current is None:
            return "missing"
        if (
            current.get("status") == "reconciling"
            and current.get("run_token") == run_token
            and gate_aborted
        ):
            current["status"] = "cancelled"
            current["ended_at"] = to_iso(now_utc())
            current["summary"] = "cancelled before the legacy command gate opened"
            current["pid"] = None
            current["pgid"] = None
            current["run_token"] = None
        return str(current.get("status") or "superseded")


def cleanup_jobs(
    data: dict,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_terminal: int = DEFAULT_MAX_TERMINAL,
) -> dict:
    now = now_utc()
    stale_cancelled = 0
    stale_reconciling = 0
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
        if is_lease_job(job):
            continue
        pid = int(job.get("pid") or 0)
        pgid = int(job.get("pgid") or 0)
        action = (
            terminate_process(
                pid,
                pgid or None,
                expected_start_fingerprint=str(
                    job.get("process_start_fingerprint") or ""
                )
                or None,
            )
            if pid
            else "none"
        )
        containment_failed = (
            not pid
            or action in {"identity-mismatch", "kill-pending"}
            or bool(pgid and is_process_group_alive(pgid))
        )
        job["status"] = "reconciling" if containment_failed else "cancelled"
        job["ended_at"] = None if containment_failed else to_iso(now)
        job["summary"] = (
            f"stale-timeout containment incomplete ({stale_after}s, pid_action={action})"
            if containment_failed
            else f"stale-timeout exceeded ({stale_after}s, pid_action={action})"
        )
        if not containment_failed:
            job["pid"] = None
            job["pgid"] = None
            job["run_token"] = None
        if containment_failed:
            stale_reconciling += 1
        else:
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
        artifact_paths = {
            str(job.get(key) or "")
            for key in ("log_path", "meta_path", "gate_path")
        }
        for attempt in job.get("attempts", []):
            if not isinstance(attempt, dict):
                continue
            artifact_paths.update(
                str(attempt.get(key) or "")
                for key in ("log_path", "receipt_path", "gate_path")
            )
        for path_text in artifact_paths:
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
        "stale_reconciling": stale_reconciling,
        "pruned": pruned,
        "deleted_files": deleted_files,
        "remaining": len(data.get("jobs", [])),
    }


def _lease_options_from_args(
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None | bool, dict[str, Any] | None]:
    task_id = str(getattr(args, "task_id", None) or "").strip()
    if not task_id:
        return None, None

    session_id = str(getattr(args, "session", None) or "").strip()
    owner = str(getattr(args, "owner", None) or "").strip()
    scope = str(getattr(args, "scope", None) or "").strip()
    config_value = str(getattr(args, "codememory_config", None) or "").strip()
    missing = [
        flag
        for flag, value in (
            ("--session", session_id),
            ("--owner", owner),
            ("--scope", scope),
            ("--codememory-config", config_value),
        )
        if not value
    ]
    if missing:
        print(f"error: lease-backed jobs require {', '.join(missing)}")
        return False, None

    config_path = Path(config_value).expanduser().resolve()
    if not config_path.is_file():
        print(f"error: Codememory config does not exist: {config_path}")
        return False, None
    worktree = Path(
        str(getattr(args, "lease_worktree", None) or args.cwd)
    ).expanduser().resolve()
    if not worktree.is_dir():
        print(f"error: lease worktree does not exist: {worktree}")
        return False, None
    ttl_seconds = int(getattr(args, "lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS))
    max_attempts = int(getattr(args, "max_attempts", DEFAULT_MAX_ATTEMPTS))
    max_log_bytes = int(getattr(args, "max_log_bytes", DEFAULT_MAX_LOG_BYTES))
    if ttl_seconds < 1 or ttl_seconds > 24 * 60 * 60:
        print("error: --lease-ttl-seconds must be between 1 and 86400")
        return False, None
    if max_attempts < 1 or max_attempts > 10:
        print("error: --max-attempts must be between 1 and 10")
        return False, None
    retry_safe = bool(getattr(args, "retry_safe", False))
    if max_attempts > 1 and not retry_safe:
        print("error: --max-attempts greater than 1 requires --retry-safe")
        return False, None
    if max_log_bytes < 1:
        print("error: --max-log-bytes must be greater than zero")
        return False, None

    state_path = Path(str(args.lease_state_path)).expanduser().resolve()
    return (
        {
            "task_id": task_id,
            "session_id": session_id,
            "owner": owner,
            "scope": scope,
            "codememory_config": str(config_path),
            "worktree_path": str(worktree),
            "oc_bin": str(args.codememory_bin),
            "state_path": str(state_path),
            "ttl_seconds": ttl_seconds,
        },
        {"max_attempts": max_attempts, "retry_safe": retry_safe},
    )


def command_enqueue(args: argparse.Namespace) -> int:
    lease_request, retry_policy = _lease_options_from_args(args)
    if lease_request is False:
        return 2
    job = enqueue_job(
        list(args.cmd or []),
        cwd_value=args.cwd,
        labels=list(args.label or []),
        timeout_seconds=int(args.timeout_seconds),
        stale_after_seconds=int(args.stale_after_seconds),
        lease_request=lease_request,
        retry_policy=retry_policy,
        max_log_bytes=int(args.max_log_bytes),
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
    *,
    lease_request: dict[str, Any] | None = None,
    retry_policy: dict[str, Any] | None = None,
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES,
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
    evidence: dict[str, str] = {}
    for label in labels:
        text = str(label).strip()
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if (
            key
            in {
                "parent_session_id",
                "parent_run_id",
                "task_graph_path",
                "plan_path",
                "parent_command",
            }
            and value
        ):
            evidence[key] = value
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
        "evidence": evidence,
        "summary": None,
        "pid": None,
        "log_path": str(RUNS_DIR / f"{job_id}.log"),
        "meta_path": str(RUNS_DIR / f"{job_id}.meta.json"),
    }
    if lease_request is not None:
        job.update(
            {
                "execution_mode": "task_lease",
                "lease_request": lease_request,
                "retry_policy": retry_policy
                or {"max_attempts": DEFAULT_MAX_ATTEMPTS, "retry_safe": False},
                "max_log_bytes": max_log_bytes,
                "attempts": [],
                "current_attempt_id": None,
                "reconcile_reason": None,
            }
        )

    with locked_jobs(writeback=True) as data:
        cleanup_jobs(data)
        data.setdefault("jobs", []).append(job)
        data["jobs"].sort(key=job_sort_key)
    return job


def command_start(args: argparse.Namespace) -> int:
    lease_request, retry_policy = _lease_options_from_args(args)
    if lease_request is False:
        return 2
    job = enqueue_job(
        list(args.cmd or []),
        cwd_value=args.cwd,
        labels=list(args.label or []),
        timeout_seconds=int(args.timeout_seconds),
        stale_after_seconds=int(args.stale_after_seconds),
        lease_request=lease_request,
        retry_policy=retry_policy,
        max_log_bytes=int(args.max_log_bytes),
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
        "evidence": job.get("evidence", {}),
    }
    meta_path = Path(str(job.get("meta_path")))
    _atomic_write_json(meta_path, meta)


def _new_attempt(job: dict, worker_start_fingerprint: str | None) -> dict[str, Any]:
    attempt_number = len(job.get("attempts", [])) + 1
    attempt_id = f"attempt_{attempt_number}_{secrets.token_hex(4)}"
    job_id = str(job.get("id"))
    return {
        "id": attempt_id,
        "number": attempt_number,
        "worker_id": f"bg:{job_id}:{attempt_id}",
        "worker_pid": os.getpid(),
        "worker_start_fingerprint": worker_start_fingerprint,
        "heartbeat_at": None,
        "status": "acquiring",
        "created_at": to_iso(now_utc()),
        "started_at": None,
        "ended_at": None,
        "pid": None,
        "pgid": None,
        "process_start_fingerprint": None,
        "lease": None,
        "exit_code": None,
        "failure_class": None,
        "outcome_confidence": None,
        "receipt_path": str(RUNS_DIR / f"{job_id}.{attempt_id}.receipt.json"),
        "gate_path": str(RUNS_DIR / f"{job_id}.{attempt_id}.gate.json"),
        "log_path": str(RUNS_DIR / f"{job_id}.{attempt_id}.log"),
        "log_truncated": False,
    }


def _reserve_jobs(
    *, job_id: str | None, max_jobs: int | None, lease_max_concurrency: int
) -> tuple[list[dict], list[dict], dict]:
    worker_start_fingerprint = process_start_fingerprint(os.getpid())
    with locked_jobs(writeback=True) as data:
        cleanup = cleanup_jobs(data)
        queued = [
            job
            for job in data.get("jobs", [])
            if job.get("status") == "queued"
        ]
        if job_id:
            queued = [job for job in queued if job.get("id") == job_id]
        limit = len(queued) if max_jobs is None else max(0, int(max_jobs))
        active_lease_jobs = sum(
            1
            for job in data.get("jobs", [])
            if is_lease_job(job) and job.get("status") == "running"
        )
        lease_slots = max(0, lease_max_concurrency - active_lease_jobs)
        legacy_reserved: list[dict] = []
        lease_reserved: list[dict] = []
        for job in sorted(queued, key=job_sort_key):
            if len(legacy_reserved) + len(lease_reserved) >= limit:
                break
            if is_lease_job(job):
                if not LEASE_EXECUTION_ENABLED or lease_slots <= 0:
                    continue
                attempt = _new_attempt(job, worker_start_fingerprint)
                job.setdefault("attempts", []).append(attempt)
                job["current_attempt_id"] = attempt["id"]
                job["status"] = "running"
                job["started_at"] = job.get("started_at") or attempt["created_at"]
                job["ended_at"] = None
                job["exit_code"] = None
                job["summary"] = f"attempt {attempt['number']} acquiring task lease"
                job["reconcile_reason"] = None
                job["log_path"] = attempt["log_path"]
                lease_reserved.append(dict(job))
                lease_slots -= 1
                continue

            run_token = secrets.token_hex(16)
            job["status"] = "running"
            job["started_at"] = to_iso(now_utc())
            job["summary"] = None
            job["run_token"] = run_token
            job["worker_pid"] = os.getpid()
            job["worker_start_fingerprint"] = worker_start_fingerprint
            job["gate_attempt_id"] = f"legacy_{run_token}"
            job["gate_path"] = str(
                RUNS_DIR / f"{job.get('id')}.legacy_{run_token}.gate.json"
            )
            legacy_reserved.append(dict(job))
    return legacy_reserved, lease_reserved, cleanup


def _identity_from_mapping(value: dict[str, Any]) -> LeaseIdentity:
    return LeaseIdentity(
        task_id=str(value["task_id"]),
        session_id=str(value["session_id"]),
        owner=str(value["owner"]),
        worker_id=str(value["worker_id"]),
        lease_id=str(value["lease_id"]),
        fencing_token=int(value["fencing_token"]),
    )


def _lease_state_path(job: dict) -> Path:
    request = job.get("lease_request")
    if not isinstance(request, dict):
        raise TypeError("lease-backed job is missing lease_request")
    return Path(str(request["state_path"])).expanduser().resolve()


def _best_effort_release(identity: LeaseIdentity, state_path: Path) -> str:
    try:
        release_lease(identity, state_path=state_path)
    except TaskLeaseError as exc:
        return exc.reason_code
    return "task_lease_released"


def _finish_prestart_attempt(
    job_id: str,
    attempt_id: str,
    *,
    failure_class: str,
    summary: str,
    identity: LeaseIdentity | None = None,
    state_path: Path | None = None,
) -> str:
    result = "superseded"

    def commit() -> None:
        nonlocal result
        with locked_jobs(writeback=True) as data:
            job = find_job(data, job_id)
            if job is None or not _attempt_matches(
                job, attempt_id, LEASE_ACTIVE_ATTEMPT_STATUSES
            ):
                if job is not None:
                    result = str(job.get("status") or "superseded")
                return
            attempt = current_attempt(job)
            assert attempt is not None
            ended_at = to_iso(now_utc())
            attempt["status"] = "failed"
            attempt["ended_at"] = ended_at
            attempt["failure_class"] = failure_class
            attempt["outcome_confidence"] = "known_no_effect"
            attempt["pid"] = None
            attempt["pgid"] = None
            policy = job.get("retry_policy")
            if not isinstance(policy, dict):
                policy = {}
            max_attempts = int(policy.get("max_attempts") or DEFAULT_MAX_ATTEMPTS)
            may_retry = len(job.get("attempts", [])) < max_attempts
            job["current_attempt_id"] = None
            job["pid"] = None
            job["pgid"] = None
            if may_retry:
                job["status"] = "queued"
                job["summary"] = f"{summary}; retry queued"
                result = "queued"
            else:
                job["status"] = "failed"
                job["ended_at"] = ended_at
                job["summary"] = summary
                result = "failed"

    if identity is not None:
        if state_path is None:
            raise ValueError("state_path is required for a fenced attempt commit")
        try:
            guarded_local_commit(identity, commit, state_path=state_path)
        except TaskLeaseError as exc:
            return _mark_attempt_reconciling(
                job_id,
                attempt_id,
                reason="pre-start transition lost exact lease fencing",
                failure_class=exc.reason_code,
            )
    else:
        commit()
    return result


def _mark_attempt_reconciling(
    job_id: str,
    attempt_id: str,
    *,
    reason: str,
    failure_class: str,
) -> str:
    with locked_jobs(writeback=True) as data:
        job = find_job(data, job_id)
        if job is None:
            return "missing"
        attempt = current_attempt(job)
        if (
            not isinstance(attempt, dict)
            or attempt.get("id") != attempt_id
            or attempt.get("status") in LEASE_TERMINAL_ATTEMPT_STATUSES
        ):
            return str(job.get("status") or "superseded")
        attempt["status"] = "unknown"
        attempt["ended_at"] = to_iso(now_utc())
        attempt["failure_class"] = failure_class
        attempt["outcome_confidence"] = "unknown"
        job["status"] = "reconciling"
        job["reconcile_reason"] = reason
        job["summary"] = reason
        job["pid"] = attempt.get("pid")
        job["pgid"] = attempt.get("pgid")
        return "reconciling"


def _persist_claimed_lease(
    job_id: str,
    attempt_id: str,
    identity: LeaseIdentity,
    lease_payload: dict[str, Any],
    *,
    state_path: Path,
) -> None:
    def commit() -> None:
        with locked_jobs(writeback=True) as data:
            job = find_job(data, job_id)
            if job is None or not _attempt_matches(job, attempt_id, {"acquiring"}):
                raise AttemptSuperseded("attempt changed while its lease was claimed")
            attempt = current_attempt(job)
            assert attempt is not None
            attempt["lease"] = dict(lease_payload)
            attempt["status"] = "starting"
            attempt["lease_claimed_at"] = to_iso(now_utc())
            attempt["heartbeat_at"] = str(
                lease_payload.get("heartbeat_at") or attempt["lease_claimed_at"]
            )
            job["summary"] = f"attempt {attempt.get('number')} holds task lease"

    guarded_local_commit(identity, commit, state_path=state_path)


def _claim_reserved_attempt(job: dict) -> tuple[LeaseIdentity | None, str]:
    attempt = current_attempt(job)
    request = job.get("lease_request")
    if not isinstance(attempt, dict) or not isinstance(request, dict):
        return None, "invalid"
    job_id = str(job.get("id"))
    attempt_id = str(attempt.get("id"))
    state_path = _lease_state_path(job)
    config_path = Path(str(request["codememory_config"]))
    worktree = Path(str(request["worktree_path"]))
    runner = make_oc_runner(
        oc_bin=str(request.get("oc_bin") or DEFAULT_OC_BIN),
        config_path=config_path,
        cwd=worktree,
    )
    try:
        report = claim_lease(
            task_id=str(request["task_id"]),
            session_id=str(request["session_id"]),
            owner=str(request["owner"]),
            worker_id=str(attempt["worker_id"]),
            scope=str(request["scope"]),
            ttl_seconds=int(request["ttl_seconds"]),
            runner=runner,
            config_path=config_path,
            cwd=worktree,
            state_path=state_path,
        )
    except TaskLeaseError as exc:
        if exc.reason_code == "task_lease_commit_indeterminate":
            status = _mark_attempt_reconciling(
                job_id,
                attempt_id,
                reason="lease claim outcome is indeterminate; execution was not started",
                failure_class=exc.reason_code,
            )
            return None, status
        status = _finish_prestart_attempt(
            job_id,
            attempt_id,
            failure_class=exc.reason_code,
            summary=f"task lease claim failed: {exc.reason_code}",
        )
        return None, status

    lease_payload = report.get("lease")
    if not isinstance(lease_payload, dict):
        status = _mark_attempt_reconciling(
            job_id,
            attempt_id,
            reason="lease claim returned no usable identity",
            failure_class="task_lease_response_invalid",
        )
        return None, status
    identity = _identity_from_mapping(lease_payload)
    try:
        _persist_claimed_lease(
            job_id,
            attempt_id,
            identity,
            lease_payload,
            state_path=state_path,
        )
    except AttemptSuperseded:
        _best_effort_release(identity, state_path)
        return None, "cancelled"
    except BackgroundStoreError:
        _best_effort_release(identity, state_path)
        return None, "reconciling"
    except TaskLeaseError as exc:
        _best_effort_release(identity, state_path)
        status = _mark_attempt_reconciling(
            job_id,
            attempt_id,
            failure_class=exc.reason_code,
            reason=f"claimed lease could not fence local admission: {exc.reason_code}",
        )
        return None, status
    return identity, "starting"


def _snapshot_job(job_id: str) -> dict | None:
    with locked_jobs(writeback=False) as data:
        job = find_job(data, job_id)
        return dict(job) if job is not None else None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _read_json_artifact(
    path: Path, *, max_bytes: int = MAX_RECEIPT_BYTES
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = path.read_bytes()
        if len(raw) > max_bytes:
            return None, None
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return payload, _sha256_bytes(raw)


def _gate_state(job_id: str, attempt: dict) -> str | None:
    marker, _ = _read_json_artifact(
        Path(str(attempt.get("gate_path") or "")), max_bytes=16 * 1024
    )
    if marker is None:
        return None
    state = marker.get("state")
    if state not in {"gate_aborted", "effect_possible"}:
        return None
    expected = {
        "job_id": job_id,
        "attempt_id": str(attempt.get("id")),
        "pid": attempt.get("pid"),
        "pgid": attempt.get("pgid"),
        "process_start_fingerprint": attempt.get("process_start_fingerprint"),
    }
    if any(marker.get(key) != value for key, value in expected.items()):
        return None
    return str(state)


def _write_gate_marker(
    path: Path,
    state: str,
    *,
    job_id: str,
    attempt_id: str,
    pid: int,
    process_start_fingerprint: str | None,
) -> None:
    _atomic_write_json(
        path,
        {
            "version": 1,
            "state": state,
            "job_id": job_id,
            "attempt_id": attempt_id,
            "pid": pid,
            "pgid": pid,
            "process_start_fingerprint": process_start_fingerprint,
            "recorded_at": to_iso(now_utc()),
        },
    )


def _run_lease_gate(
    read_fd: int,
    marker_path: Path,
    job_id: str,
    attempt_id: str,
    command: str,
) -> int:
    process_fingerprint = process_start_fingerprint(os.getpid())
    try:
        grant = os.read(read_fd, 1)
    finally:
        os.close(read_fd)
    if grant != b"1":
        _write_gate_marker(
            marker_path,
            "gate_aborted",
            job_id=job_id,
            attempt_id=attempt_id,
            pid=os.getpid(),
            process_start_fingerprint=process_fingerprint,
        )
        return 125
    _write_gate_marker(
        marker_path,
        "effect_possible",
        job_id=job_id,
        attempt_id=attempt_id,
        pid=os.getpid(),
        process_start_fingerprint=process_fingerprint,
    )
    os.execv("/bin/bash", ["/bin/bash", "-c", command])
    return 126


def _prepared_receipt(job: dict, attempt: dict, identity: LeaseIdentity) -> dict[str, Any]:
    return {
        "version": 1,
        "job_id": str(job.get("id")),
        "attempt_id": str(attempt.get("id")),
        "attempt_number": int(attempt.get("number") or 0),
        "status": "prepared",
        "attempt_status": None,
        "outcome_confidence": None,
        "command_sha256": _sha256_text(str(job.get("command") or "")),
        "cwd_sha256": _sha256_text(str(job.get("cwd") or "")),
        "lease": {
            "task_id": identity.task_id,
            "session_id": identity.session_id,
            "owner": identity.owner,
            "worker_id": identity.worker_id,
            "lease_id": identity.lease_id,
            "fencing_token": identity.fencing_token,
        },
        "prepared_at": to_iso(now_utc()),
        "started_at": None,
        "ended_at": None,
        "pid": None,
        "pgid": None,
        "exit_code": None,
        "timed_out": False,
        "cancelled": False,
        "lease_lost": False,
        "gate_state": None,
        "receipt_path": str(attempt.get("receipt_path") or ""),
        "log_path": str(attempt.get("log_path") or ""),
        "log_sha256": None,
        "log_bytes": 0,
        "log_truncated": False,
    }


def _validate_terminal_receipt(
    job: dict,
    attempt: dict,
    identity: LeaseIdentity,
    receipt: dict[str, Any],
) -> None:
    if receipt.get("version") != 1 or receipt.get("status") != "terminal":
        raise ValueError("receipt is not a supported terminal record")
    expected_scalars = {
        "job_id": str(job.get("id")),
        "attempt_id": str(attempt.get("id")),
        "attempt_number": int(attempt.get("number") or 0),
        "command_sha256": _sha256_text(str(job.get("command") or "")),
        "cwd_sha256": _sha256_text(str(job.get("cwd") or "")),
        "receipt_path": str(attempt.get("receipt_path") or ""),
        "log_path": str(attempt.get("log_path") or ""),
        "pid": attempt.get("pid"),
        "pgid": attempt.get("pgid"),
        "process_start_fingerprint": attempt.get("process_start_fingerprint"),
    }
    for key, expected in expected_scalars.items():
        if receipt.get(key) != expected:
            raise ValueError(f"receipt {key} does not match the current attempt")
    lease_payload = receipt.get("lease")
    if not isinstance(lease_payload, dict):
        raise TypeError("receipt is missing its lease identity")
    try:
        receipt_identity = _identity_from_mapping(lease_payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("receipt lease identity is invalid") from exc
    if receipt_identity != identity:
        raise ValueError("receipt lease identity is stale")
    gate_state = _gate_state(str(job.get("id")), attempt)
    if receipt.get("gate_state") != gate_state or gate_state not in {
        "gate_aborted",
        "effect_possible",
    }:
        raise ValueError("receipt gate evidence is missing or mismatched")
    if parse_iso(str(receipt.get("ended_at") or "")) is None:
        raise ValueError("receipt ended_at is invalid")
    log_sha256 = str(receipt.get("log_sha256") or "")
    if len(log_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in log_sha256
    ):
        raise ValueError("receipt log digest is invalid")
    log_path = Path(str(attempt.get("log_path") or ""))
    max_log_bytes = int(job.get("max_log_bytes") or DEFAULT_MAX_LOG_BYTES)
    try:
        descriptor = os.open(
            log_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ValueError("receipt log is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_log_bytes:
            raise ValueError("receipt log is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = max_log_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        log_bytes = b"".join(chunks)
    finally:
        os.close(descriptor)
    receipt_log_bytes = receipt.get("log_bytes")
    if (
        not isinstance(receipt_log_bytes, int)
        or isinstance(receipt_log_bytes, bool)
        or receipt_log_bytes != len(log_bytes)
        or not secrets.compare_digest(_sha256_bytes(log_bytes), log_sha256)
    ):
        raise ValueError("receipt log digest or byte count does not match evidence")
    if bool(receipt.get("log_truncated")) and len(log_bytes) != max_log_bytes:
        raise ValueError("truncated receipt log does not reach its configured bound")

    attempt_status = str(receipt.get("attempt_status") or "")
    confidence = str(receipt.get("outcome_confidence") or "")
    exit_code = receipt.get("exit_code")
    if attempt_status == "succeeded":
        valid = (
            gate_state == "effect_possible"
            and exit_code == 0
            and confidence == "known_process_outcome"
            and not receipt.get("timed_out")
            and not receipt.get("cancelled")
            and not receipt.get("lease_lost")
        )
    elif attempt_status == "failed":
        valid = (
            gate_state == "effect_possible"
            and confidence == "known_process_outcome"
            and not receipt.get("cancelled")
            and not receipt.get("lease_lost")
            and (
                bool(receipt.get("timed_out"))
                or (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0)
            )
        )
    elif attempt_status == "cancelled":
        valid = bool(receipt.get("cancelled")) and confidence in {
            "known_no_effect",
            "effect_possible",
        }
    elif attempt_status == "unknown":
        valid = (
            gate_state == "effect_possible"
            and confidence == "unknown"
            and bool(receipt.get("lease_lost"))
        )
    else:
        valid = False
    if not valid:
        raise ValueError("receipt terminal semantics are inconsistent")


def _write_terminal_receipt(
    receipt: dict[str, Any],
    *,
    attempt_status: str,
    outcome_confidence: str,
    process: subprocess.Popen[bytes] | None,
    exit_code: int | None,
    timed_out: bool,
    cancelled: bool,
    lease_lost: bool,
    gate_state: str | None,
    log_result: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    terminal = dict(receipt)
    terminal.update(
        {
            "status": "terminal",
            "attempt_status": attempt_status,
            "outcome_confidence": outcome_confidence,
            "ended_at": to_iso(now_utc()),
            "pid": process.pid if process is not None else None,
            "pgid": process.pid if process is not None else None,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "lease_lost": lease_lost,
            "gate_state": gate_state,
            "log_sha256": log_result.get("sha256"),
            "log_bytes": int(log_result.get("bytes") or 0),
            "log_truncated": bool(log_result.get("truncated", False)),
        }
    )
    receipt_path = Path(str(receipt["log_path"])).with_suffix(".receipt.json")
    expected_path = Path(str(receipt.get("receipt_path") or ""))
    if expected_path.name:
        receipt_path = expected_path
    _atomic_write_json(receipt_path, terminal)
    return terminal, _sha256_bytes(receipt_path.read_bytes())


def _drain_bounded_output(
    stream: Any,
    log_path: Path,
    max_bytes: int,
    result: dict[str, Any],
) -> None:
    digest = hashlib.sha256()
    written = 0
    truncated = False
    try:
        log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with log_path.open("wb") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                remaining = max(0, max_bytes - written)
                retained = chunk[:remaining]
                if retained:
                    handle.write(retained)
                    digest.update(retained)
                    written += len(retained)
                if len(retained) != len(chunk):
                    truncated = True
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        result["error"] = str(exc)
    finally:
        stream.close()
    result.update(
        {"bytes": written, "sha256": digest.hexdigest(), "truncated": truncated}
    )


def _lease_attempt_is_active(job_id: str, attempt_id: str) -> bool:
    with locked_jobs(writeback=False) as data:
        job = find_job(data, job_id)
        return bool(
            job is not None and _attempt_matches(job, attempt_id, {"running"})
        )


def _record_attempt_heartbeat(
    job_id: str,
    attempt_id: str,
    identity: LeaseIdentity,
    lease_payload: dict[str, Any],
    *,
    state_path: Path,
) -> None:
    def commit() -> None:
        with locked_jobs(writeback=True) as data:
            job = find_job(data, job_id)
            if job is None or not _attempt_matches(job, attempt_id, {"running"}):
                raise AttemptSuperseded("attempt changed during heartbeat")
            attempt = current_attempt(job)
            assert attempt is not None
            attempt["heartbeat_at"] = str(
                lease_payload.get("heartbeat_at") or to_iso(now_utc())
            )

    guarded_local_commit(identity, commit, state_path=state_path)


def _persist_running_attempt(
    job_id: str,
    attempt_id: str,
    identity: LeaseIdentity,
    process: subprocess.Popen[bytes],
    process_start: str,
    *,
    state_path: Path,
) -> None:
    def commit() -> None:
        with locked_jobs(writeback=True) as data:
            job = find_job(data, job_id)
            if job is None or not _attempt_matches(job, attempt_id, {"starting"}):
                raise AttemptSuperseded("attempt changed before process admission")
            attempt = current_attempt(job)
            assert attempt is not None
            started_at = to_iso(now_utc())
            attempt["status"] = "running"
            attempt["started_at"] = started_at
            attempt["pid"] = process.pid
            attempt["pgid"] = process.pid
            attempt["process_start_fingerprint"] = process_start
            job["pid"] = process.pid
            job["pgid"] = process.pid
            job["summary"] = f"attempt {attempt.get('number')} running"

    guarded_local_commit(identity, commit, state_path=state_path)


def _project_terminal_receipt(
    job_id: str,
    attempt_id: str,
    identity: LeaseIdentity,
    receipt: dict[str, Any],
    receipt_sha256: str,
    *,
    state_path: Path,
) -> tuple[str, dict | None]:
    validation_job = _snapshot_job(job_id)
    validation_attempt = (
        current_attempt(validation_job) if validation_job is not None else None
    )
    if (
        validation_job is None
        or not isinstance(validation_attempt, dict)
        or validation_attempt.get("id") != attempt_id
    ):
        raise AttemptSuperseded("attempt changed before receipt validation")
    _validate_terminal_receipt(validation_job, validation_attempt, identity, receipt)

    result = "superseded"
    snapshot: dict | None = None

    def commit() -> None:
        nonlocal result, snapshot
        with locked_jobs(writeback=True) as data:
            job = find_job(data, job_id)
            if job is None:
                result = "missing"
                return
            if not _attempt_matches(job, attempt_id, {"running"}):
                result = str(job.get("status") or "superseded")
                snapshot = dict(job)
                return
            attempt = current_attempt(job)
            assert attempt is not None
            attempt_status = str(receipt.get("attempt_status") or "unknown")
            if attempt_status not in LEASE_TERMINAL_ATTEMPT_STATUSES:
                raise ValueError("terminal receipt has an invalid attempt status")
            ended_at = str(receipt.get("ended_at") or to_iso(now_utc()))
            attempt.update(
                {
                    "status": attempt_status,
                    "ended_at": ended_at,
                    "exit_code": receipt.get("exit_code"),
                    "failure_class": (
                        "lease_lost"
                        if receipt.get("lease_lost")
                        else "timeout"
                        if receipt.get("timed_out")
                        else "process_exit"
                    ),
                    "outcome_confidence": receipt.get("outcome_confidence"),
                    "receipt_sha256": receipt_sha256,
                    "gate_state": receipt.get("gate_state"),
                    "log_truncated": bool(receipt.get("log_truncated", False)),
                    "pid": None,
                    "pgid": None,
                }
            )
            job["pid"] = None
            job["pgid"] = None
            job["exit_code"] = receipt.get("exit_code")
            if attempt_status == "succeeded":
                job["status"] = "completed"
                job["current_attempt_id"] = None
                job["ended_at"] = ended_at
                job["summary"] = "completed successfully"
                result = "completed"
            elif attempt_status == "failed":
                policy = job.get("retry_policy")
                if not isinstance(policy, dict):
                    policy = {}
                may_retry = bool(policy.get("retry_safe", False)) and len(
                    job.get("attempts", [])
                ) < int(policy.get("max_attempts") or DEFAULT_MAX_ATTEMPTS)
                job["current_attempt_id"] = None
                if may_retry:
                    job["status"] = "queued"
                    job["ended_at"] = None
                    job["summary"] = "attempt failed; retry queued"
                    result = "queued"
                else:
                    job["status"] = "failed"
                    job["ended_at"] = ended_at
                    if receipt.get("timed_out"):
                        job["summary"] = f"timed out after {job.get('timeout_seconds')}s"
                    else:
                        job["summary"] = f"exited with code {receipt.get('exit_code')}"
                    result = "failed"
            elif attempt_status == "cancelled":
                job["status"] = "cancelled"
                job["current_attempt_id"] = None
                job["ended_at"] = ended_at
                job["summary"] = "cancelled by user"
                result = "cancelled"
            else:
                job["status"] = "reconciling"
                job["reconcile_reason"] = "command outcome is unknown"
                job["summary"] = "command outcome is unknown; reconciliation required"
                result = "reconciling"
            snapshot = dict(job)

    guarded_local_commit(identity, commit, state_path=state_path)
    return result, snapshot


def _run_lease_job(job: dict) -> tuple[str, int | None]:
    identity, status = _claim_reserved_attempt(job)
    if identity is None:
        return status, None
    job_id = str(job.get("id"))
    snapshot = _snapshot_job(job_id)
    if snapshot is None:
        _best_effort_release(identity, _lease_state_path(job))
        return "missing", None
    attempt = current_attempt(snapshot)
    if not isinstance(attempt, dict):
        _best_effort_release(identity, _lease_state_path(job))
        return "invalid", None
    attempt_id = str(attempt.get("id"))
    state_path = _lease_state_path(snapshot)
    receipt = _prepared_receipt(snapshot, attempt, identity)
    receipt["receipt_path"] = str(attempt["receipt_path"])
    try:
        _atomic_write_json(Path(str(attempt["receipt_path"])), receipt)
    except BackgroundStoreError as exc:
        result = _finish_prestart_attempt(
            job_id,
            attempt_id,
            failure_class=exc.reason_code,
            summary="could not durably prepare attempt receipt",
            identity=identity,
            state_path=state_path,
        )
        _best_effort_release(identity, state_path)
        return result, None

    read_fd, write_fd = os.pipe()
    process: subprocess.Popen[bytes] | None = None
    drain_thread: threading.Thread | None = None
    log_result: dict[str, Any] = {}
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "__lease_gate__",
                str(read_fd),
                str(attempt["gate_path"]),
                job_id,
                attempt_id,
                str(snapshot["command"]),
            ],
            cwd=str(snapshot["cwd"]),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            pass_fds=(read_fd,),
            start_new_session=True,
        )
    except OSError as exc:
        os.close(read_fd)
        os.close(write_fd)
        result = _finish_prestart_attempt(
            job_id,
            attempt_id,
            failure_class="process_spawn_failed",
            summary=f"command gate could not start: {exc}",
            identity=identity,
            state_path=state_path,
        )
        _best_effort_release(identity, state_path)
        return result, None
    os.close(read_fd)
    assert process.stdout is not None
    drain_thread = threading.Thread(
        target=_drain_bounded_output,
        args=(
            process.stdout,
            Path(str(attempt["log_path"])),
            int(snapshot.get("max_log_bytes") or DEFAULT_MAX_LOG_BYTES),
            log_result,
        ),
        name=f"bg-log-{attempt_id}",
        daemon=True,
    )
    drain_thread.start()

    process_start = process_start_fingerprint(process.pid)
    if process_start is None:
        os.close(write_fd)
        terminate_process(process.pid, process.pid)
        process.wait(timeout=5)
        drain_thread.join(timeout=5)
        result = _finish_prestart_attempt(
            job_id,
            attempt_id,
            failure_class="process_identity_unavailable",
            summary="command process identity could not be established",
            identity=identity,
            state_path=state_path,
        )
        _best_effort_release(identity, state_path)
        return result, None
    receipt["process_start_fingerprint"] = process_start

    try:
        _persist_running_attempt(
            job_id,
            attempt_id,
            identity,
            process,
            process_start,
            state_path=state_path,
        )
        check_lease(identity, state_path=state_path)
    except (AttemptSuperseded, TaskLeaseError, BackgroundStoreError) as exc:
        os.close(write_fd)
        process.wait(timeout=5)
        drain_thread.join(timeout=5)
        failure_class = getattr(exc, "reason_code", "attempt_superseded")
        result = _finish_prestart_attempt(
            job_id,
            attempt_id,
            failure_class=str(failure_class),
            summary="command admission was fenced before gate release",
            identity=identity,
            state_path=state_path,
        )
        _best_effort_release(identity, state_path)
        return result, None

    os.write(write_fd, b"1")
    os.close(write_fd)
    receipt["started_at"] = to_iso(now_utc())
    receipt["pid"] = process.pid
    receipt["pgid"] = process.pid
    request = snapshot["lease_request"]
    ttl_seconds = int(request["ttl_seconds"])
    heartbeat_interval = max(0.25, ttl_seconds / 3)
    next_heartbeat = time.monotonic() + heartbeat_interval
    deadline = time.monotonic() + int(
        snapshot.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS
    )
    timed_out = False
    cancelled = False
    lease_lost = False
    while process.poll() is None:
        if not _lease_attempt_is_active(job_id, attempt_id):
            cancelled = True
            terminate_process(
                process.pid,
                process.pid,
                expected_start_fingerprint=process_start,
            )
            break
        now = time.monotonic()
        if now >= deadline:
            timed_out = True
            terminate_process(
                process.pid,
                process.pid,
                expected_start_fingerprint=process_start,
            )
            break
        if now >= next_heartbeat:
            try:
                heartbeat = heartbeat_lease(
                    identity,
                    ttl_seconds=ttl_seconds,
                    state_path=state_path,
                )
                lease_payload = heartbeat.get("lease")
                if not isinstance(lease_payload, dict):
                    raise TaskLeaseError(
                        "task_lease_response_invalid",
                        "heartbeat returned no lease identity",
                    )
                _record_attempt_heartbeat(
                    job_id,
                    attempt_id,
                    identity,
                    lease_payload,
                    state_path=state_path,
                )
            except (AttemptSuperseded, TaskLeaseError, BackgroundStoreError):
                lease_lost = True
                terminate_process(
                    process.pid,
                    process.pid,
                    expected_start_fingerprint=process_start,
                )
                break
            next_heartbeat = now + heartbeat_interval
        time.sleep(0.05)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        terminate_process(
            process.pid,
            process.pid,
            grace_seconds=0.1,
            expected_start_fingerprint=process_start,
        )
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    containment_action = terminate_process(
        process.pid,
        process.pid,
        grace_seconds=0.2,
        expected_start_fingerprint=process_start,
    )
    drain_thread.join(timeout=5)
    exit_code = process.returncode
    latest = _snapshot_job(job_id)
    latest_attempt = current_attempt(latest) if latest is not None else None
    evidence_attempt = latest_attempt if isinstance(latest_attempt, dict) else attempt
    observed_gate_state = _gate_state(job_id, evidence_attempt)
    if (
        process.returncode is None
        or is_process_group_alive(process.pid)
        or drain_thread.is_alive()
        or log_result.get("error")
        or containment_action in {"identity-mismatch", "kill-pending"}
    ):
        result = _mark_attempt_reconciling(
            job_id,
            attempt_id,
            reason="process group or bounded log drain did not settle",
            failure_class="execution_containment_incomplete",
        )
        _best_effort_release(identity, state_path)
        return result, exit_code
    if observed_gate_state != "effect_possible":
        result = _mark_attempt_reconciling(
            job_id,
            attempt_id,
            reason="durable command gate evidence is missing or invalid",
            failure_class="gate_evidence_invalid",
        )
        _best_effort_release(identity, state_path)
        return result, exit_code
    if cancelled:
        attempt_status = "cancelled"
        outcome_confidence = (
            "effect_possible"
            if observed_gate_state == "effect_possible"
            else "known_no_effect"
        )
    elif lease_lost:
        attempt_status = "unknown"
        outcome_confidence = "unknown"
    elif timed_out or exit_code != 0:
        attempt_status = "failed"
        outcome_confidence = "known_process_outcome"
    else:
        attempt_status = "succeeded"
        outcome_confidence = "known_process_outcome"
    try:
        terminal_receipt, receipt_sha256 = _write_terminal_receipt(
            receipt,
            attempt_status=attempt_status,
            outcome_confidence=outcome_confidence,
            process=process,
            exit_code=exit_code,
            timed_out=timed_out,
            cancelled=cancelled,
            lease_lost=lease_lost,
            gate_state=observed_gate_state,
            log_result=log_result,
        )
    except BackgroundStoreError as exc:
        result = _mark_attempt_reconciling(
            job_id,
            attempt_id,
            reason="terminal receipt durability is indeterminate",
            failure_class=exc.reason_code,
        )
        _best_effort_release(identity, state_path)
        return result, exit_code

    if lease_lost:
        result = _mark_attempt_reconciling(
            job_id,
            attempt_id,
            reason="task lease was lost after command effects became possible",
            failure_class="task_lease_lost",
        )
        return result, exit_code
    try:
        result, terminal_snapshot = _project_terminal_receipt(
            job_id,
            attempt_id,
            identity,
            terminal_receipt,
            receipt_sha256,
            state_path=state_path,
        )
    except (
        AttemptSuperseded,
        TaskLeaseError,
        BackgroundStoreError,
        TypeError,
        ValueError,
    ):
        current = _snapshot_job(job_id)
        if current is not None and current.get("status") in TERMINAL_STATUSES:
            result = str(current["status"])
            terminal_snapshot = current
        else:
            result = _mark_attempt_reconciling(
                job_id,
                attempt_id,
                reason="terminal receipt could not be committed under the exact lease",
                failure_class="terminal_commit_fenced",
            )
            terminal_snapshot = None
    _best_effort_release(identity, state_path)
    if terminal_snapshot is not None and result in TERMINAL_STATUSES:
        _write_meta(
            terminal_snapshot,
            timed_out=timed_out,
            duration_seconds=max(
                0.0,
                (
                    now_utc()
                    - (parse_iso(attempt.get("created_at")) or now_utc())
                ).total_seconds(),
            ),
        )
        emit_terminal_notification(terminal_snapshot)
    return result, exit_code


def _run_single_job(job: dict) -> tuple[str, int | None]:
    started = parse_iso(job.get("started_at")) or now_utc()
    timed_out = False
    run_token = str(job.get("run_token") or "")
    if not run_token:
        return "unreserved", None

    log_path = Path(str(job.get("log_path")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    read_fd, write_fd = os.pipe()
    with log_path.open("a", encoding="utf-8") as log_file:
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "__lease_gate__",
                    str(read_fd),
                    str(job["gate_path"]),
                    str(job["id"]),
                    str(job["gate_attempt_id"]),
                    str(job["command"]),
                ],
                cwd=job["cwd"],
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                pass_fds=(read_fd,),
                start_new_session=True,
            )
        except OSError:
            os.close(read_fd)
            os.close(write_fd)
            with locked_jobs(writeback=True) as data:
                current = find_job(data, str(job.get("id")))
                if current is not None and _legacy_run_matches(current, run_token):
                    current["status"] = "failed"
                    current["ended_at"] = to_iso(now_utc())
                    current["summary"] = "legacy command gate could not start"
                    current["run_token"] = None
            return "failed", None
        os.close(read_fd)
        process_start = process_start_fingerprint(process.pid)
        accepted = _publish_legacy_process(
            str(job.get("id")), run_token, process, process_start
        )
        if not accepted:
            os.close(write_fd)
            process.wait(timeout=5)
            status = _settle_rejected_legacy_gate(str(job.get("id")), run_token)
            return status, None

        if process_start is None:
            os.close(write_fd)
        else:
            os.write(write_fd, b"1")
            os.close(write_fd)

        exit_code: int | None
        if process_start is None:
            terminate_process(process.pid, process.pid)
            process.wait(timeout=2)
            exit_code = process.returncode
        else:
            try:
                process.wait(
                    timeout=int(job.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
                )
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_process(
                    process.pid,
                    process.pid,
                    expected_start_fingerprint=process_start,
                )
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                exit_code = None
        containment_action = terminate_process(
            process.pid,
            process.pid,
            grace_seconds=0.2,
            expected_start_fingerprint=process_start,
        )
        containment_failed = (
            containment_action in {"identity-mismatch", "kill-pending"}
            or is_process_group_alive(process.pid)
        )
        gate_state = _legacy_gate_state(
            _snapshot_job(str(job.get("id"))) or job
        )

    ended = now_utc()
    duration = (ended - started).total_seconds()
    if containment_failed or (process_start is not None and gate_state != "effect_possible"):
        status = "reconciling"
        summary = (
            "process group did not settle after command exit"
            if containment_failed
            else "legacy command gate evidence is missing or invalid"
        )
    elif process_start is None:
        status = "failed"
        summary = "command process identity could not be established"
    elif timed_out:
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
        if not _legacy_run_matches(current, run_token):
            return str(current.get("status") or "cancelled"), exit_code
        current["status"] = status
        current["exit_code"] = exit_code
        current["ended_at"] = to_iso(ended)
        current["summary"] = summary
        if containment_failed:
            current["pid"] = process.pid
            current["pgid"] = process.pid
        else:
            current["pid"] = None
            current["pgid"] = None
        current["worker_pid"] = None
        current["run_token"] = None
        snapshot = dict(current)

    _write_meta(snapshot, timed_out=timed_out, duration_seconds=duration)
    emit_terminal_notification(snapshot)
    return status, exit_code


def _attempt_identity(attempt: dict) -> LeaseIdentity | None:
    lease = attempt.get("lease")
    if not isinstance(lease, dict):
        return None
    try:
        return _identity_from_mapping(lease)
    except (KeyError, TypeError, ValueError):
        return None


def _worker_attempt_is_live(
    job: dict,
    attempt: dict,
    identity: LeaseIdentity | None,
    state_path: Path,
) -> bool:
    worker_pid = int(attempt.get("worker_pid") or 0)
    if not process_identity_matches(
        worker_pid, str(attempt.get("worker_start_fingerprint") or "")
    ):
        return False
    request = job.get("lease_request")
    ttl_seconds = (
        int(request.get("ttl_seconds") or DEFAULT_LEASE_TTL_SECONDS)
        if isinstance(request, dict)
        else DEFAULT_LEASE_TTL_SECONDS
    )
    attempt_status = str(attempt.get("status") or "")
    if attempt_status == "acquiring":
        created_at = parse_iso(str(attempt.get("created_at") or ""))
        return bool(
            created_at
            and now_utc() <= created_at + timedelta(seconds=max(15, ttl_seconds))
        )
    heartbeat_at = parse_iso(
        str(attempt.get("heartbeat_at") or attempt.get("lease_claimed_at") or "")
    )
    if (
        identity is None
        or heartbeat_at is None
        or now_utc() > heartbeat_at + timedelta(seconds=ttl_seconds)
    ):
        return False
    try:
        check_lease(identity, state_path=state_path)
    except TaskLeaseError:
        return False
    return True


def _contain_attempt_process(attempt: dict) -> bool:
    pid = int(attempt.get("pid") or 0)
    pgid = int(attempt.get("pgid") or 0)
    if not pid or not pgid:
        return False
    action = terminate_process(
        pid,
        pgid,
        expected_start_fingerprint=str(
            attempt.get("process_start_fingerprint") or ""
        ),
    )
    return action not in {"identity-mismatch", "kill-pending"} and not (
        is_process_group_alive(pgid)
    )


def reconcile_lease_jobs() -> dict[str, int]:
    with locked_jobs(writeback=False) as data:
        snapshots = [
            dict(job)
            for job in data.get("jobs", [])
            if is_lease_job(job) and job.get("status") == "running"
        ]

    report = {
        "inspected": len(snapshots),
        "active": 0,
        "requeued": 0,
        "failed": 0,
        "reconciling": 0,
    }
    for job in snapshots:
        attempt = current_attempt(job)
        if not isinstance(attempt, dict):
            _mark_attempt_reconciling(
                str(job.get("id")),
                str(job.get("current_attempt_id") or "missing"),
                reason="running lease job has no current attempt",
                failure_class="attempt_state_invalid",
            )
            report["reconciling"] += 1
            continue
        job_id = str(job.get("id"))
        attempt_id = str(attempt.get("id"))
        attempt_status = str(attempt.get("status") or "")
        state_path = _lease_state_path(job)
        identity = _attempt_identity(attempt)
        if _worker_attempt_is_live(job, attempt, identity, state_path):
            report["active"] += 1
            continue
        if attempt_status == "acquiring":
            identity, status = _claim_reserved_attempt(job)
            if identity is not None:
                status = _finish_prestart_attempt(
                    job_id,
                    attempt_id,
                    failure_class="worker_lost_before_start",
                    summary="reserved worker exited before command start",
                    identity=identity,
                    state_path=state_path,
                )
                _best_effort_release(identity, state_path)
        elif attempt_status == "starting" and identity is not None:
            status = _finish_prestart_attempt(
                job_id,
                attempt_id,
                failure_class="worker_lost_before_start",
                summary="lease worker exited before command start",
                identity=identity,
                state_path=state_path,
            )
            _best_effort_release(identity, state_path)
        elif attempt_status == "running" and identity is not None:
            contained = _contain_attempt_process(attempt)
            receipt_path = Path(str(attempt.get("receipt_path") or ""))
            receipt, receipt_sha256 = _read_json_artifact(receipt_path)
            if (
                contained
                and isinstance(receipt, dict)
                and isinstance(receipt_sha256, str)
                and receipt.get("status") == "terminal"
                and receipt.get("job_id") == job_id
                and receipt.get("attempt_id") == attempt_id
            ):
                try:
                    status, _ = _project_terminal_receipt(
                        job_id,
                        attempt_id,
                        identity,
                        receipt,
                        receipt_sha256,
                        state_path=state_path,
                    )
                    _best_effort_release(identity, state_path)
                except (
                    AttemptSuperseded,
                    TaskLeaseError,
                    BackgroundStoreError,
                    TypeError,
                    ValueError,
                ):
                    status = _mark_attempt_reconciling(
                        job_id,
                        attempt_id,
                        reason="terminal receipt could not be adopted under the exact lease",
                        failure_class="receipt_adoption_fenced",
                    )
            elif _gate_state(job_id, attempt) == "gate_aborted":
                status = _finish_prestart_attempt(
                    job_id,
                    attempt_id,
                    failure_class="worker_lost_before_gate",
                    summary="worker exited before command gate opened",
                    identity=identity,
                    state_path=state_path,
                )
                _best_effort_release(identity, state_path)
            else:
                status = _mark_attempt_reconciling(
                    job_id,
                    attempt_id,
                    reason=(
                        "lease worker exited after command effects became possible"
                        if contained
                        else "lease worker exited and its process group could not be contained"
                    ),
                    failure_class=(
                        "worker_lost_after_start"
                        if contained
                        else "execution_containment_incomplete"
                    ),
                )
        else:
            status = _mark_attempt_reconciling(
                job_id,
                attempt_id,
                reason="lease worker exited after command effects became possible",
                failure_class="worker_lost_after_start",
            )
        if status == "queued":
            report["requeued"] += 1
        elif status == "failed":
            report["failed"] += 1
        elif status == "reconciling":
            report["reconciling"] += 1
    return report


def command_reconcile(args: argparse.Namespace) -> int:
    report = reconcile_lease_jobs()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for key in ("inspected", "active", "requeued", "failed", "reconciling"):
        print(f"{key}: {report[key]}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    if args.lease_max_concurrency < 1:
        print("error: --lease-max-concurrency must be greater than zero")
        return 2
    reconciliation = reconcile_lease_jobs()
    jobs_to_run, lease_jobs, cleanup = _reserve_jobs(
        job_id=args.id,
        max_jobs=args.max_jobs,
        lease_max_concurrency=args.lease_max_concurrency,
    )
    if not jobs_to_run and not lease_jobs:
        print("no queued jobs")
        return 0

    completed = 0
    failed = 0
    total_ran = 0
    lease_futures: dict[Any, dict] = {}
    executor: ThreadPoolExecutor | None = None
    if lease_jobs:
        executor = ThreadPoolExecutor(
            max_workers=len(lease_jobs), thread_name_prefix="bg-lease"
        )
        lease_futures = {
            executor.submit(_run_lease_job, job): job for job in lease_jobs
        }
    for job in jobs_to_run:
        status, exit_code = _run_single_job(job)
        total_ran += 1
        if status == "completed":
            completed += 1
        elif status != "completed":
            failed += 1
        line = f"- {job.get('id')}: {status}"
        if exit_code is not None:
            line += f" (exit_code={exit_code})"
        print(line)
    for future in as_completed(lease_futures):
        job = lease_futures[future]
        try:
            status, exit_code = future.result()
        except Exception as exc:  # noqa: BLE001 - fence unexpected worker failures
            status, exit_code = "reconciling", None
            current = _snapshot_job(str(job.get("id"))) or job
            attempt = current_attempt(current)
            if isinstance(attempt, dict):
                pid = int(attempt.get("pid") or 0)
                pgid = int(attempt.get("pgid") or 0)
                if pid:
                    terminate_process(pid, pgid or None)
                identity = _attempt_identity(attempt)
                _mark_attempt_reconciling(
                    str(job.get("id")),
                    str(attempt.get("id")),
                    reason=f"lease worker raised before a safe outcome: {type(exc).__name__}",
                    failure_class="worker_exception",
                )
                if identity is not None:
                    _best_effort_release(identity, _lease_state_path(current))
        total_ran += 1
        if status == "completed":
            completed += 1
        else:
            failed += 1
        line = f"- {job.get('id')}: {status}"
        if exit_code is not None:
            line += f" (exit_code={exit_code})"
        print(line)
    if executor is not None:
        executor.shutdown(wait=True)

    print(f"ran: {total_ran}")
    print(f"completed: {completed}")
    print(f"failed: {failed}")
    print(f"stale_cancelled: {cleanup.get('stale_cancelled', 0)}")
    if reconciliation.get("inspected", 0):
        print(f"reconciled: {reconciliation['inspected']}")
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
            "evidence": snapshot.get("evidence", {}),
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
    pid = 0
    pgid = 0
    process_start: str | None = None
    lease_identity: LeaseIdentity | None = None
    lease_state_path: Path | None = None
    attempt_id: str | None = None
    immediate = False
    pidless_uncertain = False
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

        pid = int(job.get("pid") or 0)
        pgid = int(job.get("pgid") or 0)
        process_start = str(job.get("process_start_fingerprint") or "") or None
        requested_at = to_iso(now_utc())
        job["cancel_requested_at"] = requested_at
        job["summary"] = "cancellation requested (pid_action=pending)"
        if pid:
            job["run_token"] = None
        if is_lease_job(job):
            attempt = current_attempt(job)
            if isinstance(attempt, dict):
                attempt_id = str(attempt.get("id"))
                lease_identity = _attempt_identity(attempt)
                lease_state_path = _lease_state_path(job)
                process_start = str(
                    attempt.get("process_start_fingerprint") or ""
                ) or None
                if pid and attempt.get("status") in LEASE_ACTIVE_ATTEMPT_STATUSES:
                    attempt["status"] = "cancelling"
                    attempt["failure_class"] = "user_cancel_requested"
                elif attempt.get("status") not in LEASE_TERMINAL_ATTEMPT_STATUSES:
                    attempt["status"] = "cancelled"
                    attempt["ended_at"] = requested_at
                    attempt["failure_class"] = "user_cancelled"
                    attempt["outcome_confidence"] = "known_no_effect"
        if not pid and (status == "queued" or is_lease_job(job)):
            immediate = True
            job["status"] = "cancelled"
            job["ended_at"] = requested_at
            job["summary"] = "cancelled by user (pid_action=none)"
            job["pid"] = None
            job["pgid"] = None
            job["current_attempt_id"] = None
        elif not pid:
            pidless_uncertain = True
            job["status"] = "reconciling"
            job["ended_at"] = None
            job["summary"] = (
                "legacy worker may have spawned before publishing process identity"
            )

    if immediate:
        if lease_identity is not None and lease_state_path is not None:
            _best_effort_release(lease_identity, lease_state_path)
        print(f"id: {args.id}")
        print("status: cancelled")
        return 0
    if pidless_uncertain:
        print(f"id: {args.id}")
        print("status: reconciling")
        return 1

    action = terminate_process(
        pid,
        pgid or None,
        expected_start_fingerprint=process_start,
    )
    containment_failed = action in {"identity-mismatch", "kill-pending"} or bool(
        pgid and is_process_group_alive(pgid)
    )
    final_status = "reconciling" if containment_failed else "cancelled"
    with locked_jobs(writeback=True) as data:
        job = find_job(data, args.id)
        if job is not None and job.get("status") not in TERMINAL_STATUSES:
            attempt = current_attempt(job)
            if (
                is_lease_job(job)
                and isinstance(attempt, dict)
                and attempt.get("id") == attempt_id
                and attempt.get("status") not in LEASE_TERMINAL_ATTEMPT_STATUSES
            ):
                attempt["status"] = "unknown" if containment_failed else "cancelled"
                attempt["ended_at"] = to_iso(now_utc())
                attempt["failure_class"] = (
                    "cancel_containment_incomplete"
                    if containment_failed
                    else "user_cancelled"
                )
                attempt["outcome_confidence"] = (
                    "unknown" if containment_failed else "effect_possible"
                )
            job["status"] = final_status
            job["ended_at"] = None if containment_failed else to_iso(now_utc())
            job["summary"] = (
                f"cancellation containment incomplete (pid_action={action})"
                if containment_failed
                else f"cancelled by user (pid_action={action})"
            )
            if not containment_failed:
                job["pid"] = None
                job["pgid"] = None
                job["current_attempt_id"] = None

    if (
        not containment_failed
        and lease_identity is not None
        and lease_state_path is not None
    ):
        _best_effort_release(lease_identity, lease_state_path)

    print(f"id: {args.id}")
    print(f"status: {final_status}")
    return 0 if final_status == "cancelled" else 1


def command_cleanup(args: argparse.Namespace) -> int:
    reconciliation = reconcile_lease_jobs()
    with locked_jobs(writeback=True) as data:
        result = cleanup_jobs(
            data,
            retention_days=int(args.retention_days),
            max_terminal=int(args.max_terminal),
        )
    result["reconciliation"] = reconciliation

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"stale_cancelled: {result['stale_cancelled']}")
    if result["stale_reconciling"]:
        print(f"stale_reconciling: {result['stale_reconciling']}")
    print(f"pruned: {result['pruned']}")
    print(f"deleted_files: {result['deleted_files']}")
    print(f"remaining: {result['remaining']}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    if args.id:
        return command_read(argparse.Namespace(id=args.id, tail=40, json=args.json))

    with locked_jobs(writeback=False) as data:
        jobs = list(data.get("jobs", []))

    counts = {
        "queued": 0,
        "running": 0,
        "reconciling": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    lease_counts = {"queued": 0, "active": 0, "reconciling": 0}
    stale_running = 0
    for job in jobs:
        status = str(job.get("status"))
        if status in counts:
            counts[status] += 1
        if is_lease_job(job):
            if status == "queued":
                lease_counts["queued"] += 1
            elif status == "running":
                lease_counts["active"] += 1
            elif status == "reconciling":
                lease_counts["reconciling"] += 1
        if status == "running":
            if is_lease_job(job):
                continue
            baseline = parse_iso(job.get("started_at")) or parse_iso(
                job.get("created_at")
            )
            stale_after = int(
                job.get("stale_after_seconds") or DEFAULT_STALE_AFTER_SECONDS
            )
            if baseline and now_utc() > baseline + timedelta(seconds=stale_after):
                stale_running += 1

    if args.json:
        print(
            json.dumps(
                {
                    "root": str(BG_ROOT),
                    "jobs_total": len(jobs),
                    "counts": counts,
                    "queue_depth": counts["queued"],
                    "stale_running": stale_running,
                    "lease_pool": {
                        **lease_counts,
                        "default_max_concurrency": DEFAULT_MAX_CONCURRENCY,
                    },
                    "limitations": [
                        "single_host_cooperative_leases",
                        "external_effects_require_native_cas_or_idempotency",
                        "unknown_post_start_outcomes_require_reconciliation",
                    ],
                    "evidence_links": {
                        "parent_session_ids": sorted(
                            {
                                str(
                                    job.get("evidence", {}).get("parent_session_id")
                                    or ""
                                )
                                for job in jobs
                                if isinstance(job, dict)
                                and isinstance(job.get("evidence"), dict)
                                and str(
                                    job.get("evidence", {}).get("parent_session_id")
                                    or ""
                                )
                            }
                        ),
                        "task_graph_paths": sorted(
                            {
                                str(
                                    job.get("evidence", {}).get("task_graph_path") or ""
                                )
                                for job in jobs
                                if isinstance(job, dict)
                                and isinstance(job.get("evidence"), dict)
                                and str(
                                    job.get("evidence", {}).get("task_graph_path") or ""
                                )
                            }
                        ),
                    },
                    "execution_backend": "/bg",
                    "observability_surface": "/agent-pool",
                    "runtime_owner": RUNTIME_OWNER,
                },
                indent=2,
            )
        )
        return 0

    print(f"root: {BG_ROOT}")
    print(f"jobs_total: {len(jobs)}")
    print(f"queued: {counts['queued']}")
    print(f"running: {counts['running']}")
    if counts["reconciling"]:
        print(f"reconciling: {counts['reconciling']}")
    print(f"queue_depth: {counts['queued']}")
    print(f"stale_running: {stale_running}")
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
    statuses = {
        "queued": 0,
        "running": 0,
        "reconciling": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    lease_counts = {"queued": 0, "active": 0, "reconciling": 0}
    stale_running = 0

    for job in jobs:
        status = str(job.get("status"))
        if status not in statuses:
            problems.append(f"unknown job status for {job.get('id')}: {status}")
            continue
        statuses[status] += 1
        if is_lease_job(job):
            if status == "queued":
                lease_counts["queued"] += 1
            elif status == "running":
                lease_counts["active"] += 1
            elif status == "reconciling":
                lease_counts["reconciling"] += 1
                warnings.append(
                    f"job {job.get('id')} has an unknown outcome requiring reconciliation"
                )
        if status == "running":
            if is_lease_job(job):
                continue
            baseline = parse_iso(job.get("started_at")) or parse_iso(
                job.get("created_at")
            )
            stale_after = int(
                job.get("stale_after_seconds") or DEFAULT_STALE_AFTER_SECONDS
            )
            if baseline and now > baseline + timedelta(seconds=stale_after):
                stale_running += 1
                warnings.append(
                    f"job {job.get('id')} exceeds stale threshold ({stale_after}s)"
                )

    notify_state = load_notify_state()
    if not notify_state.get("enabled", True):
        warnings.append(
            "notify stack is globally disabled; bg completion notifications are muted"
        )

    latest_terminal = [
        {
            "id": job.get("id"),
            "status": job.get("status"),
            "ended_at": job.get("ended_at"),
            "summary": job.get("summary"),
        }
        for job in sorted(jobs, key=job_sort_key, reverse=True)
        if str(job.get("status")) in TERMINAL_STATUSES
    ][:5]

    report = {
        "result": "PASS" if not problems else "FAIL",
        "root": str(BG_ROOT),
        "jobs_path": str(JOBS_PATH),
        "jobs_total": len(jobs),
        "active_jobs": statuses["queued"]
        + statuses["running"]
        + statuses["reconciling"],
        "terminal_jobs": statuses["completed"]
        + statuses["failed"]
        + statuses["cancelled"],
        "counts": statuses,
        "queue_depth": statuses["queued"],
        "stale_running": stale_running,
        "failed_jobs": statuses["failed"],
        "lease_pool": {
            **lease_counts,
            "default_max_concurrency": DEFAULT_MAX_CONCURRENCY,
        },
        "limitations": [
            "single_host_cooperative_leases",
            "external_effects_require_native_cas_or_idempotency",
            "unknown_post_start_outcomes_require_reconciliation",
        ],
        "evidence_links": {
            "parent_session_ids": sorted(
                {
                    str(job.get("evidence", {}).get("parent_session_id") or "")
                    for job in jobs
                    if isinstance(job, dict)
                    and isinstance(job.get("evidence"), dict)
                    and str(job.get("evidence", {}).get("parent_session_id") or "")
                }
            ),
            "task_graph_paths": sorted(
                {
                    str(job.get("evidence", {}).get("task_graph_path") or "")
                    for job in jobs
                    if isinstance(job, dict)
                    and isinstance(job.get("evidence"), dict)
                    and str(job.get("evidence", {}).get("task_graph_path") or "")
                }
            ),
        },
        "execution_backend": "/bg",
        "observability_surface": "/agent-pool",
        "runtime_owner": RUNTIME_OWNER,
        "notify": {
            "enabled": notify_state.get("enabled", True),
            "sound_enabled": notify_state.get("sound", {}).get("enabled", True),
            "visual_enabled": notify_state.get("visual", {}).get("enabled", True),
            "event_complete_enabled": notify_state.get("events", {}).get(
                "complete", True
            ),
            "event_error_enabled": notify_state.get("events", {}).get("error", True),
        },
        "latest_terminal_jobs": latest_terminal,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/bg cleanup",
            "/bg reconcile",
            "/bg list --status running",
            "/bg status <job-id>",
            "run /notify profile focus to keep bg alerts high-signal",
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

    def add_enqueue_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--cwd", default=str(Path.cwd()))
        command_parser.add_argument("--label", action="append")
        command_parser.add_argument(
            "--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS
        )
        command_parser.add_argument(
            "--stale-after-seconds", type=int, default=DEFAULT_STALE_AFTER_SECONDS
        )
        command_parser.add_argument("--task-id")
        command_parser.add_argument("--session")
        command_parser.add_argument("--owner")
        command_parser.add_argument("--scope", default=DEFAULT_SCOPE)
        command_parser.add_argument(
            "--codememory-config",
            default=str(DEFAULT_OC_CONFIG) if DEFAULT_OC_CONFIG is not None else None,
        )
        command_parser.add_argument("--codememory-bin", default=DEFAULT_OC_BIN)
        command_parser.add_argument(
            "--lease-state-path", default=str(DEFAULT_LEASE_STATE_PATH)
        )
        command_parser.add_argument("--lease-worktree")
        command_parser.add_argument(
            "--lease-ttl-seconds", type=int, default=DEFAULT_LEASE_TTL_SECONDS
        )
        command_parser.add_argument(
            "--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS
        )
        command_parser.add_argument("--retry-safe", action="store_true")
        command_parser.add_argument(
            "--max-log-bytes", type=int, default=DEFAULT_MAX_LOG_BYTES
        )

    enqueue = sub.add_parser("enqueue", help="enqueue command for background execution")
    add_enqueue_arguments(enqueue)
    enqueue.add_argument("cmd", nargs=argparse.REMAINDER)

    start = sub.add_parser("start", help="enqueue job and start worker immediately")
    add_enqueue_arguments(start)
    start.add_argument("cmd", nargs=argparse.REMAINDER)

    run = sub.add_parser("run", help="run queued jobs")
    run.add_argument("--id")
    run.add_argument("--max-jobs", type=int)
    run.add_argument(
        "--lease-max-concurrency", type=int, default=DEFAULT_MAX_CONCURRENCY
    )

    reconcile = sub.add_parser(
        "reconcile", help="reconcile interrupted lease-backed attempts"
    )
    reconcile.add_argument("--json", action="store_true")

    list_parser = sub.add_parser("list", help="list jobs")
    list_parser.add_argument(
        "--status",
        action="append",
        choices=[
            "queued",
            "running",
            "reconciling",
            "completed",
            "failed",
            "cancelled",
        ],
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
    status.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="run background task diagnostics")
    doctor.add_argument("--json", action="store_true")

    sub.add_parser("help", help="show usage")
    return parser


def main(argv: list[str]) -> int:
    if argv and argv[0] == "__lease_gate__":
        if len(argv) != 6:
            raise ValueError("invalid internal lease gate arguments")
        marker_path = Path(argv[2]).expanduser().resolve()
        if marker_path.parent != RUNS_DIR.resolve():
            raise ValueError("lease gate marker must stay inside the runs directory")
        return _run_lease_gate(
            int(argv[1]), marker_path, argv[3], argv[4], argv[5]
        )

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
    if args.subcommand == "reconcile":
        return command_reconcile(args)
    if args.subcommand == "list":
        return command_list(args)
    if args.subcommand == "status":
        return command_status(args)
    if args.subcommand == "read":
        return command_read(args)
    if args.subcommand == "cancel":
        code = command_cancel(args)
        if code == 0:
            with locked_jobs(writeback=False) as data:
                snapshot = find_job(data, args.id)
                if snapshot is not None:
                    emit_terminal_notification(snapshot)
        return code
    if args.subcommand == "cleanup":
        return command_cleanup(args)
    if args.subcommand == "doctor":
        return command_doctor(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001 - CLI error boundary
        print(f"error: {exc}")
        raise SystemExit(1)
