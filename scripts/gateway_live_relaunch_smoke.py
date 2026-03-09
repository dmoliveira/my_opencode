#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


DIST_FILES = [
    "hooks/delegation-concurrency-guard/index.js",
    "hooks/shared/delegation-runtime-state.js",
    "hooks/shared/delegation-trace.js",
    "hooks/subagent-lifecycle-supervisor/index.js",
    "hooks/subagent-telemetry-timeline/index.js",
]

PROMPT = (
    "Use exactly two explore subagents in parallel in this same session: one inspects README.md, "
    "one inspects docs/quickstart.md. Wait for both to finish. Then launch one more explore "
    "subagent in the same session to inspect AGENTS.md. Return PASS only if all three delegations "
    "complete without any already running or duplicate running blocker; otherwise return FAIL with "
    "the blocker text."
)


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def resolve_plugin_dist(home: Path, repo_root: Path) -> Path:
    return (
        home
        / ".config"
        / "opencode"
        / "my_opencode"
        / "plugin"
        / "gateway-core"
        / "dist"
    )


def sync_dist_files(
    source_root: Path, live_root: Path, scratch: Path
) -> dict[str, dict[str, str]]:
    backup_root = scratch / "backup"
    if backup_root.exists():
        shutil.rmtree(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, str]] = {}
    for rel in DIST_FILES:
        source = source_root / rel
        live = live_root / rel
        backup = backup_root / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, backup)
        manifest[rel] = {
            "source_before": sha1(source),
            "live_before": sha1(live),
            "backup": sha1(backup),
        }
        shutil.copy2(source, live)
        manifest[rel]["live_during"] = sha1(live)
    return manifest


def restore_dist_files(live_root: Path, scratch: Path) -> None:
    backup_root = scratch / "backup"
    for rel in DIST_FILES:
        backup = backup_root / rel
        live = live_root / rel
        if backup.exists():
            shutil.copy2(backup, live)


def run_smoke(
    repo_root: Path, output_dir: Path, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("opencode")
    if not binary:
        raise RuntimeError("opencode binary not found in PATH")
    stdout_path = output_dir / "parallel-relaunch.stdout"
    stderr_path = output_dir / "parallel-relaunch.stderr"
    with (
        stdout_path.open("w", encoding="utf-8") as stdout_handle,
        stderr_path.open("w", encoding="utf-8") as stderr_handle,
    ):
        return subprocess.run(
            [
                binary,
                "run",
                "--agent",
                "orchestrator",
                "--title",
                "parallel-relaunch-live",
                "--format",
                "json",
                "--print-logs",
                PROMPT,
            ],
            cwd=repo_root,
            env=os.environ.copy(),
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )


def inspect_result(output_dir: Path) -> dict[str, object]:
    stdout_path = output_dir / "parallel-relaunch.stdout"
    stderr_path = output_dir / "parallel-relaunch.stderr"
    stdout_text = (
        stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
    )
    stderr_text = (
        stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
    )
    final_text = ""
    final_text_session_id = ""
    for line in stdout_text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "text":
            continue
        session_id = str(payload.get("sessionID", "")).strip()
        part = payload.get("part") if isinstance(payload.get("part"), dict) else {}
        chunk = str(part.get("text", ""))
        if session_id and session_id == final_text_session_id:
            final_text += chunk
        else:
            final_text_session_id = session_id
            final_text = chunk
    combined_text = f"{stdout_text}\n{stderr_text}".lower()
    passed = final_text.strip() == "PASS"
    blocker = "already running" in combined_text or "duplicate running" in combined_text
    return {
        "passed": passed,
        "blocker_detected": blocker,
        "final_text": final_text,
        "final_text_session_id": final_text_session_id,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run live same-session gateway relaunch smoke"
    )
    parser.add_argument(
        "--home",
        default=str(Path.home()),
        help="Home directory containing installed my_opencode config",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to run opencode in",
    )
    parser.add_argument(
        "--sync-source-dist",
        default="",
        help="Optional dist directory to temporarily sync into the installed gateway plugin before running the smoke",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory for smoke artifacts; defaults to a temporary directory",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="Timeout for the live opencode smoke run",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON result")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.home).expanduser().resolve()
    repo_root = Path(args.repo_root).expanduser().resolve()
    live_dist_root = resolve_plugin_dist(home, repo_root)
    if not live_dist_root.exists():
        print("error: installed gateway dist directory not found", file=sys.stderr)
        return 2
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="gateway-live-relaunch-"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict[str, str]] | None = None
    try:
        if args.sync_source_dist:
            source_dist_root = Path(args.sync_source_dist).expanduser().resolve()
            manifest = sync_dist_files(source_dist_root, live_dist_root, output_dir)
            (output_dir / "parallel-relaunch-hashes.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

        completed = run_smoke(repo_root, output_dir, max(1, args.timeout_seconds))
        inspection = inspect_result(output_dir)
        payload = {
            "result": "PASS"
            if completed.returncode == 0
            and inspection["passed"]
            and not inspection["blocker_detected"]
            else "FAIL",
            "returncode": completed.returncode,
            "repo_root": str(repo_root),
            "home": str(home),
            "output_dir": str(output_dir),
            **inspection,
        }
        if manifest is not None:
            payload["hash_manifest"] = str(output_dir / "parallel-relaunch-hashes.json")
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"result: {payload['result']}")
            print(f"output_dir: {output_dir}")
            print(f"stdout: {payload['stdout_path']}")
            print(f"stderr: {payload['stderr_path']}")
            if manifest is not None:
                print(f"hash_manifest: {payload['hash_manifest']}")
        return 0 if payload["result"] == "PASS" else 1
    except subprocess.TimeoutExpired:
        payload = {
            "result": "FAIL",
            "returncode": None,
            "repo_root": str(repo_root),
            "home": str(home),
            "output_dir": str(output_dir),
            "passed": False,
            "blocker_detected": False,
            "stdout_path": str(output_dir / "parallel-relaunch.stdout"),
            "stderr_path": str(output_dir / "parallel-relaunch.stderr"),
            "timeout_seconds": max(1, args.timeout_seconds),
            "reason": "timeout",
        }
        if manifest is not None:
            payload["hash_manifest"] = str(output_dir / "parallel-relaunch-hashes.json")
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"result: {payload['result']}")
            print(f"output_dir: {output_dir}")
            print(f"reason: {payload['reason']}")
        return 1
    finally:
        if args.sync_source_dist:
            restore_dist_files(live_dist_root, output_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
