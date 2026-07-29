from __future__ import annotations

import importlib
import hashlib
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class SessionMetadataIndexTest(unittest.TestCase):
    def test_update_writes_parseable_atomic_index(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions" / "index.json"
            result = module.update_session_index(
                {"timestamp": "2026-07-11T00:00:00+00:00", "cwd": "/repo", "reason": "test"},
                path,
            )
            self.assertEqual("PASS", result["result"])
            self.assertEqual({"events": 0, "reasons": 0, "plan_ids": 0}, result["pruned"])
            self.assertEqual("test", json.loads(path.read_text())["sessions"][0]["last_reason"])
            self.assertFalse(list(path.parent.glob(".index.json.*.tmp")))
            self.assertEqual(0o600, path.stat().st_mode & 0o777)


    def test_concurrent_updates_preserve_all_events(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            def update(reason: str) -> None:
                module.update_session_index(
                    {"timestamp": "2026-07-11T00:00:00+00:00", "cwd": "/repo", "reason": reason},
                    path,
                )
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(update, ["first", "second"]))
            saved = json.loads(path.read_text())
            self.assertEqual(2, sum(item["event_count"] for item in saved["sessions"]))
            self.assertIn(saved["sessions"][0]["last_reason"], {"first", "second"})

    def test_malformed_index_is_preserved_and_reported(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            quarantine = Path(tmp) / "quarantine"
            original = b"{not json"
            path.write_bytes(original)
            original_identity = (path.stat().st_dev, path.stat().st_ino)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("FAIL", result["result"])
            self.assertEqual("session_index_corrupt", result["reason_code"])
            self.assertEqual("malformed_json", result["corruption_kind"])
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(
                original_identity,
                (path.stat().st_dev, path.stat().st_ino),
            )
            self.assertEqual(
                hashlib.sha256(original).hexdigest(),
                result["quarantine"]["sha256"],
            )
            quarantine_path = Path(result["quarantine"]["path"])
            self.assertEqual(original, quarantine_path.read_bytes())
            self.assertEqual(0o600, quarantine_path.stat().st_mode & 0o777)
            self.assertEqual(0o700, quarantine.stat().st_mode & 0o777)

            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                repeated = module.update_session_index({"cwd": "/repo"}, path)
            self.assertTrue(repeated["quarantine"]["reused"])
            self.assertEqual([quarantine_path], list(quarantine.glob("*.bin")))
            self.assertFalse(list(quarantine.glob("*.tmp")))

    def test_invalid_utf8_is_preserved_byte_exactly(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "index.json"
            quarantine = root / "quarantine"
            original = b'\xff\xfe{"version": 1, "sessions": []}'
            path.write_bytes(original)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("session_index_corrupt", result["reason_code"])
            self.assertEqual("invalid_utf8", result["corruption_kind"])
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(original, Path(result["quarantine"]["path"]).read_bytes())

    def test_structural_corruption_is_not_silently_normalized(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        cases = {
            "non_object_root": [],
            "sessions_missing": {"version": 1},
            "sessions_not_list": {"version": 1, "sessions": {}},
            "session_not_object": {"version": 1, "sessions": ["bad"]},
            "session_id_invalid": {"version": 1, "sessions": [{"session_id": ""}]},
            "event_count_invalid": {
                "version": 1,
                "sessions": [{"session_id": "one", "event_count": True}],
            },
            "events_invalid": {
                "version": 1,
                "sessions": [{"session_id": "one", "events": ["bad"]}],
            },
            "reasons_invalid": {
                "version": 1,
                "sessions": [{"session_id": "one", "reasons": [1]}],
            },
            "plan_ids_invalid": {
                "version": 1,
                "sessions": [{"session_id": "one", "plan_ids": [1]}],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quarantine = root / "quarantine"
            for corruption_kind, payload in cases.items():
                with self.subTest(corruption_kind=corruption_kind):
                    path = root / f"{corruption_kind}.json"
                    original = json.dumps(payload).encode("utf-8")
                    path.write_bytes(original)
                    with patch.dict(
                        os.environ,
                        {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
                    ):
                        result = module.update_session_index({"cwd": "/repo"}, path)
                    self.assertEqual("FAIL", result["result"])
                    self.assertEqual("session_index_corrupt", result["reason_code"])
                    self.assertEqual(corruption_kind, result["corruption_kind"])
                    self.assertEqual(original, path.read_bytes())

    def test_unsupported_version_precedes_schema_validation_and_is_not_quarantined(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "index.json"
            quarantine = root / "quarantine"
            original = b'{"version": 2, "sessions": "future-schema"}'
            path.write_bytes(original)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("FAIL", result["result"])
            self.assertEqual("session_index_unsupported_version", result["reason_code"])
            self.assertIsNone(result["quarantine"])
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(quarantine.exists())

    def test_versionless_legacy_index_is_accepted_and_upgraded_on_write(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            path.write_text(
                json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "legacy",
                                "event_count": 1,
                                "last_event_at": "2026-07-29T00:00:00+00:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"OPENCODE_SESSION_ID": "legacy"}):
                result = module.update_session_index(
                    {
                        "timestamp": "2026-07-30T00:00:00+00:00",
                        "cwd": "/repo",
                        "reason": "manual",
                    },
                    path,
                )
            self.assertEqual("PASS", result["result"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, saved["version"])
            self.assertEqual(2, saved["sessions"][0]["event_count"])

    def test_historical_v1_shape_remains_accepted(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            historical = {
                "version": 1,
                "generated_at": "2026-07-27T00:00:00Z",
                "sessions": [
                    {
                        "session_id": "historical",
                        "cwd": "/repo",
                        "started_at": "2026-07-27T00:00:00Z",
                        "last_event_at": "2026-07-27T01:00:00Z",
                        "event_count": 7,
                        "last_reason": "manual",
                        "branches": ["main"],
                        "plan_ids": ["plan-1"],
                    }
                ],
            }
            path.write_text(json.dumps(historical), encoding="utf-8")
            loaded = module.load_session_index(path)
            self.assertEqual("historical", loaded["sessions"][0]["session_id"])
            self.assertEqual(["main"], loaded["sessions"][0]["branches"])

    def test_digest_fields_are_normalized_and_serialization_failure_is_structured(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "index.json"
            result = module.update_session_index(
                {
                    "timestamp": object(),
                    "cwd": "/repo",
                    "reason": object(),
                    "git": {"status_count": object(), "branch": object()},
                    "plan_execution": {"status": object(), "plan_id": object()},
                },
                path,
            )
            self.assertEqual("PASS", result["result"])
            event = json.loads(path.read_text(encoding="utf-8"))["sessions"][0]["events"][0]
            self.assertEqual(
                {
                    "timestamp": None,
                    "reason": None,
                    "changes": 0,
                    "branch": None,
                    "plan_status": None,
                    "plan_id": None,
                },
                event,
            )

            original = path.read_bytes()
            with patch.object(
                module,
                "_atomic_write_json",
                side_effect=TypeError("injected serialization failure"),
            ):
                failure = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("FAIL", failure["result"])
            self.assertEqual(
                "session_index_serialization_error",
                failure["reason_code"],
            )
            self.assertEqual(original, path.read_bytes())

    @unittest.skipUnless(hasattr(os, "symlink") and hasattr(os, "link"), "links unsupported")
    def test_unsafe_link_sources_are_never_quarantined(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quarantine = root / "quarantine"
            target = root / "target.json"
            original = b"{malformed"
            target.write_bytes(original)

            symlink_path = root / "symlink.json"
            symlink_path.symlink_to(target)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                symlink_result = module.update_session_index({"cwd": "/repo"}, symlink_path)
            self.assertEqual("session_index_unsafe_source", symlink_result["reason_code"])
            self.assertEqual(original, target.read_bytes())

            hardlink_path = root / "hardlink.json"
            os.link(target, hardlink_path)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                hardlink_result = module.update_session_index({"cwd": "/repo"}, hardlink_path)
            self.assertEqual("session_index_unsafe_source", hardlink_result["reason_code"])
            self.assertEqual(original, target.read_bytes())
            self.assertFalse(quarantine.exists())

    def test_quarantine_collision_is_fail_closed(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "index.json"
            quarantine = root / "quarantine"
            quarantine.mkdir(mode=0o700)
            original = b"{malformed"
            path.write_bytes(original)
            artifact = quarantine / f"{hashlib.sha256(original).hexdigest()}.bin"
            artifact.write_bytes(b"different")
            artifact.chmod(0o600)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("FAIL", result["result"])
            self.assertEqual("session_index_quarantine_collision", result["reason_code"])
            self.assertEqual("collision", result["quarantine"]["status"])
            self.assertNotIn("sha256", result["quarantine"])
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(b"different", artifact.read_bytes())

    def test_ordinary_read_error_and_insecure_quarantine_directory_do_not_copy(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory_source = root / "index-directory"
            directory_source.mkdir()
            quarantine = root / "quarantine"
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                io_result = module.update_session_index({"cwd": "/repo"}, directory_source)
            self.assertEqual("session_index_unsafe_source", io_result["reason_code"])
            self.assertIsNone(io_result["quarantine"])
            self.assertFalse(quarantine.exists())

            corrupt_path = root / "corrupt.json"
            corrupt_path.write_bytes(b"{malformed")
            quarantine.mkdir(mode=0o700)
            quarantine.chmod(0o755)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                unsafe_directory_result = module.update_session_index(
                    {"cwd": "/repo"}, corrupt_path
                )
            self.assertEqual(
                "session_index_quarantine_error",
                unsafe_directory_result["reason_code"],
            )
            self.assertEqual(b"{malformed", corrupt_path.read_bytes())
            self.assertFalse(list(quarantine.iterdir()))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_existing_symlink_artifact_is_a_collision(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "index.json"
            quarantine = root / "quarantine"
            quarantine.mkdir(mode=0o700)
            original = b"{malformed"
            path.write_bytes(original)
            target = root / "artifact-target"
            target.write_bytes(b"private-target")
            artifact = quarantine / f"{hashlib.sha256(original).hexdigest()}.bin"
            artifact.symlink_to(target)
            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ):
                result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("session_index_quarantine_collision", result["reason_code"])
            self.assertTrue(artifact.is_symlink())
            self.assertEqual(b"private-target", target.read_bytes())
            self.assertEqual(original, path.read_bytes())

    @unittest.skipUnless(
        hasattr(os, "symlink") and hasattr(os, "link") and hasattr(os, "mkfifo"),
        "required filesystem primitives unsupported",
    )
    def test_valid_link_and_fifo_sources_fail_before_read_or_write(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "valid.json"
            original = b'{"version": 1, "sessions": []}'
            valid.write_bytes(original)

            symlink_path = root / "valid-symlink.json"
            symlink_path.symlink_to(valid)
            symlink_result = module.update_session_index({"cwd": "/repo"}, symlink_path)
            self.assertEqual("session_index_unsafe_source", symlink_result["reason_code"])
            self.assertTrue(symlink_path.is_symlink())
            self.assertEqual(original, valid.read_bytes())

            hardlink_path = root / "valid-hardlink.json"
            os.link(valid, hardlink_path)
            hardlink_result = module.update_session_index({"cwd": "/repo"}, hardlink_path)
            self.assertEqual("session_index_unsafe_source", hardlink_result["reason_code"])
            self.assertEqual(original, valid.read_bytes())

            fifo_path = root / "index.fifo"
            os.mkfifo(fifo_path)
            fifo_result = module.update_session_index({"cwd": "/repo"}, fifo_path)
            self.assertEqual("session_index_unsafe_source", fifo_result["reason_code"])

    def test_unsupported_secure_primitives_fail_closed_for_existing_index(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            original = b'{"version": 1, "sessions": []}'
            path.write_bytes(original)
            with patch.object(module.os, "supports_dir_fd", set()):
                result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("session_index_security_unsupported", result["reason_code"])
            self.assertEqual(original, path.read_bytes())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_post_publication_path_swap_never_chmods_victim(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "index.json"
            path.write_text('{"version": 1, "sessions": []}', encoding="utf-8")
            victim = root / "victim"
            victim.write_text("victim", encoding="utf-8")
            victim.chmod(0o640)
            real_replace = os.replace

            def replace_then_swap(source: Path, destination: Path) -> None:
                real_replace(source, destination)
                Path(destination).unlink()
                Path(destination).symlink_to(victim)

            with patch.object(module.os, "replace", side_effect=replace_then_swap):
                result = module.update_session_index({"cwd": "/repo"}, path)
            self.assertEqual("session_index_write_race", result["reason_code"])
            self.assertTrue(path.is_symlink())
            self.assertEqual("victim", victim.read_text(encoding="utf-8"))
            self.assertEqual(0o640, victim.stat().st_mode & 0o777)

    def test_interruption_after_quarantine_link_cleans_owned_temporary(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "index.json"
            quarantine = root / "quarantine"
            original = b"{malformed"
            path.write_bytes(original)
            real_link = os.link

            def link_then_interrupt(*args, **kwargs) -> None:
                real_link(*args, **kwargs)
                raise KeyboardInterrupt

            with patch.dict(
                os.environ,
                {"MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR": str(quarantine)},
            ), patch.object(
                module, "_require_secure_index_primitives", return_value=None
            ), patch.object(module.os, "link", side_effect=link_then_interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    module.update_session_index({"cwd": "/repo"}, path)
            artifact = quarantine / f"{hashlib.sha256(original).hexdigest()}.bin"
            self.assertEqual(original, artifact.read_bytes())
            self.assertEqual(1, artifact.stat().st_nlink)
            self.assertFalse(list(quarantine.glob("*.tmp")))
            self.assertEqual(original, path.read_bytes())

    def test_pruning_interprets_legacy_naive_timestamps_as_utc(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        sessions = [
            {"session_id": "naive", "last_event_at": "2026-07-26T12:00:00"},
            {"session_id": "earlier-offset", "last_event_at": "2026-07-27T01:00:00+02:00"},
            {"session_id": "later-utc", "last_event_at": "2026-07-26T23:30:00+00:00"},
            {"session_id": "invalid", "last_event_at": "not-a-timestamp"},
            {"session_id": "expired", "last_event_at": "2026-07-01T00:00:00"},
        ]
        with patch.object(
            module,
            "_utc_now",
            return_value=datetime(2026, 7, 27, 0, 0, tzinfo=UTC),
        ):
            result = module._prune_sessions(
                sessions,
                {"max_age_days": 7, "max_sessions": 10},
            )
        self.assertEqual(
            ["later-utc", "earlier-offset", "naive", "invalid"],
            [item["session_id"] for item in result],
        )
        self.assertEqual(UTC, module._parse_iso("2026-07-26T12:00:00").tzinfo)
        self.assertEqual(
            datetime.fromisoformat("2026-07-26T12:00:00+10:00").utcoffset(),
            module._parse_iso("2026-07-26T12:00:00+10:00").utcoffset(),
        )

    def test_session_command_orders_mixed_offsets_chronologically(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_command"))
        rows = module._session_rows(
            {
                "sessions": [
                    {"session_id": "earlier-offset", "last_event_at": "2026-07-27T01:00:00+02:00"},
                    {"session_id": "later-utc", "last_event_at": "2026-07-26T23:30:00+00:00"},
                    {"session_id": "legacy-naive", "last_event_at": "2026-07-26T23:15:00"},
                    {"session_id": "invalid", "last_event_at": "not-a-timestamp"},
                ]
            }
        )
        self.assertEqual(
            ["later-utc", "legacy-naive", "earlier-offset", "invalid"],
            [row["session_id"] for row in rows],
        )

    def test_fallback_identity_is_process_unique(self) -> None:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        module = importlib.reload(importlib.import_module("session_metadata_index"))
        previous = __import__("os").environ.pop("OPENCODE_SESSION_ID", None)
        try:
            first = module._session_id("2026-07-11T00:00:00+00:00", "/repo")
            second = module._session_id("2026-07-11T00:00:00+00:00", "/repo")
            self.assertNotEqual(first, second)
            self.assertTrue(first.startswith("/repo::2026-07-11T00:00:00+00:00::"))
        finally:
            if previous is not None:
                __import__("os").environ["OPENCODE_SESSION_ID"] = previous

if __name__ == "__main__":
    unittest.main()
