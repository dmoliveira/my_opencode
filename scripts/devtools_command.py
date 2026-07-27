#!/usr/bin/env python3

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from playwright_defaults import (
    PLAYWRIGHT_CLI_COMMAND,
    PLAYWRIGHT_CLI_INTEGRITY,
    PLAYWRIGHT_CLI_LICENSE,
    PLAYWRIGHT_CLI_METADATA_FIELDS,
    PLAYWRIGHT_CLI_MIN_NODE_MAJOR,
    PLAYWRIGHT_CLI_NODE_RANGE,
    PLAYWRIGHT_CLI_PACKAGE_SPEC,
    PLAYWRIGHT_CLI_SHASUM,
    PLAYWRIGHT_CLI_SOURCE_REVISION,
    PLAYWRIGHT_CLI_VERSION,
    PLAYWRIGHT_CLI_VERSION_COMMAND,
    PLAYWRIGHT_CLI_VERSION_OUTPUT,
    inspect_playwright_cli_metadata,
    playwright_cli_npm_environment,
)

TOOLS = {
    "ast-grep": {"bin": "sg"},
    "direnv": {"bin": "direnv"},
    "ripgrep": {"bin": "rg"},
    "pre-commit": {"bin": "pre-commit"},
    "tmux": {"bin": "tmux"},
    "watchexec": {"bin": "watchexec"},
}
PLAYWRIGHT_CLI_TARGET = "playwright-cli"
PLAYWRIGHT_CLI_CACHE_ENV = "OPENCODE_DEVTOOLS_CACHE_ROOT"
PLAYWRIGHT_CLI_ATTESTATION = "provenance.json"
PLAYWRIGHT_CLI_COMMAND_TIMEOUT = 180
HOOK_INSTALL_TIMEOUT_SECONDS = 30


def usage() -> int:
    print(
        "usage: /devtools status | /devtools help | /devtools doctor [--json] | /devtools install [all|playwright-cli|<tool> ...] | /devtools hooks-install"
    )
    print(
        "observed tools: ast-grep, direnv, ripgrep, pre-commit, tmux, watchexec; optional exact installer: playwright-cli"
    )
    print(
        "notes: host tools are managed manually; install all is observation-only; playwright-cli requires an explicit exact install"
    )
    return 2


def installed_path(name: str) -> str | None:
    return shutil.which(TOOLS[name]["bin"])


def tool_installed(name: str) -> bool:
    return bool(installed_path(name))


def list_status() -> dict:
    result = {}
    for name in TOOLS:
        path = installed_path(name)
        result[name] = {
            "installed": tool_installed(name),
            "binary": TOOLS[name]["bin"],
            "path": path,
        }
    return result


def playwright_cli_cache_dir() -> Path:
    configured = os.environ.get(PLAYWRIGHT_CLI_CACHE_ENV, "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".cache" / "my_opencode" / "devtools"
    return root / PLAYWRIGHT_CLI_TARGET / PLAYWRIGHT_CLI_VERSION


def _private_directory_state(path: Path) -> str:
    if not path.exists() and not path.is_symlink():
        return "absent"
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        return "unsafe"
    return "private"


def _prepare_private_directory(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
    if _private_directory_state(path) != "private":
        raise PermissionError(f"unsafe Playwright CLI cache directory: {path}")


def prepare_playwright_cli_cache(path: Path) -> None:
    _prepare_private_directory(path)
    for name in (
        "home",
        "tmp",
        "xdg-cache",
        "xdg-config",
        "npm-cache",
        "npm-prefix",
        "s",
    ):
        _prepare_private_directory(path / name)
    for name in ("user.npmrc", "global.npmrc"):
        config = path / name
        if config.exists() or config.is_symlink():
            metadata = config.lstat()
            if (
                config.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                raise PermissionError(f"unsafe npm config path: {config}")
        config.write_text("", encoding="utf-8")
        config.chmod(0o600)


def _node_version() -> tuple[str, int | None]:
    node = shutil.which("node")
    if not node:
        return "", None
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", None
    version = result.stdout.strip() if result.returncode == 0 else ""
    try:
        major = int(version.removeprefix("v").split(".", 1)[0])
    except (ValueError, IndexError):
        major = None
    return version, major


def _attestation_state(cache: Path) -> str:
    path = cache / PLAYWRIGHT_CLI_ATTESTATION
    if not path.is_file() or path.is_symlink():
        return "not_verified"
    metadata = path.stat()
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        return "drift"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "drift"
    provenance = payload.get("provenance") if isinstance(payload, dict) else None
    expected = {
        "version": PLAYWRIGHT_CLI_VERSION,
        "license": PLAYWRIGHT_CLI_LICENSE,
        "node_range": PLAYWRIGHT_CLI_NODE_RANGE,
        "integrity": PLAYWRIGHT_CLI_INTEGRITY,
        "shasum": PLAYWRIGHT_CLI_SHASUM,
        "lifecycle_scripts": [],
    }
    valid = all(
        (
            payload.get("package_spec") == PLAYWRIGHT_CLI_PACKAGE_SPEC,
            payload.get("command") == list(PLAYWRIGHT_CLI_COMMAND),
            payload.get("version_output") == PLAYWRIGHT_CLI_VERSION_OUTPUT,
            payload.get("source_revision") == PLAYWRIGHT_CLI_SOURCE_REVISION,
            isinstance(provenance, dict),
            provenance.get("verified") is True if isinstance(provenance, dict) else False,
            provenance.get("mismatches") == [] if isinstance(provenance, dict) else False,
            provenance.get("expected") == expected
            if isinstance(provenance, dict)
            else False,
            provenance.get("observed") == expected
            if isinstance(provenance, dict)
            else False,
        )
    )
    return "verified" if valid else "drift"


def playwright_cli_status() -> dict[str, Any]:
    cache = playwright_cli_cache_dir()
    cache_state = _private_directory_state(cache)
    node_version, node_major = _node_version()
    binaries = {name: bool(shutil.which(name)) for name in ("node", "npm", "npx")}
    missing_binaries = [name for name, present in binaries.items() if not present]
    attestation = (
        _attestation_state(cache) if cache_state == "private" else "not_verified"
    )
    if cache_state == "unsafe":
        attestation = "drift"
    node_supported = node_major is not None and node_major >= PLAYWRIGHT_CLI_MIN_NODE_MAJOR
    ready = not missing_binaries and node_supported and attestation == "verified"
    return {
        "optional": True,
        "ready": ready,
        "package_spec": PLAYWRIGHT_CLI_PACKAGE_SPEC,
        "version": PLAYWRIGHT_CLI_VERSION,
        "source_revision": PLAYWRIGHT_CLI_SOURCE_REVISION,
        "expected_integrity": PLAYWRIGHT_CLI_INTEGRITY,
        "invocation": list(PLAYWRIGHT_CLI_COMMAND),
        "node_version": node_version or None,
        "node_supported": node_supported,
        "missing_binaries": missing_binaries,
        "cache_state": cache_state,
        "attestation": attestation,
    }


def print_status() -> int:
    status = list_status()
    for name, data in status.items():
        if data["installed"]:
            print(f"{name}: installed ({data['path']})")
        else:
            print(f"{name}: missing")
    cli = playwright_cli_status()
    print(
        f"{PLAYWRIGHT_CLI_TARGET}: "
        + ("ready (verified exact package)" if cli["ready"] else f"optional ({cli['attestation']})")
    )
    print(f"  invocation: {' '.join(cli['invocation'])}")
    print(f"  expected integrity: {cli['expected_integrity']}")
    if cli["missing_binaries"]:
        print(f"  missing binaries: {', '.join(cli['missing_binaries'])}")
    missing = [name for name, data in status.items() if not data["installed"]]
    if missing:
        print("manual guidance:")
        for name in missing:
            print(f"- install {name} with your trusted host package workflow and expose {TOOLS[name]['bin']} on PATH")
    print("next:")
    print("- /devtools doctor --json")
    if not cli["ready"]:
        print("- /devtools install playwright-cli")
    print("- /devtools hooks-install")
    return 0


def print_doctor(json_output: bool) -> int:
    status = list_status()
    cli = playwright_cli_status()
    missing = [name for name, data in status.items() if not data["installed"]]
    optional_warnings = []
    if not cli["ready"]:
        optional_warnings.append(
            "optional playwright-cli is not ready; run /devtools install playwright-cli"
        )
    manual_guidance = [
        f"install {name} manually and expose {TOOLS[name]['bin']} on PATH"
        for name in missing
    ]
    report = {
        "result": "PASS",
        "tools": status,
        "optional": {PLAYWRIGHT_CLI_TARGET: cli},
        "missing": missing,
        "warnings": [*manual_guidance, *optional_warnings],
        "quick_fixes": [
            *manual_guidance,
            "run /devtools hooks-install after pre-commit is available",
            'enable direnv hook in your shell: eval "$(direnv hook zsh)"',
            "for browser-use, install browser-use-sdk manually and export BROWSER_USE_API_KEY before use",
            "for Context7, prefer a local CLI install only when you need it and keep remote MCP disabled by default",
        ]
        if missing
        else [],
    }

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print("devtools doctor")
        print("--------------")
        for name, data in status.items():
            state = "PASS" if data["installed"] else "MISSING (manual)"
            suffix = data["path"] if data["path"] else "not installed"
            print(f"- {name}: {state} ({suffix})")
        print(f"result: {report['result']}")
        for warning in optional_warnings:
            print(f"warning: {warning}")
        if missing:
            print("quick_fixes:")
            for item in report["quick_fixes"]:
                print(f"- {item}")

    return 0


def _parse_metadata(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_attestation(cache: Path, payload: dict[str, Any]) -> None:
    destination = cache / PLAYWRIGHT_CLI_ATTESTATION
    temporary = cache / f".{PLAYWRIGHT_CLI_ATTESTATION}.tmp"
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, destination)


def install_playwright_cli() -> int:
    missing = [name for name in ("node", "npm", "npx") if not shutil.which(name)]
    if missing:
        print(f"error: Playwright CLI requires: {', '.join(missing)}")
        return 1
    node_version, node_major = _node_version()
    if node_major is None or node_major < PLAYWRIGHT_CLI_MIN_NODE_MAJOR:
        print(
            f"error: Playwright CLI requires Node {PLAYWRIGHT_CLI_MIN_NODE_MAJOR}+ "
            f"(found {node_version or 'unknown'})"
        )
        return 1

    cache = playwright_cli_cache_dir()
    try:
        prepare_playwright_cli_cache(cache)
    except PermissionError as error:
        print(f"error: {error}")
        return 1
    env = playwright_cli_npm_environment(cache)
    metadata_command = [
        "npm",
        "view",
        PLAYWRIGHT_CLI_PACKAGE_SPEC,
        *PLAYWRIGHT_CLI_METADATA_FIELDS,
        "--json",
    ]
    try:
        metadata_result = subprocess.run(
            metadata_command,
            cwd=cache,
            env=env,
            capture_output=True,
            text=True,
            timeout=PLAYWRIGHT_CLI_COMMAND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("error: exact Playwright CLI registry metadata lookup timed out")
        return 1
    if metadata_result.returncode != 0:
        print("error: exact Playwright CLI registry metadata lookup failed")
        return 1
    provenance = inspect_playwright_cli_metadata(_parse_metadata(metadata_result.stdout))
    if not provenance["verified"]:
        print(
            "error: Playwright CLI provenance mismatch: "
            + ", ".join(provenance["mismatches"])
        )
        return 1

    try:
        version_result = subprocess.run(
            list(PLAYWRIGHT_CLI_VERSION_COMMAND),
            cwd=cache,
            env=env,
            capture_output=True,
            text=True,
            timeout=PLAYWRIGHT_CLI_COMMAND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("error: exact Playwright CLI version execution timed out")
        return 1
    version_output = version_result.stdout.strip()
    if version_result.returncode != 0 or version_output != PLAYWRIGHT_CLI_VERSION_OUTPUT:
        print("error: exact Playwright CLI version execution failed closed")
        return 1
    _write_attestation(
        cache,
        {
            "package_spec": PLAYWRIGHT_CLI_PACKAGE_SPEC,
            "command": list(PLAYWRIGHT_CLI_COMMAND),
            "version_output": version_output,
            "source_revision": PLAYWRIGHT_CLI_SOURCE_REVISION,
            "provenance": provenance,
        },
    )
    print(f"{PLAYWRIGHT_CLI_TARGET}: verified {version_output}")
    return 0


def install_tools(targets: list[str]) -> int:
    observe_all = not targets or targets == ["all"]
    names = list(TOOLS.keys()) if observe_all else targets
    valid_targets = {*TOOLS, PLAYWRIGHT_CLI_TARGET}
    invalid = [name for name in names if name not in valid_targets]
    if invalid:
        print(f"error: unknown tool(s): {', '.join(invalid)}")
        return usage()

    if PLAYWRIGHT_CLI_TARGET in names:
        if install_playwright_cli() != 0:
            return 1
        names = [name for name in names if name != PLAYWRIGHT_CLI_TARGET]
    if not names:
        return 0
    missing = []
    for name in names:
        if tool_installed(name):
            print(f"{name}: observed ({installed_path(name)})")
            continue
        missing.append(name)
        print(
            f"{name}: not installed; manage it manually and expose "
            f"{TOOLS[name]['bin']} on PATH"
        )

    if missing and not observe_all:
        return 1
    return 0


def hooks_install() -> int:
    pre_commit = shutil.which("pre-commit")
    if not pre_commit:
        print("error: pre-commit is missing; install it with your trusted host workflow")
        return 1

    try:
        installed = subprocess.run(
            [pre_commit, "install"],
            timeout=HOOK_INSTALL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("error: pre-commit hook installation timed out")
        return 1
    except OSError as error:
        print(f"error: unable to run pre-commit: {error}")
        return 1
    if installed.returncode != 0:
        return 1
    print("git hooks installed: pre-commit")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return print_status()
    if argv[0] == "help":
        return usage()
    if argv[0] == "doctor":
        if len(argv) > 2 or (len(argv) == 2 and argv[1] != "--json"):
            return usage()
        return print_doctor(json_output=(len(argv) == 2 and argv[1] == "--json"))
    if argv[0] == "install":
        return install_tools(argv[1:])
    if argv[0] == "hooks-install":
        return hooks_install()
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
