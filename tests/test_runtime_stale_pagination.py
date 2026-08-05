from __future__ import annotations

import base64
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from runtime_stale_pagination import (
    STALE_CURSOR_MAX_ENCODED_BYTES,
    STALE_FINDING_CLASSES,
    STALE_FINDINGS_PAGE_SIZE,
    RuntimeStaleCursorError,
    decode_runtime_stale_cursor,
    empty_runtime_stale_pagination,
    encode_runtime_stale_cursor,
    initial_runtime_stale_class_states,
    materialize_runtime_stale_class_page,
)


class RuntimeStalePaginationTest(unittest.TestCase):
    def _states(self) -> dict[str, dict]:
        states = initial_runtime_stale_class_states()
        states["parent_child_mismatch"] = {
            "after": [123, "parent", "child"],
            "exhausted": False,
        }
        for issue_type in STALE_FINDING_CLASSES[1:]:
            states[issue_type] = {"after": None, "exhausted": True}
        return states

    def _token_from_payload(self, payload: dict, *, canonical: bool = True) -> str:
        raw = json.dumps(
            payload,
            sort_keys=canonical,
            separators=(",", ":") if canonical else None,
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _decode_payload(self, token: str) -> dict:
        padding = "=" * ((4 - len(token) % 4) % 4)
        return json.loads(base64.urlsafe_b64decode(token + padding))

    def test_round_trip_binds_database_threshold_clock_and_class_state(self) -> None:
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            cursor_value = encode_runtime_stale_cursor(
                now_ms=now_ms,
                stale_seconds=300,
                db_path=db_path,
                classes=self._states(),
            )
            self.assertNotIn("=", cursor_value)
            decoded = decode_runtime_stale_cursor(
                cursor_value,
                db_path=db_path,
                explicit_stale_seconds=300,
                validation_now_ms=now_ms,
            )
        self.assertEqual(now_ms, decoded["now_ms"])
        self.assertEqual(300, decoded["stale_seconds"])
        self.assertEqual(STALE_FINDINGS_PAGE_SIZE, decoded["page_size"])
        self.assertEqual(self._states(), decoded["classes"])

    def test_context_mismatch_and_future_clock_fail_closed(self) -> None:
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            cursor_value = encode_runtime_stale_cursor(
                now_ms=now_ms,
                stale_seconds=300,
                db_path=db_path,
                classes=self._states(),
            )
            for kwargs in (
                {"db_path": Path(tmp) / "other.db", "explicit_stale_seconds": 300},
                {"db_path": db_path, "explicit_stale_seconds": 301},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(
                    RuntimeStaleCursorError
                ):
                    decode_runtime_stale_cursor(
                        cursor_value,
                        validation_now_ms=now_ms,
                        **kwargs,
                    )

            payload = self._decode_payload(cursor_value)
            payload["now_ms"] = now_ms + 5 * 60 * 1000 + 1
            future = self._token_from_payload(payload)
            with self.assertRaises(RuntimeStaleCursorError):
                decode_runtime_stale_cursor(
                    future,
                    db_path=db_path,
                    explicit_stale_seconds=300,
                    validation_now_ms=now_ms,
                )

    def test_noncanonical_duplicate_bool_and_invalid_class_state_are_rejected(self) -> None:
        now_ms = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            cursor_value = encode_runtime_stale_cursor(
                now_ms=now_ms,
                stale_seconds=300,
                db_path=db_path,
                classes=self._states(),
            )
            payload = self._decode_payload(cursor_value)

            malformed = (
                "%%%",
                cursor_value + "=",
                "A" * (STALE_CURSOR_MAX_ENCODED_BYTES + 1),
            )
            for candidate in malformed:
                with self.subTest(candidate=candidate[:20]), self.assertRaises(
                    RuntimeStaleCursorError
                ):
                    decode_runtime_stale_cursor(
                        candidate,
                        db_path=db_path,
                        explicit_stale_seconds=300,
                        validation_now_ms=now_ms,
                    )

            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            self.assertIn(len(cursor_value) % 4, {2, 3})
            last_index = alphabet.index(cursor_value[-1])
            pad_alias = cursor_value[:-1] + alphabet[last_index + 1]
            self.assertEqual(
                self._decode_payload(cursor_value),
                self._decode_payload(pad_alias),
            )
            with self.assertRaises(RuntimeStaleCursorError):
                decode_runtime_stale_cursor(
                    pad_alias,
                    db_path=db_path,
                    explicit_stale_seconds=300,
                    validation_now_ms=now_ms,
                )

            noncanonical = self._token_from_payload(payload, canonical=False)
            with self.assertRaises(RuntimeStaleCursorError):
                decode_runtime_stale_cursor(
                    noncanonical,
                    db_path=db_path,
                    explicit_stale_seconds=300,
                    validation_now_ms=now_ms,
                )

            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            duplicate_raw = canonical[:-1] + ',"v":1}'
            duplicate = base64.urlsafe_b64encode(duplicate_raw.encode()).decode().rstrip("=")
            with self.assertRaises(RuntimeStaleCursorError):
                decode_runtime_stale_cursor(
                    duplicate,
                    db_path=db_path,
                    explicit_stale_seconds=300,
                    validation_now_ms=now_ms,
                )

            for mutate in (
                lambda item: item.__setitem__("page_size", True),
                lambda item: item.__setitem__("now_ms", True),
                lambda item: item.__setitem__("stale_seconds", True),
                lambda item: item["classes"]["parent_child_mismatch"].__setitem__(
                    "exhausted", 1
                ),
                lambda item: item["classes"]["parent_child_mismatch"][
                    "after"
                ].__setitem__(0, True),
                lambda item: item["classes"]["parent_child_mismatch"].__setitem__(
                    "after", [123, "parent"]
                ),
                lambda item: item["classes"]["parent_child_mismatch"].__setitem__(
                    "after", [123, "", "child"]
                ),
                lambda item: item["classes"]["parent_child_mismatch"].__setitem__(
                    "after", [123, "x" * 1025, "child"]
                ),
                lambda item: item["classes"]["silent_parent_after_delegation_abort"].update(
                    {"after": None, "exhausted": False}
                ),
                lambda item: item["classes"].pop("stale_running_tool"),
            ):
                changed = json.loads(json.dumps(payload))
                mutate(changed)
                with self.assertRaises(RuntimeStaleCursorError):
                    decode_runtime_stale_cursor(
                        self._token_from_payload(changed),
                        db_path=db_path,
                        explicit_stale_seconds=300,
                        validation_now_ms=now_ms,
                    )

    def test_materialization_keeps_twenty_and_uses_full_ordering_tuple(self) -> None:
        rows = [
            {
                "parent_time_updated": 100,
                "parent_session_id": f"parent-{index:02d}",
                "child_session_id": f"child-{index:02d}",
            }
            for index in range(21, 0, -1)
        ]
        page, state = materialize_runtime_stale_class_page(
            "parent_child_mismatch",
            rows,
            {"after": None, "exhausted": False},
        )
        self.assertEqual(20, len(page))
        self.assertFalse(state["exhausted"])
        self.assertEqual(
            [100, page[-1]["parent_session_id"], page[-1]["child_session_id"]],
            state["after"],
        )

    def test_encoder_rejects_invalid_internal_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            for now_ms, stale_seconds, states in (
                (True, 300, self._states()),
                (1, 2**31, self._states()),
                (1, 300, initial_runtime_stale_class_states()),
            ):
                with self.subTest(
                    now_ms=now_ms,
                    stale_seconds=stale_seconds,
                ), self.assertRaises(RuntimeStaleCursorError):
                    encode_runtime_stale_cursor(
                        now_ms=now_ms,
                        stale_seconds=stale_seconds,
                        db_path=db_path,
                        classes=states,
                    )

    def test_empty_failure_metadata_is_total_and_stable(self) -> None:
        fields = empty_runtime_stale_pagination(cursor_applied=True)
        self.assertEqual(STALE_FINDINGS_PAGE_SIZE, fields["stale_findings_page_size"])
        self.assertEqual(0, fields["stale_findings_page_count"])
        self.assertEqual(
            set(STALE_FINDING_CLASSES),
            set(fields["stale_findings_page_counts"]),
        )
        self.assertTrue(fields["stale_findings_cursor_applied"])
        self.assertFalse(fields["stale_findings_pagination_complete"])


if __name__ == "__main__":
    unittest.main()
