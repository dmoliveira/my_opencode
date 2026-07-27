#!/usr/bin/env python3

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import platform
import selectors
import signal
import stat
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

AST_GREP_VERSION = "0.45.0"
AST_GREP_ASSET = "app-aarch64-apple-darwin.zip"
AST_GREP_URL = f"https://github.com/ast-grep/ast-grep/releases/download/{AST_GREP_VERSION}/{AST_GREP_ASSET}"
AST_GREP_ARCHIVE_SHA256 = (
    "ec2e3680f4f84c68b48420bcca01d21389787c7318b52083dde6f46ac12ad946"
)
AST_GREP_BINARY_SHA256 = (
    "92b5c91bad81864bc2f9ee223e9cf8579abc201fe4d1027b092b0227c472977b"
)
AST_GREP_BINARY_SIZE = 52_074_976
AST_GREP_VERSION_OUTPUT = "ast-grep 0.45.0"
AST_GREP_CACHE_ENV = "OPENCODE_DEVTOOLS_CACHE_ROOT"
AST_GREP_BIN_ENV = "OPENCODE_DEVTOOLS_BIN_ROOT"

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 10
MAX_JSON_BYTES = 16 * 1024
MAX_PROCESS_OUTPUT_BYTES = 64 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60
VERSION_TIMEOUT_SECONDS = 10
LOCK_TIMEOUT_SECONDS = 2
READ_BYTES = 64 * 1024
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
EXECUTABLE_MODE = 0o700
RENAME_EXCL = 0x00000004

LOCK_NAME = f".ast-grep-{AST_GREP_VERSION}.lock"
JOURNAL_NAME = f".ast-grep-{AST_GREP_VERSION}.transaction.json"
ARCHIVE_STAGE_NAME = f".ast-grep-{AST_GREP_VERSION}.archive.tmp"
BINARY_STAGE_NAME = f".ast-grep-{AST_GREP_VERSION}.binary.tmp"
ATTESTATION_STAGE_NAME = f".ast-grep-{AST_GREP_VERSION}.attestation.tmp"
ATTESTATION_NAME = f"ast-grep-{AST_GREP_VERSION}.attestation.json"
BINARY_NAME = "ast-grep"

Durability = Literal["not_committed", "uncertain", "synced"]


@dataclass(frozen=True)
class ArchiveEntryProfile:
    name: str
    file_size: int
    compress_size: int
    crc: int
    external_attr: int
    create_system: int
    flag_bits: int
    compress_type: int
    extra: bytes
    comment: bytes = b""


@dataclass(frozen=True)
class AstGrepArtifact:
    version: str
    asset: str
    url: str
    archive_sha256: str
    archive_size: int
    binary_sha256: str
    binary_size: int
    version_output: str
    entries: tuple[ArchiveEntryProfile, ...]


_EXTRA = bytes.fromhex("5554050003463d626a75780b000104f50100000414000000")
DEFAULT_ARTIFACT = AstGrepArtifact(
    version=AST_GREP_VERSION,
    asset=AST_GREP_ASSET,
    url=AST_GREP_URL,
    archive_sha256=AST_GREP_ARCHIVE_SHA256,
    archive_size=8_111_714,
    binary_sha256=AST_GREP_BINARY_SHA256,
    binary_size=AST_GREP_BINARY_SIZE,
    version_output=AST_GREP_VERSION_OUTPUT,
    entries=(
        ArchiveEntryProfile(
            "sg",
            413_008,
            172_629,
            0x8D0A6976,
            0x81ED0000,
            3,
            0,
            zipfile.ZIP_DEFLATED,
            _EXTRA,
        ),
        ArchiveEntryProfile(
            "ast-grep",
            52_074_976,
            7_938_787,
            0xABD6D0AF,
            0x81ED0000,
            3,
            0,
            zipfile.ZIP_DEFLATED,
            _EXTRA,
        ),
    ),
)


class AstGrepInstallError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        phase: str,
        committed: bool = False,
        complete: bool = False,
        recovery_required: bool = False,
        durability: Durability = "not_committed",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.phase = phase
        self.committed = committed
        self.complete = complete
        self.recovery_required = recovery_required
        self.durability = durability
        self.cause_code = (
            str(getattr(cause, "errno"))
            if cause is not None and getattr(cause, "errno", None) is not None
            else type(cause).__name__ if cause is not None else None
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": "FAIL",
            "reason_code": self.reason_code,
            "message": str(self),
            "phase": self.phase,
            "committed": self.committed,
            "complete": self.complete,
            "recovery_required": self.recovery_required,
            "durability": self.durability,
            "cause_code": self.cause_code,
        }


@dataclass(frozen=True)
class RootAuthority:
    path: Path
    fd: int
    identity: tuple[int, int]
    uid: int
    mode: int

    def revalidate(self, *, phase: str) -> None:
        try:
            opened = os.fstat(self.fd)
            current = self.path.lstat()
        except OSError as error:
            raise AstGrepInstallError(
                "ast_grep_root_changed",
                "managed ast-grep root became unavailable",
                phase=phase,
                cause=error,
            ) from error
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or (opened.st_dev, opened.st_ino) != self.identity
            or (current.st_dev, current.st_ino) != self.identity
            or opened.st_uid != self.uid
            or current.st_uid != self.uid
            or os.getuid() != os.geteuid()
            or os.geteuid() != self.uid
            or stat.S_IMODE(opened.st_mode) != self.mode
            or stat.S_IMODE(current.st_mode) != self.mode
        ):
            raise AstGrepInstallError(
                "ast_grep_root_changed",
                "managed ast-grep root identity or authority changed",
                phase=phase,
            )


def ast_grep_cache_root() -> Path:
    configured = os.environ.get(AST_GREP_CACHE_ENV, "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".cache" / "my_opencode" / "devtools"
    )


def ast_grep_bin_root() -> Path:
    configured = os.environ.get(AST_GREP_BIN_ENV, "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "bin"
    )


def ast_grep_binary_path(bin_root: Path | None = None) -> Path:
    return (bin_root or ast_grep_bin_root()) / BINARY_NAME


def platform_supported(
    system: str | None = None,
    machine: str | None = None,
) -> bool:
    return (system or platform.system()) == "Darwin" and (
        machine or platform.machine()
    ) == "arm64"


def _platform_gate(system: str | None, machine: str | None) -> tuple[str, str]:
    actual_system = system or platform.system()
    actual_machine = machine or platform.machine()
    if actual_system != "Darwin" or actual_machine != "arm64":
        raise AstGrepInstallError(
            "ast_grep_unsupported_platform",
            f"managed ast-grep supports only Darwin arm64, not {actual_system} {actual_machine}",
            phase="platform",
        )
    if os.getuid() != os.geteuid() or os.geteuid() == 0:
        raise AstGrepInstallError(
            "ast_grep_unsafe_identity",
            "managed ast-grep requires a non-root process with matching uid/euid",
            phase="platform",
        )
    return actual_system, actual_machine


def _absolute_injected_root(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute() or ".." in expanded.parts:
        raise AstGrepInstallError(
            "ast_grep_root_unsafe",
            "managed ast-grep roots must be absolute paths without parent traversal",
            phase="authority",
        )
    return expanded


def _open_root(path: Path) -> RootAuthority:
    root = _absolute_injected_root(path)
    try:
        before = root.lstat()
        fd = os.open(
            root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as error:
        raise AstGrepInstallError(
            "ast_grep_root_unavailable",
            f"managed ast-grep root is unavailable: {root}",
            phase="authority",
            cause=error,
        ) from error
    try:
        opened = os.fstat(fd)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or before.st_uid != os.geteuid()
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != PRIVATE_DIRECTORY_MODE
            or stat.S_IMODE(opened.st_mode) != PRIVATE_DIRECTORY_MODE
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise AstGrepInstallError(
                "ast_grep_root_unsafe",
                f"managed ast-grep root is unsafe: {root}",
                phase="authority",
            )
        authority = RootAuthority(
            root,
            fd,
            (opened.st_dev, opened.st_ino),
            opened.st_uid,
            PRIVATE_DIRECTORY_MODE,
        )
        authority.revalidate(phase="authority")
        return authority
    except BaseException:
        os.close(fd)
        raise


def _close_roots(roots: Sequence[RootAuthority]) -> None:
    for root in roots:
        try:
            os.close(root.fd)
        except OSError:
            pass


def _entry_metadata(root: RootAuthority, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=root.fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise AstGrepInstallError(
            "ast_grep_state_unsafe",
            f"unable to inspect managed ast-grep state: {name}",
            phase="state",
            cause=error,
        ) from error


def _validate_regular(
    metadata: os.stat_result,
    *,
    mode: int,
    max_bytes: int,
    phase: str,
    label: str,
) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != mode
        or metadata.st_size < 0
        or metadata.st_size > max_bytes
    ):
        raise AstGrepInstallError(
            "ast_grep_state_unsafe",
            f"managed ast-grep {label} is unsafe",
            phase=phase,
        )


def _open_regular_at(
    root: RootAuthority,
    name: str,
    *,
    mode: int,
    max_bytes: int,
    phase: str,
    label: str,
) -> tuple[int, os.stat_result]:
    try:
        fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root.fd,
        )
    except OSError as error:
        raise AstGrepInstallError(
            "ast_grep_state_unsafe",
            f"unable to open managed ast-grep {label}",
            phase=phase,
            cause=error,
        ) from error
    try:
        metadata = os.fstat(fd)
        _validate_regular(
            metadata,
            mode=mode,
            max_bytes=max_bytes,
            phase=phase,
            label=label,
        )
        current = _entry_metadata(root, name)
        if current is None or (current.st_dev, current.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise AstGrepInstallError(
                "ast_grep_state_changed",
                f"managed ast-grep {label} changed while opening",
                phase=phase,
            )
        return fd, metadata
    except BaseException:
        os.close(fd)
        raise


def _read_bounded_fd(fd: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    offset = 0
    while total <= max_bytes:
        chunk = os.pread(fd, min(READ_BYTES, max_bytes + 1 - total), offset)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        offset += len(chunk)
    if total > max_bytes:
        raise AstGrepInstallError(
            "ast_grep_state_unsafe",
            "managed ast-grep file exceeds its byte limit",
            phase="state",
        )
    return b"".join(chunks)


def _hash_fd(fd: int, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    offset = 0
    while total <= max_bytes:
        chunk = os.pread(fd, min(READ_BYTES, max_bytes + 1 - total), offset)
        if not chunk:
            break
        total += len(chunk)
        offset += len(chunk)
        digest.update(chunk)
    if total > max_bytes:
        raise AstGrepInstallError(
            "ast_grep_binary_unsafe",
            "managed ast-grep binary exceeds its byte limit",
            phase="verify",
        )
    return digest.hexdigest(), total


def _parse_json_at(root: RootAuthority, name: str, *, label: str) -> dict[str, Any]:
    fd, before = _open_regular_at(
        root,
        name,
        mode=PRIVATE_FILE_MODE,
        max_bytes=MAX_JSON_BYTES,
        phase="state",
        label=label,
    )
    try:
        raw = _read_bounded_fd(fd, MAX_JSON_BYTES)
        after = os.fstat(fd)
        current = _entry_metadata(root, name)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or current is None or (current.st_dev, current.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise AstGrepInstallError(
                "ast_grep_state_changed",
                f"managed ast-grep {label} changed while reading",
                phase="state",
            )
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AstGrepInstallError(
            "ast_grep_state_malformed",
            f"managed ast-grep {label} is malformed",
            phase="state",
            cause=error,
        ) from error
    if not isinstance(payload, dict):
        raise AstGrepInstallError(
            "ast_grep_state_malformed",
            f"managed ast-grep {label} root must be an object",
            phase="state",
        )
    return payload


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short managed ast-grep write")
        view = view[written:]


def _create_json_stage(
    root: RootAuthority,
    name: str,
    payload: dict[str, Any],
    *,
    phase: str,
) -> tuple[int, tuple[int, int]]:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(encoded) > MAX_JSON_BYTES:
        raise AstGrepInstallError(
            "ast_grep_state_unsafe",
            "managed ast-grep metadata exceeds its byte limit",
            phase=phase,
        )
    fd = -1
    try:
        fd = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            PRIVATE_FILE_MODE,
            dir_fd=root.fd,
        )
        os.fchmod(fd, PRIVATE_FILE_MODE)
        _write_all(fd, encoded)
        os.fsync(fd)
        metadata = os.fstat(fd)
        _validate_regular(
            metadata,
            mode=PRIVATE_FILE_MODE,
            max_bytes=MAX_JSON_BYTES,
            phase=phase,
            label=name,
        )
        return fd, (metadata.st_dev, metadata.st_ino)
    except AstGrepInstallError:
        if fd >= 0:
            os.close(fd)
        raise
    except OSError as error:
        if fd >= 0:
            os.close(fd)
        raise AstGrepInstallError(
            "ast_grep_state_write_failed",
            f"unable to write managed ast-grep metadata: {name}",
            phase=phase,
            cause=error,
        ) from error


def _acquire_lock(
    cache: RootAuthority,
    *,
    exclusive: bool,
    create: bool,
    timeout_seconds: float,
) -> int | None:
    flags = os.O_RDWR if exclusive else os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    created = False
    try:
        fd = os.open(LOCK_NAME, flags, dir_fd=cache.fd)
    except FileNotFoundError:
        if not create:
            return None
        try:
            fd = os.open(
                LOCK_NAME,
                flags | os.O_CREAT | os.O_EXCL,
                PRIVATE_FILE_MODE,
                dir_fd=cache.fd,
            )
            created = True
        except FileExistsError:
            fd = os.open(LOCK_NAME, flags, dir_fd=cache.fd)
    try:
        if created:
            os.fchmod(fd, PRIVATE_FILE_MODE)
            os.fsync(fd)
            os.fsync(cache.fd)
        metadata = os.fstat(fd)
        _validate_regular(
            metadata,
            mode=PRIVATE_FILE_MODE,
            max_bytes=0,
            phase="lock",
            label="lock",
        )
        current = _entry_metadata(cache, LOCK_NAME)
        if current is None or (current.st_dev, current.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise AstGrepInstallError(
                "ast_grep_lock_changed",
                "managed ast-grep lock identity changed",
                phase="lock",
            )
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            try:
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise AstGrepInstallError(
                        "ast_grep_install_busy",
                        "managed ast-grep install lock is busy",
                        phase="lock",
                    )
                time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    except BaseException:
        os.close(fd)
        raise


def _release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _journal_payload(artifact: AstGrepArtifact) -> dict[str, Any]:
    return {
        "schema": 1,
        "version": artifact.version,
        "asset": artifact.asset,
        "archive_sha256": artifact.archive_sha256,
        "binary_sha256": artifact.binary_sha256,
        "state": "prepared",
    }


def _validate_journal(payload: dict[str, Any], artifact: AstGrepArtifact) -> None:
    if payload != _journal_payload(artifact):
        raise AstGrepInstallError(
            "ast_grep_journal_invalid",
            "managed ast-grep transaction journal is invalid",
            phase="recovery",
        )


def _attestation_payload(
    artifact: AstGrepArtifact,
    metadata: os.stat_result,
) -> dict[str, Any]:
    return {
        "schema": 1,
        "version": artifact.version,
        "asset": artifact.asset,
        "source_url": artifact.url,
        "archive_sha256": artifact.archive_sha256,
        "binary_sha256": artifact.binary_sha256,
        "binary_size": artifact.binary_size,
        "binary_dev": metadata.st_dev,
        "binary_ino": metadata.st_ino,
        "binary_mode": stat.S_IMODE(metadata.st_mode),
        "version_output": artifact.version_output,
    }


def _binary_evidence(
    root: RootAuthority,
    artifact: AstGrepArtifact,
) -> tuple[os.stat_result, str]:
    fd, before = _open_regular_at(
        root,
        BINARY_NAME,
        mode=EXECUTABLE_MODE,
        max_bytes=MAX_MEMBER_BYTES,
        phase="verify",
        label="binary",
    )
    try:
        digest, size = _hash_fd(fd, MAX_MEMBER_BYTES)
        after = os.fstat(fd)
        current = _entry_metadata(root, BINARY_NAME)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or current is None or (current.st_dev, current.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise AstGrepInstallError(
                "ast_grep_binary_changed",
                "managed ast-grep binary changed while hashing",
                phase="verify",
            )
        if digest != artifact.binary_sha256 or size != artifact.binary_size:
            raise AstGrepInstallError(
                "ast_grep_binary_drift",
                "managed ast-grep binary hash or size drifted",
                phase="verify",
            )
        return after, digest
    finally:
        os.close(fd)


def _validate_attestation(
    cache: RootAuthority,
    binary_metadata: os.stat_result,
    artifact: AstGrepArtifact,
    *,
    name: str = ATTESTATION_NAME,
    label: str = "attestation",
) -> dict[str, Any]:
    payload = _parse_json_at(cache, name, label=label)
    if payload != _attestation_payload(artifact, binary_metadata):
        raise AstGrepInstallError(
            "ast_grep_attestation_drift",
            "managed ast-grep attestation does not match the binary",
            phase="verify",
        )
    return payload


def _fixed_temp_entries(
    cache: RootAuthority,
    bin_root: RootAuthority,
) -> list[tuple[RootAuthority, str, int, int]]:
    return [
        (cache, ARCHIVE_STAGE_NAME, PRIVATE_FILE_MODE, MAX_ARCHIVE_BYTES),
        (bin_root, BINARY_STAGE_NAME, EXECUTABLE_MODE, MAX_MEMBER_BYTES),
        (cache, ATTESTATION_STAGE_NAME, PRIVATE_FILE_MODE, MAX_JSON_BYTES),
    ]


def _cleanup_recovery_temps(
    cache: RootAuthority,
    bin_root: RootAuthority,
) -> None:
    changed: set[int] = set()
    for root, name, expected_mode, max_bytes in _fixed_temp_entries(cache, bin_root):
        metadata = _entry_metadata(root, name)
        if metadata is None:
            continue
        allowed_modes = (
            {PRIVATE_FILE_MODE, EXECUTABLE_MODE}
            if name == BINARY_STAGE_NAME
            else {expected_mode}
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) not in allowed_modes
            or metadata.st_size < 0
            or metadata.st_size > max_bytes
        ):
            raise AstGrepInstallError(
                "ast_grep_state_unsafe",
                f"managed ast-grep recovery stage is unsafe: {name}",
                phase="recovery",
            )
        os.unlink(name, dir_fd=root.fd)
        changed.add(root.fd)
    for fd in changed:
        os.fsync(fd)


def _has_any_temp(cache: RootAuthority, bin_root: RootAuthority) -> bool:
    return any(
        _entry_metadata(root, name) is not None
        for root, name, _mode, _max_bytes in _fixed_temp_entries(cache, bin_root)
    )


def _create_journal(cache: RootAuthority, artifact: AstGrepArtifact) -> None:
    fd, _identity = _create_json_stage(
        cache,
        JOURNAL_NAME,
        _journal_payload(artifact),
        phase="journal",
    )
    os.close(fd)
    os.fsync(cache.fd)


def _remove_journal(cache: RootAuthority) -> None:
    os.unlink(JOURNAL_NAME, dir_fd=cache.fd)
    os.fsync(cache.fd)


def _download_child_environment() -> dict[str, str]:
    return {
        "HOME": "/var/empty",
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "NO_COLOR": "1",
    }


def _download_child_observed_environment_keys() -> list[str]:
    return sorted({*_download_child_environment(), "__CF_USER_TEXT_ENCODING"})


def _production_download(archive_fd: int) -> dict[str, Any]:
    child = Path(__file__).with_name("ast_grep_download_child.py")
    try:
        metadata = child.lstat()
    except OSError as error:
        raise AstGrepInstallError(
            "ast_grep_downloader_unavailable",
            "managed ast-grep downloader child is unavailable",
            phase="download",
            cause=error,
        ) from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise AstGrepInstallError(
            "ast_grep_downloader_unsafe",
            "managed ast-grep downloader child is unsafe",
            phase="download",
        )
    if not sys.executable or not Path(sys.executable).is_absolute():
        raise AstGrepInstallError(
            "ast_grep_downloader_unavailable",
            "managed ast-grep requires an absolute Python interpreter",
            phase="download",
        )
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                str(child),
                str(archive_fd),
            ],
            pass_fds=(archive_fd,),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_download_child_environment(),
            start_new_session=True,
        )
    except OSError as error:
        raise AstGrepInstallError(
            "ast_grep_download_failed",
            "unable to start managed ast-grep downloader",
            phase="download",
            cause=error,
        ) from error
    try:
        stdout, stderr = process.communicate(timeout=DOWNLOAD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        _terminate_process_group(process)
        process.communicate()
        raise AstGrepInstallError(
            "ast_grep_download_timeout",
            "managed ast-grep download exceeded its total deadline",
            phase="download",
            cause=error,
        ) from error
    if _process_group_exists(process.pid):
        _terminate_process_group(process)
        raise AstGrepInstallError(
            "ast_grep_download_survivor",
            "managed ast-grep downloader left a surviving process",
            phase="download",
        )
    if (
        process.returncode != 0
        or len(stdout) > MAX_JSON_BYTES
        or len(stderr) > MAX_JSON_BYTES
        or stderr != ""
    ):
        raise AstGrepInstallError(
            "ast_grep_download_failed",
            "managed ast-grep downloader failed closed",
            phase="download",
        )
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise AstGrepInstallError(
            "ast_grep_download_failed",
            "managed ast-grep downloader returned malformed evidence",
            phase="download",
            cause=error,
        ) from error
    if not isinstance(report, dict) or report.get("result") != "PASS":
        raise AstGrepInstallError(
            "ast_grep_download_failed",
            "managed ast-grep downloader returned invalid evidence",
            phase="download",
        )
    if (
        report.get("initial_host") != "github.com"
        or report.get("asset_url") != AST_GREP_URL
        or type(report.get("redirect_count")) is not int
        or not 0 <= report["redirect_count"] <= 3
        or not isinstance(report.get("redirect_hosts"), list)
        or len(report["redirect_hosts"]) != report["redirect_count"]
        or any(
            host not in {"github.com", "release-assets.githubusercontent.com"}
            for host in report["redirect_hosts"]
        )
        or type(report.get("bytes")) is not int
        or not 0 < report["bytes"] <= MAX_ARCHIVE_BYTES
        or not isinstance(report.get("sha256"), str)
        or len(report["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in report["sha256"])
        or report.get("archive_fd") != archive_fd
        or report.get("inherited_fds") != sorted({0, 1, 2, archive_fd})
        or report.get("environment_keys") != _download_child_observed_environment_keys()
        or report.get("pid") != process.pid
        or report.get("process_group_id") != process.pid
    ):
        raise AstGrepInstallError(
            "ast_grep_download_failed",
            "managed ast-grep downloader evidence failed validation",
            phase="download",
        )
    return {**report, "surviving_processes": 0}


def _create_archive_stage(cache: RootAuthority) -> tuple[int, tuple[int, int]]:
    fd = -1
    try:
        fd = os.open(
            ARCHIVE_STAGE_NAME,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            PRIVATE_FILE_MODE,
            dir_fd=cache.fd,
        )
        os.fchmod(fd, PRIVATE_FILE_MODE)
        metadata = os.fstat(fd)
        _validate_regular(
            metadata,
            mode=PRIVATE_FILE_MODE,
            max_bytes=MAX_ARCHIVE_BYTES,
            phase="download",
            label="archive stage",
        )
        return fd, (metadata.st_dev, metadata.st_ino)
    except AstGrepInstallError:
        if fd >= 0:
            os.close(fd)
        raise
    except OSError as error:
        if fd >= 0:
            os.close(fd)
        raise AstGrepInstallError(
            "ast_grep_stage_failed",
            "unable to create managed ast-grep archive stage",
            phase="download",
            cause=error,
        ) from error


def _validate_archive(
    archive_fd: int,
    artifact: AstGrepArtifact,
) -> tuple[zipfile.ZipFile, zipfile.ZipInfo, Any, list[dict[str, Any]]]:
    metadata = os.fstat(archive_fd)
    _validate_regular(
        metadata,
        mode=PRIVATE_FILE_MODE,
        max_bytes=MAX_ARCHIVE_BYTES,
        phase="archive",
        label="archive stage",
    )
    digest, size = _hash_fd(archive_fd, MAX_ARCHIVE_BYTES)
    if digest != artifact.archive_sha256 or size != artifact.archive_size:
        raise AstGrepInstallError(
            "ast_grep_archive_hash_mismatch",
            "managed ast-grep archive hash or size mismatched its pin",
            phase="archive",
        )
    duplicate = os.dup(archive_fd)
    os.lseek(duplicate, 0, os.SEEK_SET)
    source = os.fdopen(duplicate, "rb")
    try:
        archive = zipfile.ZipFile(source, "r")
    except (OSError, zipfile.BadZipFile) as error:
        source.close()
        raise AstGrepInstallError(
            "ast_grep_archive_invalid",
            "managed ast-grep archive is invalid",
            phase="archive",
            cause=error,
        ) from error
    try:
        if archive.comment != b"":
            raise AstGrepInstallError(
                "ast_grep_archive_invalid",
                "managed ast-grep archive comment mismatched",
                phase="archive",
            )
        entries = archive.infolist()
        if len(entries) != len(artifact.entries) or len(entries) > 2:
            raise AstGrepInstallError(
                "ast_grep_archive_invalid",
                "managed ast-grep archive entry count mismatched",
                phase="archive",
            )
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise AstGrepInstallError(
                "ast_grep_archive_invalid",
                "managed ast-grep archive contains duplicate names",
                phase="archive",
            )
        total_size = 0
        total_compressed = 0
        for entry, expected in zip(entries, artifact.entries, strict=True):
            if (
                entry.filename != expected.name
                or entry.filename in {"", ".", ".."}
                or "/" in entry.filename
                or "\\" in entry.filename
                or "\x00" in entry.filename
                or entry.file_size != expected.file_size
                or entry.compress_size != expected.compress_size
                or entry.CRC != expected.crc
                or entry.external_attr != expected.external_attr
                or entry.create_system != expected.create_system
                or entry.flag_bits != expected.flag_bits
                or entry.compress_type != expected.compress_type
                or entry.extra != expected.extra
                or entry.comment != expected.comment
                or entry.flag_bits & 0x41
                or not stat.S_ISREG(entry.external_attr >> 16)
                or (entry.external_attr >> 16) & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX)
                or entry.file_size > MAX_MEMBER_BYTES
                or entry.compress_size > MAX_ARCHIVE_BYTES
                or (
                    entry.file_size > 0
                    and (
                        entry.compress_size <= 0
                        or entry.file_size
                        > entry.compress_size * MAX_COMPRESSION_RATIO
                    )
                )
            ):
                raise AstGrepInstallError(
                    "ast_grep_archive_invalid",
                    f"managed ast-grep archive entry mismatched: {entry.filename}",
                    phase="archive",
                )
            total_size += entry.file_size
            total_compressed += entry.compress_size
        if (
            total_size > MAX_TOTAL_BYTES
            or total_compressed > MAX_ARCHIVE_BYTES
            or total_size > total_compressed * MAX_COMPRESSION_RATIO
        ):
            raise AstGrepInstallError(
                "ast_grep_archive_invalid",
                "managed ast-grep archive aggregate limits failed",
                phase="archive",
            )
        target = entries[-1]
        if target.filename != BINARY_NAME:
            raise AstGrepInstallError(
                "ast_grep_archive_invalid",
                "managed ast-grep archive target entry is missing",
                phase="archive",
            )
        profile = [
            {
                "name": item.filename,
                "file_size": item.file_size,
                "compress_size": item.compress_size,
                "crc32": f"{item.CRC:08x}",
                "external_attr": f"{item.external_attr:08x}",
                "create_system": item.create_system,
                "flag_bits": item.flag_bits,
                "compress_type": item.compress_type,
                "extra_hex": item.extra.hex(),
                "comment_hex": item.comment.hex(),
            }
            for item in entries
        ]
        return archive, target, source, profile
    except BaseException:
        archive.close()
        source.close()
        raise


def _extract_binary_stage(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    bin_root: RootAuthority,
    artifact: AstGrepArtifact,
) -> tuple[int, tuple[int, int]]:
    try:
        fd = os.open(
            BINARY_STAGE_NAME,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            PRIVATE_FILE_MODE,
            dir_fd=bin_root.fd,
        )
        os.fchmod(fd, PRIVATE_FILE_MODE)
        digest = hashlib.sha256()
        total = 0
        with archive.open(entry, "r") as source:
            while total <= MAX_MEMBER_BYTES:
                chunk = source.read(min(READ_BYTES, MAX_MEMBER_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_MEMBER_BYTES:
                    raise AstGrepInstallError(
                        "ast_grep_binary_unsafe",
                        "managed ast-grep binary exceeded its byte limit",
                        phase="extract",
                    )
                digest.update(chunk)
                _write_all(fd, chunk)
        if total != artifact.binary_size or digest.hexdigest() != artifact.binary_sha256:
            raise AstGrepInstallError(
                "ast_grep_binary_hash_mismatch",
                "managed ast-grep extracted binary mismatched its pin",
                phase="extract",
            )
        os.fchmod(fd, EXECUTABLE_MODE)
        metadata = os.fstat(fd)
        _validate_regular(
            metadata,
            mode=EXECUTABLE_MODE,
            max_bytes=MAX_MEMBER_BYTES,
            phase="extract",
            label="binary stage",
        )
        if metadata.st_size != artifact.binary_size:
            raise AstGrepInstallError(
                "ast_grep_binary_hash_mismatch",
                "managed ast-grep stage size changed",
                phase="extract",
            )
        os.fsync(fd)
        return fd, (metadata.st_dev, metadata.st_ino)
    except AstGrepInstallError:
        if "fd" in locals():
            os.close(fd)
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        if "fd" in locals():
            os.close(fd)
        raise AstGrepInstallError(
            "ast_grep_extract_failed",
            "unable to extract managed ast-grep binary",
            phase="extract",
            cause=error,
        ) from error


@dataclass
class _Capture:
    limit: int
    data: bytearray
    total: int = 0
    overflow: bool = False

    def append(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if self.total > self.limit:
            self.overflow = True
        remaining = max(0, self.limit - len(self.data))
        self.data.extend(chunk[:remaining])


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False


def _signal_process_group(process_group: int, signal_number: int) -> None:
    try:
        os.killpg(process_group, signal_number)
    except ProcessLookupError:
        pass


def _wait_process_group_gone(process_group: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while _process_group_exists(process_group):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def _terminate_process_group(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    *,
    term_timeout: float = 0.5,
    kill_timeout: float = 1.0,
) -> bool:
    process_group = process.pid
    survivor_detected = False
    if process.poll() is None or _process_group_exists(process_group):
        _signal_process_group(process_group, signal.SIGTERM)
    try:
        process.wait(timeout=term_timeout)
    except subprocess.TimeoutExpired:
        survivor_detected = True
    if _process_group_exists(process_group):
        survivor_detected = True
        _signal_process_group(process_group, signal.SIGKILL)
        if not _wait_process_group_gone(process_group, kill_timeout):
            raise AstGrepInstallError(
                "ast_grep_process_survivor",
                "managed ast-grep process group survived forced termination",
                phase="execute",
            )
    if process.poll() is None:
        try:
            process.wait(timeout=kill_timeout)
        except subprocess.TimeoutExpired as error:
            raise AstGrepInstallError(
                "ast_grep_process_survivor",
                "managed ast-grep process leader could not be reaped",
                phase="execute",
                cause=error,
            ) from error
    return survivor_detected


def _bounded_process(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as error:
        raise AstGrepInstallError(
            "ast_grep_version_failed",
            "unable to start staged ast-grep",
            phase="execute",
            cause=error,
        ) from error
    selector = selectors.DefaultSelector()
    captures = {
        "stdout": _Capture(MAX_PROCESS_OUTPUT_BYTES, bytearray()),
        "stderr": _Capture(MAX_PROCESS_OUTPUT_BYTES, bytearray()),
    }
    for name in ("stdout", "stderr"):
        stream = getattr(process, name)
        assert stream is not None
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    deadline = time.monotonic() + VERSION_TIMEOUT_SECONDS
    failed_bound = False
    survivor_detected = False
    timed_out = False
    try:
        while time.monotonic() < deadline:
            for key, _mask in selector.select(0.05):
                chunk = os.read(key.fileobj.fileno(), READ_BYTES)
                if chunk:
                    captures[str(key.data)].append(chunk)
                    continue
                selector.unregister(key.fileobj)
                key.fileobj.close()
            if any(capture.overflow for capture in captures.values()):
                failed_bound = True
                break
            if process.poll() is not None and not selector.get_map():
                break
        timed_out = process.poll() is None or bool(selector.get_map())
        if timed_out or failed_bound:
            survivor_detected = _terminate_process_group(process)
        drain_deadline = time.monotonic() + 1
        while selector.get_map() and time.monotonic() < drain_deadline:
            for key, _mask in selector.select(0.05):
                chunk = os.read(key.fileobj.fileno(), READ_BYTES)
                if chunk:
                    captures[str(key.data)].append(chunk)
                else:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
        returncode = process.wait(timeout=1)
        if _process_group_exists(process.pid):
            survivor_detected = _terminate_process_group(process) or True
    finally:
        for key in list(selector.get_map().values()):
            try:
                selector.unregister(key.fileobj)
            except KeyError:
                pass
            key.fileobj.close()
        selector.close()
        if process.poll() is None or _process_group_exists(process.pid):
            survivor_detected = _terminate_process_group(process) or survivor_detected
    return {
        "returncode": returncode,
        "stdout": bytes(captures["stdout"].data),
        "stderr": bytes(captures["stderr"].data),
        "stdout_total": captures["stdout"].total,
        "stderr_total": captures["stderr"].total,
        "overflow": failed_bound,
        "timed_out": timed_out,
        "survivor": survivor_detected,
        "surviving_processes": 0,
    }


def _version_environment(cache_root: RootAuthority) -> dict[str, str]:
    return {
        "HOME": str(cache_root.path),
        "TMPDIR": str(cache_root.path),
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "NO_COLOR": "1",
    }


def _verify_executable(
    root: RootAuthority,
    runtime_root: RootAuthority,
    name: str,
    expected_identity: tuple[int, int],
    fd: int,
    artifact: AstGrepArtifact,
) -> dict[str, Any]:
    root.revalidate(phase="execute")
    current = _entry_metadata(root, name)
    opened = os.fstat(fd)
    if current is None or (current.st_dev, current.st_ino) != expected_identity or (
        opened.st_dev,
        opened.st_ino,
    ) != expected_identity:
        raise AstGrepInstallError(
            "ast_grep_stage_changed",
            "managed ast-grep executable changed before execution",
            phase="execute",
        )
    before_hash, before_size = _hash_fd(fd, MAX_MEMBER_BYTES)
    if before_hash != artifact.binary_sha256 or before_size != artifact.binary_size:
        raise AstGrepInstallError(
            "ast_grep_binary_hash_mismatch",
            "managed ast-grep executable mismatched before execution",
            phase="execute",
        )
    before_root_entries = tuple(sorted(os.listdir(root.fd)))
    before_runtime_entries = tuple(sorted(os.listdir(runtime_root.fd)))
    report = _bounded_process(
        [str(root.path / name), "--version"],
        cwd=root.path,
        env=_version_environment(runtime_root),
    )
    after_root_entries = tuple(sorted(os.listdir(root.fd)))
    after_runtime_entries = tuple(sorted(os.listdir(runtime_root.fd)))
    after_hash, after_size = _hash_fd(fd, MAX_MEMBER_BYTES)
    current = _entry_metadata(root, name)
    opened = os.fstat(fd)
    if (
        report["timed_out"]
        or report["overflow"]
        or report["survivor"]
        or report["returncode"] != 0
        or report["stderr"] != b""
        or report["stdout"].decode("utf-8", errors="strict").strip()
        != artifact.version_output
        or after_hash != before_hash
        or after_size != before_size
        or current is None
        or (current.st_dev, current.st_ino) != expected_identity
        or (opened.st_dev, opened.st_ino) != expected_identity
        or before_root_entries != after_root_entries
        or before_runtime_entries != after_runtime_entries
    ):
        raise AstGrepInstallError(
            "ast_grep_version_failed",
            "managed ast-grep staged version verification failed closed",
            phase="execute",
        )
    return report


def rename_exclusive(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    for name in (source_name, target_name):
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise AstGrepInstallError(
                "ast_grep_publish_failed",
                "managed ast-grep publish name is unsafe",
                phase="publish",
            )
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        function = libc.renameatx_np
    except AttributeError as error:
        raise AstGrepInstallError(
            "ast_grep_publish_unsupported",
            "Darwin exclusive rename is unavailable",
            phase="publish",
            cause=error,
        ) from error
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = function(
        source_dir_fd,
        os.fsencode(source_name),
        target_dir_fd,
        os.fsencode(target_name),
        RENAME_EXCL,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == 0:
            raise AstGrepInstallError(
                "ast_grep_publish_failed",
                "Darwin exclusive rename failed without errno",
                phase="publish",
            )
        reason = (
            "ast_grep_destination_exists"
            if error_number == errno.EEXIST
            else "ast_grep_publish_unsupported"
            if error_number in {errno.ENOTSUP, errno.EINVAL}
            else "ast_grep_publish_failed"
        )
        raise AstGrepInstallError(
            reason,
            "managed ast-grep exclusive publication failed",
            phase="publish",
            cause=OSError(error_number, os.strerror(error_number), target_name),
        )


def _stage_identity(root: RootAuthority, name: str, fd: int) -> tuple[int, int]:
    opened = os.fstat(fd)
    current = _entry_metadata(root, name)
    if current is None or (current.st_dev, current.st_ino) != (
        opened.st_dev,
        opened.st_ino,
    ):
        raise AstGrepInstallError(
            "ast_grep_stage_changed",
            "managed ast-grep stage identity changed",
            phase="publish",
        )
    return opened.st_dev, opened.st_ino


def _stage_attestation(
    cache: RootAuthority,
    artifact: AstGrepArtifact,
    binary_metadata: os.stat_result,
) -> tuple[int, tuple[int, int]]:
    fd, identity = _create_json_stage(
        cache,
        ATTESTATION_STAGE_NAME,
        _attestation_payload(artifact, binary_metadata),
        phase="attestation",
    )
    try:
        os.fsync(cache.fd)
    except BaseException:
        os.close(fd)
        raise
    return fd, identity


def _publish_staged_attestation(
    cache: RootAuthority,
    bin_root: RootAuthority,
    artifact: AstGrepArtifact,
    stage_fd: int,
    stage_identity: tuple[int, int],
    renamer: Callable[[int, str, int, str], None],
    failure_injector: Callable[[str], None] | None,
) -> None:
    binary_metadata, _digest = _binary_evidence(bin_root, artifact)
    _validate_attestation(
        cache,
        binary_metadata,
        artifact,
        name=ATTESTATION_STAGE_NAME,
        label="attestation stage",
    )
    cache.revalidate(phase="attestation")
    bin_root.revalidate(phase="attestation")
    if _stage_identity(cache, ATTESTATION_STAGE_NAME, stage_fd) != stage_identity:
        raise AstGrepInstallError(
            "ast_grep_stage_changed",
            "managed ast-grep attestation stage changed",
            phase="attestation",
        )
    if _entry_metadata(cache, ATTESTATION_NAME) is not None:
        raise AstGrepInstallError(
            "ast_grep_attestation_exists",
            "managed ast-grep attestation appeared before publication",
            phase="attestation",
        )
    if failure_injector is not None:
        failure_injector("before_attestation_publish")
    cache.revalidate(phase="attestation")
    renamer(cache.fd, ATTESTATION_STAGE_NAME, cache.fd, ATTESTATION_NAME)
    published = _entry_metadata(cache, ATTESTATION_NAME)
    if published is None or (published.st_dev, published.st_ino) != stage_identity:
        raise AstGrepInstallError(
            "ast_grep_stage_changed",
            "managed ast-grep attestation identity changed during publication",
            phase="attestation",
        )
    if failure_injector is not None:
        failure_injector("after_attestation_publish")
    os.fsync(cache.fd)


def _remove_archive_stage(
    cache: RootAuthority,
    expected_identity: tuple[int, int],
) -> None:
    metadata = _entry_metadata(cache, ARCHIVE_STAGE_NAME)
    if metadata is None:
        return
    _validate_regular(
        metadata,
        mode=PRIVATE_FILE_MODE,
        max_bytes=MAX_ARCHIVE_BYTES,
        phase="cleanup",
        label="archive stage",
    )
    if (metadata.st_dev, metadata.st_ino) != expected_identity:
        raise AstGrepInstallError(
            "ast_grep_stage_changed",
            "managed ast-grep archive stage identity changed before cleanup",
            phase="cleanup",
        )
    os.unlink(ARCHIVE_STAGE_NAME, dir_fd=cache.fd)
    os.fsync(cache.fd)


def _installed_state(
    cache: RootAuthority,
    bin_root: RootAuthority,
    artifact: AstGrepArtifact,
) -> tuple[str, os.stat_result | None]:
    journal_metadata = _entry_metadata(cache, JOURNAL_NAME)
    binary_metadata = _entry_metadata(bin_root, BINARY_NAME)
    attestation_metadata = _entry_metadata(cache, ATTESTATION_NAME)
    has_temps = _has_any_temp(cache, bin_root)
    if journal_metadata is None:
        if has_temps:
            raise AstGrepInstallError(
                "ast_grep_unmanaged_temporary",
                "managed ast-grep temporary artifact exists without a journal",
                phase="state",
            )
        if binary_metadata is None and attestation_metadata is None:
            return "fresh", None
        if binary_metadata is None or attestation_metadata is None:
            raise AstGrepInstallError(
                "ast_grep_unmanaged_existing",
                "managed ast-grep binary/attestation state is incomplete",
                phase="state",
            )
        evidence, _digest = _binary_evidence(bin_root, artifact)
        _validate_attestation(cache, evidence, artifact)
        return "installed", evidence

    journal = _parse_json_at(cache, JOURNAL_NAME, label="journal")
    _validate_journal(journal, artifact)
    binary_metadata = _entry_metadata(bin_root, BINARY_NAME)
    attestation_metadata = _entry_metadata(cache, ATTESTATION_NAME)
    if binary_metadata is None and attestation_metadata is None:
        _cleanup_recovery_temps(cache, bin_root)
        return "resume_pre_publish", None
    if binary_metadata is not None and attestation_metadata is None:
        archive_stage = _entry_metadata(cache, ARCHIVE_STAGE_NAME)
        binary_stage = _entry_metadata(bin_root, BINARY_STAGE_NAME)
        attestation_stage = _entry_metadata(cache, ATTESTATION_STAGE_NAME)
        if archive_stage is not None or binary_stage is not None or attestation_stage is None:
            raise AstGrepInstallError(
                "ast_grep_recovery_inconsistent",
                "managed ast-grep binary cannot be attributed to this transaction",
                phase="recovery",
            )
        evidence, _digest = _binary_evidence(bin_root, artifact)
        _validate_attestation(
            cache,
            evidence,
            artifact,
            name=ATTESTATION_STAGE_NAME,
            label="attestation stage",
        )
        return "resume_attestation", evidence
    if binary_metadata is not None and attestation_metadata is not None:
        evidence, _digest = _binary_evidence(bin_root, artifact)
        _validate_attestation(cache, evidence, artifact)
        _cleanup_recovery_temps(cache, bin_root)
        return "resume_cleanup", evidence
    raise AstGrepInstallError(
        "ast_grep_recovery_inconsistent",
        "managed ast-grep recovery state is inconsistent",
        phase="recovery",
    )


def install_ast_grep(
    *,
    cache_root: Path | None = None,
    bin_root: Path | None = None,
    _artifact: AstGrepArtifact = DEFAULT_ARTIFACT,
    _system: str | None = None,
    _machine: str | None = None,
    _downloader: Callable[[int], dict[str, Any]] | None = None,
    _exclusive_renamer: Callable[[int, str, int, str], None] = rename_exclusive,
    _failure_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    _platform_gate(_system, _machine)
    cache = _open_root(cache_root or ast_grep_cache_root())
    bin_authority: RootAuthority | None = None
    lock_fd: int | None = None
    committed = False
    durability: Durability = "not_committed"
    journal_active = False
    downloaded = False
    download_report: dict[str, Any] | None = None
    archive_profile: list[dict[str, Any]] | None = None
    version_report: dict[str, Any] | None = None
    try:
        bin_authority = _open_root(bin_root or ast_grep_bin_root())
        if cache.identity == bin_authority.identity:
            raise AstGrepInstallError(
                "ast_grep_root_unsafe",
                "managed ast-grep cache and bin roots must be distinct",
                phase="authority",
            )
        lock_fd = _acquire_lock(
            cache,
            exclusive=True,
            create=True,
            timeout_seconds=LOCK_TIMEOUT_SECONDS,
        )
        assert lock_fd is not None
        cache.revalidate(phase="state")
        bin_authority.revalidate(phase="state")
        journal_active = _entry_metadata(cache, JOURNAL_NAME) is not None
        state, binary_metadata = _installed_state(cache, bin_authority, _artifact)
        if state == "installed":
            return {
                "result": "PASS",
                "changed": False,
                "downloaded": False,
                "committed": True,
                "complete": True,
                "recovery_required": False,
                "durability": "synced",
                "path": str(bin_authority.path / BINARY_NAME),
                "version": _artifact.version,
            }
        if state == "resume_cleanup":
            committed = True
            durability = "uncertain"
            os.fsync(bin_authority.fd)
            os.fsync(cache.fd)
            durability = "synced"
            _remove_journal(cache)
            journal_active = False
            return {
                "result": "PASS",
                "changed": True,
                "downloaded": False,
                "committed": True,
                "complete": True,
                "recovery_required": False,
                "durability": "synced",
                "path": str(bin_authority.path / BINARY_NAME),
                "version": _artifact.version,
            }
        if state == "resume_attestation":
            assert binary_metadata is not None
            committed = True
            durability = "uncertain"
            binary_fd, opened = _open_regular_at(
                bin_authority,
                BINARY_NAME,
                mode=EXECUTABLE_MODE,
                max_bytes=MAX_MEMBER_BYTES,
                phase="recovery",
                label="binary",
            )
            try:
                attestation_fd, attestation_opened = _open_regular_at(
                    cache,
                    ATTESTATION_STAGE_NAME,
                    mode=PRIVATE_FILE_MODE,
                    max_bytes=MAX_JSON_BYTES,
                    phase="recovery",
                    label="attestation stage",
                )
                try:
                    _verify_executable(
                        bin_authority,
                        cache,
                        BINARY_NAME,
                        (opened.st_dev, opened.st_ino),
                        binary_fd,
                        _artifact,
                    )
                    os.fsync(bin_authority.fd)
                    durability = "synced"
                    _publish_staged_attestation(
                        cache,
                        bin_authority,
                        _artifact,
                        attestation_fd,
                        (attestation_opened.st_dev, attestation_opened.st_ino),
                        _exclusive_renamer,
                        _failure_injector,
                    )
                finally:
                    os.close(attestation_fd)
            finally:
                os.close(binary_fd)
            _remove_journal(cache)
            journal_active = False
            return {
                "result": "PASS",
                "changed": True,
                "downloaded": False,
                "committed": True,
                "complete": True,
                "recovery_required": False,
                "durability": "synced",
                "path": str(bin_authority.path / BINARY_NAME),
                "version": _artifact.version,
            }

        if state == "fresh":
            journal_active = True
            _create_journal(cache, _artifact)
            if _failure_injector is not None:
                _failure_injector("after_journal_sync")
        binary_fd: int | None = None
        attestation_fd: int | None = None
        archive_fd, archive_identity = _create_archive_stage(cache)
        try:
            cache.revalidate(phase="download")
            bin_authority.revalidate(phase="download")
            if _failure_injector is not None:
                _failure_injector("before_download")
            report = (_downloader or _production_download)(archive_fd)
            download_report = dict(report)
            downloaded = True
            os.fsync(archive_fd)
            if _failure_injector is not None:
                _failure_injector("after_download_sync")
            if report.get("sha256") not in {None, _artifact.archive_sha256}:
                raise AstGrepInstallError(
                    "ast_grep_archive_hash_mismatch",
                    "managed ast-grep downloader evidence mismatched",
                    phase="download",
                )
            cache.revalidate(phase="archive")
            bin_authority.revalidate(phase="archive")
            archive, entry, archive_source, archive_profile = _validate_archive(
                archive_fd,
                _artifact,
            )
            try:
                binary_fd, binary_identity = _extract_binary_stage(
                    archive,
                    entry,
                    bin_authority,
                    _artifact,
                )
                if _failure_injector is not None:
                    _failure_injector("after_extract_sync")
            except BaseException:
                if binary_fd is not None:
                    os.close(binary_fd)
                    binary_fd = None
                raise
            finally:
                archive.close()
                archive_source.close()
        finally:
            os.close(archive_fd)
        assert binary_fd is not None
        try:
            _remove_archive_stage(cache, archive_identity)
            cache.revalidate(phase="execute")
            bin_authority.revalidate(phase="execute")
            version_report = _verify_executable(
                bin_authority,
                cache,
                BINARY_STAGE_NAME,
                binary_identity,
                binary_fd,
                _artifact,
            )
            if _failure_injector is not None:
                _failure_injector("after_version_verify")
            staged_binary_metadata = os.fstat(binary_fd)
            attestation_fd, attestation_identity = _stage_attestation(
                cache,
                _artifact,
                staged_binary_metadata,
            )
            if _failure_injector is not None:
                _failure_injector("after_attestation_stage_sync")
            if _failure_injector is not None:
                _failure_injector("before_binary_publish")
            cache.revalidate(phase="publish")
            bin_authority.revalidate(phase="publish")
            if _stage_identity(bin_authority, BINARY_STAGE_NAME, binary_fd) != binary_identity:
                raise AstGrepInstallError(
                    "ast_grep_stage_changed",
                    "managed ast-grep binary stage changed before publication",
                    phase="publish",
                )
            if _entry_metadata(bin_authority, BINARY_NAME) is not None:
                raise AstGrepInstallError(
                    "ast_grep_destination_exists",
                    "managed ast-grep destination appeared before publication",
                    phase="publish",
                )
            _exclusive_renamer(
                bin_authority.fd,
                BINARY_STAGE_NAME,
                bin_authority.fd,
                BINARY_NAME,
            )
            committed = True
            durability = "uncertain"
            published = _entry_metadata(bin_authority, BINARY_NAME)
            if published is None or (published.st_dev, published.st_ino) != binary_identity:
                raise AstGrepInstallError(
                    "ast_grep_stage_changed",
                    "managed ast-grep binary identity changed during publication",
                    phase="publish",
                )
            if _failure_injector is not None:
                _failure_injector("after_binary_publish")
            os.fsync(bin_authority.fd)
            durability = "synced"
            if _failure_injector is not None:
                _failure_injector("after_binary_sync")
        except BaseException:
            if attestation_fd is not None:
                os.close(attestation_fd)
                attestation_fd = None
            raise
        finally:
            os.close(binary_fd)
        assert attestation_fd is not None
        try:
            _publish_staged_attestation(
                cache,
                bin_authority,
                _artifact,
                attestation_fd,
                attestation_identity,
                _exclusive_renamer,
                _failure_injector,
            )
        finally:
            os.close(attestation_fd)
        if _failure_injector is not None:
            _failure_injector("after_attestation_sync")
            _failure_injector("before_journal_remove")
        _remove_journal(cache)
        journal_active = False
        return {
            "result": "PASS",
            "changed": True,
            "downloaded": downloaded,
            "committed": True,
            "complete": True,
            "recovery_required": False,
            "durability": "synced",
            "path": str(bin_authority.path / BINARY_NAME),
            "version": _artifact.version,
            "download": download_report,
            "archive_profile": archive_profile,
            "version_observed": (
                version_report["stdout"].decode("utf-8", errors="strict").strip()
                if version_report is not None
                else None
            ),
            "downloader_survivors": (
                download_report.get("surviving_processes", 0)
                if download_report is not None
                else 0
            ),
        }
    except AstGrepInstallError as error:
        if committed:
            error.committed = True
            error.complete = False
            error.recovery_required = True
            error.durability = durability
        elif journal_active:
            error.recovery_required = True
        raise
    except BaseException as cause:
        raise AstGrepInstallError(
            "ast_grep_install_failed",
            "managed ast-grep installation failed",
            phase="install",
            committed=committed,
            complete=False,
            recovery_required=journal_active,
            durability=durability,
            cause=cause,
        ) from cause
    finally:
        _release_lock(lock_fd)
        roots = [cache]
        if bin_authority is not None:
            roots.append(bin_authority)
        _close_roots(roots)


def _status_without_lock(
    cache: RootAuthority,
    bin_root: RootAuthority,
) -> str:
    fixed_cache = (
        JOURNAL_NAME,
        ARCHIVE_STAGE_NAME,
        ATTESTATION_STAGE_NAME,
        ATTESTATION_NAME,
    )
    fixed_bin = (BINARY_STAGE_NAME, BINARY_NAME)
    first = any(_entry_metadata(cache, name) is not None for name in fixed_cache) or any(
        _entry_metadata(bin_root, name) is not None for name in fixed_bin
    )
    if _entry_metadata(cache, LOCK_NAME) is not None:
        return "busy"
    return "recovery_required" if first else "missing"


def ast_grep_status(
    *,
    cache_root: Path | None = None,
    bin_root: Path | None = None,
    _artifact: AstGrepArtifact = DEFAULT_ARTIFACT,
    _system: str | None = None,
    _machine: str | None = None,
) -> dict[str, Any]:
    actual_system = _system or platform.system()
    actual_machine = _machine or platform.machine()
    base = {
        "managed": True,
        "version": _artifact.version,
        "platform": f"{actual_system}-{actual_machine}",
        "platform_supported": platform_supported(actual_system, actual_machine),
        "path": str(ast_grep_binary_path(bin_root)),
        "archive_sha256": _artifact.archive_sha256,
        "binary_sha256": _artifact.binary_sha256,
    }
    if not base["platform_supported"]:
        return {**base, "ready": False, "state": "unsupported"}
    if os.getuid() != os.geteuid() or os.geteuid() == 0:
        return {**base, "ready": False, "state": "unsafe_identity"}
    cache: RootAuthority | None = None
    bin_authority: RootAuthority | None = None
    lock_fd: int | None = None
    try:
        cache = _open_root(cache_root or ast_grep_cache_root())
        bin_authority = _open_root(bin_root or ast_grep_bin_root())
        if cache.identity == bin_authority.identity:
            raise AstGrepInstallError(
                "ast_grep_root_unsafe",
                "managed ast-grep roots alias",
                phase="authority",
            )
        lock_fd = _acquire_lock(
            cache,
            exclusive=False,
            create=False,
            timeout_seconds=0,
        )
        if lock_fd is None:
            state = _status_without_lock(cache, bin_authority)
            return {**base, "ready": False, "state": state}
        cache.revalidate(phase="doctor")
        bin_authority.revalidate(phase="doctor")
        journal = _entry_metadata(cache, JOURNAL_NAME)
        if journal is not None:
            _validate_journal(
                _parse_json_at(cache, JOURNAL_NAME, label="journal"),
                _artifact,
            )
            return {**base, "ready": False, "state": "recovery_required"}
        if _has_any_temp(cache, bin_authority):
            return {**base, "ready": False, "state": "unmanaged_temporary"}
        binary = _entry_metadata(bin_authority, BINARY_NAME)
        attestation = _entry_metadata(cache, ATTESTATION_NAME)
        if binary is None and attestation is None:
            return {**base, "ready": False, "state": "missing"}
        if binary is None or attestation is None:
            return {**base, "ready": False, "state": "unmanaged_existing"}
        evidence, digest = _binary_evidence(bin_authority, _artifact)
        _validate_attestation(cache, evidence, _artifact)
        return {
            **base,
            "ready": True,
            "state": "verified",
            "observed_binary_sha256": digest,
            "binary_size": evidence.st_size,
        }
    except AstGrepInstallError as error:
        if error.reason_code == "ast_grep_install_busy":
            return {**base, "ready": False, "state": "busy"}
        return {
            **base,
            "ready": False,
            "state": "drift",
            "reason_code": error.reason_code,
        }
    finally:
        _release_lock(lock_fd)
        roots = [item for item in (cache, bin_authority) if item is not None]
        _close_roots(roots)
