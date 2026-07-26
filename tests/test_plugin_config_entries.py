from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gateway_plugin_bridge
import plugin_command


class PluginConfigEntriesTest(unittest.TestCase):
    def test_gateway_tuple_detection_and_mutation_preserve_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            gateway = [
                gateway_plugin_bridge.gateway_plugin_spec(home),
                {"hooks": {"enabled": False}, "secret": "WAVE3_OPTION_SENTINEL"},
            ]
            external = ["@scope/external@1.2.3", {"mode": "safe"}]
            malformed = ["@scope/malformed", "not-an-object"]
            config = {
                "plugin": [gateway, "@superwhisper/opencode", external, malformed, gateway.copy()]
            }

            self.assertTrue(gateway_plugin_bridge.plugin_enabled(config, home))
            self.assertEqual(
                [gateway_plugin_bridge.gateway_plugin_spec(home)] * 2,
                gateway_plugin_bridge.gateway_plugin_entries(config, home),
            )
            gateway_plugin_bridge.set_plugin_enabled(config, home, True)
            self.assertEqual(gateway, config["plugin"][0])
            self.assertEqual(1, config["plugin"].count(gateway))
            self.assertIn(external, config["plugin"])
            self.assertIn(malformed, config["plugin"])

            gateway_plugin_bridge.set_plugin_enabled(config, home, False)
            self.assertFalse(gateway_plugin_bridge.plugin_enabled(config, home))
            self.assertIn(external, config["plugin"])
            self.assertIn(malformed, config["plugin"])

    def test_profiles_preserve_unknown_and_selected_known_tuples(self) -> None:
        notifier = [plugin_command.KNOWN_PLUGINS["notifier"], {"quiet": True}]
        morph = [plugin_command.KNOWN_PLUGINS["morph"], {"tokenRef": "env:MORPH_API_KEY"}]
        external = ["@scope/external", {"mode": "safe"}]
        malformed = ["@scope/malformed", 3]
        entries = [notifier, morph, external, malformed]

        stable = plugin_command.compose_plugin_entries(
            entries, [plugin_command.KNOWN_PLUGINS["notifier"]]
        )
        self.assertEqual(notifier, stable[0])
        self.assertNotIn(morph, stable)
        self.assertEqual([external, malformed], stable[1:])

    def test_plugin_profile_round_trip_keeps_tuple_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            config_path = Path(tmp) / "opencode.json"
            notifier = [plugin_command.KNOWN_PLUGINS["notifier"], {"quiet": True}]
            external = ["@scope/external", {"mode": "safe"}]
            config_path.write_text(
                json.dumps({"plugin": [notifier, external]}, indent=2) + "\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "OPENCODE_CONFIG_PATH": str(config_path),
                    "CI": "true",
                }
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "plugin_command.py"), "profile", "stable"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn(notifier, saved["plugin"])
            self.assertIn(external, saved["plugin"])

    def test_blocked_gateway_enable_skips_compatibility_mutation(self) -> None:
        module = importlib.import_module("gateway_command")
        staged_status = {
            "plugin_dir_exists": False,
            "plugin_dist_exists": False,
            "bun_available": False,
            "hook_diagnostics": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "opencode.json"
            config = {"plugin": [["@scope/external", {"mode": "safe"}]]}
            with (
                patch.object(module, "load_config", return_value=(config, config_path)),
                patch.object(
                    module,
                    "status_payload",
                    side_effect=[staged_status, {"enabled": False}],
                ),
                patch.object(module, "ensure_file_plugin_compat") as compat,
                patch.object(module, "save_config") as save,
                patch.object(module, "emit"),
            ):
                self.assertEqual(1, module.command_enable(as_json=True))
            compat.assert_not_called()
            save.assert_not_called()

    def test_blocked_gateway_enable_leaves_config_bytes_and_options_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            config_path = Path(tmp) / "opencode.json"
            payload = {
                "plugin": [
                    ["@scope/external", {"secret": "WAVE3_PRIVATE_OPTION"}],
                    "@superwhisper/opencode",
                ]
            }
            original = json.dumps(payload, indent=2) + "\n"
            config_path.write_text(original, encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "OPENCODE_CONFIG_PATH": str(config_path),
                    "CI": "true",
                    "GIT_TERMINAL_PROMPT": "0",
                }
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "gateway_command.py"), "enable", "--json"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            self.assertEqual(original, config_path.read_text(encoding="utf-8"))
            self.assertNotIn("WAVE3_PRIVATE_OPTION", result.stdout)
            self.assertNotIn("WAVE3_PRIVATE_OPTION", result.stderr)


if __name__ == "__main__":
    unittest.main()
