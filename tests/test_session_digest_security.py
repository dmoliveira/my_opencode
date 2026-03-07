from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class SessionDigestSecurityTest(unittest.TestCase):
    def test_post_session_command_ignores_project_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            home = root / "home"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".opencode").mkdir(parents=True, exist_ok=True)
            (home / ".config" / "opencode").mkdir(parents=True, exist_ok=True)

            project_cfg = {
                "post_session": {
                    "enabled": True,
                    "command": "echo PROJECT_UNTRUSTED",
                    "timeout_ms": 1234,
                    "run_on": ["exit"],
                }
            }
            user_cfg = {
                "post_session": {
                    "enabled": True,
                    "command": "echo USER_TRUSTED",
                    "timeout_ms": 5678,
                    "run_on": ["manual"],
                }
            }

            (workspace / ".opencode" / "my_opencode.jsonc").write_text(
                json.dumps(project_cfg),
                encoding="utf-8",
            )
            (home / ".config" / "opencode" / "my_opencode.json").write_text(
                json.dumps(user_cfg),
                encoding="utf-8",
            )

            old_home = os.environ.get("HOME")
            old_cwd = Path.cwd()
            old_session_cfg = os.environ.pop("MY_OPENCODE_SESSION_CONFIG_PATH", None)
            try:
                os.environ["HOME"] = str(home)
                os.chdir(workspace)
                if str(SCRIPTS_DIR) not in sys.path:
                    sys.path.insert(0, str(SCRIPTS_DIR))

                module = importlib.import_module("session_digest")
                module = importlib.reload(module)
                config = module.load_post_session_config()

                self.assertTrue(config.get("enabled"))
                self.assertEqual("echo USER_TRUSTED", config.get("command"))
                self.assertEqual(5678, config.get("timeout_ms"))
                self.assertEqual(["manual"], config.get("run_on"))
            finally:
                os.chdir(old_cwd)
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_session_cfg is not None:
                    os.environ["MY_OPENCODE_SESSION_CONFIG_PATH"] = old_session_cfg


if __name__ == "__main__":
    unittest.main()
