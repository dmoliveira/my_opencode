from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import session_sidecar_security as sidecar


def metadata_from_current_file(snapshot: sidecar.SidecarSnapshot, path: Path) -> sidecar.SidecarSnapshot:
    current = path.stat()
    return replace(
        snapshot,
        dev=current.st_dev,
        ino=current.st_ino,
        mode=stat.S_IMODE(current.st_mode),
        uid=current.st_uid,
        nlink=current.st_nlink,
        size=current.st_size,
        mtime_ns=current.st_mtime_ns,
        ctime_ns=current.st_ctime_ns,
    )


class SidecarContentFencingTest(unittest.TestCase):
    def test_caller_snapshot_rejects_changed_bytes_even_when_metadata_matches(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-collision-") as raw:
            path = Path(raw) / "digest.json"
            path.write_bytes(b'{"generation": 1}')
            path.chmod(0o600)
            loaded = sidecar.read_private_json(path, max_bytes=1024)
            assert loaded is not None
            path.write_bytes(b'{"generation": 2}')
            path.chmod(0o600)
            changed = path.read_bytes()
            simulated_collision = metadata_from_current_file(loaded.snapshot, path)
            self.assertTrue(sidecar._same_snapshot(path.stat(), simulated_collision))

            with self.assertRaises(sidecar.SidecarSecurityError) as caught:
                sidecar.atomic_write_private_json(
                    path, {"generation": 3}, max_bytes=1024,
                    expected_snapshot=simulated_collision,
                )
            self.assertEqual("session_sidecar_snapshot_changed", caught.exception.reason_code)
            self.assertFalse(caught.exception.committed)
            self.assertEqual(changed, path.read_bytes())
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_publication_snapshot_binds_the_published_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-publication-") as raw:
            path = Path(raw) / "digest.json"
            published = sidecar.atomic_write_private_json(path, {"generation": 1}, max_bytes=1024)
            altered = path.read_bytes().replace(b'"generation": 1', b'"generation": 2')
            path.write_bytes(altered)
            path.chmod(0o600)
            simulated_collision = metadata_from_current_file(published.snapshot, path)
            self.assertTrue(sidecar._same_snapshot(path.stat(), simulated_collision))

            with self.assertRaises(sidecar.SidecarSecurityError) as caught:
                sidecar.atomic_write_private_json(
                    path, {"generation": 3}, max_bytes=1024,
                    expected_snapshot=simulated_collision,
                )
            self.assertEqual("session_sidecar_snapshot_changed", caught.exception.reason_code)
            self.assertFalse(caught.exception.committed)
            self.assertEqual(altered, path.read_bytes())

    def test_change_after_initial_observation_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-inflight-") as raw:
            path = Path(raw) / "digest.json"
            path.write_bytes(b'{"generation": 1}')
            path.chmod(0o600)
            original_write = sidecar._write_all
            original_snapshot = sidecar._snapshot
            changed = b'{"generation": 2}'

            def alter_source(descriptor: int, data: bytes) -> None:
                original_write(descriptor, data)
                path.write_bytes(changed)
                path.chmod(0o600)

            def freeze_timestamps(normalized: Path, metadata: os.stat_result) -> sidecar.SidecarSnapshot:
                snapshot = original_snapshot(normalized, metadata)
                return replace(snapshot, mtime_ns=0, ctime_ns=0)

            with (
                patch.object(sidecar, "_write_all", side_effect=alter_source),
                patch.object(sidecar, "_same_snapshot", return_value=True),
                patch.object(sidecar, "_snapshot", side_effect=freeze_timestamps),
                self.assertRaises(sidecar.SidecarSecurityError) as caught,
            ):
                sidecar.atomic_write_private_json(path, {"generation": 3}, max_bytes=1024)
            self.assertEqual("session_sidecar_snapshot_changed", caught.exception.reason_code)
            self.assertFalse(caught.exception.committed)
            self.assertEqual(changed, path.read_bytes())
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_changed_staged_content_is_not_published(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-stage-race-") as raw:
            path = Path(raw) / "digest.json"
            original = b'{"generation": 1}'
            path.write_bytes(original)
            path.chmod(0o600)
            original_write = sidecar._write_all

            def alter_stage(descriptor: int, data: bytes) -> None:
                original_write(descriptor, data)
                os.lseek(descriptor, 0, os.SEEK_SET)
                replacement = data.replace(b'"generation": 3', b'"generation": 4')
                self.assertNotEqual(data, replacement)
                self.assertEqual(len(data), len(replacement))
                os.write(descriptor, replacement)

            with (
                patch.object(sidecar, "_write_all", side_effect=alter_stage),
                self.assertRaises(sidecar.SidecarSecurityError) as caught,
            ):
                sidecar.atomic_write_private_json(path, {"generation": 3}, max_bytes=1024)
            self.assertEqual("session_sidecar_snapshot_changed", caught.exception.reason_code)
            self.assertFalse(caught.exception.committed)
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_changed_content_after_replacement_reports_uncertain_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-post-race-") as raw:
            path = Path(raw) / "digest.json"
            path.write_bytes(b'{"generation": 1}')
            path.chmod(0o600)
            original_signature = sidecar._stat_signature
            changed: list[bytes] = []

            def alter_after_replace(descriptor: int) -> None:
                data = path.read_bytes()
                replacement = data.replace(b'"generation": 3', b'"generation": 4')
                self.assertNotEqual(data, replacement)
                self.assertEqual(len(data), len(replacement))
                path.write_bytes(replacement)
                path.chmod(0o600)
                changed.append(replacement)

            def freeze_timestamps(metadata: os.stat_result) -> tuple[int, ...]:
                return (*original_signature(metadata)[:-2], 0, 0)

            with (
                patch.object(sidecar, "_fsync_directory", side_effect=alter_after_replace),
                patch.object(sidecar, "_stat_signature", side_effect=freeze_timestamps),
                self.assertRaises(sidecar.SidecarSecurityError) as caught,
            ):
                sidecar.atomic_write_private_json(path, {"generation": 3}, max_bytes=1024)
            self.assertEqual("session_sidecar_durability_uncertain", caught.exception.reason_code)
            self.assertTrue(caught.exception.committed)
            self.assertEqual("uncertain", caught.exception.durability)
            self.assertEqual(changed[0], path.read_bytes())

    def test_metadata_only_snapshot_is_not_a_content_precondition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-metadata-only-") as raw:
            path = Path(raw) / "digest.json"
            path.write_bytes(b'{"generation": 1}')
            path.chmod(0o600)
            inspection = sidecar.inspect_sidecar(path)
            assert inspection.snapshot is not None
            original = path.read_bytes()
            with self.assertRaises(sidecar.SidecarSecurityError) as caught:
                sidecar.atomic_write_private_json(
                    path, {"generation": 2}, max_bytes=1024,
                    expected_snapshot=inspection.snapshot,
                )
            self.assertEqual("session_sidecar_snapshot_unverified", caught.exception.reason_code)
            self.assertFalse(caught.exception.committed)
            self.assertEqual(original, path.read_bytes())

    def test_oversized_existing_source_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-oversized-") as raw:
            path = Path(raw) / "digest.json"
            original = b"x" * 1025
            path.write_bytes(original)
            path.chmod(0o600)
            with self.assertRaises(sidecar.SidecarSecurityError) as caught:
                sidecar.atomic_write_private_json(path, {}, max_bytes=1024)
            self.assertEqual("session_sidecar_too_large", caught.exception.reason_code)
            self.assertFalse(caught.exception.committed)
            self.assertEqual(original, path.read_bytes())

    def test_source_read_failure_does_not_publish_or_disclose_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-read-failure-") as raw:
            path = Path(raw) / "digest.json"
            original = b'{"generation": 1}'
            path.write_bytes(original)
            path.chmod(0o600)
            with (
                patch.object(sidecar.os, "read", side_effect=OSError("synthetic-secret")),
                self.assertRaises(sidecar.SidecarSecurityError) as caught,
            ):
                sidecar.atomic_write_private_json(path, {"generation": 2}, max_bytes=1024)
            self.assertEqual("session_sidecar_read_error", caught.exception.reason_code)
            self.assertFalse(caught.exception.committed)
            self.assertNotIn("synthetic-secret", str(caught.exception))
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_short_source_read_is_not_accepted_as_a_complete_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-short-read-") as raw:
            path = Path(raw) / "digest.json"
            original = b'{"generation": 1}'
            path.write_bytes(original)
            path.chmod(0o600)
            with (
                patch.object(sidecar, "_read_bounded", return_value=original[:4]),
                patch.object(sidecar, "_write_all", wraps=sidecar._write_all) as write_stage,
                self.assertRaises(sidecar.SidecarSecurityError) as caught,
            ):
                sidecar.atomic_write_private_json(path, {"generation": 2}, max_bytes=1024)
            self.assertEqual("session_sidecar_snapshot_changed", caught.exception.reason_code)
            self.assertEqual("read", caught.exception.phase)
            self.assertFalse(caught.exception.committed)
            write_stage.assert_not_called()
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_published_read_failure_reports_uncertain_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-post-read-failure-") as raw:
            path = Path(raw) / "digest.json"
            path.write_bytes(b'{"generation": 1}')
            path.chmod(0o600)
            real_read = sidecar._read_authorized_bytes
            reads = 0

            def fail_after_replace(*args, **kwargs):
                nonlocal reads
                reads += 1
                if reads == 3:
                    raise sidecar.SidecarSecurityError(
                        "session_sidecar_read_error", "synthetic failure", phase="read"
                    )
                return real_read(*args, **kwargs)

            with (
                patch.object(sidecar, "_read_authorized_bytes", side_effect=fail_after_replace),
                self.assertRaises(sidecar.SidecarSecurityError) as caught,
            ):
                sidecar.atomic_write_private_json(path, {"generation": 2}, max_bytes=1024)
            self.assertEqual(3, reads)
            self.assertEqual("session_sidecar_durability_uncertain", caught.exception.reason_code)
            self.assertTrue(caught.exception.committed)
            self.assertEqual("uncertain", caught.exception.durability)
            self.assertEqual(2, json.loads(path.read_bytes())["generation"])

    def test_content_fingerprint_is_not_rendered_in_snapshot_repr(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-snapshot-privacy-") as raw:
            path = Path(raw) / "digest.json"
            secret = b'{"synthetic":"PRIVATE-SIDECAR-CANARY"}'
            path.write_bytes(secret)
            path.chmod(0o600)
            loaded = sidecar.read_private_bytes(path, max_bytes=1024)
            assert loaded is not None
            self.assertNotIn(secret.decode(), repr(loaded.snapshot))
            self.assertNotIn(hashlib.sha256(secret).hexdigest(), repr(loaded.snapshot))


if __name__ == "__main__":
    unittest.main()
