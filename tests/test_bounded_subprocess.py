from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bounded_subprocess import (
    COMMAND_CLASS_POLICIES,
    OPERATION_CLASSES,
    BoundedCommandError,
    resolve_timeout_seconds,
    run_bounded,
)


class BoundedSubprocessTest(unittest.TestCase):
    def test_registry_uses_known_command_classes(self) -> None:
        self.assertEqual(32, len(OPERATION_CLASSES))
        self.assertEqual(
            set(OPERATION_CLASSES.values()),
            set(COMMAND_CLASS_POLICIES),
        )
        for operation in OPERATION_CLASSES:
            self.assertRegex(operation, r"^[a-z][a-z0-9_]*$")

    def test_defaults_and_valid_overrides_are_isolated_by_class(self) -> None:
        environment_keys = {
            policy.environment_key for policy in COMMAND_CLASS_POLICIES.values()
        }
        with patch.dict(os.environ, {}, clear=False):
            for key in environment_keys:
                os.environ.pop(key, None)
            for command_class, policy in COMMAND_CLASS_POLICIES.items():
                operation = next(
                    name
                    for name, registered_class in OPERATION_CLASSES.items()
                    if registered_class == command_class
                )
                self.assertEqual(
                    (command_class, policy.default_seconds),
                    resolve_timeout_seconds(operation),
                )
                with patch.dict(
                    os.environ,
                    {policy.environment_key: str(policy.maximum_seconds)},
                ):
                    self.assertEqual(
                        (command_class, policy.maximum_seconds),
                        resolve_timeout_seconds(operation),
                    )

    def test_every_class_rejects_invalid_or_over_cap_overrides(self) -> None:
        invalid_values = ("", "nope", "0", "-1", "nan", "inf")
        for command_class, policy in COMMAND_CLASS_POLICIES.items():
            operation = next(
                name
                for name, registered_class in OPERATION_CLASSES.items()
                if registered_class == command_class
            )
            for raw in (*invalid_values, str(policy.maximum_seconds + 0.1)):
                with self.subTest(command_class=command_class, raw=raw):
                    with (
                        patch.dict(
                            os.environ,
                            {policy.environment_key: raw},
                        ),
                        self.assertRaises(BoundedCommandError) as raised,
                    ):
                        resolve_timeout_seconds(operation)
                    self.assertEqual(
                        f"{operation}_timeout_invalid", raised.exception.reason_code
                    )
                    self.assertEqual(command_class, raised.exception.command_class)
                    self.assertIsNone(raised.exception.timeout_seconds)

    def test_success_and_nonzero_return_completed_processes(self) -> None:
        success = run_bounded(
            [sys.executable, "-c", "print('ok')"],
            operation="worktree_git_repository_probe",
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, success.returncode)
        self.assertEqual("ok", success.stdout.strip())

        nonzero = run_bounded(
            [sys.executable, "-c", "raise SystemExit(7)"],
            operation="worktree_git_repository_probe",
            capture_output=True,
            text=True,
        )
        self.assertEqual(7, nonzero.returncode)

    def test_missing_and_launch_errors_are_distinct(self) -> None:
        missing_name = f"missing-bounded-command-{os.getpid()}"
        with self.assertRaises(BoundedCommandError) as raised:
            run_bounded(
                [missing_name],
                operation="ship_github_version",
                capture_output=True,
                text=True,
            )
        self.assertEqual("ship_github_version_command_missing", raised.exception.reason_code)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-executable"
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            with self.assertRaises(BoundedCommandError) as raised:
                run_bounded(
                    [str(path)],
                    operation="ship_github_version",
                    capture_output=True,
                    text=True,
                )
        self.assertEqual("ship_github_version_command_error", raised.exception.reason_code)

        with tempfile.TemporaryDirectory() as tmp:
            missing_cwd = Path(tmp) / "missing-directory"
            with self.assertRaises(BoundedCommandError) as raised:
                run_bounded(
                    [sys.executable, "-c", "pass"],
                    operation="ship_github_version",
                    cwd=missing_cwd,
                )
        self.assertEqual("ship_github_version_command_error", raised.exception.reason_code)

        with (
            patch(
                "bounded_subprocess.subprocess.run",
                side_effect=ValueError("invalid subprocess launch"),
            ),
            self.assertRaises(BoundedCommandError) as raised,
        ):
            run_bounded(
                [sys.executable, "-c", "pass"],
                operation="ship_github_version",
            )
        self.assertEqual("ship_github_version_command_error", raised.exception.reason_code)

    def test_helper_owns_check_shell_and_timeout(self) -> None:
        for key, value in (("check", True), ("shell", True), ("timeout", 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                run_bounded(
                    [sys.executable, "-c", "pass"],
                    operation="worktree_git_repository_probe",
                    **{key: value},
                )

    def test_timeout_kills_and_reaps_direct_child(self) -> None:
        policy = COMMAND_CLASS_POLICIES["git_probe"]
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "pid"
            script = (
                "import os, pathlib, sys, time; "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
                "time.sleep(60)"
            )
            started = time.monotonic()
            with (
                patch.dict(os.environ, {policy.environment_key: "0.5"}),
                self.assertRaises(BoundedCommandError) as raised,
            ):
                run_bounded(
                    [sys.executable, "-c", script, str(pid_path)],
                    operation="worktree_git_repository_probe",
                    capture_output=True,
                    text=True,
                )
            elapsed = time.monotonic() - started
            self.assertEqual(
                "worktree_git_repository_probe_timeout",
                raised.exception.reason_code,
            )
            self.assertLess(elapsed, 3.0)
            self.assertTrue(pid_path.exists())
            pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_invalid_configuration_does_not_launch(self) -> None:
        policy = COMMAND_CLASS_POLICIES["git_probe"]
        with (
            patch.dict(os.environ, {policy.environment_key: "invalid"}),
            patch("bounded_subprocess.subprocess.run") as run,
            self.assertRaises(BoundedCommandError),
        ):
            run_bounded(
                [sys.executable, "-c", "pass"],
                operation="worktree_git_repository_probe",
            )
        run.assert_not_called()

    def test_unknown_operation_fails_before_launch(self) -> None:
        with (
            patch("bounded_subprocess.subprocess.run") as run,
            self.assertRaises(ValueError),
        ):
            run_bounded([sys.executable, "-c", "pass"], operation="unknown")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
