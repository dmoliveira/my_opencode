"""Preflight legacy setup and create instruction links without replacement."""

from __future__ import annotations

import argparse
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VERSION_PATTERN = re.compile(
    r"(?:opencode\s+)?v?([0-9]+)\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?"
)
VERSION_TIMEOUT_SECONDS = 5
MAX_VERSION_BYTES = 512


def _stop_probe(process: subprocess.Popen[bytes]) -> None:
    # Include children that may have inherited the probe's stdout.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _probe_version(binary: str, home: str) -> bytes:
    env = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ
    }
    env.update(
        CI="true",
        GIT_TERMINAL_PROMPT="0",
        GCM_INTERACTIVE="never",
        HOME=home,
        XDG_CONFIG_HOME=os.path.join(home, "config"),
        XDG_DATA_HOME=os.path.join(home, "data"),
        XDG_STATE_HOME=os.path.join(home, "state"),
        XDG_CACHE_HOME=os.path.join(home, "cache"),
        XDG_RUNTIME_DIR=home,
        TMPDIR=home,
        TMP=home,
        TEMP=home,
    )
    try:
        process = subprocess.Popen(
            [binary, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=home,
            env=env,
        )
    except OSError as error:
        raise ValueError("OpenCode is not installed or not on PATH") from error

    assert process.stdout is not None
    stdout = bytearray()
    deadline = time.monotonic() + VERSION_TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = max(0, deadline - time.monotonic())
                if not selector.select(remaining):
                    raise subprocess.TimeoutExpired(
                        process.args, VERSION_TIMEOUT_SECONDS
                    )
                chunk = os.read(
                    process.stdout.fileno(), MAX_VERSION_BYTES + 1 - len(stdout)
                )
                if not chunk:
                    break
                stdout.extend(chunk)
                if len(stdout) > MAX_VERSION_BYTES:
                    raise ValueError("unrecognized OpenCode version")
        process.wait(timeout=max(0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        _stop_probe(process)
        raise ValueError("OpenCode version probe timed out") from error
    except BaseException:
        _stop_probe(process)
        raise
    finally:
        process.stdout.close()

    if process.returncode != 0:
        raise ValueError("unable to determine OpenCode compatibility")
    return bytes(stdout)


def require_v1_runtime() -> None:
    binary = shutil.which("opencode")
    if binary is None:
        raise ValueError("OpenCode is not installed or not on PATH")
    # Even --version can create logs and caches; do not point it at user state.
    with tempfile.TemporaryDirectory(prefix="my-opencode-version-") as home:
        stdout = _probe_version(os.path.abspath(binary), home)
    try:
        version = stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValueError("unrecognized OpenCode version") from error
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError("unrecognized OpenCode version")
    if match.group(1) != "1":
        raise ValueError(
            "legacy setup requires OpenCode V1; V2 and other versions are unsupported"
        )


def _link_matches(link: Path, target: str) -> bool:
    return link.is_symlink() and os.path.realpath(link) == os.path.realpath(
        os.path.join(link.parent, target)
    )


def _check_link(link: Path, target: str) -> None:
    if os.path.lexists(link.parent) and not link.parent.is_dir():
        raise ValueError(f"link parent is not a directory: {link.parent}")
    if os.path.lexists(link) and not _link_matches(link, target):
        raise ValueError(f"refusing to replace existing path: {link}")


def instruction_links(
    repo: Path, config_dir: Path, agents_target: str, *, create: bool
) -> None:
    links = [(repo / "AGENTS.md", agents_target)]
    agent_dir = repo / "agent"
    if agent_dir.is_dir():
        links.extend(
            (config_dir / "agent" / path.name, str(path))
            for path in sorted(agent_dir.glob("*.md"))
            if not path.name.startswith(".") and path.exists()
        )

    for link, target in links:
        _check_link(link, target)
    if not create:
        return

    for link, target in links:
        if _link_matches(link, target):
            continue
        try:
            # os.symlink fails if anything already occupies the destination.
            os.symlink(target, link)
        except FileExistsError:
            if not _link_matches(link, target):
                raise ValueError(f"refusing to replace existing path: {link}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("runtime")
    links = subparsers.add_parser("links")
    links.add_argument("--repo", type=Path, required=True)
    links.add_argument("--config-dir", type=Path, required=True)
    links.add_argument("--agents-target", required=True)
    links.add_argument("--create", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "runtime":
            require_v1_runtime()
        else:
            instruction_links(
                args.repo, args.config_dir, args.agents_target, create=args.create
            )
    except (OSError, ValueError) as error:
        print(f"error: {error}; setup cannot proceed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
