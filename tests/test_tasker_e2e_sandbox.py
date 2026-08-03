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

import tasker_e2e_sandbox


class TaskerShellBoundaryTest(unittest.TestCase):
    def test_allows_single_codememory_command(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc add task "planned work" --kind chore --priority P2 --format json'
        )

    def test_allows_exact_launcher_discovery(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command("command -v oc")

    def test_allows_chained_read_only_health_checks(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            "command -v oc && oc config --doctor"
        )

    def test_allows_chained_read_only_help_checks(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            "oc add task --help && oc add memory --help && oc link --help"
        )

    def test_rejects_unapproved_or_mutating_subcommands(self) -> None:
        commands = (
            "oc done task_1",
            "oc cancel task_1",
            "oc fail task_1",
            "oc event done note --target task_1",
            "oc frobnicate task_1",
            "oc done task_1 && oc cancel task_2",
        )
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "unapproved"):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_non_codememory_commands(self) -> None:
        for command in ("git status", "gh pr list", "python3 helper.py", "make test"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "non-Codememory"):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_allows_single_write_with_global_options(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc --format json add task "planned work" --kind chore --priority P2'
        )

    def test_rejects_chaining_pipes_redirects_and_newlines(self) -> None:
        commands = (
            "oc find task && oc add task title",
            "oc list task | grep title",
            "oc list task > result.json",
            "oc find task; oc add task title",
            "oc find task\noc add task title",
        )
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaisesRegex(
                    AssertionError, "compound|chained|backend write"
                ):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_multiple_or_chained_backend_writes(self) -> None:
        commands = (
            "oc add task first && oc add task second",
            "oc --format json find task && oc --format json add task title",
        )
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "backend write"):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_command_substitution(self) -> None:
        for command in ("oc get $(git rev-parse HEAD)", "oc get `whoami`"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "compound"):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_refusal_allows_planning_write_with_execution_words_in_data(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="refusal",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
            mode="refusal",
        )
        tasker_e2e_sandbox.validate_commands(
            scenario,
            [
                'oc add task "Docs" --summary "Do not run git, tests, or PR creation"'
            ],
        )

    def test_links_for_resolves_current_link_records(self) -> None:
        responses = [
            {"id": "task_1", "scope_key": "sandbox"},
            {"items": [{"id": "link_1"}, {"id": "link_2"}]},
            {
                "id": "link_1",
                "from_id": "memory_1",
                "edge_type": "about",
                "to_id": "task_1",
            },
            {
                "id": "link_2",
                "from_id": "task_1",
                "edge_type": "depends-on",
                "to_id": "task_2",
            },
        ]
        with patch.object(
            tasker_e2e_sandbox, "oc_json", side_effect=responses
        ) as oc_json:
            links = tasker_e2e_sandbox.links_for("task_1")

        self.assertEqual(
            {
                ("incoming", "about", "memory_1"),
                ("outgoing", "depends-on", "task_2"),
            },
            links,
        )
        self.assertEqual(4, oc_json.call_count)

    def test_prepare_runtime_uses_worktree_tasker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_home = Path(tmp)
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(config_home)
            tasker_path = config_home / "opencode" / "agent" / "tasker.md"
            config_path = config_home / "opencode" / "opencode.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertTrue(tasker_path.is_symlink())
            self.assertEqual(REPO_ROOT / "agent" / "tasker.md", tasker_path.resolve())
            self.assertEqual(str(config_home), runtime_env["XDG_CONFIG_HOME"])
            self.assertEqual("allow", config["permission"]["bash"])
            self.assertEqual("deny", config["permission"]["edit"])


if __name__ == "__main__":
    unittest.main()
