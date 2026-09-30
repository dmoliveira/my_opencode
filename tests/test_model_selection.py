from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ModelSelectionTest(unittest.TestCase):
    def _config(self) -> dict:
        return json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))

    def _spec(self, name: str) -> dict:
        return json.loads(
            (REPO_ROOT / "agent" / "specs" / f"{name}.json").read_text(
                encoding="utf-8"
            )
        )

    def test_gpt6_model_entries_have_exact_reasoning_variants(self) -> None:
        expected_models = {
            "gpt-6-luna": {
                "name": "GPT-6 Luna",
                "reasoning": True,
                "variants": {
                    "none": {"reasoningEffort": "none"},
                    "low": {"reasoningEffort": "low"},
                    "medium": {"reasoningEffort": "medium"},
                    "high": {"reasoningEffort": "high"},
                    "xhigh": {"reasoningEffort": "xhigh"},
                    "max": {"reasoningEffort": "max"},
                },
            },
            "gpt-6.1-sol": {
                "name": "GPT-6.1 Sol",
                "reasoning": True,
                "variants": {
                    "low": {"reasoningEffort": "low"},
                    "medium": {"reasoningEffort": "medium"},
                    "high": {"reasoningEffort": "high"},
                    "xhigh": {"reasoningEffort": "xhigh"},
                    "max": {"reasoningEffort": "max"},
                },
            },
        }

        models = self._config()["provider"]["openai"]["models"]
        self.assertEqual(
            expected_models,
            {model_id: models[model_id] for model_id in expected_models},
        )

    def test_eight_routed_specs_use_gpt6_models(self) -> None:
        expected_assignments = {
            "explore": "openai/gpt-6-luna",
            "verifier": "openai/gpt-6-luna",
            "release-scribe": "openai/gpt-6-luna",
            "strategic-planner": "openai/gpt-6.1-sol",
            "ambiguity-analyst": "openai/gpt-6.1-sol",
            "reviewer": "openai/gpt-6.1-sol",
            "oracle": "openai/gpt-6.1-sol",
            "plan-critic": "openai/gpt-6.1-sol",
        }

        actual_assignments = {
            name: self._spec(name)["model"] for name in expected_assignments
        }
        self.assertEqual(expected_assignments, actual_assignments)


if __name__ == "__main__":
    unittest.main()
