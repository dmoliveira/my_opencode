#!/usr/bin/env python3

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCRIPT = REPO_ROOT / "scripts" / "plugin_command.py"
MCP_SCRIPT = REPO_ROOT / "scripts" / "mcp_command.py"
NOTIFY_SCRIPT = REPO_ROOT / "scripts" / "notify_command.py"
DIGEST_SCRIPT = REPO_ROOT / "scripts" / "session_digest.py"
TELEMETRY_SCRIPT = REPO_ROOT / "scripts" / "telemetry_command.py"
POST_SESSION_SCRIPT = REPO_ROOT / "scripts" / "post_session_command.py"
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
        result = run_script(PLUGIN_SCRIPT, cfg, home, "profile", "lean")
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

        telemetry_path = home / ".config" / "opencode" / "opencode-telemetry.json"
        telemetry_env = os.environ.copy()
        telemetry_env["OPENCODE_TELEMETRY_PATH"] = str(telemetry_path)

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

            cfg = load_json_file(telemetry_path)
            expect(cfg.get("enabled") is True, "telemetry should remain enabled")
            expect(cfg.get("timeout_ms") == 800, "telemetry timeout should be updated")
            expect(
                cfg.get("events", {}).get("question") is False,
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

        session_cfg_path = home / ".config" / "opencode" / "opencode-session.json"
        post_env = os.environ.copy()
        post_env["MY_OPENCODE_SESSION_CONFIG_PATH"] = str(session_cfg_path)
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

    print("selftest: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"selftest: FAIL - {exc}")
        raise SystemExit(1)
