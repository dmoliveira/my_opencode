#!/usr/bin/env python3
"""Run unittest without inherited Git overrides that can redirect fixtures."""

from __future__ import annotations

import os
import subprocess
import sys


def isolated_environment(environment: dict[str, str]) -> dict[str, str]:
    result = {
        key: value for key, value in environment.items() if not key.startswith("GIT_")
    }
    result.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
        }
    )
    return result


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", *sys.argv[1:]],
        env=isolated_environment(dict(os.environ)),
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
