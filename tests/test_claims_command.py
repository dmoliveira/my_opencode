from __future__ import annotations

import json
import multiprocessing
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import atomic_json_state
import claims_command
import workflow_command


def run_claim_worker(start, results, environment, issue_id: str, owner: str) -> None:
    try:
        if not start.wait(timeout=10):
            results.put((-1, "", "start barrier timed out"))
            return
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "claims_command.py"),
                "claim",
                issue_id,
                "--by",
                owner,
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        results.put((completed.returncode, completed.stdout, completed.stderr))
    except (OSError, subprocess.SubprocessError) as exc:
        results.put((-1, "", repr(exc)))


class ClaimsStatePersistenceTest(unittest.TestCase):
    def test_atomic_save_never_exposes_truncated_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claims-atomic-test-") as raw_tmp:
            root = Path(raw_tmp)
            state_path = root / "claims.json"
            old_state = {"version": 1, "claims": {"old": {"status": "active"}}}
            new_state = {"version": 1, "claims": {"new": {"status": "active"}}}
            state_path.write_text(json.dumps(old_state) + "\n", encoding="utf-8")
            replace_ready = threading.Event()
            release_replace = threading.Event()
            writer_errors: list[OSError] = []
            real_replace = os.replace

            def paused_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
                replace_ready.set()
                if not release_replace.wait(timeout=10):
                    raise TimeoutError("replace barrier timed out")
                real_replace(source, target)

            def write_new_state() -> None:
                try:
                    claims_command.save_state(state_path, new_state)
                except OSError as exc:
                    writer_errors.append(exc)

            with patch.object(atomic_json_state.os, "replace", side_effect=paused_replace):
                writer = threading.Thread(target=write_new_state, daemon=True)
                writer.start()
                try:
                    self.assertTrue(replace_ready.wait(timeout=10))
                    copied_path = root / "copied-claims.json"
                    copied_path.write_text(
                        state_path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                    self.assertEqual(old_state, json.loads(state_path.read_text()))
                    self.assertEqual(old_state, json.loads(copied_path.read_text()))
                    staged_paths = list(root.glob(".claims.json.*.tmp"))
                    self.assertEqual(1, len(staged_paths))
                    self.assertEqual(new_state, json.loads(staged_paths[0].read_text()))
                finally:
                    release_replace.set()
                    writer.join(timeout=10)

            self.assertFalse(writer.is_alive())
            self.assertEqual([], writer_errors)
            self.assertEqual(new_state, json.loads(state_path.read_text()))
            self.assertEqual([], list(root.glob(".claims.json.*.tmp")))
            self.assertEqual(0o600, stat.S_IMODE(state_path.stat().st_mode))

    def test_replace_failure_preserves_old_state_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claims-replace-test-") as raw_tmp:
            root = Path(raw_tmp)
            state_path = root / "claims.json"
            original = b'{"version": 1, "claims": {"old": {}}}\n'
            state_path.write_bytes(original)

            with (
                patch.object(
                    atomic_json_state.os,
                    "replace",
                    side_effect=OSError("replace failed"),
                ),
                self.assertRaisesRegex(OSError, "replace failed"),
            ):
                claims_command.save_state(
                    state_path,
                    {"version": 1, "claims": {"new": {}}},
                )

            self.assertEqual(original, state_path.read_bytes())
            self.assertEqual([], list(root.glob(".claims.json.*.tmp")))

    def test_persistent_corruption_remains_fail_closed_and_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claims-corrupt-test-") as raw_tmp:
            root = Path(raw_tmp)
            for index, content in enumerate((b"", b"{broken")):
                with self.subTest(content=content):
                    state_path = root / f"claims-{index}.json"
                    state_path.write_bytes(content)
                    with (
                        patch.object(
                            workflow_command, "DEFAULT_CLAIMS_PATH", state_path
                        ),
                        self.assertRaises(json.JSONDecodeError),
                    ):
                        workflow_command.load_claim_rows()
                    self.assertEqual(content, state_path.read_bytes())

    def test_claims_and_agent_pool_commands_share_pool_transaction_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claims-pool-lock-test-") as raw_tmp:
            root = Path(raw_tmp)
            state_path = root / "claims.json"
            pool_path = root / "agent-pool.json"
            environment = {
                **os.environ,
                "CI": "true",
                "HOME": str(root),
                "MY_OPENCODE_CLAIMS_PATH": str(state_path),
                "MY_OPENCODE_AGENT_POOL_PATH": str(pool_path),
                "MY_OPENCODE_AUDIT_PATH": str(root / "audit.json"),
            }
            claim_command = [
                sys.executable,
                str(SCRIPTS / "claims_command.py"),
                "claim",
                "shared-pool-issue",
                "--by",
                "human:owner",
                "--json",
            ]
            spawn_command = [
                sys.executable,
                str(SCRIPTS / "agent_pool_command.py"),
                "spawn",
                "--type",
                "coder",
                "--json",
            ]

            with atomic_json_state.json_state_write_lock(pool_path):
                claim_process = subprocess.Popen(
                    claim_command,
                    cwd=ROOT,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                spawn_process = subprocess.Popen(
                    spawn_command,
                    cwd=ROOT,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                time.sleep(0.5)
                self.assertIsNone(claim_process.poll())
                self.assertIsNone(spawn_process.poll())
                self.assertFalse(pool_path.exists())

            claim_stdout, claim_stderr = claim_process.communicate(timeout=20)
            spawn_stdout, spawn_stderr = spawn_process.communicate(timeout=20)
            self.assertEqual(0, claim_process.returncode, claim_stderr or claim_stdout)
            self.assertEqual(0, spawn_process.returncode, spawn_stderr or spawn_stdout)
            pool_state = json.loads(pool_path.read_text())
            self.assertEqual(["coder-1"], [row["agent_id"] for row in pool_state["agents"]])
            claims_state = json.loads(state_path.read_text())
            self.assertIn("shared-pool-issue", claims_state["claims"])
            self.assertEqual(0o600, stat.S_IMODE(pool_path.stat().st_mode))

    def test_concurrent_claims_preserve_distinct_updates_and_reject_duplicates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claims-concurrency-test-") as raw_tmp:
            root = Path(raw_tmp)
            distinct_path = root / "distinct-claims.json"
            distinct_results = self.run_concurrent_claims(
                root,
                distinct_path,
                [("issue-a", "human:a"), ("issue-b", "human:b")],
            )
            self.assertEqual([0, 0], sorted(row[0] for row in distinct_results))
            distinct_state = json.loads(distinct_path.read_text())
            self.assertEqual(
                {"issue-a", "issue-b"}, set(distinct_state["claims"].keys())
            )

            duplicate_path = root / "duplicate-claims.json"
            duplicate_results = self.run_concurrent_claims(
                root,
                duplicate_path,
                [("same-issue", "human:a"), ("same-issue", "human:b")],
            )
            self.assertEqual([0, 1], sorted(row[0] for row in duplicate_results))
            duplicate_state = json.loads(duplicate_path.read_text())
            self.assertEqual(["same-issue"], list(duplicate_state["claims"].keys()))
            self.assertEqual(0o600, stat.S_IMODE(duplicate_path.stat().st_mode))

    def run_concurrent_claims(
        self,
        root: Path,
        state_path: Path,
        claims: list[tuple[str, str]],
    ) -> list[tuple[int, str, str]]:
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = []
        for index, (issue_id, owner) in enumerate(claims):
            environment = {
                **os.environ,
                "CI": "true",
                "HOME": str(root),
                "MY_OPENCODE_CLAIMS_PATH": str(state_path),
                "MY_OPENCODE_AGENT_POOL_PATH": str(
                    state_path.with_name(f"{state_path.stem}-agent-pool.json")
                ),
                "MY_OPENCODE_AUDIT_PATH": str(
                    state_path.with_name(f"{state_path.stem}-audit-{index}.json")
                ),
            }
            process = context.Process(
                target=run_claim_worker,
                args=(start, results, environment, issue_id, owner),
            )
            process.start()
            processes.append(process)

        start.set()
        rows = [results.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            self.assertFalse(process.is_alive())
            self.assertEqual(0, process.exitcode)
        self.assertTrue(
            all(row[0] >= 0 for row in rows),
            "\n".join(row[2] for row in rows if row[0] < 0),
        )
        return rows


if __name__ == "__main__":
    unittest.main()
