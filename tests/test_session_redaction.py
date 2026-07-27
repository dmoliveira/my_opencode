from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "session_command.py"

SESSION_CANARY = "WAVE7_SESSION_PRIVATE_CANARY"
QUERY_CANARY = "WAVE7_QUERY_PRIVATE_CANARY"
CWD_CANARY = "WAVE7_CWD_PRIVATE_CANARY"
REASON_CANARY = "WAVE7_REASON_PRIVATE_CANARY"
BRANCH_CANARY = "WAVE7_BRANCH_PRIVATE_CANARY"
PLAN_CANARY = "WAVE7_PLAN_PRIVATE_CANARY"
INDEX_CANARY = "WAVE7_INDEX_PATH_PRIVATE_CANARY"
DIGEST_CANARY = "WAVE7_DIGEST_PATH_PRIVATE_CANARY"
LAUNCH_CANARY = "WAVE7_LAUNCH_PRIVATE_CANARY"
MALFORMED_CANARY = "WAVE7_MALFORMED_PRIVATE_CANARY"
SENSITIVE_CANARIES = (
    SESSION_CANARY,
    QUERY_CANARY,
    CWD_CANARY,
    REASON_CANARY,
    BRANCH_CANARY,
    PLAN_CANARY,
    INDEX_CANARY,
    DIGEST_CANARY,
    LAUNCH_CANARY,
    MALFORMED_CANARY,
)


class SessionRedactionTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        index_path = root / INDEX_CANARY / "index.json"
        digest_path = root / DIGEST_CANARY / "last-session.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessions": [
                        {
                            "session_id": SESSION_CANARY,
                            "cwd": f"/{CWD_CANARY}/repo",
                            "started_at": "2026-07-27T00:00:00Z",
                            "last_event_at": "2026-07-27T01:00:00Z",
                            "event_count": 7,
                            "last_reason": f"{REASON_CANARY}-{QUERY_CANARY}",
                            "branches": [BRANCH_CANARY],
                            "plan_ids": [PLAN_CANARY],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        digest_path.write_text(
            json.dumps(
                {
                    "git": {"branch": BRANCH_CANARY, "status_count": 3},
                    "plan_execution": {"status": "active", "plan_id": PLAN_CANARY},
                }
            ),
            encoding="utf-8",
        )
        return index_path, digest_path

    def _run(
        self,
        root: Path,
        args: list[str],
        *,
        redact_default: bool = False,
        malformed_index: bool = False,
        malformed_digest: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        index_path, digest_path = self._fixture(root)
        if malformed_index:
            index_path.write_text("{" + MALFORMED_CANARY, encoding="utf-8")
        if malformed_digest:
            digest_path.write_text("{" + MALFORMED_CANARY, encoding="utf-8")
        env = {
            **os.environ,
            "HOME": str(root),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(index_path),
            "MY_OPENCODE_DIGEST_PATH": str(digest_path),
            "MY_OPENCODE_SESSION_REDACT_DEFAULT": "true" if redact_default else "false",
            "MY_OPENCODE_SESSION_REDACT_FIELDS": "started_at,last_event_at,event_count",
            "OPENCODE_SESSION_ID": "",
            "CI": "true",
        }
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _assert_no_canaries(self, text: str) -> None:
        for canary in SENSITIVE_CANARIES:
            self.assertNotIn(canary, text)
            self.assertNotIn(canary.lower(), text)

    def test_redacted_search_json_uses_exact_share_safe_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                ["search", QUERY_CANARY, "--redact", "--json"],
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self._assert_no_canaries(result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            {"result", "command", "redacted", "count", "sessions"},
            set(payload),
        )
        self.assertEqual(1, payload["count"])
        self.assertEqual(
            {"started_at", "last_event_at", "event_count"},
            set(payload["sessions"][0]),
        )
        self.assertEqual(7, payload["sessions"][0]["event_count"])

    def test_redacted_search_human_output_uses_same_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), ["search", QUERY_CANARY, "--redact"])
        self.assertEqual(0, result.returncode, result.stderr)
        self._assert_no_canaries(result.stdout + result.stderr)
        self.assertIn("session search (redacted)", result.stdout)
        self.assertIn("events=7", result.stdout)
        self.assertNotIn("query:", result.stdout)
        self.assertNotIn("session_id", result.stdout)

    def test_redacted_search_environment_default_and_strict_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                ["search", QUERY_CANARY, "--json"],
                redact_default=True,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["redacted"])
        self.assertIn("started_at", payload["sessions"][0])
        self._assert_no_canaries(result.stdout + result.stderr)

    def test_redacted_search_failure_is_fixed_and_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_result = self._run(
                Path(tmp),
                ["search", QUERY_CANARY, "--redact", "--json"],
                malformed_index=True,
            )
        self.assertEqual(1, json_result.returncode)
        self._assert_no_canaries(json_result.stdout + json_result.stderr)
        self.assertEqual(
            {
                "result": "FAIL",
                "command": "search",
                "redacted": True,
                "error_code": "session_index_unavailable",
            },
            json.loads(json_result.stdout),
        )

        with tempfile.TemporaryDirectory() as tmp:
            human_result = self._run(
                Path(tmp),
                ["search", QUERY_CANARY, "--redact"],
                malformed_index=True,
            )
        self.assertEqual(1, human_result.returncode)
        self._assert_no_canaries(human_result.stdout + human_result.stderr)
        self.assertEqual("error_code: session_index_unavailable", human_result.stdout.strip())

    def test_redacted_search_missing_query_has_fixed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), ["search", "--redact", "--json"])
        self.assertEqual(1, result.returncode)
        self.assertEqual(
            "session_search_query_required",
            json.loads(result.stdout)["error_code"],
        )

    def test_redacted_handoff_json_skips_sensitive_digest_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                [
                    "handoff",
                    "--id",
                    SESSION_CANARY,
                    "--launch-cwd",
                    f"/{LAUNCH_CANARY}",
                    "--fork",
                    "--redact",
                    "--json",
                ],
                malformed_digest=True,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self._assert_no_canaries(result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            {
                "result",
                "command",
                "redacted",
                "started_at",
                "last_event_at",
                "event_count",
            },
            set(payload),
        )
        self.assertEqual(7, payload["event_count"])

    def test_redacted_handoff_human_and_environment_default_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                ["handoff", "--id", SESSION_CANARY, "--launch-cwd", LAUNCH_CANARY],
                redact_default=True,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self._assert_no_canaries(result.stdout + result.stderr)
        self.assertIn("session handoff (redacted)", result.stdout)
        self.assertIn("event_count: 7", result.stdout)
        self.assertNotIn("next_actions", result.stdout)
        self.assertNotIn("resume_command", result.stdout)

    def test_redacted_handoff_failures_never_echo_target_or_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                ["handoff", "--id", MALFORMED_CANARY, "--redact", "--json"],
            )
        self.assertEqual(1, result.returncode)
        self._assert_no_canaries(result.stdout + result.stderr)
        self.assertEqual(
            {
                "result": "FAIL",
                "command": "handoff",
                "redacted": True,
                "error_code": "session_not_found",
            },
            json.loads(result.stdout),
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                ["handoff", "--redact", "--json"],
                malformed_index=True,
            )
        self.assertEqual(1, result.returncode)
        self._assert_no_canaries(result.stdout + result.stderr)
        self.assertEqual("session_index_unavailable", json.loads(result.stdout)["error_code"])

        with tempfile.TemporaryDirectory() as tmp:
            human_result = self._run(
                Path(tmp),
                ["handoff", "--id", MALFORMED_CANARY, "--redact"],
            )
        self.assertEqual(1, human_result.returncode)
        self._assert_no_canaries(human_result.stdout + human_result.stderr)
        self.assertEqual("error_code: session_not_found", human_result.stdout.strip())

    def test_unredacted_search_and_handoff_contracts_remain_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            search = self._run(root, ["search", QUERY_CANARY, "--json"])
            handoff = self._run(
                root,
                ["handoff", "--id", SESSION_CANARY, "--launch-cwd", LAUNCH_CANARY, "--json"],
            )
        self.assertEqual(0, search.returncode, search.stderr)
        search_payload = json.loads(search.stdout)
        self.assertFalse(search_payload["redacted"])
        self.assertIn("index_path", search_payload)
        self.assertIn("query", search_payload)
        self.assertEqual(SESSION_CANARY, search_payload["sessions"][0]["session_id"])

        self.assertEqual(0, handoff.returncode, handoff.stderr)
        handoff_payload = json.loads(handoff.stdout)
        self.assertFalse(handoff_payload["redacted"])
        self.assertEqual(SESSION_CANARY, handoff_payload["session_id"])
        self.assertIn(LAUNCH_CANARY, handoff_payload["resume_command"])
        self.assertIn("next_actions", handoff_payload)

    def test_invalid_record_fields_are_safely_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = self._fixture(root)
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            payload["sessions"][0]["started_at"] = MALFORMED_CANARY
            payload["sessions"][0]["last_event_at"] = MALFORMED_CANARY
            payload["sessions"][0]["event_count"] = MALFORMED_CANARY
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            env = {
                **os.environ,
                "HOME": str(root),
                "MY_OPENCODE_SESSION_INDEX_PATH": str(index_path),
                "MY_OPENCODE_SESSION_REDACT_DEFAULT": "true",
                "OPENCODE_SESSION_ID": "",
                "CI": "true",
            }
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "handoff", "--id", SESSION_CANARY, "--json"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self._assert_no_canaries(result.stdout + result.stderr)
        redacted = json.loads(result.stdout)
        self.assertIsNone(redacted["started_at"])
        self.assertIsNone(redacted["last_event_at"])
        self.assertEqual(0, redacted["event_count"])


if __name__ == "__main__":
    unittest.main()
