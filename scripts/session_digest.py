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

from config_layering import load_layered_config  # type: ignore
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
    except Exception:
        return {"status": "unknown", "available": False}

    section = layered.get("plan_execution")
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

    return {
        "status": str(section.get("status") or "idle"),
        "available": True,
        "plan_id": metadata.get("id"),
        "plan_path": plan.get("path"),
        "finished_at": section.get("finished_at"),
        "step_counts": counts,
        "deviation_count": len(deviations),
    }


def write_digest(path: Path, digest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(digest, indent=2) + "\n", encoding="utf-8")


def run_hook(command: str, digest_path: Path) -> int:
    env = os.environ.copy()
    env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)
    result = subprocess.run(command, shell=True, env=env, check=False)
    return result.returncode


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
        data, _ = load_layered_config()
        if isinstance(data.get("post_session"), dict):
            post = data.get("post_session")
        elif SESSION_CONFIG_PATH.exists():
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

    digest = build_digest(reason=reason, cwd=cwd)

    post_result = None
    if run_post:
        post_config = load_post_session_config()
        post_result = run_post_session(post_config, reason=reason, digest_path=path)
        digest["post_session"] = post_result

    write_digest(path, digest)
    print_summary(path, digest)

    post_exit = 0
    if isinstance(post_result, dict) and post_result.get("attempted"):
        if post_result.get("timed_out"):
            post_exit = 124
        else:
            post_exit = int(post_result.get("exit_code", 0) or 0)

    if hook_value:
        code = run_hook(hook_value, path)
        print(f"hook: exited with code {code}")
        return code if code != 0 else post_exit

    return post_exit


def command_show(argv: list[str]) -> int:
    path_value = parse_option(argv, "--path")
    path = Path(path_value).expanduser() if path_value else DEFAULT_DIGEST_PATH
    if not path.exists():
        print(f"error: digest file not found: {path}")
        return 1

    digest = json.loads(path.read_text(encoding="utf-8"))
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

    if not path.exists():
        warnings.append("digest file does not exist yet")
        return {
            "result": "PASS",
            "path": str(path),
            "exists": False,
            "warnings": warnings,
            "problems": problems,
            "quick_fixes": ["run /digest run --reason manual"],
        }

    try:
        digest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        problems.append(f"failed to parse digest JSON: {exc}")
        return {
            "result": "FAIL",
            "path": str(path),
            "exists": True,
            "warnings": warnings,
            "problems": problems,
            "quick_fixes": ["run /digest run --reason manual to regenerate"],
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

    return {
        "result": "PASS" if not problems else "FAIL",
        "path": str(path),
        "exists": True,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": ["run /digest run --reason manual"] if warnings else [],
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
