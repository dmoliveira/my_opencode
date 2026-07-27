#!/usr/bin/env python3
"""Run verified Playwright CLI/MCP and configured-tuple model smokes."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from playwright_defaults import (
    PLAYWRIGHT_CLI_COMMAND,
    PLAYWRIGHT_CLI_LIFECYCLE_SCRIPTS,
    PLAYWRIGHT_CLI_METADATA_FIELDS,
    PLAYWRIGHT_CLI_MIN_NODE_MAJOR,
    PLAYWRIGHT_CLI_PACKAGE_SPEC,
    PLAYWRIGHT_CLI_VERSION_COMMAND,
    PLAYWRIGHT_CLI_VERSION_OUTPUT,
    PLAYWRIGHT_MCP_CAPABILITIES,
    PLAYWRIGHT_MCP_COMMAND,
    PLAYWRIGHT_MCP_GIT_HEAD,
    PLAYWRIGHT_MCP_INTEGRITY,
    PLAYWRIGHT_MCP_LICENSE,
    PLAYWRIGHT_MCP_PACKAGE_SPEC,
    PLAYWRIGHT_MCP_TOOL_COUNT,
    PLAYWRIGHT_MCP_VERSION,
    inspect_playwright_cli_metadata,
    playwright_cli_npm_environment,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
EXACT_MODEL = "openai/gpt-5.4-mini"
MCP_PROTOCOL_VERSION = "2025-11-25"
PLAYWRIGHT_VERSION = PLAYWRIGHT_MCP_VERSION
PLAYWRIGHT_LICENSE = PLAYWRIGHT_MCP_LICENSE
PLAYWRIGHT_INTEGRITY = PLAYWRIGHT_MCP_INTEGRITY
PLAYWRIGHT_GIT_HEAD = PLAYWRIGHT_MCP_GIT_HEAD
MCP_REQUIRED_TOOL_COUNT = PLAYWRIGHT_MCP_TOOL_COUNT
SELECTED_GATEWAY_HOOK = "noninteractive-shell-guard"
MCP_REQUIRED_TOOLS = {
    "core": "browser_navigate",
    "testing": "browser_generate_locator",
    "network": "browser_route",
    "storage": "browser_storage_state",
    "vision": "browser_mouse_move_xy",
    "devtools": "browser_resume",
    "pdf": "browser_pdf_save",
}
SENSITIVE_ENV_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")
CLI_LOG_BYTES = 128 * 1024
CLI_SNAPSHOT_BYTES = 1024 * 1024
CLI_SCREENSHOT_BYTES = 5 * 1024 * 1024
PROCESS_STDOUT_BYTES = 4 * 1024 * 1024
PROCESS_STDERR_BYTES = 2 * 1024 * 1024
MCP_LINE_BYTES = 2 * 1024 * 1024
MCP_QUEUE_ITEMS = 128
MCP_QUEUE_BYTES = 4 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
ARTIFACT_MAX_ENTRIES = 4096
ARTIFACT_MAX_FILES = 2048
ARTIFACT_MAX_DEPTH = 32
ARTIFACT_MAX_PATH_BYTES = 4096
ARTIFACT_MAX_FILE_BYTES = 8 * 1024 * 1024
ARTIFACT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
OUTPUT_MARKER_NAME = ".my-opencode-harness-output"
OUTPUT_MARKER_CONTENT = b"my_opencode:harness-output:v1\n"
SUPPORTED_PROCESS_PLATFORMS = {"darwin", "linux"}

PROJECT_FIXTURES: dict[str, dict[str, Any]] = {
    "python": {
        "implementation": "stats.py",
        "test_file": "test_stats.py",
        "test_command": ["python3", "-m", "unittest", "-v"],
        "files": {
            "stats.py": '''def summarize(values):
    """Return count, total, average, minimum, and maximum for numeric values."""
    return {}
''',
            "test_stats.py": '''import unittest

from stats import summarize


class SummarizeTests(unittest.TestCase):
    def test_nonempty_values(self):
        self.assertEqual(
            summarize([2, 4, 9]),
            {"count": 3, "total": 15, "average": 5, "minimum": 2, "maximum": 9},
        )

    def test_empty_values(self):
        self.assertEqual(
            summarize([]),
            {"count": 0, "total": 0, "average": None, "minimum": None, "maximum": None},
        )


if __name__ == "__main__":
    unittest.main()
''',
        },
    },
    "node": {
        "implementation": "slugify.mjs",
        "test_file": "slugify.test.mjs",
        "test_command": ["node", "--test", "slugify.test.mjs"],
        "files": {
            "slugify.mjs": '''export function slugify(value) {
  return String(value).toLowerCase()
}
''',
            "slugify.test.mjs": '''import assert from "node:assert/strict"
import test from "node:test"

import { slugify } from "./slugify.mjs"

test("normalizes punctuation and repeated whitespace", () => {
  assert.equal(slugify("  Ship Fast, Stay Safe!  "), "ship-fast-stay-safe")
})

test("collapses separators and trims their edges", () => {
  assert.equal(slugify("Already---Slugged___Value"), "already-slugged-value")
})
''',
        },
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("cli", "mcp", "projects", "all"), nargs="?", default="all"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    parser.add_argument("--model", default=EXACT_MODEL)
    parser.add_argument("--scenario-label", default="wave6")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def selected_components(mode: str) -> tuple[str, ...]:
    if mode == "all":
        return ("mcp", "projects")
    return (mode,)


def _require_supported_process_platform() -> None:
    if sys.platform not in SUPPORTED_PROCESS_PLATFORMS:
        raise RuntimeError(
            "harness process containment supports only Darwin and Linux"
        )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _regular_file_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _validate_owned_directory(metadata: os.stat_result, label: str) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(f"{label} must be a directory")
    if metadata.st_uid != os.geteuid():
        raise PermissionError(f"{label} must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise PermissionError(f"{label} must not be group/world writable")


def _open_owned_directory(path: Path, label: str) -> int:
    before = path.lstat()
    _validate_owned_directory(before, label)
    descriptor = os.open(path, _directory_flags())
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise PermissionError(f"{label} changed during validation")
        _validate_owned_directory(opened, label)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def prepare_output_directory(
    repo_root: Path, requested_output: Path | None
) -> tuple[Path, dict[str, Any]]:
    """Allocate one owner-only output directory under the selected runtime root."""
    _require_supported_process_platform()
    selected_repo = Path(os.path.abspath(repo_root.expanduser()))
    resolved_repo = repo_root.expanduser().resolve(strict=True)
    runtime_root = resolved_repo / "runtime"
    raw_output = requested_output
    if raw_output is None:
        raw_output = runtime_root / f"harness-wave-8-{uuid.uuid4().hex}"
    if ".." in raw_output.parts:
        raise ValueError("output directory must not contain '..'")
    if raw_output.is_absolute():
        requested_absolute = Path(os.path.abspath(raw_output))
        try:
            requested_relative = requested_absolute.relative_to(selected_repo)
        except ValueError:
            candidate = requested_absolute
        else:
            candidate = resolved_repo / requested_relative
    else:
        candidate = Path(os.path.abspath(resolved_repo / raw_output))
    try:
        relative = candidate.relative_to(runtime_root)
    except ValueError as error:
        raise ValueError(
            "output directory must be a strict descendant of repository runtime"
        ) from error
    if not relative.parts:
        raise ValueError(
            "output directory must be a strict descendant of repository runtime"
        )

    repo_descriptor = _open_owned_directory(resolved_repo, "repository root")
    runtime_descriptor = -1
    try:
        runtime_metadata = os.stat(
            "runtime", dir_fd=repo_descriptor, follow_symlinks=False
        )
        _validate_owned_directory(runtime_metadata, "repository runtime root")
        runtime_descriptor = os.open(
            "runtime", _directory_flags(), dir_fd=repo_descriptor
        )
        opened_runtime = os.fstat(runtime_descriptor)
        if (opened_runtime.st_dev, opened_runtime.st_ino) != (
            runtime_metadata.st_dev,
            runtime_metadata.st_ino,
        ):
            raise PermissionError("repository runtime root changed during validation")
        _validate_owned_directory(opened_runtime, "repository runtime root")

        parent_descriptor = os.dup(runtime_descriptor)
        try:
            for index, component in enumerate(relative.parts[:-1], start=1):
                metadata = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                _validate_owned_directory(
                    metadata, f"output ancestor {'/'.join(relative.parts[:index])}"
                )
                child_descriptor = os.open(
                    component, _directory_flags(), dir_fd=parent_descriptor
                )
                opened = os.fstat(child_descriptor)
                if (opened.st_dev, opened.st_ino) != (
                    metadata.st_dev,
                    metadata.st_ino,
                ):
                    os.close(child_descriptor)
                    raise PermissionError("output ancestor changed during validation")
                os.close(parent_descriptor)
                parent_descriptor = child_descriptor

            leaf = relative.parts[-1]
            try:
                os.stat(leaf, dir_fd=parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError("output directory must not already exist")
            os.mkdir(leaf, mode=0o700, dir_fd=parent_descriptor)
            output_descriptor = os.open(
                leaf, _directory_flags(), dir_fd=parent_descriptor
            )
            try:
                os.fchmod(output_descriptor, 0o700)
                created = os.fstat(output_descriptor)
                _validate_owned_directory(created, "created output directory")
                marker_flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                )
                marker_descriptor = os.open(
                    OUTPUT_MARKER_NAME,
                    marker_flags,
                    0o600,
                    dir_fd=output_descriptor,
                )
                try:
                    os.fchmod(marker_descriptor, 0o600)
                    remaining = memoryview(OUTPUT_MARKER_CONTENT)
                    while remaining:
                        remaining = remaining[os.write(marker_descriptor, remaining) :]
                    os.fsync(marker_descriptor)
                    marker_metadata = os.fstat(marker_descriptor)
                    if (
                        not stat.S_ISREG(marker_metadata.st_mode)
                        or marker_metadata.st_nlink != 1
                        or stat.S_IMODE(marker_metadata.st_mode) != 0o600
                        or marker_metadata.st_size != len(OUTPUT_MARKER_CONTENT)
                    ):
                        raise PermissionError("output ownership marker is unsafe")
                finally:
                    os.close(marker_descriptor)
                os.fsync(output_descriptor)
                visible = candidate.lstat()
                if (visible.st_dev, visible.st_ino) != (
                    created.st_dev,
                    created.st_ino,
                ):
                    raise PermissionError(
                        "created output directory changed before use"
                    )
            finally:
                os.close(output_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if runtime_descriptor >= 0:
            os.close(runtime_descriptor)
        os.close(repo_descriptor)
    return candidate, {
        "marker": OUTPUT_MARKER_NAME,
        "marker_version": OUTPUT_MARKER_CONTENT.decode("ascii").strip(),
        "runtime_created": False,
    }


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.total_bytes = 0
        self._retained = bytearray()
        self.truncated = False
        self.eof = False

    def append(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        self._retained.extend(chunk)
        if len(self._retained) > self.limit:
            del self._retained[: len(self._retained) - self.limit]
            self.truncated = True

    def mark_incomplete(self) -> None:
        if not self.eof:
            self.truncated = True

    def text(self) -> str:
        return bytes(self._retained).decode("utf-8", errors="replace")

    def metadata(self) -> dict[str, Any]:
        return {
            "total_bytes": self.total_bytes,
            "retained_bytes": len(self._retained),
            "truncated": self.truncated,
            "eof": self.eof,
        }


def _register_process_streams(
    process: subprocess.Popen[bytes],
    *,
    stdout_limit: int,
    stderr_limit: int,
) -> tuple[selectors.BaseSelector, dict[str, _BoundedCapture]]:
    selector = selectors.DefaultSelector()
    captures = {
        "stdout": _BoundedCapture(stdout_limit),
        "stderr": _BoundedCapture(stderr_limit),
    }
    for name in ("stdout", "stderr"):
        stream = getattr(process, name)
        if stream is None:
            captures[name].mark_incomplete()
            continue
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    return selector, captures


def _read_process_streams(
    selector: selectors.BaseSelector,
    captures: dict[str, _BoundedCapture],
    timeout: float,
    stdout_consumer: Any | None = None,
) -> None:
    for key, _mask in selector.select(max(0.0, timeout)):
        stream = key.fileobj
        name = str(key.data)
        capture = captures[name]
        try:
            chunk = os.read(stream.fileno(), READ_CHUNK_BYTES)
        except BlockingIOError:
            continue
        if chunk:
            capture.append(chunk)
            if name == "stdout" and stdout_consumer is not None:
                stdout_consumer(chunk)
            continue
        capture.eof = True
        selector.unregister(stream)
        stream.close()


def _close_process_streams(
    selector: selectors.BaseSelector,
    captures: dict[str, _BoundedCapture],
) -> None:
    for key in list(selector.get_map().values()):
        name = str(key.data)
        captures[name].mark_incomplete()
        try:
            selector.unregister(key.fileobj)
        except KeyError:
            pass
        try:
            key.fileobj.close()
        except OSError:
            pass
    selector.close()


def _signal_process_group(process_group: int, signal_number: signal.Signals) -> bool:
    try:
        os.killpg(process_group, signal_number)
    except ProcessLookupError:
        return False
    return True


def run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    stdout_limit: int = PROCESS_STDOUT_BYTES,
    stderr_limit: int = PROCESS_STDERR_BYTES,
) -> dict[str, Any]:
    _require_supported_process_platform()
    started = time.monotonic()
    deadline = started + max(0.1, float(timeout))
    shutdown_reserve = min(1.0, max(0.2, float(timeout) * 0.2))
    execution_deadline = max(started, deadline - shutdown_reserve)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        start_new_session=True,
    )
    selector, captures = _register_process_streams(
        process,
        stdout_limit=stdout_limit,
        stderr_limit=stderr_limit,
    )
    timed_out = False
    process_group = process.pid
    signals_sent: list[str] = []
    stage = "running"
    stage_deadline = execution_deadline
    parent_exited_at: float | None = None
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            _read_process_streams(
                selector,
                captures,
                min(0.05, max(0.0, stage_deadline - now)),
            )
            returncode = process.poll()
            streams_open = bool(selector.get_map())
            capture_failed = any(item.truncated for item in captures.values())
            if returncode is not None and not streams_open:
                break
            now = time.monotonic()
            if stage == "running" and returncode is not None:
                if parent_exited_at is None:
                    parent_exited_at = now
                if streams_open and now - parent_exited_at >= 0.05:
                    timed_out = True
                    if _signal_process_group(process_group, signal.SIGTERM):
                        signals_sent.append("TERM")
                    stage = "term"
                    stage_deadline = min(deadline, now + shutdown_reserve / 2)
                    continue
            if stage == "running" and (capture_failed or now >= execution_deadline):
                timed_out = now >= execution_deadline
                if _signal_process_group(process_group, signal.SIGTERM):
                    signals_sent.append("TERM")
                stage = "term"
                stage_deadline = min(deadline, now + shutdown_reserve / 2)
                continue
            if stage == "term" and now >= stage_deadline:
                if _signal_process_group(process_group, signal.SIGKILL):
                    signals_sent.append("KILL")
                stage = "kill"
                stage_deadline = deadline
        if process.poll() is None or selector.get_map():
            if _signal_process_group(process_group, signal.SIGKILL):
                signals_sent.append("KILL")
            while time.monotonic() < deadline and (
                process.poll() is None or selector.get_map()
            ):
                _read_process_streams(
                    selector,
                    captures,
                    min(0.02, max(0.0, deadline - time.monotonic())),
                )
    finally:
        _close_process_streams(selector, captures)
        if process.poll() is None:
            _signal_process_group(process_group, signal.SIGKILL)
            remaining = max(0.0, deadline - time.monotonic())
            if remaining:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    pass
    stream_metadata = {
        name: capture.metadata() for name, capture in captures.items()
    }
    capture_failed = any(
        item["truncated"] or not item["eof"] for item in stream_metadata.values()
    )
    process_returncode = process.poll()
    public_returncode = (
        124
        if timed_out
        else 125
        if capture_failed
        else process_returncode
        if process_returncode is not None
        else 124
    )
    return {
        "command": command,
        "returncode": public_returncode,
        "process_returncode": process_returncode,
        "stdout": captures["stdout"].text(),
        "stderr": captures["stderr"].text(),
        "stdout_total_bytes": stream_metadata["stdout"]["total_bytes"],
        "stdout_truncated": stream_metadata["stdout"]["truncated"],
        "stderr_total_bytes": stream_metadata["stderr"]["total_bytes"],
        "stderr_truncated": stream_metadata["stderr"]["truncated"],
        "stream_metadata": stream_metadata,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "process_pid": process.pid,
        "process_group": process_group,
        "signals_sent": signals_sent,
    }


def _read_regular_file_no_follow(path: Path, maximum_bytes: int) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > maximum_bytes
    ):
        raise RuntimeError("artifact must be a bounded single-link regular file")
    descriptor = os.open(path, _regular_file_flags())
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino, opened.st_size)
            != (before.st_dev, before.st_ino, before.st_size)
        ):
            raise RuntimeError("artifact changed while opening")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum_bytes:
            chunk = os.read(
                descriptor, min(READ_CHUNK_BYTES, maximum_bytes + 1 - total)
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if (
            total > maximum_bytes
            or total != before.st_size
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        ):
            raise RuntimeError("artifact changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _scan_bounded_tree(
    root: Path,
    *,
    max_entries: int = ARTIFACT_MAX_ENTRIES,
    max_files: int = ARTIFACT_MAX_FILES,
    max_depth: int = ARTIFACT_MAX_DEPTH,
    max_file_bytes: int = ARTIFACT_MAX_FILE_BYTES,
    max_total_bytes: int = ARTIFACT_MAX_TOTAL_BYTES,
    forbidden_values: Iterable[str] = (),
) -> dict[str, Any]:
    root_metadata = root.lstat()
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise RuntimeError("artifact root must be a non-symlink directory")
    root_descriptor = os.open(root, _directory_flags())
    opened_root = os.fstat(root_descriptor)
    if (opened_root.st_dev, opened_root.st_ino) != (
        root_metadata.st_dev,
        root_metadata.st_ino,
    ):
        os.close(root_descriptor)
        raise RuntimeError("artifact root changed while opening")
    stack: list[tuple[int, tuple[str, ...], int]] = [(root_descriptor, (), 0)]
    records: list[dict[str, Any]] = []
    top_level: set[str] = set()
    entry_count = 0
    total_bytes = 0
    forbidden = [value.encode("utf-8") for value in forbidden_values if value]
    try:
        while stack:
            descriptor, prefix, depth = stack.pop()
            try:
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        entry_count += 1
                        if entry_count > max_entries:
                            raise RuntimeError("artifact entry count exceeded")
                        parts = (*prefix, entry.name)
                        if depth == 0:
                            top_level.add(entry.name)
                        relative = "/".join(parts)
                        if len(relative.encode("utf-8")) > ARTIFACT_MAX_PATH_BYTES:
                            raise RuntimeError("artifact path length exceeded")
                        metadata = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(metadata.st_mode):
                            if depth + 1 > max_depth:
                                raise RuntimeError("artifact tree depth exceeded")
                            child = os.open(
                                entry.name, _directory_flags(), dir_fd=descriptor
                            )
                            opened = os.fstat(child)
                            if (opened.st_dev, opened.st_ino) != (
                                metadata.st_dev,
                                metadata.st_ino,
                            ):
                                os.close(child)
                                raise RuntimeError(
                                    "artifact directory changed while opening"
                                )
                            stack.append((child, parts, depth + 1))
                            continue
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                            raise RuntimeError(
                                "artifact tree contains a symlink, hardlink, or special file"
                            )
                        if metadata.st_size > max_file_bytes:
                            raise RuntimeError("artifact file size exceeded")
                        if len(records) + 1 > max_files:
                            raise RuntimeError("artifact file count exceeded")
                        if total_bytes + metadata.st_size > max_total_bytes:
                            raise RuntimeError("artifact aggregate size exceeded")
                        file_descriptor = os.open(
                            entry.name, _regular_file_flags(), dir_fd=descriptor
                        )
                        try:
                            opened = os.fstat(file_descriptor)
                            if (
                                not stat.S_ISREG(opened.st_mode)
                                or opened.st_nlink != 1
                                or (
                                    opened.st_dev,
                                    opened.st_ino,
                                    opened.st_size,
                                )
                                != (
                                    metadata.st_dev,
                                    metadata.st_ino,
                                    metadata.st_size,
                                )
                            ):
                                raise RuntimeError(
                                    "artifact file changed while opening"
                                )
                            chunks: list[bytes] = []
                            observed = 0
                            while observed <= max_file_bytes:
                                chunk = os.read(
                                    file_descriptor,
                                    min(
                                        READ_CHUNK_BYTES,
                                        max_file_bytes + 1 - observed,
                                    ),
                                )
                                if not chunk:
                                    break
                                chunks.append(chunk)
                                observed += len(chunk)
                            content = b"".join(chunks)
                            after = os.fstat(file_descriptor)
                            if (
                                observed != metadata.st_size
                                or observed > max_file_bytes
                                or (
                                    after.st_dev,
                                    after.st_ino,
                                    after.st_size,
                                    after.st_mtime_ns,
                                )
                                != (
                                    metadata.st_dev,
                                    metadata.st_ino,
                                    metadata.st_size,
                                    metadata.st_mtime_ns,
                                )
                            ):
                                raise RuntimeError(
                                    "artifact file changed while reading"
                                )
                        finally:
                            os.close(file_descriptor)
                        if any(value in content for value in forbidden):
                            raise RuntimeError("artifact tree contains forbidden material")
                        total_bytes += observed
                        records.append(
                            {
                                "path": relative,
                                "size": observed,
                                "sha256": hashlib.sha256(content).hexdigest(),
                                "content": content,
                            }
                        )
            finally:
                os.close(descriptor)
    except BaseException:
        for descriptor, _prefix, _depth in stack:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    records.sort(key=lambda item: str(item["path"]))
    return {
        "entry_count": entry_count,
        "file_count": len(records),
        "total_bytes": total_bytes,
        "top_level": sorted(top_level),
        "files": records,
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        _read_regular_file_no_follow(path, ARTIFACT_MAX_FILE_BYTES)
    ).hexdigest()


def sha256_tree(root: Path) -> tuple[str, int]:
    scan = _scan_bounded_tree(root)
    digest = hashlib.sha256()
    for record in scan["files"]:
        relative = str(record["path"]).encode("utf-8")
        content = record["content"]
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest(), int(scan["file_count"])


def remaining_timeout(deadline: float, maximum: int) -> int:
    remaining = int(deadline - time.monotonic())
    if remaining < 1:
        raise TimeoutError("exact-model aggregate deadline exceeded")
    return max(1, min(maximum, remaining))


def verify_committed_candidate(
    repo_root: Path, timeout: int
) -> dict[str, Any]:
    source_root = repo_root / "plugin" / "gateway-core" / "src"
    dist_root = repo_root / "plugin" / "gateway-core" / "dist"
    if not source_root.is_dir() or not dist_root.is_dir():
        return {"result": "FAIL", "reason": "gateway_candidate_missing"}
    try:
        with tempfile.TemporaryDirectory(prefix="wave5-gateway-build-") as raw_home:
            build = run_process(
                [
                    "npm",
                    "--prefix",
                    "plugin/gateway-core",
                    "run",
                    "build",
                ],
                cwd=repo_root,
                env=isolated_env(Path(raw_home)),
                timeout=timeout,
            )
        head = run_process(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            env=isolated_env(repo_root),
            timeout=min(30, timeout),
        )
        tracked_status = run_process(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_root,
            env=isolated_env(repo_root),
            timeout=min(30, timeout),
        )
        candidate_status = run_process(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "plugin/gateway-core/src",
                "plugin/gateway-core/dist",
            ],
            cwd=repo_root,
            env=isolated_env(repo_root),
            timeout=min(30, timeout),
        )
    except OSError:
        return {"result": "FAIL", "reason": "candidate_verification_command_failed"}

    head_commit = head["stdout"].strip().lower()
    source_sha256, source_file_count = sha256_tree(source_root)
    dist_sha256, dist_file_count = sha256_tree(dist_root)
    passed = all(
        (
            build["returncode"] == 0,
            head["returncode"] == 0,
            len(head_commit) == 40,
            all(char in "0123456789abcdef" for char in head_commit),
            tracked_status["returncode"] == 0,
            not tracked_status["stdout"].strip(),
            candidate_status["returncode"] == 0,
            not candidate_status["stdout"].strip(),
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "reason": "candidate_committed_and_built" if passed else "candidate_not_clean",
        "head_commit": head_commit if len(head_commit) == 40 else "unavailable",
        "build_returncode": build["returncode"],
        "tracked_clean_after_build": not tracked_status["stdout"].strip(),
        "candidate_paths_clean_after_build": not candidate_status[
            "stdout"
        ].strip(),
        "stream_metadata": {
            "build": _result_stream_metadata(build),
            "head": _result_stream_metadata(head),
            "tracked_status": _result_stream_metadata(tracked_status),
            "candidate_status": _result_stream_metadata(candidate_status),
        },
        "source": {
            "path": "plugin/gateway-core/src",
            "sha256": source_sha256,
            "file_count": source_file_count,
        },
        "dist": {
            "path": "plugin/gateway-core/dist",
            "sha256": dist_sha256,
            "file_count": dist_file_count,
        },
    }


def host_auth_path() -> Path:
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    )
    return data_home / "opencode" / "auth.json"


def collect_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if len(value) >= 16:
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from collect_string_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from collect_string_values(item)


def credential_values(auth_path: Path) -> list[str]:
    values = {
        value
        for key, value in os.environ.items()
        if len(value) >= 8
        and any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
    }
    if auth_path.exists():
        try:
            values.update(collect_string_values(json.loads(auth_path.read_text())))
        except (OSError, json.JSONDecodeError):
            pass
    return sorted(values, key=len, reverse=True)


def auth_store_summary(auth_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    openai = payload.get("openai", {}) if isinstance(payload, dict) else {}
    auth_type = openai.get("type") if isinstance(openai, dict) else None
    return {
        "store_available": auth_path.is_file(),
        "openai_auth_type": auth_type if auth_type == "oauth" else "unavailable",
        "oauth_store_only": auth_type == "oauth",
    }


def sanitize_text(text: str, secrets: list[str]) -> tuple[str, bool]:
    sanitized = text
    detected = False
    for secret in secrets:
        if secret and secret in sanitized:
            detected = True
            sanitized = sanitized.replace(secret, "[CREDENTIAL_REMOVED]")
    return sanitized, detected


def write_safe_text(
    path: Path,
    text: str,
    secrets: list[str],
    private_values: Iterable[str] = (),
) -> bool:
    sanitized, detected = sanitize_text(text, secrets)
    for value in sorted({item for item in private_values if item}, key=len, reverse=True):
        sanitized = sanitized.replace(value, "[PRIVATE_VALUE_REMOVED]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sanitized, encoding="utf-8")
    return detected


def sanitize_report_value(
    value: Any,
    secrets: list[str],
    private_values: Iterable[str],
) -> tuple[Any, bool]:
    if isinstance(value, str):
        sanitized, credential_detected = sanitize_text(value, secrets)
        private_detected = False
        for private in sorted(
            {item for item in private_values if item}, key=len, reverse=True
        ):
            if private in sanitized:
                private_detected = True
                sanitized = sanitized.replace(private, "[PRIVATE_VALUE_REMOVED]")
        return sanitized, credential_detected or private_detected
    if isinstance(value, list):
        output: list[Any] = []
        detected = False
        for item in value:
            sanitized, item_detected = sanitize_report_value(
                item, secrets, private_values
            )
            output.append(sanitized)
            detected |= item_detected
        return output, detected
    if isinstance(value, dict):
        output_dict: dict[str, Any] = {}
        detected = False
        for key, item in value.items():
            sanitized, item_detected = sanitize_report_value(
                item, secrets, private_values
            )
            output_dict[str(key)] = sanitized
            detected |= item_detected
        return output_dict, detected
    return value, False


def write_safe_report(
    path: Path,
    report: dict[str, Any],
    secrets: list[str],
    private_values: Iterable[str],
) -> tuple[dict[str, Any], bool]:
    sanitized, detected = sanitize_report_value(report, secrets, private_values)
    safe_report = sanitized if isinstance(sanitized, dict) else {"result": "FAIL"}
    path.write_text(json.dumps(safe_report, indent=2) + "\n", encoding="utf-8")
    return safe_report, detected


def isolated_env(home: Path, audit_path: Path | None = None) -> dict[str, str]:
    env = {
        key: value
        for key in ("LANG", "LC_ALL", "LOGNAME", "PATH", "SHELL", "TMPDIR", "USER")
        if (value := os.environ.get(key))
    }
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "CI": "true",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GCM_INTERACTIVE": "never",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
        }
    )
    if audit_path is not None:
        env["MY_OPENCODE_GATEWAY_EVENT_AUDIT"] = "1"
        env["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"] = str(audit_path)
    session_id = os.environ.get("OPENCODE_SESSION_ID", "").strip()
    if session_id:
        env["OPENCODE_SESSION_ID"] = session_id
    return env


def runtime_auth_contract(env: dict[str, str]) -> dict[str, Any]:
    forwarded_api_keys = [key for key in env if "API_KEY" in key.upper()]
    return {
        "forwarded_api_key_count": len(forwarded_api_keys),
        "default_plugins_retained": "OPENCODE_DISABLE_DEFAULT_PLUGINS" not in env,
    }


def copy_auth_store(home: Path, source: Path) -> bool:
    if not source.is_file():
        return False
    destination = home / ".local" / "share" / "opencode" / "auth.json"
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    destination.chmod(0o600)
    return True


def gateway_plugin_spec(dist_entry: Path) -> str:
    return dist_entry.resolve().as_uri()


def ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=False)
    except FileExistsError:
        pass
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise PermissionError("exact-model sandbox directory must be owner-only")


def gateway_tuple_options() -> dict[str, Any]:
    return {
        "hooks": {
            "enabled": True,
            "order": [SELECTED_GATEWAY_HOOK],
            "disabled": [],
        },
        "noninteractiveShellGuard": {"enabled": True},
    }


def write_opencode_config(
    home: Path, model: str, dist_entry: Path
) -> dict[str, Any]:
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "small_model": model,
        "default_agent": "build",
        "provider": {
            "openai": {
                "models": {
                    "gpt-5.4-mini": {"name": "GPT-5.4 mini"},
                }
            }
        },
        "plugin": [[gateway_plugin_spec(dist_entry), gateway_tuple_options()]],
        "mcp": {},
        "lsp": False,
        "formatter": False,
        "permission": "allow",
    }
    path = home / ".config" / "opencode" / "opencode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def configured_tuple_summary(config: dict[str, Any]) -> dict[str, Any]:
    entries = config.get("plugin", [])
    entry = entries[0] if isinstance(entries, list) and len(entries) == 1 else None
    options = (
        entry[1]
        if isinstance(entry, list)
        and len(entry) == 2
        and isinstance(entry[0], str)
        and isinstance(entry[1], dict)
        else {}
    )
    hooks = options.get("hooks", {}) if isinstance(options, dict) else {}
    order = hooks.get("order", []) if isinstance(hooks, dict) else []
    return {
        "configured_plugin_entry_count": len(entries) if isinstance(entries, list) else 0,
        "configured_plugin_entry_kind": "tuple" if options else "invalid",
        "hooks_enabled": hooks.get("enabled") is True if isinstance(hooks, dict) else False,
        "selected_hook_ids": order if isinstance(order, list) else [],
    }


def project_gateway_shim_count(project: Path) -> int:
    plugin_dir = project / ".opencode" / "plugins"
    return len(list(plugin_dir.glob("*"))) if plugin_dir.is_dir() else 0


def read_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    content = _read_regular_file_no_follow(path, ARTIFACT_MAX_FILE_BYTES)
    for line in content.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def audit_summary(path: Path) -> dict[str, Any]:
    entries = read_audit(path)
    bootstrap = [
        entry
        for entry in entries
        if entry.get("reason_code") == "gateway_runtime_bootstrap"
    ]
    observed = [
        str(entry.get("actual_model"))
        for entry in entries
        if entry.get("reason_code") == "agent_runtime_model_observed"
        and entry.get("actual_model")
    ]
    session_env_prefixed = [
        entry
        for entry in entries
        if entry.get("reason_code") == "runtime_session_env_prefixed"
    ]
    return {
        "entry_count": len(entries),
        "bootstrap_count": len(bootstrap),
        "bootstrap_hooks_enabled": (
            len(bootstrap) == 1 and bootstrap[0].get("hooks_enabled") is True
        ),
        "observed_models": list(dict.fromkeys(observed)),
        "runtime_session_env_prefixed_count": len(session_env_prefixed),
    }


def fixture_hashes(project: Path) -> dict[str, str]:
    scan = _scan_bounded_tree(project)
    return {
        str(record["path"]): str(record["sha256"])
        for record in scan["files"]
        if "__pycache__" not in Path(str(record["path"])).parts
        and Path(str(record["path"])).suffix != ".pyc"
    }


def write_project_fixture(project: Path, name: str) -> dict[str, Any]:
    spec = PROJECT_FIXTURES[name]
    project.mkdir(parents=True, exist_ok=True)
    for relative, content in spec["files"].items():
        (project / relative).write_text(content, encoding="utf-8")
    (project / "AGENTS.md").write_text(
        "# Fixture instructions\n\n"
        f"Edit only `{spec['implementation']}`. Never edit tests, AGENTS.md, or .opencode files. "
        f"Run `{' '.join(spec['test_command'])}` and leave it green.\n",
        encoding="utf-8",
    )
    return spec


def project_prompt(name: str, spec: dict[str, Any]) -> str:
    return (
        f"Fix the {name} fixture. Edit only {spec['implementation']}; do not create, rename, "
        "or edit any other file. Run the native test command "
        f"`{' '.join(spec['test_command'])}` and keep working until it passes. "
        "Do not use git. Report the implementation change and final test result concisely."
    )


def run_model_once(
    *,
    model: str,
    project: Path,
    env: dict[str, str],
    prompt: str,
    title: str,
    timeout: int,
) -> dict[str, Any]:
    command = [
        "opencode",
        "run",
        "--model",
        model,
        "--agent",
        "build",
        "--format",
        "json",
        "--print-logs",
        "--log-level",
        "DEBUG",
        "--title",
        title,
        prompt,
    ]
    return run_process(
        command,
        cwd=project,
        env=env,
        timeout=timeout,
    )


def prepare_model_sandbox(
    base: Path,
    *,
    model: str,
    dist_entry: Path,
    auth_source: Path,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    ensure_private_directory(base)
    home = base / "home"
    project = base / "project"
    project.mkdir(parents=True, exist_ok=True)
    config = write_opencode_config(home, model, dist_entry)
    if not copy_auth_store(home, auth_source):
        raise FileNotFoundError("OpenCode auth store is unavailable")
    audit_path = base / "gateway-events.jsonl"
    return home, project, audit_path, config


def run_model_preflight(
    *,
    base: Path,
    model: str,
    dist_entry: Path,
    auth_source: Path,
    output_dir: Path,
    timeout: int,
    secrets: list[str],
    additional_private_values: Iterable[str] = (),
) -> dict[str, Any]:
    home, project, audit_path, config = prepare_model_sandbox(
        base,
        model=model,
        dist_entry=dist_entry,
        auth_source=auth_source,
    )
    runtime_env = isolated_env(home, audit_path)
    auth_contract = runtime_auth_contract(runtime_env)
    tuple_summary = configured_tuple_summary(config)
    private_values = (
        str(base.absolute()),
        str(base.resolve()),
        str(auth_source.absolute()),
        str(auth_source.resolve()),
        str(dist_entry.absolute()),
        str(dist_entry.resolve()),
        dist_entry.absolute().as_uri(),
        dist_entry.resolve().as_uri(),
        gateway_plugin_spec(dist_entry),
        "noninteractiveShellGuard",
        *additional_private_values,
    )
    marker = "MODEL_PREFLIGHT_OK"
    result = run_model_once(
        model=model,
        project=project,
        env=runtime_env,
        prompt=f"Reply with exactly {marker}. Do not use tools.",
        title="Harness Wave 5 exact-model preflight",
        timeout=timeout,
    )
    credential_detected = write_safe_text(
        output_dir / "preflight.stdout.jsonl",
        result["stdout"],
        secrets,
        private_values,
    )
    credential_detected |= write_safe_text(
        output_dir / "preflight.stderr.log",
        result["stderr"],
        secrets,
        private_values,
    )
    audit = audit_summary(audit_path)
    retained_audit = output_dir / "preflight.gateway-events.jsonl"
    credential_detected |= write_safe_text(
        retained_audit,
        _read_regular_file_no_follow(
            audit_path, ARTIFACT_MAX_FILE_BYTES
        ).decode("utf-8", errors="replace")
        if audit_path.exists()
        else "",
        secrets,
        private_values,
    )
    shim_count = project_gateway_shim_count(project)
    marker_seen = marker in result["stdout"]
    passed = all(
        (
            result["returncode"] == 0,
            marker_seen,
            audit["bootstrap_count"] == 1,
            audit["bootstrap_hooks_enabled"],
            audit["observed_models"] == [model],
            tuple_summary["configured_plugin_entry_count"] == 1,
            tuple_summary["configured_plugin_entry_kind"] == "tuple",
            tuple_summary["hooks_enabled"],
            tuple_summary["selected_hook_ids"] == [SELECTED_GATEWAY_HOOK],
            shim_count == 0,
            auth_contract["forwarded_api_key_count"] == 0,
            auth_contract["default_plugins_retained"],
            not credential_detected,
        )
    )
    if passed:
        reason = "exact_model_available"
    elif result["returncode"] == 0 and marker_seen and audit["bootstrap_count"] != 1:
        reason = "gateway_audit_unavailable"
    else:
        reason = "model_auth_or_availability_preflight_failed"
    return {
        "result": "PASS" if passed else "BLOCKED",
        "reason": reason,
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "stream_metadata": _result_stream_metadata(result),
        "marker_seen": marker_seen,
        "audit": audit,
        "observed_models": audit["observed_models"],
        "observed_model_source": "gateway_audit",
        **tuple_summary,
        **auth_contract,
        "project_gateway_shim_count": shim_count,
        "credential_material_detected": credential_detected,
    }


def run_project_fixture(
    *,
    name: str,
    base: Path,
    model: str,
    dist_entry: Path,
    auth_source: Path,
    output_dir: Path,
    timeout: int,
    deadline: float,
    secrets: list[str],
    additional_private_values: Iterable[str] = (),
) -> dict[str, Any]:
    home, project, audit_path, config = prepare_model_sandbox(
        base,
        model=model,
        dist_entry=dist_entry,
        auth_source=auth_source,
    )
    runtime_env = isolated_env(home, audit_path)
    auth_contract = runtime_auth_contract(runtime_env)
    tuple_summary = configured_tuple_summary(config)
    private_values = (
        str(base.absolute()),
        str(base.resolve()),
        str(auth_source.absolute()),
        str(auth_source.resolve()),
        str(dist_entry.absolute()),
        str(dist_entry.resolve()),
        dist_entry.absolute().as_uri(),
        dist_entry.resolve().as_uri(),
        gateway_plugin_spec(dist_entry),
        "noninteractiveShellGuard",
        *additional_private_values,
    )
    spec = write_project_fixture(project, name)
    initial_test = run_process(
        list(spec["test_command"]),
        cwd=project,
        env=isolated_env(home),
        timeout=remaining_timeout(deadline, 60),
    )
    before_hashes = fixture_hashes(project)
    model_run = run_model_once(
        model=model,
        project=project,
        env=runtime_env,
        prompt=project_prompt(name, spec),
        title=f"Harness Wave 5 {name} fixture",
        timeout=remaining_timeout(deadline, timeout),
    )
    final_test = run_process(
        list(spec["test_command"]),
        cwd=project,
        env=isolated_env(home),
        timeout=remaining_timeout(deadline, 60),
    )
    after_hashes = fixture_hashes(project)
    changed_files = sorted(
        path
        for path in set(before_hashes) | set(after_hashes)
        if before_hashes.get(path) != after_hashes.get(path)
    )
    artifact_dir = output_dir / name
    credential_detected = False
    for label, run in (
        ("initial-test", initial_test),
        ("model", model_run),
        ("final-test", final_test),
    ):
        credential_detected |= write_safe_text(
            artifact_dir / f"{label}.stdout.log",
            run["stdout"],
            secrets,
            private_values,
        )
        credential_detected |= write_safe_text(
            artifact_dir / f"{label}.stderr.log",
            run["stderr"],
            secrets,
            private_values,
        )
    audit = audit_summary(audit_path)
    audit_text = (
        _read_regular_file_no_follow(
            audit_path, ARTIFACT_MAX_FILE_BYTES
        ).decode("utf-8", errors="replace")
        if audit_path.exists()
        else ""
    )
    credential_detected |= write_safe_text(
        artifact_dir / "gateway-events.jsonl",
        audit_text,
        secrets,
        private_values,
    )
    shim_count = project_gateway_shim_count(project)
    test_hash_unchanged = (
        before_hashes.get(spec["test_file"]) == after_hashes.get(spec["test_file"])
    )
    passed = all(
        (
            initial_test["returncode"] != 0,
            model_run["returncode"] == 0,
            final_test["returncode"] == 0,
            changed_files == [spec["implementation"]],
            test_hash_unchanged,
            audit["bootstrap_count"] == 1,
            audit["bootstrap_hooks_enabled"],
            audit["observed_models"] == [model],
            audit["runtime_session_env_prefixed_count"] >= 1,
            tuple_summary["configured_plugin_entry_count"] == 1,
            tuple_summary["configured_plugin_entry_kind"] == "tuple",
            tuple_summary["hooks_enabled"],
            tuple_summary["selected_hook_ids"] == [SELECTED_GATEWAY_HOOK],
            shim_count == 0,
            auth_contract["forwarded_api_key_count"] == 0,
            auth_contract["default_plugins_retained"],
            not credential_detected,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "fixture": name,
        "implementation": spec["implementation"],
        "test_file": spec["test_file"],
        "test_command": spec["test_command"],
        "initial_test_returncode": initial_test["returncode"],
        "model_returncode": model_run["returncode"],
        "model_timed_out": model_run["timed_out"],
        "final_test_returncode": final_test["returncode"],
        "stream_metadata": {
            "initial_test": _result_stream_metadata(initial_test),
            "model": _result_stream_metadata(model_run),
            "final_test": _result_stream_metadata(final_test),
        },
        "changed_files": changed_files,
        "test_hash_unchanged": test_hash_unchanged,
        "audit": audit,
        "observed_models": audit["observed_models"],
        "observed_model_source": "gateway_audit",
        **tuple_summary,
        **auth_contract,
        "project_gateway_shim_count": shim_count,
        "credential_material_detected": credential_detected,
    }


def _append_bounded_line(lines: deque[str], line: str, retained_bytes: int) -> int:
    encoded = line.encode("utf-8", errors="replace")
    if len(encoded) > CLI_LOG_BYTES:
        encoded = encoded[-CLI_LOG_BYTES:]
        line = encoded.decode("utf-8", errors="replace")
    lines.append(line)
    retained_bytes += len(encoded)
    while retained_bytes > CLI_LOG_BYTES and lines:
        overflow = retained_bytes - CLI_LOG_BYTES
        first = lines[0].encode("utf-8", errors="replace")
        if len(first) <= overflow:
            lines.popleft()
            retained_bytes -= len(first)
            continue
        lines[0] = first[overflow:].decode("utf-8", errors="replace")
        retained_bytes -= overflow
    return retained_bytes


class _JsonLineDecoder:
    def __init__(
        self,
        *,
        max_line_bytes: int = MCP_LINE_BYTES,
        max_queue_items: int = MCP_QUEUE_ITEMS,
        max_queue_bytes: int = MCP_QUEUE_BYTES,
    ) -> None:
        self.max_line_bytes = max_line_bytes
        self.max_queue_items = max_queue_items
        self.max_queue_bytes = max_queue_bytes
        self.pending = bytearray()
        self.messages: deque[tuple[dict[str, Any], int]] = deque()
        self.queued_bytes = 0
        self.error = ""
        self.eof = False

    def _fail(self, message: str) -> None:
        if not self.error:
            self.error = message

    def _append_line(self, line: bytes, retained_bytes: int) -> None:
        if len(line) > self.max_line_bytes:
            self._fail("MCP stdout line exceeded its byte limit")
            return
        try:
            text = line.decode("utf-8", errors="strict")
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._fail("MCP stdout emitted invalid UTF-8 JSON")
            return
        if not isinstance(payload, dict):
            self._fail("MCP stdout JSON messages must be objects")
            return
        if (
            len(self.messages) >= self.max_queue_items
            or self.queued_bytes + retained_bytes > self.max_queue_bytes
        ):
            self._fail("MCP stdout message queue exceeded its byte limit")
            return
        self.messages.append((payload, retained_bytes))
        self.queued_bytes += retained_bytes

    def feed(self, chunk: bytes) -> None:
        if self.error or self.eof:
            return
        self.pending.extend(chunk)
        while not self.error:
            newline = self.pending.find(b"\n")
            if newline < 0:
                if len(self.pending) > self.max_line_bytes:
                    self._fail("MCP stdout line exceeded its byte limit")
                return
            wire_line = bytes(self.pending[:newline])
            line = wire_line.removesuffix(b"\r")
            del self.pending[: newline + 1]
            self._append_line(line, len(wire_line) + 1)

    def finish(self) -> None:
        if self.eof:
            return
        self.eof = True
        if self.pending and not self.error:
            self._fail("MCP stdout closed with a partial JSON line")

    def response(self, response_id: int) -> dict[str, Any] | None:
        for item in tuple(self.messages):
            payload, retained_bytes = item
            if payload.get("id") != response_id:
                continue
            self.messages.remove(item)
            self.queued_bytes -= retained_bytes
            return payload
        return None


def _wait_for_mcp_response(
    *,
    process: subprocess.Popen[bytes],
    selector: selectors.BaseSelector,
    captures: dict[str, _BoundedCapture],
    decoder: _JsonLineDecoder,
    response_id: int,
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        response = decoder.response(response_id)
        if response is not None:
            return response
        if decoder.error:
            raise RuntimeError(decoder.error)
        if captures["stdout"].truncated or captures["stderr"].truncated:
            raise RuntimeError("MCP process output exceeded its capture limit")
        _read_process_streams(
            selector,
            captures,
            min(0.05, max(0.0, deadline - time.monotonic())),
            decoder.feed,
        )
        if captures["stdout"].eof:
            decoder.finish()
        if process.poll() is not None and captures["stdout"].eof:
            if decoder.error:
                raise RuntimeError(decoder.error)
            raise RuntimeError(f"MCP stdout closed before response {response_id}")
    raise TimeoutError(f"MCP response {response_id} timed out")


def _write_pipe_with_deadline(stream: Any, payload: bytes, deadline: float) -> None:
    descriptor = stream.fileno()
    os.set_blocking(descriptor, False)
    view = memoryview(payload)
    while view and time.monotonic() < deadline:
        try:
            written = os.write(descriptor, view)
        except BlockingIOError:
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            continue
        view = view[written:]
    if view:
        raise TimeoutError("MCP stdin write exceeded the process deadline")


def _shutdown_mcp_process(
    *,
    process: subprocess.Popen[bytes],
    selector: selectors.BaseSelector,
    captures: dict[str, _BoundedCapture],
    decoder: _JsonLineDecoder,
    deadline: float,
) -> list[str]:
    signals_sent: list[str] = []
    if process.stdin is not None and not process.stdin.closed:
        process.stdin.close()
    remaining = max(0.0, deadline - time.monotonic())
    term_deadline = time.monotonic() + min(0.25, remaining / 2)
    if process.poll() is None or selector.get_map():
        if _signal_process_group(process.pid, signal.SIGTERM):
            signals_sent.append("TERM")
    while time.monotonic() < term_deadline and (
        process.poll() is None or selector.get_map()
    ):
        _read_process_streams(
            selector,
            captures,
            min(0.02, max(0.0, term_deadline - time.monotonic())),
            decoder.feed,
        )
    if process.poll() is None or selector.get_map():
        if _signal_process_group(process.pid, signal.SIGKILL):
            signals_sent.append("KILL")
    while time.monotonic() < deadline and (
        process.poll() is None or selector.get_map()
    ):
        _read_process_streams(
            selector,
            captures,
            min(0.02, max(0.0, deadline - time.monotonic())),
            decoder.feed,
        )
    if captures["stdout"].eof:
        decoder.finish()
    _close_process_streams(selector, captures)
    if process.poll() is None:
        _signal_process_group(process.pid, signal.SIGKILL)
        remaining = max(0.0, deadline - time.monotonic())
        if remaining:
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
    return signals_sent


def evaluate_mcp_inventory(
    server_info: dict[str, Any], tool_names: list[str]
) -> dict[str, Any]:
    missing = {
        capability: tool
        for capability, tool in MCP_REQUIRED_TOOLS.items()
        if tool not in tool_names
    }
    return {
        "server_name": server_info.get("name"),
        "tool_count": len(tool_names),
        "required_tool_count": MCP_REQUIRED_TOOL_COUNT,
        "required_tools": MCP_REQUIRED_TOOLS,
        "missing_required_tools": missing,
        "pass": (
            server_info.get("name") == "Playwright"
            and len(tool_names) == MCP_REQUIRED_TOOL_COUNT
            and not missing
        ),
    }


def npm_provenance(
    *, cwd: Path, sandbox: Path, timeout: int, secrets: list[str], output_dir: Path
) -> dict[str, Any]:
    command = [
        "npm",
        "view",
        PLAYWRIGHT_MCP_PACKAGE_SPEC,
        "version",
        "license",
        "dist.integrity",
        "gitHead",
        "scripts",
        "--json",
    ]
    result = run_process(
        command,
        cwd=cwd,
        env=playwright_cli_npm_environment(sandbox),
        timeout=timeout,
    )
    detected = write_safe_text(
        output_dir / "npm-view.stderr.log",
        _bounded_text(result["stderr"]),
        secrets,
        [str(sandbox)],
    )
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    scripts = payload.get("scripts")
    script_map = scripts if isinstance(scripts, dict) else {}
    lifecycle_scripts = sorted(
        name for name in PLAYWRIGHT_CLI_LIFECYCLE_SCRIPTS if script_map.get(name)
    )
    safe_payload = {
        "version": payload.get("version"),
        "license": payload.get("license"),
        "integrity": (
            (payload.get("dist") or {}).get("integrity")
            if isinstance(payload.get("dist"), dict)
            else payload.get("dist.integrity")
        ),
        "gitHead": payload.get("gitHead"),
        "lifecycle_scripts": lifecycle_scripts,
    }
    (output_dir / "npm-provenance.json").write_text(
        json.dumps(safe_payload, indent=2) + "\n", encoding="utf-8"
    )
    passed = all(
        (
            result["returncode"] == 0,
            safe_payload["version"] == PLAYWRIGHT_VERSION,
            safe_payload["license"] == PLAYWRIGHT_LICENSE,
            safe_payload["integrity"] == PLAYWRIGHT_INTEGRITY,
            safe_payload["gitHead"] == PLAYWRIGHT_GIT_HEAD,
            safe_payload["lifecycle_scripts"] == [],
            not detected,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        **safe_payload,
        "stream_metadata": _result_stream_metadata(result),
        "credential_material_detected": detected,
    }


class _QuietTodoHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def prepare_playwright_npm_sandbox(sandbox: Path) -> None:
    ensure_private_directory(sandbox)
    for name in (
        "home",
        "tmp",
        "xdg-cache",
        "xdg-config",
        "npm-cache",
        "npm-prefix",
        "s",
    ):
        ensure_private_directory(sandbox / name)
    for name in ("user.npmrc", "global.npmrc"):
        path = sandbox / name
        path.write_text("", encoding="utf-8")
        path.chmod(0o600)


def prepare_playwright_cli_sandbox(sandbox: Path) -> tuple[Path, Path]:
    prepare_playwright_npm_sandbox(sandbox)
    for name in ("workspace", "site"):
        ensure_private_directory(sandbox / name)
    return sandbox / "workspace", sandbox / "site"


def write_todo_fixture(site: Path) -> Path:
    path = site / "index.html"
    path.write_text(
        """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Wave 6 Todo</title></head>
<body>
  <main>
    <h1>Wave 6 Todo</h1>
    <form id="todo-form">
      <label for="new-todo">New todo</label>
      <input id="new-todo" aria-label="New todo">
      <button type="submit">Add</button>
    </form>
    <p role="status" id="status">0 items</p>
    <ul aria-label="Todo items" id="items"></ul>
  </main>
  <script>
    document.querySelector('#todo-form').addEventListener('submit', event => {
      event.preventDefault();
      const input = document.querySelector('#new-todo');
      if (!input.value.trim()) return;
      const item = document.createElement('li');
      item.textContent = input.value.trim();
      document.querySelector('#items').append(item);
      document.querySelector('#status').textContent =
        `${document.querySelectorAll('#items li').length} items`;
      input.value = '';
    });
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return path


def start_todo_server(
    site: Path,
) -> tuple[http.server.ThreadingHTTPServer, threading.Thread, str]:
    handler = functools.partial(_QuietTodoHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(
        target=server.serve_forever,
        name="wave6-todo-server",
        daemon=True,
    )
    thread.start()
    port = int(server.server_address[1])
    return server, thread, f"http://127.0.0.1:{port}/"


def sandbox_inventory(root: Path) -> dict[str, Any]:
    scan = _scan_bounded_tree(root)
    digest = hashlib.sha256()
    for record in scan["files"]:
        relative = str(record["path"])
        size = int(record["size"])
        digest.update(relative.encode("utf-8"))
        digest.update(size.to_bytes(8, "big"))
    return {
        "file_count": scan["file_count"],
        "total_bytes": scan["total_bytes"],
        "metadata_sha256": digest.hexdigest(),
        "top_level": scan["top_level"],
    }


def tracked_worktree_fingerprint(
    repo_root: Path, deadline: float | None = None
) -> str:
    if deadline is not None and deadline <= time.monotonic():
        return "unavailable"
    timeout = (
        5.0
        if deadline is None
        else max(0.1, min(5.0, deadline - time.monotonic()))
    )
    result = run_process(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=repo_root,
        env=isolated_env(repo_root),
        timeout=timeout,
    )
    if result["returncode"] != 0:
        return "unavailable"
    return hashlib.sha256(result["stdout"].encode("utf-8")).hexdigest()


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _bounded_text(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= CLI_LOG_BYTES:
        return text
    return encoded[-CLI_LOG_BYTES:].decode("utf-8", errors="replace")


def _result_stream_metadata(result: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("stream_metadata")
    if isinstance(metadata, dict):
        return metadata
    return {
        name: {
            "total_bytes": len(str(result.get(name) or "").encode("utf-8")),
            "retained_bytes": len(str(result.get(name) or "").encode("utf-8")),
            "truncated": False,
            "eof": True,
        }
        for name in ("stdout", "stderr")
    }


def _workspace_artifact_bytes(
    workspace: Path, relative: str, maximum_bytes: int
) -> bytes:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or ".." in relative_path.parts
        or not relative_path.parts
    ):
        raise RuntimeError("Playwright CLI emitted an unsafe artifact path")
    descriptor = _open_owned_directory(workspace, "Playwright CLI workspace")
    try:
        for component in relative_path.parts[:-1]:
            metadata = os.stat(
                component, dir_fd=descriptor, follow_symlinks=False
            )
            if not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("Playwright CLI artifact parent is unsafe")
            child = os.open(component, _directory_flags(), dir_fd=descriptor)
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                os.close(child)
                raise RuntimeError("Playwright CLI artifact parent changed")
            os.close(descriptor)
            descriptor = child
        metadata = os.stat(
            relative_path.parts[-1],
            dir_fd=descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > maximum_bytes
        ):
            raise RuntimeError("Playwright CLI artifact is unsafe or oversized")
        file_descriptor = os.open(
            relative_path.parts[-1], _regular_file_flags(), dir_fd=descriptor
        )
        try:
            opened = os.fstat(file_descriptor)
            if (
                opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino, opened.st_size)
                != (metadata.st_dev, metadata.st_ino, metadata.st_size)
            ):
                raise RuntimeError("Playwright CLI artifact changed while opening")
            chunks: list[bytes] = []
            total = 0
            while total <= maximum_bytes:
                chunk = os.read(
                    file_descriptor,
                    min(READ_CHUNK_BYTES, maximum_bytes + 1 - total),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            after = os.fstat(file_descriptor)
            if (
                total != metadata.st_size
                or total > maximum_bytes
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                != (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                )
            ):
                raise RuntimeError("Playwright CLI artifact changed while reading")
            return b"".join(chunks)
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _process_identity(pid: int, deadline: float | None = None) -> str | None:
    if not _process_alive(pid):
        return None
    if deadline is not None and deadline <= time.monotonic():
        return None
    timeout = (
        2.0
        if deadline is None
        else max(0.1, min(2.0, deadline - time.monotonic()))
    )
    result = run_process(
        ["ps", "-p", str(pid), "-o", "pid=,lstart=,comm="],
        cwd=REPO_ROOT,
        env=isolated_env(REPO_ROOT),
        timeout=timeout,
    )
    identity = " ".join(result["stdout"].split())
    if result["returncode"] != 0 or not identity.startswith(f"{pid} "):
        return None
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _identity_alive(
    pid: int, identity: str, deadline: float | None = None
) -> bool:
    return _process_identity(pid, deadline) == identity


def _process_group_members(
    group: int, deadline: float | None = None
) -> set[int]:
    if group <= 0:
        return set()
    if deadline is not None and deadline <= time.monotonic():
        return {-1}
    timeout = (
        2.0
        if deadline is None
        else max(0.1, min(2.0, deadline - time.monotonic()))
    )
    result = run_process(
        ["ps", "-axo", "pid=,pgid="],
        cwd=REPO_ROOT,
        env=isolated_env(REPO_ROOT),
        timeout=timeout,
    )
    members: set[int] = set()
    if result["returncode"] != 0:
        return members
    for line in result["stdout"].splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, pgid = (int(part) for part in parts)
        except ValueError:
            continue
        if pgid == group:
            members.add(pid)
    return members


def _terminate_owned_processes(
    identities: dict[int, str], groups: set[int], deadline: float | None = None
) -> None:
    lifecycle_deadline = deadline or (time.monotonic() + 3)
    own_group = os.getpgrp()
    for group in sorted(groups):
        if time.monotonic() >= lifecycle_deadline:
            break
        members = _process_group_members(group, lifecycle_deadline)
        group_is_owned = bool(members) and all(
            pid in identities
            and _identity_alive(pid, identities[pid], lifecycle_deadline)
            for pid in members
        )
        if group == own_group or not group_is_owned:
            continue
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            continue
    term_deadline = min(lifecycle_deadline, time.monotonic() + 0.25)
    while time.monotonic() < term_deadline and any(
        _identity_alive(pid, identity, lifecycle_deadline)
        for pid, identity in identities.items()
    ):
        time.sleep(0.05)
    for pid, identity in sorted(identities.items()):
        if time.monotonic() >= lifecycle_deadline:
            break
        if not _identity_alive(pid, identity, lifecycle_deadline):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _safe_error(error: str, secrets: list[str], private_values: list[str]) -> tuple[str, bool]:
    sanitized, detected = sanitize_text(error, secrets)
    for private in sorted(private_values, key=len, reverse=True):
        if private:
            sanitized = sanitized.replace(private, "[PRIVATE_VALUE_REMOVED]")
    return sanitized, detected


def run_cli_probe(
    *,
    repo_root: Path,
    output_dir: Path,
    scenario_label: str,
    timeout: int,
    secrets: list[str],
) -> dict[str, Any]:
    missing = [name for name in ("node", "npm", "npx") if shutil.which(name) is None]
    if missing:
        return {
            "result": "BLOCKED",
            "reason": "playwright_cli_runtime_missing",
            "missing_binaries": missing,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    artifacts_dir = output_dir / "artifacts"
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^a-zA-Z0-9_-]+", "-", scenario_label).strip("-") or "wave6"
    session = f"{label}-{uuid.uuid4().hex[:10]}"
    commands: list[dict[str, Any]] = []
    artifact_paths: set[str] = set()
    owned_pids: set[int] = set()
    owned_groups: set[int] = set()
    owned_identities: dict[int, str] = {}
    live_owned_groups: set[int] = set()
    credential_detected = False
    provenance: dict[str, Any] = {"verified": False, "mismatches": ["not_run"]}
    assertions = {"item_count": False, "added_text": False}
    error = ""
    scoped_close = False
    version_verified = False
    repo_before = tracked_worktree_fingerprint(repo_root)
    sandbox_cleanup_confirmed = False

    with tempfile.TemporaryDirectory(prefix="wave6-playwright-cli-") as raw_tmp:
        sandbox = Path(raw_tmp)
        workspace, site = prepare_playwright_cli_sandbox(sandbox)
        write_todo_fixture(site)
        env = playwright_cli_npm_environment(sandbox)
        before_inventory = sandbox_inventory(sandbox)
        private_values = [str(sandbox)]
        lifecycle_started = time.monotonic()
        deadline = lifecycle_started + max(1, timeout)
        cleanup_reserve = min(10.0, max(2.0, float(timeout) * 0.1))
        operation_deadline = max(lifecycle_started, deadline - cleanup_reserve)
        open_attempted = False
        server: http.server.ThreadingHTTPServer | None = None
        server_thread: threading.Thread | None = None
        base_url = ""

        def capture_identity(pid: int) -> bool:
            identity = _process_identity(pid, deadline)
            if identity is None:
                return False
            owned_pids.add(pid)
            owned_identities[pid] = identity
            return True

        def execute(label_name: str, command: list[str], *, cleanup: bool = False) -> dict[str, Any]:
            nonlocal credential_detected
            try:
                command_timeout = (
                    remaining_timeout(deadline, min(20, max(1, timeout)))
                    if cleanup
                    else remaining_timeout(operation_deadline, max(1, timeout))
                )
                result = run_process(
                    command,
                    cwd=workspace,
                    env=env,
                    timeout=command_timeout,
                )
            except (OSError, TimeoutError) as execution_error:
                result = {
                    "command": command,
                    "returncode": 124 if isinstance(execution_error, TimeoutError) else 1,
                    "stdout": "",
                    "stderr": str(execution_error),
                    "timed_out": isinstance(execution_error, TimeoutError),
                    "duration_seconds": 0.0,
                }
            pid = result.get("process_pid")
            group = result.get("process_group")
            if isinstance(pid, int) and pid > 0:
                owned_pids.add(pid)
            if isinstance(group, int) and group > 0:
                owned_groups.add(group)
                members = _process_group_members(group, deadline)
                captured_group_member = False
                for member in members:
                    captured_group_member |= capture_identity(member)
                if captured_group_member:
                    live_owned_groups.add(group)
            stdout_path = logs_dir / f"{label_name}.stdout.log"
            stderr_path = logs_dir / f"{label_name}.stderr.log"
            credential_detected |= write_safe_text(
                stdout_path,
                _bounded_text(str(result.get("stdout") or "")),
                secrets,
                private_values,
            )
            credential_detected |= write_safe_text(
                stderr_path,
                _bounded_text(str(result.get("stderr") or "")),
                secrets,
                private_values,
            )
            artifact_paths.update(
                {
                    stdout_path.relative_to(output_dir).as_posix(),
                    stderr_path.relative_to(output_dir).as_posix(),
                }
            )
            safe_command = ["[TODO_URL]" if item == base_url else item for item in command]
            commands.append(
                {
                    "label": label_name,
                    "command": safe_command,
                    "returncode": result.get("returncode"),
                    "timed_out": bool(result.get("timed_out")),
                    "duration_seconds": result.get("duration_seconds"),
                    "stream_metadata": _result_stream_metadata(result),
                    "stdout_artifact": stdout_path.relative_to(output_dir).as_posix(),
                    "stderr_artifact": stderr_path.relative_to(output_dir).as_posix(),
                }
            )
            return result

        try:
            node_result = execute("node-version", ["node", "--version"])
            node_output = str(node_result.get("stdout") or "").strip()
            try:
                node_major = int(node_output.removeprefix("v").split(".", 1)[0])
            except (ValueError, IndexError):
                node_major = 0
            if (
                node_result.get("returncode") != 0
                or node_major < PLAYWRIGHT_CLI_MIN_NODE_MAJOR
            ):
                raise RuntimeError("Playwright CLI requires Node 18+")

            metadata_result = execute(
                "npm-view",
                [
                    "npm",
                    "view",
                    PLAYWRIGHT_CLI_PACKAGE_SPEC,
                    *PLAYWRIGHT_CLI_METADATA_FIELDS,
                    "--json",
                ],
            )
            provenance = inspect_playwright_cli_metadata(
                _parse_json_object(str(metadata_result.get("stdout") or ""))
            )
            if metadata_result.get("returncode") != 0 or not provenance["verified"]:
                raise RuntimeError("Playwright CLI provenance verification failed")

            version_result = execute("version", list(PLAYWRIGHT_CLI_VERSION_COMMAND))
            version_verified = all(
                (
                    version_result.get("returncode") == 0,
                    str(version_result.get("stdout") or "").strip()
                    == PLAYWRIGHT_CLI_VERSION_OUTPUT,
                )
            )
            if not version_verified:
                raise RuntimeError("Playwright CLI exact version check failed")

            server, server_thread, base_url = start_todo_server(site)
            private_values.append(base_url)
            open_attempted = True
            open_result = execute(
                "open",
                [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "open", base_url, "--json"],
            )
            if open_result.get("returncode") != 0:
                raise RuntimeError("Playwright CLI open failed")
            open_payload = _parse_json_object(str(open_result.get("stdout") or ""))
            daemon_pid = open_payload.get("pid")
            if isinstance(daemon_pid, int) and daemon_pid > 0:
                capture_identity(daemon_pid)
                try:
                    daemon_group = os.getpgid(daemon_pid)
                except ProcessLookupError:
                    daemon_group = 0
                if daemon_group > 0:
                    owned_groups.add(daemon_group)
                    live_owned_groups.add(daemon_group)
                    for member in _process_group_members(daemon_group, deadline):
                        capture_identity(member)
            snapshot_info = (open_payload.get("result") or {}).get("snapshot", {})
            snapshot_relative = (
                snapshot_info.get("file") if isinstance(snapshot_info, dict) else ""
            )
            if not isinstance(snapshot_relative, str) or not snapshot_relative:
                raise RuntimeError("Playwright CLI open snapshot missing")
            open_snapshot = _workspace_artifact_bytes(
                workspace, snapshot_relative, CLI_SNAPSHOT_BYTES
            )
            snapshot_text = open_snapshot.decode("utf-8")
            textbox_match = re.search(
                r'textbox "New todo"[^\n]*\[ref=(e\d+)\]', snapshot_text
            )
            button_match = re.search(r'button "Add"[^\n]*\[ref=(e\d+)\]', snapshot_text)
            if textbox_match is None or button_match is None:
                raise RuntimeError("Playwright CLI Todo element references missing")
            retained_snapshot = artifacts_dir / "open-snapshot.yml"
            retained_snapshot.write_bytes(open_snapshot)
            artifact_paths.add(retained_snapshot.relative_to(output_dir).as_posix())

            flow = (
                (
                    "fill",
                    [
                        *PLAYWRIGHT_CLI_COMMAND,
                        f"-s={session}",
                        "fill",
                        textbox_match.group(1),
                        "Ship Wave 6",
                        "--json",
                    ],
                ),
                (
                    "click",
                    [
                        *PLAYWRIGHT_CLI_COMMAND,
                        f"-s={session}",
                        "click",
                        button_match.group(1),
                        "--json",
                    ],
                ),
                (
                    "snapshot",
                    [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "snapshot", "--json"],
                ),
                (
                    "screenshot",
                    [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "screenshot", "--json"],
                ),
            )
            flow_results: dict[str, dict[str, Any]] = {}
            for flow_label, flow_command in flow:
                flow_result = execute(flow_label, flow_command)
                flow_results[flow_label] = flow_result
                if flow_result.get("returncode") != 0:
                    raise RuntimeError(f"Playwright CLI {flow_label} failed")
            snapshot_payload = _parse_json_object(
                str(flow_results["snapshot"].get("stdout") or "")
            )
            final_snapshot = str(snapshot_payload.get("snapshot") or "")
            assertions = {
                "item_count": "1 items" in final_snapshot,
                "added_text": "Ship Wave 6" in final_snapshot,
            }
            retained_final = artifacts_dir / "todo-snapshot.txt"
            retained_final.write_text(final_snapshot, encoding="utf-8")
            artifact_paths.add(retained_final.relative_to(output_dir).as_posix())

            screenshot_payload = _parse_json_object(
                str(flow_results["screenshot"].get("stdout") or "")
            )
            screenshot_match = re.search(
                r"\(([^)]+\.png)\)", str(screenshot_payload.get("result") or "")
            )
            if screenshot_match is None:
                raise RuntimeError("Playwright CLI screenshot artifact missing")
            screenshot = _workspace_artifact_bytes(
                workspace, screenshot_match.group(1), CLI_SCREENSHOT_BYTES
            )
            retained_screenshot = artifacts_dir / "todo.png"
            retained_screenshot.write_bytes(screenshot)
            artifact_paths.add(retained_screenshot.relative_to(output_dir).as_posix())
            if not all(assertions.values()):
                raise RuntimeError("Playwright CLI Todo assertions failed")
        except (OSError, RuntimeError, TimeoutError) as execution_error:
            error, detected = _safe_error(str(execution_error), secrets, private_values)
            credential_detected |= detected
        finally:
            if open_attempted:
                close_result = execute(
                    "close",
                    [*PLAYWRIGHT_CLI_COMMAND, f"-s={session}", "close", "--json"],
                    cleanup=True,
                )
                close_payload = _parse_json_object(
                    str(close_result.get("stdout") or "")
                )
                scoped_close = all(
                    (
                        close_result.get("returncode") == 0,
                        close_payload.get("session") == session,
                        close_payload.get("status") == "closed",
                    )
                )
            if server is not None:
                server.shutdown()
                server.server_close()
            if server_thread is not None:
                server_thread.join(
                    timeout=max(0.0, min(3.0, deadline - time.monotonic()))
                )
            for group in live_owned_groups:
                for member in _process_group_members(group, deadline):
                    capture_identity(member)
            wait_deadline = min(deadline, time.monotonic() + 1)
            while time.monotonic() < wait_deadline and any(
                _identity_alive(pid, identity, deadline)
                for pid, identity in owned_identities.items()
            ):
                time.sleep(0.05)
            surviving = {
                pid
                for pid, identity in owned_identities.items()
                if _identity_alive(pid, identity, deadline)
            }
            if surviving:
                _terminate_owned_processes(
                    owned_identities, live_owned_groups, deadline
                )
                surviving = {
                    pid
                    for pid, identity in owned_identities.items()
                    if _identity_alive(pid, identity, deadline)
                }
            unverified_group_members = {
                pid
                for group in live_owned_groups
                for pid in _process_group_members(group, deadline)
                if pid not in owned_identities
                or not _identity_alive(pid, owned_identities[pid], deadline)
            }
            after_inventory = sandbox_inventory(sandbox)
            repo_after = tracked_worktree_fingerprint(repo_root, deadline)
            sandbox_only_writes = repo_before != "unavailable" and repo_before == repo_after

        passed = all(
            (
                provenance.get("verified") is True,
                version_verified,
                not error,
                all(assertions.values()),
                scoped_close,
                not surviving,
                not unverified_group_members,
                sandbox_only_writes,
                not credential_detected,
            )
        )
        report = {
            "result": "PASS" if passed else "FAIL",
            "reason": "playwright_cli_todo_green" if passed else "playwright_cli_failed",
            "session": session,
            "package_spec": PLAYWRIGHT_CLI_PACKAGE_SPEC,
            "provenance": provenance,
            "version_verified": version_verified,
            "commands": commands,
            "assertions": assertions,
            "scoped_close": scoped_close,
            "close_all_used": False,
            "kill_all_used": False,
            "owned_child_pids": sorted(owned_pids),
            "owned_process_groups": sorted(owned_groups),
            "surviving_owned_pids": sorted(surviving),
            "unverified_owned_group_pids": sorted(unverified_group_members),
            "sandbox_inventory_before": before_inventory,
            "sandbox_inventory_after": after_inventory,
            "sandbox_only_writes": sandbox_only_writes,
            "artifact_paths": sorted(artifact_paths),
            "credential_material_detected": credential_detected,
            "error": error,
        }
    sandbox_cleanup_confirmed = not sandbox.exists()
    report["sandbox_cleanup_confirmed"] = sandbox_cleanup_confirmed
    if not sandbox_cleanup_confirmed:
        report["result"] = "FAIL"
        report["reason"] = "playwright_cli_sandbox_cleanup_failed"
    return report


def run_mcp_probe(
    *, output_dir: Path, timeout: int, secrets: list[str]
) -> dict[str, Any]:
    _require_supported_process_platform()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wave2-playwright-mcp-") as raw_tmp:
        sandbox = Path(raw_tmp)
        prepare_playwright_npm_sandbox(sandbox)
        npm_env = playwright_cli_npm_environment(sandbox)
        provenance = npm_provenance(
            cwd=sandbox,
            sandbox=sandbox,
            timeout=timeout,
            secrets=secrets,
            output_dir=output_dir,
        )
        command = list(PLAYWRIGHT_MCP_COMMAND)
        if provenance["result"] != "PASS":
            return {
                "result": "FAIL",
                "command": command,
                "capabilities": list(PLAYWRIGHT_MCP_CAPABILITIES),
                "protocol_version": None,
                "inventory": evaluate_mcp_inventory({}, []),
                "provenance": provenance,
                "error": "Playwright MCP provenance verification failed",
                "credential_material_detected": provenance.get(
                    "credential_material_detected", False
                ),
            }
        started = time.monotonic()
        deadline = started + max(0.1, float(timeout))
        shutdown_reserve = min(1.0, max(0.2, float(timeout) * 0.2))
        protocol_deadline = max(started, deadline - shutdown_reserve)
        process: subprocess.Popen[bytes] = subprocess.Popen(
            command,
            cwd=sandbox,
            env=npm_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
            start_new_session=True,
        )
        selector, captures = _register_process_streams(
            process,
            stdout_limit=MCP_QUEUE_BYTES,
            stderr_limit=PROCESS_STDERR_BYTES,
        )
        decoder = _JsonLineDecoder()
        error = ""
        initialize: dict[str, Any] = {}
        tools_response: dict[str, Any] = {}
        signals_sent: list[str] = []
        try:
            assert process.stdin is not None
            initialize_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "wave2-stdio-probe",
                        "version": "1.0.0",
                    },
                },
            }
            _write_pipe_with_deadline(
                process.stdin,
                (
                    json.dumps(initialize_request, separators=(",", ":")) + "\n"
                ).encode("utf-8"),
                protocol_deadline,
            )
            initialize = _wait_for_mcp_response(
                process=process,
                selector=selector,
                captures=captures,
                decoder=decoder,
                response_id=1,
                deadline=protocol_deadline,
            )
            followup = (
                json.dumps(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    separators=(",", ":"),
                )
                + "\n"
                +
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            _write_pipe_with_deadline(
                process.stdin, followup.encode("utf-8"), protocol_deadline
            )
            tools_response = _wait_for_mcp_response(
                process=process,
                selector=selector,
                captures=captures,
                decoder=decoder,
                response_id=2,
                deadline=protocol_deadline,
            )
        except (AssertionError, BrokenPipeError, RuntimeError, TimeoutError) as exc:
            error = str(exc)
        finally:
            signals_sent = _shutdown_mcp_process(
                process=process,
                selector=selector,
                captures=captures,
                decoder=decoder,
                deadline=deadline,
            )
        stream_metadata = {
            name: capture.metadata() for name, capture in captures.items()
        }
        if not error and decoder.error:
            error = decoder.error
        if not error and any(
            metadata["truncated"] or not metadata["eof"]
            for metadata in stream_metadata.values()
        ):
            error = "MCP process output was truncated or did not reach EOF"
        stdout_text = captures["stdout"].text()
        stderr_text = captures["stderr"].text()
        process_returncode = process.poll()

    initialize_result = initialize.get("result", {})
    tools_result = tools_response.get("result", {})
    tools = tools_result.get("tools", []) if isinstance(tools_result, dict) else []
    tool_names = sorted(
        str(tool.get("name"))
        for tool in tools
        if isinstance(tool, dict) and tool.get("name")
    )
    server_info = (
        initialize_result.get("serverInfo", {})
        if isinstance(initialize_result, dict)
        else {}
    )
    inventory = evaluate_mcp_inventory(server_info, tool_names)
    protocol_version = (
        initialize_result.get("protocolVersion")
        if isinstance(initialize_result, dict)
        else None
    )
    credential_detected = write_safe_text(
        output_dir / "mcp.stdout.jsonl",
        _bounded_text(stdout_text),
        secrets,
        [str(sandbox)],
    )
    credential_detected |= write_safe_text(
        output_dir / "mcp.stderr.log",
        _bounded_text(stderr_text),
        secrets,
        [str(sandbox)],
    )
    inventory_artifact = {
        "command": command,
        "protocol_version": protocol_version,
        "server_info": server_info,
        "tool_count": len(tool_names),
        "required_tool_count": MCP_REQUIRED_TOOL_COUNT,
        "tool_names": tool_names,
        "required_tools": MCP_REQUIRED_TOOLS,
    }
    (output_dir / "mcp-inventory.json").write_text(
        json.dumps(inventory_artifact, indent=2) + "\n", encoding="utf-8"
    )
    passed = all(
        (
            provenance["result"] == "PASS",
            not error,
            protocol_version == MCP_PROTOCOL_VERSION,
            inventory["pass"],
            not credential_detected,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "command": command,
        "capabilities": list(PLAYWRIGHT_MCP_CAPABILITIES),
        "protocol_version": protocol_version,
        "inventory": inventory,
        "provenance": provenance,
        "error": error,
        "process_returncode": process_returncode,
        "stream_metadata": stream_metadata,
        "signals_sent": signals_sent,
        "credential_material_detected": credential_detected,
    }


def run_projects(
    *,
    repo_root: Path,
    output_dir: Path,
    model: str,
    timeout: int,
    secrets: list[str],
    forbidden_values: list[str] | None = None,
) -> dict[str, Any]:
    dist_entry = repo_root / "plugin" / "gateway-core" / "dist" / "index.js"
    auth_source = host_auth_path()
    if model != EXACT_MODEL:
        return {
            "result": "BLOCKED",
            "reason": "exact_model_required",
            "requested_model": model,
            "required_model": EXACT_MODEL,
        }
    if shutil.which("opencode") is None:
        return {"result": "BLOCKED", "reason": "opencode_missing"}
    if not auth_source.is_file():
        return {"result": "BLOCKED", "reason": "opencode_auth_store_missing"}
    auth = auth_store_summary(auth_source)
    if not auth["oauth_store_only"]:
        return {"result": "BLOCKED", "reason": "openai_oauth_store_required"}
    candidate = verify_committed_candidate(repo_root, timeout)
    if candidate["result"] != "PASS":
        return {
            "result": "FAIL",
            "reason": candidate["reason"],
            "candidate": candidate,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(1, timeout)
    preflight: dict[str, Any] = {
        "result": "BLOCKED",
        "reason": "preflight_not_run",
    }
    fixtures: dict[str, dict[str, Any]] = {}
    sandbox_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="wave5-exact-model-") as raw_tmp:
            raw_sandbox_path = Path(raw_tmp).absolute()
            sandbox_path = raw_sandbox_path.resolve()
            sandbox_private_values = [
                str(raw_sandbox_path),
                str(sandbox_path),
                str(auth_source.absolute()),
                str(auth_source.resolve()),
                str(dist_entry.absolute()),
                str(dist_entry.resolve()),
                dist_entry.absolute().as_uri(),
                dist_entry.resolve().as_uri(),
                gateway_plugin_spec(dist_entry),
                "noninteractiveShellGuard",
            ]
            if forbidden_values is not None:
                forbidden_values.extend(sandbox_private_values)
            preflight = run_model_preflight(
                base=sandbox_path / "preflight",
                model=model,
                dist_entry=dist_entry,
                auth_source=auth_source,
                output_dir=output_dir,
                timeout=remaining_timeout(deadline, timeout),
                secrets=secrets,
                additional_private_values=sandbox_private_values,
            )
            if preflight["result"] == "PASS":
                for name in PROJECT_FIXTURES:
                    try:
                        fixtures[name] = run_project_fixture(
                            name=name,
                            base=sandbox_path / name,
                            model=model,
                            dist_entry=dist_entry,
                            auth_source=auth_source,
                            output_dir=output_dir,
                            timeout=timeout,
                            deadline=deadline,
                            secrets=secrets,
                            additional_private_values=sandbox_private_values,
                        )
                    except TimeoutError:
                        fixtures[name] = {
                            "result": "FAIL",
                            "fixture": name,
                            "reason": "project_aggregate_timeout",
                            "model_timed_out": True,
                        }
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        preflight = {
            "result": "BLOCKED",
            "reason": "exact_model_sandbox_failed",
            "error_type": type(error).__name__,
        }
    sandbox_cleanup_confirmed = bool(
        sandbox_path is not None and not sandbox_path.exists()
    )
    fixtures_pass = len(fixtures) == len(PROJECT_FIXTURES) and all(
        report["result"] == "PASS" for report in fixtures.values()
    )
    passed = all(
        (
            preflight.get("result") == "PASS",
            fixtures_pass,
            sandbox_cleanup_confirmed,
        )
    )
    return {
        "result": "PASS" if passed else "FAIL",
        "reason": (
            "exact_model_projects_green"
            if passed
            else preflight.get("reason", "project_validation_failed")
            if preflight.get("result") != "PASS"
            else "project_validation_failed"
        ),
        "model": model,
        "auth": {
            **auth,
            "source": "isolated_opencode_oauth_store",
        },
        "preflight": preflight,
        "candidate": candidate,
        "fixtures": fixtures,
        "aggregate_timeout_seconds": timeout,
        "sandbox_cleanup_confirmed": sandbox_cleanup_confirmed,
    }


def retained_artifacts_safe(
    output_dir: Path,
    secrets: list[str],
    forbidden_values: Iterable[str] = (),
) -> bool:
    try:
        _scan_bounded_tree(
            output_dir,
            forbidden_values=(*secrets, *forbidden_values),
        )
    except (OSError, RuntimeError, UnicodeError, ValueError):
        return False
    return True


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.expanduser().resolve(strict=True)
        output_dir, output_authority = prepare_output_directory(
            repo_root, args.output_dir
        )
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        report = {
            "result": "FAIL",
            "reason": "unsafe_output_directory",
            "error": str(error),
            "mode": args.mode,
            "model": args.model,
            "scenario_label": args.scenario_label,
        }
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"harness Wave 8 configured-tuple proof: {report['result']}")
            print(f"reason: {report['reason']}")
        return 2
    secrets = credential_values(host_auth_path())
    forbidden_values: list[str] = []
    report: dict[str, Any] = {
        "mode": args.mode,
        "model": args.model,
        "scenario_label": args.scenario_label,
        "output_authority": output_authority,
    }
    components = selected_components(args.mode)
    if "cli" in components:
        report["cli"] = run_cli_probe(
            repo_root=repo_root,
            output_dir=output_dir / "cli",
            scenario_label=args.scenario_label,
            timeout=args.timeout_seconds,
            secrets=secrets,
        )
    if "mcp" in components:
        report["mcp"] = run_mcp_probe(
            output_dir=output_dir / "mcp",
            timeout=args.timeout_seconds,
            secrets=secrets,
        )
    if "projects" in components:
        report["projects"] = run_projects(
            repo_root=repo_root,
            output_dir=output_dir / "projects",
            model=args.model,
            timeout=args.timeout_seconds,
            secrets=secrets,
            forbidden_values=forbidden_values,
        )
    component_results = [
        component.get("result")
        for key, component in report.items()
        if key in ("cli", "mcp", "projects") and isinstance(component, dict)
    ]
    report["retained_artifacts_safe"] = False
    report["result"] = (
        "PASS"
        if component_results
        and all(result == "PASS" for result in component_results)
        else "BLOCKED"
        if "BLOCKED" in component_results
        else "FAIL"
    )
    report_path = output_dir / "report.json"
    report, report_sensitive = write_safe_report(
        report_path, report, secrets, forbidden_values
    )
    artifact_safe = retained_artifacts_safe(
        output_dir, secrets, forbidden_values
    ) and not report_sensitive
    report["retained_artifacts_safe"] = artifact_safe
    if not artifact_safe:
        report["result"] = "FAIL"
    report, final_report_sensitive = write_safe_report(
        report_path, report, secrets, forbidden_values
    )
    if final_report_sensitive:
        report["retained_artifacts_safe"] = False
        report["result"] = "FAIL"
        report, _ = write_safe_report(
            report_path, report, secrets, forbidden_values
        )
    if not retained_artifacts_safe(output_dir, secrets, forbidden_values):
        report["retained_artifacts_safe"] = False
        report["result"] = "FAIL"
        report, _ = write_safe_report(
            report_path, report, secrets, forbidden_values
        )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"harness Wave 6 configured-tuple proof: {report['result']}")
        print(f"artifacts: {output_dir}")
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
