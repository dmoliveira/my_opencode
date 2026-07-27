from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class GatewayMistakeLedgerTest(unittest.TestCase):
    def _module(self):
        return importlib.reload(importlib.import_module("gateway_command"))

    def _ledger_path(self, root: Path) -> Path:
        directory = root / ".opencode"
        directory.mkdir(mode=0o755)
        return directory / "mistake-ledger.jsonl"

    def test_fixed_path_ignores_legacy_environment_override(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MY_OPENCODE_MISTAKE_LEDGER_PATH": "/tmp/private-ledger-canary"},
        ):
            root = Path(tmp)
            self.assertEqual(
                root / ".opencode" / "mistake-ledger.jsonl",
                module.gateway_mistake_ledger_path(root),
            )

    def test_absent_summary_never_discloses_host_path(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            summary = module.gateway_mistake_ledger_summary(Path(tmp))
        self.assertEqual(
            {
                "exists": False,
                "window_entry_count": 0,
                "window_category_counts": {},
                "invalid_lines": 0,
                "truncated": False,
                "last_entry": None,
            },
            summary,
        )
        self.assertNotIn("path", summary)

    def test_bounded_tail_suppresses_legacy_private_fields(self) -> None:
        module = self._module()
        canary = "WAVE7_LEDGER_PRIVATE_CANARY"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self._ledger_path(root)
            rows = []
            for index in range(620):
                rows.append(
                    json.dumps(
                        {
                            "ts": f"2026-07-27T00:{index % 60:02d}:00Z",
                            "category": "completion_without_validation",
                            "summary": f"{canary}-{index}-" + ("x" * 480),
                            "sessionId": f"{canary}-session-{index}",
                            "tool": f"{canary}-tool-{index}",
                        }
                    )
                )
            rows.append("not-json")
            rows.append(
                json.dumps(
                    {
                        "ts": canary,
                        "category": canary,
                        "summary": canary,
                        "sessionId": canary,
                        "tool": canary,
                    }
                )
            )
            ledger_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            ledger_path.chmod(0o600)

            summary = module.gateway_mistake_ledger_summary(root)

        rendered = json.dumps(summary, sort_keys=True)
        self.assertNotIn(canary, rendered)
        self.assertNotIn("path", summary)
        self.assertTrue(summary["truncated"])
        self.assertLessEqual(summary["window_entry_count"], 500)
        self.assertEqual(1, summary["invalid_lines"])
        self.assertEqual({"ts": None, "category": "unknown"}, summary["last_entry"])
        self.assertNotIn("total_entries", summary)
        self.assertNotIn("recent_categories", summary)

    def test_final_symlink_is_refused_and_victim_is_unchanged(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self._ledger_path(root)
            victim_path = root / "victim.txt"
            victim_path.write_text("victim-sentinel", encoding="utf-8")
            ledger_path.symlink_to(victim_path)

            summary = module.gateway_mistake_ledger_summary(root)

            self.assertEqual("mistake_ledger_unsafe_file", summary["error_code"])
            self.assertEqual("victim-sentinel", victim_path.read_text(encoding="utf-8"))

    def test_parent_symlink_is_refused(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as target:
            root = Path(tmp)
            target_path = Path(target)
            victim = target_path / "mistake-ledger.jsonl"
            victim.write_text("victim-sentinel", encoding="utf-8")
            victim.chmod(0o600)
            (root / ".opencode").symlink_to(target_path, target_is_directory=True)

            summary = module.gateway_mistake_ledger_summary(root)

            self.assertEqual("mistake_ledger_unsafe_directory", summary["error_code"])
            self.assertEqual("victim-sentinel", victim.read_text(encoding="utf-8"))

    @unittest.skipUnless(hasattr(os, "link"), "hardlinks unavailable")
    def test_hardlink_is_refused_and_victim_is_unchanged(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self._ledger_path(root)
            victim_path = root / "victim.txt"
            victim_path.write_text("victim-sentinel", encoding="utf-8")
            victim_path.chmod(0o600)
            os.link(victim_path, ledger_path)

            summary = module.gateway_mistake_ledger_summary(root)

            self.assertEqual("mistake_ledger_unsafe_file", summary["error_code"])
            self.assertEqual("victim-sentinel", victim_path.read_text(encoding="utf-8"))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_fifo_is_refused(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self._ledger_path(root)
            os.mkfifo(ledger_path, 0o600)

            summary = module.gateway_mistake_ledger_summary(root)

            self.assertEqual("mistake_ledger_unsafe_file", summary["error_code"])

    def test_unsafe_file_and_directory_modes_are_refused(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self._ledger_path(root)
            ledger_path.write_text("{}\n", encoding="utf-8")
            ledger_path.chmod(0o644)
            summary = module.gateway_mistake_ledger_summary(root)
            self.assertEqual("mistake_ledger_unsafe_permissions", summary["error_code"])

            ledger_path.chmod(0o600)
            ledger_path.parent.chmod(0o770)
            summary = module.gateway_mistake_ledger_summary(root)
            self.assertEqual("mistake_ledger_unsafe_directory", summary["error_code"])

    @unittest.skipUnless(hasattr(os, "getuid"), "UID ownership unavailable")
    def test_ownership_mismatch_is_refused(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = self._ledger_path(root)
            ledger_path.write_text("{}\n", encoding="utf-8")
            ledger_path.chmod(0o600)
            with patch.object(module.os, "getuid", return_value=os.getuid() + 1):
                summary = module.gateway_mistake_ledger_summary(root)
            self.assertEqual("mistake_ledger_ownership_mismatch", summary["error_code"])


if __name__ == "__main__":
    unittest.main()
