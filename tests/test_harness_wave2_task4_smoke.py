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


def process_result(returncode: int, stdout: str = "", stderr: str = "") -> dict:
    return {
        "command": [],
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": False,
        "duration_seconds": 0.01,
    }


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
