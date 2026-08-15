from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_layering import ConfigTransactionError  # noqa: E402
from tui_config import TUI_SCHEMA, ensure_execution_sidebar  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
