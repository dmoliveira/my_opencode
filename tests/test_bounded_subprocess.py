from __future__ import annotations

import ctypes
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bounded_subprocess
from bounded_subprocess import (
    COMMAND_CLASS_POLICIES,
    OPERATION_CLASSES,
    BoundedCommandError,
    resolve_timeout_seconds,
    run_bounded,
)


class BoundedSubprocessTest(unittest.TestCase):
    def _assert_pid_terminated(self, pid: int) -> None:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if os.name == "nt":
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    return
                exit_code = ctypes.c_ulong()
                try:
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        if exit_code.value != 259:
                            return
                finally:
                    kernel32.CloseHandle(handle)
                time.sleep(0.05)
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 87:
                    return
                raise
            time.sleep(0.05)
        self.fail(f"process {pid} is still running")

    class _FakeProcess:
        pid = 123
        _handle = 456

        def __init__(self) -> None:
            self.killed = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self, **_kwargs):
            return 1

    def _fake_kernel32(self, *, snapshot=20, resume=0, assign=True):
        calls = []
        assign_ok = assign

        def create_job(_security, _name):
            calls.append("create_job")
            return 10

        def assign(_job, _process):
            calls.append("assign")
            return assign_ok

        def create_snapshot(_flags, _pid):
            calls.append("snapshot")
            return snapshot

        def thread_first(_snapshot, entry):
            calls.append("thread_first")
            entry._obj.th32OwnerProcessID = 123
            entry._obj.th32ThreadID = 30
            return True

        def open_thread(_access, _inherit, _thread_id):
            calls.append("open_thread")
            return 40

        def resume_thread(_thread):
            calls.append("resume")
            return resume

        def close_handle(handle):
            calls.append(("close", handle))
            return True

        def terminate_job(_job, _code):
            calls.append("terminate")
            return True

        kernel = type("FakeKernel", (), {})()
        kernel.CreateJobObjectW = Mock(side_effect=create_job)
        kernel.AssignProcessToJobObject = Mock(side_effect=assign)
        kernel.CreateToolhelp32Snapshot = Mock(side_effect=create_snapshot)
        kernel.Thread32First = Mock(side_effect=thread_first)
        kernel.Thread32Next = Mock(return_value=False)
        kernel.OpenThread = Mock(side_effect=open_thread)
        kernel.ResumeThread = Mock(side_effect=resume_thread)
        kernel.CloseHandle = Mock(side_effect=close_handle)
        kernel.TerminateJobObject = Mock(side_effect=terminate_job)
        return kernel, calls

    def test_windows_job_assignment_resumes_only_after_assignment(self) -> None:
        fake_process = self._FakeProcess()
        kernel, calls = self._fake_kernel32()
        with (
            patch.object(os, "name", "nt"),
            patch("ctypes.WinDLL", return_value=kernel, create=True),
        ):
            job = bounded_subprocess._attach_windows_job(fake_process)
        self.assertIsNotNone(job)
        self.assertLess(calls.index("assign"), calls.index("resume"))
        job.close()
        self.assertIn(("close", 10), calls)

    def test_windows_job_setup_failures_close_handles(self) -> None:
        for kwargs, expected in (
            ({"snapshot": ctypes.c_void_p(-1).value}, "snapshot"),
            ({"resume": 0xFFFFFFFF}, "resume"),
            ({"assign": False}, "assign"),
        ):
            with self.subTest(expected=expected):
                fake_process = self._FakeProcess()
                kernel, calls = self._fake_kernel32(**kwargs)
                with (
                    patch.object(os, "name", "nt"),
                    patch("ctypes.WinDLL", return_value=kernel, create=True),
                    self.assertRaises(bounded_subprocess._WindowsJobError),
                ):
                    bounded_subprocess._attach_windows_job(fake_process)
                self.assertIn(("close", 10), calls)

    def test_windows_job_termination_falls_back_to_taskkill(self) -> None:
        fake_process = self._FakeProcess()
        job = Mock()
        job.terminate.side_effect = OSError("job termination failed")
        with (
            patch.object(os, "name", "nt"),
            patch("bounded_subprocess.subprocess.run") as taskkill,
        ):
            bounded_subprocess._terminate_process_tree(fake_process, job)
        taskkill.assert_called_once()
        self.assertTrue(fake_process.killed)

    def test_registry_uses_known_command_classes(self) -> None:
        self.assertEqual(35, len(OPERATION_CLASSES))
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

    def test_input_matches_subprocess_run_semantics(self) -> None:
        text = run_bounded(
            [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
            operation="worktree_git_repository_probe",
            input="text input",
            capture_output=True,
            text=True,
        )
        self.assertEqual("text input\n", text.stdout)
        binary = run_bounded(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
            ],
            operation="worktree_git_repository_probe",
            input=b"binary input",
            capture_output=True,
        )
        self.assertEqual(b"binary input", binary.stdout)
        with self.assertRaises(ValueError):
            run_bounded(
                [sys.executable, "-c", "pass"],
                operation="worktree_git_repository_probe",
                input=b"input",
                stdin=subprocess.PIPE,
            )

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
                "bounded_subprocess.subprocess.Popen",
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
            self._assert_pid_terminated(pid)

    def test_timeout_kills_descendants_after_leader_exit(self) -> None:
        policy = COMMAND_CLASS_POLICIES["git_probe"]
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_path = Path(tmp) / "child-pid"
            child_script = (
                "import os, pathlib, sys, time; "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
                "time.sleep(60)"
            )
            script = (
                "import pathlib, subprocess, sys, os, time; "
                "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]], "
                "stdout=sys.stdout, stderr=sys.stderr); "
                "deadline = time.monotonic() + 2; "
                "path = pathlib.Path(sys.argv[1]); "
                "exec(\"while not path.exists() and time.monotonic() < deadline:\\n"
                "    time.sleep(.01)\"); "
                "os._exit(0)"
            )
            started = time.monotonic()
            with (
                patch.dict(os.environ, {policy.environment_key: "2.0"}),
                self.assertRaises(BoundedCommandError),
            ):
                run_bounded(
                    [sys.executable, "-c", script, str(child_pid_path), child_script],
                    operation="worktree_git_repository_probe",
                    capture_output=True,
                    text=True,
                )
            self.assertLess(time.monotonic() - started, 5.0)
            self.assertTrue(child_pid_path.exists())
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                try:
                    proc_stat = Path(f"/proc/{child_pid}/stat")
                    if proc_stat.exists() and proc_stat.read_text().split()[2] == "Z":
                        break
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                except OSError as exc:
                    if os.name == "nt" and getattr(exc, "winerror", None) == 87:
                        break
                    raise
                time.sleep(0.05)
            else:
                self.fail("bounded timeout left a descendant process running")

    def test_invalid_configuration_does_not_launch(self) -> None:
        policy = COMMAND_CLASS_POLICIES["git_probe"]
        with (
            patch.dict(os.environ, {policy.environment_key: "invalid"}),
                patch("bounded_subprocess.subprocess.Popen") as run,
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
