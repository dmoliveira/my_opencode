from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gateway_v2_permission_rejection_live_smoke import control_evidence_passed


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


if __name__ == "__main__":
    unittest.main()
