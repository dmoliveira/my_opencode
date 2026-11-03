from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_layering import ConfigTransactionError  # noqa: E402
from tui_config import (  # noqa: E402
    TUI_SCHEMA,
    OpenCodeVersionProbeError,
    _require_v1_cli,
    ensure_execution_sidebar,
)


class TuiConfigTests(unittest.TestCase):
    def test_adds_sidebar_without_replacing_existing_tui_settings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tui-config-") as raw_tmp:
            tmp = Path(raw_tmp)
            config = tmp / "home" / ".config" / "opencode" / "tui.json"
            config.parent.mkdir(parents=True)
            config.write_text(
                json.dumps(
                    {
                        "$schema": TUI_SCHEMA,
                        "theme": "custom",
                        "plugin": [["npm:existing-plugin", {"option": True}]],
                    }
                ),
                encoding="utf-8",
            )
            plugin = tmp / "plugin" / "gateway-sidebar"
            plugin.mkdir(parents=True)

            result = ensure_execution_sidebar(config, plugin)

            self.assertTrue(result.changed)
            loaded = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(loaded["theme"], "custom")
            self.assertEqual(loaded["plugin"][0], ["npm:existing-plugin", {"option": True}])
            self.assertIn([plugin.resolve().as_uri(), {}], loaded["plugin"])
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tui-config-") as raw_tmp:
            tmp = Path(raw_tmp)
            config = tmp / "tui.json"
            plugin = tmp / "plugin" / "gateway-sidebar"
            plugin.mkdir(parents=True)

            ensure_execution_sidebar(config, plugin)
            result = ensure_execution_sidebar(config, plugin)

            self.assertFalse(result.changed)
            loaded = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(loaded["plugin"], [[plugin.resolve().as_uri(), {}]])

    def test_replaces_stale_managed_entries_and_preserves_first_tuple_options(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tui-config-") as raw_tmp:
            tmp = Path(raw_tmp)
            config = tmp / "home" / ".config" / "opencode" / "tui.json"
            config.parent.mkdir(parents=True)
            plugin = tmp / "current" / "plugin" / "gateway-sidebar"
            plugin.mkdir(parents=True)
            stale_plugin = (
                tmp / "my_opencode-wt-previous" / "plugin" / "gateway-sidebar"
            )
            unrelated_local_plugin = tmp / "acme" / "plugin" / "gateway-sidebar"
            nested_unrelated_local_plugin = (
                tmp / "my_opencode" / "vendor" / "acme" / "plugin" / "gateway-sidebar"
            )
            config.write_text(
                json.dumps(
                    {
                        "theme": "custom",
                        "plugin": [
                            [
                                stale_plugin.as_uri(),
                                {"enabled": True, "position": "right"},
                            ],
                            "file://{env:HOME}/.config/opencode/my_opencode/plugin/gateway-sidebar",
                            "FILE://{env:HOME}/.config/opencode/my_opencode/plugin/gateway-sidebar",
                            [unrelated_local_plugin.as_uri(), {"keep": "local"}],
                            [
                                nested_unrelated_local_plugin.as_uri(),
                                {"keep": "nested-local"},
                            ],
                            ["npm:unrelated", {"keep": True}],
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"HOME": str(tmp / "home")}):
                result = ensure_execution_sidebar(config, plugin)

            self.assertTrue(result.changed)
            loaded = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(loaded["theme"], "custom")
            self.assertEqual(
                loaded["plugin"],
                [
                    [
                        plugin.resolve().as_uri(),
                        {"enabled": True, "position": "right"},
                    ],
                    [unrelated_local_plugin.as_uri(), {"keep": "local"}],
                    [
                        nested_unrelated_local_plugin.as_uri(),
                        {"keep": "nested-local"},
                    ],
                    ["npm:unrelated", {"keep": True}],
                ],
            )

            with patch.dict(os.environ, {"HOME": str(tmp / "home")}):
                second = ensure_execution_sidebar(config, plugin)
            self.assertFalse(second.changed)

    def test_rejects_non_array_plugin_configuration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tui-config-") as raw_tmp:
            tmp = Path(raw_tmp)
            config = tmp / "tui.json"
            config.write_text('{"plugin": {}}', encoding="utf-8")
            plugin = tmp / "plugin" / "gateway-sidebar"
            plugin.mkdir(parents=True)

            with self.assertRaises(ConfigTransactionError):
                ensure_execution_sidebar(config, plugin)

            self.assertEqual(config.read_text(encoding="utf-8"), '{"plugin": {}}')


class TuiRuntimeGuardTests(unittest.TestCase):
    def test_only_fully_parsed_v1_versions_are_accepted(self) -> None:
        for version in ("1.18.18", "opencode v1.18.18", "1.2.3-rc.1"):
            with self.subTest(version=version), patch("tui_config.probe_opencode_version", return_value=version):
                _require_v1_cli()
        for version in ("2.2.5", "3.0.0", "0.9.0", "unknown", "1.18", "prefix 1.18.18", "1.18.18 trailing"):
            with self.subTest(version=version), patch("tui_config.probe_opencode_version", return_value=version), self.assertRaisesRegex(ValueError, "verified OpenCode V1"):
                _require_v1_cli()

    def test_failed_probe_does_not_expose_diagnostics(self) -> None:
        with patch("tui_config.probe_opencode_version", side_effect=OpenCodeVersionProbeError("SECRET_CANARY")), self.assertRaises(ValueError) as caught:
            _require_v1_cli()
        self.assertNotIn("SECRET_CANARY", str(caught.exception))


@unittest.skipUnless(os.name == "posix", "fixture executables require POSIX")
class TuiConfigCliTests(unittest.TestCase):
    @staticmethod
    def fixture(root: Path, version_script: str | None) -> tuple[dict[str, str], Path, Path, Path, Path]:
        home = root / "home"
        config_dir = home / ".config" / "opencode"
        plugin = root / "plugin" / "gateway-sidebar"
        binary_dir = root / "bin"
        temporary = root / "tmp"
        for directory in (config_dir, plugin, binary_dir, temporary):
            directory.mkdir(parents=True)
        cli = config_dir / "cli.json"
        cli.write_text('{"theme":{"name":"synthetic"},"plugins":[]}\n', encoding="utf-8")
        runtime = home / "runtime.sqlite"
        runtime.write_text("synthetic runtime sentinel\n", encoding="utf-8")
        if version_script is not None:
            binary = binary_dir / "opencode"
            binary.write_text(
                "#!/bin/sh\n"
                '[ "$#" = 1 ] && [ "$1" = "--version" ] || exit 99\n'
                'printf probe > "$HOME/probe-home"\n'
                'printf probe > "$PWD/probe-cwd"\n'
                'if [ -n "${OPENCODE_DB:-}" ]; then printf changed > "$OPENCODE_DB"; fi\n'
                + version_script + "\n",
                encoding="utf-8",
            )
            binary.chmod(0o700)
        env = {
            "HOME": str(home), "PATH": str(binary_dir), "TMPDIR": str(temporary),
            "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / "data"),
            "XDG_STATE_HOME": str(home / "state"), "XDG_CACHE_HOME": str(home / "cache"),
            "OPENCODE_DB": str(runtime), "PYTHONDONTWRITEBYTECODE": "1", "CI": "true",
        }
        return env, config_dir, plugin, cli, runtime

    @staticmethod
    def run_cli(env: dict[str, str], config: Path, plugin: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tui_config.py"), "ensure-execution-sidebar",
             "--config", str(config), "--plugin-path", str(plugin), "--json"],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12, check=False,
        )

    def test_unverified_and_v2_runtimes_refuse_without_config_writes(self) -> None:
        cases = {
            "missing": None,
            "v2": 'printf "opencode v2.2.5\\n"',
            "future": 'printf "3.0.0\\n"',
            "malformed": 'printf "unexpected version\\n"',
            "failed": 'printf "1.18.18\\n"; exit 1',
            "invalid_utf8": "printf '\\377'",
            "oversized": "printf '" + ("x" * 513) + "'",
        }
        for label, script in cases.items():
            for existing in (True, False):
                with self.subTest(runtime=label, existing=existing), tempfile.TemporaryDirectory(prefix="tui-v2-guard-") as raw:
                    root = Path(raw)
                    env, config_dir, plugin, cli, runtime = self.fixture(root, script)
                    tui = config_dir / "tui.json" if existing else config_dir / "new" / "tui.json"
                    if existing:
                        tui.write_text('{"theme":"legacy-sentinel"}\n', encoding="utf-8")
                    paths = (cli, runtime, tui) if existing else (cli, runtime)
                    before = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mode) for path in paths}
                    result = self.run_cli(env, tui, plugin)
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn("OpenCode V1", result.stderr)
                    self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mode) for path in paths})
                    self.assertFalse((Path(env["HOME"]) / "probe-home").exists())
                    self.assertFalse((root / "probe-cwd").exists())
                    self.assertFalse((config_dir / "new").exists())
                    self.assertEqual(list((root / "tmp").iterdir()), [])

    def test_verified_v1_writes_only_legacy_config_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tui-v1-guard-") as raw:
            root = Path(raw)
            env, config_dir, plugin, cli, runtime = self.fixture(root, 'printf "opencode v1.18.18\\n"')
            tui = config_dir / "tui.json"
            tui.write_text('{"theme":"legacy-sentinel"}\n', encoding="utf-8")
            cli_before, runtime_before = cli.read_bytes(), runtime.read_bytes()
            first = self.run_cli(env, tui, plugin)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(json.loads(first.stdout)["changed"])
            loaded = json.loads(tui.read_text(encoding="utf-8"))
            self.assertEqual(loaded["theme"], "legacy-sentinel")
            self.assertEqual(loaded["plugin"], [[plugin.resolve().as_uri(), {}]])
            self.assertEqual(cli.read_bytes(), cli_before)
            self.assertEqual(runtime.read_bytes(), runtime_before)
            second = self.run_cli(env, tui, plugin)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(json.loads(second.stdout)["changed"])
            self.assertFalse((Path(env["HOME"]) / "probe-home").exists())
            self.assertEqual(list((root / "tmp").iterdir()), [])

    def test_hung_version_probe_refuses_before_creating_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tui-hung-guard-") as raw:
            root = Path(raw)
            env, config_dir, plugin, cli, runtime = self.fixture(root, "exec /bin/sleep 30")
            env["MY_OPENCODE_VERSION_PROBE_TIMEOUT_SECONDS"] = "0.2"
            cli_before, runtime_before = cli.read_bytes(), runtime.read_bytes()
            tui = config_dir / "new" / "tui.json"
            result = self.run_cli(env, tui, plugin)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("unable to verify", result.stderr)
            self.assertFalse(tui.parent.exists())
            self.assertEqual(cli.read_bytes(), cli_before)
            self.assertEqual(runtime.read_bytes(), runtime_before)
            self.assertEqual(list((root / "tmp").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
