from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gateway_v2_permission_rejection_live_smoke import control_evidence_passed, interrupt_evidence_passed


class PermissionControlEvidenceTest(unittest.TestCase):
    @staticmethod
    def valid_controls() -> dict:
        def row(returned: bool, captured: bool | None = None) -> dict:
            return {
                "permission_requested": True,
                "after_hook_seen": True,
                "control_applied": True,
                "permission_bypassed": False,
                "tool_returned_to_model": returned,
                "host_cause_is_captured": captured,
            }

        return {
            "host_clone": row(False, True),
            "drop_cause": row(True),
            "throw_after": row(True),
        }

    def test_requires_every_observation_and_the_expected_host_behavior(self) -> None:
        controls = self.valid_controls()
        self.assertTrue(control_evidence_passed(controls))
        for mode, field, value in (
            ("host_clone", "host_cause_is_captured", False),
            ("host_clone", "tool_returned_to_model", True),
            ("drop_cause", "tool_returned_to_model", False),
            ("throw_after", "tool_returned_to_model", False),
            ("throw_after", "permission_bypassed", True),
            ("throw_after", "control_applied", False),
            ("drop_cause", "after_hook_seen", False),
            ("host_clone", "permission_requested", False),
        ):
            with self.subTest(mode=mode, field=field):
                changed = copy.deepcopy(controls)
                changed[mode][field] = value
                self.assertFalse(control_evidence_passed(changed))

    def test_incomplete_or_non_boolean_evidence_is_not_accepted(self) -> None:
        controls = self.valid_controls()
        missing = copy.deepcopy(controls)
        del missing["throw_after"]
        self.assertFalse(control_evidence_passed(missing))
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value):
                changed = copy.deepcopy(controls)
                changed["host_clone"]["host_cause_is_captured"] = value
                self.assertFalse(control_evidence_passed(changed))


class InterruptControlEvidenceTest(unittest.TestCase):
    @staticmethod
    def valid_controls() -> dict:
        common = {
            "permission_requested": True,
            "after_hook_seen": True,
            "permission_bypassed": False,
            "redactor_exception_on_wire": False,
            "redactor_exception_in_database": False,
            "redactor_exception_in_server_log": False,
            "forged_canary_on_wire": False,
            "forged_canary_in_database": False,
            "forged_canary_in_server_log": False,
        }
        stopped = {
            **common, "interrupt_guard_registered": True, "control_applied": True,
            "interrupt_phase": "after", "interrupt_result": {"interrupted": True},
            "session_outcome": "interrupted", "tool_returned_to_model": False,
            "peer_pending_preserved": True, "peer_completed": True,
        }
        return {
            "plain": {**stopped, "retry_completed": True},
            "forged": dict(stopped),
            "failure": {
                **common, "interrupt_guard_registered": True, "control_applied": True,
                "session_outcome": "failed", "tool_returned_to_model": False,
                "quarantine_enforced": True, "retry_blocked": True,
                "auxiliary_blocked": {"generate": True, "compaction": True},
                "peer_pending_preserved": True, "peer_completed": True,
            },
            "unprotected": {**common, "control_applied": True, "tool_returned_to_model": True},
            "feedback": {
                **common, "interrupt_guard_registered": True, "control_applied": False,
                "tool_returned_to_model": True, "redacted_feedback_on_wire": True,
                "feedback_on_wire": False, "feedback_in_database": False, "feedback_in_server_log": False,
            },
        }

    def test_requires_success_failure_peer_and_privacy_controls(self) -> None:
        controls = self.valid_controls()
        self.assertTrue(interrupt_evidence_passed(controls))
        for mode, field, value in (
            ("plain", "retry_completed", False),
            ("plain", "peer_pending_preserved", False),
            ("failure", "quarantine_enforced", False),
            ("failure", "retry_blocked", False),
            ("failure", "auxiliary_blocked", {"generate": True, "compaction": False}),
            ("unprotected", "tool_returned_to_model", False),
            ("forged", "forged_canary_in_database", True),
            ("feedback", "feedback_on_wire", True),
            ("feedback", "redacted_feedback_on_wire", False),
        ):
            with self.subTest(mode=mode, field=field):
                changed = copy.deepcopy(controls)
                changed[mode][field] = value
                self.assertFalse(interrupt_evidence_passed(changed))
        missing = copy.deepcopy(controls)
        del missing["failure"]
        self.assertFalse(interrupt_evidence_passed(missing))


if __name__ == "__main__":
    unittest.main()
