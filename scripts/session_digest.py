#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import (  # type: ignore
    _load_json_or_jsonc,
    load_layered_config,
    resolve_write_path,
)
from plan_execution_runtime import load_plan_execution_state  # type: ignore
from recovery_engine import (  # type: ignore
    build_resume_hints,
    evaluate_resume_eligibility,
    explain_resume_reason,
)
from session_metadata_index import (  # type: ignore
    DEFAULT_INDEX_PATH,
    update_session_index,
)
from session_sidecar_security import (  # type: ignore
    PublicationResult,
    SidecarSecurityError,
    SidecarSnapshot,
    assert_distinct_sidecars,
    atomic_write_private_json,
    inspect_sidecar,
    read_private_json,
    secure_sidecar_lock,
)
from todo_enforcement import normalize_todo_state  # type: ignore


DEFAULT_DIGEST_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_DIGEST_PATH", "~/.config/opencode/digests/last-session.json"
    )
).expanduser()

SESSION_CONFIG_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SESSION_CONFIG_PATH", "~/.config/opencode/opencode-session.json"
    )
).expanduser()
SESSION_ENV_SET = "MY_OPENCODE_SESSION_CONFIG_PATH" in os.environ
DIGEST_MAX_BYTES = 1024 * 1024
_EXPECTED_SNAPSHOT_UNSET = object()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_text(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def collect_git_snapshot(cwd: Path) -> dict:
    branch = run_text(["git", "-C", str(cwd), "branch", "--show-current"])
    status = run_text(["git", "-C", str(cwd), "status", "--short"])
    ahead_behind = run_text(["git", "-C", str(cwd), "status", "--short", "--branch"])

    status_lines = [line for line in status.splitlines() if line.strip()]
    return {
        "branch": branch or None,
        "status_count": len(status_lines),
        "status_preview": status_lines[:20],
        "branch_header": ahead_behind.splitlines()[0] if ahead_behind else None,
    }


def build_digest(reason: str, cwd: Path) -> dict:
    return {
        "timestamp": now_iso(),
        "reason": reason,
        "cwd": str(cwd),
        "git": collect_git_snapshot(cwd),
        "plan_execution": collect_plan_execution_snapshot(),
    }


def collect_plan_execution_snapshot() -> dict:
    try:
        layered, _ = load_layered_config()
        write_path = resolve_write_path()
    except Exception:
        return {"status": "unknown", "available": False}

    section, _ = load_plan_execution_state(layered, write_path)
    if not isinstance(section, dict) or not section:
        return {"status": "idle", "available": False}

    raw_steps = section.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    counts = {
        "total": len(steps),
        "done": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "done"
        ),
        "failed": sum(
            1
            for step in steps
            if isinstance(step, dict) and step.get("state") == "failed"
        ),
        "in_progress": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "in_progress"
        ),
        "pending": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "pending"
        ),
        "skipped": sum(
            1
            for step in steps
            if isinstance(step, dict)
            and normalize_todo_state(step.get("state")) == "skipped"
        ),
    }
    raw_plan = section.get("plan")
    plan: dict = raw_plan if isinstance(raw_plan, dict) else {}
    raw_metadata = plan.get("metadata")
    metadata: dict = raw_metadata if isinstance(raw_metadata, dict) else {}
    raw_deviations = section.get("deviations")
    deviations: list = raw_deviations if isinstance(raw_deviations, list) else []
    raw_resume = section.get("resume")
    resume: dict = raw_resume if isinstance(raw_resume, dict) else {}
    interruption_class = str(resume.get("last_interruption_class") or "tool_failure")
    eligibility = evaluate_resume_eligibility(section, interruption_class)
    reason_code = str(
        eligibility.get("reason_code") or "resume_missing_runtime_artifacts"
    )
    cooldown_remaining = int(eligibility.get("cooldown_remaining", 0) or 0)
    checkpoint = (
        eligibility.get("checkpoint")
        if isinstance(eligibility.get("checkpoint"), dict)
        else None
    )
    resume_hints = {
        "enabled": bool(resume.get("enabled", True)),
        "interruption_class": interruption_class,
        "eligible": bool(eligibility.get("eligible")),
        "reason_code": reason_code,
        "reason": explain_resume_reason(
            reason_code,
            cooldown_remaining=cooldown_remaining,
        ),
        "cooldown_remaining": cooldown_remaining,
        "hints": build_resume_hints(
            reason_code,
            interruption_class=interruption_class,
            checkpoint=checkpoint,
            cooldown_remaining=cooldown_remaining,
        ),
    }

    return {
        "status": str(section.get("status") or "idle"),
        "available": True,
        "plan_id": metadata.get("id"),
        "plan_path": plan.get("path"),
        "finished_at": section.get("finished_at"),
        "step_counts": counts,
        "deviation_count": len(deviations),
        "resume_hints": resume_hints,
    }


def _digest_lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


def _index_lock_path() -> Path:
    return DEFAULT_INDEX_PATH.with_name(f"{DEFAULT_INDEX_PATH.name}.lock")


def _transaction_sidecars(path: Path) -> dict[str, Path]:
    return {
        "digest": path,
        "digest_lock": _digest_lock_path(path),
        "index": DEFAULT_INDEX_PATH,
        "index_lock": _index_lock_path(),
    }


def _raise_preflight_failure(reason_code: str, message: str) -> None:
    raise SidecarSecurityError(reason_code, message, phase="preflight")


def _preflight_digest_transaction(path: Path) -> bool:
    sidecars = _transaction_sidecars(path)
    assert_distinct_sidecars(sidecars)
    digest_exists = False
    for target in ("digest", "index"):
        inspection = inspect_sidecar(sidecars[target], target=target)
        if target == "digest":
            digest_exists = inspection.exists
        if inspection.state in {"missing", "private"}:
            continue
        reason_code = inspection.reason_code or "session_sidecar_unsafe_target"
        if inspection.state == "repairable":
            reason_code = "session_sidecar_insecure_permissions"
        _raise_preflight_failure(
            reason_code,
            f"{target} sidecar failed private-file preflight",
        )
    for target in ("digest_lock", "index_lock"):
        inspection = inspect_sidecar(sidecars[target], target=target)
        if inspection.state in {"missing", "private", "repairable"}:
            continue
        _raise_preflight_failure(
            inspection.reason_code or "session_sidecar_unsafe_target",
            f"{target} failed stable-lock preflight",
        )
    return digest_exists


def _read_digest(path: Path, *, allow_missing: bool) -> tuple[dict, SidecarSnapshot] | None:
    loaded = read_private_json(
        path,
        max_bytes=DIGEST_MAX_BYTES,
        allow_missing=allow_missing,
    )
    if loaded is None:
        return None
    return loaded.payload, loaded.snapshot


def _revalidate_after_hook(
    path: Path,
    *,
    required: bool,
) -> tuple[dict, SidecarSnapshot] | None:
    _preflight_digest_transaction(path)
    loaded = _read_digest(path, allow_missing=not required)
    if required and loaded is None:
        raise SidecarSecurityError(
            "session_sidecar_unsafe_target",
            "digest disappeared after external hook",
            phase="hook_revalidation",
        )
    return loaded


def write_digest(
    path: Path,
    digest: dict,
    *,
    expected_snapshot: SidecarSnapshot | None | object = _EXPECTED_SNAPSHOT_UNSET,
) -> PublicationResult:
    if expected_snapshot is _EXPECTED_SNAPSHOT_UNSET:
        return atomic_write_private_json(
            path,
            digest,
            max_bytes=DIGEST_MAX_BYTES,
        )
    return atomic_write_private_json(
        path,
        digest,
        max_bytes=DIGEST_MAX_BYTES,
        expected_snapshot=expected_snapshot,
    )


def _print_sidecar_failure(
    path: Path,
    exc: SidecarSecurityError,
    *,
    generation: str,
    digest_committed: bool = False,
    session_index: dict | None = None,
) -> int:
    print("result: FAIL")
    print(f"digest: {path}")
    print(f"reason_code: {exc.reason_code}")
    print(f"phase: {exc.phase}")
    print(f"generation: {generation}")
    print(f"committed: {'yes' if exc.committed else 'no'}")
    print(f"durability: {exc.durability}")
    print(f"digest_committed: {'yes' if digest_committed or exc.committed else 'no'}")
    if isinstance(session_index, dict):
        print(f"session_index_result: {session_index.get('result', 'unknown')}")
        if session_index.get("reason_code"):
            print(f"session_index_reason: {session_index.get('reason_code')}")
    return 1


def run_hook(command: str, digest_path: Path) -> int:
    env = os.environ.copy()
    env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)
    result = subprocess.run(command, shell=True, env=env, check=False)
    return result.returncode


def trusted_post_session_paths() -> list[Path]:
    home = Path("~").expanduser()
    candidates = [
        home / ".config" / "opencode" / "my_opencode.jsonc",
        home / ".config" / "opencode" / "my_opencode.json",
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".config" / "opencode" / "opencode.json",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path.expanduser())
    return unique


def load_trusted_post_session_block() -> dict | None:
    for path in trusted_post_session_paths():
        if not path.exists():
            continue
        try:
            data = _load_json_or_jsonc(path)
        except Exception:
            continue
        post = data.get("post_session")
        if isinstance(post, dict):
            return post
    return None


def load_post_session_config() -> dict:
    config = {
        "enabled": False,
        "command": "",
        "timeout_ms": 120000,
        "run_on": ["exit"],
    }

    post = None

    if SESSION_ENV_SET:
        if not SESSION_CONFIG_PATH.exists():
            return config
        data = json.loads(SESSION_CONFIG_PATH.read_text(encoding="utf-8"))
        post = data.get("post_session")
    else:
        post = load_trusted_post_session_block()
        if post is None and SESSION_CONFIG_PATH.exists():
            legacy_data = json.loads(SESSION_CONFIG_PATH.read_text(encoding="utf-8"))
            post = legacy_data.get("post_session")

    if not isinstance(post, dict):
        return config

    if isinstance(post.get("enabled"), bool):
        config["enabled"] = post["enabled"]
    if isinstance(post.get("command"), str):
        config["command"] = post["command"]
    if isinstance(post.get("timeout_ms"), int) and post["timeout_ms"] > 0:
        config["timeout_ms"] = post["timeout_ms"]
    if isinstance(post.get("run_on"), list):
        values = [x for x in post["run_on"] if isinstance(x, str)]
        if values:
            config["run_on"] = values

    return config


def run_post_session(config: dict, reason: str, digest_path: Path) -> dict:
    if not config["enabled"]:
        return {"attempted": False, "reason": "disabled"}

    if reason not in config["run_on"]:
        return {
            "attempted": False,
            "reason": f"reason {reason} not in run_on",
            "run_on": config["run_on"],
        }

    command = (config.get("command") or "").strip()
    if not command:
        return {"attempted": False, "reason": "command is unset"}

    env = os.environ.copy()
    env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)
    env["MY_OPENCODE_POST_REASON"] = reason

    timeout_seconds = max(config["timeout_ms"] / 1000.0, 0.2)
    try:
        result = subprocess.run(
            command,
            shell=True,
            env=env,
            check=False,
            timeout=timeout_seconds,
        )
        return {
            "attempted": True,
            "command": command,
            "exit_code": result.returncode,
            "timed_out": False,
            "timeout_ms": config["timeout_ms"],
        }
    except subprocess.TimeoutExpired:
        return {
            "attempted": True,
            "command": command,
            "exit_code": None,
            "timed_out": True,
            "timeout_ms": config["timeout_ms"],
        }


def print_summary(path: Path, digest: dict) -> None:
    print(f"digest: {path}")
    print(f"timestamp: {digest.get('timestamp')}")
    print(f"reason: {digest.get('reason')}")
    print(f"cwd: {digest.get('cwd')}")
    git = digest.get("git", {}) if isinstance(digest.get("git"), dict) else {}
    print(f"branch: {git.get('branch')}")
    print(f"changes: {git.get('status_count')}")
    post = digest.get("post_session")
    if isinstance(post, dict) and post.get("attempted"):
        status = "timeout" if post.get("timed_out") else f"exit {post.get('exit_code')}"
        print(f"post_session: {status}")
    plan_exec = (
        digest.get("plan_execution")
        if isinstance(digest.get("plan_execution"), dict)
        else {}
    )
    if plan_exec:
        print(f"plan_execution: {plan_exec.get('status', 'idle')}")
        if plan_exec.get("plan_id"):
            print(f"plan_id: {plan_exec.get('plan_id')}")
        resume_hints = (
            plan_exec.get("resume_hints")
            if isinstance(plan_exec.get("resume_hints"), dict)
            else {}
        )
        if resume_hints:
            print(f"resume_eligible: {'yes' if resume_hints.get('eligible') else 'no'}")
            print(f"resume_reason: {resume_hints.get('reason_code')}")
    session_index = (
        digest.get("session_index")
        if isinstance(digest.get("session_index"), dict)
        else {}
    )
    if session_index:
        print(f"session_index_result: {session_index.get('result', 'unknown')}")
        if session_index.get("reason_code"):
            print(f"session_index_reason: {session_index.get('reason_code')}")
        print(f"session_id: {session_index.get('session_id')}")
        print(f"session_index: {session_index.get('path')}")
        quarantine = (
            session_index.get("quarantine")
            if isinstance(session_index.get("quarantine"), dict)
            else {}
        )
        if quarantine:
            print(f"session_index_quarantine: {quarantine.get('path')}")
            print(f"session_index_sha256: {quarantine.get('sha256')}")


def usage() -> int:
    print(
        'usage: /digest run [--reason <idle|exit|manual>] [--path <digest.json>] [--hook "command"] [--run-post] | /digest show [--path <digest.json>] | /digest doctor [--path <digest.json>] [--json]'
    )
    return 2


def parse_option(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    index = argv.index(name)
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def command_run(argv: list[str]) -> int:
    reason = parse_option(argv, "--reason") or "manual"
    path_value = parse_option(argv, "--path")
    hook_value = parse_option(argv, "--hook")
    run_post = "--run-post" in argv

    path = Path(path_value).expanduser() if path_value else DEFAULT_DIGEST_PATH
    cwd = Path.cwd()

    post_result = None
    try:
        digest_existed_before_post = _preflight_digest_transaction(path)
        digest = build_digest(reason=reason, cwd=cwd)
        if run_post:
            post_config = load_post_session_config()
            post_result = run_post_session(post_config, reason=reason, digest_path=path)
            digest["post_session"] = post_result
            _revalidate_after_hook(path, required=digest_existed_before_post)
    except SidecarSecurityError as exc:
        return _print_sidecar_failure(path, exc, generation="preflight")

    try:
        timeout_ms = max(
            0,
            min(
                60_000,
                int(os.environ.get("MY_OPENCODE_DIGEST_LOCK_TIMEOUT_MS", "5000")),
            ),
        )
    except ValueError:
        timeout_ms = 5_000

    initial_publication: PublicationResult
    final_publication: PublicationResult
    session_index: dict | None = None
    try:
        with secure_sidecar_lock(
            _digest_lock_path(path),
            timeout_seconds=timeout_ms / 1000.0,
        ):
            _preflight_digest_transaction(path)
            initial_publication = write_digest(path, digest)
            try:
                session_index = update_session_index(digest)
            except Exception:
                session_index = {
                    "result": "FAIL",
                    "reason_code": "session_index_io_error",
                    "quarantine": None,
                    "error": "session index update failed unexpectedly",
                }
            digest["session_index"] = session_index
            final_publication = write_digest(
                path,
                digest,
                expected_snapshot=initial_publication.snapshot,
            )
    except SidecarSecurityError as exc:
        return _print_sidecar_failure(
            path,
            exc,
            generation="final" if session_index is not None else "initial",
            digest_committed="initial_publication" in locals(),
            session_index=session_index,
        )

    print_summary(path, digest)
    print(f"digest_initial_durability: {initial_publication.durability}")
    print(f"digest_final_durability: {final_publication.durability}")

    post_exit = 0
    if isinstance(post_result, dict) and post_result.get("attempted"):
        if post_result.get("timed_out"):
            post_exit = 124
        else:
            post_exit = int(post_result.get("exit_code", 0) or 0)

    if hook_value:
        code = run_hook(hook_value, path)
        print(f"hook: exited with code {code}")
        try:
            observed = _revalidate_after_hook(path, required=True)
        except SidecarSecurityError as exc:
            return _print_sidecar_failure(
                path,
                exc,
                generation="post_hook",
                digest_committed=True,
                session_index=session_index,
            )
        assert observed is not None
        observed_digest, observed_snapshot = observed
        if observed_snapshot != final_publication.snapshot:
            print("hook_digest_superseded: yes")
            print_summary(path, observed_digest)
        if code != 0:
            return code
        if post_exit != 0:
            return post_exit
        observed_session_index = observed_digest.get("session_index")
        if not isinstance(observed_session_index, dict):
            print("result: FAIL")
            print("reason_code: session_sidecar_malformed_json")
            return 1
        return (
            0
            if observed_session_index.get("result") == "PASS"
            else 1
        )

    if post_exit != 0:
        return post_exit
    return 0 if digest.get("session_index", {}).get("result") == "PASS" else 1


def command_show(argv: list[str]) -> int:
    path_value = parse_option(argv, "--path")
    path = Path(path_value).expanduser() if path_value else DEFAULT_DIGEST_PATH
    try:
        loaded = _read_digest(path, allow_missing=True)
    except SidecarSecurityError as exc:
        return _print_sidecar_failure(path, exc, generation="show")
    if loaded is None:
        print(f"error: digest file not found: {path}")
        return 1

    digest, _ = loaded
    print_summary(path, digest)

    preview = digest.get("git", {}).get("status_preview", [])
    if preview:
        print("status preview:")
        for line in preview:
            print(f"- {line}")
    return 0


def collect_doctor(path: Path) -> dict:
    problems: list[str] = []
    warnings: list[str] = []

    try:
        inspection = inspect_sidecar(path, target="digest")
    except SidecarSecurityError as exc:
        return {
            "result": "FAIL",
            "path": str(path),
            "exists": False,
            "reason_code": exc.reason_code,
            "warnings": warnings,
            "problems": ["digest sidecar safety check failed"],
            "quick_fixes": ["run /session repair-sidecars --json"],
        }

    if not inspection.exists:
        warnings.append("digest file does not exist yet")
        return {
            "result": "PASS",
            "path": str(path),
            "exists": False,
            "warnings": warnings,
            "problems": problems,
            "quick_fixes": ["run /digest run --reason manual"],
            "sidecar": inspection.to_payload(),
        }

    if inspection.state != "private":
        reason_code = inspection.reason_code or "session_sidecar_unsafe_target"
        problems.append("digest sidecar is not private and safe")
        return {
            "result": "FAIL",
            "path": str(path),
            "exists": True,
            "reason_code": reason_code,
            "warnings": warnings,
            "problems": problems,
            "sidecar": inspection.to_payload(),
            "quick_fixes": ["run /session repair-sidecars --json"],
        }

    try:
        loaded = _read_digest(path, allow_missing=False)
        assert loaded is not None
        digest, _ = loaded
    except SidecarSecurityError as exc:
        problems.append("digest sidecar could not be loaded securely")
        return {
            "result": "FAIL",
            "path": str(path),
            "exists": True,
            "reason_code": exc.reason_code,
            "warnings": warnings,
            "problems": problems,
            "sidecar": inspection.to_payload(),
            "quick_fixes": ["inspect the local digest before regenerating it"],
        }

    for field in ("timestamp", "reason", "cwd", "git"):
        if field not in digest:
            warnings.append(f"missing digest field: {field}")

    plan_exec = digest.get("plan_execution")
    if plan_exec is not None and not isinstance(plan_exec, dict):
        warnings.append("plan_execution block is invalid")

    git_block = digest.get("git")
    if not isinstance(git_block, dict):
        warnings.append("git block is missing or invalid")
    else:
        if git_block.get("branch") is None:
            warnings.append("git branch is unknown")

    raw_session_index = digest.get("session_index")
    session_index = raw_session_index if isinstance(raw_session_index, dict) else {}
    if not session_index:
        warnings.append("session_index result is missing or invalid")
    elif session_index.get("result") != "PASS":
        reason_code = str(session_index.get("reason_code") or "session_index_unknown_failure")
        problems.append(f"session index update failed: {reason_code}")

    return {
        "result": "PASS" if not problems else "FAIL",
        "path": str(path),
        "exists": True,
        "warnings": warnings,
        "problems": problems,
        "session_index": session_index,
        "sidecar": inspection.to_payload(),
        "quick_fixes": ["run /digest run --reason manual"]
        if warnings or problems
        else [],
    }


def command_doctor(argv: list[str]) -> int:
    path_value = parse_option(argv, "--path")
    json_output = "--json" in argv
    if len([x for x in argv if x == "--json"]) > 1:
        return usage()

    path = Path(path_value).expanduser() if path_value else DEFAULT_DIGEST_PATH
    report = collect_doctor(path)

    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("digest doctor")
    print("------------")
    print(f"path: {report['path']}")
    print(f"exists: {'yes' if report['exists'] else 'no'}")

    if report["warnings"]:
        print("\nwarnings:")
        for item in report["warnings"]:
            print(f"- {item}")

    if report["problems"]:
        print("\nproblems:")
        for item in report["problems"]:
            print(f"- {item}")
        print("\nresult: FAIL")
        return 1

    print("\nresult: PASS")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()

    command = argv[0]
    rest = argv[1:]

    if command == "help":
        return usage()
    if command == "run":
        return command_run(rest)
    if command == "show":
        return command_show(rest)
    if command == "doctor":
        return command_doctor(rest)
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
