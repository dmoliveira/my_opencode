from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mcp_command
from config_layering import ConfigTransactionError


class McpV2LayoutGuardTest(unittest.TestCase):
    def run_cli(
        self, home: Path, cwd: Path, *args: str, config: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_STATE_HOME": str(home / "state"),
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C",
            "CI": "true",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        if config is not None:
            env["OPENCODE_CONFIG_PATH"] = str(config)
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "mcp_command.py"), *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_native_and_ambiguous_layouts_refuse_mutations_without_changing_bytes(
        self,
    ) -> None:
        layouts = (
            {
                "context7": {
                    "type": "remote",
                    "url": "http://127.0.0.1:9/mcp",
                    "disabled": False,
                    "headers": {"Authorization": "MCP_SYNTHETIC_SECRET"},
                }
            },
            {},
            None,
            ["MCP_SYNTHETIC_SECRET"],
            {"type": "remote", "url": "MCP_SYNTHETIC_SECRET"},
        )
        actions = (
            ("disable", "context7"),
            ("enable", "context7"),
            ("disable", "all"),
            ("enable", "all"),
            ("disable", "firecrawl"),
            ("profile", "minimal"),
            ("profile", "google-drive"),
        )
        for layout in layouts:
            for action in actions:
                with (
                    self.subTest(layout=type(layout).__name__, action=action),
                    tempfile.TemporaryDirectory() as raw,
                ):
                    root = Path(raw)
                    home = root / "home"
                    home.mkdir()
                    config = root / "opencode.json"
                    original = (
                        json.dumps(
                            {
                                "mcp": {
                                    "servers": layout,
                                    "context7": {"enabled": True},
                                },
                                "keep": [1, 2],
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                    config.write_text(original, encoding="utf-8")
                    result = self.run_cli(home, root, *action, config=config)
                    self.assertNotEqual(
                        0, result.returncode, result.stdout + result.stderr
                    )
                    self.assertIn("mcp.servers", result.stdout + result.stderr)
                    self.assertNotIn(
                        "MCP_SYNTHETIC_SECRET", result.stdout + result.stderr
                    )
                    self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_status_and_json_doctor_refuse_native_layout_without_leaking_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            config = root / "opencode.json"
            original = (
                json.dumps(
                    {
                        "mcp": {
                            "servers": {
                                "context7": {
                                    "type": "remote",
                                    "url": "https://MCP_SYNTHETIC_SECRET.invalid/mcp",
                                    "headers": {
                                        "Authorization": "MCP_SYNTHETIC_SECRET"
                                    },
                                    "disabled": False,
                                }
                            }
                        }
                    },
                    indent=2,
                )
                + "\n"
            )
            config.write_text(original, encoding="utf-8")
            status = self.run_cli(home, root, "status", config=config)
            self.assertNotEqual(0, status.returncode)
            self.assertIn("mcp.servers", status.stdout + status.stderr)
            self.assertNotIn("MCP_SYNTHETIC_SECRET", status.stdout + status.stderr)
            doctor = self.run_cli(home, root, "doctor", "--json", config=config)
            self.assertNotEqual(0, doctor.returncode)
            self.assertNotIn("MCP_SYNTHETIC_SECRET", doctor.stdout + doctor.stderr)
            report = json.loads(doctor.stdout)
            self.assertEqual("FAIL", report["result"])
            self.assertEqual("mcp_native_layout_unsupported", report["reason_code"])
            self.assertIs(report["runtime_state_verified"], False)
            self.assertEqual({}, report["servers"])
            self.assertEqual(original, config.read_text(encoding="utf-8"))
            human_doctor = self.run_cli(home, root, "doctor", config=config)
            self.assertNotEqual(0, human_doctor.returncode)
            self.assertIn("result: FAIL", human_doctor.stdout)
            self.assertNotIn("MCP_SYNTHETIC_SECRET", human_doctor.stdout)
            help_result = self.run_cli(home, root, "help", config=config)
            self.assertEqual(0, help_result.returncode, help_result.stderr)
            self.assertNotIn(
                "MCP_SYNTHETIC_SECRET", help_result.stdout + help_result.stderr
            )

    def test_escaped_native_key_is_rejected_without_rewriting_config(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            config = root / "opencode.json"
            original = '{"mcp":{"\\u0073ervers":{"context7":{"disabled":false}}}}\n'
            config.write_text(original, encoding="utf-8")
            result = self.run_cli(home, root, "disable", "context7", config=config)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("mcp.servers", result.stdout + result.stderr)
            self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_guard_is_rechecked_inside_each_transaction_mutator(self) -> None:
        for action in (
            ("disable", "context7"),
            ("disable", "firecrawl"),
            ("profile", "minimal"),
        ):
            native = {"mcp": {"servers": {"context7": {"disabled": False}}}}
            original = copy.deepcopy(native)
            with (
                self.subTest(action=action),
                patch.object(
                    mcp_command,
                    "edit_config",
                    side_effect=lambda mutate, snapshot=native: mutate(snapshot),
                ),
            ):
                with self.assertRaises(ConfigTransactionError) as caught:
                    if action[0] == "profile":
                        mcp_command.apply_profile(action[1])
                    else:
                        mcp_command.set_enabled(*action)
                self.assertEqual(
                    "mcp_native_layout_unsupported", caught.exception.reason_code
                )
                self.assertEqual(original, native)

    def test_actual_transaction_rechecks_after_stale_preflight_view(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            config = root / "opencode.json"
            original = '{"mcp":{"servers":{"context7":{"disabled":false}}}}\n'
            config.write_text(original, encoding="utf-8")
            env = {"HOME": str(home), "OPENCODE_CONFIG_PATH": str(config)}
            stale_view = {"mcp": {"context7": {"enabled": True}}}
            with (
                patch.dict(os.environ, env),
                patch.object(mcp_command, "load_config", return_value=stale_view),
                self.assertRaises(ConfigTransactionError) as caught,
            ):
                mcp_command.main(["disable", "context7"])
            self.assertEqual(
                "mcp_native_layout_unsupported", caught.exception.reason_code
            )
            self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_native_user_layer_blocks_legacy_project_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            project = root / "project"
            user_config = home / ".config" / "opencode" / "opencode.json"
            project_config = project / ".opencode" / "my_opencode.json"
            user_config.parent.mkdir(parents=True)
            project_config.parent.mkdir(parents=True)
            user_bytes = '{"mcp":{"servers":{"context7":{"type":"remote","url":"http://127.0.0.1:9/mcp","disabled":false}}}}\n'
            project_bytes = '{"mcp":{"context7":{"enabled":true}}}\n'
            user_config.write_text(user_bytes, encoding="utf-8")
            project_config.write_text(project_bytes, encoding="utf-8")
            result = self.run_cli(home, project, "disable", "context7")
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("mcp.servers", result.stdout + result.stderr)
            self.assertEqual(user_bytes, user_config.read_text(encoding="utf-8"))
            self.assertEqual(project_bytes, project_config.read_text(encoding="utf-8"))

    def test_legacy_results_are_explicitly_config_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            home.mkdir()
            config = root / "opencode.json"
            config.write_text(
                '{"mcp":{"context7":{"type":"remote","url":"http://127.0.0.1:9/mcp","enabled":true}}}\n',
                encoding="utf-8",
            )
            status = self.run_cli(home, root, "status", config=config)
            self.assertEqual(0, status.returncode, status.stderr)
            self.assertIn("runtime state not verified", status.stdout.lower())
            doctor = self.run_cli(home, root, "doctor", "--json", config=config)
            self.assertEqual(0, doctor.returncode, doctor.stderr)
            report = json.loads(doctor.stdout)
            self.assertEqual("PASS", report["result"])
            self.assertIs(report["runtime_state_verified"], False)
            changed = self.run_cli(home, root, "disable", "context7", config=config)
            self.assertEqual(0, changed.returncode, changed.stderr)
            self.assertIn("runtime state not verified", changed.stdout.lower())
            self.assertIs(
                json.loads(config.read_text(encoding="utf-8"))["mcp"]["context7"][
                    "enabled"
                ],
                False,
            )
            for action in (("profile", "minimal"), ("disable", "firecrawl")):
                result = self.run_cli(home, root, *action, config=config)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("runtime state not verified", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
