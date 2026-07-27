#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ASSET_URL = "https://github.com/ast-grep/ast-grep/releases/download/0.45.0/app-aarch64-apple-darwin.zip"
ALLOWED_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com"})
ASSET_HOST = "release-assets.githubusercontent.com"
MAX_REDIRECTS = 3
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
SOCKET_TIMEOUT_SECONDS = 10
CHILD_DEADLINE_SECONDS = 55
READ_BYTES = 64 * 1024
FIXED_HEADERS = {
    "Accept": "application/octet-stream",
    "Accept-Encoding": "identity",
    "User-Agent": "my-opencode-ast-grep-installer/1",
}
EXPECTED_ENVIRONMENT_KEYS = frozenset(
    {"HOME", "PATH", "LANG", "LC_ALL", "NO_COLOR", "__CF_USER_TEXT_ENCODING"}
)


class DownloadError(RuntimeError):
    pass


def validate_url(url: str, *, redirect: bool) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise DownloadError("download URL left the HTTPS host allowlist")
    if parsed.query and (not redirect or parsed.hostname != ASSET_HOST):
        raise DownloadError("download URL contains an unauthorized query")
    return parsed


def fixed_request(url: str, *, redirect: bool) -> urllib.request.Request:
    validate_url(url, redirect=redirect)
    return urllib.request.Request(url, headers=FIXED_HEADERS, method="GET")


class AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.hosts: list[str] = []

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request:
        if code not in {301, 302, 303, 307, 308}:
            raise DownloadError("unsupported release redirect status")
        if len(self.hosts) >= MAX_REDIRECTS:
            raise DownloadError("release redirect limit exceeded")
        parsed = validate_url(newurl, redirect=True)
        self.hosts.append(str(parsed.hostname))
        return fixed_request(newurl, redirect=True)


def build_opener(redirects: AllowlistedRedirectHandler) -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
        redirects,
    )


def _validated_output_fd(fd: int) -> os.stat_result:
    if fd < 3:
        raise DownloadError("invalid archive descriptor")
    os.set_inheritable(fd, False)
    metadata = os.fstat(fd)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise DownloadError("archive descriptor is unsafe")
    return metadata


def download_to_fd(
    fd: int,
    *,
    opener: Any | None = None,
    redirects: AllowlistedRedirectHandler | None = None,
) -> dict[str, Any]:
    _validated_output_fd(fd)
    redirect_handler = redirects or AllowlistedRedirectHandler()
    active_opener = opener or build_opener(redirect_handler)
    request = fixed_request(ASSET_URL, redirect=False)
    deadline = time.monotonic() + CHILD_DEADLINE_SECONDS
    digest = hashlib.sha256()
    total = 0
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        response = active_opener.open(request, timeout=SOCKET_TIMEOUT_SECONDS)
        with response:
            status = int(getattr(response, "status", response.getcode()))
            if status != 200:
                raise DownloadError("release asset response was not HTTP 200")
            encoding = str(response.headers.get("Content-Encoding") or "identity")
            if encoding.lower() != "identity":
                raise DownloadError("release asset used unsupported content encoding")
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    declared = int(raw_length)
                except ValueError as error:
                    raise DownloadError("release asset length is malformed") from error
                if declared < 0 or declared > MAX_ARCHIVE_BYTES:
                    raise DownloadError("release asset exceeds byte limit")
            while True:
                if time.monotonic() >= deadline:
                    raise DownloadError("release asset child deadline exceeded")
                chunk = response.read(min(READ_BYTES, MAX_ARCHIVE_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise DownloadError("release asset exceeds byte limit")
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short release archive write")
                    view = view[written:]
    except (socket.timeout, TimeoutError) as error:
        raise DownloadError("release asset socket operation timed out") from error
    if total <= 0:
        raise DownloadError("release asset was empty")
    os.fsync(fd)
    return {
        "bytes": total,
        "sha256": digest.hexdigest(),
        "redirect_count": len(redirect_handler.hosts),
        "redirect_hosts": list(redirect_handler.hosts),
        "initial_host": "github.com",
    }


def runtime_evidence(archive_fd: int) -> dict[str, Any]:
    inherited_fds: list[int] = []
    try:
        candidates = {
            int(name)
            for name in os.listdir("/dev/fd")
            if name.isascii() and name.isdigit()
        }
    except OSError as error:
        raise DownloadError("unable to enumerate inherited descriptors") from error
    for candidate in sorted(candidates):
        try:
            os.fstat(candidate)
        except OSError:
            continue
        inherited_fds.append(candidate)
    expected_fds = {0, 1, 2, archive_fd}
    if set(inherited_fds) != expected_fds:
        raise DownloadError("downloader inherited an unauthorized descriptor")
    environment_keys = sorted(os.environ)
    if set(environment_keys) != EXPECTED_ENVIRONMENT_KEYS:
        raise DownloadError("downloader inherited an unauthorized environment key")
    return {
        "asset_url": ASSET_URL,
        "archive_fd": archive_fd,
        "inherited_fds": inherited_fds,
        "environment_keys": environment_keys,
        "pid": os.getpid(),
        "process_group_id": os.getpgrp(),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(json.dumps({"result": "FAIL", "reason": "invalid arguments"}))
        return 2
    try:
        fd = int(argv[0])
        evidence = runtime_evidence(fd)
        report = download_to_fd(fd)
    except (DownloadError, OSError, ValueError, urllib.error.URLError) as error:
        reason = str(error) if isinstance(error, DownloadError) else "download failed closed"
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "reason": reason,
                    "error_type": type(error).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"result": "PASS", **evidence, **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
