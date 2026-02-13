#!/usr/bin/env python3

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from hook_framework import HookRegistration, resolve_event_plan  # type: ignore
from hook_actions import (  # type: ignore
    continuation_reminder,
    error_recovery_hint,
    output_truncation_safety,
)
from model_routing_schema import (  # type: ignore
    default_schema,
    resolve_category,
    resolve_model_settings,
    validate_schema,
)
from keyword_mode_schema import resolve_prompt_modes  # type: ignore
from context_resilience import (  # type: ignore
    build_recovery_plan,
    prune_context,
    resolve_policy,
)
from rules_engine import (  # type: ignore
    discover_rules,
    parse_frontmatter,
    resolve_effective_rules,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCRIPT = REPO_ROOT / "scripts" / "plugin_command.py"
MCP_SCRIPT = REPO_ROOT / "scripts" / "mcp_command.py"
NOTIFY_SCRIPT = REPO_ROOT / "scripts" / "notify_command.py"
DIGEST_SCRIPT = REPO_ROOT / "scripts" / "session_digest.py"
TELEMETRY_SCRIPT = REPO_ROOT / "scripts" / "telemetry_command.py"
POST_SESSION_SCRIPT = REPO_ROOT / "scripts" / "post_session_command.py"
POLICY_SCRIPT = REPO_ROOT / "scripts" / "policy_command.py"
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "doctor_command.py"
CONFIG_SCRIPT = REPO_ROOT / "scripts" / "config_command.py"
STACK_SCRIPT = REPO_ROOT / "scripts" / "stack_profile_command.py"
INSTALL_WIZARD_SCRIPT = REPO_ROOT / "scripts" / "install_wizard.py"
NVIM_INTEGRATION_SCRIPT = REPO_ROOT / "scripts" / "nvim_integration_command.py"
BG_MANAGER_SCRIPT = REPO_ROOT / "scripts" / "background_task_manager.py"
REFACTOR_LITE_SCRIPT = REPO_ROOT / "scripts" / "refactor_lite_command.py"
HOOKS_SCRIPT = REPO_ROOT / "scripts" / "hooks_command.py"
MODEL_ROUTING_SCRIPT = REPO_ROOT / "scripts" / "model_routing_command.py"
ROUTING_SCRIPT = REPO_ROOT / "scripts" / "routing_command.py"
KEYWORD_MODE_SCRIPT = REPO_ROOT / "scripts" / "keyword_mode_command.py"
RULES_SCRIPT = REPO_ROOT / "scripts" / "rules_command.py"
RESILIENCE_SCRIPT = REPO_ROOT / "scripts" / "context_resilience_command.py"
BASE_CONFIG = REPO_ROOT / "opencode.json"


def run_script(
    script: Path, cfg: Path, home: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OPENCODE_CONFIG_PATH"] = str(cfg)
    env["HOME"] = str(home)
    env.pop("SUPERMEMORY_API_KEY", None)
    env.pop("MORPH_API_KEY", None)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def run_script_layered(
    script: Path, home: Path, cwd: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("OPENCODE_CONFIG_PATH", None)
    env.pop("SUPERMEMORY_API_KEY", None)
    env.pop("MORPH_API_KEY", None)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=cwd,
    )


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parse_json_output(text: str) -> dict:
    return json.loads(text)


def load_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class LocalTcpProbeServer:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                conn.close()
            except OSError:
                pass

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.thread.join(timeout=1)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        home = tmp / "home"
        home.mkdir(parents=True, exist_ok=True)
        cfg = tmp / "opencode.json"
        shutil.copy2(BASE_CONFIG, cfg)

        # Plugin profile lean should pass doctor.
        result = run_script(
            PLUGIN_SCRIPT, tmp / "opencode.json", home, "profile", "lean"
        )
        expect(result.returncode == 0, f"plugin profile lean failed: {result.stderr}")

        result = run_script(PLUGIN_SCRIPT, cfg, home, "doctor", "--json")
        expect(
            result.returncode == 0,
            f"plugin doctor --json (lean) failed: {result.stderr}",
        )
        report = parse_json_output(result.stdout)
        expect(
            report.get("result") == "PASS", "plugin doctor should pass for lean profile"
        )

        # Plugin stable should fail doctor without keys in isolated HOME.
        result = run_script(PLUGIN_SCRIPT, cfg, home, "profile", "stable")
        expect(result.returncode == 0, f"plugin profile stable failed: {result.stderr}")

        result = run_script(PLUGIN_SCRIPT, cfg, home, "doctor", "--json")
        expect(
            result.returncode == 1,
            "plugin doctor stable should fail when keys are absent",
        )
        report = parse_json_output(result.stdout)
        problems = "\n".join(report.get("problems", []))
        expect("supermemory enabled" in problems, "expected supermemory key problem")
        expect("wakatime enabled" in problems, "expected wakatime key problem")

        result = run_script(PLUGIN_SCRIPT, cfg, home, "setup-keys")
        expect(result.returncode == 0, f"plugin setup-keys failed: {result.stderr}")
        expect(
            "[supermemory]" in result.stdout, "setup-keys missing supermemory section"
        )
        expect("[wakatime]" in result.stdout, "setup-keys missing wakatime section")

        # MCP minimal should pass with disabled warning.
        result = run_script(MCP_SCRIPT, cfg, home, "profile", "minimal")
        expect(result.returncode == 0, f"mcp profile minimal failed: {result.stderr}")

        result = run_script(MCP_SCRIPT, cfg, home, "doctor", "--json")
        expect(
            result.returncode == 0,
            f"mcp doctor --json (minimal) failed: {result.stderr}",
        )
        report = parse_json_output(result.stdout)
        expect(
            report.get("result") == "PASS", "mcp doctor should pass for minimal profile"
        )
        warnings = "\n".join(report.get("warnings", []))
        expect(
            "all MCP servers are disabled" in warnings, "expected disabled MCP warning"
        )

        # MCP research should enable both servers and pass.
        result = run_script(MCP_SCRIPT, cfg, home, "profile", "research")
        expect(result.returncode == 0, f"mcp profile research failed: {result.stderr}")

        result = run_script(MCP_SCRIPT, cfg, home, "doctor", "--json")
        expect(
            result.returncode == 0,
            f"mcp doctor --json (research) failed: {result.stderr}",
        )
        report = parse_json_output(result.stdout)
        expect(
            report.get("result") == "PASS",
            "mcp doctor should pass for research profile",
        )
        expect(
            report.get("servers", {}).get("context7", {}).get("status") == "enabled",
            "context7 should be enabled in research profile",
        )
        expect(
            report.get("servers", {}).get("gh_grep", {}).get("status") == "enabled",
            "gh_grep should be enabled in research profile",
        )

        # Layered config precedence: project override should beat user override.
        project_dir = tmp / "project"
        (project_dir / ".opencode").mkdir(parents=True, exist_ok=True)
        user_cfg_dir = home / ".config" / "opencode"
        user_cfg_dir.mkdir(parents=True, exist_ok=True)

        (user_cfg_dir / "my_opencode.json").write_text(
            json.dumps(
                {
                    "plugin": ["@mohak34/opencode-notifier@latest"],
                    "mcp": {"context7": {"enabled": False}},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (project_dir / ".opencode" / "my_opencode.jsonc").write_text(
            """
            {
              // project override wins over user
              "plugin": [
                "@mohak34/opencode-notifier@latest",
                "opencode-supermemory",
              ],
              "mcp": {
                "context7": { "enabled": true },
              },
            }
            """,
            encoding="utf-8",
        )

        result = run_script_layered(PLUGIN_SCRIPT, home, project_dir, "status")
        expect(result.returncode == 0, f"plugin layered status failed: {result.stderr}")
        expect(
            "supermemory: enabled" in result.stdout,
            "project layered config should enable supermemory",
        )
        expect(
            "config: " in result.stdout
            and str(project_dir / ".opencode" / "my_opencode.jsonc") in result.stdout,
            "layered writes should target highest-precedence existing config",
        )

        result = run_script_layered(MCP_SCRIPT, home, project_dir, "status")
        expect(result.returncode == 0, f"mcp layered status failed: {result.stderr}")
        expect(
            "context7: enabled" in result.stdout,
            "project layered config should override user mcp context7 to enabled",
        )

        notify_path = home / ".config" / "opencode" / "opencode-notifications.json"
        notify_env = os.environ.copy()
        notify_env["OPENCODE_NOTIFICATIONS_PATH"] = str(notify_path)

        def run_notify(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(NOTIFY_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=notify_env,
                check=False,
            )

        result = run_notify("profile", "focus")
        expect(result.returncode == 0, f"notify profile focus failed: {result.stderr}")
        cfg = load_json_file(notify_path)
        expect(cfg.get("enabled") is True, "notify focus should keep global enabled")
        expect(
            cfg.get("events", {}).get("complete") is False,
            "notify focus should disable complete event",
        )
        expect(
            cfg.get("channels", {}).get("error", {}).get("visual") is True,
            "notify focus should keep error visual on",
        )

        result = run_notify("disable", "sound")
        expect(result.returncode == 0, f"notify disable sound failed: {result.stderr}")
        cfg = load_json_file(notify_path)
        expect(
            cfg.get("sound", {}).get("enabled") is False,
            "notify disable sound should set sound.enabled false",
        )

        result = run_notify("channel", "permission", "visual", "off")
        expect(
            result.returncode == 0,
            f"notify channel permission visual off failed: {result.stderr}",
        )
        cfg = load_json_file(notify_path)
        expect(
            cfg.get("channels", {}).get("permission", {}).get("visual") is False,
            "notify channel should set permission.visual off",
        )

        result = run_notify("status")
        expect(result.returncode == 0, f"notify status failed: {result.stderr}")
        expect("config:" in result.stdout, "notify status should print config path")

        result = run_notify("doctor", "--json")
        expect(result.returncode == 0, f"notify doctor --json failed: {result.stderr}")
        report = parse_json_output(result.stdout)
        expect(report.get("result") == "PASS", "notify doctor should pass")

        digest_path = home / ".config" / "opencode" / "digests" / "selftest.json"
        digest_env = os.environ.copy()
        digest_env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)

        result = subprocess.run(
            [sys.executable, str(DIGEST_SCRIPT), "run", "--reason", "selftest"],
            capture_output=True,
            text=True,
            env=digest_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"digest run failed: {result.stderr}")
        expect(digest_path.exists(), "digest run should create digest file")
        digest = load_json_file(digest_path)
        expect(digest.get("reason") == "selftest", "digest reason should match")

        result = subprocess.run(
            [sys.executable, str(DIGEST_SCRIPT), "show", "--path", str(digest_path)],
            capture_output=True,
            text=True,
            env=digest_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"digest show failed: {result.stderr}")
        expect("reason: selftest" in result.stdout, "digest show should print reason")

        result = subprocess.run(
            [
                sys.executable,
                str(DIGEST_SCRIPT),
                "doctor",
                "--path",
                str(digest_path),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=digest_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"digest doctor --json failed: {result.stderr}")
        report = parse_json_output(result.stdout)
        expect(report.get("result") == "PASS", "digest doctor should pass")

        layered_cfg_path = tmp / "layered-commands.json"
        shutil.copy2(BASE_CONFIG, layered_cfg_path)
        telemetry_path = home / ".config" / "opencode" / "opencode-telemetry.json"
        session_cfg_path = home / ".config" / "opencode" / "opencode-session.json"
        policy_path = home / ".config" / "opencode" / "opencode-policy.json"
        telemetry_env = os.environ.copy()
        telemetry_env["OPENCODE_CONFIG_PATH"] = str(layered_cfg_path)
        telemetry_env["HOME"] = str(home)

        def run_telemetry(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(TELEMETRY_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=telemetry_env,
                check=False,
            )

        result = run_telemetry("profile", "local")
        expect(
            result.returncode == 0, f"telemetry profile local failed: {result.stderr}"
        )

        server = LocalTcpProbeServer()
        server.start()
        try:
            result = run_telemetry(
                "set",
                "endpoint",
                f"http://127.0.0.1:{server.port}/opencode/events",
            )
            expect(
                result.returncode == 0,
                f"telemetry set endpoint failed: {result.stderr}",
            )

            result = run_telemetry("set", "timeout", "800")
            expect(
                result.returncode == 0, f"telemetry set timeout failed: {result.stderr}"
            )

            result = run_telemetry("disable", "question")
            expect(
                result.returncode == 0,
                f"telemetry disable question failed: {result.stderr}",
            )

            cfg = load_json_file(layered_cfg_path)
            telemetry_cfg = cfg.get("telemetry", {})
            expect(
                telemetry_cfg.get("enabled") is True,
                "telemetry should remain enabled",
            )
            expect(
                telemetry_cfg.get("timeout_ms") == 800,
                "telemetry timeout should be updated",
            )
            expect(
                telemetry_cfg.get("events", {}).get("question") is False,
                "telemetry question event should be disabled",
            )

            result = run_telemetry("doctor", "--json")
            expect(
                result.returncode == 0,
                f"telemetry doctor --json failed: {result.stderr}",
            )
            report = parse_json_output(result.stdout)
            expect(report.get("result") == "PASS", "telemetry doctor should pass")
            expect(
                report.get("reachability", {}).get("ok") is True,
                "telemetry doctor should report endpoint reachable",
            )
        finally:
            server.close()

        post_env = os.environ.copy()
        post_env["OPENCODE_CONFIG_PATH"] = str(layered_cfg_path)
        post_env["HOME"] = str(home)
        post_env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)

        def run_post_session(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(POST_SESSION_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=post_env,
                check=False,
            )

        result = run_post_session(
            "set",
            "command",
            "python3 -c \"import os,pathlib;pathlib.Path(os.environ['MY_OPENCODE_DIGEST_PATH'] + '.hook').write_text(os.environ.get('MY_OPENCODE_POST_REASON',''))\"",
        )
        expect(
            result.returncode == 0,
            f"post-session set command failed: {result.stderr}",
        )

        result = run_post_session("set", "run-on", "manual,exit")
        expect(
            result.returncode == 0,
            f"post-session set run-on failed: {result.stderr}",
        )

        result = run_post_session("enable")
        expect(result.returncode == 0, f"post-session enable failed: {result.stderr}")

        result = subprocess.run(
            [
                sys.executable,
                str(DIGEST_SCRIPT),
                "run",
                "--reason",
                "manual",
                "--run-post",
            ],
            capture_output=True,
            text=True,
            env=post_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            result.returncode == 0,
            f"digest run --run-post failed: {result.stderr}",
        )

        hook_path = Path(str(digest_path) + ".hook")
        expect(
            hook_path.exists(), "post-session command should create hook output file"
        )
        expect(
            hook_path.read_text(encoding="utf-8") == "manual",
            "post-session command should receive manual reason",
        )

        digest_after = load_json_file(digest_path)
        post_info = digest_after.get("post_session", {})
        expect(
            post_info.get("attempted") is True, "digest should record post-session run"
        )
        expect(
            post_info.get("exit_code") == 0, "post-session command should exit cleanly"
        )

        policy_env = os.environ.copy()
        policy_env["OPENCODE_CONFIG_PATH"] = str(layered_cfg_path)
        policy_env["HOME"] = str(home)

        def run_policy(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(POLICY_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=policy_env,
                check=False,
            )

        result = run_policy("profile", "strict")
        expect(result.returncode == 0, f"policy profile strict failed: {result.stderr}")

        layered_cfg = load_json_file(layered_cfg_path)
        notify_cfg = layered_cfg.get("notify", {})
        expect(
            notify_cfg.get("events", {}).get("complete") is False,
            "strict policy should disable complete event",
        )
        expect(
            notify_cfg.get("channels", {}).get("permission", {}).get("visual") is True,
            "strict policy should keep permission visual enabled",
        )

        result = run_policy("status")
        expect(result.returncode == 0, f"policy status failed: {result.stderr}")
        expect("profile: strict" in result.stdout, "policy status should report strict")

        notify_policy_path = (
            home / ".config" / "opencode" / "opencode-notifications.json"
        )
        notify_policy_path.parent.mkdir(parents=True, exist_ok=True)
        notify_policy_path.write_text(
            json.dumps(
                {
                    "events": {"complete": False},
                    "channels": {"permission": {"visual": True}},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        config_env = os.environ.copy()
        config_env["OPENCODE_CONFIG_DIR"] = str(home / ".config" / "opencode")
        config_env["HOME"] = str(home)

        def run_config(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(CONFIG_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=config_env,
                check=False,
            )

        result = run_config("backup", "--name", "selftest")
        expect(result.returncode == 0, f"config backup failed: {result.stderr}")
        backup_line = next(
            (
                line
                for line in result.stdout.splitlines()
                if line.startswith("backup: ")
            ),
            "",
        )
        expect(bool(backup_line), "config backup should output backup id")
        backup_id = backup_line.replace("backup: ", "", 1).strip()

        notify_policy_path.write_text('{"enabled": false}\n', encoding="utf-8")

        result = run_config("restore", backup_id)
        expect(result.returncode == 0, f"config restore failed: {result.stderr}")

        restored_notify = load_json_file(notify_policy_path)
        expect(
            restored_notify.get("events", {}).get("complete") is False,
            "config restore should recover previous notify file",
        )

        result = run_config("list")
        expect(result.returncode == 0, f"config list failed: {result.stderr}")
        expect(backup_id in result.stdout, "config list should include created backup")

        layered_project_dir = tmp / "layered-project"
        (layered_project_dir / ".opencode").mkdir(parents=True, exist_ok=True)
        (layered_project_dir / ".opencode" / "my_opencode.jsonc").write_text(
            """
            {
              // project layered config for selftest
              "plugin": ["@mohak34/opencode-notifier@latest"],
            }
            """,
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(CONFIG_SCRIPT), "layers"],
            capture_output=True,
            text=True,
            env=config_env,
            check=False,
            cwd=layered_project_dir,
        )
        expect(result.returncode == 0, f"config layers failed: {result.stderr}")
        expect("config layers" in result.stdout, "config layers should print heading")
        expect(
            "project_jsonc" in result.stdout,
            "config layers should include project_jsonc layer",
        )

        result = subprocess.run(
            [sys.executable, str(CONFIG_SCRIPT), "layers", "--json"],
            capture_output=True,
            text=True,
            env=config_env,
            check=False,
            cwd=layered_project_dir,
        )
        expect(
            result.returncode == 0,
            f"config layers --json failed: {result.stderr}",
        )
        layers_report = parse_json_output(result.stdout)
        expect(
            isinstance(layers_report.get("layers"), list),
            "config layers --json should emit layers list",
        )
        project_layer = next(
            (
                layer
                for layer in layers_report.get("layers", [])
                if layer.get("name") == "project_jsonc"
            ),
            {},
        )
        expect(
            project_layer.get("exists") is True,
            "config layers --json should mark project_jsonc as active when present",
        )
        expect(
            str(layers_report.get("write_path", "")).endswith(
                "/.opencode/my_opencode.jsonc"
            ),
            "config layers --json should choose project_jsonc write path",
        )

        stack_state_path = home / ".config" / "opencode" / "opencode-stack-profile.json"
        stack_env = os.environ.copy()
        stack_env["HOME"] = str(home)
        stack_env["MY_OPENCODE_STACK_PROFILE_PATH"] = str(stack_state_path)
        stack_env["MY_OPENCODE_POLICY_PATH"] = str(policy_path)
        stack_env["OPENCODE_NOTIFICATIONS_PATH"] = str(notify_policy_path)
        stack_env["OPENCODE_CONFIG_PATH"] = str(layered_cfg_path)
        stack_env["OPENCODE_TELEMETRY_PATH"] = str(telemetry_path)
        stack_env["MY_OPENCODE_SESSION_CONFIG_PATH"] = str(session_cfg_path)

        def run_stack(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(STACK_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=stack_env,
                check=False,
                cwd=REPO_ROOT,
            )

        result = run_stack("apply", "focus")
        expect(result.returncode == 0, f"stack apply focus failed: {result.stderr}")

        notify_after_focus = load_json_file(notify_policy_path)
        telemetry_after_focus = load_json_file(telemetry_path)
        post_after_focus = load_json_file(session_cfg_path)
        policy_after_focus = load_json_file(policy_path)
        expect(
            notify_after_focus.get("events", {}).get("complete") is False,
            "focus stack should disable complete notifications",
        )
        expect(
            telemetry_after_focus.get("enabled") is False,
            "focus stack should disable telemetry",
        )
        expect(
            post_after_focus.get("post_session", {}).get("enabled") is False,
            "focus stack should disable post-session hook",
        )
        expect(
            policy_after_focus.get("current") == "strict",
            "focus stack should apply strict policy",
        )

        model_focus = subprocess.run(
            [sys.executable, str(MODEL_ROUTING_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=stack_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            model_focus.returncode == 0,
            f"model-routing status after focus failed: {model_focus.stderr}",
        )
        model_focus_report = parse_json_output(model_focus.stdout)
        expect(
            model_focus_report.get("active_category") == "deep",
            "focus stack should set deep model routing category",
        )

        result = run_stack("apply", "quiet-ci")
        expect(result.returncode == 0, f"stack apply quiet-ci failed: {result.stderr}")
        post_after_quiet = load_json_file(session_cfg_path)
        expect(
            post_after_quiet.get("post_session", {}).get("enabled") is True,
            "quiet-ci stack should enable post-session",
        )
        expect(
            post_after_quiet.get("post_session", {}).get("command") == "make validate",
            "quiet-ci stack should set validate command",
        )

        model_quiet = subprocess.run(
            [sys.executable, str(MODEL_ROUTING_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=stack_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            model_quiet.returncode == 0,
            f"model-routing status after quiet-ci failed: {model_quiet.stderr}",
        )
        model_quiet_report = parse_json_output(model_quiet.stdout)
        expect(
            model_quiet_report.get("active_category") == "quick",
            "quiet-ci stack should set quick model routing category",
        )

        result = run_stack("status")
        expect(result.returncode == 0, f"stack status failed: {result.stderr}")
        expect(
            "profile: quiet-ci" in result.stdout, "stack status should report quiet-ci"
        )

        bg_dir = home / ".config" / "opencode" / "my_opencode" / "bg"
        bg_env = os.environ.copy()
        bg_env["HOME"] = str(home)
        bg_env["MY_OPENCODE_BG_DIR"] = str(bg_dir)
        bg_env["OPENCODE_NOTIFICATIONS_PATH"] = str(tmp / "bg-notify.json")

        (tmp / "bg-notify.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "sound": {"enabled": False},
                    "visual": {"enabled": True},
                    "events": {
                        "complete": True,
                        "error": True,
                        "permission": True,
                        "question": True,
                    },
                    "channels": {
                        "complete": {"sound": False, "visual": True},
                        "error": {"sound": False, "visual": True},
                        "permission": {"sound": False, "visual": True},
                        "question": {"sound": False, "visual": True},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        def run_bg(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(BG_MANAGER_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=bg_env,
                check=False,
                cwd=REPO_ROOT,
            )

        result = run_bg(
            "enqueue",
            "--timeout-seconds",
            "30",
            "--",
            sys.executable,
            "-c",
            'print("bg-ok")',
        )
        expect(result.returncode == 0, f"bg enqueue failed: {result.stderr}")
        bg_job_id = ""
        for line in result.stdout.splitlines():
            if line.startswith("id: "):
                bg_job_id = line.replace("id: ", "", 1).strip()
                break
        expect(bool(bg_job_id), "bg enqueue should print id")

        result = run_bg("run", "--id", bg_job_id)
        expect(result.returncode == 0, f"bg run failed: {result.stderr}")
        expect(bg_job_id in result.stdout, "bg run output should include job id")
        expect(
            "[bg notify][complete]" in result.stderr,
            "bg run should emit completion notification when notify stack allows it",
        )

        result = run_bg("read", bg_job_id, "--json")
        expect(result.returncode == 0, f"bg read json failed: {result.stderr}")
        bg_report = parse_json_output(result.stdout)
        expect(
            bg_report.get("job", {}).get("status") == "completed",
            "bg run should complete successful job",
        )
        expect("bg-ok" in bg_report.get("log_tail", ""), "bg log should include output")

        result = run_bg(
            "enqueue",
            "--timeout-seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(2)",
        )
        expect(
            result.returncode == 0, f"bg enqueue timeout job failed: {result.stderr}"
        )
        timeout_job_id = ""
        for line in result.stdout.splitlines():
            if line.startswith("id: "):
                timeout_job_id = line.replace("id: ", "", 1).strip()
                break
        expect(bool(timeout_job_id), "bg timeout enqueue should print id")

        result = run_bg("run", "--id", timeout_job_id)
        expect(result.returncode == 1, "bg timeout run should fail with non-zero")
        expect(
            "[bg notify][error]" in result.stderr,
            "bg timeout run should emit error notification",
        )

        result = run_bg("read", timeout_job_id, "--json")
        expect(result.returncode == 0, f"bg read timeout json failed: {result.stderr}")
        timeout_report = parse_json_output(result.stdout)
        expect(
            timeout_report.get("job", {}).get("status") == "failed",
            "bg timeout job should be marked failed",
        )
        expect(
            "timed out" in str(timeout_report.get("job", {}).get("summary", "")),
            "bg timeout job should include timeout summary",
        )

        result = run_bg("enqueue", "--", sys.executable, "-c", 'print("queued")')
        expect(result.returncode == 0, f"bg enqueue cancel job failed: {result.stderr}")
        cancel_job_id = ""
        for line in result.stdout.splitlines():
            if line.startswith("id: "):
                cancel_job_id = line.replace("id: ", "", 1).strip()
                break
        expect(bool(cancel_job_id), "bg cancel enqueue should print id")

        result = run_bg("cancel", cancel_job_id)
        expect(result.returncode == 0, f"bg cancel failed: {result.stderr}")

        result = run_bg("read", cancel_job_id, "--json")
        expect(
            result.returncode == 0, f"bg read cancelled json failed: {result.stderr}"
        )
        cancel_report = parse_json_output(result.stdout)
        expect(
            cancel_report.get("job", {}).get("status") == "cancelled",
            "bg cancelled job should be marked cancelled",
        )

        result = run_bg("cleanup", "--max-terminal", "1", "--json")
        expect(result.returncode == 0, f"bg cleanup failed: {result.stderr}")
        cleanup_report = parse_json_output(result.stdout)
        expect(
            int(cleanup_report.get("pruned", 0)) >= 1,
            "bg cleanup should prune terminal jobs when max-terminal is low",
        )

        result = run_bg("status")
        expect(result.returncode == 0, f"bg status failed: {result.stderr}")
        expect(
            "jobs_total:" in result.stdout, "bg status should print aggregate counts"
        )

        result = run_bg("status", "--json")
        expect(result.returncode == 0, f"bg status json failed: {result.stderr}")
        bg_status_report = parse_json_output(result.stdout)
        expect(
            isinstance(bg_status_report.get("counts"), dict),
            "bg status --json should return counts object",
        )

        result = run_bg("start", "--", sys.executable, "-c", 'print("bg-start")')
        expect(result.returncode == 0, f"bg start failed: {result.stderr}")
        start_job_id = ""
        for line in result.stdout.splitlines():
            if line.startswith("id: "):
                start_job_id = line.replace("id: ", "", 1).strip()
                break
        expect(bool(start_job_id), "bg start should print job id")

        start_done = False
        for _ in range(30):
            result = run_bg("read", start_job_id, "--json")
            expect(result.returncode == 0, f"bg read start job failed: {result.stderr}")
            start_report = parse_json_output(result.stdout)
            if start_report.get("job", {}).get("status") == "completed":
                start_done = True
                expect(
                    "bg-start" in start_report.get("log_tail", ""),
                    "bg start job log should include output",
                )
                break
            time.sleep(0.1)
        expect(start_done, "bg start should complete asynchronously")

        result = run_bg("doctor", "--json")
        expect(result.returncode == 0, f"bg doctor json failed: {result.stderr}")
        bg_doctor_report = parse_json_output(result.stdout)
        expect(bg_doctor_report.get("result") == "PASS", "bg doctor should pass")
        expect(
            isinstance(bg_doctor_report.get("notify"), dict),
            "bg doctor should include notify diagnostics",
        )

        refactor_env = os.environ.copy()
        refactor_env["HOME"] = str(home)
        hook_audit_path = home / ".config" / "opencode" / "hooks" / "actions.jsonl"
        refactor_env["MY_OPENCODE_HOOK_AUDIT_PATH"] = str(hook_audit_path)

        result = subprocess.run(
            [
                sys.executable,
                str(REFACTOR_LITE_SCRIPT),
                "profile",
                "--scope",
                "scripts/*.py",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            result.returncode == 0,
            f"refactor-lite dry-run json failed: {result.stderr}",
        )
        refactor_report = parse_json_output(result.stdout)
        expect(
            refactor_report.get("result") == "PASS", "refactor-lite dry-run should pass"
        )
        expect(
            refactor_report.get("preflight", {}).get("matched_file_count", 0) > 0,
            "refactor-lite should return a non-empty file map",
        )

        refactor_tmp = tmp / "refactor_tmp"
        refactor_tmp.mkdir(parents=True, exist_ok=True)
        (refactor_tmp / "sample.py").write_text(
            'def run_profile():\n    return "profile"\n', encoding="utf-8"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(REFACTOR_LITE_SCRIPT),
                "profile",
                "--scope",
                "*.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=refactor_tmp,
        )
        expect(
            result.returncode == 1, "refactor-lite should fail when hooks cannot run"
        )
        refactor_fail_report = parse_json_output(result.stdout)
        expect(
            refactor_fail_report.get("error_code") == "verification_failed",
            "refactor-lite should report verification_failed when make validate is unavailable",
        )

        result = subprocess.run(
            [sys.executable, str(REFACTOR_LITE_SCRIPT), "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            result.returncode == 1,
            "refactor-lite should fail when target argument is missing",
        )
        missing_target_report = parse_json_output(result.stdout)
        expect(
            missing_target_report.get("error_code") == "target_required",
            "refactor-lite should report target_required when target is absent",
        )

        ambiguous_dir = tmp / "refactor_ambiguous"
        ambiguous_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(30):
            (ambiguous_dir / f"file_{idx}.py").write_text(
                'def profile_value():\n    return "profile"\n', encoding="utf-8"
            )

        result = subprocess.run(
            [
                sys.executable,
                str(REFACTOR_LITE_SCRIPT),
                "profile",
                "--json",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=ambiguous_dir,
        )
        expect(
            result.returncode == 1,
            "refactor-lite safe mode should fail for ambiguous broad target",
        )
        ambiguous_report = parse_json_output(result.stdout)
        expect(
            ambiguous_report.get("error_code") == "ambiguous_target",
            "refactor-lite should report ambiguous_target in safe mode",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(REFACTOR_LITE_SCRIPT),
                "profile",
                "--strategy",
                "aggressive",
                "--json",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=ambiguous_dir,
        )
        expect(
            result.returncode == 0,
            "refactor-lite aggressive mode should allow broad target analysis",
        )
        aggressive_report = parse_json_output(result.stdout)
        expect(
            aggressive_report.get("result") == "PASS",
            "refactor-lite aggressive mode should pass dry-run preflight",
        )

        hook_plan = resolve_event_plan(
            "PostToolUse",
            [
                HookRegistration("continuation-reminder", "PostToolUse", priority=50),
                HookRegistration("truncate-safety", "PostToolUse", priority=80),
                HookRegistration("error-hints", "PostToolUse", priority=70),
                HookRegistration("stop-audit", "Stop", priority=10),
            ],
            {
                "enabled": True,
                "disabled": ["truncate-safety"],
                "order": ["error-hints", "continuation-reminder"],
            },
        )
        expect(
            [hook.hook_id for hook in hook_plan]
            == ["error-hints", "continuation-reminder"],
            "hook framework should apply deterministic order and disabled list",
        )

        hook_tie_break = resolve_event_plan(
            "PostToolUse",
            [
                HookRegistration("bbb", "PostToolUse", priority=100),
                HookRegistration("aaa", "PostToolUse", priority=100),
            ],
            {"enabled": True},
        )
        expect(
            [hook.hook_id for hook in hook_tie_break] == ["aaa", "bbb"],
            "hook framework should use stable id ordering as deterministic fallback",
        )

        reminder_report = continuation_reminder(
            {"checklist": ["update docs", "", "run tests"]}
        )
        expect(
            reminder_report.get("triggered") is True
            and reminder_report.get("pending_count") == 2,
            "continuation reminder should trigger for unfinished checklist items",
        )

        no_reminder_report = continuation_reminder({"checklist": []})
        expect(
            no_reminder_report.get("triggered") is False,
            "continuation reminder should stay quiet when checklist is empty",
        )

        truncation_report = output_truncation_safety(
            {
                "text": "\n".join(f"line {idx}" for idx in range(300)),
                "max_lines": 120,
                "max_chars": 2_000,
            }
        )
        expect(
            truncation_report.get("truncated") is True,
            "truncate safety should trigger for oversized output",
        )

        git_hint_report = error_recovery_hint(
            {
                "command": "git status",
                "exit_code": 128,
                "stderr": "fatal: not a git repository",
            }
        )
        expect(
            git_hint_report.get("category") == "git_context",
            "error hints should detect git context failures",
        )

        hook_enable = subprocess.run(
            [sys.executable, str(HOOKS_SCRIPT), "enable"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(hook_enable.returncode == 0, "hooks enable should succeed")

        hook_disable_id = subprocess.run(
            [sys.executable, str(HOOKS_SCRIPT), "disable-hook", "error-hints"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(hook_disable_id.returncode == 0, "hooks disable-hook should succeed")

        hook_skipped = subprocess.run(
            [
                sys.executable,
                str(HOOKS_SCRIPT),
                "run",
                "error-hints",
                "--json",
                json.dumps(
                    {
                        "command": "python3 missing.py",
                        "exit_code": 2,
                        "stderr": "No such file or directory",
                    }
                ),
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(hook_skipped.returncode == 0, "hooks command run should succeed")
        skipped_report = parse_json_output(hook_skipped.stdout)
        expect(
            skipped_report.get("reason") == "hook_disabled",
            "disabled hook should return hook_disabled skip reason",
        )

        hook_enable_id = subprocess.run(
            [sys.executable, str(HOOKS_SCRIPT), "enable-hook", "error-hints"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(hook_enable_id.returncode == 0, "hooks enable-hook should succeed")

        hook_run = subprocess.run(
            [
                sys.executable,
                str(HOOKS_SCRIPT),
                "run",
                "error-hints",
                "--json",
                json.dumps(
                    {
                        "command": "python3 missing.py",
                        "exit_code": 2,
                        "stderr": "No such file or directory",
                    }
                ),
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(hook_run.returncode == 0, "hooks command run should succeed")
        hook_report = parse_json_output(hook_run.stdout)
        expect(
            hook_report.get("category") == "path_missing",
            "hooks command should return path_missing category",
        )
        expect(hook_audit_path.exists(), "hook audit log should be created")
        audit_lines = [
            line.strip()
            for line in hook_audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        expect(len(audit_lines) >= 2, "hook audit log should capture hook events")
        audit_last = json.loads(audit_lines[-1])
        expect(
            "stderr" not in audit_last and "stdout" not in audit_last,
            "hook audit log should not include raw command output",
        )

        hooks_doctor = subprocess.run(
            [sys.executable, str(HOOKS_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(hooks_doctor.returncode == 0, "hooks doctor should pass")
        hooks_doctor_report = parse_json_output(hooks_doctor.stdout)
        expect(
            hooks_doctor_report.get("result") == "PASS",
            "hooks doctor json should report PASS",
        )

        routing_schema = default_schema()
        schema_problems = validate_schema(routing_schema)
        expect(not schema_problems, "default model routing schema should validate")

        resolved_requested = resolve_category(routing_schema, "deep")
        expect(
            resolved_requested.get("category") == "deep"
            and resolved_requested.get("reason") == "requested_category",
            "model routing should resolve explicit known category",
        )

        resolved_missing = resolve_category(routing_schema, "unknown")
        expect(
            resolved_missing.get("category") == routing_schema.get("default_category")
            and resolved_missing.get("reason") == "fallback_missing_category",
            "model routing should fallback to default when category is missing",
        )

        resolved_unavailable = resolve_category(
            routing_schema,
            "deep",
            available_models={"openai/gpt-5-mini"},
        )
        expect(
            resolved_unavailable.get("category")
            == routing_schema.get("default_category")
            and resolved_unavailable.get("reason") == "fallback_unavailable_model",
            "model routing should fallback when requested model is unavailable",
        )

        resolved_with_precedence = resolve_model_settings(
            schema=routing_schema,
            requested_category="deep",
            user_overrides={"verbosity": "high", "model": "openai/custom-unavailable"},
            system_defaults={
                "model": "openai/gpt-5.3-codex",
                "temperature": 0.3,
                "reasoning": "medium",
                "verbosity": "low",
            },
            available_models={"openai/gpt-5-mini", "openai/gpt-5.3-codex"},
        )
        expect(
            resolved_with_precedence.get("settings", {}).get("model")
            == "openai/gpt-5.3-codex",
            "model routing should fallback to available category/system model deterministically",
        )
        expect(
            len(resolved_with_precedence.get("trace", [])) >= 4,
            "model routing should include deterministic fallback trace",
        )
        last_trace = resolved_with_precedence.get("trace", [])[-1]
        expect(
            isinstance(last_trace, dict)
            and last_trace.get("reason") == "fallback_unavailable_model_to_category",
            "model routing fallback reason should be deterministic and explicit",
        )

        model_routing_set = subprocess.run(
            [sys.executable, str(MODEL_ROUTING_SCRIPT), "set-category", "visual"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            model_routing_set.returncode == 0,
            "model-routing set-category should succeed",
        )
        model_routing_resolve = subprocess.run(
            [
                sys.executable,
                str(MODEL_ROUTING_SCRIPT),
                "resolve",
                "--override-model",
                "openai/nonexistent",
                "--available-models",
                "openai/gpt-5-mini,openai/gpt-5.3-codex",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            model_routing_resolve.returncode == 0,
            "model-routing resolve should succeed",
        )
        model_routing_report = parse_json_output(model_routing_resolve.stdout)
        expect(
            model_routing_report.get("category") == "visual"
            and model_routing_report.get("settings", {}).get("model")
            == "openai/gpt-5.3-codex",
            "model-routing resolve should keep active category and apply model fallback",
        )
        expect(
            isinstance(model_routing_report.get("resolution_trace"), dict),
            "model-routing resolve should emit requested/attempted/selected trace payload",
        )

        model_routing_trace = subprocess.run(
            [sys.executable, str(MODEL_ROUTING_SCRIPT), "trace", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            model_routing_trace.returncode == 0,
            "model-routing trace should succeed",
        )
        model_routing_trace_report = parse_json_output(model_routing_trace.stdout)
        expect(
            model_routing_trace_report.get("has_trace") is True,
            "model-routing trace should persist latest resolution trace",
        )
        expect(
            model_routing_trace_report.get("trace", {}).get("selected", {}).get("model")
            == "openai/gpt-5.3-codex",
            "model-routing trace should expose selected model from latest resolve",
        )

        routing_status = subprocess.run(
            [sys.executable, str(ROUTING_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(routing_status.returncode == 0, "routing status should succeed")
        routing_status_report = parse_json_output(routing_status.stdout)
        expect(
            routing_status_report.get("active_category") == "visual",
            "routing status should reflect active category from model routing state",
        )

        routing_explain = subprocess.run(
            [
                sys.executable,
                str(ROUTING_SCRIPT),
                "explain",
                "--category",
                "deep",
                "--override-model",
                "openai/nonexistent",
                "--available-models",
                "openai/gpt-5-mini,openai/gpt-5.3-codex",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(routing_explain.returncode == 0, "routing explain should succeed")
        routing_explain_report = parse_json_output(routing_explain.stdout)
        expect(
            routing_explain_report.get("selected_model") == "openai/gpt-5.3-codex",
            "routing explain should expose selected model",
        )
        expect(
            isinstance(routing_explain_report.get("resolution_trace"), dict),
            "routing explain should include structured resolution trace",
        )

        keyword_report = resolve_prompt_modes(
            "Please safe-apply and deep-analyze this migration; ulw can wait.",
            enabled=True,
            disabled_keywords=set(),
        )
        expect(
            keyword_report.get("matched_keywords")
            == ["safe-apply", "deep-analyze", "ulw"],
            "keyword detector should resolve matched keywords in precedence order",
        )
        expect(
            keyword_report.get("effective_flags", {}).get("analysis_depth") == "high",
            "keyword detector should keep higher-precedence conflicting flag values",
        )
        expect(
            len(keyword_report.get("conflicts", [])) >= 1,
            "keyword detector should report conflicts when lower-precedence flags are discarded",
        )

        keyword_opt_out = resolve_prompt_modes(
            "no-keyword-mode safe-apply deep-analyze",
            enabled=True,
            disabled_keywords=set(),
        )
        expect(
            keyword_opt_out.get("matched_keywords") == []
            and keyword_opt_out.get("request_opt_out") == "no-keyword-mode",
            "keyword detector should support prompt-level global opt-out",
        )

        keyword_no_partial_match = resolve_prompt_modes(
            "please go deeper and safely apply this refactor",
            enabled=True,
            disabled_keywords=set(),
        )
        expect(
            keyword_no_partial_match.get("matched_keywords") == [],
            "keyword detector should avoid partial-word false positives",
        )

        keyword_ignore_inline_code = resolve_prompt_modes(
            "Document this literal command: `safe-apply deep-analyze`",
            enabled=True,
            disabled_keywords=set(),
        )
        expect(
            keyword_ignore_inline_code.get("matched_keywords") == [],
            "keyword detector should ignore inline code literal keywords",
        )

        keyword_ignore_fenced_code = resolve_prompt_modes(
            """Use this snippet:\n```text\nsafe-apply deep-analyze\n```\nthen explain docs.""",
            enabled=True,
            disabled_keywords=set(),
        )
        expect(
            keyword_ignore_fenced_code.get("matched_keywords") == [],
            "keyword detector should ignore fenced code literal keywords",
        )

        keyword_detect = subprocess.run(
            [
                sys.executable,
                str(KEYWORD_MODE_SCRIPT),
                "detect",
                "--prompt",
                "safe-apply deep-analyze ulw refactor this module",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(keyword_detect.returncode == 0, "keyword-mode detect should succeed")
        keyword_detect_report = parse_json_output(keyword_detect.stdout)
        expect(
            keyword_detect_report.get("matched_keywords")
            == ["safe-apply", "deep-analyze", "ulw"],
            "keyword-mode detect should emit deterministic keyword ordering",
        )

        keyword_apply = subprocess.run(
            [
                sys.executable,
                str(KEYWORD_MODE_SCRIPT),
                "apply",
                "--prompt",
                "parallel-research deep-analyze check call graph",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(keyword_apply.returncode == 0, "keyword-mode apply should succeed")
        keyword_state = parse_json_output(keyword_apply.stdout)
        expect(
            keyword_state.get("matched_keywords")
            == ["deep-analyze", "parallel-research"],
            "keyword-mode apply should persist precedence-ordered active modes",
        )
        keyword_status = subprocess.run(
            [sys.executable, str(KEYWORD_MODE_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(keyword_status.returncode == 0, "keyword-mode status should succeed")
        keyword_status_report = parse_json_output(keyword_status.stdout)
        expect(
            keyword_status_report.get("active_modes")
            == ["deep-analyze", "parallel-research"],
            "keyword-mode status should expose persisted runtime context",
        )

        keyword_disable_ulw = subprocess.run(
            [sys.executable, str(KEYWORD_MODE_SCRIPT), "disable-keyword", "ulw"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            keyword_disable_ulw.returncode == 0,
            "keyword-mode disable-keyword should succeed",
        )
        keyword_detect_after_disable = subprocess.run(
            [
                sys.executable,
                str(KEYWORD_MODE_SCRIPT),
                "detect",
                "--prompt",
                "ulw deep-analyze",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            keyword_detect_after_disable.returncode == 0,
            "keyword-mode detect after disable-keyword should succeed",
        )
        keyword_detect_after_disable_report = parse_json_output(
            keyword_detect_after_disable.stdout
        )
        expect(
            keyword_detect_after_disable_report.get("matched_keywords")
            == ["deep-analyze"],
            "keyword-mode detect should respect disabled keyword config",
        )

        keyword_global_disable = subprocess.run(
            [sys.executable, str(KEYWORD_MODE_SCRIPT), "disable"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            keyword_global_disable.returncode == 0,
            "keyword-mode disable should succeed",
        )
        keyword_detect_disabled = subprocess.run(
            [
                sys.executable,
                str(KEYWORD_MODE_SCRIPT),
                "detect",
                "--prompt",
                "safe-apply deep-analyze",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            keyword_detect_disabled.returncode == 0,
            "keyword detect should run while disabled",
        )
        keyword_detect_disabled_report = parse_json_output(
            keyword_detect_disabled.stdout
        )
        expect(
            keyword_detect_disabled_report.get("request_opt_out") == "global_disabled"
            and keyword_detect_disabled_report.get("matched_keywords") == [],
            "keyword-mode detect should report global disabled state",
        )

        keyword_global_enable = subprocess.run(
            [sys.executable, str(KEYWORD_MODE_SCRIPT), "enable"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            keyword_global_enable.returncode == 0, "keyword-mode enable should succeed"
        )
        keyword_enable_ulw = subprocess.run(
            [sys.executable, str(KEYWORD_MODE_SCRIPT), "enable-keyword", "ulw"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            keyword_enable_ulw.returncode == 0,
            "keyword-mode enable-keyword should succeed",
        )

        keyword_doctor = subprocess.run(
            [sys.executable, str(KEYWORD_MODE_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(keyword_doctor.returncode == 0, "keyword-mode doctor should succeed")
        keyword_doctor_report = parse_json_output(keyword_doctor.stdout)
        expect(
            keyword_doctor_report.get("result") == "PASS",
            "keyword-mode doctor should report PASS",
        )

        frontmatter, body = parse_frontmatter(
            """---\ndescription: Rule example\npriority: 60\nglobs:\n  - scripts/*.py\n---\nUse safe edits.\n"""
        )
        expect(
            frontmatter.get("priority") == 60,
            "rules frontmatter should parse integer fields",
        )
        expect(
            frontmatter.get("globs") == ["scripts/*.py"],
            "rules frontmatter should parse list fields",
        )
        expect(
            body.strip() == "Use safe edits.",
            "rules frontmatter parser should return markdown body",
        )

        project_tmp = tmp / "rules-project"
        project_rules_dir = project_tmp / ".opencode" / "rules"
        user_rules_dir = home / ".config" / "opencode" / "rules"
        project_rules_dir.mkdir(parents=True, exist_ok=True)
        user_rules_dir.mkdir(parents=True, exist_ok=True)

        (project_rules_dir / "python-safe.md").write_text(
            """---\nid: style-python\ndescription: Python strict style\npriority: 80\nglobs:\n  - scripts/*.py\n---\nPrefer explicit typing for new functions.\n""",
            encoding="utf-8",
        )
        (project_rules_dir / "docs-a.md").write_text(
            """---\nid: docs-a\ndescription: Project docs first\npriority: 50\nglobs:\n  - README.md\n---\nProject docs ordering A.\n""",
            encoding="utf-8",
        )
        (project_rules_dir / "docs-z.md").write_text(
            """---\nid: docs-z\ndescription: Project docs second\npriority: 50\nglobs:\n  - README.md\n---\nProject docs ordering Z.\n""",
            encoding="utf-8",
        )
        (user_rules_dir / "python-safe.md").write_text(
            """---\nid: style-python\ndescription: User python defaults\npriority: 70\nglobs:\n  - scripts/*.py\n---\nPrefer concise comments.\n""",
            encoding="utf-8",
        )
        (user_rules_dir / "docs-rule.md").write_text(
            """---\ndescription: Docs guidance\npriority: 50\nglobs:\n  - README.md\n---\nKeep examples concise.\n""",
            encoding="utf-8",
        )
        (user_rules_dir / "global-safety.md").write_text(
            """---\nid: global-safety\ndescription: Always-on safety guidance\npriority: 40\nalwaysApply: true\n---\nKeep generated code deterministic and auditable.\n""",
            encoding="utf-8",
        )

        discovered_rules = discover_rules(project_tmp, home=home)
        expect(
            len(discovered_rules) == 6,
            "rules discovery should include user and project markdown rules",
        )
        resolved_rules = resolve_effective_rules(
            discovered_rules, "scripts/selftest.py"
        )
        effective_rule_ids = [
            str(rule.get("id")) for rule in resolved_rules.get("effective_rules", [])
        ]
        expect(
            "style-python" in effective_rule_ids,
            "rules resolution should include matching python rule",
        )
        winning_python_rule = next(
            rule
            for rule in resolved_rules.get("effective_rules", [])
            if rule.get("id") == "style-python"
        )
        expect(
            winning_python_rule.get("scope") == "project",
            "project-scoped rule should win when duplicate ids conflict",
        )
        expect(
            len(resolved_rules.get("conflicts", [])) == 1,
            "rules resolution should report duplicate-id conflicts",
        )
        readme_rules = resolve_effective_rules(discovered_rules, "README.md")
        expect(
            any(
                str(rule.get("id")) == "docs-rule"
                for rule in readme_rules.get("effective_rules", [])
            ),
            "rules resolution should match README-targeted docs rule",
        )
        readme_rule_ids = [
            str(rule.get("id")) for rule in readme_rules.get("effective_rules", [])
        ]
        expect(
            readme_rule_ids[:2] == ["docs-a", "docs-z"],
            "rules resolution should preserve deterministic lexical ordering for equal-priority project rules",
        )

        non_matching_rules = resolve_effective_rules(
            discovered_rules, "scripts/unknown.txt"
        )
        expect(
            any(
                str(rule.get("id")) == "global-safety"
                for rule in non_matching_rules.get("effective_rules", [])
            ),
            "alwaysApply rules should apply regardless of target path",
        )

        rules_env = os.environ.copy()
        rules_env["HOME"] = str(home)
        rules_env.pop("OPENCODE_CONFIG_PATH", None)

        rules_status = subprocess.run(
            [sys.executable, str(RULES_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=project_tmp,
        )
        expect(rules_status.returncode == 0, "rules status should succeed")
        rules_status_report = parse_json_output(rules_status.stdout)
        expect(
            rules_status_report.get("discovered_count") == 6,
            "rules status should report discovered rules count",
        )

        rules_explain = subprocess.run(
            [
                sys.executable,
                str(RULES_SCRIPT),
                "explain",
                "scripts/selftest.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=project_tmp,
        )
        expect(rules_explain.returncode == 0, "rules explain should succeed")
        rules_explain_report = parse_json_output(rules_explain.stdout)
        expect(
            any(
                str(rule.get("id")) == "style-python"
                for rule in rules_explain_report.get("effective_rules", [])
            ),
            "rules explain should include effective matching rules",
        )

        rules_disable_id = subprocess.run(
            [sys.executable, str(RULES_SCRIPT), "disable-id", "style-python"],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=project_tmp,
        )
        expect(rules_disable_id.returncode == 0, "rules disable-id should succeed")
        rules_explain_disabled = subprocess.run(
            [
                sys.executable,
                str(RULES_SCRIPT),
                "explain",
                "scripts/selftest.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=project_tmp,
        )
        expect(
            rules_explain_disabled.returncode == 0,
            "rules explain after disable-id should succeed",
        )
        rules_explain_disabled_report = parse_json_output(rules_explain_disabled.stdout)
        expect(
            not any(
                str(rule.get("id")) == "style-python"
                for rule in rules_explain_disabled_report.get("effective_rules", [])
            ),
            "rules explain should exclude disabled rule ids",
        )

        rules_doctor = subprocess.run(
            [sys.executable, str(RULES_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=project_tmp,
        )
        expect(rules_doctor.returncode == 0, "rules doctor should succeed")
        rules_doctor_report = parse_json_output(rules_doctor.stdout)
        expect(
            rules_doctor_report.get("result") == "PASS",
            "rules doctor should report PASS for valid rules",
        )

        rules_enable_id = subprocess.run(
            [sys.executable, str(RULES_SCRIPT), "enable-id", "style-python"],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=project_tmp,
        )
        expect(rules_enable_id.returncode == 0, "rules enable-id should succeed")

        resilience_policy, resilience_policy_problems = resolve_policy(
            {
                "truncation_mode": "aggressive",
                "notification_level": "verbose",
                "protected_tools": ["read"],
                "protected_message_kinds": ["decision"],
            }
        )
        expect(
            not resilience_policy_problems,
            "resilience policy should accept valid aggressive configuration",
        )
        expect(
            resilience_policy.get("old_error_turn_threshold") == 2,
            "aggressive resilience mode should tighten old-error threshold",
        )

        invalid_policy, invalid_policy_problems = resolve_policy(
            {
                "truncation_mode": "unsafe",
                "notification_level": "loud",
                "protected_tools": "bash",
            }
        )
        expect(
            bool(invalid_policy_problems),
            "resilience policy should report schema problems for invalid values",
        )
        expect(
            invalid_policy.get("truncation_mode") == "default",
            "invalid resilience mode should fall back to default",
        )

        context_messages = [
            {
                "role": "assistant",
                "kind": "analysis",
                "content": "consider option A",
                "turn": 1,
            },
            {
                "role": "assistant",
                "kind": "analysis",
                "content": "consider option A",
                "turn": 2,
            },
            {
                "role": "tool",
                "tool_name": "write",
                "kind": "write",
                "target_path": "README.md",
                "content": "draft 1",
                "turn": 3,
            },
            {
                "role": "tool",
                "tool_name": "write",
                "kind": "write",
                "target_path": "README.md",
                "content": "draft 2",
                "turn": 4,
            },
            {
                "role": "tool",
                "tool_name": "bash",
                "kind": "error",
                "command": "make validate",
                "exit_code": 1,
                "content": "lint failed",
                "turn": 5,
            },
            {
                "role": "tool",
                "tool_name": "bash",
                "kind": "result",
                "command": "make validate",
                "exit_code": 0,
                "content": "lint pass",
                "turn": 9,
            },
            {
                "role": "assistant",
                "kind": "decision",
                "content": "ship with tests",
                "turn": 10,
            },
            {
                "role": "assistant",
                "kind": "analysis",
                "content": "historical note",
                "turn": 2,
            },
        ]
        pruned_context = prune_context(
            context_messages, resilience_policy, max_messages=5
        )
        drop_reasons = {
            item.get("reason") for item in pruned_context.get("dropped", [])
        }
        expect(
            "deduplicated" in drop_reasons,
            "context pruning should deduplicate repeated non-protected messages",
        )
        expect(
            "superseded_write" in drop_reasons,
            "context pruning should prune superseded writes for same target",
        )
        expect(
            "stale_error_purged" in drop_reasons,
            "context pruning should purge old errors when newer success exists",
        )
        expect(
            any(
                message.get("kind") == "decision"
                for message in pruned_context.get("messages", [])
            ),
            "context pruning should preserve protected decision messages",
        )
        expect(
            any(
                message.get("command") == "make validate"
                and message.get("exit_code") == 0
                for message in pruned_context.get("messages", [])
            ),
            "context pruning should preserve latest command outcomes as critical evidence",
        )

        recovery_plan = build_recovery_plan(
            context_messages, pruned_context, resilience_policy
        )
        expect(
            recovery_plan.get("can_resume") is True,
            "recovery plan should allow resume when success anchor exists",
        )
        expect(
            recovery_plan.get("recovery_action") == "resume_hint",
            "recovery plan should emit resume hints after successful recovery",
        )
        expect(
            "make validate" in str(recovery_plan.get("resume_hint", "")),
            "resume hint should reference latest successful command",
        )
        expect(
            isinstance(recovery_plan.get("diagnostics", {}).get("drop_counts"), dict),
            "recovery diagnostics should include pruning reason counts",
        )

        failed_only_messages = [
            {
                "role": "tool",
                "tool_name": "bash",
                "kind": "error",
                "command": "make install-test",
                "exit_code": 2,
                "content": "missing dependency",
                "turn": 1,
            },
            {
                "role": "assistant",
                "kind": "analysis",
                "content": "investigate dependency mismatch",
                "turn": 2,
            },
        ]
        failed_pruned = prune_context(failed_only_messages, resilience_policy)
        failed_plan = build_recovery_plan(
            failed_only_messages, failed_pruned, resilience_policy
        )
        expect(
            failed_plan.get("can_resume") is False,
            "recovery plan should block resume when no success anchor is available",
        )
        expect(
            failed_plan.get("recovery_action") == "safe_fallback",
            "recovery plan should provide safe fallback path for unrecoverable contexts",
        )
        expect(
            bool(failed_plan.get("fallback", {}).get("steps")),
            "safe fallback should include actionable recovery steps",
        )

        resilience_status = subprocess.run(
            [sys.executable, str(RESILIENCE_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            resilience_status.returncode == 0,
            "resilience status should succeed",
        )
        resilience_status_report = parse_json_output(resilience_status.stdout)
        expect(
            resilience_status_report.get("enabled") is True,
            "resilience status should report subsystem enabled by default",
        )

        resilience_doctor = subprocess.run(
            [sys.executable, str(RESILIENCE_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=rules_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(resilience_doctor.returncode == 0, "resilience doctor should succeed")
        resilience_doctor_report = parse_json_output(resilience_doctor.stdout)
        expect(
            resilience_doctor_report.get("result") == "PASS",
            "resilience doctor should pass stress diagnostics",
        )
        expect(
            int(resilience_doctor_report.get("stress_dropped_count", 0)) > 0,
            "resilience doctor stress run should prune at least one message",
        )

        wizard_state_path = (
            home / ".config" / "opencode" / "my_opencode-install-state.json"
        )
        wizard_env = os.environ.copy()
        wizard_env["OPENCODE_CONFIG_PATH"] = str(tmp / "opencode.json")
        wizard_env["HOME"] = str(home)
        wizard_env["OPENCODE_NOTIFICATIONS_PATH"] = str(notify_policy_path)
        wizard_env["MY_OPENCODE_POLICY_PATH"] = str(policy_path)
        wizard_env["OPENCODE_TELEMETRY_PATH"] = str(telemetry_path)
        wizard_env["MY_OPENCODE_SESSION_CONFIG_PATH"] = str(session_cfg_path)
        wizard_env["MY_OPENCODE_INSTALL_STATE_PATH"] = str(wizard_state_path)

        result = subprocess.run(
            [
                sys.executable,
                str(INSTALL_WIZARD_SCRIPT),
                "--non-interactive",
                "--skip-extras",
                "--plugin-profile",
                "stable",
                "--mcp-profile",
                "research",
                "--policy-profile",
                "balanced",
                "--notify-profile",
                "skip",
                "--telemetry-profile",
                "local",
                "--post-session-profile",
                "manual-validate",
                "--model-profile",
                "deep",
            ],
            capture_output=True,
            text=True,
            env=wizard_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            result.returncode == 0,
            f"install wizard non-interactive run failed: {result.stderr}",
        )
        expect(wizard_state_path.exists(), "wizard should persist state file")
        wizard_state = load_json_file(wizard_state_path)
        expect(
            wizard_state.get("profiles", {}).get("plugin") == "stable",
            "wizard should persist selected plugin profile",
        )
        expect(
            wizard_state.get("profiles", {}).get("telemetry") == "local",
            "wizard should persist selected telemetry profile",
        )
        expect(
            wizard_state.get("profiles", {}).get("model_routing") == "deep",
            "wizard should persist selected model routing profile",
        )
        post_after_wizard = load_json_file(session_cfg_path)
        expect(
            post_after_wizard.get("post_session", {}).get("enabled") is True,
            "wizard manual-validate profile should enable post-session",
        )
        expect(
            post_after_wizard.get("post_session", {}).get("command") == "make validate",
            "wizard manual-validate profile should configure make validate",
        )

        nvim_cfg_dir = home / ".config" / "nvim"
        nvim_plugin_dir = (
            home
            / ".local"
            / "share"
            / "nvim"
            / "site"
            / "pack"
            / "opencode"
            / "start"
            / "opencode.nvim"
        )
        (nvim_plugin_dir / "lua").mkdir(parents=True, exist_ok=True)
        nvim_env = os.environ.copy()
        nvim_env["HOME"] = str(home)
        nvim_env["MY_OPENCODE_NVIM_CONFIG_DIR"] = str(nvim_cfg_dir)
        nvim_env["MY_OPENCODE_NVIM_PLUGIN_DIR"] = str(nvim_plugin_dir)

        result = subprocess.run(
            [
                sys.executable,
                str(NVIM_INTEGRATION_SCRIPT),
                "install",
                "minimal",
                "--link-init",
            ],
            capture_output=True,
            text=True,
            env=nvim_env,
            check=False,
        )
        expect(result.returncode == 0, f"nvim install minimal failed: {result.stderr}")
        expect(
            (nvim_cfg_dir / "lua" / "my_opencode" / "opencode.lua").exists(),
            "nvim integration install should write lua profile",
        )
        expect(
            (nvim_cfg_dir / "init.lua").exists(),
            "nvim integration install should write init.lua require",
        )

        result = subprocess.run(
            [sys.executable, str(NVIM_INTEGRATION_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=nvim_env,
            check=False,
        )
        expect(result.returncode == 0, f"nvim doctor json failed: {result.stderr}")
        report = parse_json_output(result.stdout)
        expect(report.get("result") == "PASS", "nvim doctor should pass after install")

        result = subprocess.run(
            [
                sys.executable,
                str(NVIM_INTEGRATION_SCRIPT),
                "uninstall",
                "--unlink-init",
            ],
            capture_output=True,
            text=True,
            env=nvim_env,
            check=False,
        )
        expect(result.returncode == 0, f"nvim uninstall failed: {result.stderr}")
        expect(
            not (nvim_cfg_dir / "lua" / "my_opencode" / "opencode.lua").exists(),
            "nvim uninstall should remove lua profile",
        )

        result = run_script(
            PLUGIN_SCRIPT, tmp / "opencode.json", home, "profile", "lean"
        )
        expect(
            result.returncode == 0,
            f"plugin profile lean (for doctor summary) failed: {result.stderr}",
        )

        doctor_env = os.environ.copy()
        doctor_env["OPENCODE_CONFIG_PATH"] = str(tmp / "opencode.json")
        doctor_env["HOME"] = str(home)
        doctor_env["OPENCODE_NOTIFICATIONS_PATH"] = str(notify_path)
        doctor_env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)
        doctor_env["OPENCODE_TELEMETRY_PATH"] = str(telemetry_path)
        doctor_env["MY_OPENCODE_SESSION_CONFIG_PATH"] = str(session_cfg_path)
        doctor_env["MY_OPENCODE_POLICY_PATH"] = str(policy_path)

        result = subprocess.run(
            [sys.executable, str(DOCTOR_SCRIPT), "run", "--json"],
            capture_output=True,
            text=True,
            env=doctor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"doctor run --json failed: {result.stderr}")
        report = parse_json_output(result.stdout)
        expect(report.get("result") == "PASS", "doctor summary should pass")
        expect(
            report.get("failed_count") == 0,
            "doctor summary should have zero failed checks",
        )
        bg_checks = [
            check for check in report.get("checks", []) if check.get("name") == "bg"
        ]
        expect(bool(bg_checks), "doctor summary should include bg check")
        expect(bg_checks[0].get("ok") is True, "doctor bg check should pass")

        refactor_checks = [
            check
            for check in report.get("checks", [])
            if check.get("name") == "refactor-lite"
        ]
        expect(
            bool(refactor_checks),
            "doctor summary should include optional refactor-lite check",
        )
        expect(
            refactor_checks[0].get("ok") is True,
            "doctor refactor-lite check should pass when backend exists",
        )

        model_routing_checks = [
            check
            for check in report.get("checks", [])
            if check.get("name") == "model-routing"
        ]
        expect(
            bool(model_routing_checks),
            "doctor summary should include model-routing check",
        )
        expect(
            model_routing_checks[0].get("ok") is True,
            "doctor model-routing check should pass",
        )

        keyword_mode_checks = [
            check
            for check in report.get("checks", [])
            if check.get("name") == "keyword-mode"
        ]
        expect(
            bool(keyword_mode_checks),
            "doctor summary should include keyword-mode check",
        )
        expect(
            keyword_mode_checks[0].get("ok") is True,
            "doctor keyword-mode check should pass",
        )

        rules_checks = [
            check for check in report.get("checks", []) if check.get("name") == "rules"
        ]
        expect(
            bool(rules_checks),
            "doctor summary should include rules check",
        )
        expect(
            rules_checks[0].get("ok") is True,
            "doctor rules check should pass",
        )

        resilience_checks = [
            check
            for check in report.get("checks", [])
            if check.get("name") == "resilience"
        ]
        expect(
            bool(resilience_checks),
            "doctor summary should include resilience check",
        )
        expect(
            resilience_checks[0].get("ok") is True,
            "doctor resilience check should pass",
        )

    print("selftest: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"selftest: FAIL - {exc}")
        raise SystemExit(1)
