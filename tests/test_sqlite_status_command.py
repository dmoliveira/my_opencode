from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import doctor_command
import shared_memory_runtime
import sqlite_status_command as status


class SqliteStatusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.runtime = self.root / "runtime.db"
        self.shared = self.root / "shared.db"
        self.codememory = self.root / "codememory.db"
        self.index = self.root / "index.json"
        self.digest = self.root / "digest.json"
        for path, content in (
            (self.runtime, b"runtime"),
            (self.shared, b"shared"),
            (self.codememory, b"codememory"),
            (self.index, b"index"),
            (self.digest, b"digest"),
        ):
            path.write_bytes(content)
            path.chmod(0o600)

    def owner_report(self):
        return {
            "result": "PASS",
            "stores": {
                "runtime_history": {
                    "result": "PASS",
                    "path": str(self.runtime),
                    "diagnostics": {
                        "runtime_permission_status": "private",
                        "runtime_db_size_bytes": 7,
                        "runtime_db_wal_bytes": 0,
                        "stuck_findings": [{"session_id": "PRIVATE-SESSION"}],
                        "raw_prompt": "PRIVATE-PROMPT",
                    },
                },
                "session_sidecars": {
                    "result": "PASS",
                    "path": str(self.index),
                    "diagnostics": {
                        "sidecar_findings": [
                            {
                                "target": "index",
                                "path": str(self.index),
                                "state": "private",
                            },
                            {
                                "target": "digest",
                                "path": str(self.digest),
                                "state": "private",
                            },
                        ]
                    },
                },
                "shared_memory": {
                    "result": "PASS",
                    "path": str(self.shared),
                    "diagnostics": {"memory_count": 123, "secret": "PRIVATE-CONTENT"},
                },
                "codememory": {
                    "result": "PASS",
                    "path": str(self.codememory),
                    "diagnostics": {"scope": "PRIVATE-SCOPE"},
                },
            },
        }

    def owner_config(self):
        return {"state": "resolved", "backend": "sqlite", "path": str(self.codememory)}

    def test_summary_exposes_bounded_metadata_and_existing_owner_health(self):
        report = status.build_status(self.owner_report(), self.owner_config())
        self.assertEqual("PASS", report["result"])
        self.assertEqual(
            list(status.STORE_ORDER), [item["store"] for item in report["stores"]]
        )
        runtime, sidecars, shared, codememory = report["stores"]
        self.assertEqual(str(self.runtime), runtime["path"])
        self.assertEqual(7, runtime["file_metadata"]["bytes"])
        self.assertEqual(7, runtime["owner_reported_database_bytes"])
        self.assertEqual("private", runtime["privacy"]["state"])
        self.assertEqual("missing", runtime["wal_metadata"]["state"])
        self.assertEqual(
            {"index", "digest"}, {item["kind"] for item in sidecars["artifacts"]}
        )
        self.assertEqual("manual_archive_default", shared["retention"]["state"])
        self.assertEqual("unknown", shared["retention"]["automatic_cleanup"])
        self.assertEqual("unknown", shared["privacy"]["state"])
        self.assertEqual("sqlite", codememory["backend"])
        self.assertEqual("native_config", codememory["path_source"])
        self.assertNotIn("PRIVATE-SESSION", json.dumps(report))
        self.assertNotIn("PRIVATE-PROMPT", json.dumps(report))
        self.assertNotIn("PRIVATE-CONTENT", json.dumps(report))
        self.assertNotIn("PRIVATE-SCOPE", json.dumps(report))

    def test_sidecar_writer_policy_is_from_owner_with_explicit_fallback(self):
        policy = {
            "max_sessions": 22,
            "max_age_days": 5,
            "max_events_per_session": 9,
            "max_reasons_per_session": 3,
            "max_plan_ids_per_session": 2,
        }
        with patch.object(
            status.session_metadata_index, "_load_policy", return_value=policy
        ):
            report = status.build_status(self.owner_report(), self.owner_config())
        self.assertEqual(policy, report["stores"][1]["retention"]["values"])
        self.assertEqual(
            "effective_writer_policy_with_default_fallback",
            report["stores"][1]["retention"]["state"],
        )
        policy["max_sessions"] = True
        with patch.object(
            status.session_metadata_index, "_load_policy", return_value=policy
        ):
            report = status.build_status(self.owner_report(), self.owner_config())
        self.assertEqual("unknown", report["stores"][1]["retention"]["state"])

    def test_privacy_does_not_follow_symlink_or_certify_ancestors(self):
        target = self.root / "large-secret"
        target.write_bytes(b"secret payload")
        link = self.root / "alias.db"
        link.symlink_to(target)
        report = status.build_status(
            self.owner_report(),
            {"state": "resolved", "backend": "sqlite", "path": str(link)},
        )
        codememory = report["stores"][3]
        self.assertEqual("WARN", report["result"])
        self.assertIn("codememory_doctor_path_mismatch", report["reason_codes"])
        self.assertEqual("non_regular", codememory["file_metadata"]["state"])
        self.assertIsNone(codememory["file_metadata"]["bytes"])
        self.assertEqual("file_metadata_attention", codememory["privacy"]["state"])
        self.assertTrue(any("ancestor" in value for value in report["limitations"]))

    def test_missing_invalid_relative_and_unknown_are_not_zero_or_safe(self):
        source = self.owner_report()
        source["stores"]["runtime_history"].update(
            path="relative.db",
            diagnostics={
                "runtime_permission_status": "private-but-not-enumerated",
                "runtime_db_size_bytes": True,
            },
        )
        source["stores"]["session_sidecars"]["diagnostics"] = {
            "sidecar_findings": [
                {"target": [], "path": "x", "state": []},
                {"target": "index", "state": []},
            ]
        }
        source["stores"]["shared_memory"]["path"] = str(self.root / "missing.db")
        report = status.build_status(
            source, {"state": "unavailable", "backend": None, "path": None}
        )
        self.assertEqual("WARN", report["result"])
        self.assertIsNone(report["stores"][0]["path"])
        self.assertEqual("unknown", report["stores"][0]["privacy"]["state"])
        self.assertIsNone(report["stores"][0]["owner_reported_database_bytes"])
        self.assertEqual(
            "unknown", report["stores"][1]["artifacts"][0]["owner_privacy_state"]
        )
        self.assertEqual("missing", report["stores"][2]["file_metadata"]["state"])
        self.assertIsNone(report["stores"][2]["file_metadata"]["bytes"])
        self.assertIsNone(report["stores"][3]["path"])
        self.assertIn("codememory_config_unavailable", report["reason_codes"])

    def test_owner_result_malformed_or_fail_does_not_become_pass(self):
        self.assertEqual("FAIL", status.build_status({}, self.owner_config())["result"])
        report = self.owner_report()
        for invalid in (None, [], "PASS?", True):
            report["result"] = invalid
            self.assertEqual(
                "FAIL", status.build_status(report, self.owner_config())["result"]
            )
        report["result"] = "FAIL"
        self.assertEqual(
            "FAIL", status.build_status(report, self.owner_config())["result"]
        )
        report = self.owner_report()
        report["stores"]["runtime_history"]["result"] = []
        self.assertEqual(
            "FAIL", status.build_status(report, self.owner_config())["result"]
        )
        report["stores"].pop("shared_memory")
        self.assertEqual("FAIL", status.build_status(report, None)["result"])

    def test_non_sqlite_or_malformed_native_config_never_displays_secret_url(self):
        report = status.build_status(
            self.owner_report(),
            {
                "state": "resolved",
                "backend": "postgres",
                "path": "postgres://PRIVATE-SECRET",
            },
        )
        self.assertEqual("WARN", report["result"])
        self.assertIsNone(report["stores"][3]["path"])
        self.assertIn("codememory_non_sqlite_backend", report["reason_codes"])
        self.assertNotIn("PRIVATE-SECRET", json.dumps(report))
        for backend in ([], None, "postgresql", True):
            invalid = status.build_status(
                self.owner_report(), {"state": "resolved", "backend": backend}
            )
            self.assertEqual("WARN", invalid["result"])
            self.assertIsNone(invalid["stores"][3]["backend"])

    def test_native_config_resolution_rejects_malformed_and_does_not_echo_output(self):
        config = self.root / "config.yaml"
        config.write_text("version: 1\n")
        content = {
            "type": "config",
            "database": {
                "backend": "sqlite",
                "path": str(self.codememory),
                "url": "PRIVATE-SECRET",
            },
        }
        result = {
            "kind": "completed",
            "exit_code": 0,
            "stdout": json.dumps(content).encode(),
            "stderr": b"",
        }
        with (
            patch.object(status.doctor, "_config_path", return_value=config),
            patch.object(status.shutil, "which", return_value="/usr/bin/oc"),
            patch.object(
                status.doctor, "_run_bounded_command", return_value=result
            ) as run,
        ):
            actual = status._owner_config()
        self.assertEqual(self.owner_config(), actual)
        self.assertEqual(
            ["/usr/bin/oc", "--config", str(config), "config", "--format", "json"],
            run.call_args.args[0],
        )
        self.assertNotIn("PRIVATE-SECRET", json.dumps(actual))
        for payload in (
            b"not-json",
            b"{}",
            b'{"type":"config","database":{"backend":[]}}',
        ):
            with (
                patch.object(status.doctor, "_config_path", return_value=config),
                patch.object(status.shutil, "which", return_value="/usr/bin/oc"),
                patch.object(
                    status.doctor,
                    "_run_bounded_command",
                    return_value={**result, "stdout": payload},
                ),
            ):
                self.assertIn(
                    status._owner_config()["state"], {"unavailable", "invalid"}
                )
        with patch.object(status.shutil, "which", return_value=None):
            self.assertEqual("unavailable", status._owner_config()["state"])

    def test_native_config_runtime_override_is_resolved_without_creating_database(self):
        oc = shutil.which("oc")
        if not oc:
            self.skipTest("native Codememory CLI not installed")
        config = self.root / "native-config.yaml"
        configured = self.root / "configured.db"
        override = self.root / "override.db"
        config.write_text(
            "version: 1\ndatabase:\n  backend: sqlite\n  path: "
            + json.dumps(str(configured))
            + "\n"
        )
        env = {
            "HOME": str(self.root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "CODEMEMORY_CONFIG_PATH": str(config),
            "CODEMEMORY_SQLITE_PATH": str(override),
            "MY_OPENCODE_CODEMEMORY_BIN": oc,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with patch.dict(os.environ, env, clear=True):
            actual = status._owner_config()
        self.assertEqual(
            {"state": "resolved", "backend": "sqlite", "path": str(override)}, actual
        )
        self.assertFalse(configured.exists())
        self.assertFalse(override.exists())
        self.assertEqual(
            before, {path.name: path.read_bytes() for path in self.root.iterdir()}
        )

    def test_config_path_exceptions_and_lone_surrogates_fail_closed(self):
        with (
            patch.object(
                status.doctor,
                "_config_path",
                side_effect=RuntimeError("PRIVATE SECRET"),
            ),
            patch.object(status.shutil, "which", return_value="/usr/bin/oc"),
        ):
            result = status._owner_config()
        self.assertEqual(
            {"state": "unavailable", "backend": None, "path": None}, result
        )
        self.assertNotIn("PRIVATE", json.dumps(result))
        report = self.owner_report()
        report["stores"]["runtime_history"]["path"] = "/private/\ud800"
        result = status.build_status(report, self.owner_config())
        self.assertIsNone(result["stores"][0]["path"])

    def test_no_path_mode_ownership_certifies_privacy(self):
        self.runtime.chmod(0o644)
        report = status.build_status(self.owner_report(), self.owner_config())
        self.assertEqual("0644", report["stores"][0]["file_metadata"]["mode"])
        self.assertEqual(
            "inconsistent_samples", report["stores"][0]["privacy"]["state"]
        )
        self.assertEqual("WARN", report["stores"][0]["health"])
        self.assertIn("runtime_history_file_metadata_attention", report["reason_codes"])
        self.assertEqual(
            "runtime_owner_diagnostic", report["stores"][0]["privacy"]["basis"]
        )
        self.assertIn(
            "Metadata and owner diagnostics are sampled", report["limitations"][0]
        )

    def test_nonprivate_wal_and_shared_memory_are_reported_as_attention(self):
        wal = Path(str(self.runtime) + "-wal")
        wal.write_bytes(b"untrusted")
        wal.chmod(0o644)
        self.shared.chmod(0o644)
        report = status.build_status(self.owner_report(), self.owner_config())
        self.assertEqual("WARN", report["result"])
        self.assertEqual(
            "inconsistent_samples", report["stores"][0]["privacy"]["state"]
        )
        self.assertEqual(
            "file_metadata_attention", report["stores"][2]["privacy"]["state"]
        )
        self.assertIn("shared_memory_file_metadata_attention", report["reason_codes"])

    def test_hardlinked_sidecar_is_an_explicit_attention_not_a_privacy_certificate(
        self,
    ):
        alias = self.root / "index-alias.json"
        os.link(self.index, alias)
        report = status.build_status(self.owner_report(), self.owner_config())
        sidecar = report["stores"][1]
        self.assertEqual("WARN", sidecar["health"])
        self.assertEqual("file_metadata_attention", sidecar["privacy"]["state"])
        self.assertEqual(2, sidecar["artifacts"][0]["file_metadata"]["link_count"])
        self.assertIn(
            "session_sidecars_file_metadata_attention", report["reason_codes"]
        )

    def test_cli_redaction_and_human_output_do_not_include_paths_or_secrets(self):
        with (
            patch.object(status.doctor, "build_report", side_effect=self.owner_report),
            patch.object(status, "_owner_config", side_effect=self.owner_config),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(0, status.main(["--json", "--redact"]))
        report = json.loads(output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertNotIn("PRIVATE-", output.getvalue())
        self.assertTrue(all(item["path"] is None for item in report["stores"]))
        self.assertTrue(
            all(item["path"] is None for item in report["stores"][1]["artifacts"])
        )
        self.assertEqual(
            "metadata-only-not-automatically-share-safe", report["sensitivity"]
        )
        with (
            patch.object(status.doctor, "build_report", side_effect=self.owner_report),
            patch.object(status, "_owner_config", side_effect=self.owner_config),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(0, status.main([]))
        self.assertIn("runtime_history: PASS", output.getvalue())
        self.assertIn(
            "retention=manual-archive-default:30d;automatic=unknown", output.getvalue()
        )
        self.assertIn("index: path=", output.getvalue())
        self.assertIn("digest: path=", output.getvalue())
        self.assertNotIn("PRIVATE-", output.getvalue())
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(2, status.main(["--unknown-PRIVATE-CANARY"]))
        self.assertNotIn("PRIVATE-CANARY", output.getvalue())

    def test_owner_exceptions_fail_closed_without_echoing_sensitive_detail(self):
        with (
            patch.object(
                status.doctor,
                "build_report",
                side_effect=RuntimeError("PRIVATE-CANARY /private/path"),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(1, status.main(["--json", "--redact"]))
        self.assertEqual("FAIL", json.loads(output.getvalue())["result"])
        self.assertNotIn("PRIVATE-CANARY", output.getvalue())
        self.assertNotIn("/private/path", output.getvalue())

    def test_route_preserves_existing_doctor_sqlite_behavior(self):
        with patch.object(status, "main", return_value=17) as route:
            self.assertEqual(
                17, doctor_command.command_sqlite(["status", "--json", "--redact"])
            )
            route.assert_called_once_with(["--json", "--redact"])
        with patch("sqlite_doctor_command.main", return_value=18) as old_route:
            self.assertEqual(18, doctor_command.command_sqlite(["--json"]))
            old_route.assert_called_once_with(["--json"])

    def test_real_cli_isolated_missing_stores_does_not_create_files(self):
        config = self.root / "oc.yaml"
        db = self.root / "missing-codememory.db"
        config.write_text(
            "version: 1\ndatabase:\n  backend: sqlite\n  path: "
            + json.dumps(str(db))
            + "\n"
        )
        oc = shutil.which("oc")
        if not oc:
            self.skipTest("native Codememory CLI not installed")
        env = {
            "HOME": str(self.root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "OPENCODE_CONFIG_PATH": str(self.root / "missing-opencode.json"),
            "MY_OPENCODE_RUNTIME_DB_PATH": str(self.root / "missing-runtime.db"),
            "MY_OPENCODE_SHARED_MEMORY_PATH": str(self.root / "missing-shared.db"),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(self.root / "missing-index.json"),
            "MY_OPENCODE_DIGEST_PATH": str(self.root / "missing-digest.json"),
            "CODEMEMORY_CONFIG_PATH": str(config),
            "MY_OPENCODE_CODEMEMORY_BIN": oc,
        }
        before = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        wrapper = str(ROOT / "scripts/slash_command_wrapper.py")
        commands = [
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/doctor_command.py"),
                "sqlite",
                "status",
                "--json",
                "--redact",
            ],
            [
                sys.executable,
                "-B",
                wrapper,
                "--script",
                wrapper,
                "--fixed-before",
                "doctor",
                "--raw-args",
                "sqlite status --json --redact",
            ],
        ]
        for command in commands:
            process = subprocess.run(
                command,
                cwd=self.root,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            self.assertIn(process.returncode, (0, 1), process.stderr)
            report = json.loads(process.stdout)
            self.assertEqual("sqlite-status", report["command"])
            self.assertEqual("", process.stderr)
            self.assertNotIn(str(self.root), process.stdout)
            self.assertFalse(db.exists())
            self.assertEqual(
                before,
                {
                    str(path.relative_to(self.root)): path.read_bytes()
                    for path in self.root.rglob("*")
                    if path.is_file()
                },
            )

    def test_real_cli_with_initialized_disposable_stores_preserves_bytes(self):
        oc = shutil.which("oc")
        if not oc:
            self.skipTest("native Codememory CLI not installed")
        self.runtime.unlink()
        self.shared.unlink()
        self.codememory.unlink()
        with sqlite3.connect(self.runtime) as conn:
            conn.executescript("""
                CREATE TABLE session (id TEXT PRIMARY KEY, parent_id TEXT, title TEXT,
                    time_created INTEGER, time_updated INTEGER);
                CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT,
                    time_created INTEGER, data TEXT);
                CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT,
                    session_id TEXT, time_created INTEGER, data TEXT);
                CREATE INDEX session_parent ON session(parent_id, time_updated);
                CREATE INDEX message_session ON message(session_id, time_created, id, data);
                CREATE INDEX part_message ON part(message_id, id);
            """)
        self.runtime.chmod(0o600)
        conn = shared_memory_runtime.connect(self.shared)
        conn.close()
        self.shared.chmod(0o600)
        self.index.write_text(
            json.dumps({"version": 1, "generated_at": None, "sessions": []})
        )
        self.digest.write_text("{}")
        config = self.root / "native.yaml"
        config.write_text(
            "version: 1\ndatabase:\n  backend: sqlite\n  path: "
            + json.dumps(str(self.codememory))
            + "\ncache:\n  enabled: false\n  dir: "
            + json.dumps(str(self.root / "cache"))
            + "\ndefaults:\n  scope_key: example/repo\n"
        )
        env = {
            "HOME": str(self.root),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "XDG_CONFIG_HOME": str(self.root / "xdg-config"),
            "XDG_CACHE_HOME": str(self.root / "xdg-cache"),
            "XDG_DATA_HOME": str(self.root / "xdg-data"),
            "OPENCODE_CONFIG_PATH": str(self.root / "missing-opencode.json"),
            "MY_OPENCODE_RUNTIME_DB_PATH": str(self.runtime),
            "MY_OPENCODE_SHARED_MEMORY_PATH": str(self.shared),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(self.index),
            "MY_OPENCODE_DIGEST_PATH": str(self.digest),
            "CODEMEMORY_CONFIG_PATH": str(config),
            "MY_OPENCODE_CODEMEMORY_BIN": oc,
        }
        setup = subprocess.run(
            [oc, "--config", str(config), "db", "migrate", "--format", "json"],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, setup.returncode, setup.stderr)
        before = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        process = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/doctor_command.py"),
                "sqlite",
                "status",
                "--json",
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertIn(process.returncode, (0, 1), process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual("", process.stderr)
        items = {item["store"]: item for item in report["stores"]}
        self.assertEqual(str(self.runtime), items["runtime_history"]["path"])
        self.assertEqual(str(self.shared), items["shared_memory"]["path"])
        self.assertEqual(str(self.codememory), items["codememory"]["path"])
        self.assertEqual("native_config", items["codememory"]["path_source"])
        self.assertEqual(
            before,
            {
                str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            },
        )


if __name__ == "__main__":
    unittest.main()
