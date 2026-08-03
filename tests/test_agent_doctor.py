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
        self.assertLessEqual(
            agent_doctor.count_prompt_words(body),
            int(agent_doctor.ORCHESTRATOR_BODY_WORD_BASELINE * 0.70),
        )


if __name__ == "__main__":
    unittest.main()
