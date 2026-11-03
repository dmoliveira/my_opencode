from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import background_task_manager as bg

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class BackgroundArtifactRetentionTest(unittest.TestCase):
    def test_retention_preserves_records_and_does_not_unlink_stored_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bg-artifact-retention-") as raw:
            root = Path(raw)
            external = root / "external.log"
            external.write_bytes(b"synthetic external data\n")
            link = root / "owned-link"
            link.symlink_to(external)
            artifact = root / "attempt.receipt.json"
            artifact.write_bytes(b"synthetic receipt\n")
            before_paths = {
                path: (path.read_bytes(), path.lstat().st_ino, path.lstat().st_mtime_ns)
                for path in (external, link, artifact)
            }
            jobs = [
                {"id": "recent", "status": "completed", "created_at": "2025-12-31T00:00:00Z", "log_path": str(link)},
                {"id": "older", "status": "failed", "created_at": "2000-01-01T00:00:00Z", "log_path": str(external),
                 "attempts": [{"receipt_path": str(artifact), "gate_path": str(external)}]},
                {"id": "newer", "status": "cancelled", "created_at": "2025-12-30T00:00:00Z", "meta_path": str(external)},
                {"id": "unknown", "status": "reconciling", "created_at": "2000-01-01T00:00:00Z", "log_path": str(external)},
                {"id": "queued", "status": "queued", "created_at": "2000-01-01T00:00:00Z"},
            ]
            data = {"jobs": jobs}
            original = copy.deepcopy(data)
            with (
                patch.object(bg, "now_utc", return_value=NOW),
                patch.object(Path, "unlink", autospec=True) as unlink,
                patch.object(bg.os, "unlink") as os_unlink,
                patch.object(bg.os, "remove") as os_remove,
                patch.object(bg, "terminate_process", side_effect=AssertionError("must not signal")),
            ):
                report = bg.cleanup_jobs(data, retention_days=14, max_terminal=1)
            unlink.assert_not_called()
            os_unlink.assert_not_called()
            os_remove.assert_not_called()
            self.assertEqual(original, data)
            self.assertEqual("deferred", report["terminal_retention_mode"])
            self.assertEqual(2, report["terminal_retention_deferred"])
            self.assertEqual(0, report["pruned"])
            self.assertEqual(0, report["deleted_files"])
            self.assertEqual(len(jobs), report["remaining"])
            self.assertEqual(
                before_paths,
                {path: (path.read_bytes(), path.lstat().st_ino, path.lstat().st_mtime_ns)
                 for path in before_paths},
            )
            self.assertTrue(link.is_symlink())

    def test_retention_reports_deferred_mode_even_without_eligible_jobs(self) -> None:
        data = {"jobs": [{"id": "recent", "status": "completed", "created_at": "2025-12-31T00:00:00Z"}]}
        original = copy.deepcopy(data)
        with patch.object(bg, "now_utc", return_value=NOW):
            report = bg.cleanup_jobs(data, retention_days=14, max_terminal=200)
        self.assertEqual(original, data)
        self.assertEqual("deferred", report["terminal_retention_mode"])
        self.assertEqual(0, report["terminal_retention_deferred"])
        self.assertEqual(0, report["pruned"])

    def test_deferred_count_respects_age_and_disabled_count_cap(self) -> None:
        jobs = [
            {"id": "old", "status": "failed", "created_at": "2000-01-01T00:00:00Z"},
            {"id": "recent", "status": "completed", "created_at": "2025-12-31T00:00:00Z"},
            {"id": "undated", "status": "cancelled", "created_at": "invalid"},
        ]
        for max_terminal, expected in ((-1, 1), (0, 3), (1, 2)):
            with self.subTest(max_terminal=max_terminal):
                data = {"jobs": copy.deepcopy(jobs)}
                with patch.object(bg, "now_utc", return_value=NOW):
                    report = bg.cleanup_jobs(data, retention_days=14, max_terminal=max_terminal)
                self.assertEqual(jobs, data["jobs"])
                self.assertEqual(expected, report["terminal_retention_deferred"])

    def test_cleanup_reports_deferred_retention_in_json_and_text(self) -> None:
        for json_output in (False, True):
            with self.subTest(json_output=json_output):
                data = {"jobs": [{"id": "old", "status": "completed", "created_at": "2000-01-01T00:00:00Z"}]}

                @contextlib.contextmanager
                def locked_jobs(*, writeback: bool = True, _data=data):
                    yield _data

                output = io.StringIO()
                with (
                    patch.object(bg, "locked_jobs", side_effect=locked_jobs),
                    patch.object(bg, "reconcile_lease_jobs", return_value={}),
                    patch.object(bg, "now_utc", return_value=NOW),
                    contextlib.redirect_stdout(output),
                ):
                    result = bg.command_cleanup(argparse.Namespace(retention_days=14, max_terminal=0, json=json_output))
                self.assertEqual(1, result)
                self.assertEqual(1, len(data["jobs"]))
                if json_output:
                    report = json.loads(output.getvalue())
                    self.assertEqual("deferred", report["terminal_retention_mode"])
                    self.assertEqual(1, report["terminal_retention_deferred"])
                    self.assertEqual(0, report["pruned"])
                else:
                    self.assertIn("terminal_retention_mode: deferred", output.getvalue())
                    self.assertIn("terminal_retention_deferred: 1", output.getvalue())

    def test_cleanup_cli_preserves_external_artifact_in_synthetic_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bg-retention-cli-") as raw:
            root = Path(raw)
            home, tmp, store = (root / name for name in ("home", "tmp", "bg"))
            for directory in (home, tmp, store):
                directory.mkdir(mode=0o700)
            external = root / "outside.log"
            external.write_bytes(b"synthetic external artifact\n")
            before = (external.read_bytes(), external.stat().st_ino, external.stat().st_mtime_ns)
            terminal = {
                "id": "old", "status": "completed", "created_at": "2000-01-01T00:00:00Z",
                "log_path": str(external),
            }
            jobs = store / "jobs.json"
            jobs.write_text(json.dumps({"version": 1, "jobs": [terminal]}), encoding="utf-8")
            jobs.chmod(0o600)
            env = {
                "HOME": str(home), "TMPDIR": str(tmp), "MY_OPENCODE_BG_DIR": str(store),
                "PATH": "/opt/homebrew/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C",
            }
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "background_task_manager.py"), "cleanup",
                 "--max-terminal", "0", "--retention-days", "0", "--json"],
                cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=30, check=False,
            )
            self.assertEqual(1, result.returncode, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual("deferred", report["terminal_retention_mode"])
            self.assertEqual(1, report["terminal_retention_deferred"])
            self.assertEqual(0, report["deleted_files"])
            self.assertEqual([terminal], json.loads(jobs.read_text(encoding="utf-8"))["jobs"])
            self.assertEqual(before, (external.read_bytes(), external.stat().st_ino, external.stat().st_mtime_ns))

    def test_cleanup_succeeds_when_no_terminal_retention_is_due(self) -> None:
        data = {"jobs": [{"id": "recent", "status": "completed", "created_at": "2025-12-31T00:00:00Z"}]}

        @contextlib.contextmanager
        def locked_jobs(*, writeback: bool = True):
            yield data

        with (
            patch.object(bg, "locked_jobs", side_effect=locked_jobs),
            patch.object(bg, "reconcile_lease_jobs", return_value={}),
            patch.object(bg, "now_utc", return_value=NOW),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = bg.command_cleanup(argparse.Namespace(retention_days=14, max_terminal=200, json=True))
        self.assertEqual(0, result)
        self.assertEqual(1, len(data["jobs"]))

    def test_cleanup_help_states_that_retention_is_deferred(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            bg.build_parser().parse_args(["cleanup", "--help"])
        self.assertEqual(0, caught.exception.code)
        self.assertIn("terminal records and artifacts are preserved", output.getvalue().lower())
        self.assertIn("deferred-candidate count", output.getvalue().lower())

    def test_implicit_cleanup_preserves_terminal_record_during_enqueue_and_reserve(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bg-implicit-retention-") as raw:
            root = Path(raw)
            sentinel = root / "external.log"
            sentinel.write_bytes(b"synthetic external artifact\n")
            terminal = {
                "id": "old", "status": "completed", "created_at": "2000-01-01T00:00:00Z",
                "log_path": str(sentinel),
            }
            data = {"jobs": [copy.deepcopy(terminal)]}

            @contextlib.contextmanager
            def locked_jobs(*, writeback: bool = True):
                yield data

            with (
                patch.object(bg, "locked_jobs", side_effect=locked_jobs),
                patch.object(bg, "now_utc", return_value=NOW),
                patch.object(bg, "RUNS_DIR", root / "runs"),
                patch.object(bg, "process_start_fingerprint", return_value="a" * 64),
                patch.object(bg, "terminate_process", side_effect=AssertionError("must not signal")),
                patch.object(Path, "unlink", autospec=True) as unlink,
            ):
                enqueued = bg.enqueue_job(
                    ["synthetic-command"], cwd_value=str(root), labels=[],
                    timeout_seconds=5, stale_after_seconds=10,
                )
                self.assertIsNotNone(enqueued)
                _, _, report = bg._reserve_jobs(job_id="no-such-job", max_jobs=1, lease_max_concurrency=1)
            unlink.assert_not_called()
            self.assertIn(terminal, data["jobs"])
            self.assertEqual(1, report["terminal_retention_deferred"])
            self.assertEqual(b"synthetic external artifact\n", sentinel.read_bytes())

    def test_stale_processing_still_quarantines_unverified_jobs(self) -> None:
        job = {
            "id": "stale", "status": "running", "started_at": "2000-01-01T00:00:00Z",
            "pid": 987654, "pgid": 987654, "process_start_fingerprint": None,
        }
        with (
            patch.object(bg, "now_utc", return_value=NOW),
            patch.object(bg, "terminate_process", side_effect=AssertionError("must not signal")),
        ):
            report = bg.cleanup_jobs({"jobs": [job]})
        self.assertEqual("reconciling", job["status"])
        self.assertEqual(987654, job["pid"])
        self.assertEqual(1, report["stale_reconciling"])
        self.assertEqual("deferred", report["terminal_retention_mode"])

    def test_stale_job_that_becomes_terminal_is_not_pruned(self) -> None:
        job = {
            "id": "stale", "status": "running", "started_at": "2000-01-01T00:00:00Z",
            "pid": 987654, "pgid": 987654, "process_start_fingerprint": "a" * 64,
        }
        data = {"jobs": [job]}
        with (
            patch.object(bg, "now_utc", return_value=NOW),
            patch.object(bg, "terminate_process", return_value="terminated") as terminate,
            patch.object(Path, "unlink", autospec=True) as unlink,
        ):
            report = bg.cleanup_jobs(data, retention_days=0, max_terminal=0)
        terminate.assert_called_once()
        unlink.assert_not_called()
        self.assertEqual("cancelled", job["status"])
        self.assertEqual([job], data["jobs"])
        self.assertEqual(1, report["terminal_retention_deferred"])
        self.assertEqual(0, report["pruned"])


if __name__ == "__main__":
    unittest.main()
