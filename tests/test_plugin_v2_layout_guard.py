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
sys.path.insert(0, str(ROOT / "scripts"))

import plugin_command
from config_layering import ConfigTransactionError


class PluginV2LayoutGuardTest(unittest.TestCase):
    def run_cli(
        self, home: Path, cwd: Path, *args: str, config: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_STATE_HOME": str(home / "state"),
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C",
            "CI": "true",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if config is not None:
            env["OPENCODE_CONFIG_PATH"] = str(config)
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "plugin_command.py"), *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_native_layouts_refuse_reports_and_mutations_without_writing(self) -> None:
        retired = plugin_command.RETIRED_PLUGINS["notifier"]
        layouts = (
            [retired],
            [{"package": retired, "options": {"token": "PLUGIN_SYNTHETIC_SECRET"}}],
            [],
            None,
            {"token": "PLUGIN_SYNTHETIC_SECRET"},
            "PLUGIN_SYNTHETIC_SECRET",
        )
        actions = (
            (),
            ("status",),
            ("doctor",),
            ("setup-keys",),
            ("profile", "lean"),
            ("profile", "stable"),
            ("profile", "experimental"),
            ("disable", "notifier"),
            ("disable", "morph"),
            ("disable", "worktree"),
            ("disable", "all"),
        )
        for layout in layouts:
            for action in actions:
                with (
                    self.subTest(layout=type(layout).__name__, action=action),
                    tempfile.TemporaryDirectory() as raw,
                ):
                    root = Path(raw)
                    home = root / "home"
                    home.mkdir()
                    config = root / "opencode.json"
                    original = (
                        json.dumps(
                            {
                                "plugin": [[retired, {"legacy": True}]],
                                "plugins": layout,
                                "keep": [1, 2],
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                    config.write_text(original, encoding="utf-8")
                    result = self.run_cli(home, root, *action, config=config)
                    combined = result.stdout + result.stderr
                    self.assertNotEqual(0, result.returncode, combined)
                    self.assertIn("plugins", combined)
                    self.assertNotIn("PLUGIN_SYNTHETIC_SECRET", combined)
                    self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_json_doctor_fails_structurally_without_native_options(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            config = root / "opencode.json"
            original = (
                json.dumps(
                    {
                        "plugins": [
                            {
                                "package": plugin_command.RETIRED_PLUGINS["notifier"],
                                "options": {"token": "PLUGIN_SYNTHETIC_SECRET"},
                            }
                        ]
                    }
                )
                + "\n"
            )
            config.write_text(original, encoding="utf-8")
            result = self.run_cli(home, root, "doctor", "--json", config=config)
            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("PLUGIN_SYNTHETIC_SECRET", result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual("FAIL", report["result"])
            self.assertEqual("plugin_native_layout_unsupported", report["reason_code"])
            self.assertEqual("helper_resolved_layers", report["configuration_scope"])
            self.assertIs(report["runtime_state_verified"], False)
            self.assertEqual({}, report["plugins"])
            self.assertEqual(original, config.read_text(encoding="utf-8"))

            help_result = self.run_cli(home, root, "help", config=config)
            self.assertEqual(0, help_result.returncode)
            self.assertNotIn("PLUGIN_SYNTHETIC_SECRET", help_result.stdout)
            enable = self.run_cli(home, root, "enable", "notifier", config=config)
            self.assertNotEqual(0, enable.returncode)
            self.assertNotIn("PLUGIN_SYNTHETIC_SECRET", enable.stdout + enable.stderr)
            self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_escaped_native_key_is_rejected_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            config = root / "opencode.json"
            original = '{"\\u0070lugins": [{"package": "./synthetic"}]}\n'
            config.write_text(original, encoding="utf-8")
            result = self.run_cli(home, root, "disable", "notifier", config=config)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("plugins", result.stdout + result.stderr)
            self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_native_user_layer_blocks_legacy_project_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            project = root / "project"
            user_config = home / ".config" / "opencode" / "opencode.json"
            project_config = project / ".opencode" / "my_opencode.json"
            user_config.parent.mkdir(parents=True)
            project_config.parent.mkdir(parents=True)
            user_bytes = '{"plugins":[{"package":"./synthetic"}]}\n'
            project_bytes = '{"plugin":[]}\n'
            user_config.write_text(user_bytes, encoding="utf-8")
            project_config.write_text(project_bytes, encoding="utf-8")
            result = self.run_cli(home, project, "disable", "notifier")
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("plugins", result.stdout + result.stderr)
            self.assertEqual(user_bytes, user_config.read_text(encoding="utf-8"))
            self.assertEqual(project_bytes, project_config.read_text(encoding="utf-8"))

    def test_actual_locked_mutations_recheck_after_stale_preflight_view(self) -> None:
        for action in (
            ("disable", "notifier"),
            ("disable", "all"),
            ("profile", "lean"),
        ):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                home = root / "home"
                home.mkdir()
                config = root / "opencode.json"
                original = '{"plugins":[{"package":"./synthetic"}]}\n'
                config.write_text(original, encoding="utf-8")
                env = {"HOME": str(home), "OPENCODE_CONFIG_PATH": str(config)}
                stale_view = {"plugin": []}
                with (
                    patch.dict(os.environ, env),
                    patch.object(
                        plugin_command, "load_config", return_value=stale_view
                    ),
                    self.assertRaises(ConfigTransactionError) as caught,
                ):
                    plugin_command.main(list(action))
                self.assertEqual(
                    "plugin_native_layout_unsupported", caught.exception.reason_code
                )
                self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_legacy_results_are_explicitly_config_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            config = root / "opencode.json"
            retired = plugin_command.RETIRED_PLUGINS["notifier"]
            config.write_text(
                json.dumps({"plugin": [retired]}) + "\n", encoding="utf-8"
            )
            status = self.run_cli(home, root, "status", config=config)
            self.assertEqual(0, status.returncode, status.stderr)
            self.assertIn("runtime state not verified", status.stdout.lower())
            disabled = self.run_cli(home, root, "disable", "notifier", config=config)
            self.assertEqual(0, disabled.returncode, disabled.stderr)
            self.assertIn("runtime state not verified", disabled.stdout.lower())
            self.assertEqual(
                [], json.loads(config.read_text(encoding="utf-8"))["plugin"]
            )
            doctor = self.run_cli(home, root, "doctor", "--json", config=config)
            self.assertEqual(0, doctor.returncode, doctor.stderr)
            report = json.loads(doctor.stdout)
            self.assertEqual("PASS", report["result"])
            self.assertEqual("helper_resolved_layers", report["configuration_scope"])
            self.assertIs(report["runtime_state_verified"], False)
            for action in (("doctor",), ("profile", "lean"), ("setup-keys",)):
                result = self.run_cli(home, root, *action, config=config)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("runtime state not verified", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
