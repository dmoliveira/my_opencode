from __future__ import annotations

import importlib
import json
import os
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

import gateway_plugin_bridge
import install_wizard
import plugin_command


class PluginConfigEntriesTest(unittest.TestCase):
    def test_gateway_tuple_detection_and_mutation_preserve_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            gateway = [
                gateway_plugin_bridge.gateway_plugin_spec(home),
                {"hooks": {"enabled": False}, "secret": "WAVE3_OPTION_SENTINEL"},
            ]
            external = ["@scope/external@1.2.3", {"mode": "safe"}]
            malformed = ["@scope/malformed", "not-an-object"]
            config = {
                "plugin": [gateway, "@superwhisper/opencode", external, malformed, gateway.copy()]
            }

            self.assertTrue(gateway_plugin_bridge.plugin_enabled(config, home))
            self.assertEqual(
                [gateway_plugin_bridge.gateway_plugin_spec(home)] * 2,
                gateway_plugin_bridge.gateway_plugin_entries(config, home),
            )
            gateway_plugin_bridge.set_plugin_enabled(config, home, True)
            self.assertEqual(gateway, config["plugin"][0])
            self.assertEqual(1, config["plugin"].count(gateway))
            self.assertIn(external, config["plugin"])
            self.assertIn(malformed, config["plugin"])

            gateway_plugin_bridge.set_plugin_enabled(config, home, False)
            self.assertFalse(gateway_plugin_bridge.plugin_enabled(config, home))
            self.assertIn(external, config["plugin"])
            self.assertIn(malformed, config["plugin"])

    def test_external_free_composition_removes_retired_and_preserves_unknown(self) -> None:
        notifier = [
            plugin_command.RETIRED_PLUGINS["notifier"],
            {"quiet": True},
        ]
        morph = [
            plugin_command.RETIRED_PLUGINS["morph"],
            {"tokenRef": "env:MORPH_API_KEY"},
        ]
        external = ["@scope/external", {"mode": "safe"}]
        malformed = ["@scope/malformed", 3]

        composed = plugin_command.compose_plugin_entries(
            [notifier, morph, external, malformed], []
        )

        self.assertEqual([external, malformed], composed)

    def test_named_disable_removes_only_exact_retired_alias_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            config_path = Path(tmp) / "opencode.json"
            notifier = [
                plugin_command.RETIRED_PLUGINS["notifier"],
                {"secret": "WAVE5_NOTIFIER_OPTION"},
            ]
            morph = [
                plugin_command.RETIRED_PLUGINS["morph"],
                {"tokenRef": "env:MORPH_API_KEY"},
            ]
            external = ["@scope/external", {"mode": "safe"}]
            malformed = [plugin_command.RETIRED_PLUGINS["notifier"], 3]
            original_entries = [
                notifier,
                morph,
                external,
                malformed,
                plugin_command.RETIRED_PLUGINS["worktree"],
            ]
            config_path.write_text(
                json.dumps({"plugin": original_entries}, indent=2) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "plugin_command.py"),
                    "disable",
                    "notifier",
                ],
                cwd=REPO_ROOT,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "OPENCODE_CONFIG_PATH": str(config_path),
                    "CI": "true",
                },
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("WAVE5_NOTIFIER_OPTION", result.stdout)
            self.assertNotIn("WAVE5_NOTIFIER_OPTION", result.stderr)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [
                    morph,
                    external,
                    malformed,
                    plugin_command.RETIRED_PLUGINS["worktree"],
                ],
                saved["plugin"],
            )

    def test_absent_named_disable_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            config_path = Path(tmp) / "opencode.json"
            original = (
                '{\n  "plugin": ["github:JRedeker/opencode-morph-fast-apply"],\n'
                '  "sentinel": "preserve-format"\n}\n'
            )
            config_path.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "plugin_command.py"),
                    "disable",
                    "notifier",
                ],
                cwd=REPO_ROOT,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "OPENCODE_CONFIG_PATH": str(config_path),
                    "CI": "true",
                },
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(original, config_path.read_text(encoding="utf-8"))

    def test_all_legacy_profiles_normalize_without_disclosing_tuple_options(self) -> None:
        for profile in ("lean", "stable", "experimental"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "home"
                home.mkdir()
                config_path = Path(tmp) / "opencode.json"
                gateway = "file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core"
                external = ["@scope/external", {"mode": "safe"}]
                malformed = ["@scope/malformed", 3]
                config_path.write_text(
                    json.dumps(
                        {
                            "plugin": [
                                [
                                    plugin_command.RETIRED_PLUGINS["notifier"],
                                    {"secret": "WAVE4_PRIVATE_PROFILE_OPTION"},
                                ],
                                plugin_command.RETIRED_PLUGINS["morph"],
                                plugin_command.RETIRED_PLUGINS["worktree"],
                                gateway,
                                external,
                                malformed,
                            ]
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                env = {
                    **os.environ,
                    "HOME": str(home),
                    "OPENCODE_CONFIG_PATH": str(config_path),
                    "CI": "true",
                }
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPTS_DIR / "plugin_command.py"),
                        "profile",
                        profile,
                    ],
                    cwd=REPO_ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertNotIn("WAVE4_PRIVATE_PROFILE_OPTION", result.stdout)
                self.assertNotIn("WAVE4_PRIVATE_PROFILE_OPTION", result.stderr)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual([gateway, external, malformed], saved["plugin"])

    def test_doctor_fails_retired_tuple_without_disclosing_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            config_path = Path(tmp) / "opencode.json"
            config_path.write_text(
                json.dumps(
                    {
                        "plugin": [
                            [
                                plugin_command.RETIRED_PLUGINS["notifier"],
                                {"secret": "WAVE4_PRIVATE_DOCTOR_OPTION"},
                            ]
                        ]
                    }
                ),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "OPENCODE_CONFIG_PATH": str(config_path),
                "CI": "true",
            }
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "plugin_command.py"), "doctor", "--json"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(1, result.returncode)
            report = json.loads(result.stdout)
            self.assertEqual("FAIL", report["result"])
            self.assertEqual("present", report["plugins"]["notifier"]["status"])
            self.assertNotIn("WAVE4_PRIVATE_DOCTOR_OPTION", result.stdout)
            self.assertNotIn("WAVE4_PRIVATE_DOCTOR_OPTION", result.stderr)

    def test_enable_retired_plugin_rejects_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            config_path = Path(tmp) / "opencode.json"
            original = json.dumps({"plugin": [["@scope/external", {"mode": "safe"}]]}, indent=2) + "\n"
            config_path.write_text(original, encoding="utf-8")
            env = {
                **os.environ,
                "HOME": str(home),
                "OPENCODE_CONFIG_PATH": str(config_path),
                "CI": "true",
            }
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "plugin_command.py"), "enable", "notifier"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("cannot be enabled", result.stdout)
            self.assertEqual(original, config_path.read_text(encoding="utf-8"))

    def test_installer_compatibility_profiles_normalize_without_enable_loop(self) -> None:
        for profile in ("lean", "stable", "experimental", "custom"):
            with self.subTest(profile=profile):
                self.assertEqual(
                    ("lean", []), install_wizard.normalize_plugin_profile(profile)
                )

        with patch.object(install_wizard, "run_repo_script", return_value=0) as run:
            self.assertEqual(
                0,
                install_wizard.apply_plugin_profile(
                    "custom", custom_aliases=["notifier"]
                ),
            )
        run.assert_called_once_with("plugin_command.py", "profile", "lean")

    def test_installer_persists_only_successful_logical_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "install-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "mcp": "minimal",
                            "notify": "focus",
                            "post_session": "disabled",
                            "sentinel": "preserved",
                        },
                        "managed": {},
                    }
                ),
                encoding="utf-8",
            )
            calls: list[tuple[str, tuple[str, ...]]] = []

            def run_repo_script(name: str, *args: str) -> int:
                calls.append((name, args))
                if name == "mcp_command.py":
                    return 1
                if name == "post_session_command.py" and args[1:3] == (
                    "command",
                    "make validate",
                ):
                    return 1
                return 0

            with (
                patch.object(install_wizard, "STATE_PATH", state_path),
                patch.object(
                    install_wizard,
                    "run_repo_script",
                    side_effect=run_repo_script,
                ),
            ):
                result = install_wizard.main(
                    [
                        "--non-interactive",
                        "--skip-extras",
                        "--plugin-profile",
                        "lean",
                        "--mcp-profile",
                        "research",
                        "--policy-profile",
                        "strict",
                        "--notify-profile",
                        "skip",
                        "--telemetry-profile",
                        "local",
                        "--post-session-profile",
                        "manual-validate",
                        "--model-profile",
                        "deep",
                        "--browser-profile",
                        "agent-browser",
                    ]
                )

            self.assertEqual(1, result)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("lean", saved["profiles"]["plugin"])
            self.assertEqual("minimal", saved["profiles"]["mcp"])
            self.assertEqual("focus", saved["profiles"]["notify"])
            self.assertEqual("disabled", saved["profiles"]["post_session"])
            self.assertEqual("strict", saved["profiles"]["policy"])
            self.assertEqual("local", saved["profiles"]["telemetry"])
            self.assertEqual("deep", saved["profiles"]["model_routing"])
            self.assertEqual("agent-browser", saved["profiles"]["browser"])
            self.assertEqual("preserved", saved["profiles"]["sentinel"])
            self.assertEqual(0o600, state_path.stat().st_mode & 0o777)
            post_calls = [call for call in calls if call[0] == "post_session_command.py"]
            self.assertEqual(3, len(post_calls))

    def test_installer_defaults_to_google_drive_mcp_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "install-state.json"
            calls: list[tuple[str, tuple[str, ...]]] = []

            def run_repo_script(name: str, *args: str) -> int:
                calls.append((name, args))
                return 0

            with (
                patch.object(install_wizard, "STATE_PATH", state_path),
                patch.object(install_wizard, "run_repo_script", side_effect=run_repo_script),
            ):
                result = install_wizard.main(
                    [
                        "--non-interactive",
                        "--skip-extras",
                        "--plugin-profile",
                        "lean",
                        "--policy-profile",
                        "balanced",
                        "--notify-profile",
                        "skip",
                        "--telemetry-profile",
                        "off",
                        "--post-session-profile",
                        "disabled",
                        "--model-profile",
                        "balanced",
                        "--browser-profile",
                        "playwright",
                    ]
                )

            self.assertEqual(0, result)
            self.assertIn(
                ("mcp_command.py", ("profile", "google-drive")),
                calls,
            )
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("google-drive", saved["profiles"]["mcp"])

    def test_installer_fresh_failure_does_not_claim_failed_or_skipped_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "install-state.json"

            def run_repo_script(name: str, *args: str) -> int:
                del args
                return 1 if name == "mcp_command.py" else 0

            with (
                patch.object(install_wizard, "STATE_PATH", state_path),
                patch.object(
                    install_wizard,
                    "run_repo_script",
                    side_effect=run_repo_script,
                ),
            ):
                result = install_wizard.main(
                    [
                        "--non-interactive",
                        "--skip-extras",
                        "--plugin-profile",
                        "lean",
                        "--mcp-profile",
                        "research",
                        "--policy-profile",
                        "balanced",
                        "--notify-profile",
                        "skip",
                        "--telemetry-profile",
                        "off",
                        "--post-session-profile",
                        "disabled",
                        "--model-profile",
                        "balanced",
                        "--browser-profile",
                        "playwright",
                    ]
                )

            self.assertEqual(1, result)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotIn("mcp", saved["profiles"])
            self.assertNotIn("notify", saved["profiles"])
            self.assertNotIn("opencode_nvim", saved["profiles"])
            self.assertNotIn("openchamber", saved["profiles"])

    def test_installer_state_write_is_atomic_private_and_preserves_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "install-state.json"
            with patch.object(install_wizard, "STATE_PATH", state_path):
                install_wizard.save_state(
                    {
                        "profiles": {"policy": "strict"},
                        "managed": {},
                        "unknown": {"sentinel": True},
                    }
                )

            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual({"sentinel": True}, saved["unknown"])
            self.assertEqual(0o600, state_path.stat().st_mode & 0o777)
            self.assertEqual([], list(state_path.parent.glob(f".{state_path.name}.*.tmp")))

    def test_installer_state_preflight_rejects_unsafe_targets_before_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root / "victim.json"
            victim.write_text('{"victim": true}\n', encoding="utf-8")
            state_path = root / "install-state.json"
            state_path.symlink_to(victim)
            with (
                patch.object(install_wizard, "STATE_PATH", state_path),
                patch.object(install_wizard, "run_repo_script") as run,
            ):
                result = install_wizard.main(["--non-interactive", "--skip-extras"])
            self.assertEqual(1, result)
            run.assert_not_called()
            self.assertEqual('{"victim": true}\n', victim.read_text(encoding="utf-8"))

            state_path.unlink()
            os.link(victim, state_path)
            with patch.object(install_wizard, "STATE_PATH", state_path):
                with self.assertRaisesRegex(OSError, "unsafe install state file"):
                    install_wizard.save_state({"profiles": {}, "managed": {}})
            self.assertEqual('{"victim": true}\n', victim.read_text(encoding="utf-8"))

            state_path.unlink()
            target_parent = root / "target-parent"
            target_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(target_parent, target_is_directory=True)
            with patch.object(
                install_wizard, "STATE_PATH", linked_parent / "state.json"
            ):
                with self.assertRaisesRegex(OSError, "unsafe install state parent"):
                    install_wizard.save_state({"profiles": {}, "managed": {}})

            writable_parent = root / "writable-parent"
            writable_parent.mkdir()
            writable_parent.chmod(0o777)
            with patch.object(
                install_wizard, "STATE_PATH", writable_parent / "state.json"
            ):
                with self.assertRaisesRegex(OSError, "writable install state parent"):
                    install_wizard.save_state({"profiles": {}, "managed": {}})

            writable_state = root / "writable-state.json"
            writable_state.write_text(
                '{"profiles": {}, "managed": {}}\n', encoding="utf-8"
            )
            writable_state.chmod(0o666)
            with (
                patch.object(install_wizard, "STATE_PATH", writable_state),
                patch.object(install_wizard, "run_repo_script") as writable_run,
            ):
                result = install_wizard.main(
                    ["--non-interactive", "--skip-extras"]
                )
            self.assertEqual(1, result)
            writable_run.assert_not_called()

    def test_blocked_gateway_enable_skips_compatibility_mutation(self) -> None:
        module = importlib.import_module("gateway_command")
        staged_status = {
            "plugin_dir_exists": False,
            "plugin_dist_exists": False,
            "bun_available": False,
            "hook_diagnostics": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "opencode.json"
            config = {"plugin": [["@scope/external", {"mode": "safe"}]]}
            with (
                patch.object(module, "load_config", return_value=(config, config_path)),
                patch.object(
                    module,
                    "status_payload",
                    side_effect=[staged_status, {"enabled": False}],
                ),
                patch.object(module, "ensure_file_plugin_compat") as compat,
                patch.object(module, "edit_layered_config") as save,
                patch.object(module, "emit"),
            ):
                self.assertEqual(1, module.command_enable(as_json=True))
            compat.assert_not_called()
            save.assert_not_called()

    def test_blocked_gateway_enable_leaves_config_bytes_and_options_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            config_path = Path(tmp) / "opencode.json"
            payload = {
                "plugin": [
                    ["@scope/external", {"secret": "WAVE3_PRIVATE_OPTION"}],
                    "@superwhisper/opencode",
                ]
            }
            original = json.dumps(payload, indent=2) + "\n"
            config_path.write_text(original, encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "OPENCODE_CONFIG_PATH": str(config_path),
                    "CI": "true",
                    "GIT_TERMINAL_PROMPT": "0",
                }
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "gateway_command.py"), "enable", "--json"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            self.assertEqual(original, config_path.read_text(encoding="utf-8"))
            self.assertNotIn("WAVE3_PRIVATE_OPTION", result.stdout)
            self.assertNotIn("WAVE3_PRIVATE_OPTION", result.stderr)


if __name__ == "__main__":
    unittest.main()
