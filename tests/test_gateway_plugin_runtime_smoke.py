from __future__ import annotations

import importlib
import json
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


class GatewayPluginRuntimeSmokeTest(unittest.TestCase):
    def test_tuple_probe_retains_only_sanitized_evidence_and_cleans_files(self) -> None:
        module = importlib.import_module("gateway_local_plugin_runtime_smoke")
        sentinel = "WAVE3_PRIVATE_PLUGIN_OPTION"

        def fake_run(command, *, cwd, env, timeout):
            audit_path = Path(env["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"])
            audit_path.write_text(
                json.dumps(
                    {
                        "reason_code": "gateway_runtime_bootstrap",
                        "hooks_enabled": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, sentinel, "")

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "tuple-probe"
            with patch.object(module, "run_command", side_effect=fake_run):
                result = module.collect_tuple_result(work_dir, 10)
            self.assertFalse(work_dir.exists())
            self.assertEqual("PASS", result["result"])
            self.assertEqual(0, result["shim_count"])
            self.assertTrue(result["raw_option_echo_seen"])
            self.assertTrue(result["audit_sanitized"])
            retained = json.dumps(result)
            self.assertNotIn(sentinel, retained)
            self.assertNotIn(str(work_dir), retained)


if __name__ == "__main__":
    unittest.main()
