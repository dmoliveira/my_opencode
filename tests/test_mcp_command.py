from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mcp_command


@contextmanager
def config_sandbox(content: str) -> Iterator[tuple[Path, dict[str, str]]]:
    with tempfile.TemporaryDirectory(prefix="mcp-command-test-") as raw_tmp:
        root = Path(raw_tmp)
        home = root / "home"
        home.mkdir()
        config = root / "opencode.json"
        config.write_text(content, encoding="utf-8")
        env = {
            **os.environ,
            "HOME": str(home),
            "OPENCODE_CONFIG_PATH": str(config),
            "CI": "true",
        }
        yield config, env


def run_command(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "mcp_command.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def custom_firecrawl(enabled: bool = True) -> dict[str, object]:
    return {
        "type": "local",
        "command": ["custom-firecrawl-wrapper", "FIRECRAWL_COMMAND_SECRET"],
        "url": "https://FIRECRAWL_URL_SECRET.invalid/mcp?token=private",
        "options": {
            "headers": {"authorization": "FIRECRAWL_HEADER_SECRET"},
            "nested": [1, {"keep": True}],
        },
        "enabled": enabled,
    }


class McpFirecrawlRetirementTest(unittest.TestCase):
    def test_absent_disable_is_byte_stable_and_never_creates_default(self) -> None:
        original = '{\n  "mcp": {},\n  "sentinel": "preserve-format"\n}\n'
        with config_sandbox(original) as (config, env):
            result = run_command(env, "disable", "firecrawl")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(original, config.read_text(encoding="utf-8"))
            self.assertNotIn("firecrawl-mcp", result.stdout + result.stderr)

    def test_retired_enable_and_profile_are_rejected_without_mutation(self) -> None:
        original = json.dumps(
            {"mcp": {"firecrawl": custom_firecrawl()}}, indent=2
        ) + "\n"
        for args in (("enable", "firecrawl"), ("profile", "firecrawl")):
            with self.subTest(args=args), config_sandbox(original) as (config, env):
                result = run_command(env, *args)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(original, config.read_text(encoding="utf-8"))
                self.assertNotIn("FIRECRAWL_", result.stdout + result.stderr)

    def test_named_disable_preserves_every_custom_field_except_enabled(self) -> None:
        entry = custom_firecrawl()
        original = {"mcp": {"firecrawl": entry}, "sentinel": "keep"}
        with config_sandbox(json.dumps(original, indent=2) + "\n") as (config, env):
            result = run_command(env, "disable", "firecrawl")
            self.assertEqual(0, result.returncode, result.stderr)
            saved = json.loads(config.read_text(encoding="utf-8"))
            expected = json.loads(json.dumps(entry))
            expected["enabled"] = False
            self.assertEqual(expected, saved["mcp"]["firecrawl"])
            self.assertEqual("keep", saved["sentinel"])
            self.assertNotIn("FIRECRAWL_", result.stdout + result.stderr)

    def test_every_profile_disables_existing_retired_entry_without_creating_absent(self) -> None:
        for profile, enabled_names in mcp_command.PROFILE_MAP.items():
            with self.subTest(profile=profile, state="configured"):
                entry = custom_firecrawl()
                payload = {"mcp": {"firecrawl": entry}}
                with config_sandbox(json.dumps(payload, indent=2) + "\n") as (config, env):
                    result = run_command(env, "profile", profile)
                    self.assertEqual(0, result.returncode, result.stderr)
                    saved = json.loads(config.read_text(encoding="utf-8"))
                    expected = json.loads(json.dumps(entry))
                    expected["enabled"] = False
                    self.assertEqual(expected, saved["mcp"]["firecrawl"])
                    for name in mcp_command.ACTIVE_SERVERS:
                        self.assertEqual(
                            name in enabled_names, saved["mcp"][name]["enabled"]
                        )
            with (
                self.subTest(profile=profile, state="absent"),
                config_sandbox('{"mcp": {}}\n') as (config, env),
            ):
                result = run_command(env, "profile", profile)
                self.assertEqual(0, result.returncode, result.stderr)
                saved = json.loads(config.read_text(encoding="utf-8"))
                self.assertNotIn("firecrawl", saved["mcp"])

    def test_enable_all_excludes_retired_and_disable_all_preserves_then_disables(self) -> None:
        entry = custom_firecrawl()
        payload = {"mcp": {"firecrawl": entry}}
        with config_sandbox(json.dumps(payload, indent=2) + "\n") as (config, env):
            enabled = run_command(env, "enable", "all")
            self.assertEqual(0, enabled.returncode, enabled.stderr)
            after_enable = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(entry, after_enable["mcp"]["firecrawl"])
            self.assertTrue(
                all(after_enable["mcp"][name]["enabled"] for name in mcp_command.ACTIVE_SERVERS)
            )

            disabled = run_command(env, "disable", "all")
            self.assertEqual(0, disabled.returncode, disabled.stderr)
            after_disable = json.loads(config.read_text(encoding="utf-8"))
            expected = json.loads(json.dumps(entry))
            expected["enabled"] = False
            self.assertEqual(expected, after_disable["mcp"]["firecrawl"])
            self.assertTrue(
                all(
                    after_disable["mcp"][name]["enabled"] is False
                    for name in mcp_command.ACTIVE_SERVERS
                )
            )

    def test_status_and_doctor_redact_retired_endpoint_and_command(self) -> None:
        entry = custom_firecrawl()
        original = json.dumps({"mcp": {"firecrawl": entry}}, indent=2) + "\n"
        with config_sandbox(original) as (config, env):
            outputs: dict[tuple[str, ...], str] = {}
            for args in (("status",), ("doctor",), ("doctor", "--json")):
                result = run_command(env, *args)
                self.assertEqual(0, result.returncode, result.stderr)
                output = result.stdout + result.stderr
                outputs[args] = output
                self.assertNotIn("FIRECRAWL_COMMAND_SECRET", output)
                self.assertNotIn("FIRECRAWL_URL_SECRET", output)
                self.assertNotIn("FIRECRAWL_HEADER_SECRET", output)
                self.assertEqual(original, config.read_text(encoding="utf-8"))

            report = json.loads(outputs[("doctor", "--json")])
            retired = report["servers"]["firecrawl"]
            self.assertEqual(
                {"name", "configured", "status", "reason"}, set(retired)
            )
            self.assertEqual("enabled", retired["status"])
            self.assertEqual("retired_disable_only", retired["reason"])
            self.assertTrue(
                any(
                    "/mcp disable firecrawl" in warning
                    for warning in report["warnings"]
                )
            )

    def test_absent_and_disabled_retired_state_are_healthy(self) -> None:
        cases = {
            "absent": {"mcp": {}},
            "disabled": {"mcp": {"firecrawl": custom_firecrawl(enabled=False)}},
        }
        for label, payload in cases.items():
            original = json.dumps(payload, indent=2) + "\n"
            with self.subTest(label=label), config_sandbox(original) as (config, env):
                result = run_command(env, "doctor", "--json")
                self.assertEqual(0, result.returncode, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual("PASS", report["result"])
                self.assertFalse(
                    any("firecrawl" in warning for warning in report["warnings"])
                )
                self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_help_exposes_firecrawl_only_as_disable_target(self) -> None:
        with config_sandbox('{"mcp": {}}\n') as (_config, env):
            result = run_command(env, "help")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("/mcp enable firecrawl", result.stdout)
        self.assertNotIn("profile firecrawl", result.stdout)
        self.assertIn("/mcp disable firecrawl", result.stdout)


class McpGoogleDriveTest(unittest.TestCase):
    def test_google_drive_enable_and_disable_use_the_canonical_remote(self) -> None:
        with config_sandbox('{"mcp": {}}\n') as (config, env):
            enabled = run_command(env, "enable", "google-drive")
            self.assertEqual(0, enabled.returncode, enabled.stderr)
            saved = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "type": "remote",
                    "url": "https://drivemcp.googleapis.com/mcp/v1",
                    "enabled": True,
                },
                saved["mcp"]["google-drive"],
            )

            disabled = run_command(env, "disable", "google-drive")
            self.assertEqual(0, disabled.returncode, disabled.stderr)
            saved = json.loads(config.read_text(encoding="utf-8"))
            self.assertIs(saved["mcp"]["google-drive"]["enabled"], False)
            self.assertEqual(
                "https://drivemcp.googleapis.com/mcp/v1",
                saved["mcp"]["google-drive"]["url"],
            )

    def test_google_drive_profile_is_standalone_and_minimal_turns_it_off(self) -> None:
        with config_sandbox('{"mcp": {}}\n') as (config, env):
            profile = run_command(env, "profile", "google-drive")
            self.assertEqual(0, profile.returncode, profile.stderr)
            saved = json.loads(config.read_text(encoding="utf-8"))
            self.assertTrue(saved["mcp"]["google-drive"]["enabled"])
            for name in mcp_command.ACTIVE_SERVERS:
                self.assertEqual(
                    name == "google-drive", saved["mcp"][name]["enabled"]
                )

            minimal = run_command(env, "profile", "minimal")
            self.assertEqual(0, minimal.returncode, minimal.stderr)
            saved = json.loads(config.read_text(encoding="utf-8"))
            self.assertFalse(saved["mcp"]["google-drive"]["enabled"])

    def test_google_drive_mutations_preserve_custom_fields(self) -> None:
        custom = {
            "type": "remote",
            "url": "https://custom.example/mcp",
            "headers": {"Authorization": "Bearer {env:GOOGLE_TOKEN}"},
            "options": {"timeout": 30},
            "enabled": False,
        }
        for action, expected_enabled in (
            (("enable", "google-drive"), True),
            (("disable", "google-drive"), False),
            (("profile", "google-drive"), True),
            (("profile", "minimal"), False),
        ):
            with self.subTest(action=action), config_sandbox(
                json.dumps({"mcp": {"google-drive": custom}}, indent=2) + "\n"
            ) as (config, env):
                result = run_command(env, *action)
                self.assertEqual(0, result.returncode, result.stderr)
                saved = json.loads(config.read_text(encoding="utf-8"))
                entry = saved["mcp"]["google-drive"]
                for key in ("type", "url", "headers", "options"):
                    self.assertEqual(custom[key], entry[key])
                self.assertIs(entry["enabled"], expected_enabled)

    def test_help_exposes_google_drive_profile_and_toggles(self) -> None:
        with config_sandbox('{"mcp": {}}\n') as (_config, env):
            result = run_command(env, "help")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("profile google-drive", result.stdout)
        self.assertIn("/mcp enable google-drive", result.stdout)
        self.assertIn("/mcp disable google-drive", result.stdout)


if __name__ == "__main__":
    unittest.main()
