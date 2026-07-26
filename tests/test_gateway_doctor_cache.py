from __future__ import annotations

import importlib
import json
import os
import stat
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
                fresh = module.run_local_plugin_runtime_smoke(force_fresh=True)
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
        doctor.assert_called_once_with(True, fresh=True)


if __name__ == "__main__":
    unittest.main()
