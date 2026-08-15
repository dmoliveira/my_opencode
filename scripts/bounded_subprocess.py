from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandClassPolicy:
    environment_key: str
    default_seconds: float
    maximum_seconds: float


COMMAND_CLASS_POLICIES: dict[str, CommandClassPolicy] = {
    "git_probe": CommandClassPolicy(
        "MY_OPENCODE_GIT_PROBE_TIMEOUT_SECONDS", 5.0, 30.0
    ),
    "git_status": CommandClassPolicy(
        "MY_OPENCODE_GIT_STATUS_TIMEOUT_SECONDS", 15.0, 60.0
    ),
    "git_metadata": CommandClassPolicy(
        "MY_OPENCODE_GIT_METADATA_TIMEOUT_SECONDS", 20.0, 60.0
    ),
    "github_probe": CommandClassPolicy(
        "MY_OPENCODE_GITHUB_PROBE_TIMEOUT_SECONDS", 10.0, 30.0
    ),
    "github_metadata": CommandClassPolicy(
        "MY_OPENCODE_GITHUB_METADATA_TIMEOUT_SECONDS", 30.0, 120.0
    ),
    "codememory_probe": CommandClassPolicy(
        "MY_OPENCODE_CODEMEMORY_PROBE_TIMEOUT_SECONDS", 10.0, 30.0
    ),
    "codememory_lease_probe": CommandClassPolicy(
        "MY_OPENCODE_CODEMEMORY_LEASE_PROBE_TIMEOUT_SECONDS", 2.0, 2.0
    ),
    "codememory_mutation": CommandClassPolicy(
        "MY_OPENCODE_CODEMEMORY_MUTATION_TIMEOUT_SECONDS", 30.0, 120.0
    ),
}


OPERATION_CLASSES: dict[str, str] = {
    "worktree_git_branch_name_check": "git_probe",
    "worktree_git_repository_probe": "git_probe",
    "worktree_git_head_probe": "git_probe",
    "shared_memory_git_repo_root": "git_probe",
    "shared_memory_git_repo_identity": "git_probe",
    "session_git_branch": "git_probe",
    "session_git_status": "git_status",
    "session_git_ahead_behind": "git_status",
    "knowledge_git_merge_log": "git_metadata",
    "completion_git_repo_root": "git_probe",
    "completion_git_head": "git_probe",
    "completion_git_staged_diff": "git_status",
    "completion_git_tracked_diff": "git_status",
    "completion_git_untracked_files": "git_status",
    "release_git_latest_tag": "git_metadata",
    "release_git_current_branch": "git_probe",
    "release_git_worktree_status": "git_status",
    "release_git_upstream_probe": "git_probe",
    "release_git_divergence": "git_status",
    "release_git_fallback_log": "git_metadata",
    "release_git_local_tag": "git_probe",
    "hotfix_git_current_branch": "git_probe",
    "hotfix_git_worktree_status": "git_status",
    "hotfix_git_head": "git_probe",
    "hotfix_github_followup_lookup": "github_metadata",
    "ship_git_repo_root": "git_probe",
    "ship_github_version": "github_probe",
    "ship_git_current_branch": "git_probe",
    "pages_github_repo_lookup": "github_metadata",
    "pages_github_metadata": "github_metadata",
    "wave_github_pr_metadata": "github_metadata",
    "hygiene_github_merged_pr_metadata": "github_metadata",
    "intent_codememory_doctor": "codememory_probe",
    "intent_codememory_find": "codememory_probe",
    "intent_codememory_apply": "codememory_mutation",
    "task_projection_codememory_list": "codememory_probe",
    "task_projection_codememory_get": "codememory_probe",
    "task_lease_codememory_doctor": "codememory_lease_probe",
    "task_lease_codememory_current": "codememory_lease_probe",
    "task_lease_codememory_get": "codememory_lease_probe",
}


_OPERATION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_FORBIDDEN_RUN_OPTIONS = frozenset(
    {"check", "creationflags", "shell", "start_new_session", "timeout"}
)


class _WindowsJob:
    def __init__(self, handle: Any, kernel32: Any) -> None:
        self.handle = handle
        self.kernel32 = kernel32

    def terminate(self) -> None:
        if not self.kernel32.TerminateJobObject(self.handle, 1):
            raise OSError("TerminateJobObject failed")

    def close(self) -> None:
        if self.handle is not None:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


class _WindowsJobError(RuntimeError):
    pass


def _attach_windows_job(process: subprocess.Popen[Any]) -> _WindowsJob | None:
    if os.name != "nt":
        return None
    handle = None
    kernel32 = None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise _WindowsJobError("CreateJobObjectW failed")
        if not kernel32.AssignProcessToJobObject(handle, wintypes.HANDLE(process._handle)):
            raise _WindowsJobError("AssignProcessToJobObject failed")

        class _ThreadEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if not snapshot or snapshot == invalid_handle:
            raise _WindowsJobError("CreateToolhelp32Snapshot failed")
        thread = None
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process.pid:
                    thread = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                    break
                found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
            if not thread or kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                raise _WindowsJobError("ResumeThread failed")
        finally:
            if thread:
                kernel32.CloseHandle(thread)
            kernel32.CloseHandle(snapshot)
        return _WindowsJob(handle, kernel32)
    except _WindowsJobError:
        if handle:
            try:
                kernel32.TerminateJobObject(handle, 1)
            finally:
                kernel32.CloseHandle(handle)
        raise
    except Exception as exc:
        if handle and kernel32 is not None:
            try:
                kernel32.TerminateJobObject(handle, 1)
            finally:
                kernel32.CloseHandle(handle)
        raise _WindowsJobError("Windows Job Object setup failed") from exc


def _terminate_process_tree(
    process: subprocess.Popen[Any], job: _WindowsJob | None
) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif job is not None:
            try:
                job.terminate()
            except OSError:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
        else:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=5,
            )
    except (OSError, ProcessLookupError, subprocess.SubprocessError):
        pass
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass


def _reap_process(process: subprocess.Popen[Any]) -> tuple[Any, Any]:
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return (
            exc.stdout,
            exc.stderr,
        )


def _communicate_limited(
    process: subprocess.Popen[Any],
    job: _WindowsJob | None,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
    text_mode: bool,
) -> tuple[Any, Any, str | None]:
    if process.stdout is None or process.stderr is None:
        raise ValueError("bounded output capture requires stdout and stderr pipes")
    lock = threading.Lock()
    output_limit_reached = threading.Event()
    chunks: dict[str, list[Any]] = {"stdout": [], "stderr": []}
    reader_errors: list[Exception] = []
    captured_bytes = 0

    def read_stream(name: str, stream: Any) -> None:
        nonlocal captured_bytes
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                encoded = chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
                with lock:
                    remaining = max(0, max_output_bytes - captured_bytes)
                    if remaining:
                        if len(encoded) <= remaining:
                            captured = chunk
                        elif isinstance(chunk, str):
                            captured = encoded[:remaining].decode(
                                "utf-8", errors="ignore"
                            )
                        else:
                            captured = encoded[:remaining]
                        if captured:
                            chunks[name].append(captured)
                    captured_bytes += len(encoded)
                    if captured_bytes > max_output_bytes:
                        output_limit_reached.set()
        except (OSError, ValueError) as exc:
            reader_errors.append(exc)

    readers = [
        threading.Thread(
            target=read_stream,
            args=(name, stream),
            daemon=True,
            name=f"bounded-{name}",
        )
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout_seconds
    outcome: str | None = None
    while process.poll() is None:
        if output_limit_reached.is_set():
            outcome = "output_limit"
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            outcome = "timeout"
            break
        output_limit_reached.wait(timeout=min(0.02, remaining))
    if outcome is not None:
        _terminate_process_tree(process, job)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process, job)
        process.wait(timeout=1)
    for reader in readers:
        reader.join(timeout=5)
    if any(reader.is_alive() for reader in readers):
        for stream in (process.stdout, process.stderr):
            stream.close()
        raise OSError("bounded output reader did not terminate")
    for stream in (process.stdout, process.stderr):
        stream.close()
    if outcome is None and output_limit_reached.is_set():
        outcome = "output_limit"
    if reader_errors and outcome is None:
        raise OSError(str(reader_errors[0]))

    if text_mode:
        stdout = "".join(chunks["stdout"])
        stderr = "".join(chunks["stderr"])
    else:
        stdout = b"".join(chunks["stdout"])
        stderr = b"".join(chunks["stderr"])
    return stdout, stderr, outcome


@dataclass(frozen=True)
class BoundedCommandFailure:
    reason_code: str
    operation: str
    command_class: str
    timeout_seconds: float | None
    command: tuple[str, ...]
    detail: str
    stdout: str
    stderr: str


class BoundedCommandError(subprocess.SubprocessError):
    def __init__(self, failure: BoundedCommandFailure) -> None:
        super().__init__(failure.detail)
        self._failure = failure

    @property
    def failure(self) -> BoundedCommandFailure:
        return self._failure

    @property
    def reason_code(self) -> str:
        return self._failure.reason_code

    @property
    def operation(self) -> str:
        return self._failure.operation

    @property
    def command_class(self) -> str:
        return self._failure.command_class

    @property
    def timeout_seconds(self) -> float | None:
        return self._failure.timeout_seconds


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _failure(
    *,
    operation: str,
    command_class: str,
    suffix: str,
    timeout_seconds: float | None,
    command: Sequence[str],
    detail: str,
    stdout: Any = None,
    stderr: Any = None,
) -> BoundedCommandError:
    return BoundedCommandError(
        BoundedCommandFailure(
            reason_code=f"{operation}_{suffix}",
            operation=operation,
            command_class=command_class,
            timeout_seconds=timeout_seconds,
            command=tuple(str(item) for item in command),
            detail=detail,
            stdout=_text(stdout),
            stderr=_text(stderr),
        )
    )


def resolve_timeout_seconds(operation: str) -> tuple[str, float]:
    if not _OPERATION_PATTERN.fullmatch(operation) or operation not in OPERATION_CLASSES:
        raise ValueError(f"unknown bounded subprocess operation: {operation}")
    command_class = OPERATION_CLASSES[operation]
    policy = COMMAND_CLASS_POLICIES[command_class]
    if policy.environment_key not in os.environ:
        return command_class, policy.default_seconds
    raw = os.environ[policy.environment_key].strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise _failure(
            operation=operation,
            command_class=command_class,
            suffix="timeout_invalid",
            timeout_seconds=None,
            command=(),
            detail=(
                f"{policy.environment_key} must be a finite positive number no greater "
                f"than {policy.maximum_seconds:g}"
            ),
        ) from exc
    if (
        not raw
        or not math.isfinite(value)
        or value <= 0
        or value > policy.maximum_seconds
    ):
        raise _failure(
            operation=operation,
            command_class=command_class,
            suffix="timeout_invalid",
            timeout_seconds=None,
            command=(),
            detail=(
                f"{policy.environment_key} must be a finite positive number no greater "
                f"than {policy.maximum_seconds:g}"
            ),
        )
    return command_class, value


def run_bounded(
    command: Sequence[str],
    *,
    operation: str,
    **run_options: Any,
) -> subprocess.CompletedProcess[Any]:
    if not command:
        raise ValueError("bounded subprocess command must not be empty")
    max_output_bytes = run_options.pop("max_output_bytes", None)
    if max_output_bytes is not None and (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes < 1
    ):
        raise ValueError("max_output_bytes must be a positive integer")
    forbidden = sorted(_FORBIDDEN_RUN_OPTIONS.intersection(run_options))
    if forbidden:
        raise ValueError(
            "run_bounded owns these subprocess options: " + ", ".join(forbidden)
        )
    command_class, timeout_seconds = resolve_timeout_seconds(operation)
    normalized = [str(item) for item in command]
    popen_options = dict(run_options)
    input_data = popen_options.pop("input", None)
    if input_data is not None:
        if "stdin" in popen_options:
            raise ValueError("stdin and input arguments may not both be used")
        popen_options["stdin"] = subprocess.PIPE
    capture_output = popen_options.pop("capture_output", False)
    if max_output_bytes is not None and not capture_output:
        raise ValueError("max_output_bytes requires capture_output=True")
    if max_output_bytes is not None and input_data is not None:
        raise ValueError("max_output_bytes does not support input")
    if capture_output:
        if "stdout" in popen_options or "stderr" in popen_options:
            raise ValueError(
                "capture_output cannot be used with stdout or stderr"
            )
        popen_options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if os.name == "posix":
        popen_options["start_new_session"] = True
    else:
        popen_options["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        )
    try:
        process = subprocess.Popen(
            normalized,
            shell=False,
            **popen_options,
        )
    except FileNotFoundError as exc:
        suffix = (
            "command_missing"
            if not os.path.exists(normalized[0])
            else "command_error"
        )
        raise _failure(
            operation=operation,
            command_class=command_class,
            suffix=suffix,
            timeout_seconds=timeout_seconds,
            command=normalized,
            detail=str(exc),
        ) from exc
    except (OSError, ValueError) as exc:
        raise _failure(
            operation=operation,
            command_class=command_class,
            suffix="command_error",
            timeout_seconds=timeout_seconds,
            command=normalized,
            detail=str(exc),
        ) from exc

    try:
        job = _attach_windows_job(process)
    except _WindowsJobError as exc:
        _terminate_process_tree(process, None)
        _reap_process(process)
        raise _failure(
            operation=operation,
            command_class=command_class,
            suffix="command_error",
            timeout_seconds=timeout_seconds,
            command=normalized,
            detail=str(exc),
        ) from exc
    try:
        try:
            if max_output_bytes is None:
                stdout, stderr = process.communicate(
                    input=input_data, timeout=timeout_seconds
                )
            else:
                text_mode = bool(
                    popen_options.get("text")
                    or popen_options.get("universal_newlines")
                    or popen_options.get("encoding")
                )
                stdout, stderr, outcome = _communicate_limited(
                    process,
                    job,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                    text_mode=text_mode,
                )
                if outcome == "timeout":
                    raise _failure(
                        operation=operation,
                        command_class=command_class,
                        suffix="timeout",
                        timeout_seconds=timeout_seconds,
                        command=normalized,
                        detail=f"bounded subprocess timed out after {timeout_seconds:g}s",
                        stdout=stdout,
                        stderr=stderr,
                    )
                if outcome == "output_limit":
                    raise _failure(
                        operation=operation,
                        command_class=command_class,
                        suffix="output_limit",
                        timeout_seconds=timeout_seconds,
                        command=normalized,
                        detail=(
                            "bounded subprocess exceeded combined output limit of "
                            f"{max_output_bytes} bytes"
                        ),
                        stdout=stdout,
                        stderr=stderr,
                    )
        except subprocess.TimeoutExpired as exc:
            _terminate_process_tree(process, job)
            stdout, stderr = _reap_process(process)
            raise _failure(
                operation=operation,
                command_class=command_class,
                suffix="timeout",
                timeout_seconds=timeout_seconds,
                command=normalized,
                detail=f"bounded subprocess timed out after {timeout_seconds:g}s",
                stdout=stdout if stdout is not None else exc.stdout,
                stderr=stderr if stderr is not None else exc.stderr,
            ) from exc
        except (OSError, ValueError) as exc:
            _terminate_process_tree(process, job)
            _reap_process(process)
            raise _failure(
                operation=operation,
                command_class=command_class,
                suffix="command_error",
                timeout_seconds=timeout_seconds,
                command=normalized,
                detail=str(exc),
            ) from exc
        except BoundedCommandError:
            raise
        except Exception:
            _terminate_process_tree(process, job)
            _reap_process(process)
            raise
        return subprocess.CompletedProcess(normalized, process.returncode, stdout, stderr)
    finally:
        if job is not None:
            job.close()
