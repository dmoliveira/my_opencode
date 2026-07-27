from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import harness_wave2_task4_smoke as harness
import playwright_defaults as playwright


def process_result(returncode: int, stdout: str = "", stderr: str = "") -> dict:
    return {
        "command": [],
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": False,
        "duration_seconds": 0.01,
    }


def playwright_cli_metadata(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": playwright.PLAYWRIGHT_CLI_VERSION,
        "license": playwright.PLAYWRIGHT_CLI_LICENSE,
        "engines": {"node": playwright.PLAYWRIGHT_CLI_NODE_RANGE},
        "dist": {
            "integrity": playwright.PLAYWRIGHT_CLI_INTEGRITY,
            "shasum": playwright.PLAYWRIGHT_CLI_SHASUM,
        },
        "scripts": {"test": "playwright test"},
    }
    payload.update(overrides)
    return payload


def write_successful_audit(path: Path) -> None:
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    path.write_text(
        "".join(
            json.dumps(event) + "\n"
            for event in (
                {
                    "reason_code": "gateway_runtime_bootstrap",
                    "hooks_enabled": True,
                },
                {
                    "reason_code": "agent_runtime_model_observed",
                    "actual_model": harness.EXACT_MODEL,
                },
                {"reason_code": "runtime_session_env_prefixed"},
            )
        ),
        encoding="utf-8",
    )


class HarnessWave2Task4SmokeTest(unittest.TestCase):
    def test_cli_mode_is_explicit_and_all_keeps_legacy_components(self) -> None:
        args = harness.parse_args(["cli", "--scenario-label", "wave6-check"])
        self.assertEqual("cli", args.mode)
        self.assertEqual("wave6-check", args.scenario_label)
        self.assertEqual(("cli",), harness.selected_components("cli"))
        self.assertEqual(("mcp", "projects"), harness.selected_components("all"))

    def test_mcp_inventory_requires_exact_tool_count_and_representatives(self) -> None:
        representatives = list(harness.MCP_REQUIRED_TOOLS.values())
        filler = [
            f"synthetic_tool_{index}"
            for index in range(harness.MCP_REQUIRED_TOOL_COUNT - len(representatives))
        ]
        exact = representatives + filler
        self.assertTrue(
            harness.evaluate_mcp_inventory({"name": "Playwright"}, exact)["pass"]
        )
        self.assertFalse(
            harness.evaluate_mcp_inventory({"name": "Playwright"}, exact[:-1])["pass"]
        )
        self.assertFalse(
            harness.evaluate_mcp_inventory(
                {"name": "Playwright"}, exact + ["one_too_many"]
            )["pass"]
        )
        self.assertFalse(
            harness.evaluate_mcp_inventory(
                {"name": "Playwright"}, exact[1:] + ["replacement"]
            )["pass"]
        )

    def test_mcp_lifecycle_drift_fails_before_package_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            captured_env: dict[str, str] = {}

            def fake_process(command, **kwargs):
                captured_env.update(kwargs["env"])
                return process_result(
                    0,
                    json.dumps(
                        {
                            "version": harness.PLAYWRIGHT_VERSION,
                            "license": harness.PLAYWRIGHT_LICENSE,
                            "dist": {"integrity": harness.PLAYWRIGHT_INTEGRITY},
                            "gitHead": harness.PLAYWRIGHT_GIT_HEAD,
                            "scripts": {"postinstall": "curl example.invalid"},
                        }
                    ),
                )

            with (
                patch.object(harness, "run_process", side_effect=fake_process),
                patch.object(harness.subprocess, "Popen") as popen,
            ):
                report = harness.run_mcp_probe(
                    output_dir=Path(raw_tmp) / "evidence",
                    timeout=30,
                    secrets=[],
                )

        self.assertEqual("FAIL", report["result"])
        self.assertEqual(["postinstall"], report["provenance"]["lifecycle_scripts"])
        self.assertEqual("true", captured_env["npm_config_ignore_scripts"])
        self.assertTrue(captured_env["npm_config_userconfig"].endswith("user.npmrc"))
        self.assertNotIn("OPENAI_API_KEY", captured_env)
        popen.assert_not_called()

    def test_mcp_log_tail_is_byte_bounded(self) -> None:
        lines = harness.deque()
        retained = harness._append_bounded_line(
            lines, "x" * (harness.CLI_LOG_BYTES * 2), 0
        )
        self.assertLessEqual(retained, harness.CLI_LOG_BYTES)
        self.assertLessEqual(
            len("".join(lines).encode("utf-8")), harness.CLI_LOG_BYTES
        )

    def test_process_identity_change_is_not_treated_as_owned(self) -> None:
        with patch.object(harness, "_process_identity", return_value="new-identity"):
            self.assertFalse(harness._identity_alive(42, "old-identity"))
        with (
            patch.object(harness, "_process_group_members", return_value={42}),
            patch.object(harness, "_process_identity", return_value="new-identity"),
            patch.object(harness.os, "killpg") as kill_group,
            patch.object(harness.os, "kill") as kill_pid,
        ):
            harness._terminate_owned_processes({42: "old-identity"}, {42})
        kill_group.assert_not_called()
        kill_pid.assert_not_called()

    def test_cli_provenance_mismatch_prevents_package_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            calls: list[list[str]] = []

            def fake_process(command, **_kwargs):
                command = list(command)
                calls.append(command)
                if command == ["node", "--version"]:
                    return process_result(0, "v22.0.0\n")
                if command[:2] == ["npm", "view"]:
                    return process_result(
                        0,
                        json.dumps(playwright_cli_metadata(version="0.1.18")),
                    )
                raise AssertionError("package code must not run after metadata drift")

            with (
                patch.object(harness.shutil, "which", return_value="/fake/tool"),
                patch.object(harness, "run_process", side_effect=fake_process),
                patch.object(
                    harness, "tracked_worktree_fingerprint", return_value="stable"
                ),
            ):
                report = harness.run_cli_probe(
                    repo_root=REPO_ROOT,
                    output_dir=root / "evidence",
                    scenario_label="wave6",
                    timeout=30,
                    secrets=[],
                )

        self.assertEqual("FAIL", report["result"])
        self.assertFalse(report["provenance"]["verified"])
        self.assertEqual(["node-version", "npm-view"], [item["label"] for item in report["commands"]])
        self.assertTrue(report["sandbox_cleanup_confirmed"])
        self.assertFalse(any(command[0] == "npx" for command in calls))

    def test_cli_todo_flow_uses_unique_session_scoped_close_and_bounded_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            calls: list[list[str]] = []

            def fake_process(command, *, cwd, **_kwargs):
                command = list(command)
                calls.append(command)
                if command == ["node", "--version"]:
                    return process_result(0, "v22.0.0\n")
                if command[:2] == ["npm", "view"]:
                    return process_result(0, json.dumps(playwright_cli_metadata()))
                if command[-1] == "--version":
                    return process_result(0, f"{playwright.PLAYWRIGHT_CLI_VERSION}\n")
                session_arg = next(item for item in command if item.startswith("-s="))
                session = session_arg.removeprefix("-s=")
                if "open" in command:
                    snapshot = cwd / ".playwright-cli" / "open.yml"
                    snapshot.parent.mkdir(parents=True, exist_ok=True)
                    snapshot.write_text(
                        '- textbox "New todo" [ref=e4]\n- button "Add" [ref=e5]\n',
                        encoding="utf-8",
                    )
                    return process_result(
                        0,
                        json.dumps(
                            {
                                "session": session,
                                "result": {
                                    "snapshot": {
                                        "file": ".playwright-cli/open.yml"
                                    }
                                },
                            }
                        ),
                    )
                if "snapshot" in command:
                    return process_result(
                        0,
                        json.dumps(
                            {"snapshot": "status: 1 items\nlistitem: Ship Wave 6"}
                        ),
                    )
                if "screenshot" in command:
                    screenshot = cwd / ".playwright-cli" / "todo.png"
                    screenshot.write_bytes(b"synthetic-png")
                    return process_result(
                        0,
                        json.dumps(
                            {
                                "result": "- [Screenshot](.playwright-cli/todo.png)"
                            }
                        ),
                    )
                if "close" in command:
                    return process_result(
                        0, json.dumps({"session": session, "status": "closed"})
                    )
                if "fill" in command or "click" in command:
                    return process_result(0, "{}")
                raise AssertionError(f"unexpected command: {command}")

            with (
                patch.object(harness.shutil, "which", return_value="/fake/tool"),
                patch.object(harness, "run_process", side_effect=fake_process),
                patch.object(
                    harness, "tracked_worktree_fingerprint", return_value="stable"
                ),
            ):
                report = harness.run_cli_probe(
                    repo_root=REPO_ROOT,
                    output_dir=root / "evidence",
                    scenario_label="wave6",
                    timeout=30,
                    secrets=[],
                )

            self.assertEqual("PASS", report["result"])
            self.assertTrue(report["session"].startswith("wave6-"))
            self.assertTrue(report["scoped_close"])
            self.assertEqual([], report["surviving_owned_pids"])
            self.assertTrue(report["sandbox_only_writes"])
            self.assertTrue(report["sandbox_cleanup_confirmed"])
            self.assertEqual(
                [
                    "node-version",
                    "npm-view",
                    "version",
                    "open",
                    "fill",
                    "click",
                    "snapshot",
                    "screenshot",
                    "close",
                ],
                [item["label"] for item in report["commands"]],
            )
            self.assertTrue(all(not path.startswith("/") for path in report["artifact_paths"]))
            cli_commands = [command for command in calls if command[0] == "npx"]
            session_args = {
                item for command in cli_commands for item in command if item.startswith("-s=")
            }
            self.assertEqual({f"-s={report['session']}"}, session_args)
            flattened = " ".join(item for command in cli_commands for item in command)
            self.assertNotIn("close-all", flattened)
            self.assertNotIn("kill-all", flattened)

    def test_config_uses_one_exact_tuple_and_no_project_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            dist_entry = root / "candidate" / "dist" / "index.js"
            dist_entry.parent.mkdir(parents=True)
            dist_entry.write_text("export default () => ({})\n", encoding="utf-8")

            config = harness.write_opencode_config(
                home, harness.EXACT_MODEL, dist_entry
            )
            summary = harness.configured_tuple_summary(config)

            self.assertEqual(1, len(config["plugin"]))
            self.assertEqual(dist_entry.resolve().as_uri(), config["plugin"][0][0])
            self.assertEqual(
                {
                    "hooks": {
                        "enabled": True,
                        "order": ["noninteractive-shell-guard"],
                        "disabled": [],
                    },
                    "noninteractiveShellGuard": {"enabled": True},
                },
                config["plugin"][0][1],
            )
            self.assertEqual(
                {
                    "configured_plugin_entry_count": 1,
                    "configured_plugin_entry_kind": "tuple",
                    "hooks_enabled": True,
                    "selected_hook_ids": ["noninteractive-shell-guard"],
                },
                summary,
            )
            self.assertEqual(0, harness.project_gateway_shim_count(project))
            self.assertNotIn(dist_entry.as_uri(), json.dumps(summary))
            self.assertNotIn(harness.gateway_plugin_spec(dist_entry), json.dumps(summary))
            self.assertNotIn("noninteractiveShellGuard", json.dumps(summary))

    def test_private_sandbox_directory_rejects_unsafe_existing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private = root / "private"
            harness.ensure_private_directory(private)
            self.assertEqual(0o700, stat.S_IMODE(private.stat().st_mode))

            permissive = root / "permissive"
            permissive.mkdir(mode=0o755)
            permissive.chmod(0o755)
            with self.assertRaisesRegex(PermissionError, "owner-only"):
                harness.ensure_private_directory(permissive)

            linked = root / "linked"
            linked.symlink_to(private, target_is_directory=True)
            with self.assertRaisesRegex(PermissionError, "owner-only"):
                harness.ensure_private_directory(linked)

    def test_oauth_store_and_runtime_env_projection_exclude_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth_path = root / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "openai": {
                            "type": "oauth",
                            "access": "WAVE5_ACCESS_TOKEN",
                            "refresh": "WAVE5_REFRESH_TOKEN",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "WAVE5_API_KEY",
                    "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
                },
                clear=False,
            ):
                env = harness.isolated_env(root / "home", root / "audit.jsonl")

            auth = harness.auth_store_summary(auth_path)
            contract = harness.runtime_auth_contract(env)
            retained = json.dumps({"auth": auth, "contract": contract})
            self.assertTrue(auth["oauth_store_only"])
            self.assertEqual("oauth", auth["openai_auth_type"])
            self.assertEqual(0, contract["forwarded_api_key_count"])
            self.assertTrue(contract["default_plugins_retained"])
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("OPENCODE_DISABLE_DEFAULT_PLUGINS", env)
            self.assertNotIn("WAVE5_ACCESS_TOKEN", retained)
            self.assertNotIn("WAVE5_REFRESH_TOKEN", retained)

    def test_auth_store_is_copied_privately_instead_of_linked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "host-auth.json"
            source.write_text('{"openai":{"type":"oauth"}}\n', encoding="utf-8")
            home = root / "home"

            self.assertTrue(harness.copy_auth_store(home, source))

            destination = home / ".local" / "share" / "opencode" / "auth.json"
            self.assertFalse(destination.is_symlink())
            self.assertEqual(source.read_bytes(), destination.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(destination.stat().st_mode))

    def test_audit_summary_requires_structured_bootstrap_model_and_env_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "gateway-events.jsonl"
            events = [
                {
                    "reason_code": "gateway_runtime_bootstrap",
                    "hooks_enabled": True,
                },
                {
                    "reason_code": "agent_runtime_model_observed",
                    "actual_model": harness.EXACT_MODEL,
                },
                {"reason_code": "runtime_session_env_prefixed"},
                {"reason_code": "runtime_session_env_prefixed"},
            ]
            audit_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            summary = harness.audit_summary(audit_path)
            self.assertEqual(1, summary["bootstrap_count"])
            self.assertTrue(summary["bootstrap_hooks_enabled"])
            self.assertEqual([harness.EXACT_MODEL], summary["observed_models"])
            self.assertEqual(2, summary["runtime_session_env_prefixed_count"])
            self.assertNotIn(str(audit_path), json.dumps(summary))

    def test_preflight_distinguishes_missing_gateway_audit_from_model_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "preflight"
            output = root / "evidence"
            dist_entry = root / "candidate" / "dist" / "index.js"
            dist_entry.parent.mkdir(parents=True)
            dist_entry.write_text("export default () => ({})\n", encoding="utf-8")
            auth = root / "auth.json"
            auth.write_text(
                json.dumps({"openai": {"type": "oauth", "access": "TOKEN"}}),
                encoding="utf-8",
            )

            with patch.object(
                harness,
                "run_model_once",
                return_value=process_result(0, "MODEL_PREFLIGHT_OK"),
            ):
                report = harness.run_model_preflight(
                    base=base,
                    model=harness.EXACT_MODEL,
                    dist_entry=dist_entry,
                    auth_source=auth,
                    output_dir=output,
                    timeout=60,
                    secrets=[],
                )

            self.assertEqual("BLOCKED", report["result"])
            self.assertEqual("gateway_audit_unavailable", report["reason"])
            self.assertEqual(0o700, stat.S_IMODE(base.stat().st_mode))

    def test_committed_candidate_report_is_relative_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "plugin" / "gateway-core" / "src"
            dist = repo / "plugin" / "gateway-core" / "dist"
            source.mkdir(parents=True)
            dist.mkdir(parents=True)
            (source / "index.ts").write_text("export default 1\n", encoding="utf-8")
            (dist / "index.js").write_text("export default 1\n", encoding="utf-8")

            def fake_run(command, **_kwargs):
                if command[0] == "npm":
                    return process_result(0)
                if command[1:3] == ["rev-parse", "HEAD"]:
                    return process_result(0, "a" * 40 + "\n")
                if command[1] == "status":
                    return process_result(0, "")
                raise AssertionError(command)

            with patch.object(harness, "run_process", side_effect=fake_run):
                report = harness.verify_committed_candidate(repo, 30)

            self.assertEqual("PASS", report["result"])
            self.assertEqual("a" * 40, report["head_commit"])
            self.assertTrue(report["tracked_clean_after_build"])
            self.assertEqual("plugin/gateway-core/src", report["source"]["path"])
            self.assertEqual("plugin/gateway-core/dist", report["dist"]["path"])
            self.assertEqual(64, len(report["source"]["sha256"]))
            self.assertEqual(64, len(report["dist"]["sha256"]))
            self.assertNotIn(str(repo), json.dumps(report))

    def test_candidate_rejects_uncommitted_tracked_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "plugin" / "gateway-core" / "src"
            dist = repo / "plugin" / "gateway-core" / "dist"
            source.mkdir(parents=True)
            dist.mkdir(parents=True)
            (source / "index.ts").write_text("export default 1\n", encoding="utf-8")
            (dist / "index.js").write_text("export default 1\n", encoding="utf-8")

            def fake_run(command, **_kwargs):
                if command[0] == "npm":
                    return process_result(0)
                if command[1:3] == ["rev-parse", "HEAD"]:
                    return process_result(0, "b" * 40 + "\n")
                if command[1] == "status" and "--untracked-files=no" in command:
                    return process_result(0, " M scripts/harness_wave2_task4_smoke.py\n")
                if command[1] == "status":
                    return process_result(0)
                raise AssertionError(command)

            with patch.object(harness, "run_process", side_effect=fake_run):
                report = harness.verify_committed_candidate(repo, 30)

            self.assertEqual("FAIL", report["result"])
            self.assertFalse(report["tracked_clean_after_build"])

    def test_fixture_hashes_include_project_opencode_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            plugin = project / ".opencode" / "plugins" / "shim.js"
            plugin.parent.mkdir(parents=True)
            plugin.write_text("export default {}\n", encoding="utf-8")

            hashes = harness.fixture_hashes(project)

            self.assertIn(".opencode/plugins/shim.js", hashes)

    def test_python_fixture_keeps_tests_unchanged_and_retains_no_private_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "python"
            output = root / "evidence"
            dist_entry = root / "candidate" / "dist" / "index.js"
            dist_entry.parent.mkdir(parents=True)
            dist_entry.write_text("export default () => ({})\n", encoding="utf-8")
            auth = root / "auth.json"
            auth.write_text(
                json.dumps({"openai": {"type": "oauth", "access": "TOKEN"}}),
                encoding="utf-8",
            )
            test_results = iter([process_result(1), process_result(0)])

            def fake_process(*_args, **_kwargs):
                return next(test_results)

            def fake_model(**kwargs):
                kwargs["project"].joinpath("stats.py").write_text(
                    """def summarize(values):
    if not values:
        return {"count": 0, "total": 0, "average": None, "minimum": None, "maximum": None}
    total = sum(values)
    return {"count": len(values), "total": total, "average": total / len(values), "minimum": min(values), "maximum": max(values)}
""",
                    encoding="utf-8",
                )
                audit_path = Path(
                    kwargs["env"]["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"]
                )
                write_successful_audit(audit_path)
                return process_result(
                    0,
                    f"private={base} tuple={harness.gateway_plugin_spec(dist_entry)} "
                    "noninteractiveShellGuard",
                )

            with (
                patch.object(harness, "run_process", side_effect=fake_process),
                patch.object(harness, "run_model_once", side_effect=fake_model),
            ):
                report = harness.run_project_fixture(
                    name="python",
                    base=base,
                    model=harness.EXACT_MODEL,
                    dist_entry=dist_entry,
                    auth_source=auth,
                    output_dir=output,
                    timeout=60,
                    deadline=time.monotonic() + 60,
                    secrets=[],
                )

            retained = json.dumps(report)
            self.assertEqual("PASS", report["result"])
            self.assertEqual(["stats.py"], report["changed_files"])
            self.assertTrue(report["test_hash_unchanged"])
            self.assertEqual(0, report["project_gateway_shim_count"])
            self.assertEqual(1, report["configured_plugin_entry_count"])
            self.assertEqual(1, report["audit"]["runtime_session_env_prefixed_count"])
            self.assertNotIn(str(base), retained)
            self.assertNotIn(dist_entry.as_uri(), retained)
            self.assertNotIn(harness.gateway_plugin_spec(dist_entry), retained)
            self.assertNotIn("noninteractiveShellGuard", retained)
            evidence_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(str(base), evidence_text)
            self.assertNotIn(dist_entry.as_uri(), evidence_text)
            self.assertNotIn(harness.gateway_plugin_spec(dist_entry), evidence_text)
            self.assertNotIn("noninteractiveShellGuard", evidence_text)

    def test_node_fixture_keeps_tests_unchanged_and_changes_only_implementation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "node"
            output = root / "evidence"
            dist_entry = root / "candidate" / "dist" / "index.js"
            dist_entry.parent.mkdir(parents=True)
            dist_entry.write_text("export default () => ({})\n", encoding="utf-8")
            auth = root / "auth.json"
            auth.write_text(
                json.dumps({"openai": {"type": "oauth", "access": "TOKEN"}}),
                encoding="utf-8",
            )
            test_results = iter([process_result(1), process_result(0)])

            def fake_process(*_args, **_kwargs):
                return next(test_results)

            def fake_model(**kwargs):
                kwargs["project"].joinpath("slugify.mjs").write_text(
                    """export function slugify(value) {
  return String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}
""",
                    encoding="utf-8",
                )
                write_successful_audit(
                    Path(kwargs["env"]["MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH"])
                )
                return process_result(0)

            with (
                patch.object(harness, "run_process", side_effect=fake_process),
                patch.object(harness, "run_model_once", side_effect=fake_model),
            ):
                report = harness.run_project_fixture(
                    name="node",
                    base=base,
                    model=harness.EXACT_MODEL,
                    dist_entry=dist_entry,
                    auth_source=auth,
                    output_dir=output,
                    timeout=60,
                    deadline=time.monotonic() + 60,
                    secrets=[],
                )

            self.assertEqual("PASS", report["result"])
            self.assertEqual(["slugify.mjs"], report["changed_files"])
            self.assertTrue(report["test_hash_unchanged"])
            self.assertEqual(0, report["project_gateway_shim_count"])
            self.assertEqual([harness.EXACT_MODEL], report["observed_models"])
            self.assertGreaterEqual(
                report["audit"]["runtime_session_env_prefixed_count"], 1
            )

    def test_safe_report_removes_credentials_and_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            safe, detected = harness.write_safe_report(
                report_path,
                {
                    "result": "PASS",
                    "secret": "WAVE5_REPORT_SECRET",
                    "path": "/private/wave5/path",
                },
                ["WAVE5_REPORT_SECRET"],
                ["/private/wave5/path"],
            )
            retained = report_path.read_text(encoding="utf-8")
            self.assertTrue(detected)
            self.assertNotIn("WAVE5_REPORT_SECRET", retained)
            self.assertNotIn("/private/wave5/path", retained)
            self.assertIn("[CREDENTIAL_REMOVED]", retained)
            self.assertIn("[PRIVATE_VALUE_REMOVED]", retained)
            self.assertEqual("PASS", safe["result"])

    def test_remaining_timeout_enforces_aggregate_deadline(self) -> None:
        with patch.object(harness.time, "monotonic", return_value=10.0):
            self.assertEqual(5, harness.remaining_timeout(15.9, 30))
            with self.assertRaisesRegex(TimeoutError, "aggregate deadline"):
                harness.remaining_timeout(10.5, 30)


if __name__ == "__main__":
    unittest.main()
