from __future__ import annotations

import errno
import fcntl
import hashlib
import io
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import warnings
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ast_grep_download_child as download_child  # noqa: E402
import ast_grep_installer as installer  # noqa: E402


SCRIPT_BINARY = b"#!/bin/sh\nprintf 'ast-grep 0.45.0\\n'\n"


def _zip_bytes(
    entries: list[tuple[str, bytes, int, bytes]],
) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w") as archive:
            for name, content, mode, extra in entries:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                info.extra = extra
                archive.writestr(info, content)
    return output.getvalue()


def fixture_artifact(
    *,
    binary: bytes = SCRIPT_BINARY,
    entries: list[tuple[str, bytes, int, bytes]] | None = None,
) -> tuple[bytes, installer.AstGrepArtifact]:
    rows = entries or [
        ("sg", b"deprecated alias\n", stat.S_IFREG | 0o755, b""),
        ("ast-grep", binary, stat.S_IFREG | 0o755, b""),
    ]
    archive_bytes = _zip_bytes(rows)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        profiles = tuple(
            installer.ArchiveEntryProfile(
                entry.filename,
                entry.file_size,
                entry.compress_size,
                entry.CRC,
                entry.external_attr,
                entry.create_system,
                entry.flag_bits,
                entry.compress_type,
                entry.extra,
                entry.comment,
            )
            for entry in archive.infolist()
        )
    artifact = installer.AstGrepArtifact(
        version="0.45.0",
        asset="fixture.zip",
        url="https://github.com/example/fixture.zip",
        archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
        archive_size=len(archive_bytes),
        binary_sha256=hashlib.sha256(binary).hexdigest(),
        binary_size=len(binary),
        version_output="ast-grep 0.45.0",
        entries=profiles,
    )
    return archive_bytes, artifact


def fixture_downloader(payload: bytes):
    digest = hashlib.sha256(payload).hexdigest()

    def download(fd: int) -> dict[str, object]:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        return {"sha256": digest, "bytes": len(payload)}

    return download


def test_rename_exclusive(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    try:
        os.link(
            source_name,
            target_name,
            src_dir_fd=source_dir_fd,
            dst_dir_fd=target_dir_fd,
            follow_symlinks=False,
        )
    except FileExistsError as error:
        raise installer.AstGrepInstallError(
            "ast_grep_destination_exists",
            "test exclusive destination exists",
            phase="publish",
            cause=error,
        ) from error
    os.unlink(source_name, dir_fd=source_dir_fd)


def tree_snapshot(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        row: dict[str, object] = {
            "path": str(path.relative_to(root)),
            "mode": stat.S_IMODE(metadata.st_mode),
            "uid": metadata.st_uid,
            "dev": metadata.st_dev,
            "ino": metadata.st_ino,
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
            "type": "directory" if stat.S_ISDIR(metadata.st_mode) else "file",
        }
        if stat.S_ISREG(metadata.st_mode):
            row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(row)
    return rows


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        try:
            os.fchmod(temporary_fd, 0o600)
            encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
            view = memoryview(encoded)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("short owner-host report write")
                view = view[written:]
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class _Response:
    def __init__(self, payload: bytes, **headers: str) -> None:
        self.payload = payload
        self.offset = 0
        self.status = 200
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, **_kwargs):
        self.requests.append(request)
        return self.response


class AstGrepDownloadChildTest(unittest.TestCase):
    def test_download_uses_fixed_headers_and_bounded_fd(self) -> None:
        payload = b"fixture archive"
        opener = _Opener(_Response(payload, **{"Content-Length": str(len(payload))}))
        redirects = download_child.AllowlistedRedirectHandler()
        with tempfile.NamedTemporaryFile() as output:
            os.fchmod(output.fileno(), 0o600)
            report = download_child.download_to_fd(
                output.fileno(), opener=opener, redirects=redirects
            )
            os.lseek(output.fileno(), 0, os.SEEK_SET)
            self.assertEqual(payload, os.read(output.fileno(), len(payload)))
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report["sha256"])
        headers = {key.lower(): value for key, value in opener.requests[0].header_items()}
        self.assertEqual("application/octet-stream", headers["accept"])
        self.assertEqual("identity", headers["accept-encoding"])
        self.assertNotIn("authorization", headers)
        self.assertNotIn("cookie", headers)

    def test_redirect_allowlist_and_limit_fail_closed(self) -> None:
        handler = download_child.AllowlistedRedirectHandler()
        request = download_child.fixed_request(download_child.ASSET_URL, redirect=False)
        allowed = (
            "https://release-assets.githubusercontent.com/path?sv=1&sig=opaque"
        )
        redirected = handler.redirect_request(request, None, 302, "", {}, allowed)
        self.assertEqual("release-assets.githubusercontent.com", redirected.host)
        for bad in (
            "http://release-assets.githubusercontent.com/path",
            "https://evil.example/path",
            "https://user@release-assets.githubusercontent.com/path",
            "https://github.com/path?token=bad",
        ):
            with self.subTest(url=bad), self.assertRaises(download_child.DownloadError):
                download_child.validate_url(bad, redirect=True)
        handler.hosts = ["release-assets.githubusercontent.com"] * 3
        with self.assertRaises(download_child.DownloadError):
            handler.redirect_request(request, None, 302, "", {}, allowed)

    def test_declared_or_streamed_oversize_is_rejected(self) -> None:
        with tempfile.NamedTemporaryFile() as output:
            os.fchmod(output.fileno(), 0o600)
            opener = _Opener(
                _Response(
                    b"x",
                    **{"Content-Length": str(download_child.MAX_ARCHIVE_BYTES + 1)},
                )
            )
            with self.assertRaises(download_child.DownloadError):
                download_child.download_to_fd(output.fileno(), opener=opener)

    def test_parent_download_child_is_isolated_and_deadline_bounded(self) -> None:
        with tempfile.NamedTemporaryFile() as output:
            os.fchmod(output.fileno(), 0o600)
            report = {
                "result": "PASS",
                "asset_url": installer.AST_GREP_URL,
                "initial_host": "github.com",
                "redirect_count": 1,
                "redirect_hosts": ["release-assets.githubusercontent.com"],
                "bytes": 1,
                "sha256": "0" * 64,
                "archive_fd": output.fileno(),
                "inherited_fds": sorted({0, 1, 2, output.fileno()}),
                "environment_keys": installer._download_child_observed_environment_keys(),
                "pid": 424_242,
                "process_group_id": 424_242,
            }
            process = mock.Mock()
            process.pid = 424_242
            process.returncode = 0
            process.communicate.return_value = (json.dumps(report), "")
            with mock.patch.object(
                installer.subprocess,
                "Popen",
                return_value=process,
            ) as popen, mock.patch.object(
                installer, "_process_group_exists", return_value=False
            ):
                self.assertEqual(
                    {**report, "surviving_processes": 0},
                    installer._production_download(output.fileno()),
                )
            args, kwargs = popen.call_args
            command = args[0]
            self.assertEqual(["-I", "-B", "-S"], command[1:4])
            self.assertEqual((output.fileno(),), kwargs["pass_fds"])
            self.assertTrue(kwargs["start_new_session"])
            process.communicate.assert_called_once_with(
                timeout=installer.DOWNLOAD_TIMEOUT_SECONDS
            )
            forbidden = {"AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "HTTPS_PROXY"}
            self.assertTrue(forbidden.isdisjoint(kwargs["env"]))

            timed_out = mock.Mock()
            timed_out.pid = 424_243
            timed_out.communicate.side_effect = [
                subprocess.TimeoutExpired(command, 60),
                ("", ""),
            ]
            with mock.patch.object(
                installer.subprocess,
                "Popen",
                return_value=timed_out,
            ), mock.patch.object(installer, "_terminate_process_group") as terminate:
                with self.assertRaises(installer.AstGrepInstallError) as raised:
                    installer._production_download(output.fileno())
            terminate.assert_called_once_with(timed_out)
            self.assertEqual("ast_grep_download_timeout", raised.exception.reason_code)


class AstGrepInstallerTest(unittest.TestCase):
    def roots(self, root: Path) -> tuple[Path, Path]:
        cache = root / "cache"
        bin_root = root / "bin"
        cache.mkdir(mode=0o700)
        bin_root.mkdir(mode=0o700)
        return cache, bin_root

    def install_fixture(
        self,
        cache: Path,
        bin_root: Path,
        archive_bytes: bytes,
        artifact: installer.AstGrepArtifact,
        **kwargs,
    ) -> dict[str, object]:
        return installer.install_ast_grep(
            cache_root=cache,
            bin_root=bin_root,
            _artifact=artifact,
            _system="Darwin",
            _machine="arm64",
            _downloader=fixture_downloader(archive_bytes),
            _exclusive_renamer=test_rename_exclusive,
            **kwargs,
        )

    def test_unsupported_platform_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cache = root / "missing-cache"
            bin_root = root / "missing-bin"
            with self.assertRaises(installer.AstGrepInstallError) as raised:
                installer.install_ast_grep(
                    cache_root=cache,
                    bin_root=bin_root,
                    _system="Linux",
                    _machine="x86_64",
                )
            self.assertEqual(
                "ast_grep_unsupported_platform", raised.exception.reason_code
            )
            self.assertFalse(cache.exists())
            self.assertFalse(bin_root.exists())

    def test_root_authority_rejects_symlink_and_unsafe_mode(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cache, bin_root = self.roots(root)
            unsafe = root / "unsafe"
            unsafe.mkdir(mode=0o755)
            with self.assertRaises(installer.AstGrepInstallError):
                self.install_fixture(unsafe, bin_root, archive_bytes, artifact)
            alias = root / "alias"
            alias.symlink_to(cache, target_is_directory=True)
            with self.assertRaises(installer.AstGrepInstallError):
                self.install_fixture(alias, bin_root, archive_bytes, artifact)

    def test_fresh_install_doctor_and_offline_idempotence(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))
            first = self.install_fixture(cache, bin_root, archive_bytes, artifact)
            self.assertTrue(first["changed"])
            self.assertTrue(first["complete"])
            binary = bin_root / installer.BINARY_NAME
            attestation = cache / installer.ATTESTATION_NAME
            self.assertEqual(0o700, stat.S_IMODE(binary.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(attestation.stat().st_mode))
            self.assertFalse((bin_root / "sg").exists())
            status = installer.ast_grep_status(
                cache_root=cache,
                bin_root=bin_root,
                _artifact=artifact,
                _system="Darwin",
                _machine="arm64",
            )
            self.assertTrue(status["ready"])
            before = (binary.stat().st_ino, binary.read_bytes(), attestation.read_bytes())
            with mock.patch.object(
                installer,
                "_production_download",
                side_effect=AssertionError("offline no-op must not download"),
            ), mock.patch.object(
                installer,
                "_bounded_process",
                side_effect=AssertionError("offline no-op must not execute"),
            ):
                second = installer.install_ast_grep(
                    cache_root=cache,
                    bin_root=bin_root,
                    _artifact=artifact,
                    _system="Darwin",
                    _machine="arm64",
                    _exclusive_renamer=test_rename_exclusive,
                )
            self.assertFalse(second["changed"])
            self.assertEqual(
                before,
                (binary.stat().st_ino, binary.read_bytes(), attestation.read_bytes()),
            )

    def test_archive_hash_and_exact_manifest_fail_closed(self) -> None:
        valid_bytes, valid_artifact = fixture_artifact()
        bad_rows = {
            "duplicate": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("sg", SCRIPT_BINARY, stat.S_IFREG | 0o755, b""),
            ],
            "traversal": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("../ast-grep", SCRIPT_BINARY, stat.S_IFREG | 0o755, b""),
            ],
            "symlink": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("ast-grep", SCRIPT_BINARY, stat.S_IFLNK | 0o777, b""),
            ],
            "unknown_extra": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("ast-grep", SCRIPT_BINARY, stat.S_IFREG | 0o755, b"\x34\x12\x00\x00"),
            ],
            "absolute": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("/ast-grep", SCRIPT_BINARY, stat.S_IFREG | 0o755, b""),
            ],
            "windows_separator": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("dir\\ast-grep", SCRIPT_BINARY, stat.S_IFREG | 0o755, b""),
            ],
            "fifo": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("ast-grep", SCRIPT_BINARY, stat.S_IFIFO | 0o755, b""),
            ],
            "device": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("ast-grep", SCRIPT_BINARY, stat.S_IFCHR | 0o755, b""),
            ],
            "socket": [
                ("sg", b"one", stat.S_IFREG | 0o755, b""),
                ("ast-grep", SCRIPT_BINARY, stat.S_IFSOCK | 0o755, b""),
            ],
        }
        for label, rows in bad_rows.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                payload = _zip_bytes(rows)
                artifact = replace(
                    valid_artifact,
                    archive_sha256=hashlib.sha256(payload).hexdigest(),
                    archive_size=len(payload),
                )
                path = Path(raw) / "archive.zip"
                path.write_bytes(payload)
                path.chmod(0o600)
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    with self.assertRaises(installer.AstGrepInstallError):
                        installer._validate_archive(fd, artifact)
                finally:
                    os.close(fd)

        encrypted = bytearray(valid_bytes)
        for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            start = 0
            while True:
                index = encrypted.find(signature, start)
                if index < 0:
                    break
                flags = int.from_bytes(
                    encrypted[index + flag_offset : index + flag_offset + 2], "little"
                )
                encrypted[index + flag_offset : index + flag_offset + 2] = (
                    flags | 1
                ).to_bytes(2, "little")
                start = index + 4
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "encrypted.zip"
            path.write_bytes(encrypted)
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                with self.assertRaises(installer.AstGrepInstallError):
                    installer._validate_archive(
                        fd,
                        replace(
                            valid_artifact,
                            archive_sha256=hashlib.sha256(encrypted).hexdigest(),
                            archive_size=len(encrypted),
                        ),
                    )
            finally:
                os.close(fd)

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "archive.zip"
            path.write_bytes(valid_bytes)
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                with self.assertRaises(installer.AstGrepInstallError) as raised:
                    installer._validate_archive(
                        fd,
                        replace(valid_artifact, archive_sha256="0" * 64),
                    )
                self.assertEqual(
                    "ast_grep_archive_hash_mismatch", raised.exception.reason_code
                )
            finally:
                os.close(fd)

    def test_member_bounds_are_enforced_with_integer_ratio(self) -> None:
        archive_bytes, artifact = fixture_artifact(binary=b"x" * 1024)
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            installer, "MAX_MEMBER_BYTES", 512
        ):
            path = Path(raw) / "archive.zip"
            path.write_bytes(archive_bytes)
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                with self.assertRaises(installer.AstGrepInstallError):
                    installer._validate_archive(fd, artifact)
            finally:
                os.close(fd)

    def test_extracted_stage_retains_only_a_read_descriptor(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _cache, bin_root = self.roots(root)
            archive_path = root / "archive.zip"
            archive_path.write_bytes(archive_bytes)
            archive_path.chmod(0o600)
            archive_fd = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW)
            authority = installer._open_root(bin_root)
            binary_fd = -1
            archive = source = None
            try:
                archive, entry, source, _profile = installer._validate_archive(
                    archive_fd,
                    artifact,
                )
                binary_fd, identity = installer._extract_binary_stage(
                    archive,
                    entry,
                    authority,
                    artifact,
                )
                self.assertEqual(
                    os.O_RDONLY,
                    fcntl.fcntl(binary_fd, fcntl.F_GETFL) & os.O_ACCMODE,
                )
                metadata = os.fstat(binary_fd)
                self.assertEqual(identity, (metadata.st_dev, metadata.st_ino))
            finally:
                if binary_fd >= 0:
                    os.close(binary_fd)
                if archive is not None:
                    archive.close()
                if source is not None:
                    source.close()
                os.close(archive_fd)
                os.close(authority.fd)

    def test_version_hang_and_output_flood_fail_closed(self) -> None:
        cases = {
            "hang": b"#!/bin/sh\nsleep 5\n",
            "flood": b"#!/bin/sh\nwhile :; do printf 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\\n'; done\n",
        }
        for label, binary in cases.items():
            archive_bytes, artifact = fixture_artifact(binary=binary)
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                cache, bin_root = self.roots(Path(raw))
                with mock.patch.object(installer, "VERSION_TIMEOUT_SECONDS", 0.2):
                    with self.assertRaises(installer.AstGrepInstallError) as raised:
                        self.install_fixture(cache, bin_root, archive_bytes, artifact)
                self.assertEqual(
                    "ast_grep_version_failed", raised.exception.reason_code
                )
                self.assertFalse((bin_root / installer.BINARY_NAME).exists())

    def test_bounded_process_kills_descendants_after_leader_exit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            heartbeat_path = root / "heartbeat"
            child_program = "\n".join(
                (
                    "import pathlib,signal,time",
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                    f"path=pathlib.Path({str(heartbeat_path)!r})",
                    "path.write_text('ready')",
                    "for _ in range(1500):",
                    "    with path.open('a') as stream:",
                    "        stream.write('.')",
                    "    time.sleep(0.02)",
                )
            )
            program = "\n".join(
                (
                    "import pathlib, subprocess, sys, time",
                    f"child = subprocess.Popen([sys.executable, '-c', {child_program!r}])",
                    f"heartbeat = pathlib.Path({str(heartbeat_path)!r})",
                    "deadline = time.monotonic() + 2",
                    "while not heartbeat.exists() and time.monotonic() < deadline: time.sleep(0.005)",
                    "print('leader exited')",
                )
            )
            with mock.patch.object(installer, "VERSION_TIMEOUT_SECONDS", 0.2):
                report = installer._bounded_process(
                    [sys.executable, "-c", program],
                    cwd=root,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                )
            self.assertTrue(report["timed_out"])
            self.assertTrue(report["survivor"])
            self.assertEqual(0, report["surviving_processes"])
            heartbeat = heartbeat_path.read_bytes()
            time.sleep(0.15)
            self.assertEqual(heartbeat, heartbeat_path.read_bytes())

    def test_zombie_only_group_does_not_override_reaped_leader(self) -> None:
        class ReapedLeader:
            pid = 424_242

            def __init__(self) -> None:
                self.reaped = False

            def poll(self):
                return 0 if self.reaped else None

            def wait(self, timeout):
                self.reaped = True
                return 0

        process = ReapedLeader()
        with mock.patch.object(
            installer,
            "_process_group_exists",
            return_value=True,
        ), mock.patch.object(installer, "_signal_process_group") as signal_group, mock.patch.object(
            installer,
            "_wait_process_group_gone",
            return_value=False,
        ) as settle:
            self.assertTrue(installer._terminate_process_group(process))
        self.assertTrue(process.reaped)
        self.assertEqual(
            [signal.SIGTERM, signal.SIGKILL],
            [call.args[1] for call in signal_group.call_args_list],
        )
        settle.assert_called_once_with(process.pid, 1.0)

    def test_binary_only_journal_recovers_without_download(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))

            def fail_after_sync(phase: str) -> None:
                if phase == "after_binary_sync":
                    raise RuntimeError("injected post-publication failure")

            with self.assertRaises(installer.AstGrepInstallError) as raised:
                self.install_fixture(
                    cache,
                    bin_root,
                    archive_bytes,
                    artifact,
                    _failure_injector=fail_after_sync,
                )
            self.assertTrue(raised.exception.committed)
            self.assertTrue(raised.exception.recovery_required)
            self.assertTrue((cache / installer.JOURNAL_NAME).exists())
            self.assertTrue((bin_root / installer.BINARY_NAME).exists())

            result = installer.install_ast_grep(
                cache_root=cache,
                bin_root=bin_root,
                _artifact=artifact,
                _system="Darwin",
                _machine="arm64",
                _downloader=lambda _fd: (_ for _ in ()).throw(
                    AssertionError("recovery must not download")
                ),
                _exclusive_renamer=test_rename_exclusive,
            )
            self.assertTrue(result["complete"])
            self.assertFalse((cache / installer.JOURNAL_NAME).exists())

    def test_every_transaction_boundary_recovers_to_exact_state(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        phases = (
            "after_journal_sync",
            "after_download_sync",
            "after_extract_sync",
            "after_version_verify",
            "after_attestation_stage_sync",
            "before_binary_publish",
            "after_binary_publish",
            "after_binary_sync",
            "before_attestation_publish",
            "after_attestation_publish",
            "after_attestation_sync",
            "before_journal_remove",
        )
        committed_phases = {
            "after_binary_publish",
            "after_binary_sync",
            "before_attestation_publish",
            "after_attestation_publish",
            "after_attestation_sync",
            "before_journal_remove",
        }
        for target_phase in phases:
            with self.subTest(phase=target_phase), tempfile.TemporaryDirectory() as raw:
                cache, bin_root = self.roots(Path(raw))

                def fail_at_boundary(phase: str) -> None:
                    if phase == target_phase:
                        raise RuntimeError(f"injected boundary failure: {phase}")

                with self.assertRaises(installer.AstGrepInstallError) as raised:
                    self.install_fixture(
                        cache,
                        bin_root,
                        archive_bytes,
                        artifact,
                        _failure_injector=fail_at_boundary,
                    )
                self.assertTrue(raised.exception.recovery_required)
                self.assertEqual(
                    target_phase in committed_phases,
                    raised.exception.committed,
                )
                recovered = self.install_fixture(
                    cache,
                    bin_root,
                    archive_bytes,
                    artifact,
                )
                self.assertTrue(recovered["complete"])
                self.assertFalse((cache / installer.JOURNAL_NAME).exists())
                self.assertFalse((cache / installer.ARCHIVE_STAGE_NAME).exists())
                self.assertFalse((cache / installer.ATTESTATION_STAGE_NAME).exists())
                self.assertFalse((bin_root / installer.BINARY_STAGE_NAME).exists())
                self.assertTrue(
                    installer.ast_grep_status(
                        cache_root=cache,
                        bin_root=bin_root,
                        _artifact=artifact,
                        _system="Darwin",
                        _machine="arm64",
                    )["ready"]
                )

    def test_sync_failures_recover_at_binary_attestation_and_journal_boundaries(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        boundaries = (
            "attestation_stage_directory",
            "binary_directory",
            "attestation_directory",
            "journal_remove",
        )
        for boundary in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as raw:
                cache, bin_root = self.roots(Path(raw))
                original_fsync = installer.os.fsync
                failed = False

                def fail_sync(fd: int) -> None:
                    nonlocal failed
                    if not failed:
                        identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
                        is_bin_root = identity == (
                            bin_root.stat().st_dev,
                            bin_root.stat().st_ino,
                        )
                        is_cache_root = identity == (
                            cache.stat().st_dev,
                            cache.stat().st_ino,
                        )
                        binary_exists = (bin_root / installer.BINARY_NAME).exists()
                        attestation_exists = (cache / installer.ATTESTATION_NAME).exists()
                        journal_exists = (cache / installer.JOURNAL_NAME).exists()
                        should_fail = (
                            boundary == "attestation_stage_directory"
                            and is_cache_root
                            and (cache / installer.ATTESTATION_STAGE_NAME).exists()
                            and not binary_exists
                            and not attestation_exists
                        ) or (
                            boundary == "binary_directory"
                            and is_bin_root
                            and binary_exists
                            and not attestation_exists
                        ) or (
                            boundary == "attestation_directory"
                            and is_cache_root
                            and attestation_exists
                            and journal_exists
                        ) or (
                            boundary == "journal_remove"
                            and is_cache_root
                            and attestation_exists
                            and not journal_exists
                        )
                        if should_fail:
                            failed = True
                            raise OSError(errno.EIO, f"injected {boundary} sync failure")
                    original_fsync(fd)

                with mock.patch.object(installer.os, "fsync", side_effect=fail_sync):
                    with self.assertRaises(installer.AstGrepInstallError) as raised:
                        self.install_fixture(cache, bin_root, archive_bytes, artifact)
                self.assertTrue(failed)
                self.assertEqual(
                    boundary != "attestation_stage_directory",
                    raised.exception.committed,
                )
                recovered = self.install_fixture(
                    cache,
                    bin_root,
                    archive_bytes,
                    artifact,
                )
                self.assertTrue(recovered["complete"])

    def test_recovery_open_failure_closes_binary_and_reports_committed(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))

            def fail_after_binary_sync(phase: str) -> None:
                if phase == "after_binary_sync":
                    raise RuntimeError("leave attributable binary recovery state")

            with self.assertRaises(installer.AstGrepInstallError):
                self.install_fixture(
                    cache,
                    bin_root,
                    archive_bytes,
                    artifact,
                    _failure_injector=fail_after_binary_sync,
                )
            binary_metadata = (bin_root / installer.BINARY_NAME).stat()
            original_open = installer._open_regular_at
            opened_binary_fd: int | None = None

            def fail_second_open(root, name, **kwargs):
                nonlocal opened_binary_fd
                if name == installer.BINARY_NAME:
                    result = original_open(root, name, **kwargs)
                    opened_binary_fd = result[0]
                    return result
                raise installer.AstGrepInstallError(
                    "ast_grep_state_unsafe",
                    "injected attestation-stage open failure",
                    phase="recovery",
                )

            with mock.patch.object(
                installer,
                "_installed_state",
                return_value=("resume_attestation", binary_metadata),
            ), mock.patch.object(
                installer,
                "_open_regular_at",
                side_effect=fail_second_open,
            ):
                with self.assertRaises(installer.AstGrepInstallError) as raised:
                    self.install_fixture(cache, bin_root, archive_bytes, artifact)
            self.assertTrue(raised.exception.committed)
            self.assertEqual("uncertain", raised.exception.durability)
            assert opened_binary_fd is not None
            with self.assertRaises(OSError):
                os.fstat(opened_binary_fd)

    def test_resume_cleanup_sync_failure_reports_existing_commit(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))

            def fail_after_attestation_sync(phase: str) -> None:
                if phase == "after_attestation_sync":
                    raise RuntimeError("leave completed publication journal")

            with self.assertRaises(installer.AstGrepInstallError):
                self.install_fixture(
                    cache,
                    bin_root,
                    archive_bytes,
                    artifact,
                    _failure_injector=fail_after_attestation_sync,
                )
            original_fsync = installer.os.fsync
            bin_identity = (bin_root.stat().st_dev, bin_root.stat().st_ino)
            failed = False

            def fail_bin_sync(fd: int) -> None:
                nonlocal failed
                metadata = os.fstat(fd)
                if not failed and (metadata.st_dev, metadata.st_ino) == bin_identity:
                    failed = True
                    raise OSError(errno.EIO, "injected recovery bin sync failure")
                original_fsync(fd)

            with mock.patch.object(installer.os, "fsync", side_effect=fail_bin_sync):
                with self.assertRaises(installer.AstGrepInstallError) as raised:
                    self.install_fixture(cache, bin_root, archive_bytes, artifact)
            self.assertTrue(failed)
            self.assertTrue(raised.exception.committed)
            self.assertEqual("uncertain", raised.exception.durability)
            self.assertTrue(
                self.install_fixture(cache, bin_root, archive_bytes, artifact)["complete"]
            )

    def test_destination_race_and_root_swap_preserve_victim(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cache, bin_root = self.roots(root)

            def racing_rename(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
                if dst == installer.BINARY_NAME:
                    victim_fd = os.open(
                        dst,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o700,
                        dir_fd=dst_fd,
                    )
                    os.write(victim_fd, b"victim")
                    os.close(victim_fd)
                    raise installer.AstGrepInstallError(
                        "ast_grep_destination_exists",
                        "injected destination race",
                        phase="publish",
                    )
                test_rename_exclusive(src_fd, src, dst_fd, dst)

            with self.assertRaises(installer.AstGrepInstallError):
                installer.install_ast_grep(
                    cache_root=cache,
                    bin_root=bin_root,
                    _artifact=artifact,
                    _system="Darwin",
                    _machine="arm64",
                    _downloader=fixture_downloader(archive_bytes),
                    _exclusive_renamer=racing_rename,
                )
            self.assertEqual(b"victim", (bin_root / installer.BINARY_NAME).read_bytes())

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cache, bin_root = self.roots(root)
            displaced = root / "bin-displaced"

            def swap_root(phase: str) -> None:
                if phase == "before_binary_publish":
                    bin_root.rename(displaced)
                    bin_root.mkdir(mode=0o700)
                    (bin_root / "victim").write_text("safe", encoding="utf-8")

            with self.assertRaises(installer.AstGrepInstallError) as raised:
                self.install_fixture(
                    cache,
                    bin_root,
                    archive_bytes,
                    artifact,
                    _failure_injector=swap_root,
                )
            self.assertEqual("ast_grep_root_changed", raised.exception.reason_code)
            self.assertEqual("safe", (bin_root / "victim").read_text())

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cache, bin_root = self.roots(root)

            def chmod_root(phase: str) -> None:
                if phase == "before_binary_publish":
                    bin_root.chmod(0o755)

            with self.assertRaises(installer.AstGrepInstallError) as raised:
                self.install_fixture(
                    cache,
                    bin_root,
                    archive_bytes,
                    artifact,
                    _failure_injector=chmod_root,
                )
            self.assertEqual("ast_grep_root_changed", raised.exception.reason_code)

    def test_exact_byte_destination_collision_is_never_adopted(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))

            def collide_with_exact_bytes(
                src_fd: int, src: str, dst_fd: int, dst: str
            ) -> None:
                if dst == installer.BINARY_NAME:
                    victim_fd = os.open(
                        dst,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o700,
                        dir_fd=dst_fd,
                    )
                    os.write(victim_fd, SCRIPT_BINARY)
                    os.close(victim_fd)
                    raise installer.AstGrepInstallError(
                        "ast_grep_destination_exists",
                        "injected exact-byte collision",
                        phase="publish",
                    )
                test_rename_exclusive(src_fd, src, dst_fd, dst)

            with self.assertRaises(installer.AstGrepInstallError):
                installer.install_ast_grep(
                    cache_root=cache,
                    bin_root=bin_root,
                    _artifact=artifact,
                    _system="Darwin",
                    _machine="arm64",
                    _downloader=fixture_downloader(archive_bytes),
                    _exclusive_renamer=collide_with_exact_bytes,
                )
            victim = bin_root / installer.BINARY_NAME
            victim_identity = (victim.stat().st_ino, victim.read_bytes())
            with self.assertRaises(installer.AstGrepInstallError) as retry:
                self.install_fixture(cache, bin_root, archive_bytes, artifact)
            self.assertEqual(
                "ast_grep_recovery_inconsistent", retry.exception.reason_code
            )
            self.assertEqual(victim_identity, (victim.stat().st_ino, victim.read_bytes()))
            self.assertFalse((cache / installer.ATTESTATION_NAME).exists())

    def test_attestation_race_is_no_clobber_and_reports_committed(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))

            def racing_attestation(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
                if dst == installer.ATTESTATION_NAME:
                    victim_fd = os.open(
                        dst,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=dst_fd,
                    )
                    os.write(victim_fd, b"victim-attestation")
                    os.close(victim_fd)
                    raise installer.AstGrepInstallError(
                        "ast_grep_attestation_exists",
                        "injected attestation race",
                        phase="attestation",
                    )
                test_rename_exclusive(src_fd, src, dst_fd, dst)

            with self.assertRaises(installer.AstGrepInstallError) as raised:
                installer.install_ast_grep(
                    cache_root=cache,
                    bin_root=bin_root,
                    _artifact=artifact,
                    _system="Darwin",
                    _machine="arm64",
                    _downloader=fixture_downloader(archive_bytes),
                    _exclusive_renamer=racing_attestation,
                )
            self.assertTrue(raised.exception.committed)
            self.assertTrue(raised.exception.recovery_required)
            self.assertEqual(
                b"victim-attestation",
                (cache / installer.ATTESTATION_NAME).read_bytes(),
            )

    def test_doctor_detects_path_swap_during_hash(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cache, bin_root = self.roots(root)
            self.install_fixture(cache, bin_root, archive_bytes, artifact)
            binary = bin_root / installer.BINARY_NAME
            replacement = root / "replacement"
            replacement.write_bytes(b"victim")
            replacement.chmod(0o700)
            original_hash = installer._hash_fd
            swapped = False

            def swap_after_hash(fd: int, limit: int):
                nonlocal swapped
                result = original_hash(fd, limit)
                if not swapped:
                    os.replace(replacement, binary)
                    swapped = True
                return result

            with mock.patch.object(installer, "_hash_fd", side_effect=swap_after_hash):
                status = installer.ast_grep_status(
                    cache_root=cache,
                    bin_root=bin_root,
                    _artifact=artifact,
                    _system="Darwin",
                    _machine="arm64",
                )
            self.assertFalse(status["ready"])
            self.assertEqual("drift", status["state"])
            self.assertEqual(b"victim", binary.read_bytes())

    def test_native_rename_unavailable_fails_without_fallback(self) -> None:
        class MissingLibc:
            pass

        with mock.patch.object(installer.ctypes, "CDLL", return_value=MissingLibc()):
            with self.assertRaises(installer.AstGrepInstallError) as raised:
                installer.rename_exclusive(1, "source", 1, "target")
        self.assertEqual("ast_grep_publish_unsupported", raised.exception.reason_code)

    def test_unmanaged_existing_and_doctor_tamper_are_rejected(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))
            unmanaged = bin_root / installer.BINARY_NAME
            unmanaged.write_bytes(SCRIPT_BINARY)
            unmanaged.chmod(0o700)
            with self.assertRaises(installer.AstGrepInstallError) as raised:
                self.install_fixture(cache, bin_root, archive_bytes, artifact)
            self.assertEqual("ast_grep_unmanaged_existing", raised.exception.reason_code)

        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))
            self.install_fixture(cache, bin_root, archive_bytes, artifact)
            binary = bin_root / installer.BINARY_NAME
            binary.write_bytes(binary.read_bytes() + b"tamper")
            binary.chmod(0o700)
            status = installer.ast_grep_status(
                cache_root=cache,
                bin_root=bin_root,
                _artifact=artifact,
                _system="Darwin",
                _machine="arm64",
            )
            self.assertFalse(status["ready"])
            self.assertEqual("drift", status["state"])

    def test_absent_lock_doctor_is_read_only_and_busy_is_reported(self) -> None:
        _archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))
            status = installer.ast_grep_status(
                cache_root=cache,
                bin_root=bin_root,
                _artifact=artifact,
                _system="Darwin",
                _machine="arm64",
            )
            self.assertEqual("missing", status["state"])
            self.assertEqual([], list(cache.iterdir()))

            authority = installer._open_root(cache)
            lock_fd = installer._acquire_lock(
                authority,
                exclusive=True,
                create=True,
                timeout_seconds=0,
            )
            try:
                status = installer.ast_grep_status(
                    cache_root=cache,
                    bin_root=bin_root,
                    _artifact=artifact,
                    _system="Darwin",
                    _machine="arm64",
                )
                self.assertEqual("busy", status["state"])
            finally:
                installer._release_lock(lock_fd)
                os.close(authority.fd)

    def test_malformed_journal_and_orphan_stage_refuse_recovery(self) -> None:
        archive_bytes, artifact = fixture_artifact()
        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))
            (cache / installer.JOURNAL_NAME).write_text("{}\n", encoding="utf-8")
            (cache / installer.JOURNAL_NAME).chmod(0o600)
            with self.assertRaises(installer.AstGrepInstallError) as raised:
                self.install_fixture(cache, bin_root, archive_bytes, artifact)
            self.assertEqual("ast_grep_journal_invalid", raised.exception.reason_code)

        with tempfile.TemporaryDirectory() as raw:
            cache, bin_root = self.roots(Path(raw))
            (cache / installer.ARCHIVE_STAGE_NAME).write_bytes(b"orphan")
            (cache / installer.ARCHIVE_STAGE_NAME).chmod(0o600)
            with self.assertRaises(installer.AstGrepInstallError) as raised:
                self.install_fixture(cache, bin_root, archive_bytes, artifact)
            self.assertEqual(
                "ast_grep_unmanaged_temporary", raised.exception.reason_code
            )


@unittest.skipUnless(
    os.environ.get("MY_OPENCODE_RUN_AST_GREP_LIVE") == "1",
    "set MY_OPENCODE_RUN_AST_GREP_LIVE=1 on Darwin arm64",
)
class AstGrepOwnerHostGate(unittest.TestCase):
    def test_live_download_install_doctor_idempotence_and_value(self) -> None:
        self.assertEqual(
            ("Darwin", "arm64"),
            (installer.platform.system(), installer.platform.machine()),
        )
        phase = os.environ.get("MY_OPENCODE_AST_GREP_WORKER_PHASE")
        if phase == "fresh":
            self._run_fresh_worker()
            return
        if phase == "offline":
            self._run_offline_worker()
            return
        self._run_sandboxed_gate()

    def _sandbox_root(self) -> Path:
        root = Path(os.environ["MY_OPENCODE_AST_GREP_SANDBOX_ROOT"]).resolve()
        self.assertTrue(root.is_absolute())
        self.assertEqual(0o700, stat.S_IMODE(root.stat().st_mode))
        return root

    def _install_roots(self) -> tuple[Path, Path, Path]:
        root = self._sandbox_root()
        return root / "install" / "cache", root / "install" / "bin", root / "work"

    def _run_fresh_worker(self) -> None:
        root = self._sandbox_root()
        cache, bin_root, work = self._install_roots()
        for path in (cache, bin_root, work):
            path.mkdir(parents=True, mode=0o700, exist_ok=False)
        synthetic = {
            "AWS_SECRET_ACCESS_KEY": "TASK46_SYNTHETIC_SECRET",
            "GITHUB_TOKEN": "TASK46_SYNTHETIC_TOKEN",
            "HTTPS_PROXY": "http://127.0.0.1:9",
        }
        with mock.patch.dict(os.environ, synthetic, clear=False):
            first = installer.install_ast_grep(cache_root=cache, bin_root=bin_root)
        self.assertTrue(first["complete"])
        self.assertEqual(0, first["downloader_survivors"])
        download = first["download"]
        self.assertEqual(installer.AST_GREP_URL, download["asset_url"])
        self.assertEqual(installer.AST_GREP_ARCHIVE_SHA256, download["sha256"])
        self.assertEqual(8_111_714, download["bytes"])
        self.assertEqual(
            sorted({0, 1, 2, download["archive_fd"]}),
            download["inherited_fds"],
        )
        self.assertEqual(
            installer._download_child_observed_environment_keys(),
            download["environment_keys"],
        )
        self.assertTrue(set(download["environment_keys"]).isdisjoint(synthetic))
        self.assertFalse(installer._process_group_exists(download["process_group_id"]))
        status = installer.ast_grep_status(cache_root=cache, bin_root=bin_root)
        self.assertTrue(status["ready"])
        self.assertEqual(installer.AST_GREP_VERSION_OUTPUT, first["version_observed"])

        native = work / "native-rename"
        native.mkdir(mode=0o700)
        native_fd = os.open(native, os.O_RDONLY | os.O_DIRECTORY)
        try:
            source_fd = os.open(
                "source",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=native_fd,
            )
            os.write(source_fd, b"source")
            os.close(source_fd)
            installer.rename_exclusive(native_fd, "source", native_fd, "published")
            published = (native / "published").read_bytes()

            collision_source_fd = os.open(
                "collision-source",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=native_fd,
            )
            os.write(collision_source_fd, b"replacement")
            os.close(collision_source_fd)
            collision_target_fd = os.open(
                "collision-target",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=native_fd,
            )
            os.write(collision_target_fd, b"victim")
            os.close(collision_target_fd)
            with self.assertRaises(installer.AstGrepInstallError) as collision:
                installer.rename_exclusive(
                    native_fd,
                    "collision-source",
                    native_fd,
                    "collision-target",
                )
        finally:
            os.close(native_fd)
        self.assertEqual("ast_grep_destination_exists", collision.exception.reason_code)
        self.assertEqual(b"victim", (native / "collision-target").read_bytes())

        observed_profile = first["archive_profile"]
        self.assertEqual(["sg", "ast-grep"], [item["name"] for item in observed_profile])
        self.assertEqual(52_487_984, sum(item["file_size"] for item in observed_profile))
        self.assertEqual(
            8_111_416,
            sum(item["compress_size"] for item in observed_profile),
        )
        report = {
            "result": "PASS",
            "phase": "fresh",
            "asset_url_observed": download["asset_url"],
            "redirect_count_observed": download["redirect_count"],
            "redirect_hosts_observed": download["redirect_hosts"],
            "archive_bytes_observed": download["bytes"],
            "archive_sha256_observed": download["sha256"],
            "archive_profile_observed": observed_profile,
            "binary_sha256_observed": status["observed_binary_sha256"],
            "version_output_observed": first["version_observed"],
            "child_pid_observed": download["pid"],
            "child_process_group_observed": download["process_group_id"],
            "child_inherited_fds_observed": download["inherited_fds"],
            "child_archive_fd_observed": download["archive_fd"],
            "child_environment_keys_observed": download["environment_keys"],
            "synthetic_secret_names_forwarded": sorted(
                set(download["environment_keys"]) & set(synthetic)
            ),
            "surviving_processes_observed": first["downloader_survivors"],
            "doctor_state_observed": status["state"],
            "managed_sg_exists_observed": (bin_root / "sg").exists(),
            "native_rename_exclusive_success": published == b"source",
            "native_rename_exclusive_eexist_preserved": (
                collision.exception.reason_code == "ast_grep_destination_exists"
                and (native / "collision-target").read_bytes() == b"victim"
            ),
        }
        serialized = json.dumps(report, sort_keys=True)
        self.assertTrue(all(value not in serialized for value in synthetic.values()))
        write_json_atomic(Path(os.environ["MY_OPENCODE_AST_GREP_WORKER_REPORT"]), report)
        self.assertTrue(str(root) in str(Path(os.environ["MY_OPENCODE_AST_GREP_WORKER_REPORT"])))

    def _run_offline_worker(self) -> None:
        self.assertEqual("1", os.environ.get("MY_OPENCODE_AST_GREP_NETWORK_DENIED"))
        cache, bin_root, work = self._install_roots()
        fixture_root = Path(__file__).parent / "fixtures" / "ast_grep"
        binary = bin_root / installer.BINARY_NAME
        attestation = cache / installer.ATTESTATION_NAME
        before_doctor = tree_snapshot(cache.parent)
        status = installer.ast_grep_status(cache_root=cache, bin_root=bin_root)
        after_doctor = tree_snapshot(cache.parent)
        self.assertTrue(status["ready"])
        self.assertEqual(before_doctor, after_doctor)

        before_second = tree_snapshot(cache.parent)
        binary_identity = (binary.stat().st_ino, binary.read_bytes())
        attestation_identity = (attestation.stat().st_ino, attestation.read_bytes())
        with mock.patch.object(
            installer,
            "_production_download",
            side_effect=AssertionError("second install must not invoke a downloader"),
        ), mock.patch.object(
            installer,
            "_bounded_process",
            side_effect=AssertionError("second install must not execute the binary"),
        ):
            second = installer.install_ast_grep(cache_root=cache, bin_root=bin_root)
        after_second = tree_snapshot(cache.parent)
        self.assertFalse(second["changed"])
        self.assertEqual(before_second, after_second)
        self.assertEqual(binary_identity, (binary.stat().st_ino, binary.read_bytes()))
        self.assertEqual(
            attestation_identity,
            (attestation.stat().st_ino, attestation.read_bytes()),
        )

        python_file = work / "sample.py"
        js_file = work / "sample.js"
        shutil.copy2(fixture_root / "sample.py", python_file)
        shutil.copy2(fixture_root / "sample.js", js_file)
        clean_env = {
            "HOME": str(work),
            "TMPDIR": str(work),
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
        }
        query = subprocess.run(
            [
                str(binary),
                "run",
                "--pattern",
                "subprocess.run($$$ARGS)",
                "--lang",
                "python",
                "--json=stream",
                str(python_file),
            ],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, query.returncode, query.stderr)
        rows = [json.loads(line) for line in query.stdout.splitlines() if line]
        text_count = python_file.read_text().count("subprocess.run(")
        rewrite = subprocess.run(
            [
                str(binary),
                "run",
                "--pattern",
                "legacy($A)",
                "--rewrite",
                "modern($A)",
                "--lang",
                "javascript",
                "--update-all",
                str(js_file),
            ],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        warm: list[float] = []
        for _ in range(20):
            started = time.monotonic()
            run = subprocess.run(
                [
                    str(binary),
                    "run",
                    "--pattern",
                    "subprocess.run($$$ARGS)",
                    "--lang",
                    "python",
                    str(python_file),
                ],
                env=clean_env,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertIn(run.returncode, {0, 1})
            warm.append(time.monotonic() - started)
        ordered = sorted(warm)
        p95 = ordered[int((len(ordered) - 1) * 0.95)]
        js_text = js_file.read_text()
        self.assertEqual(2, len(rows))
        self.assertEqual(4, text_count)
        self.assertEqual(0, rewrite.returncode, rewrite.stderr)
        self.assertIn("return modern(value)", js_text)
        self.assertIn('"legacy(value)"', js_text)
        self.assertIn("// legacy(value)", js_text)
        report = {
            "result": "PASS",
            "phase": "offline",
            "network_denied_by_sandbox": True,
            "doctor_state_observed": status["state"],
            "doctor_write_free_observed": before_doctor == after_doctor,
            "second_install_changed_observed": second["changed"],
            "second_install_write_free_observed": before_second == after_second,
            "binary_inode_and_bytes_preserved": binary_identity
            == (binary.stat().st_ino, binary.read_bytes()),
            "attestation_inode_and_bytes_preserved": attestation_identity
            == (attestation.stat().st_ino, attestation.read_bytes()),
            "downloader_invocations_observed": 0,
            "version_execution_invocations_observed": 0,
            "fixture_ast_matches_observed": len(rows),
            "fixture_text_matches_observed": text_count,
            "rewrite_expected_only_observed": True,
            "warm_p95_seconds_observed": round(p95, 6),
            "performance_informational": True,
        }
        write_json_atomic(Path(os.environ["MY_OPENCODE_AST_GREP_WORKER_REPORT"]), report)

    def _run_sandboxed_phase(
        self,
        *,
        root: Path,
        phase: str,
        report_path: Path,
        deny_network: bool,
    ) -> dict[str, object]:
        quoted_root = json.dumps(str(root.resolve()))
        profile = "\n".join(
            (
                "(version 1)",
                "(allow default)",
                "(deny file-write*",
                "  (require-all",
                f"    (require-not (subpath {quoted_root}))",
                '    (require-not (literal "/dev/null"))))',
                "(deny network*)" if deny_network else "",
            )
        )
        environment = dict(os.environ)
        environment.update(
            {
                "MY_OPENCODE_RUN_AST_GREP_LIVE": "1",
                "MY_OPENCODE_AST_GREP_WORKER_PHASE": phase,
                "MY_OPENCODE_AST_GREP_SANDBOX_ROOT": str(root),
                "MY_OPENCODE_AST_GREP_WORKER_REPORT": str(report_path),
                "MY_OPENCODE_AST_GREP_NETWORK_DENIED": "1" if deny_network else "0",
                "HOME": str(root / "home"),
                "TMPDIR": str(root / "tmp"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        test_name = (
            "tests.test_ast_grep_installer.AstGrepOwnerHostGate."
            "test_live_download_install_doctor_idempotence_and_value"
        )
        command = [
            "/usr/bin/sandbox-exec",
            "-p",
            profile,
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "-v",
            test_name,
        ]
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(
            0,
            result.returncode,
            f"sandboxed {phase} phase failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertTrue(report_path.is_file())
        payload = json.loads(report_path.read_text())
        self.assertEqual("PASS", payload.get("result"))
        return payload

    def _run_sandboxed_gate(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        final_report = Path(
            os.environ.get(
                "MY_OPENCODE_AST_GREP_REPORT",
                repo_root
                / "runtime"
                / "harness-wave-8"
                / "task46"
                / "owner-host-report.json",
            )
        ).resolve()
        final_report.unlink(missing_ok=True)
        sandbox_root_path: Path | None = None
        with tempfile.TemporaryDirectory(prefix="ast-grep-owner-host-") as raw:
            sandbox_root = Path(raw).resolve()
            sandbox_root_path = sandbox_root
            sandbox_root.chmod(0o700)
            for name in ("home", "tmp"):
                (sandbox_root / name).mkdir(mode=0o700)
            fresh_report_path = sandbox_root / "fresh-report.json"
            offline_report_path = sandbox_root / "offline-report.json"
            fresh = self._run_sandboxed_phase(
                root=sandbox_root,
                phase="fresh",
                report_path=fresh_report_path,
                deny_network=False,
            )
            offline = self._run_sandboxed_phase(
                root=sandbox_root,
                phase="offline",
                report_path=offline_report_path,
                deny_network=True,
            )
            self.assertEqual(
                {"fresh-report.json", "home", "install", "offline-report.json", "tmp", "work"},
                {path.name for path in sandbox_root.iterdir()},
            )
        assert sandbox_root_path is not None
        self.assertFalse(sandbox_root_path.exists())

        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        implementation_hashes = {
            name: hashlib.sha256((repo_root / name).read_bytes()).hexdigest()
            for name in (
                "scripts/ast_grep_download_child.py",
                "scripts/ast_grep_installer.py",
                "tests/test_ast_grep_installer.py",
            )
        }
        report: dict[str, object] = {
            "result": "PASS",
            "gate": "task_46_owner_host",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "host": {
                "system": platform.system(),
                "machine": platform.machine(),
                "release": platform.release(),
                "uid": os.geteuid(),
            },
            "git_revision": revision,
            "implementation_sha256": implementation_hashes,
            "sandbox_enforced_write_scope": True,
            "sandbox_allowed_write_root": "temporary injected root only",
            "network_denied_for_offline_replay": True,
            "cleanup_confirmed": True,
            "fresh": fresh,
            "offline": offline,
        }
        serialized = json.dumps(report, sort_keys=True)
        for secret in ("TASK46_SYNTHETIC_SECRET", "TASK46_SYNTHETIC_TOKEN"):
            self.assertNotIn(secret, serialized)
        write_json_atomic(final_report, report)
        self.assertEqual(0o600, stat.S_IMODE(final_report.stat().st_mode))


if __name__ == "__main__":
    unittest.main()
