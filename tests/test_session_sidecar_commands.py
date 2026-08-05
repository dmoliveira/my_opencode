from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class SessionSidecarCommandsTest(unittest.TestCase):
    def _module(self, digest_path: Path):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        with patch.dict(
            os.environ,
            {"MY_OPENCODE_DIGEST_PATH": str(digest_path)},
        ):
            return importlib.reload(importlib.import_module("session_command"))

    def _write(self, path: Path, data: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)

    def _run_json(self, callback, arguments: list[str]) -> tuple[int, dict]:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = callback(arguments)
        return code, json.loads(output.getvalue())

    def test_repair_preview_and_apply_preserve_bytes_and_inodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "sessions" / "index.json"
            digest_path = root / "digests" / "last-session.json"
            index_bytes = b"{corrupt-index-private-canary"
            digest_bytes = b'{"digest": "private-canary"}'
            self._write(index_path, index_bytes, 0o644)
            self._write(digest_path, digest_bytes, 0o700)
            identities = {
                "index": (index_path.stat().st_dev, index_path.stat().st_ino),
                "digest": (digest_path.stat().st_dev, digest_path.stat().st_ino),
            }
            module = self._module(digest_path)

            code, preview = self._run_json(
                lambda argv: module._command_repair_sidecars(argv, index_path),
                ["--json"],
            )
            self.assertEqual(1, code)
            self.assertEqual("session_sidecar_repair_required", preview["reason_code"])
            self.assertEqual(0, preview["changed_count"])
            self.assertFalse(preview["partial"])
            self.assertEqual(
                ["repairable", "repairable"],
                [item["state"] for item in preview["sidecars"]],
            )
            self.assertEqual(0o644, index_path.stat().st_mode & 0o777)
            self.assertEqual(0o700, digest_path.stat().st_mode & 0o777)

            code, applied = self._run_json(
                lambda argv: module._command_repair_sidecars(argv, index_path),
                ["--apply", "--json"],
            )
            self.assertEqual(0, code)
            self.assertEqual("PASS", applied["result"])
            self.assertEqual(2, applied["changed_count"])
            self.assertFalse(applied["partial"])
            self.assertEqual(
                ["repaired", "repaired"],
                [item["state"] for item in applied["sidecars"]],
            )
            self.assertEqual(index_bytes, index_path.read_bytes())
            self.assertEqual(digest_bytes, digest_path.read_bytes())
            self.assertEqual(
                identities["index"],
                (index_path.stat().st_dev, index_path.stat().st_ino),
            )
            self.assertEqual(
                identities["digest"],
                (digest_path.stat().st_dev, digest_path.stat().st_ino),
            )

            code, second = self._run_json(
                lambda argv: module._command_repair_sidecars(argv, index_path),
                ["--apply", "--json"],
            )
            self.assertEqual(0, code)
            self.assertEqual(0, second["changed_count"])
            self.assertEqual(
                ["private", "private"],
                [item["state"] for item in second["sidecars"]],
            )

    def test_global_alias_or_blocked_preflight_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            digest_path = root / "digest.json"
            self._write(index_path, b"alias", 0o644)
            os.link(index_path, digest_path)
            module = self._module(digest_path)

            code, payload = self._run_json(
                lambda argv: module._command_repair_sidecars(argv, index_path),
                ["--apply", "--json"],
            )
            self.assertEqual(1, code)
            self.assertEqual("session_sidecar_alias", payload["reason_code"])
            self.assertEqual(0, payload["changed_count"])
            self.assertEqual(0o644, index_path.stat().st_mode & 0o777)
            self.assertEqual(0o644, digest_path.stat().st_mode & 0o777)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            digest_path = root / "digest.json"
            self._write(index_path, b"repairable", 0o644)
            self._write(digest_path, b"blocked", 0o400)
            module = self._module(digest_path)
            code, payload = self._run_json(
                lambda argv: module._command_repair_sidecars(argv, index_path),
                ["--apply", "--json"],
            )
            self.assertEqual(1, code)
            self.assertEqual("session_sidecar_insecure_permissions", payload["reason_code"])
            self.assertEqual(0, payload["changed_count"])
            self.assertEqual(0o644, index_path.stat().st_mode & 0o777)
            self.assertEqual(0o400, digest_path.stat().st_mode & 0o777)

    def test_apply_reports_partial_after_late_race_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            digest_path = root / "digest.json"
            self._write(index_path, b"index", 0o644)
            self._write(digest_path, b"digest", 0o644)
            module = self._module(digest_path)
            real_repair = module.repair_sidecar_mode
            calls = 0

            def fail_second(path: Path, *, target: str, expected_snapshot=None):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise module.SidecarSecurityError(
                        "session_sidecar_snapshot_changed",
                        "injected race",
                        phase="repair",
                    )
                return real_repair(
                    path,
                    target=target,
                    expected_snapshot=expected_snapshot,
                )

            with patch.object(module, "repair_sidecar_mode", side_effect=fail_second):
                code, payload = self._run_json(
                    lambda argv: module._command_repair_sidecars(argv, index_path),
                    ["--apply", "--json"],
                )
            self.assertEqual(1, code)
            self.assertTrue(payload["partial"])
            self.assertEqual(1, payload["changed_count"])
            self.assertEqual(0o600, index_path.stat().st_mode & 0o777)
            self.assertEqual(0o644, digest_path.stat().st_mode & 0o777)

    def test_apply_binds_preflight_to_original_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            digest_path = root / "digest.json"
            replacement = root / "replacement.json"
            self._write(index_path, b"original", 0o644)
            self._write(digest_path, b"digest", 0o600)
            self._write(replacement, b"replacement-victim", 0o644)
            module = self._module(digest_path)
            real_assert = module.assert_distinct_sidecars
            calls = 0

            def swap_before_repair(paths):
                nonlocal calls
                calls += 1
                if calls == 2:
                    os.replace(replacement, index_path)
                return real_assert(paths)

            with patch.object(
                module,
                "assert_distinct_sidecars",
                side_effect=swap_before_repair,
            ):
                code, payload = self._run_json(
                    lambda argv: module._command_repair_sidecars(argv, index_path),
                    ["--apply", "--json"],
                )
            self.assertEqual(1, code)
            self.assertEqual(
                "session_sidecar_snapshot_changed",
                payload["reason_code"],
            )
            self.assertEqual(0, payload["changed_count"])
            self.assertEqual(0o644, index_path.stat().st_mode & 0o777)
            self.assertEqual(b"replacement-victim", index_path.read_bytes())

    def test_doctor_reports_sidecar_findings_without_repairing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            digest_path = root / "digest.json"
            self._write(index_path, b'{"version": 1, "sessions": []}', 0o644)
            self._write(digest_path, b"{}", 0o600)
            module = self._module(digest_path)
            code, payload = self._run_json(
                lambda argv: module._command_doctor(argv, index_path),
                ["--db-path", str(root / "missing.db"), "--json"],
            )
            self.assertEqual(1, code)
            self.assertEqual(
                ["repairable", "private"],
                [item["state"] for item in payload["sidecar_findings"]],
            )
            self.assertEqual("session_index_insecure_permissions", payload["reason_code"])
            self.assertEqual(0o644, index_path.stat().st_mode & 0o777)

    def test_protected_main_allows_explicit_sidecar_preview_and_apply(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        helper = importlib.reload(importlib.import_module("worktree_helper_command"))
        for suffix in ("--json", "--apply --json"):
            with self.subTest(suffix=suffix):
                self.assertTrue(
                    helper.is_direct_allowed_protected_main_command(
                        "python3 scripts/session_command.py "
                        f"repair-sidecars {suffix}"
                    )
                )
                self.assertTrue(
                    helper.is_direct_allowed_protected_main_command(
                        "python3 scripts/session_command.py "
                        f"repair-runtime-permissions {suffix}"
                    )
                )


if __name__ == "__main__":
    unittest.main()
