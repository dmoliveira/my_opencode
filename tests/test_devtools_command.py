from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import devtools_command as devtools
from playwright_defaults import (
    PLAYWRIGHT_CLI_INTEGRITY,
    PLAYWRIGHT_CLI_LICENSE,
    PLAYWRIGHT_CLI_NODE_RANGE,
    PLAYWRIGHT_CLI_PACKAGE_SPEC,
    PLAYWRIGHT_CLI_SHASUM,
    PLAYWRIGHT_CLI_VERSION,
)


def metadata(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": PLAYWRIGHT_CLI_VERSION,
        "license": PLAYWRIGHT_CLI_LICENSE,
        "engines": {"node": PLAYWRIGHT_CLI_NODE_RANGE},
        "dist": {
            "integrity": PLAYWRIGHT_CLI_INTEGRITY,
            "shasum": PLAYWRIGHT_CLI_SHASUM,
        },
        "scripts": {"test": "playwright test"},
    }
    payload.update(overrides)
    return payload


def completed(
    command: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class DevtoolsPlaywrightCliTest(unittest.TestCase):
    def test_linux_without_homebrew_verifies_exact_cli_in_isolated_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="devtools-cli-test-") as raw_tmp:
            root = Path(raw_tmp)
            host_home = root / "host-home"
            host_home.mkdir()
            (host_home / ".npmrc").write_text(
                "//registry.npmjs.org/:_authToken=HOST_NPM_TOKEN\n",
                encoding="utf-8",
            )
            calls: list[tuple[list[str], dict[str, str]]] = []

            def which(name: str) -> str | None:
                if name == "brew":
                    return None
                return f"/fake/{name}"

            def run(command, **kwargs):
                command = list(command)
                env = dict(kwargs.get("env") or {})
                calls.append((command, env))
                if command[-1] == "--version" and "node" in command[0]:
                    return completed(command, stdout="v18.20.0\n")
                if command[:2] == ["npm", "view"]:
                    return completed(command, stdout=json.dumps(metadata()))
                if command[:3] == ["npx", "--yes", PLAYWRIGHT_CLI_PACKAGE_SPEC]:
                    return completed(command, stdout=f"{PLAYWRIGHT_CLI_VERSION}\n")
                raise AssertionError(f"unexpected command: {command}")

            cache_root = root / "cache-root"
            with (
                patch.dict(
                    os.environ,
                    {
                        "HOME": str(host_home),
                        "PATH": "/fake/bin",
                        "OPENAI_API_KEY": "MODEL_SECRET",
                        "NPM_TOKEN": "NPM_SECRET",
                        devtools.PLAYWRIGHT_CLI_CACHE_ENV: str(cache_root),
                    },
                    clear=True,
                ),
                patch.object(devtools.shutil, "which", side_effect=which),
                patch.object(devtools.subprocess, "run", side_effect=run),
            ):
                self.assertEqual(0, devtools.install_tools(["playwright-cli"]))

            npm_calls = [item for item in calls if item[0][0] in {"npm", "npx"}]
            self.assertEqual(2, len(npm_calls))
            self.assertEqual(
                ["npx", "--yes", PLAYWRIGHT_CLI_PACKAGE_SPEC, "--version"],
                npm_calls[1][0],
            )
            for _, env in npm_calls:
                self.assertNotIn("OPENAI_API_KEY", env)
                self.assertNotIn("NPM_TOKEN", env)
                self.assertEqual("true", env["npm_config_ignore_scripts"])
                self.assertEqual("https://registry.npmjs.org/", env["npm_config_registry"])
                self.assertNotEqual(str(host_home), env["HOME"])
                self.assertEqual("", Path(env["npm_config_userconfig"]).read_text())
                self.assertEqual("", Path(env["npm_config_globalconfig"]).read_text())

            cache = cache_root / "playwright-cli" / PLAYWRIGHT_CLI_VERSION
            attestation = cache / devtools.PLAYWRIGHT_CLI_ATTESTATION
            self.assertEqual(0o700, stat.S_IMODE(cache.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(attestation.stat().st_mode))
            self.assertEqual(
                PLAYWRIGHT_CLI_PACKAGE_SPEC,
                json.loads(attestation.read_text())["package_spec"],
            )
            self.assertEqual("verified", devtools._attestation_state(cache))
            tampered = json.loads(attestation.read_text())
            tampered["provenance"]["expected"]["integrity"] = "sha512-drift"
            tampered["provenance"]["observed"]["integrity"] = "sha512-drift"
            attestation.write_text(json.dumps(tampered), encoding="utf-8")
            attestation.chmod(0o600)
            self.assertEqual("drift", devtools._attestation_state(cache))

    def test_node_before_18_fails_before_registry_or_package_execution(self) -> None:
        calls: list[list[str]] = []

        def run(command, **_kwargs):
            command = list(command)
            calls.append(command)
            return completed(command, stdout="v16.20.2\n")

        with (
            patch.object(
                devtools.shutil, "which", side_effect=lambda name: f"/fake/{name}"
            ),
            patch.object(devtools.subprocess, "run", side_effect=run),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(1, devtools.install_playwright_cli())
        self.assertEqual(1, len(calls))
        self.assertIn("node", calls[0][0])

    def test_metadata_drift_fails_closed_before_npx(self) -> None:
        cases = {
            "version": {"version": "0.1.18"},
            "license": {"license": "MIT"},
            "integrity": {
                "dist": {"integrity": "sha512-drift", "shasum": PLAYWRIGHT_CLI_SHASUM}
            },
            "lifecycle": {"scripts": {"postinstall": "curl example.invalid"}},
        }
        for label, override in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw_tmp:
                calls: list[list[str]] = []

                def run(command, _calls=calls, _override=override, **_kwargs):
                    command = list(command)
                    _calls.append(command)
                    if "node" in command[0]:
                        return completed(command, stdout="v22.0.0\n")
                    if command[:2] == ["npm", "view"]:
                        return completed(
                            command, stdout=json.dumps(metadata(**_override))
                        )
                    raise AssertionError("npx must not execute after provenance drift")

                with (
                    patch.dict(
                        os.environ,
                        {devtools.PLAYWRIGHT_CLI_CACHE_ENV: raw_tmp},
                        clear=False,
                    ),
                    patch.object(
                        devtools.shutil,
                        "which",
                        side_effect=lambda name: f"/fake/{name}",
                    ),
                    patch.object(devtools.subprocess, "run", side_effect=run),
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(1, devtools.install_playwright_cli())
                self.assertFalse(any(command[0] == "npx" for command in calls))

    def test_install_all_remains_homebrew_only(self) -> None:
        with (
            patch.object(devtools, "install_playwright_cli") as cli_install,
            patch.object(devtools, "tool_installed", return_value=True),
            patch.object(devtools.shutil, "which", return_value="/fake/brew"),
            patch.object(devtools, "print_status", return_value=0),
        ):
            self.assertEqual(0, devtools.install_tools(["all"]))
        cli_install.assert_not_called()

    def test_doctor_treats_optional_absence_as_warning_without_running_package(self) -> None:
        commands: list[list[str]] = []

        def run(command, **_kwargs):
            command = list(command)
            commands.append(command)
            if "node" in command[0]:
                return completed(command, stdout="v22.0.0\n")
            raise AssertionError("doctor must not execute npm, npx, or browser code")

        installed = {
            name: {
                "installed": True,
                "binary": data["bin"],
                "path": f"/fake/{data['bin']}",
            }
            for name, data in devtools.TOOLS.items()
        }
        with (
            tempfile.TemporaryDirectory() as raw_tmp,
            patch.dict(
                os.environ,
                {devtools.PLAYWRIGHT_CLI_CACHE_ENV: raw_tmp},
                clear=False,
            ),
            patch.object(devtools, "list_status", return_value=installed),
            patch.object(
                devtools.shutil,
                "which",
                side_effect=lambda name: f"/fake/{name}",
            ),
            patch.object(devtools.subprocess, "run", side_effect=run),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(0, devtools.print_doctor(json_output=True))
        report = json.loads(output.getvalue())
        self.assertEqual("PASS", report["result"])
        self.assertFalse(report["optional"]["playwright-cli"]["ready"])
        self.assertEqual(1, len(commands))
        self.assertIn("node", commands[0][0])


if __name__ == "__main__":
    unittest.main()
