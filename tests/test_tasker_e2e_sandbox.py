from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import tasker_e2e_sandbox
import tasker_production_live_smoke
from opencode_version_probe import OpenCodeVersionProbeError


class TaskerLaunchVersionTest(unittest.TestCase):
    def test_only_explicit_v1_version_passes_for_selected_executable(self) -> None:
        selected = ("/fixture/oc", "/fixture/selected-opencode")
        for version in ("1.18.18", "opencode v1.18.18", "1.2.3-rc.1"):
            with (
                self.subTest(version=version),
                patch.object(
                    tasker_e2e_sandbox, "resolve_tasker_launcher", side_effect=selected
                ),
                patch.object(
                    tasker_e2e_sandbox, "probe_opencode_version", return_value=version
                ) as probe,
            ):
                self.assertEqual(
                    selected, tasker_e2e_sandbox.resolve_tasker_launchers()
                )
                probe.assert_called_once_with(selected[1])

        for version in (
            "2.2.5", "3.0.0", "0.9.0", "unknown", "1.18",
            "prefix 1.18.18", "1.18.18 trailing", "SECRET_CANARY",
        ):
            with (
                self.subTest(version=version),
                patch.object(
                    tasker_e2e_sandbox, "resolve_tasker_launcher", side_effect=selected
                ),
                patch.object(
                    tasker_e2e_sandbox, "probe_opencode_version", return_value=version
                ),
                self.assertRaisesRegex(RuntimeError, "verified OpenCode V1"),
            ):
                tasker_e2e_sandbox.resolve_tasker_launchers()

    def test_probe_failure_is_refused_without_leaking_diagnostics(self) -> None:
        with (
            patch.object(
                tasker_e2e_sandbox, "resolve_tasker_launcher",
                side_effect=("/fixture/oc", "/fixture/opencode"),
            ),
            patch.object(
                tasker_e2e_sandbox, "probe_opencode_version",
                side_effect=OpenCodeVersionProbeError("SECRET_CANARY"),
            ),
            self.assertRaises(RuntimeError) as caught,
        ):
            tasker_e2e_sandbox.resolve_tasker_launchers()
        self.assertNotIn("SECRET_CANARY", str(caught.exception))

    def test_e2e_entrypoint_refuses_before_creating_any_fixture(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                tasker_e2e_sandbox, "resolve_tasker_launcher",
                side_effect=("/fixture/oc", "/fixture/opencode"),
            ),
            patch.object(
                tasker_e2e_sandbox, "probe_opencode_version", return_value="2.2.5"
            ),
            patch.object(tasker_e2e_sandbox, "snapshot_tree", return_value={}),
            patch.object(
                tasker_e2e_sandbox.tempfile, "TemporaryDirectory",
                side_effect=AssertionError("unexpected fixture creation"),
            ) as temporary,
            patch.object(tasker_e2e_sandbox, "prepare_tasker_runtime") as prepare,
            patch.object(tasker_e2e_sandbox, "initialize_tasker_runtime") as initialize,
            redirect_stdout(output),
        ):
            result = tasker_e2e_sandbox.main(["--runs", "1", "--json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(1, result)
        self.assertEqual("FAIL", payload["result"])
        self.assertEqual(
            ["runtime-isolation"], [item["name"] for item in payload["failures"]]
        )
        self.assertIn("verified OpenCode V1", payload["failures"][0]["error"])
        self.assertFalse(payload["temporary_root_created"])
        self.assertFalse(payload["temporary_root_removed"])
        self.assertFalse(payload["disposable_database_created"])
        temporary.assert_not_called()
        prepare.assert_not_called()
        initialize.assert_not_called()

    def test_production_entrypoint_refuses_before_snapshot_or_fixture(self) -> None:
        with (
            patch.object(
                tasker_e2e_sandbox, "resolve_tasker_launcher",
                side_effect=("/fixture/oc", "/fixture/opencode"),
            ),
            patch.object(
                tasker_e2e_sandbox, "probe_opencode_version", return_value="2.2.5"
            ),
            patch.object(
                tasker_e2e_sandbox, "snapshot_tree",
                side_effect=AssertionError("unexpected snapshot"),
            ) as snapshot,
            patch.object(
                tasker_production_live_smoke, "TemporaryDirectory",
                side_effect=AssertionError("unexpected fixture creation"),
            ) as temporary,
            self.assertRaisesRegex(RuntimeError, "verified OpenCode V1"),
        ):
            tasker_production_live_smoke.run(1000)
        snapshot.assert_not_called()
        temporary.assert_not_called()

    def test_failure_after_fixture_creation_still_checks_cleanup(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                tasker_e2e_sandbox, "resolve_tasker_launcher",
                side_effect=("/fixture/oc", "/fixture/opencode"),
            ),
            patch.object(
                tasker_e2e_sandbox, "probe_opencode_version", return_value="1.18.18"
            ),
            patch.object(tasker_e2e_sandbox, "snapshot_tree", return_value={}),
            patch.object(
                tasker_e2e_sandbox, "prepare_tasker_runtime",
                side_effect=RuntimeError("fixture failed"),
            ),
            redirect_stdout(output),
        ):
            result = tasker_e2e_sandbox.main(["--runs", "1", "--json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(1, result)
        self.assertTrue(payload["temporary_root_created"])
        self.assertTrue(payload["temporary_root_removed"])
        self.assertEqual(
            ["runtime-isolation", "disposable-codememory-store"],
            [item["name"] for item in payload["failures"]],
        )

    def test_failed_fixture_cleanup_remains_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            fixture = Path(parent) / "fixture"
            fixture.mkdir()
            output = io.StringIO()
            with (
                patch.object(
                    tasker_e2e_sandbox, "resolve_tasker_launcher",
                    side_effect=("/fixture/oc", "/fixture/opencode"),
                ),
                patch.object(
                    tasker_e2e_sandbox, "probe_opencode_version", return_value="1.18.18"
                ),
                patch.object(tasker_e2e_sandbox, "snapshot_tree", return_value={}),
                patch.object(tasker_e2e_sandbox.tempfile, "TemporaryDirectory") as temporary,
                patch.object(
                    tasker_e2e_sandbox, "prepare_tasker_runtime",
                    side_effect=RuntimeError("fixture failed"),
                ),
                redirect_stdout(output),
            ):
                temporary.return_value.__enter__.return_value = str(fixture)
                temporary.return_value.__exit__.return_value = False
                result = tasker_e2e_sandbox.main(["--runs", "1", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(1, result)
            self.assertTrue(payload["temporary_root_created"])
            self.assertFalse(payload["temporary_root_removed"])
            self.assertIn(
                "temporary-root-cleanup", [item["name"] for item in payload["failures"]]
            )


@unittest.skipUnless(os.name == "posix", "fixture launchers require POSIX")
class TaskerLaunchVersionCliTest(unittest.TestCase):
    def test_both_entrypoints_reject_v2_without_launching_a_fixture(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tasker-v2-launch-test-") as raw:
            root = Path(raw)
            binary_dir = root / "bin"
            home = root / "home"
            temporary = root / "tmp"
            for directory in (binary_dir, home, temporary):
                directory.mkdir()
            sentinel = home / "runtime-sentinel"
            sentinel.write_text("owned runtime sentinel\n", encoding="utf-8")
            calls = root / "opencode-calls"
            unexpected = root / "unexpected-run"
            oc_called = root / "oc-called"
            opencode = binary_dir / "opencode"
            opencode.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {shlex.quote(str(calls))}\n"
                "if [ \"$#\" = 1 ] && [ \"$1\" = --version ]; then\n"
                "  printf '%s\\n' 'opencode v2.2.5'\n"
                "  exit 0\n"
                "fi\n"
                f"printf called > {shlex.quote(str(unexpected))}\n"
                "exit 97\n",
                encoding="utf-8",
            )
            opencode.chmod(0o700)
            oc = binary_dir / "oc"
            oc.write_text(
                f"#!/bin/sh\nprintf called > {shlex.quote(str(oc_called))}\nexit 97\n",
                encoding="utf-8",
            )
            oc.chmod(0o700)
            env = {
                "HOME": str(home),
                "PATH": f"{binary_dir}{os.pathsep}{os.defpath}",
                "TMPDIR": str(temporary),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "CI": "true",
            }
            for name, args in (
                ("tasker_e2e_sandbox.py", ["--runs", "1", "--json"]),
                ("tasker_production_live_smoke.py", ["--json"]),
            ):
                with self.subTest(entrypoint=name):
                    result = subprocess.run(
                        [sys.executable, str(SCRIPTS_DIR / name), *args],
                        cwd=root,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    payload = json.loads(result.stdout)
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual("FAIL", payload["result"])
                    self.assertIn("verified OpenCode V1", json.dumps(payload))
                    if name == "tasker_e2e_sandbox.py":
                        self.assertFalse(payload["temporary_root_created"])
                        self.assertFalse(payload["disposable_database_created"])
                        self.assertEqual(
                            ["runtime-isolation"],
                            [item["name"] for item in payload["failures"]],
                        )
            self.assertEqual(["--version", "--version"], calls.read_text().splitlines())
            self.assertFalse(unexpected.exists())
            self.assertFalse(oc_called.exists())
            self.assertEqual("owned runtime sentinel\n", sentinel.read_text())


class TaskerEventEvidenceTest(unittest.TestCase):
    SESSION = "ses_fixture"

    def event(self, kind: str, **part: object) -> dict:
        part_type = {
            "step_start": "step-start",
            "step_finish": "step-finish",
            "tool_use": "tool",
            "text": "text",
        }.get(kind, kind)
        return {
            "type": kind,
            "sessionID": self.SESSION,
            "part": {
                "type": part_type,
                "sessionID": self.SESSION,
                "messageID": "msg_fixture",
                **part,
            },
        }

    def tool(self, name: str, command: object = "oc current --format json") -> dict:
        return self.event(
            "tool_use",
            tool=name,
            state={
                "status": "completed",
                "input": {"command": command},
                "output": "{}",
            },
        )

    def trace(self, *body: dict, reason: str = "stop") -> list[dict]:
        if any(event.get("type") == "tool_use" for event in body):
            return [
                self.event("step_start"),
                *body,
                self.event("step_finish", reason="tool-calls"),
                self.event("step_start"),
                self.event("text", text="Planning-only; did not execute."),
                self.event("step_finish", reason=reason),
            ]
        return [
            self.event("step_start"),
            *body,
            self.event("text", text="Planning-only; did not execute."),
            self.event("step_finish", reason=reason),
        ]

    def refusal(self) -> tasker_e2e_sandbox.Scenario:
        return tasker_e2e_sandbox.Scenario(
            name="synthetic-refusal",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
            mode="refusal",
        )

    def test_json_lines_require_complete_unambiguous_objects(self) -> None:
        invalid = (
            "",
            "  \n",
            "not json\n",
            "null\n",
            "[]\n",
            "1\n",
            '{"type":"text"}\n{"type":',
            '{"type":"text","type":"tool_use"}\n',
            '{"type":"tool_use","part":{"tool":"bash","tool":"shell"}}\n',
            '{"type":"text","value":NaN}\n',
        )
        for stdout in invalid:
            with (
                self.subTest(stdout=stdout),
                self.assertRaises(AssertionError),
            ):
                tasker_e2e_sandbox.parse_events(stdout)

    def test_json_lines_accept_valid_events_and_blank_lines(self) -> None:
        events = self.trace(self.tool("bash"))
        stdout = "\n" + "\n".join(json.dumps(event) for event in events) + "\n\n"
        self.assertEqual(events, tasker_e2e_sandbox.parse_events(stdout))

    def test_v1_bash_and_v2_shell_are_examined(self) -> None:
        for name in ("bash", "shell"):
            with self.subTest(name=name):
                events = self.trace(self.tool(name))
                self.assertEqual(
                    ["oc current --format json"],
                    tasker_e2e_sandbox.extract_commands(events),
                )
                self.assertEqual(
                    [],
                    tasker_e2e_sandbox.validate_scenario(self.refusal(), events)[
                        "warnings"
                    ],
                )
                unsafe = self.trace(self.tool(name, "git push"))
                with self.assertRaisesRegex(AssertionError, "non-Codememory"):
                    tasker_e2e_sandbox.validate_scenario(self.refusal(), unsafe)

    def test_positive_v1_scenario_still_checks_planning_commands(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="positive",
            prompt="planning only",
            expected_titles={},
            expected_edges=[],
        )
        command = 'oc add task "example" --scope sandbox --worktree /tmp/worktree --branch sandbox/tasker'
        outcome = tasker_e2e_sandbox.validate_scenario(
            scenario, self.trace(self.tool("bash", command))
        )
        self.assertEqual("positive", outcome["name"])

    def test_refusal_without_tool_calls_accepts_complete_final_text(self) -> None:
        self.assertEqual(
            [],
            tasker_e2e_sandbox.validate_scenario(self.refusal(), self.trace())[
                "warnings"
            ],
        )

    def test_rejects_unsupported_or_unexamined_tools(self) -> None:
        for name in ("unknown", "write", "edit", "task", "subagent", "", None, []):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                tasker_e2e_sandbox.validate_scenario(
                    self.refusal(), self.trace(self.tool(name))
                )

    def test_accepts_known_read_only_tool_evidence(self) -> None:
        for name in ("read", "list", "glob", "grep"):
            with self.subTest(name=name):
                tasker_e2e_sandbox.validate_scenario(
                    self.refusal(), self.trace(self.tool(name))
                )

    def test_rejects_missing_or_malformed_tool_state(self) -> None:
        parts = (
            {},
            {"tool": "shell"},
            {"tool": "shell", "state": None},
            {"tool": "shell", "state": {"status": "completed", "input": {}}},
            {
                "tool": "shell",
                "state": {"status": "completed", "input": {"command": 12}},
            },
            {
                "tool": "shell",
                "state": {
                    "status": "completed",
                    "input": {"command": ""},
                    "output": "",
                },
            },
            {
                "tool": "shell",
                "state": {"status": "running", "input": {"command": "oc current"}},
            },
            {
                "tool": "read",
                "state": {"status": "completed", "input": None, "output": ""},
            },
            {
                "tool": "read",
                "state": {"status": "completed", "input": {}, "output": None},
            },
        )
        for part in parts:
            with self.subTest(part=part), self.assertRaises(AssertionError):
                tasker_e2e_sandbox.validate_scenario(
                    self.refusal(), self.trace(self.event("tool_use", **part))
                )

    def test_refuses_incomplete_or_incoherent_streams(self) -> None:
        valid = self.trace()
        other_session = self.event("text", text="Planning-only")
        other_session["sessionID"] = "ses_other"
        invalid_part = self.event("text", text="Planning-only")
        invalid_part["part"]["type"] = "tool"
        invalid_part_session = self.event(
            "text", text="Planning-only", sessionID="ses_other"
        )
        missing_session = self.event("text", text="Planning-only")
        del missing_session["sessionID"]
        missing_part_session = self.event("text", text="Planning-only")
        del missing_part_session["part"]["sessionID"]
        missing_message = self.event("text", text="Planning-only")
        del missing_message["part"]["messageID"]
        changed_message = self.event("text", text="Planning-only", messageID="msg_other")
        bad_streams = (
            [],
            valid[:-1],
            valid[1:],
            self.trace(reason="tool-calls"),
            [self.event("step_start"), self.event("step_finish", reason="stop")],
            [
                self.event("step_start"),
                self.event("text", text=""),
                self.event("step_finish", reason="stop"),
            ],
            self.trace(self.event("error", message="failed")),
            self.trace(self.event("unknown")),
            self.trace(other_session),
            self.trace(invalid_part),
            self.trace(invalid_part_session),
            self.trace(missing_session),
            self.trace(missing_part_session),
            self.trace(missing_message),
            self.trace(changed_message),
            [self.event("step_start"), self.event("step_start"), *valid[1:]],
            [*valid, self.event("text", text="unexpected trailing output")],
            [
                self.event("step_start"),
                self.event("step_finish", reason="tool-calls"),
                *valid,
            ],
            [
                self.event("step_start"),
                self.event("text", text="Planning-only"),
                self.event("step_finish", reason="tool-calls"),
                self.event("step_start"),
                self.event("step_finish", reason="stop"),
            ],
        )
        for events in bad_streams:
            with self.subTest(events=events), self.assertRaises(AssertionError):
                tasker_e2e_sandbox.validate_scenario(self.refusal(), events)

    def test_refusal_requires_a_final_explicit_planning_boundary(self) -> None:
        for text in (
            "I will implement this.",
            "Planning-only is over; I will implement this.",
        ):
            events = [
                self.event("step_start"),
                self.event("text", text=text),
                self.event("step_finish", reason="stop"),
            ]
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(AssertionError, "explicit planning boundary"),
            ):
                tasker_e2e_sandbox.validate_scenario(self.refusal(), events)

    def test_run_scenario_cannot_pass_with_missing_or_bad_output(self) -> None:
        runtime = {
            "TASKER_E2E_WORKSPACE": "/fixture",
            "TASKER_E2E_OPENCODE_BIN": "/fixture/opencode",
        }
        results = (
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="{broken", stderr=""),
            SimpleNamespace(returncode=1, stdout="", stderr="runtime failed"),
        )
        for result in results:
            with (
                self.subTest(result=result),
                patch.object(tasker_e2e_sandbox, "run_process", return_value=result),
                self.assertRaises(AssertionError),
            ):
                tasker_e2e_sandbox.run_scenario(
                    self.refusal(), timeout_ms=1000, runtime_env=runtime
                )


class TaskerShellBoundaryTest(unittest.TestCase):
    def test_instruction_fallback_is_readable_without_the_sibling_agents_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agent").mkdir()
            fallback = root / "agent" / "tasker.md"
            fallback.write_text("Planning-only fixture contract", encoding="utf-8")
            (root / "AGENTS.md").symlink_to(root / "missing-shared-contract")
            with patch.object(tasker_e2e_sandbox, "REPO_ROOT", root):
                self.assertEqual(fallback, tasker_e2e_sandbox.sandbox_instruction_source())

    def test_allows_single_codememory_command(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc add task "planned work" --scope sandbox --worktree /tmp/worktree --branch sandbox/tasker --kind chore --priority P2 --format json'
        )

    def test_allows_exact_launcher_discovery(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command("command -v oc")

    def test_rejects_chained_read_only_health_checks(self) -> None:
        with self.assertRaisesRegex(AssertionError, "compound|chained"):
            tasker_e2e_sandbox.validate_tasker_shell_command(
                "command -v oc && oc config --doctor"
            )

    def test_rejects_chained_read_only_help_checks(self) -> None:
        with self.assertRaisesRegex(AssertionError, "compound|chained"):
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
            with (
                self.subTest(command=command),
                self.assertRaisesRegex(AssertionError, "unapproved|compound"),
            ):
                tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_non_codememory_commands(self) -> None:
        for command in ("git status", "gh pr list", "python3 helper.py", "make test"):
            with (
                self.subTest(command=command),
                self.assertRaisesRegex(AssertionError, "non-Codememory"),
            ):
                tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_allows_single_write_with_global_options(self) -> None:
        tasker_e2e_sandbox.validate_tasker_shell_command(
            'oc --format json add task "planned work" --scope sandbox --worktree /tmp/worktree --branch sandbox/tasker --kind chore --priority P2'
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
            with (
                self.subTest(command=command),
                self.assertRaisesRegex(
                    AssertionError, "compound|chained|backend write"
                ),
            ):
                tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_multiple_or_chained_backend_writes(self) -> None:
        commands = (
            "oc add task first && oc add task second",
            "oc --format json find task && oc --format json add task title",
        )
        for command in commands:
            with (
                self.subTest(command=command),
                self.assertRaisesRegex(AssertionError, "backend write|compound"),
            ):
                tasker_e2e_sandbox.validate_tasker_shell_command(command)

    def test_rejects_command_substitution(self) -> None:
        for command in ("oc get $(git rev-parse HEAD)", "oc get `whoami`"):
            with (
                self.subTest(command=command),
                self.assertRaisesRegex(AssertionError, "compound"),
            ):
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
                'oc add task "Docs" --scope sandbox --worktree /tmp/worktree --branch sandbox/tasker --summary "Do not run git, tests, or PR creation"'
            ],
        )

    def test_rejects_write_outside_prompt_sandbox(self) -> None:
        scenario = tasker_e2e_sandbox.Scenario(
            name="scoped-write",
            prompt="Use scope 'sandbox', worktree '/tmp/worktree', and branch 'sandbox/tasker'.",
            expected_titles={},
            expected_edges=[],
        )
        with self.assertRaisesRegex(AssertionError, "crossed the requested sandbox"):
            tasker_e2e_sandbox.validate_commands(
                scenario,
                [
                    'oc add task "Docs" --scope other --worktree /tmp/worktree --branch sandbox/tasker'
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

            self.assertFalse(tasker_path.is_symlink())
            self.assertEqual(
                (REPO_ROOT / "agent" / "tasker.md").read_text(), tasker_path.read_text()
            )
            self.assertEqual(str(config_home.resolve()), runtime_env["XDG_CONFIG_HOME"])
            self.assertEqual(1, len(config["plugin"]))
            self.assertTrue(
                config["plugin"][0][0].endswith("plugin/gateway-core/dist/index.js")
            )
            self.assertEqual("allow", config["permission"]["bash"])
            self.assertEqual("deny", config["permission"]["edit"])
            tasker_spec = json.loads(
                (REPO_ROOT / "agent" / "specs" / "tasker.json").read_text(
                    encoding="utf-8"
                )
            )
            denied_tools = tasker_spec["metadata"]["denied_tools"]
            self.assertTrue(
                all(config["permission"].get(tool) == "deny" for tool in denied_tools),
                config["permission"],
            )

    def test_runtime_environment_is_allowlisted_and_storage_is_disposable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_home = Path(tmp)
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(config_home)
            config_path = Path(runtime_env["TASKER_E2E_CODEMEMORY_CONFIG"])
            database_path = Path(runtime_env["TASKER_E2E_CODEMEMORY_DATABASE"])
            config_text = config_path.read_text(encoding="utf-8")
            self.assertTrue(config_path.is_file())
            self.assertTrue(database_path.is_absolute())
            self.assertIn(str(database_path), config_text)
            self.assertFalse(database_path.exists())

            result = tasker_e2e_sandbox.run_process(
                [
                    sys.executable,
                    "-c",
                    "import json, os; print(json.dumps(dict(os.environ)))",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides={
                    **runtime_env,
                    "CODEMEMORY_CONFIG_PATH": "/tmp/host-config.yaml",
                    "CODEMEMORY_SQLITE_PATH": "/tmp/host.sqlite3",
                    "DATABASE_URL": "postgresql://host",
                    "OPENCODE_CONFIG_CONTENT": "{}",
                    "UNRELATED_SECRET": "must-not-leak",
                },
            )
            self.assertEqual(0, result.returncode, result.stderr)
            child_env = json.loads(result.stdout)
            self.assertEqual(str(config_home.resolve()), child_env["XDG_CONFIG_HOME"])
            self.assertEqual(str((config_home / "home").resolve()), child_env["HOME"])
            for name in (
                "CODEMEMORY_CONFIG_PATH",
                "CODEMEMORY_SQLITE_PATH",
                "DATABASE_URL",
                "OPENCODE_CONFIG_CONTENT",
                "UNRELATED_SECRET",
            ):
                self.assertNotIn(name, child_env)

    def test_launcher_pins_executable_and_rejects_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_home = Path(tmp)
            runtime_env = tasker_e2e_sandbox.prepare_tasker_runtime(config_home)
            args_path = config_home / "fake-oc-args.json"
            fake_oc = config_home / "fake-oc"
            fake_oc.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                f"open({str(args_path)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
                "print('{}')\n",
                encoding="utf-8",
            )
            fake_oc.chmod(0o700)
            tasker_e2e_sandbox.configure_tasker_runtime_launchers(
                runtime_env,
                real_oc=str(fake_oc),
                real_opencode=sys.executable,
            )
            runtime_env["PATH"] = str(config_home / "empty-path")
            result = tasker_e2e_sandbox.run_process(
                [runtime_env["TASKER_E2E_OC_WRAPPER"], "current", "--format", "json"],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "--config",
                    runtime_env["TASKER_E2E_CODEMEMORY_CONFIG"],
                    "current",
                    "--format",
                    "json",
                ],
                json.loads(args_path.read_text(encoding="utf-8")),
            )
            rejected = tasker_e2e_sandbox.run_process(
                [
                    runtime_env["TASKER_E2E_OC_WRAPPER"],
                    "--config",
                    "/tmp/host-config.yaml",
                    "current",
                ],
                cwd=REPO_ROOT,
                timeout_ms=120000,
                env_overrides=runtime_env,
            )
            self.assertEqual(64, rejected.returncode)


if __name__ == "__main__":
    unittest.main()
