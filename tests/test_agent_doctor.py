from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import agent_doctor
import build_agents


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


class AgentDoctorTaskerPromptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = REPO_ROOT / "agent" / "specs" / "tasker.json"
        self.spec = json.loads(self.path.read_text(encoding="utf-8"))
        self.body = self.spec["body_template"]

    def test_tasker_budget_and_contract(self) -> None:
        checks = agent_doctor._check_tasker_prompt_contract(self.spec, self.path)
        word_count = agent_doctor.count_prompt_words(self.body)

        self.assertTrue(
            all(check["ok"] for check in checks),
            [check for check in checks if not check["ok"]],
        )
        self.assertLessEqual(word_count, agent_doctor.TASKER_BODY_WORD_LIMIT)
        self.assertLessEqual(
            word_count,
            int(agent_doctor.TASKER_BODY_WORD_BASELINE * 0.75),
        )

    def test_tasker_budget_boundary(self) -> None:
        at_limit = agent_doctor.prompt_body_budget_check(
            "tasker",
            "word " * agent_doctor.TASKER_BODY_WORD_LIMIT,
            baseline=agent_doctor.TASKER_BODY_WORD_BASELINE,
            limit=agent_doctor.TASKER_BODY_WORD_LIMIT,
            path=self.path,
        )
        over_limit = agent_doctor.prompt_body_budget_check(
            "tasker",
            "word " * (agent_doctor.TASKER_BODY_WORD_LIMIT + 1),
            baseline=agent_doctor.TASKER_BODY_WORD_BASELINE,
            limit=agent_doctor.TASKER_BODY_WORD_LIMIT,
            path=self.path,
        )

        self.assertTrue(at_limit["ok"])
        self.assertFalse(over_limit["ok"])

    def test_tasker_contract_rejects_each_missing_marker(self) -> None:
        for marker in agent_doctor.TASKER_TEMPLATE_CONTRACT_MARKERS:
            with self.subTest(marker=marker):
                mutated = dict(self.spec)
                mutated["body_template"] = self.body.replace(marker, "")
                checks = agent_doctor._check_tasker_prompt_contract(
                    mutated, self.path
                )
                self.assertTrue(
                    any(
                        not check["ok"]
                        and check["reason"] == f"missing marker: {marker}"
                        for check in checks
                    ),
                    marker,
                )

    def test_tasker_contract_rejects_missing_body(self) -> None:
        checks = agent_doctor._check_tasker_prompt_contract(
            {"name": "tasker", "body_template": ""}, self.path
        )

        self.assertEqual(1, len(checks))
        self.assertFalse(checks[0]["ok"])
        self.assertIn("non-empty string", checks[0]["reason"])

    def test_tasker_stays_unpinned_on_writing_model(self) -> None:
        categories = agent_doctor.load_routing_categories()
        policy = agent_doctor.agent_model_policy_check(
            self.spec, categories, self.path
        )
        generated = (REPO_ROOT / "agent" / "tasker.md").read_text(encoding="utf-8")
        generated_header = generated.split("---", 2)[1]

        self.assertNotIn("model", self.spec)
        self.assertEqual("writing", policy["category"])
        self.assertTrue(policy["inherits_category"])
        self.assertEqual("openai/gpt-5.6-terra", policy["effective_model"])
        self.assertFalse(
            any(line.startswith("model:") for line in generated_header.splitlines())
        )


class AgentDoctorModelPolicyTest(unittest.TestCase):
    ROUTING_CATEGORIES = {
        "balanced": {"model": "openai/gpt-5.6-terra"},
        "writing": {"model": "openai/gpt-5.6-terra"},
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
        self.assertEqual("openai/gpt-5.6-terra", check["effective_model"])

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


class BuildAgentsCheckTest(unittest.TestCase):
    def write_spec(self, specs_dir: Path) -> None:
        (specs_dir / "source-name.json").write_text(
            json.dumps(
                {
                    "name": "rendered-name",
                    "mode": "subagent",
                    "description_template": "A test agent.",
                    "tools": {"read": True},
                    "body_template": "Return concise evidence.",
                }
            ),
            encoding="utf-8",
        )

    def test_check_detects_orphan_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            specs_dir = root / "specs"
            output_dir = root / "agent"
            specs_dir.mkdir()
            output_dir.mkdir()
            self.write_spec(specs_dir)
            orphan = output_dir / "orphan.md"
            orphan.write_text(
                f"{build_agents.GENERATED_AGENT_MARKER_PREFIX}orphan.json -->\nstale",
                encoding="utf-8",
            )

            with patch.object(build_agents, "SPEC_DIR", specs_dir), patch.object(
                build_agents, "OUTPUT_DIR", output_dir
            ):
                self.assertEqual(0, build_agents.build_agents("balanced"))
                self.assertEqual(
                    1, build_agents.build_agents("balanced", check_only=True)
                )
                self.assertTrue(orphan.exists())
                manual = output_dir / "README.md"
                manual.write_text("manual agent documentation", encoding="utf-8")
                self.assertEqual(
                    0, build_agents.build_agents("balanced", prune_stale=True)
                )

            self.assertFalse(orphan.exists())
            self.assertTrue(manual.exists())

    def test_check_uses_rendered_spec_name_for_expected_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            specs_dir = root / "specs"
            output_dir = root / "agent"
            specs_dir.mkdir()
            output_dir.mkdir()
            self.write_spec(specs_dir)

            with patch.object(build_agents, "SPEC_DIR", specs_dir), patch.object(
                build_agents, "OUTPUT_DIR", output_dir
            ):
                self.assertEqual(0, build_agents.build_agents("balanced"))
                self.assertTrue((output_dir / "rendered-name.md").exists())
                self.assertFalse((output_dir / "source-name.md").exists())
                self.assertEqual(
                    0, build_agents.build_agents("balanced", check_only=True)
                )


if __name__ == "__main__":
    unittest.main()
