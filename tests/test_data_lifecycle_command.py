from __future__ import annotations

import copy
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import data_lifecycle_command as lifecycle


def request(store="runtime_history", action="removal"):
    selectors = {
        "runtime_history": {"session_id": "ses_example", "cli_family": "opencode-v2"},
        "session_sidecars": {"session_id": "ses_example"},
        "shared_memory": {"scope": "repo", "namespace": "example", "older_days": 30},
        "codememory": {
            "scope": "example/repo",
            "artifact_kind": "memory",
            "record_id": "memory_1",
            "config": "/private/explicit/config.yaml",
        },
    }
    return {
        "version": 1,
        "store": store,
        "action": action,
        "selector": selectors[store],
    }


class DataLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)

    def private_file(self, name="request.json", payload=None):
        path = self.root / name
        path.write_text(json.dumps(request() if payload is None else payload))
        path.chmod(0o600)
        return path

    def test_all_stores_both_actions_return_blocked_nonexecuting_plans(self):
        for store in lifecycle.STORES:
            for action in ("removal", "redaction"):
                with self.subTest(store=store, action=action):
                    value = request(store, action)
                    original = copy.deepcopy(value)
                    plan = lifecycle.preview(value)
                    self.assertEqual(value, original)
                    self.assertEqual(plan["kind"], "offline_workflow_plan")
                    self.assertEqual(plan["status"], "blocked")
                    self.assertFalse(plan["apply_supported"])
                    self.assertFalse(plan["source_inspected"])
                    self.assertIsNone(plan["affected_count"])
                    self.assertEqual(plan, lifecycle.preview(value))
                    for step in plan["suggested_owner_steps"]:
                        self.assertFalse(step["executed"])
                        self.assertNotIn("--apply", step["argv"])
                        self.assertNotIn("delete", step["argv"])

    def test_discriminated_schema_rejects_unknown_and_missing_fields(self):
        for store in lifecycle.STORES:
            for level in ("top", "selector"):
                value = request(store)
                target = value if level == "top" else value["selector"]
                target["raw_prompt"] = "DO NOT ECHO"
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.preview(value)
                target.pop("raw_prompt")
                target.pop(next(iter(target)))
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.preview(value)
        for value in (
            None,
            [],
            True,
            "raw",
            {**request(), "version": True},
            {**request(), "version": 2},
            {**request(), "store": []},
            {**request(), "action": "erase"},
        ):
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.preview(value)

    def test_unsafe_selectors_and_moving_age_bounds(self):
        for value in ("", " padded ", "a\nb", "a\x00b", "--help", "a" * 257, [], True):
            candidate = request("shared_memory")
            candidate["selector"]["namespace"] = value
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.preview(candidate)
        for days in (0, -1, 36501, True, 1.0, "30", None):
            candidate = request("shared_memory")
            candidate["selector"]["older_days"] = days
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.preview(candidate)
        for days in (1, 36500):
            candidate = request("shared_memory")
            candidate["selector"]["older_days"] = days
            report = lifecycle.preview(candidate)
            self.assertIn(str(days), report["suggested_owner_steps"][1]["argv"])

    def test_owner_specific_selectors_do_not_grant_other_authority(self):
        for scope in ("session", "repo", "shared"):
            candidate = request("shared_memory")
            candidate["selector"]["scope"] = scope
            self.assertEqual(scope, lifecycle.preview(candidate)["selector"]["scope"])
        candidate = request("shared_memory")
        candidate["selector"]["scope"] = "project"
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.preview(candidate)
        for field, value in (
            ("cli_family", "opencode-v1"),
            ("session_id", "../other"),
            ("session_id", "--help"),
        ):
            candidate = request()
            candidate["selector"][field] = value
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.preview(candidate)
        for field, value in (
            ("artifact_kind", "task"),
            ("artifact_kind", []),
            ("record_id", "task_1"),
            ("record_id", "memory_01"),
            ("record_id", "doc_1"),
            ("config", "relative.yaml"),
            ("config", "/private/../other.yaml"),
        ):
            candidate = request("codememory")
            candidate["selector"][field] = value
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.preview(candidate)
        candidate = request("codememory")
        candidate["selector"].update(artifact_kind="document", record_id="doc_2")
        self.assertEqual("doc_2", lifecycle.preview(candidate)["selector"]["record_id"])

    def test_owner_generated_sidecar_fallback_ids_are_inert_and_store_specific(self):
        import session_metadata_index as owner

        examples = (
            ("/synthetic/project", "2025-01-01T00:00:00Z"),
            ("/synthetic/path with spaces", "2025-01-01T12:30:00.123456+05:30"),
            (
                "/synthetic/embedded::colon;'$(not-a-command)'",
                "2025-01-01T12:30:00-07:00",
            ),
            ("/synthetic/" + "a" * 500, "2025-01-01T00:00:00+00:00"),
            ("/", "not-an-iso-date"),
            ("/synthetic/\u00e9", "2025-01-01T00:00:00+00:00"),
        )
        for cwd, timestamp in examples:
            with (
                self.subTest(cwd=cwd),
                patch.dict(os.environ, {"OPENCODE_SESSION_ID": ""}),
            ):
                identifier = owner._session_id(timestamp, cwd)
                candidate = request("session_sidecars")
                candidate["selector"]["session_id"] = identifier
                with (
                    patch("builtins.open", side_effect=AssertionError("file opened")),
                    patch("os.stat", side_effect=AssertionError("file inspected")),
                    patch(
                        "subprocess.run", side_effect=AssertionError("owner invoked")
                    ),
                    patch(
                        "socket.socket", side_effect=AssertionError("network invoked")
                    ),
                ):
                    plan = lifecycle.preview(candidate)
                self.assertEqual("blocked", plan["status"])
                self.assertFalse(plan["source_inspected"])
                self.assertFalse(plan["apply_supported"])
                self.assertEqual(identifier, plan["selector"]["session_id"])
                self.assertEqual(
                    [
                        "python3",
                        "scripts/session_command.py",
                        "show",
                        identifier,
                        "--json",
                    ],
                    plan["suggested_owner_steps"][0]["argv"],
                )
                self.assertFalse(plan["suggested_owner_steps"][0]["executed"])
                self.assertTrue(
                    any("duplicate" in item.lower() for item in plan["limitations"])
                )
                runtime = request("runtime_history")
                runtime["selector"]["session_id"] = identifier
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.preview(runtime)

    def test_sidecar_fallback_rejects_malformed_or_unsafe_identifiers(self):
        token = "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"
        stamp = "2025-01-01T00:00:00+00:00"
        good = f"/synthetic/a::{stamp}::{token}"
        bad = (
            "",
            None,
            True,
            [],
            "a" * 257,
            f"relative::{stamp}::{token}",
            f"--help::{stamp}::{token}",
            f"::{stamp}::{token}",
            f"/synthetic/a::{stamp}::{'1' * 32}",
            f"/synthetic/a::{stamp}::aaaaaaaaaaaa4aaa0aaaaaaaaaaaaaaa",
            f"/synthetic/a::{stamp}::{token.upper()}",
            f"/synthetic/a::{stamp}::{token[:-1]}",
            f"/synthetic/a::2025-01-01T00:00:00::{token}",
            f"/synthetic/a::2025-01-01T00:00:00Z::{token}",
            f"/synthetic/a::2025-02-30T00:00:00+00:00::{token}",
            f"/synthetic/a::2025-01-01T00:00:00+24:00::{token}",
            f"/synthetic/a\nPRIVATE-CANARY::{stamp}::{token}",
            f"/synthetic/a\0PRIVATE-CANARY::{stamp}::{token}",
            f"/synthetic/a\u202ePRIVATE-CANARY::{stamp}::{token}",
            "/" + "a" * 8192 + f"::{stamp}::{token}",
        )
        candidate = request("session_sidecars")
        candidate["selector"]["session_id"] = good
        self.assertEqual(good, lifecycle.preview(candidate)["selector"]["session_id"])
        for identifier in bad:
            with self.subTest(identifier=repr(identifier)[:100]):
                candidate["selector"]["session_id"] = identifier
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.preview(candidate)

        suffix = f"::{stamp}::{token}"
        exact_limit = "/" + "a" * (8192 - len(suffix) - 1) + suffix
        candidate["selector"]["session_id"] = exact_limit
        self.assertEqual(
            exact_limit, lifecycle.preview(candidate)["selector"]["session_id"]
        )
        candidate["selector"]["session_id"] = "/" + exact_limit
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.preview(candidate)

    def test_invalid_fallback_cli_does_not_echo_private_values(self):
        candidate = request("session_sidecars")
        candidate["selector"]["session_id"] = (
            "/synthetic/PRIVATE-CANARY\n::2025-01-01T00:00:00+00:00::"
            "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"
        )
        source = self.private_file("invalid-private-request.json", candidate)
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with (
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(1, lifecycle.main(["preview", "--file", str(source)]))
        self.assertEqual("", error.getvalue())
        self.assertEqual("FAIL", json.loads(output.getvalue())["result"])
        self.assertNotIn("PRIVATE-CANARY", output.getvalue())
        self.assertNotIn(str(source), output.getvalue())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_owner_fallback_cli_is_nonexecuting_and_preserves_disposable_files(self):
        import session_metadata_index as owner

        with patch.dict(os.environ, {"OPENCODE_SESSION_ID": ""}):
            identifier = owner._session_id(
                "2025-01-01T00:00:00Z", "/synthetic/cwd::name;$(touch SHOULD_NOT_EXIST)"
            )
        index = self.private_file(
            "synthetic-index.json",
            {"version": 1, "sessions": [{"session_id": identifier}]},
        )
        candidate = request("session_sidecars")
        candidate["selector"]["session_id"] = identifier
        source = self.private_file("fallback-request.json", candidate)

        def snapshot():
            files = {}
            for path in self.root.iterdir():
                info = path.stat()
                files[path.name] = (
                    path.read_bytes(),
                    info.st_mode,
                    info.st_ino,
                    info.st_nlink,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )
            return files

        before = snapshot()
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.root),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(index),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        planned = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/data_lifecycle_command.py"),
                "preview",
                "--file",
                str(source),
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, planned.returncode, planned.stderr)
        self.assertEqual("", planned.stderr)
        plan = json.loads(planned.stdout)
        self.assertEqual(identifier, plan["selector"]["session_id"])
        self.assertEqual("blocked", plan["status"])
        self.assertEqual(before, snapshot())
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        shown = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/session_command.py"),
                "show",
                identifier,
                "--json",
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, shown.returncode, shown.stderr)
        self.assertEqual(identifier, json.loads(shown.stdout)["session"]["session_id"])
        self.assertEqual(before, snapshot())
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_counts_only_summary_drops_all_keys_scalars_and_topology(self):
        canary = "sk-PRIVATE-PROMPT-AND-PATH"
        value = {
            canary: [
                canary,
                {"path": canary, "token": 123456, "flag": True, "other": None},
            ]
        }
        summary = lifecycle.summarize(value, "runtime_history")
        rendered = json.dumps(summary)
        for private in (canary, "123456", '"path"', '"token"'):
            self.assertNotIn(private, rendered)
        self.assertFalse(summary["restorable"])
        self.assertFalse(summary["store_provenance_verified"])
        self.assertFalse(summary["content_included"])
        self.assertEqual(13, summary["structure"]["node_count"])
        self.assertEqual(3, summary["structure"]["maximum_depth"])
        for scalar in (None, "private", True, 42):
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.summarize(scalar, "shared_memory")

    def test_hostile_json_and_numeric_values_fail_without_content(self):
        cases = [
            b"not-json",
            b"\xff",
            b'{"a":1,"a":2}',
            b'{"a":1,"\\u0061":2}',
            b"[NaN]",
            b"[Infinity]",
            b"[-Infinity]",
            b"[1e999]",
            b'["\\ud800"]',
            b'{"\\udfff":1}',
            b"[" + b"9" * 129 + b"]",
        ]
        for raw in cases:
            with (
                self.subTest(raw=raw[:20]),
                self.assertRaises(lifecycle.LifecycleError),
            ):
                lifecycle.parse_json(raw)
        self.assertEqual([1e100], lifecycle.parse_json(b"[1e100]"))
        self.assertEqual(
            [int("9" * 128)], lifecycle.parse_json(b"[" + b"9" * 128 + b"]")
        )

    def test_depth_node_and_byte_limits_precede_unbounded_parsing(self):
        raw = b"[" * 33 + b"0" + b"]" * 33
        with patch.object(
            lifecycle.json, "loads", side_effect=AssertionError("parser reached")
        ):
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.parse_json(raw)
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.parse_json(b"[" + b"0," * 50000 + b"0]")
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.parse_json(b" " * (lifecycle.MAX_INPUT_BYTES + 1))
        self.assertEqual(
            32,
            lifecycle.structure(lifecycle.parse_json(b"[" * 32 + b"0" + b"]" * 32))[
                "maximum_depth"
            ],
        )
        self.assertEqual(
            50000,
            lifecycle.structure(lifecycle.parse_json(b"[" + b"0," * 49998 + b"0]"))[
                "node_count"
            ],
        )
        padded = b"[]" + b" " * (lifecycle.MAX_INPUT_BYTES - 2)
        self.assertEqual([], lifecycle.parse_json(padded))

    def test_private_reader_rejects_symlink_hardlink_fifo_and_permissions(self):
        original = self.private_file()
        symlink = self.root / "symlink"
        symlink.symlink_to(original)
        hardlink = self.root / "hardlink"
        os.link(original, hardlink)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for path in (symlink, hardlink, fifo):
            with self.assertRaises(lifecycle.SidecarSecurityError):
                lifecycle.load_json(path)
        hardlink.unlink()
        original.chmod(0o644)
        with self.assertRaises(lifecycle.SidecarSecurityError):
            lifecycle.load_json(original)
        original.chmod(0o600)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(lifecycle.SidecarSecurityError):
            lifecycle.load_json(alias / "request.json")

    def test_concurrent_file_change_fails_coherent_reader(self):
        path = self.private_file()
        import session_sidecar_security as security

        real = security._read_bounded

        def replace_source(*args):
            raw = real(*args)
            replacement = self.private_file("replacement.json", {"changed": True})
            replacement.replace(path)
            return raw

        with (
            patch.object(security, "_read_bounded", side_effect=replace_source),
            self.assertRaises(lifecycle.SidecarSecurityError),
        ):
            lifecycle.load_json(path)

    def test_unsupported_platform_is_a_safe_nonleaking_failure(self):
        path = self.private_file()
        with (
            patch("session_sidecar_security.sys.platform", "unsupported"),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(1, lifecycle.main(["preview", "--file", str(path)]))
        self.assertEqual(
            "data_lifecycle_input_unsafe_or_unavailable",
            json.loads(output.getvalue())["reason_code"],
        )
        self.assertNotIn(str(path), output.getvalue())

    def test_invalid_home_expansion_has_fixed_json_and_empty_stderr(self):
        process = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/data_lifecycle_command.py"),
                "preview",
                "--file",
                "~nonexistent_lifecycle_user_42/private-canary.json",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(1, process.returncode)
        self.assertEqual("", process.stderr)
        self.assertEqual(
            {
                "result": "FAIL",
                "reason_code": "data_lifecycle_input_unsafe_or_unavailable",
            },
            json.loads(process.stdout),
        )
        self.assertNotIn("private-canary", process.stdout)

    def test_bad_arguments_and_inputs_never_echo_canaries_on_either_stream(self):
        canary = "PRIVATE-UNKNOWN-ARGUMENT"
        bad = self.private_file("invalid.json", {canary: "private"})
        for argv in (
            ["preview", "--file", str(bad), "--unknown", canary],
            ["preview", "--file", str(bad)],
            ["summarize-export", "--file", str(bad), "--store", canary],
            ["apply", canary],
            [],
        ):
            with (
                redirect_stdout(io.StringIO()) as output,
                redirect_stderr(io.StringIO()) as error,
            ):
                self.assertEqual(1, lifecycle.main(argv))
            self.assertEqual("FAIL", json.loads(output.getvalue())["result"])
            self.assertNotIn(canary, output.getvalue() + error.getvalue())
            self.assertNotIn(str(bad), output.getvalue() + error.getvalue())

    def test_actual_cli_changes_no_store_or_file_and_has_no_owner_process_calls(self):
        stores = []
        for store in ("runtime_history", "shared_memory", "codememory"):
            path = self.root / f"{store}.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE private (secret TEXT)")
                conn.execute("INSERT INTO private VALUES ('PRIVATE-STORAGE-CANARY')")
            stores.append(path)
        sidecar = self.private_file(
            "index.json", {"PRIVATE-KEY": ["PRIVATE-PROMPT", 777888999]}
        )
        for store in lifecycle.STORES:
            path = self.private_file(f"{store}.json", request(store))
            before = {p.name: p.read_bytes() for p in self.root.iterdir()}
            process = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts/data_lifecycle_command.py"),
                    "preview",
                    "--file",
                    str(path),
                ],
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual("blocked", json.loads(process.stdout)["status"])
            self.assertEqual("", process.stderr)
            self.assertEqual(
                before, {p.name: p.read_bytes() for p in self.root.iterdir()}
            )
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        process = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/data_lifecycle_command.py"),
                "summarize-export",
                "--file",
                str(sidecar),
                "--store",
                "session_sidecars",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertNotIn("PRIVATE", process.stdout + process.stderr)
        self.assertNotIn("777888999", process.stdout + process.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        with (
            patch("subprocess.run", side_effect=AssertionError("owner invoked")),
            patch("socket.socket", side_effect=AssertionError("network invoked")),
        ):
            for store in lifecycle.STORES:
                lifecycle.preview(request(store))


if __name__ == "__main__":
    unittest.main()
