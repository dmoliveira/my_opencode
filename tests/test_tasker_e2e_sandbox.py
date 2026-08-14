from __future__ import annotations

import json
import shutil
import subprocess
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
    def test_allows_single_scoped_codememory_write(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc add task "planned work" --scope sandbox --kind chore --priority P2 --format json'
        )

    def test_allows_exact_launcher_discovery_and_doctor_only(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command("command -v oc")
        tasker_e2e_sandbox.validate_tasker_shell_command("oc --help")
        tasker_e2e_sandbox.validate_tasker_shell_command(
            "oc config --doctor --format json"
        )
        for command in (
            "oc config --show --format json",
            "oc db check --full --format json",
            "oc plan doctor --format json",
        ):
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "unapproved"):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_allows_one_safe_sqlite_bootstrap_write(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            "oc db migrate --format json"
        )

    def test_rejects_unapproved_or_terminal_subcommands(self) -> None:
        commands = (
            "oc done task_1",
            "oc fail task_1 --why no",
            "oc transition task_1 done --reason no",
            "oc event done note --target task_1",
            "oc db backup --destination /tmp/db.sqlite3",
            "oc undo operation_1 --reason no",
            "oc redo operation_1 --reason no",
            "oc frobnicate task_1",
            "oc help",
            "oc -h",
            "oc history --help",
            "oc --unknown current",
            "oc --format json current",
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
                    AssertionError, "compound|chained|backend write|scope"
                ):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_multiple_or_chained_backend_writes(self) -> None:
        commands = (
            "oc add task first --scope sandbox && oc add task second --scope sandbox",
            "oc db migrate && oc add task title --scope sandbox",
        )
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "backend write|chained"):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_command_substitution(self) -> None:
        for command in ("oc get $(git rev-parse HEAD)", "oc get `whoami`"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "compound"):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_requires_scope_and_correct_entity_arguments(self) -> None:
        commands = (
            'oc add task "planned work" --kind chore',
            'oc add task "planned work" --scope sandbox --worktree /tmp/x',
            'oc add doc "brief" --scope sandbox --type brief',
            'oc add memory "note" --scope sandbox --body body',
            'oc add session "run" --scope sandbox --worktree /tmp/x --branch demo --task task_1',
        )
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaises(AssertionError):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_enforces_safe_planning_link_and_update_shapes(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            "oc link epic_1 parent-of task_1 --format json"
        )
        tasker_e2e_sandbox.validate_tasker_shell_command(
            "oc link task_2 depends-on task_1 --format json"
        )
        tasker_e2e_sandbox.validate_tasker_shell_command(
            "oc link memory_1 about epic_1 --format json"
        )
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc set task_1 summary "new summary" --reason "user requested" --expected-revision 3 --format json'
        )
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc cancel task_1 --why "user removed it" --expected-revision 1 --format json'
        )
        for command in (
            "oc link session_1 active-task task_1",
            "oc link session_1 captured memory_1",
            "oc link session_1 parent-of task_1",
            "oc link task_1 parent-of task_2",
            "oc link epic_1 about task_1",
            "oc link memory_1 about session_1",
            "oc link epic_1 parent-of task_1",
            "oc set task_1 status done --reason no",
            "oc set task_1 summary x --override anything --reason no",
            "oc set task_1 summary x --reason no",
            "oc cancel task_1",
            "oc cancel task_1 --why no",
        ):
            with self.subTest(command=command):
                with self.assertRaises(AssertionError):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_validates_exact_lookup_before_add(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="exact-lookup",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
        )
        valid = [
            'oc find "planned work" --type task --scope sandbox --format json',
            'oc add task "planned work" --scope sandbox --kind chore --format json',
        ]
        tasker_e2e_sandbox.validate_commands(scenario, valid)

        invalid = [
            'oc add task "planned work" --scope sandbox --kind chore --format json',
        ]
        with self.assertRaisesRegex(AssertionError, "exact typed JSON lookup"):
            tasker_e2e_sandbox.validate_commands(scenario, invalid)
        duplicate_link = [
            *valid,
            "oc link memory_1 about task_1 --format json",
            "oc link memory_1 about task_1 --format json",
        ]
        with self.assertRaisesRegex(AssertionError, "duplicate planning link"):
            tasker_e2e_sandbox.validate_commands(scenario, duplicate_link)
        scoped_scenario = tasker_e2e_sandbox.Scenario(
            name="scope-bound",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
            scope="sandbox",
        )
        with self.assertRaisesRegex(AssertionError, "outside scenario scope"):
            tasker_e2e_sandbox.validate_commands(
                scoped_scenario,
                [
                    'oc find "planned work" --type task --scope wrong --format json',
                    'oc add task "planned work" --scope sandbox --kind chore --format json',
                ],
            )

    def test_requires_safe_archive_restore_shapes_and_preview_before_apply(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc archive memory_1 --reason "obsolete note" --format json'
        )
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc restore doc_1 --reason "restore brief" --apply plan_token --format json'
        )
        for command in (
            "oc archive task_1 --reason no",
            "oc restore memory_1",
            "oc archive memory_1 --reason no --override referenced-record",
        ):
            with self.subTest(command=command):
                with self.assertRaises(AssertionError):
                    tasker_e2e_sandbox.validate_tasker_shell_command(command)

        scenario = tasker_e2e_sandbox.Scenario(
            name="archive-preview",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
        )
        base_add = [
            'oc find "planned work" --type task --scope sandbox --format json',
            'oc add task "planned work" --scope sandbox --kind chore --format json',
        ]
        tasker_e2e_sandbox.validate_commands(
            scenario,
            [
                *base_add,
                "oc get memory_1 --view full --format json",
                'oc archive memory_1 --reason "obsolete" --format json',
                'oc archive memory_1 --reason "obsolete" --apply plan_token --format json',
            ],
        )
        with self.assertRaisesRegex(AssertionError, "did not follow a preview"):
            tasker_e2e_sandbox.validate_commands(
                scenario,
                [
                    *base_add,
                    "oc get memory_1 --view full --format json",
                    'oc archive memory_1 --reason "obsolete" --apply plan_token --format json',
                ],
            )

    def test_requires_full_inspection_before_cancel_or_unlink(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="mutation-inspection",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
        )
        base_add = [
            'oc find "planned work" --type task --scope sandbox --format json',
            'oc add task "planned work" --scope sandbox --kind chore --format json',
        ]
        for command in (
            "oc cancel task_1 --why obsolete --expected-revision 1 --format json",
            "oc unlink link_1 --reason obsolete --format json",
        ):
            with self.subTest(command=command):
                with self.assertRaisesRegex(AssertionError, "did not inspect"):
                    tasker_e2e_sandbox.validate_commands(
                        scenario, [*base_add, command]
                    )
        tasker_e2e_sandbox.validate_commands(
            scenario,
            [
                *base_add,
                "oc get task_1 --view full --format json",
                "oc cancel task_1 --why obsolete --expected-revision 1 --format json",
            ],
        )
        tasker_e2e_sandbox.validate_commands(
            scenario,
            [
                *base_add,
                "oc get link_1 --view full --format json",
                "oc unlink link_1 --reason obsolete --format json",
            ],
        )

    def test_validates_bounded_read_only_research_delegation(self) -> None:
        allowed = [
            {
                "agent": "explore",
                "prompt": "Objective: map local patterns. Scoped ownership: agent files. Acceptance: cite paths. Required checks: read only. Evidence: file:line.",
            },
            {
                "agent": "librarian",
                "prompt": "Objective: verify upstream syntax. Scoped ownership: official docs. Acceptance: supported flags. Required checks: official sources only. Evidence: URL and quote.",
            },
        ]
        tasker_e2e_sandbox.validate_tasker_research_delegations(allowed)
        tasker_e2e_sandbox.validate_tasker_research_delegations(
            [
                {
                    "agent": "explore",
                    "prompt": "Objective: document OC syntax. Scoped ownership: docs. Acceptance: cite sources. Required checks: read only. Evidence: path and quote. Do not run any oc/codememory/git commands; only explain the documented `oc add` syntax.",
                }
            ]
        )
        tasker_e2e_sandbox.validate_tasker_research_delegations(
            [
                {
                    "agent": "explore",
                    "prompt": "Objective: inspect docs. Workspace root: repository. Scoped ownership: exactly two files. Hard constraints: do not run any oc/codememory/git commands. Return in your final message a quoted line number as evidence.",
                }
            ]
        )
        for invalid in (
            [*allowed, allowed[0]],
            [{"agent": "verifier", "prompt": allowed[0]["prompt"]}],
            [
                {
                    "agent": "explore",
                    "prompt": "Objective: implement the fix. Scope: files. Acceptance: done. Evidence: output.",
                }
            ],
            [
                {
                    "agent": "explore",
                    "prompt": "Objective: implement the fix with `oc add`. Scope: files. Acceptance: done. Evidence: output. Do not run oc commands.",
                }
            ],
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(AssertionError):
                    tasker_e2e_sandbox.validate_tasker_research_delegations(invalid)

    def test_requires_research_before_persistence_and_synthesis(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="research-order",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
            require_research=True,
        )
        research = {
            "type": "tool_use",
            "part": {
                "tool": "task",
                "state": {
                    "input": {
                        "subagent_type": "explore",
                        "prompt": "Objective: inspect docs. Scope: docs. Acceptance: cite. Evidence: paths. Do not run any oc/codememory/git commands.",
                    },
                    "output": "Research synthesis: docs inspected.",
                },
            },
        }
        write = {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {"input": {"command": "oc db migrate --format json"}},
            },
        }
        tasker_e2e_sandbox.validate_research_precedes_persistence(
            scenario, [research, write], "Research synthesis: docs confirmed the workflow."
        )
        with self.assertRaisesRegex(AssertionError, "persisted before"):
            tasker_e2e_sandbox.validate_research_precedes_persistence(
                scenario, [write, research], "Research synthesis: late."
            )
        with self.assertRaisesRegex(AssertionError, "omitted"):
            tasker_e2e_sandbox.validate_research_precedes_persistence(
                scenario, [research, write], "Created task_1."
            )
        pending_research = {
            **research,
            "part": {
                **research["part"],
                "state": {"input": research["part"]["state"]["input"]},
            },
        }
        with self.assertRaisesRegex(AssertionError, "delegation completed"):
            tasker_e2e_sandbox.validate_research_precedes_persistence(
                scenario,
                [pending_research, write],
                "Research synthesis: incomplete.",
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


class TaskerSandboxRuntimeTest(unittest.TestCase):
    def test_prepare_runtime_isolates_opencode_and_codememory(self) -> None:
        if shutil.which("oc") is None:
            self.skipTest("oc is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            config_home = Path(tmp)
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(config_home)
            tasker_path = config_home / "opencode" / "agent" / "tasker.md"
            explore_path = config_home / "opencode" / "agent" / "explore.md"
            librarian_path = config_home / "opencode" / "agent" / "librarian.md"
            config_path = config_home / "opencode" / "opencode.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            wrapper = Path(runtime_env["TASKER_E2E_OC_WRAPPER"])
            codememory_config = Path(runtime_env["TASKER_E2E_CODEMEMORY_CONFIG"])
            database = Path(runtime_env["TASKER_E2E_CODEMEMORY_DATABASE"])
            workspace = Path(runtime_env["TASKER_E2E_WORKSPACE"])

            self.assertTrue(tasker_path.is_symlink())
            self.assertEqual(REPO_ROOT / "agent" / "tasker.md", tasker_path.resolve())
            self.assertFalse(explore_path.is_symlink())
            self.assertFalse(librarian_path.is_symlink())
            self.assertIn(
                f"model: {tasker_e2e_sandbox.TASKER_MODEL}",
                explore_path.read_text(encoding="utf-8"),
            )
            self.assertIn(
                f"model: {tasker_e2e_sandbox.TASKER_MODEL}",
                librarian_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(str(config_home), runtime_env["XDG_CONFIG_HOME"])
            bash_permissions = config["permission"]["bash"]
            self.assertIsInstance(bash_permissions, dict)
            self.assertEqual("deny", bash_permissions["*"])
            self.assertNotIn("oc *", bash_permissions)
            self.assertEqual("allow", bash_permissions["oc config --doctor*"])
            self.assertEqual("allow", bash_permissions["oc db migrate*"])
            self.assertEqual("allow", bash_permissions["oc add task *"])
            self.assertEqual("allow", bash_permissions["oc archive memory_*"])
            self.assertEqual("deny", bash_permissions["oc init *"])
            self.assertTrue(config["agent"]["build"]["disable"])
            self.assertTrue(config["agent"]["general"]["disable"])
            self.assertEqual("allow", config["permission"]["task"])
            self.assertEqual("deny", config["permission"]["edit"])
            self.assertEqual("allow", config["permission"]["webfetch"])
            self.assertTrue(wrapper.is_file())
            self.assertTrue(codememory_config.is_file())
            self.assertFalse(database.exists())
            self.assertTrue((workspace / "docs").is_symlink())
            self.assertEqual(REPO_ROOT / "docs", (workspace / "docs").resolve())
            workspace_config = workspace / ".codememory" / "config.sqlite.yaml"
            self.assertTrue(workspace_config.is_file())
            self.assertFalse(workspace_config.is_symlink())
            self.assertEqual(
                codememory_config.read_text(encoding="utf-8"),
                workspace_config.read_text(encoding="utf-8"),
            )
            self.assertIn(str(wrapper.parent), runtime_env["PATH"].split(":"))
            self.assertIn(str(database), codememory_config.read_text(encoding="utf-8"))
            wrapper_text = wrapper.read_text(encoding="utf-8")
            self.assertIn("rejected unsafe Codememory command", wrapper_text)
            self.assertIn("safe_environment", wrapper_text)
            self.assertIn("RECOVERY_TOKENS", wrapper_text)
            self.assertIn('{"task", "epic", "memory", "doc"}', wrapper_text)
            self.assertEqual("1", runtime_env["TASKER_E2E_ISOLATED_ENV"])
            self.assertTrue(Path(runtime_env["TASKER_E2E_OPENCODE_BIN"]).is_file())

    def test_runtime_environment_strips_host_config_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(Path(tmp))
            observed = tasker_e2e_sandbox.run_process(
                [
                    sys.executable,
                    "-c",
                    "import os; print('|'.join(os.environ.get(name, '') for name in ('OPENCODE_CONFIG_PATH', 'OPENCODE_CONFIG_CONTENT', 'CODEMEMORY_SQLITE_PATH')))",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides={
                    **runtime_env,
                    "OPENCODE_CONFIG_PATH": "/tmp/host-opencode.json",
                    "OPENCODE_CONFIG_CONTENT": "{\"permission\":{\"bash\":\"allow\"}}",
                    "CODEMEMORY_SQLITE_PATH": "/tmp/host-codememory.sqlite3",
                },
            )
            self.assertEqual(0, observed.returncode, observed.stderr)
            self.assertEqual("||", observed.stdout.strip())

    def test_wrapper_blocks_config_escape_and_uses_disposable_database(self) -> None:
        if shutil.which("oc") is None:
            self.skipTest("oc is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            config_home = Path(tmp)
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(config_home)
            database = Path(runtime_env["TASKER_E2E_CODEMEMORY_DATABASE"])
            escaped_database = config_home / "escaped.sqlite3"
            migrated = tasker_e2e_sandbox.run_process(
                ["oc", "db", "migrate", "--format", "json"],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides={
                    **runtime_env,
                    "CODEMEMORY_SQLITE_PATH": str(escaped_database),
                    "DATABASE_URL": "sqlite:///should-not-be-used.sqlite3",
                },
            )
            self.assertEqual(0, migrated.returncode, migrated.stderr)
            self.assertTrue(database.is_file())
            self.assertFalse(escaped_database.exists())
            rejected = tasker_e2e_sandbox.run_process(
                ["oc", "--config", str(config_home / "escape.yaml"), "config", "--doctor"],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(64, rejected.returncode)
            self.assertIn("rejected unsafe", rejected.stderr)
            for command in (
                ["db", "backup", "--output", str(config_home / "backup.sqlite3")],
                ["db", "check", "--full"],
                ["plan", "doctor"],
                ["link", "task_1", "active-task", "task_2"],
                ["link", "session_1", "parent-of", "task_2"],
                ["link", "task_1", "parent-of", "task_2"],
                ["link", "epic_1", "about", "task_2"],
                ["link", "memory_1", "about", "session_1"],
                ["set", "task_1", "status", "done", "--reason", "unsafe"],
                ["set", "task_1", "summary", "safe", "--reason", "missing revision"],
                ["cancel", "task_1", "--why", "missing inspection"],
                ["unlink", "link_1", "--reason", "missing inspection"],
                ["archive", "memory_1"],
            ):
                with self.subTest(command=command):
                    forbidden = tasker_e2e_sandbox.run_process(
                        ["oc", *command],
                        cwd=REPO_ROOT,
                        timeout_ms=120000,
                        env_overrides=runtime_env,
                    )
                    self.assertEqual(64, forbidden.returncode)
                    self.assertIn("rejected unsafe", forbidden.stderr)

    def test_wrapper_binds_artifact_writes_to_the_scenario_scope(self) -> None:
        if shutil.which("oc") is None:
            self.skipTest("oc is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(
                Path(tmp), allowed_scope="approved-scope"
            )
            workspace = Path(runtime_env["TASKER_E2E_WORKSPACE"])
            migrated = tasker_e2e_sandbox.run_process(
                ["oc", "db", "migrate", "--format", "json"],
                cwd=workspace,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, migrated.returncode, migrated.stderr)
            for command in (
                ["find", "wrong", "--type", "task", "--scope", "wrong-scope", "--format", "json"],
                [
                    "add",
                    "task",
                    "wrong",
                    "--scope",
                    "wrong-scope",
                    "--kind",
                    "chore",
                    "--priority",
                    "P2",
                    "--format",
                    "json",
                ],
            ):
                with self.subTest(command=command):
                    rejected = tasker_e2e_sandbox.run_process(
                        ["oc", *command],
                        cwd=workspace,
                        timeout_ms=120000,
                        env_overrides=runtime_env,
                    )
                    self.assertEqual(64, rejected.returncode)
            accepted = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "add",
                    "task",
                    "approved",
                    "--scope",
                    "approved-scope",
                    "--kind",
                    "chore",
                    "--priority",
                    "P2",
                    "--format",
                    "json",
                ],
                cwd=workspace,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)

    def test_wrapper_requires_inspection_before_cancel_and_unlink(self) -> None:
        if shutil.which("oc") is None:
            self.skipTest("oc is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(Path(tmp))

            def run(*args: str) -> object:
                result = tasker_e2e_sandbox.run_process(
                    ["oc", *args],
                    cwd=Path(runtime_env["TASKER_E2E_WORKSPACE"]),
                    timeout_ms=120000,
                    env_overrides=runtime_env,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                return json.loads(result.stdout)

            run("db", "migrate", "--format", "json")
            task = run(
                "add",
                "task",
                "cancel inspection task",
                "--scope",
                "inspection",
                "--kind",
                "chore",
                "--priority",
                "P2",
                "--format",
                "json",
            )
            memory = run(
                "add",
                "memory",
                "unlink inspection note",
                "--scope",
                "inspection",
                "--kind",
                "note",
                "--body",
                "temporary",
                "--label",
                "planning",
                "--format",
                "json",
            )
            link = run(
                "link",
                str(memory["id"]),
                "about",
                str(task["id"]),
                "--format",
                "json",
            )
            run("get", str(memory["id"]), "--view", "full", "--format", "json")
            for command in (
                [
                    "link",
                    str(memory["id"]),
                    "about",
                    str(task["id"]),
                    "--format",
                    "json",
                ],
                [
                    "archive",
                    str(memory["id"]),
                    "--reason",
                    "still referenced",
                    "--format",
                    "json",
                ],
            ):
                with self.subTest(command=command):
                    blocked = tasker_e2e_sandbox.run_process(
                        ["oc", *command],
                        cwd=Path(runtime_env["TASKER_E2E_WORKSPACE"]),
                        timeout_ms=120000,
                        env_overrides=runtime_env,
                    )
                    self.assertEqual(64, blocked.returncode)
            for command in (
                ["cancel", str(task["id"]), "--why", "missing inspection"],
                ["unlink", str(link["id"]), "--reason", "missing inspection"],
            ):
                with self.subTest(command=command):
                    blocked = tasker_e2e_sandbox.run_process(
                        ["oc", *command],
                        cwd=Path(runtime_env["TASKER_E2E_WORKSPACE"]),
                        timeout_ms=120000,
                        env_overrides=runtime_env,
                    )
                    self.assertEqual(64, blocked.returncode)

            run("get", str(task["id"]), "--view", "full", "--format", "json")
            stale_cancel = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "cancel",
                    str(task["id"]),
                    "--why",
                    "stale revision",
                    "--expected-revision",
                    "2",
                    "--format",
                    "json",
                ],
                cwd=Path(runtime_env["TASKER_E2E_WORKSPACE"]),
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(64, stale_cancel.returncode)
            inspections_path = Path(runtime_env["TASKER_E2E_RECORD_INSPECTIONS"])
            inspections = json.loads(inspections_path.read_text(encoding="utf-8"))
            inspections[str(task["id"])]["claimed_by_active_session"] = True
            inspections_path.write_text(json.dumps(inspections), encoding="utf-8")
            claimed_cancel = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "cancel",
                    str(task["id"]),
                    "--why",
                    "claimed task",
                    "--expected-revision",
                    "1",
                    "--format",
                    "json",
                ],
                cwd=Path(runtime_env["TASKER_E2E_WORKSPACE"]),
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(64, claimed_cancel.returncode)
            inspections[str(task["id"])].pop("claimed_by_active_session")
            inspections_path.write_text(json.dumps(inspections), encoding="utf-8")
            run(
                "cancel",
                str(task["id"]),
                "--why",
                "temporary removal",
                "--expected-revision",
                "1",
                "--format",
                "json",
            )
            run("get", str(link["id"]), "--view", "full", "--format", "json")
            run("unlink", str(link["id"]), "--reason", "temporary removal", "--format", "json")

    def test_wrapper_requires_one_time_recovery_approval(self) -> None:
        if shutil.which("oc") is None:
            self.skipTest("oc is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(Path(tmp))
            approvals = Path(runtime_env["TASKER_E2E_RECOVERY_APPROVALS"])
            migrated = tasker_e2e_sandbox.run_process(
                ["oc", "db", "migrate", "--format", "json"],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, migrated.returncode, migrated.stderr)
            created = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "add",
                    "memory",
                    "recovery approval note",
                    "--scope",
                    "recovery-approval",
                    "--kind",
                    "note",
                    "--body",
                    "temporary",
                    "--label",
                    "planning",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, created.returncode, created.stderr)
            memory_id = json.loads(created.stdout)["id"]
            inspected = tasker_e2e_sandbox.run_process(
                ["oc", "get", memory_id, "--view", "full", "--format", "json"],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, inspected.returncode, inspected.stderr)
            unapproved_apply = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "archive",
                    memory_id,
                    "--reason",
                    "temporary",
                    "--apply",
                    "unknown",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(64, unapproved_apply.returncode)
            self.assertFalse(approvals.exists())
            preview = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "archive",
                    memory_id,
                    "--reason",
                    "temporary",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, preview.returncode, preview.stderr)
            plan_hash = json.loads(preview.stdout)["plan_hash"]
            self.assertTrue(approvals.is_file())
            applied = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "archive",
                    memory_id,
                    "--reason",
                    "temporary",
                    "--apply",
                    plan_hash,
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, applied.returncode, applied.stderr)
            replay = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "archive",
                    memory_id,
                    "--reason",
                    "temporary",
                    "--apply",
                    plan_hash,
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(64, replay.returncode)
            restored_preview = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "restore",
                    memory_id,
                    "--reason",
                    "temporary",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, restored_preview.returncode, restored_preview.stderr)
            restore_hash = json.loads(restored_preview.stdout)["plan_hash"]
            restored = tasker_e2e_sandbox.run_process(
                [
                    "oc",
                    "restore",
                    memory_id,
                    "--reason",
                    "temporary",
                    "--apply",
                    restore_hash,
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, restored.returncode, restored.stderr)

    def test_installed_oc_supports_documented_tasker_commands(self) -> None:
        if shutil.which("oc") is None:
            self.skipTest("oc is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(Path(tmp))
            real_oc = runtime_env["TASKER_E2E_REAL_OC"]
            for command, required_text in (
                (["history", "--help"], "Usage: codememory history"),
                (["unlink", "--help"], "--reason <REASON>"),
                (["archive", "--help"], "--apply <APPLY>"),
                (["restore", "--help"], "--apply <APPLY>"),
                (["set", "--help"], "--reason <REASON>"),
            ):
                with self.subTest(command=command):
                    result = tasker_e2e_sandbox.run_process(
                        [real_oc, *command],
                        cwd=REPO_ROOT,
                        timeout_ms=120000,
                        env_overrides=runtime_env,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn(required_text, result.stdout)


class TaskerScenarioRunTest(unittest.TestCase):
    def test_duplicate_mode_validates_every_run_before_returning(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="duplicate",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
            mode="duplicate",
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime_env = {
                "TASKER_E2E_WORKSPACE": tmp,
                "TASKER_E2E_OPENCODE_BIN": "/bin/true",
            }
            results = [
                {"name": "duplicate", "resolved_ids": {"task": "task_1"}},
                {"name": "duplicate", "resolved_ids": {"task": "task_1"}},
            ]
            with (
                patch.object(
                    tasker_e2e_sandbox,
                    "run_process",
                    side_effect=[
                        subprocess.CompletedProcess([], 0, stdout="first", stderr=""),
                        subprocess.CompletedProcess([], 0, stdout="second", stderr=""),
                    ],
                ) as run_process,
                patch.object(
                    tasker_e2e_sandbox,
                    "parse_events",
                    side_effect=[[], []],
                ),
                patch.object(
                    tasker_e2e_sandbox,
                    "validate_scenario",
                    side_effect=results,
                ) as validate_scenario,
            ):
                outcome = tasker_e2e_sandbox.run_scenario(
                    scenario, timeout_ms=1000, runtime_env=runtime_env
                )

        self.assertEqual(2, run_process.call_count)
        self.assertEqual(2, validate_scenario.call_count)
        self.assertEqual(2, outcome["validated_runs"])

    def test_duplicate_mode_stops_when_first_run_fails_validation(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="duplicate",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
            mode="duplicate",
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime_env = {
                "TASKER_E2E_WORKSPACE": tmp,
                "TASKER_E2E_OPENCODE_BIN": "/bin/true",
            }
            with (
                patch.object(
                    tasker_e2e_sandbox,
                    "run_process",
                    return_value=subprocess.CompletedProcess(
                        [], 0, stdout="first", stderr=""
                    ),
                ) as run_process,
                patch.object(tasker_e2e_sandbox, "parse_events", return_value=[]),
                patch.object(
                    tasker_e2e_sandbox,
                    "validate_scenario",
                    side_effect=AssertionError("first-run violation"),
                ),
            ):
                with self.assertRaisesRegex(AssertionError, "first-run violation"):
                    tasker_e2e_sandbox.run_scenario(
                        scenario, timeout_ms=1000, runtime_env=runtime_env
                    )

        self.assertEqual(1, run_process.call_count)

    def test_repository_snapshot_detects_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".codememory"
            root.mkdir()
            config = root / "config.sqlite.yaml"
            config.write_text("version: 1\n", encoding="utf-8")
            before = tasker_e2e_sandbox.snapshot_tree(root)
            self.assertEqual(before, tasker_e2e_sandbox.snapshot_tree(root))
            config.write_text("version: 2\n", encoding="utf-8")
            self.assertNotEqual(before, tasker_e2e_sandbox.snapshot_tree(root))


if __name__ == "__main__":
    unittest.main()
