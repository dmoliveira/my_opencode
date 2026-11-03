"""Read an OpenCode executable's version without using the user's runtime home."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from bounded_subprocess import BoundedCommandError, run_bounded


class OpenCodeVersionProbeError(RuntimeError):
    """The selected executable could not be safely identified."""


def probe_opencode_version(binary: str | None = None) -> str:
    selected = binary if binary is not None else shutil.which("opencode")
    if not selected:
        raise OpenCodeVersionProbeError("OpenCode executable unavailable")
    # Even --version can create logs and caches. Restrict the child environment
    # and working directory to a disposable home, independently of user XDG paths.
    try:
        with tempfile.TemporaryDirectory(prefix="my-opencode-version-") as home:
            env = {
                key: os.environ[key]
                for key in (
                    "PATH",
                    "LANG",
                    "LC_ALL",
                    "SYSTEMROOT",
                    "WINDIR",
                    "PATHEXT",
                    "COMSPEC",
                )
                if key in os.environ
            }
            env.update(
                CI="true",
                GIT_TERMINAL_PROMPT="0",
                GCM_INTERACTIVE="never",
                HOME=home,
                USERPROFILE=home,
                APPDATA=os.path.join(home, "appdata"),
                LOCALAPPDATA=os.path.join(home, "localappdata"),
                XDG_CONFIG_HOME=os.path.join(home, "config"),
                XDG_DATA_HOME=os.path.join(home, "data"),
                XDG_STATE_HOME=os.path.join(home, "state"),
                XDG_CACHE_HOME=os.path.join(home, "cache"),
                XDG_RUNTIME_DIR=home,
                TMPDIR=home,
                TMP=home,
                TEMP=home,
            )
            result = run_bounded(
                [os.path.abspath(selected), "--version"],
                operation="opencode_version_probe",
                cwd=home,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                max_output_bytes=512,
            )
    except (BoundedCommandError, OSError, ValueError) as error:
        raise OpenCodeVersionProbeError("OpenCode version probe failed") from error
    if result.returncode != 0:
        raise OpenCodeVersionProbeError("OpenCode version probe failed")
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise OpenCodeVersionProbeError("OpenCode version probe failed") from error
