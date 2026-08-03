from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import agent_doctor


class AgentDoctorPromptBudgetTest(unittest.TestCase):
    def budget_check(self, word_count: int) -> dict:
        return agent_doctor.prompt_body_budget_check(
            "fixture",
            "word " * word_count,
            baseline=word_count,
            limit=agent_doctor.ORCHESTRATOR_BODY_WORD_LIMIT,
            path=Path("fixture.json"),
        )

    def test_word_budget_accepts_exact_limit(self) -> None:
        check = self.budget_check(agent_doctor.ORCHESTRATOR_BODY_WORD_LIMIT)

        self.assertTrue(check["ok"])
        self.assertEqual(agent_doctor.ORCHESTRATOR_BODY_WORD_LIMIT, check["actual"])
        self.assertEqual(agent_doctor.ORCHESTRATOR_BODY_WORD_LIMIT, check["limit"])

    def test_word_budget_rejects_limit_plus_one(self) -> None:
        check = self.budget_check(agent_doctor.ORCHESTRATOR_BODY_WORD_LIMIT + 1)

        self.assertFalse(check["ok"])
        self.assertIn("limit is 450", check["reason"])

    def test_orchestrator_compaction_and_contract(self) -> None:
        path = REPO_ROOT / "agent" / "specs" / "orchestrator.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        body = spec["body_template"]
        checks = agent_doctor._check_orchestrator_prompt_contract(spec, path)

        self.assertTrue(
            all(check["ok"] for check in checks),
            [check for check in checks if not check["ok"]],
        )
        word_count = agent_doctor.count_prompt_words(body)
        self.assertEqual(446, word_count)
        self.assertLessEqual(
            word_count,
            int(agent_doctor.ORCHESTRATOR_BODY_WORD_BASELINE * 0.70),
        )


class AgentDoctorModelPolicyTest(unittest.TestCase):
    ROUTING_CATEGORIES = {
        "balanced": {"model": "openai/gpt-5.6-terra"},
        "writing": {"model": "openai/gpt-5.4"},
    }

    def check(self, spec: dict) -> dict:
        return agent_doctor.agent_model_policy_check(
            spec, self.ROUTING_CATEGORIES, Path("fixture.json")
        )

    def test_matching_explicit_pin_passes(self) -> None:
        check = self.check(
            {
                "name": "fixture",
                "model": "openai/gpt-5.6-terra",
                "metadata": {"default_category": "balanced"},
            }
        )

        self.assertTrue(check["ok"])
        self.assertFalse(check["inherits_category"])
        self.assertEqual("openai/gpt-5.6-terra", check["effective_model"])

    def test_mismatched_explicit_pin_fails(self) -> None:
        check = self.check(
            {
                "name": "fixture",
                "model": "openai/gpt-5.4",
                "metadata": {"default_category": "balanced"},
            }
        )

        self.assertFalse(check["ok"])
        self.assertIn("does not match balanced", check["reason"])
        self.assertEqual("openai/gpt-5.6-terra", check["expected_model"])

    def test_unpinned_agent_inherits_category_model(self) -> None:
        check = self.check(
            {"name": "fixture", "metadata": {"default_category": "writing"}}
        )

        self.assertTrue(check["ok"])
        self.assertTrue(check["inherits_category"])
        self.assertIsNone(check["pinned_model"])
        self.assertEqual("openai/gpt-5.4", check["effective_model"])

    def test_unknown_category_fails(self) -> None:
        check = self.check(
            {"name": "fixture", "metadata": {"default_category": "missing"}}
        )

        self.assertFalse(check["ok"])
        self.assertIn("unknown routing category", check["reason"])

    def test_malformed_explicit_pin_fails(self) -> None:
        check = self.check(
            {
                "name": "fixture",
                "model": 56,
                "metadata": {"default_category": "balanced"},
            }
        )

        self.assertFalse(check["ok"])
        self.assertIn("invalid explicit model pin", check["reason"])

    def test_current_inventory_and_model_policy_are_complete(self) -> None:
        checks = agent_doctor._check_agent_spec_metadata()
        inventory = next(
            check for check in checks if check["name"] == "spec_inventory_exact"
        )
        model_checks = [
            check for check in checks if check["name"].endswith("_model_policy")
        ]

        self.assertTrue(inventory["ok"], inventory)
        self.assertEqual(
            {
                "ambiguity-analyst",
                "experience-designer",
                "explore",
                "librarian",
                "oracle",
                "orchestrator",
                "plan-critic",
                "release-scribe",
                "reviewer",
                "strategic-planner",
                "tasker",
                "verifier",
            },
            set(inventory["actual"]),
        )
        self.assertEqual(12, len(model_checks))
        self.assertTrue(
            all(check["ok"] for check in model_checks),
            [check for check in model_checks if not check["ok"]],
        )


if __name__ == "__main__":
    unittest.main()
