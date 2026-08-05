from __future__ import annotations

import argparse
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

import hotfix_command
import hygiene_drift_check
import knowledge_capture_pipeline
import pages_readiness_check
import session_digest
import shared_memory_runtime
import ship_command
import update_wave_completion_doc
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
            command=("gh" if "github" in operation else "git",),
            detail="injected bounded failure",
            stdout="",
            stderr="",
        )
    )


class GitMetadataTimeoutTest(unittest.TestCase):
    def test_shared_memory_fallback_preserves_shape_and_records_diagnostic(self) -> None:
        def fail_for_operation(_command, *, operation, **_kwargs):
            raise bounded_error(operation)

        diagnostics: list[str] = []
        cwd = Path("/tmp/shared-memory-fallback")
        with patch.object(
            shared_memory_runtime,
            "run_bounded",
            side_effect=fail_for_operation,
        ):
            self.assertEqual(str(cwd), shared_memory_runtime._repo_root(cwd, diagnostics))
        self.assertEqual(["shared_memory_git_repo_root_timeout"], diagnostics)

        diagnostics = []
        with patch.object(
            shared_memory_runtime,
            "run_bounded",
            side_effect=fail_for_operation,
        ):
            self.assertEqual(
                str(cwd), shared_memory_runtime._repo_identity(cwd, diagnostics)
            )
        self.assertEqual(
            [
                "shared_memory_git_repo_identity_timeout",
                "shared_memory_git_repo_root_timeout",
            ],
            diagnostics,
        )

    def test_session_git_snapshot_keeps_fields_and_adds_diagnostics(self) -> None:
        def fail_for_operation(_command, *, operation, **_kwargs):
            raise bounded_error(operation)

        with patch.object(
            session_digest,
            "run_bounded",
            side_effect=fail_for_operation,
        ):
            payload = session_digest.collect_git_snapshot(Path("/tmp/repo"))
        self.assertIsNone(payload["branch"])
        self.assertEqual(0, payload["status_count"])
        self.assertEqual([], payload["status_preview"])
        self.assertIsNone(payload["branch_header"])
        self.assertEqual(
            [
                "session_git_branch_timeout",
                "session_git_status_timeout",
                "session_git_ahead_behind_timeout",
            ],
            payload["diagnostics"],
        )

    def test_knowledge_collector_keeps_empty_fallback_with_diagnostic(self) -> None:
        diagnostics: list[str] = []
        with patch.object(
            knowledge_capture_pipeline,
            "run_bounded",
            side_effect=bounded_error("knowledge_git_merge_log"),
        ):
            signals = knowledge_capture_pipeline.collect_pr_signals(
                Path("/tmp/repo"),
                diagnostics=diagnostics,
            )
        self.assertEqual([], signals)
        self.assertEqual(["knowledge_git_merge_log_timeout"], diagnostics)

    def test_hotfix_followup_lookup_returns_exact_reason(self) -> None:
        with patch.object(
            hotfix_command,
            "run_bounded",
            side_effect=bounded_error("hotfix_github_followup_lookup"),
        ):
            self.assertEqual(
                (None, "hotfix_github_followup_lookup_timeout"),
                hotfix_command.resolve_followup_url("123"),
            )

    def test_ship_probe_failures_are_diagnostic_and_block_create(self) -> None:
        with patch.object(
            ship_command,
            "run_bounded",
            side_effect=bounded_error("ship_github_version"),
        ):
            health = ship_command._gh_health()
        self.assertFalse(health["available"])
        self.assertEqual("ship_github_version_timeout", health["reason_code"])

        with (
            patch.object(
                ship_command,
                "run_bounded",
                side_effect=bounded_error("ship_git_repo_root"),
            ),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = ship_command._command_create_pr(
                ["--version", "1.2.3", "--confirm"],
                True,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, code)
        self.assertEqual("FAIL", payload["result"])
        self.assertEqual(["ship_git_repo_root_timeout"], payload["reason_codes"])

        nonzero = subprocess.CompletedProcess(["git"], 2, "", "not a repository")
        with (
            patch.object(ship_command, "run_bounded", return_value=nonzero),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = ship_command._command_create_pr(
                ["--version", "1.2.3", "--confirm"],
                True,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, code)
        self.assertEqual(["ship_git_repo_root_failed"], payload["reason_codes"])

    def test_pages_cli_and_fetch_expose_timeout_reason(self) -> None:
        with patch.object(
            pages_readiness_check,
            "run_bounded",
            side_effect=bounded_error("pages_github_metadata"),
        ):
            payload, detail, status, reason = pages_readiness_check.fetch_pages_payload(
                Path("/tmp/repo"), "owner/repo"
            )
        self.assertIsNone(payload)
        self.assertIsNone(status)
        self.assertIn("injected bounded failure", detail or "")
        self.assertEqual("pages_github_metadata_timeout", reason)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "docs-automation.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "actions/configure-pages@v1\nactions/deploy-pages@v1\ndocs/pages\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(repo_root=root, repo=None, json=True)
            with (
                patch.object(pages_readiness_check, "parse_args", return_value=args),
                patch.object(
                    pages_readiness_check,
                    "run_bounded",
                    side_effect=bounded_error("pages_github_repo_lookup"),
                ),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = pages_readiness_check.main()
            cli_payload = json.loads(stdout.getvalue())
        self.assertEqual(1, code)
        self.assertEqual(
            ["pages_github_repo_lookup_timeout"], cli_payload["reason_codes"]
        )

    def test_wave_generation_timeout_is_structured_and_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "docs" / "plan" / "v2.2-flow-wave-plan.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan\n", encoding="utf-8")
            output = plan.with_name("v2.2-flow-wave-completion.md")
            with (
                patch.object(
                    update_wave_completion_doc,
                    "run_bounded",
                    side_effect=bounded_error("wave_github_pr_metadata"),
                ),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = update_wave_completion_doc.main(
                    [
                        "--repo-root",
                        str(root),
                        "--wave",
                        "v2.2",
                        "--pr",
                        "1",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertFalse(output.exists())
        self.assertEqual(1, code)
        self.assertEqual(["wave_github_pr_metadata_timeout"], payload["reason_codes"])

    def test_hygiene_metadata_timeout_remains_a_warning(self) -> None:
        with patch.object(
            hygiene_drift_check,
            "run_bounded",
            side_effect=bounded_error("hygiene_github_merged_pr_metadata"),
        ):
            labels, titles, warning = hygiene_drift_check._fetch_recent_pr_metadata(
                Path("/tmp/repo")
            )
        self.assertEqual(set(), labels)
        self.assertEqual([], titles)
        self.assertIn("hygiene_github_merged_pr_metadata_timeout", warning or "")

    def test_nonzero_metadata_commands_preserve_existing_fallbacks(self) -> None:
        nonzero = subprocess.CompletedProcess(["gh"], 1, "", "failed")
        with patch.object(hotfix_command, "run_bounded", return_value=nonzero):
            self.assertEqual(
                (None, "followup_lookup_failed"),
                hotfix_command.resolve_followup_url("123"),
            )


if __name__ == "__main__":
    unittest.main()
