from __future__ import annotations

import importlib
import json
import stat
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
            self.assertEqual(0o700, stat.S_IMODE(audit_path.parent.stat().st_mode))
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

    def test_contract_probe_is_sanitized_bounded_and_cleans_outer_root(self) -> None:
        module = importlib.import_module("gateway_local_plugin_runtime_smoke")
        sentinel = "WAVE4_CONTRACT_PRIVATE_SENTINEL"

        def fake_run(command, *, cwd, env, timeout):
            self.assertLessEqual(timeout, 45)
            audit_path = Path(env["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"])
            self.assertEqual(0o700, stat.S_IMODE(audit_path.parent.stat().st_mode))
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
            outer_root = Path(tmp) / "contract-root"
            runtime_root = Path(tmp) / "runtime-root-must-not-exist"
            with (
                patch.object(module.tempfile, "mkdtemp", return_value=str(outer_root)),
                patch.object(module, "RUNTIME_ROOT", runtime_root),
                patch.object(module, "run_command", side_effect=fake_run),
            ):
                results = module.collect_contract_results(45, 100)

            self.assertFalse(outer_root.exists())
            self.assertFalse(runtime_root.exists())
            self.assertEqual(["direct", "tuple"], [item["mode"] for item in results])
            self.assertTrue(all(item["result"] == "PASS" for item in results))
            self.assertTrue(all(item["artifacts_cleaned"] for item in results))
            retained = json.dumps(results)
            self.assertNotIn(sentinel, retained)
            self.assertNotIn(str(outer_root), retained)
            self.assertNotIn("plugin_spec", retained)
            self.assertNotIn("stdout", retained)
            self.assertNotIn("stderr", retained)

    def test_contract_probe_enforces_shared_aggregate_deadline(self) -> None:
        module = importlib.import_module("gateway_local_plugin_runtime_smoke")
        with tempfile.TemporaryDirectory() as tmp:
            outer_root = Path(tmp) / "contract-timeout"
            with (
                patch.object(module.tempfile, "mkdtemp", return_value=str(outer_root)),
                patch.object(module.time, "monotonic", side_effect=[0.0, 101.0, 101.0]),
                patch.object(module, "collect_direct_result") as direct,
                patch.object(module, "collect_tuple_result") as tuple_probe,
            ):
                results = module.collect_contract_results(45, 100)

            direct.assert_not_called()
            tuple_probe.assert_not_called()
            self.assertFalse(outer_root.exists())
            self.assertEqual(2, len(results))
            self.assertTrue(all(item["result"] == "FAIL" for item in results))
            self.assertTrue(
                all(item["reason"] == "contract_aggregate_timeout" for item in results)
            )

    def test_private_probe_directory_rejects_permissive_parent(self) -> None:
        module = importlib.import_module("gateway_local_plugin_runtime_smoke")
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "permissive"
            work_dir.mkdir(mode=0o755)
            work_dir.chmod(0o755)

            with self.assertRaisesRegex(PermissionError, "owner-only"):
                module.ensure_private_directory(work_dir)

    def test_secret_smoke_hardens_owned_output_and_rejects_symlinks(self) -> None:
        module = importlib.import_module("gateway_secret_redaction_live_smoke")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir(mode=0o755)
            output.chmod(0o755)

            module.prepare_private_output_dir(output)

            self.assertEqual(0o700, stat.S_IMODE(output.stat().st_mode))
            linked = root / "linked"
            linked.symlink_to(output, target_is_directory=True)
            with self.assertRaisesRegex(PermissionError, "must not be a symlink"):
                module.prepare_private_output_dir(linked)


if __name__ == "__main__":
    unittest.main()
