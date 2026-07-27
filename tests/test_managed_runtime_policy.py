from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from playwright_defaults import PLAYWRIGHT_MCP_COMMAND


class ManagedRuntimePolicyTest(unittest.TestCase):
    def _config(self) -> dict:
        return json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))

    def test_autoupdate_requires_operator_notification(self) -> None:
        self.assertEqual("notify", self._config()["autoupdate"])

    def test_hosted_mcps_remain_disabled_and_playwright_is_exact_pinned(self) -> None:
        mcp = self._config()["mcp"]
        hosted = {"context7", "gh_grep", "exa_search", "github"}
        self.assertEqual(hosted | {"playwright"}, set(mcp))
        for name in hosted:
            with self.subTest(name=name):
                self.assertEqual("remote", mcp[name]["type"])
                self.assertIs(mcp[name]["enabled"], False)

        playwright = mcp["playwright"]
        self.assertEqual("local", playwright["type"])
        self.assertIs(playwright["enabled"], False)
        self.assertEqual(list(PLAYWRIGHT_MCP_COMMAND), playwright["command"])

    def test_managed_plugin_inventory_is_local_gateway_only(self) -> None:
        self.assertEqual(
            ["file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core"],
            self._config()["plugin"],
        )


if __name__ == "__main__":
    unittest.main()
