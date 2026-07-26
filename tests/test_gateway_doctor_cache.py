from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(SCRIPTS_DIR))


class GatewayDoctorCacheTest(unittest.TestCase):
    def _module(self):
        return importlib.import_module("gateway_command")

    @staticmethod
    def _live_pass() -> dict:
        return {
            "result": "PASS",
            "reason": "local_plugin_runtime_loader_ok",
            "path": "/temporary/smoke.py",
            "exit": 0,
            "results": [
                {
                    "mode": "direct",
                    "result": "PASS",
                    "run_exit": 0,
                    "audit_exists": True,
                    "bootstrap_seen": True,
                    "plugin_install_failed": False,
                    "plugin_resolve_failed": False,
                    "work_dir": "/temporary/private-work",
                    "server_log": "/temporary/private-server.log",
                }
            ],
        }

    @classmethod
    def _contract_pass(cls) -> dict:
        direct = cls._live_pass()["results"][0]
        return {
            "result": "PASS",
            "reason": "local_plugin_runtime_loader_ok",
            "exit": 0,
            "results": [direct, {**direct, "mode": "tuple"}],
        }

    def test_success_cache_is_owner_only_sanitized_and_reused(self) -> None:
        module = self._module()
        now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"HOME": tmp, "XDG_CACHE_HOME": str(Path(tmp) / "cache")},
            clear=False,
        ), patch.object(module, "_gateway_smoke_fingerprint", return_value="f" * 64), patch.object(
            module, "_gateway_smoke_cache_now", return_value=now
        ), patch.object(
            module, "_run_local_plugin_runtime_smoke_live", return_value=self._live_pass()
        ) as live:
            first = module.run_local_plugin_runtime_smoke()
            second = module.run_local_plugin_runtime_smoke()
            cache_path = module.gateway_doctor_smoke_cache_path()
            cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))

            self.assertFalse(first["cached"])
            self.assertTrue(first["cache_stored"])
            self.assertTrue(second["cached"])
            self.assertEqual(1, live.call_count)
            self.assertEqual(0o600, stat.S_IMODE(cache_path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(cache_path.parent.stat().st_mode))
            self.assertEqual(
                {"schema", "fingerprint", "checked_at", "result"},
                set(cached_payload),
            )
            retained = cache_path.read_text(encoding="utf-8")
            self.assertNotIn("work_dir", retained)
            self.assertNotIn("server_log", retained)
            self.assertNotIn("/temporary/", retained)
            self.assertNotIn("work_dir", json.dumps(second))

    def test_corrupt_insecure_expired_and_future_cache_entries_rerun_live(self) -> None:
        module = self._module()
        base = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"HOME": tmp, "XDG_CACHE_HOME": str(Path(tmp) / "cache")},
            clear=False,
        ), patch.object(module, "_gateway_smoke_fingerprint", return_value="a" * 64), patch.object(
            module, "_run_local_plugin_runtime_smoke_live", return_value=self._live_pass()
        ) as live:
            with patch.object(module, "_gateway_smoke_cache_now", return_value=base):
                module.run_local_plugin_runtime_smoke()
            cache_path = module.gateway_doctor_smoke_cache_path()

            cache_path.write_text("{broken", encoding="utf-8")
            cache_path.chmod(0o600)
            with patch.object(module, "_gateway_smoke_cache_now", return_value=base):
                self.assertFalse(module.run_local_plugin_runtime_smoke()["cached"])

            cache_path.chmod(0o644)
            with patch.object(module, "_gateway_smoke_cache_now", return_value=base):
                self.assertFalse(module.run_local_plugin_runtime_smoke()["cached"])
            self.assertEqual(0o600, stat.S_IMODE(cache_path.stat().st_mode))

            cache_path.parent.chmod(0o755)
            with patch.object(module, "_gateway_smoke_cache_now", return_value=base):
                self.assertFalse(module.run_local_plugin_runtime_smoke()["cached"])
            self.assertEqual(0o700, stat.S_IMODE(cache_path.parent.stat().st_mode))

            with patch.object(
                module, "_gateway_smoke_cache_now", return_value=base + timedelta(seconds=900)
            ):
                self.assertFalse(module.run_local_plugin_runtime_smoke()["cached"])

            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["checked_at"] = (base + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            cache_path.chmod(0o600)
            with patch.object(module, "_gateway_smoke_cache_now", return_value=base):
                self.assertFalse(module.run_local_plugin_runtime_smoke()["cached"])
            self.assertEqual(6, live.call_count)

    def test_fingerprint_mismatch_and_fresh_failure_invalidate_prior_pass(self) -> None:
        module = self._module()
        now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"HOME": tmp, "XDG_CACHE_HOME": str(Path(tmp) / "cache")},
            clear=False,
        ), patch.object(module, "_gateway_smoke_cache_now", return_value=now):
            with patch.object(module, "_gateway_smoke_fingerprint", return_value="a" * 64), patch.object(
                module, "_run_local_plugin_runtime_smoke_live", return_value=self._live_pass()
            ) as live:
                module.run_local_plugin_runtime_smoke()
                self.assertEqual(1, live.call_count)
            cache_path = module.gateway_doctor_smoke_cache_path()
            self.assertTrue(cache_path.exists())

            with patch.object(module, "_gateway_smoke_fingerprint", return_value="b" * 64), patch.object(
                module, "_run_local_plugin_runtime_smoke_live", return_value=self._live_pass()
            ) as live:
                mismatch = module.run_local_plugin_runtime_smoke()
                self.assertFalse(mismatch["cached"])
                self.assertEqual(1, live.call_count)

            failure = {"result": "FAIL", "reason": "smoke_failed", "results": []}
            with patch.object(module, "_gateway_smoke_fingerprint", return_value="b" * 64), patch.object(
                module, "_run_local_plugin_runtime_smoke_live", return_value=failure
            ) as live:
                fresh = module.run_local_plugin_runtime_smoke(
                    cache_policy="refresh"
                )
                self.assertEqual("FAIL", fresh["result"])
                self.assertFalse(fresh["cached"])
                self.assertEqual(1, live.call_count)
            self.assertFalse(cache_path.exists())

    def test_symlink_cache_is_neither_read_written_nor_removed(self) -> None:
        module = self._module()
        now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"HOME": tmp, "XDG_CACHE_HOME": str(Path(tmp) / "cache")},
            clear=False,
        ), patch.object(module, "_gateway_smoke_cache_now", return_value=now), patch.object(
            module, "_gateway_smoke_fingerprint", return_value="c" * 64
        ), patch.object(
            module, "_run_local_plugin_runtime_smoke_live", return_value=self._live_pass()
        ):
            cache_path = module.gateway_doctor_smoke_cache_path()
            cache_path.parent.mkdir(parents=True, mode=0o700)
            victim = Path(tmp) / "victim.json"
            victim.write_text("do-not-touch", encoding="utf-8")
            cache_path.symlink_to(victim)

            result = module.run_local_plugin_runtime_smoke()
            self.assertFalse(result["cached"])
            self.assertFalse(result["cache_stored"])
            self.assertTrue(cache_path.is_symlink())
            self.assertEqual("do-not-touch", victim.read_text(encoding="utf-8"))

    def test_cli_forwards_fresh_to_doctor(self) -> None:
        module = self._module()
        with patch.object(module, "command_doctor", return_value=7) as doctor:
            self.assertEqual(7, module.main(["doctor", "--fresh", "--json"]))
        doctor.assert_called_once_with(True, fresh=True, deep=False)

    def test_deep_cache_policy_never_reads_writes_or_invalidates_direct_cache(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"HOME": tmp, "XDG_CACHE_HOME": str(Path(tmp) / "cache")},
            clear=False,
        ):
            cache_path = module.gateway_doctor_smoke_cache_path()
            cache_path.parent.mkdir(parents=True, mode=0o700)
            cache_path.write_text("direct-cache-sentinel", encoding="utf-8")
            cache_path.chmod(0o600)
            with patch.object(
                module,
                "_run_local_plugin_runtime_smoke_live",
                return_value=self._contract_pass(),
            ) as live:
                result = module.run_local_plugin_runtime_smoke(
                    cache_policy="none", mode="contract"
                )
            self.assertEqual("PASS", result["result"])
            self.assertEqual("none", result["cache_policy"])
            self.assertEqual("direct-cache-sentinel", cache_path.read_text())
            live.assert_called_once_with(mode="contract")

            cache_path.unlink()
            with patch.object(
                module,
                "_run_local_plugin_runtime_smoke_live",
                return_value={"result": "FAIL", "reason": "probe_failed"},
            ):
                result = module.run_local_plugin_runtime_smoke(
                    cache_policy="none", mode="contract"
                )
            self.assertEqual("FAIL", result["result"])
            self.assertFalse(cache_path.exists())

    def test_direct_cache_rejects_contract_or_duplicate_results(self) -> None:
        module = self._module()
        self.assertIsNone(module._cacheable_smoke_summary(self._contract_pass()))
        duplicate = self._live_pass()
        duplicate["results"].append(dict(duplicate["results"][0]))
        self.assertIsNone(module._cacheable_smoke_summary(duplicate))

    def test_fingerprint_includes_bundled_gateway_default(self) -> None:
        module = self._module()
        expected = (
            module.REPO_ROOT
            / "plugin"
            / "gateway-core"
            / "config"
            / "default-gateway-core.config.json"
        )
        self.assertIn(expected, module._gateway_smoke_fingerprint_files())

    def test_live_contract_requires_exact_modes_and_projects_failure(self) -> None:
        module = self._module()
        canary = "WAVE4_RAW_SMOKE_CANARY"
        direct = self._live_pass()["results"][0]
        completed = subprocess.CompletedProcess(
            ["gateway-smoke"],
            0,
            json.dumps(
                {
                    "reason": canary,
                    "results": [
                        {
                            **direct,
                            "stdout": canary,
                            "work_dir": f"/tmp/{canary}",
                        }
                    ]
                }
            ),
            canary,
        )
        with patch.object(module.subprocess, "run", return_value=completed) as run:
            result = module._run_local_plugin_runtime_smoke_live(
                mode="contract"
            )

        self.assertEqual("FAIL", result["result"])
        self.assertEqual(["direct"], [item["mode"] for item in result["results"]])
        self.assertNotIn(canary, json.dumps(result))
        command = run.call_args.args[0]
        self.assertIn("contract", command)
        self.assertIn("100", command)

    def test_cli_forwards_deep_and_rejects_deep_fresh(self) -> None:
        module = self._module()
        with patch.object(module, "command_doctor", return_value=9) as doctor:
            self.assertEqual(9, module.main(["doctor", "--deep", "--json"]))
        doctor.assert_called_once_with(True, fresh=False, deep=True)

        with patch.object(module, "command_doctor") as doctor:
            self.assertEqual(2, module.main(["doctor", "--deep", "--fresh"]))
        doctor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
