from __future__ import annotations

import math
import os
import re
import subprocess
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
}


_OPERATION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_FORBIDDEN_RUN_OPTIONS = frozenset({"check", "shell", "timeout"})


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
    forbidden = sorted(_FORBIDDEN_RUN_OPTIONS.intersection(run_options))
    if forbidden:
        raise ValueError(
            "run_bounded owns these subprocess options: " + ", ".join(forbidden)
        )
    command_class, timeout_seconds = resolve_timeout_seconds(operation)
    normalized = [str(item) for item in command]
    try:
        return subprocess.run(
            normalized,
            check=False,
            shell=False,
            timeout=timeout_seconds,
            **run_options,
        )
    except subprocess.TimeoutExpired as exc:
        raise _failure(
            operation=operation,
            command_class=command_class,
            suffix="timeout",
            timeout_seconds=timeout_seconds,
            command=normalized,
            detail=f"bounded subprocess timed out after {timeout_seconds:g}s",
            stdout=exc.stdout,
            stderr=exc.stderr,
        ) from exc
    except FileNotFoundError as exc:
        missing_target = _text(exc.filename)
        suffix = "command_missing" if missing_target == normalized[0] else "command_error"
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
