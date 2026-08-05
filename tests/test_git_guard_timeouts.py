from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import completion_gates
import hotfix_runtime
import release_train_command
import release_train_engine
import worktree_helper_command
from bounded_subprocess import (
    OPERATION_CLASSES,
    BoundedCommandError,
    BoundedCommandFailure,
)


def bounded_error(operation: str, suffix: str = "timeout") -> BoundedCommandError:
    return BoundedCommandError(
        BoundedCommandFailure(
            reason_code=f"{operation}_{suffix}",
            operation=operation,
            command_class=OPERATION_CLASSES[operation],
            timeout_seconds=1.0 if suffix == "timeout" else None,
            command=("git",),
            detail="injected bounded failure",
            stdout="",
            stderr="",
        )
    )


def completed(
    returncode: int,
    *,
    stdout: str | bytes = "",
    stderr: str | bytes = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], returncode, stdout, stderr)


class GitGuardTimeoutTest(unittest.TestCase):
    def test_worktree_helper_supports_isolated_runpy_loading(self) -> None:
        script = (
            "import runpy; "
            f"runpy.run_path({str(SCRIPTS_DIR / 'worktree_helper_command.py')!r}, "
            "run_name='worktree_helper_command_test')"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_worktree_probes_fail_closed_with_cli_reason(self) -> None:
        diagnostics: list[str] = []
        with patch.object(
            worktree_helper_command,
            "run_bounded",
            side_effect=bounded_error("worktree_git_branch_name_check"),
        ):
            self.assertFalse(
                worktree_helper_command.is_valid_git_branch_name(
                    "safe-branch",
                    diagnostics,
                )
            )
        self.assertEqual(["worktree_git_branch_name_check_timeout"], diagnostics)

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(
                    worktree_helper_command,
                    "run_bounded",
                    side_effect=bounded_error("worktree_git_repository_probe"),
                ),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = worktree_helper_command.command_maintenance(
                    [
                        "--directory",
                        tmp,
                        "--command",
                        "printf 'blocked'",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
        self.assertEqual(1, code)
        self.assertEqual("worktree_git_repository_probe_timeout", payload["reason_code"])
        self.assertEqual("ERROR", payload["result"])

    def test_completion_fingerprint_reports_timeout_and_nonzero_fails_closed(self) -> None:
        diagnostics: list[str] = []
        with patch.object(
            completion_gates,
            "run_bounded",
            side_effect=bounded_error("completion_git_repo_root"),
        ):
            self.assertIsNone(
                completion_gates.git_state_fingerprint(
                    Path("/tmp/repo"), diagnostics=diagnostics
                )
            )
        self.assertEqual(["completion_git_repo_root_timeout"], diagnostics)

        with patch.object(
            completion_gates,
            "run_bounded",
            side_effect=bounded_error("completion_git_repo_root"),
        ):
            payload = completion_gates.evaluate_completion_gates(
                {"required_validation": ["test"]},
                directory=Path("/tmp/repo"),
            )
        self.assertEqual("FAIL", payload["result"])
        self.assertEqual(["completion_git_repo_root_timeout"], payload["diagnostics"])

        with patch.object(
            completion_gates,
            "run_bounded",
            return_value=completed(2, stdout=b"", stderr=b"failure"),
        ):
            diagnostics = []
            self.assertIsNone(
                completion_gates.git_state_fingerprint(
                    Path("/tmp/repo"), diagnostics=diagnostics
                )
            )
        self.assertEqual([], diagnostics)

    def test_release_upstream_absence_differs_from_probe_failures(self) -> None:
        with patch.object(
            release_train_engine,
            "run_bounded",
            return_value=completed(1),
        ):
            diagnostics: list[str] = []
            self.assertFalse(
                release_train_engine.branch_behind_remote(
                    Path("/tmp/repo"), "main", diagnostics
                )
            )
        self.assertEqual([], diagnostics)

        with patch.object(
            release_train_engine,
            "run_bounded",
            side_effect=[completed(0, stdout="origin/main"), completed(2)],
        ):
            diagnostics = []
            self.assertFalse(
                release_train_engine.branch_behind_remote(
                    Path("/tmp/repo"), "main", diagnostics
                )
            )
        self.assertEqual(["release_git_divergence_failed"], diagnostics)

        with patch.object(
            release_train_engine,
            "run_bounded",
            side_effect=[completed(0, stdout="origin/main"), completed(0, stdout="bad")],
        ):
            diagnostics = []
            self.assertFalse(
                release_train_engine.branch_behind_remote(
                    Path("/tmp/repo"), "main", diagnostics
                )
            )
        self.assertEqual(["release_git_divergence_invalid"], diagnostics)

        with patch.object(
            release_train_engine,
            "run_bounded",
            side_effect=bounded_error("release_git_upstream_probe"),
        ):
            diagnostics = []
            self.assertFalse(
                release_train_engine.branch_behind_remote(
                    Path("/tmp/repo"), "main", diagnostics
                )
            )
        self.assertEqual(["release_git_upstream_probe_timeout"], diagnostics)

    def test_release_arbitrary_range_is_unbounded_but_fallback_is_bounded(self) -> None:
        with (
            patch.object(
                release_train_engine,
                "run_git",
                return_value=(0, "abc change", ""),
            ) as unbounded,
            patch.object(release_train_engine, "run_git_probe") as bounded,
        ):
            payload = release_train_engine.draft_release_notes(
                Path("/tmp/repo"),
                base_tag="v1.0.0",
                head="HEAD",
            )
        self.assertEqual("PASS", payload["result"])
        unbounded.assert_called_once_with(
            Path("/tmp/repo"), ["log", "--oneline", "v1.0.0..HEAD"]
        )
        bounded.assert_not_called()

        with (
            patch.object(release_train_engine, "latest_tag", return_value=None),
            patch.object(
                release_train_engine,
                "run_git_probe",
                return_value=(0, "abc change", ""),
            ) as bounded,
        ):
            payload = release_train_engine.draft_release_notes(
                Path("/tmp/repo"),
                base_tag=None,
                head="HEAD",
            )
        self.assertEqual("PASS", payload["result"])
        self.assertEqual(
            "release_git_fallback_log",
            bounded.call_args.kwargs["operation"],
        )

    def test_release_local_tag_probe_distinguishes_expected_absence(self) -> None:
        with patch.object(
            release_train_command,
            "run_bounded",
            return_value=completed(1),
        ):
            self.assertEqual(
                (False, None),
                release_train_command._local_tag_exists(
                    Path("/tmp/repo"), "v1.2.3"
                ),
            )
        with patch.object(
            release_train_command,
            "run_bounded",
            return_value=completed(128),
        ):
            self.assertEqual(
                (False, "release_git_local_tag_failed"),
                release_train_command._local_tag_exists(
                    Path("/tmp/repo"), "v1.2.3"
                ),
            )
        with patch.object(
            release_train_command,
            "run_bounded",
            side_effect=bounded_error("release_git_local_tag"),
        ), self.assertRaises(BoundedCommandError) as raised:
            release_train_command._local_tag_exists(
                Path("/tmp/repo"), "v1.2.3"
            )
        self.assertEqual("release_git_local_tag_timeout", raised.exception.reason_code)

    def test_release_publish_blocks_on_local_tag_probe_timeout(self) -> None:
        with (
            patch.object(
                release_train_command,
                "evaluate_prepare",
                return_value={"ready": True, "reason_codes": [], "remediation": []},
            ),
            patch.object(
                release_train_command,
                "_local_tag_exists",
                side_effect=bounded_error("release_git_local_tag"),
            ),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = release_train_command.command_publish(
                ["--version", "1.2.3", "--create-tag", "--dry-run", "--json"]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, code)
        self.assertEqual("FAIL", payload["result"])
        self.assertEqual(
            ["release_git_local_tag_timeout"], payload["reason_codes"]
        )

    def test_release_status_preserves_fallbacks_with_timeout_diagnostics(self) -> None:
        def fail_for_operation(_command, *, operation, **_kwargs):
            raise bounded_error(operation)

        with (
            patch.object(
                release_train_engine,
                "run_bounded",
                side_effect=fail_for_operation,
            ),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = release_train_command.command_status(
                ["--repo-root", "/tmp/repo", "--json"]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, code)
        self.assertEqual("PASS", payload["result"])
        self.assertIsNone(payload["branch"])
        self.assertIsNone(payload["latest_tag"])
        self.assertFalse(payload["clean_worktree"])
        self.assertEqual(
            [
                "release_git_current_branch_timeout",
                "release_git_latest_tag_timeout",
                "release_git_worktree_status_timeout",
            ],
            payload["diagnostics"],
        )

    def test_hotfix_start_exposes_git_timeout_reasons(self) -> None:
        def fail_for_operation(_command, *, operation, **_kwargs):
            raise bounded_error(operation)

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(
                    hotfix_runtime,
                    "run_bounded",
                    side_effect=fail_for_operation,
                ),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = hotfix_runtime.command_start(
                    [
                        "--incident-id",
                        "incident-1",
                        "--scope",
                        "patch",
                        "--impact",
                        "sev2",
                        "--json",
                    ],
                    Path(tmp) / "config.json",
                    Path(tmp),
                )
            payload = json.loads(stdout.getvalue())
        self.assertEqual(1, code)
        self.assertIn("hotfix_git_current_branch_timeout", payload["reason_codes"])
        self.assertIn("hotfix_git_worktree_status_timeout", payload["reason_codes"])
        self.assertIn("dirty_worktree", payload["reason_codes"])


if __name__ == "__main__":
    unittest.main()
