from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
import builtins
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class SessionSidecarSecurityTest(unittest.TestCase):
    def _module(self):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.reload(importlib.import_module("session_sidecar_security"))

    def test_atomic_publish_and_bounded_read_are_private(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "private" / "digest.json"
            first = module.atomic_write_private_json(
                path,
                {"generation": 1},
                max_bytes=1024,
            )
            self.assertTrue(first.committed)
            self.assertEqual("synced", first.durability)
            self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            first_inode = (path.stat().st_dev, path.stat().st_ino)

            loaded = module.read_private_json(path, max_bytes=1024)
            self.assertEqual({"generation": 1}, loaded.payload)
            self.assertEqual(first_inode, (loaded.snapshot.dev, loaded.snapshot.ino))

            second = module.atomic_write_private_json(
                path,
                {"generation": 2},
                max_bytes=1024,
            )
            self.assertEqual("synced", second.durability)
            self.assertNotEqual(first_inode, (path.stat().st_dev, path.stat().st_ino))
            self.assertEqual(
                {"generation": 2},
                json.loads(path.read_text(encoding="utf-8")),
            )
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_missing_read_and_inspection_never_create_parent(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "digest.json"
            self.assertIsNone(
                module.read_private_bytes(path, max_bytes=1024, allow_missing=True)
            )
            inspection = module.inspect_sidecar(path)
            self.assertEqual("missing", inspection.state)
            self.assertFalse(inspection.exists)
            self.assertFalse(path.parent.exists())

    def test_mode_repair_narrows_without_changing_bytes_or_inode(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "digest.json"
            original = b'{"private": true}'
            path.write_bytes(original)
            path.chmod(0o644)
            before = (path.stat().st_dev, path.stat().st_ino)
            inspection = module.inspect_sidecar(path)
            self.assertEqual("repairable", inspection.state)
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.read_private_json(path, max_bytes=1024)
            self.assertEqual(
                "session_sidecar_insecure_permissions",
                raised.exception.reason_code,
            )

            repaired = module.repair_sidecar_mode(path)
            self.assertEqual("repaired", repaired.state)
            self.assertTrue(repaired.changed)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual(before, (path.stat().st_dev, path.stat().st_ino))
            self.assertEqual(original, path.read_bytes())

            second = module.repair_sidecar_mode(path)
            self.assertEqual("private", second.state)
            self.assertFalse(second.changed)

    def test_mode_repair_never_adds_owner_permissions(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "digest.json"
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o400)
            inspection = module.inspect_sidecar(path)
            self.assertEqual("blocked", inspection.state)
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.repair_sidecar_mode(path)
            self.assertEqual(
                "session_sidecar_insecure_permissions",
                raised.exception.reason_code,
            )
            self.assertEqual(0o400, path.stat().st_mode & 0o777)

    @unittest.skipUnless(
        hasattr(os, "symlink") and hasattr(os, "link") and hasattr(os, "mkfifo"),
        "required filesystem primitives unsupported",
    )
    def test_unsafe_target_types_and_links_fail_without_victim_mutation(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root / "victim.json"
            victim.write_text("{}", encoding="utf-8")
            victim.chmod(0o600)
            original = victim.read_bytes()

            symlink = root / "symlink.json"
            symlink.symlink_to(victim)
            hardlink = root / "hardlink.json"
            os.link(victim, hardlink)
            fifo = root / "digest.fifo"
            os.mkfifo(fifo)
            directory = root / "directory.json"
            directory.mkdir()

            for path in (symlink, hardlink, fifo, directory):
                with self.subTest(path=path.name):
                    with self.assertRaises(module.SidecarSecurityError) as raised:
                        module.read_private_bytes(path, max_bytes=1024)
                    self.assertEqual(
                        "session_sidecar_unsafe_target",
                        raised.exception.reason_code,
                    )
            self.assertEqual(original, victim.read_bytes())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_symlinked_parent_is_rejected_without_creation(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real"
            real_parent.mkdir(mode=0o700)
            alias_parent = root / "alias"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            target = alias_parent / "digest.json"
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.atomic_write_private_json(target, {"value": 1}, max_bytes=1024)
            self.assertIn(
                raised.exception.reason_code,
                {"session_sidecar_unsafe_ancestor", "session_sidecar_unsafe_parent"},
            )
            self.assertFalse((real_parent / "digest.json").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_intermediate_user_symlink_is_rejected(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real"
            nested = real_parent / "nested"
            nested.mkdir(parents=True, mode=0o700)
            alias = root / "alias"
            alias.symlink_to(real_parent, target_is_directory=True)
            target = alias / "nested" / "digest.json"
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.atomic_write_private_json(target, {"value": 1}, max_bytes=1024)
            self.assertEqual(
                "session_sidecar_unsafe_ancestor",
                raised.exception.reason_code,
            )
            self.assertFalse((nested / "digest.json").exists())

    def test_oversized_and_malformed_json_have_stable_errors(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oversized = root / "oversized.json"
            oversized.write_bytes(b"x" * 17)
            oversized.chmod(0o600)
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.read_private_bytes(oversized, max_bytes=16)
            self.assertEqual("session_sidecar_too_large", raised.exception.reason_code)

            malformed = root / "malformed.json"
            malformed.write_bytes(b"{bad")
            malformed.chmod(0o600)
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.read_private_json(malformed, max_bytes=1024)
            self.assertEqual(
                "session_sidecar_malformed_json",
                raised.exception.reason_code,
            )

            invalid_root = root / "root.json"
            invalid_root.write_text("[]", encoding="utf-8")
            invalid_root.chmod(0o600)
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.read_private_json(invalid_root, max_bytes=1024)
            self.assertEqual(
                "session_sidecar_invalid_root",
                raised.exception.reason_code,
            )

    def test_pre_replace_failure_preserves_existing_target(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "digest.json"
            path.write_text('{"generation": 1}', encoding="utf-8")
            path.chmod(0o600)
            original = path.read_bytes()
            identity = (path.stat().st_dev, path.stat().st_ino)
            with patch.object(
                module.os,
                "replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    module.atomic_write_private_json(
                        path,
                        {"generation": 2},
                        max_bytes=1024,
                    )
            self.assertFalse(raised.exception.committed)
            self.assertEqual("not_committed", raised.exception.durability)
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(identity, (path.stat().st_dev, path.stat().st_ino))

    def test_caller_snapshot_change_is_rejected_before_publication(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "digest.json"
            path.write_text('{"generation": 1}', encoding="utf-8")
            path.chmod(0o600)
            loaded = module.read_private_json(path, max_bytes=1024)
            path.write_text('{"generation": 2}', encoding="utf-8")
            path.chmod(0o600)
            changed = path.read_bytes()
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.atomic_write_private_json(
                    path,
                    {"generation": 3},
                    max_bytes=1024,
                    expected_snapshot=loaded.snapshot,
                )
            self.assertEqual(
                "session_sidecar_snapshot_changed",
                raised.exception.reason_code,
            )
            self.assertFalse(raised.exception.committed)
            self.assertEqual(changed, path.read_bytes())

    def test_post_replace_failure_reports_uncertain_commit(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "digest.json"
            path.write_text('{"generation": 1}', encoding="utf-8")
            path.chmod(0o600)
            with patch.object(
                module,
                "_fsync_directory",
                side_effect=OSError("injected parent fsync failure"),
            ):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    module.atomic_write_private_json(
                        path,
                        {"generation": 2},
                        max_bytes=1024,
                    )
            self.assertTrue(raised.exception.committed)
            self.assertEqual("uncertain", raised.exception.durability)
            self.assertEqual(
                {"generation": 2},
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_replace_then_raise_reports_committed_uncertain(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "digest.json"
            path.write_text('{"generation": 1}', encoding="utf-8")
            path.chmod(0o600)
            real_replace = module.os.replace

            def commit_then_raise(*args, **kwargs):
                real_replace(*args, **kwargs)
                raise OSError("injected post-rename failure")

            with patch.object(module.os, "replace", side_effect=commit_then_raise):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    module.atomic_write_private_json(
                        path,
                        {"generation": 2},
                        max_bytes=1024,
                    )
            self.assertTrue(raised.exception.committed)
            self.assertEqual("uncertain", raised.exception.durability)
            self.assertEqual(
                "session_sidecar_durability_uncertain",
                raised.exception.reason_code,
            )
            self.assertEqual(
                {"generation": 2},
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_replace_observer_failure_is_conservatively_committed(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "digest.json"
            path.write_text('{"generation": 1}', encoding="utf-8")
            path.chmod(0o600)
            real_replace = module.os.replace
            real_target_stat = module._raw_target_stat
            replaced = False

            def commit_then_raise(*args, **kwargs):
                nonlocal replaced
                real_replace(*args, **kwargs)
                replaced = True
                raise OSError("injected post-rename failure")

            def fail_observer(authority):
                if replaced:
                    raise module.SidecarSecurityError(
                        "session_sidecar_unsafe_target",
                        "injected observer failure",
                        phase="target",
                    )
                return real_target_stat(authority)

            with patch.object(
                module.os,
                "replace",
                side_effect=commit_then_raise,
            ), patch.object(
                module,
                "_raw_target_stat",
                side_effect=fail_observer,
            ):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    module.atomic_write_private_json(
                        path,
                        {"generation": 2},
                        max_bytes=1024,
                    )
            self.assertTrue(raised.exception.committed)
            self.assertEqual("uncertain", raised.exception.durability)
            self.assertEqual(
                "session_sidecar_durability_uncertain",
                raised.exception.reason_code,
            )
            self.assertEqual(
                {"generation": 2},
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_repair_expected_snapshot_rejects_same_mode_inode_swap(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "digest.json"
            replacement = root / "replacement.json"
            path.write_text('{"source": true}', encoding="utf-8")
            path.chmod(0o644)
            observed = module.inspect_sidecar(path)
            replacement.write_text('{"victim": true}', encoding="utf-8")
            replacement.chmod(0o644)
            os.replace(replacement, path)
            victim_identity = (path.stat().st_dev, path.stat().st_ino)

            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.repair_sidecar_mode(
                    path,
                    expected_snapshot=observed.snapshot,
                )
            self.assertEqual(
                "session_sidecar_snapshot_changed",
                raised.exception.reason_code,
            )
            self.assertEqual(0o644, path.stat().st_mode & 0o777)
            self.assertEqual(victim_identity, (path.stat().st_dev, path.stat().st_ino))
            self.assertEqual({"victim": True}, json.loads(path.read_text()))

    def test_alias_detection_covers_existing_and_missing_targets(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text("{}", encoding="utf-8")
            first.chmod(0o600)
            os.link(first, second)
            with self.assertRaises(module.SidecarSecurityError) as raised:
                module.assert_distinct_sidecars({"digest": first, "index": second})
            self.assertEqual("session_sidecar_alias", raised.exception.reason_code)

            missing = root / "missing.json"
            with self.assertRaises(module.SidecarSecurityError):
                module.assert_distinct_sidecars({"digest": missing, "index": missing})

            with patch.object(module.sys, "platform", "darwin"):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    module.assert_distinct_sidecars(
                        {
                            "digest": root / "Case.json",
                            "index": root / "case.json",
                        }
                    )
            self.assertEqual("session_sidecar_alias", raised.exception.reason_code)

    def test_legacy_lock_is_narrowed_without_replacing_inode(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "index.json.lock"
            lock_path.write_text("0", encoding="utf-8")
            lock_path.chmod(0o644)
            identity = (lock_path.stat().st_dev, lock_path.stat().st_ino)
            with module.secure_sidecar_lock(lock_path, timeout_seconds=0.5):
                self.assertEqual(0o600, lock_path.stat().st_mode & 0o777)
                self.assertEqual(identity, (lock_path.stat().st_dev, lock_path.stat().st_ino))

    def test_lock_timeout_is_bounded(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "index.json.lock"
            with module.secure_sidecar_lock(lock_path, timeout_seconds=0.5):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    with module.secure_sidecar_lock(lock_path, timeout_seconds=0.05):
                        pass
            self.assertEqual("session_sidecar_lock_timeout", raised.exception.reason_code)

    def test_unsupported_platform_fails_before_creating_parent(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "digest.json"
            with patch.object(module.sys, "platform", "win32"):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    module.atomic_write_private_json(path, {}, max_bytes=1024)
            self.assertEqual(
                "session_sidecar_unsupported_platform",
                raised.exception.reason_code,
            )
            self.assertFalse(path.parent.exists())

    def test_missing_flock_capability_fails_before_creating_lock_parent(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "digest.json.lock"
            real_import = builtins.__import__

            def import_without_fcntl(name, *args, **kwargs):
                if name == "fcntl":
                    raise ImportError("injected missing fcntl")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=import_without_fcntl):
                with self.assertRaises(module.SidecarSecurityError) as raised:
                    with module.secure_sidecar_lock(path):
                        pass
            self.assertEqual(
                "session_sidecar_unsupported_platform",
                raised.exception.reason_code,
            )
            self.assertFalse(path.parent.exists())


if __name__ == "__main__":
    unittest.main()
