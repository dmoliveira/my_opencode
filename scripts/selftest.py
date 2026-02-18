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
from datetime import UTC, datetime, timedelta
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
from auto_slash_schema import detect_intent, evaluate_precision  # type: ignore
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
from todo_enforcement import (  # type: ignore
    build_bypass_event,
    remediation_prompts,
    validate_plan_completion,
    validate_todo_set,
    validate_todo_transition,
)
from recovery_engine import (  # type: ignore
    evaluate_resume_eligibility,
    execute_resume,
)
from safe_edit_adapters import (  # type: ignore
    detect_language,
    evaluate_semantic_capability,
    validate_changed_references,
)
from checkpoint_snapshot_manager import (  # type: ignore
    list_snapshots,
    prune_snapshots,
    show_snapshot,
    write_snapshot,
)
from execution_budget_runtime import (  # type: ignore
    build_budget_state,
    evaluate_budget,
    resolve_budget_policy,
)
from health_score_collector import (  # type: ignore
    apply_suppression_window,
    build_indicators,
    evaluate_health,
    load_health_state,
    persist_health_snapshot,
    save_health_state,
)
from knowledge_capture_pipeline import (  # type: ignore
    collect_pr_signals,
    collect_task_digest_signals,
    generate_draft_entries,
    transition_entry,
)
from autopilot_runtime import (  # type: ignore
    execute_cycle,
    initialize_run,
    validate_objective,
)
from autopilot_integration import integrate_controls  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCRIPT = REPO_ROOT / "scripts" / "plugin_command.py"
MCP_SCRIPT = REPO_ROOT / "scripts" / "mcp_command.py"
NOTIFY_SCRIPT = REPO_ROOT / "scripts" / "notify_command.py"
DIGEST_SCRIPT = REPO_ROOT / "scripts" / "session_digest.py"
SESSION_SCRIPT = REPO_ROOT / "scripts" / "session_command.py"
TELEMETRY_SCRIPT = REPO_ROOT / "scripts" / "telemetry_command.py"
POST_SESSION_SCRIPT = REPO_ROOT / "scripts" / "post_session_command.py"
POLICY_SCRIPT = REPO_ROOT / "scripts" / "policy_command.py"
QUALITY_SCRIPT = REPO_ROOT / "scripts" / "quality_command.py"
GATEWAY_SCRIPT = REPO_ROOT / "scripts" / "gateway_command.py"
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
AUTO_SLASH_SCRIPT = REPO_ROOT / "scripts" / "auto_slash_command.py"
RULES_SCRIPT = REPO_ROOT / "scripts" / "rules_command.py"
RESILIENCE_SCRIPT = REPO_ROOT / "scripts" / "context_resilience_command.py"
BROWSER_SCRIPT = REPO_ROOT / "scripts" / "browser_command.py"
START_WORK_SCRIPT = REPO_ROOT / "scripts" / "start_work_command.py"
TODO_SCRIPT = REPO_ROOT / "scripts" / "todo_command.py"
RESUME_SCRIPT = REPO_ROOT / "scripts" / "resume_command.py"
SAFE_EDIT_SCRIPT = REPO_ROOT / "scripts" / "safe_edit_command.py"
LSP_SCRIPT = REPO_ROOT / "scripts" / "lsp_command.py"
CHECKPOINT_SCRIPT = REPO_ROOT / "scripts" / "checkpoint_command.py"
BUDGET_SCRIPT = REPO_ROOT / "scripts" / "budget_command.py"
AUTOPILOT_COMMAND_SCRIPT = REPO_ROOT / "scripts" / "autopilot_command.py"
PR_REVIEW_ANALYZER_SCRIPT = REPO_ROOT / "scripts" / "pr_review_analyzer.py"
PR_REVIEW_COMMAND_SCRIPT = REPO_ROOT / "scripts" / "pr_review_command.py"
RELEASE_TRAIN_ENGINE_SCRIPT = REPO_ROOT / "scripts" / "release_train_engine.py"
RELEASE_TRAIN_COMMAND_SCRIPT = REPO_ROOT / "scripts" / "release_train_command.py"
HOTFIX_RUNTIME_SCRIPT = REPO_ROOT / "scripts" / "hotfix_runtime.py"
HOTFIX_COMMAND_SCRIPT = REPO_ROOT / "scripts" / "hotfix_command.py"
HEALTH_COMMAND_SCRIPT = REPO_ROOT / "scripts" / "health_command.py"
LEARN_COMMAND_SCRIPT = REPO_ROOT / "scripts" / "learn_command.py"
AGENT_DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "agent_doctor.py"
BUILD_AGENTS_SCRIPT = REPO_ROOT / "scripts" / "build_agents.py"
BASE_CONFIG = REPO_ROOT / "opencode.json"
AGENT_DIR = REPO_ROOT / "agent"


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


def plan_runtime_path(config_path: Path) -> Path:
    return config_path.parent / "my_opencode" / "runtime" / "plan_execution.json"


def load_plan_runtime(config_path: Path) -> dict:
    runtime_path = plan_runtime_path(config_path)
    expect(runtime_path.exists(), "plan runtime state file should exist")
    return load_json_file(runtime_path)


def save_plan_runtime(config_path: Path, runtime: dict) -> None:
    runtime_path = plan_runtime_path(config_path)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")


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
        test_env = os.environ.copy()
        test_env["HOME"] = str(home)
        test_bin_dir = home / "bin"
        test_bin_dir.mkdir(parents=True, exist_ok=True)
        opencode_stub = test_bin_dir / "opencode"
        opencode_stub.write_text(
            """#!/bin/sh
if [ \"$1\" = \"agent\" ] && [ \"$2\" = \"list\" ]; then
  cat <<'EOF'
orchestrator (primary)
explore (subagent)
librarian (subagent)
oracle (subagent)
verifier (subagent)
reviewer (subagent)
release-scribe (subagent)
EOF
  exit 0
fi
exit 0
""",
            encoding="utf-8",
        )
        opencode_stub.chmod(0o755)
        test_env["PATH"] = f"{test_bin_dir}:{os.environ.get('PATH', '')}"
        installed_agent_dir = home / ".config" / "opencode" / "agent"
        installed_agent_dir.mkdir(parents=True, exist_ok=True)
        for agent_file in AGENT_DIR.glob("*.md"):
            shutil.copy2(agent_file, installed_agent_dir / agent_file.name)
        cfg = tmp / "opencode.json"
        shutil.copy2(BASE_CONFIG, cfg)

        # Agent operating contract sanity checks
        expect(AGENT_DIR.exists(), "agent directory should exist")
        required_agents = {
            "orchestrator.md": {
                "must": [
                    "mode: primary",
                    "Use `verifier` before claiming done",
                    "Use `reviewer` for final quality/safety pass",
                    "Anti-loop guard",
                ]
            },
            "explore.md": {
                "must": ["mode: subagent", "bash: false", "write: false", "edit: false"]
            },
            "librarian.md": {
                "must": ["mode: subagent", "bash: false", "write: false", "edit: false"]
            },
            "oracle.md": {"must": ["mode: subagent", "write: false", "edit: false"]},
            "verifier.md": {"must": ["mode: subagent", "write: false", "edit: false"]},
            "reviewer.md": {"must": ["mode: subagent", "write: false", "edit: false"]},
            "release-scribe.md": {
                "must": ["mode: subagent", "write: false", "edit: false"]
            },
        }
        for filename, rules in required_agents.items():
            path = AGENT_DIR / filename
            expect(path.exists(), f"required agent file should exist: {filename}")
            content = path.read_text(encoding="utf-8")
            for marker in rules["must"]:
                expect(
                    marker in content,
                    f"agent file {filename} should include marker: {marker}",
                )

        base_config_payload = load_json_file(cfg)
        expect(
            str(base_config_payload.get("default_agent") or "") == "build",
            "default_agent should remain build",
        )
        plugin_entries_any = base_config_payload.get("plugin", [])
        plugin_entries = (
            plugin_entries_any if isinstance(plugin_entries_any, list) else []
        )
        expect(
            any(
                isinstance(entry, str)
                and "plugin/gateway-core" in entry
                and entry.startswith("file:")
                for entry in plugin_entries
            ),
            "base config should include gateway-core file plugin entry",
        )
        command_map_any = base_config_payload.get("command", {})
        command_map = command_map_any if isinstance(command_map_any, dict) else {}
        autopilot_template = str(
            (command_map.get("autopilot", {}) or {}).get("template", "")
        )
        expect(
            'autopilot_command.py" $ARGUMENTS --json' in autopilot_template,
            "autopilot command template should pass through slash arguments for subcommand/help dispatch",
        )
        for command_name in ("continue-work", "autopilot-go"):
            template = str(
                (command_map.get(command_name, {}) or {}).get("template", "")
            )
            expect(
                '--goal "$ARGUMENTS"' in template,
                f"{command_name} command template should pass slash arguments as explicit goal",
            )

        install_script = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
        expect(
            'mkdir -p "$CONFIG_DIR/agent"' in install_script
            and 'cp -f "$INSTALL_DIR"/agent/*.md "$CONFIG_DIR/agent/"'
            in install_script,
            "installer should sync custom agent definitions to global agent directory",
        )

        build_agents_check = subprocess.run(
            [
                sys.executable,
                str(BUILD_AGENTS_SCRIPT),
                "--profile",
                "balanced",
                "--check",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            build_agents_check.returncode == 0,
            "build_agents check should pass when generated agent markdown is up-to-date",
        )

        agent_doctor_run = subprocess.run(
            [sys.executable, str(AGENT_DOCTOR_SCRIPT), "run", "--json"],
            capture_output=True,
            text=True,
            env=test_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            agent_doctor_run.returncode == 0,
            f"agent doctor should pass for required local agent roster: {agent_doctor_run.stderr}",
        )
        agent_doctor_report = parse_json_output(agent_doctor_run.stdout)
        expect(
            agent_doctor_report.get("result") == "PASS",
            "agent doctor should report PASS for expected contracts",
        )

        healthy_signals = {
            "observed_at": "2026-02-14T00:00:00Z",
            "validation_targets": {
                "validate": True,
                "selftest": True,
                "install_test": True,
            },
            "git": {"clean_worktree": True, "behind_remote": False},
            "runtime_policy": {
                "budget_profile": "balanced",
                "hooks_enabled": False,
                "disabled_hooks": [],
            },
            "automation": {"bg_failed_jobs": 0, "doctor_failed_count": 0},
            "freshness": {
                "stale_checkpoints": 0,
                "overdue_followups": 0,
                "stale_branches": 0,
            },
        }
        healthy_indicators = build_indicators(healthy_signals)
        healthy_report = evaluate_health(healthy_indicators)
        expect(
            healthy_report.get("status") == "healthy"
            and float(healthy_report.get("score") or 0.0) == 100.0,
            "health score should be healthy for all-pass indicators",
        )

        critical_signals = {
            "observed_at": "2026-02-14T00:00:00Z",
            "validation_targets": {
                "validate": False,
                "selftest": True,
                "install_test": True,
            },
            "git": {"clean_worktree": False, "behind_remote": False},
            "runtime_policy": {
                "budget_profile": "balanced",
                "hooks_enabled": False,
                "disabled_hooks": [],
            },
            "automation": {"bg_failed_jobs": 1, "doctor_failed_count": 0},
            "freshness": {
                "stale_checkpoints": 0,
                "overdue_followups": 0,
                "stale_branches": 0,
            },
        }
        critical_indicators = build_indicators(critical_signals)
        critical_report = evaluate_health(critical_indicators)
        expect(
            critical_report.get("status") == "critical",
            "health score should become critical when multiple fail indicators are present",
        )
        expect(
            "validation_suite_failed" in set(critical_report.get("reason_codes", [])),
            "health score should surface validation_suite_failed reason code",
        )

        warning_signals = {
            "observed_at": "2026-02-14T00:00:00Z",
            "validation_targets": {
                "validate": True,
                "selftest": True,
                "install_test": True,
            },
            "git": {"clean_worktree": True, "behind_remote": False},
            "runtime_policy": {
                "budget_profile": "extended",
                "hooks_enabled": False,
                "disabled_hooks": [],
            },
            "automation": {"bg_failed_jobs": 0, "doctor_failed_count": 0},
            "freshness": {
                "stale_checkpoints": 0,
                "overdue_followups": 0,
                "stale_branches": 0,
            },
        }
        warning_indicators = build_indicators(warning_signals)
        suppression_start = datetime(2026, 2, 14, 0, 0, tzinfo=UTC)
        suppression_summary_1, suppression_state_1 = apply_suppression_window(
            warning_indicators,
            {"suppression": {}, "updated_at": None},
            now=suppression_start,
        )
        expect(
            suppression_summary_1.get("emitted_count", 0) >= 1,
            "suppression should emit first warning observation",
        )
        suppression_summary_2, _ = apply_suppression_window(
            warning_indicators,
            suppression_state_1,
            now=suppression_start + timedelta(hours=1),
        )
        expect(
            suppression_summary_2.get("suppressed_count", 0) >= 1,
            "suppression should suppress repeated warning signals inside window",
        )

        save_health_state(cfg, suppression_state_1)
        loaded_state = load_health_state(cfg)
        expect(
            isinstance(loaded_state.get("suppression"), dict),
            "health state should persist suppression map",
        )
        snapshot_paths = persist_health_snapshot(
            cfg,
            {
                "observed_at": "2026-02-14T00:00:00Z",
                "score": 82.5,
                "status": "degraded",
                "indicators": warning_indicators,
                "reason_codes": ["policy_drift_detected"],
                "next_actions": ["restore expected budget profile baseline"],
                "suppression": suppression_summary_2,
                "weight_normalized": False,
            },
        )
        expect(
            Path(str(snapshot_paths.get("latest", ""))).exists()
            and Path(str(snapshot_paths.get("history", ""))).exists(),
            "health snapshot persistence should write latest and history files",
        )

        health_repo = tmp / "health_repo"
        health_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "-b", "main"],
            capture_output=True,
            text=True,
            check=False,
            cwd=health_repo,
        )
        subprocess.run(
            ["git", "config", "user.email", "selftest@example.com"],
            capture_output=True,
            text=True,
            check=False,
            cwd=health_repo,
        )
        subprocess.run(
            ["git", "config", "user.name", "Selftest"],
            capture_output=True,
            text=True,
            check=False,
            cwd=health_repo,
        )
        (health_repo / "README.md").write_text("health fixture\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"],
            capture_output=True,
            text=True,
            check=False,
            cwd=health_repo,
        )
        subprocess.run(
            ["git", "commit", "-m", "seed health fixture"],
            capture_output=True,
            text=True,
            check=False,
            cwd=health_repo,
        )

        health_env = os.environ.copy()
        health_env["OPENCODE_CONFIG_PATH"] = str(cfg)
        health_env["HOME"] = str(home)
        health_env.pop("SUPERMEMORY_API_KEY", None)
        health_env.pop("MORPH_API_KEY", None)

        health_status = subprocess.run(
            [
                sys.executable,
                str(HEALTH_COMMAND_SCRIPT),
                "status",
                "--force-refresh",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=health_env,
            check=False,
            cwd=health_repo,
        )
        expect(
            health_status.returncode == 0,
            "health command status should succeed with force-refresh",
        )
        health_status_payload = parse_json_output(health_status.stdout)
        expect(
            health_status_payload.get("result") == "PASS"
            and health_status_payload.get("status")
            in {"healthy", "degraded", "critical"},
            "health status should return a valid status payload",
        )

        health_status_repeat = subprocess.run(
            [
                sys.executable,
                str(HEALTH_COMMAND_SCRIPT),
                "status",
                "--force-refresh",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=health_env,
            check=False,
            cwd=health_repo,
        )
        expect(
            health_status_repeat.returncode == 0,
            "health status repeat run should succeed",
        )
        health_status_repeat_payload = parse_json_output(health_status_repeat.stdout)
        expect(
            health_status_repeat_payload.get("score")
            == health_status_payload.get("score")
            and health_status_repeat_payload.get("status")
            == health_status_payload.get("status"),
            "health scoring should be deterministic across repeated runs with unchanged signals",
        )

        health_trend = subprocess.run(
            [
                sys.executable,
                str(HEALTH_COMMAND_SCRIPT),
                "trend",
                "--limit",
                "5",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=health_env,
            check=False,
            cwd=health_repo,
        )
        expect(
            health_trend.returncode == 0,
            "health command trend should succeed",
        )
        health_trend_payload = parse_json_output(health_trend.stdout)
        expect(
            int(health_trend_payload.get("count", 0)) >= 1,
            "health trend should include at least one snapshot entry",
        )

        health_drift = subprocess.run(
            [sys.executable, str(HEALTH_COMMAND_SCRIPT), "drift", "--json"],
            capture_output=True,
            text=True,
            env=health_env,
            check=False,
            cwd=health_repo,
        )
        expect(
            health_drift.returncode == 0,
            "health command drift should succeed",
        )
        health_drift_payload = parse_json_output(health_drift.stdout)
        expect(
            health_drift_payload.get("result") == "PASS"
            and "drift_count" in health_drift_payload,
            "health drift should return drift summary fields",
        )

        cfg_payload = json.loads(cfg.read_text(encoding="utf-8"))
        budget_runtime = (
            cfg_payload.get("budget_runtime")
            if isinstance(cfg_payload.get("budget_runtime"), dict)
            else {}
        )
        budget_runtime["profile"] = "extended"
        cfg_payload["budget_runtime"] = budget_runtime
        cfg.write_text(json.dumps(cfg_payload, indent=2) + "\n", encoding="utf-8")

        health_drift_precise = subprocess.run(
            [
                sys.executable,
                str(HEALTH_COMMAND_SCRIPT),
                "drift",
                "--force-refresh",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=health_env,
            check=False,
            cwd=health_repo,
        )
        expect(
            health_drift_precise.returncode == 0,
            "health drift force-refresh should succeed",
        )
        health_drift_precise_payload = parse_json_output(health_drift_precise.stdout)
        expect(
            "policy_drift_detected"
            in set(health_drift_precise_payload.get("reason_codes", [])),
            "health drift should surface policy_drift_detected for budget profile drift",
        )
        precise_indicators = {
            str(item.get("indicator_id"))
            for item in health_drift_precise_payload.get("drift", [])
            if isinstance(item, dict)
        }
        expect(
            "runtime_policy_drift" in precise_indicators,
            "health drift should attribute profile mismatch to runtime_policy_drift indicator",
        )

        health_doctor = subprocess.run(
            [sys.executable, str(HEALTH_COMMAND_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=health_env,
            check=False,
            cwd=health_repo,
        )
        expect(
            health_doctor.returncode == 0,
            "health command doctor should pass when collector and policy exist",
        )
        health_doctor_payload = parse_json_output(health_doctor.stdout)
        expect(
            health_doctor_payload.get("result") == "PASS",
            "health doctor should report pass",
        )

        knowledge_repo = tmp / "knowledge_repo"
        knowledge_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "-b", "main"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        subprocess.run(
            ["git", "config", "user.email", "selftest@example.com"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        subprocess.run(
            ["git", "config", "user.name", "Selftest"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        (knowledge_repo / "README.md").write_text(
            "knowledge fixture\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "add", "README.md"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        subprocess.run(
            ["git", "commit", "-m", "seed knowledge fixture"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        subprocess.run(
            ["git", "checkout", "-b", "feature/e27-t2"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        (knowledge_repo / "notes.txt").write_text("task signal\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "notes.txt"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add E27-T2 capture notes"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        subprocess.run(
            ["git", "checkout", "main"],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )
        subprocess.run(
            [
                "git",
                "merge",
                "--no-ff",
                "feature/e27-t2",
                "-m",
                "Merge pull request #999 from selftest/feature/e27-t2 E27-T2",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=knowledge_repo,
        )

        digest_dir = home / ".config" / "opencode" / "digests"
        digest_dir.mkdir(parents=True, exist_ok=True)
        (digest_dir / "e27-t2.json").write_text(
            json.dumps(
                {
                    "timestamp": "2026-02-14T00:00:00Z",
                    "reason": "E27-T2 lifecycle verification",
                    "cwd": str(knowledge_repo),
                    "branch": "main",
                    "changes": 3,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        pr_signals = collect_pr_signals(knowledge_repo, limit=5)
        expect(
            any(
                int(item.get("metadata", {}).get("pr_number") or 0) == 999
                for item in pr_signals
            ),
            "knowledge pipeline should extract merged PR signals with PR number",
        )

        digest_signals = collect_task_digest_signals(digest_dir, limit=5)
        expect(
            any(
                str(item.get("source_link", "")).startswith("digest:")
                for item in digest_signals
            ),
            "knowledge pipeline should extract task digest signals",
        )

        knowledge_drafts = generate_draft_entries(pr_signals + digest_signals)
        e27_draft = next(
            (
                entry
                for entry in knowledge_drafts
                if str(entry.get("entry_id", "")).startswith("kc-e27-t2")
            ),
            None,
        )
        expect(
            isinstance(e27_draft, dict)
            and len(e27_draft.get("evidence_sources", [])) >= 2,
            "knowledge pipeline should generate grouped draft entries with source links",
        )

        reviewed_entry, review_failures = transition_entry(
            e27_draft,
            target_status="review",
        )
        expect(
            not review_failures and reviewed_entry.get("status") == "review",
            "knowledge pipeline should allow draft-to-review transition when quality gates pass",
        )

        published_entry, publish_failures = transition_entry(
            reviewed_entry,
            target_status="published",
            approved_by="selftest-reviewer",
        )
        expect(
            not publish_failures and published_entry.get("status") == "published",
            "knowledge pipeline should allow review-to-published transition with approval metadata",
        )

        learn_env = os.environ.copy()
        learn_env["OPENCODE_CONFIG_PATH"] = str(cfg)
        learn_env["HOME"] = str(home)
        learn_env.pop("SUPERMEMORY_API_KEY", None)
        learn_env.pop("MORPH_API_KEY", None)

        learn_capture = subprocess.run(
            [
                sys.executable,
                str(LEARN_COMMAND_SCRIPT),
                "capture",
                "--limit",
                "5",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=learn_env,
            check=False,
            cwd=knowledge_repo,
        )
        expect(
            learn_capture.returncode == 0,
            "learn capture should succeed",
        )
        learn_capture_payload = parse_json_output(learn_capture.stdout)
        expect(
            int(learn_capture_payload.get("total_entries", 0)) >= 1,
            "learn capture should persist at least one entry",
        )
        captured_entries = learn_capture_payload.get("entries", [])
        capture_entry_id = ""
        if isinstance(captured_entries, list):
            for entry in captured_entries:
                if not isinstance(entry, dict):
                    continue
                if len(entry.get("evidence_sources", [])) >= 2:
                    capture_entry_id = str(entry.get("entry_id", ""))
                    break
            if (
                not capture_entry_id
                and captured_entries
                and isinstance(captured_entries[0], dict)
            ):
                capture_entry_id = str(captured_entries[0].get("entry_id", ""))
        expect(bool(capture_entry_id), "learn capture should return an entry id")

        learn_entries_path = Path(str(learn_capture_payload.get("entries_path", "")))
        if learn_entries_path.exists():
            learn_entries_payload = json.loads(
                learn_entries_path.read_text(encoding="utf-8")
            )
            if isinstance(learn_entries_payload, list):
                mutated_entries = []
                for entry in learn_entries_payload:
                    if not isinstance(entry, dict):
                        continue
                    if str(entry.get("entry_id", "")) == capture_entry_id:
                        sources = [
                            str(item) for item in entry.get("evidence_sources", [])
                        ]
                        if len(sources) < 2:
                            sources.append("digest:selftest-extra-source.json")
                        entry["evidence_sources"] = sorted(set(sources))
                    mutated_entries.append(entry)
                learn_entries_path.write_text(
                    json.dumps(mutated_entries, indent=2) + "\n",
                    encoding="utf-8",
                )

        learn_review_low_confidence = subprocess.run(
            [
                sys.executable,
                str(LEARN_COMMAND_SCRIPT),
                "review",
                "--entry-id",
                capture_entry_id,
                "--confidence",
                "40",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=learn_env,
            check=False,
            cwd=knowledge_repo,
        )
        expect(
            learn_review_low_confidence.returncode != 0,
            "learn review should fail when confidence is below threshold",
        )

        learn_review = subprocess.run(
            [
                sys.executable,
                str(LEARN_COMMAND_SCRIPT),
                "review",
                "--entry-id",
                capture_entry_id,
                "--summary",
                "E27-T2 reviewed guidance",
                "--confidence",
                "88",
                "--risk",
                "high",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=learn_env,
            check=False,
            cwd=knowledge_repo,
        )
        expect(
            learn_review.returncode == 0,
            "learn review should succeed",
        )
        learn_review_payload = parse_json_output(learn_review.stdout)
        expect(
            str(learn_review_payload.get("status", "")) == "review",
            "learn review should promote entry to review status",
        )

        learn_publish_requires_second_approval = subprocess.run(
            [
                sys.executable,
                str(LEARN_COMMAND_SCRIPT),
                "publish",
                "--entry-id",
                capture_entry_id,
                "--approved-by",
                "selftest-reviewer",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=learn_env,
            check=False,
            cwd=knowledge_repo,
        )
        expect(
            learn_publish_requires_second_approval.returncode != 0,
            "learn publish should fail for high-risk entries without second approval",
        )

        learn_publish = subprocess.run(
            [
                sys.executable,
                str(LEARN_COMMAND_SCRIPT),
                "publish",
                "--entry-id",
                capture_entry_id,
                "--approved-by",
                "selftest-reviewer-2",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=learn_env,
            check=False,
            cwd=knowledge_repo,
        )
        expect(
            learn_publish.returncode == 0,
            "learn publish should succeed after second approval",
        )
        learn_publish_payload = parse_json_output(learn_publish.stdout)
        expect(
            str(learn_publish_payload.get("status", "")) == "published",
            "learn publish should promote entry to published status",
        )
        expect(
            isinstance(learn_publish_payload.get("integrations", {}), dict),
            "learn publish should return integration payload",
        )

        learn_search = subprocess.run(
            [
                sys.executable,
                str(LEARN_COMMAND_SCRIPT),
                "search",
                "--query",
                "e27-t2",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=learn_env,
            check=False,
            cwd=knowledge_repo,
        )
        expect(
            learn_search.returncode == 0,
            "learn search should succeed",
        )
        learn_search_payload = parse_json_output(learn_search.stdout)
        expect(
            int(learn_search_payload.get("count", 0)) >= 1,
            "learn search should return matching entries",
        )

        learn_doctor = subprocess.run(
            [sys.executable, str(LEARN_COMMAND_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=learn_env,
            check=False,
            cwd=knowledge_repo,
        )
        expect(
            learn_doctor.returncode == 0,
            "learn doctor should pass when command and contract are present",
        )
        learn_doctor_payload = parse_json_output(learn_doctor.stdout)
        expect(
            learn_doctor_payload.get("result") == "PASS",
            "learn doctor should report pass",
        )

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

        # Plugin stable should pass doctor in isolated HOME.
        result = run_script(PLUGIN_SCRIPT, cfg, home, "profile", "stable")
        expect(result.returncode == 0, f"plugin profile stable failed: {result.stderr}")

        result = run_script(PLUGIN_SCRIPT, cfg, home, "doctor", "--json")
        expect(
            result.returncode == 0,
            "plugin doctor stable should pass",
        )

        # Plugin experimental should fail doctor when MORPH_API_KEY is absent.
        result = run_script(PLUGIN_SCRIPT, cfg, home, "profile", "experimental")
        expect(
            result.returncode == 0,
            f"plugin profile experimental failed: {result.stderr}",
        )

        result = run_script(PLUGIN_SCRIPT, cfg, home, "doctor", "--json")
        expect(
            result.returncode == 1,
            "plugin doctor experimental should fail when MORPH_API_KEY is absent",
        )
        report = parse_json_output(result.stdout)
        problems = "\n".join(report.get("problems", []))
        expect("morph enabled" in problems, "expected morph key problem")

        result = run_script(PLUGIN_SCRIPT, cfg, home, "setup-keys")
        expect(result.returncode == 0, f"plugin setup-keys failed: {result.stderr}")
        expect("[morph]" in result.stdout, "setup-keys missing morph section")

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
                "github:JRedeker/opencode-morph-fast-apply",
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
            "morph: enabled" in result.stdout,
            "project layered config should enable morph",
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
        session_index_path = home / ".config" / "opencode" / "sessions" / "index.json"
        session_index_path.parent.mkdir(parents=True, exist_ok=True)
        session_index_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": "2025-01-01T00:00:00+00:00",
                    "sessions": [
                        {
                            "session_id": "stale-session",
                            "cwd": "/tmp/stale",
                            "started_at": "2025-01-01T00:00:00+00:00",
                            "last_event_at": "2025-01-01T00:00:00+00:00",
                            "event_count": 1,
                            "last_reason": "manual",
                            "reasons": ["manual"],
                            "plan_ids": [],
                            "events": [
                                {
                                    "timestamp": "2025-01-01T00:00:00+00:00",
                                    "reason": "manual",
                                    "changes": 0,
                                    "branch": "main",
                                    "plan_status": "idle",
                                    "plan_id": None,
                                }
                            ],
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        digest_env = os.environ.copy()
        digest_env["MY_OPENCODE_DIGEST_PATH"] = str(digest_path)
        digest_env["MY_OPENCODE_SESSION_INDEX_PATH"] = str(session_index_path)
        digest_env["MY_OPENCODE_SESSION_ID"] = "selftest-session"

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
        raw_session_index_result = digest.get("session_index")
        session_index_result: dict = (
            raw_session_index_result
            if isinstance(raw_session_index_result, dict)
            else {}
        )
        expect(
            session_index_result.get("result") == "PASS",
            "digest run should persist session metadata index",
        )

        raw_session_index = load_json_file(session_index_path)
        session_index: dict = (
            raw_session_index if isinstance(raw_session_index, dict) else {}
        )
        raw_index_sessions = session_index.get("sessions")
        index_sessions: list[dict] = (
            raw_index_sessions if isinstance(raw_index_sessions, list) else []
        )
        expect(
            isinstance(index_sessions, list)
            and any(
                isinstance(item, dict)
                and item.get("session_id") == "selftest-session"
                and int(item.get("event_count", 0)) >= 1
                for item in index_sessions
            ),
            "session index should include active selftest session entry",
        )
        expect(
            not any(
                isinstance(item, dict) and item.get("session_id") == "stale-session"
                for item in index_sessions
            ),
            "session index should prune stale sessions using retention policy",
        )

        result = subprocess.run(
            [sys.executable, str(SESSION_SCRIPT), "list", "--json"],
            capture_output=True,
            text=True,
            env=digest_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"session list --json failed: {result.stderr}")
        session_list_payload = parse_json_output(result.stdout)
        expect(
            session_list_payload.get("result") == "PASS"
            and session_list_payload.get("count", 0) >= 1,
            "session list should return at least one indexed session",
        )

        result = subprocess.run(
            [sys.executable, str(SESSION_SCRIPT), "show", "selftest-session", "--json"],
            capture_output=True,
            text=True,
            env=digest_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"session show --json failed: {result.stderr}")
        session_show_payload = parse_json_output(result.stdout)
        expect(
            session_show_payload.get("result") == "PASS"
            and session_show_payload.get("session", {}).get("session_id")
            == "selftest-session",
            "session show should resolve indexed session by id",
        )

        result = subprocess.run(
            [sys.executable, str(SESSION_SCRIPT), "search", "selftest", "--json"],
            capture_output=True,
            text=True,
            env=digest_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"session search --json failed: {result.stderr}")
        session_search_payload = parse_json_output(result.stdout)
        expect(
            session_search_payload.get("result") == "PASS"
            and session_search_payload.get("count", 0) >= 1,
            "session search should match indexed selftest session",
        )

        result = subprocess.run(
            [sys.executable, str(SESSION_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=digest_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(result.returncode == 0, f"session doctor --json failed: {result.stderr}")
        session_doctor_payload = parse_json_output(result.stdout)
        expect(
            session_doctor_payload.get("result") == "PASS",
            "session doctor should pass when index is readable",
        )

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

        quality_env = os.environ.copy()
        quality_env["OPENCODE_CONFIG_PATH"] = str(layered_cfg_path)
        quality_env["HOME"] = str(home)

        def run_quality(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(QUALITY_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=quality_env,
                check=False,
            )

        result = run_quality("profile", "strict", "--json")
        expect(
            result.returncode == 0, f"quality profile strict failed: {result.stderr}"
        )
        quality_report = parse_json_output(result.stdout)
        expect(
            quality_report.get("profile") == "strict",
            "quality profile strict should persist strict profile",
        )

        result = run_quality("status", "--json")
        expect(result.returncode == 0, f"quality status failed: {result.stderr}")
        quality_status = parse_json_output(result.stdout)
        expect(
            quality_status.get("quality", {}).get("ts", {}).get("tests") is True,
            "quality strict profile should enable ts tests",
        )

        result = run_quality("doctor", "--json")
        expect(result.returncode == 0, f"quality doctor failed: {result.stderr}")
        quality_doctor = parse_json_output(result.stdout)
        expect(
            quality_doctor.get("result") == "PASS",
            "quality doctor should pass for valid profile",
        )

        gateway_env = os.environ.copy()
        gateway_env["OPENCODE_CONFIG_PATH"] = str(layered_cfg_path)
        gateway_env["HOME"] = str(home)
        gateway_cwd = tmp / "gateway-cwd"
        gateway_cwd.mkdir(parents=True, exist_ok=True)

        def run_gateway(
            *args: str,
            cwd: Path | None = None,
            env_override: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            env = dict(gateway_env)
            if env_override:
                env.update(env_override)
            return subprocess.run(
                [sys.executable, str(GATEWAY_SCRIPT), *args],
                capture_output=True,
                text=True,
                env=env,
                check=False,
                cwd=str(cwd or gateway_cwd),
            )

        result = run_gateway("status", "--json")
        expect(result.returncode == 0, f"gateway status failed: {result.stderr}")
        gateway_status = parse_json_output(result.stdout)
        expect(
            gateway_status.get("result") == "PASS",
            "gateway status should return PASS",
        )
        expect(
            isinstance(gateway_status.get("orphan_cleanup"), dict),
            "gateway status should report orphan cleanup telemetry",
        )
        expect(
            isinstance(gateway_status.get("hook_diagnostics"), dict),
            "gateway status should report gateway-core hook diagnostics",
        )
        expect(
            "dist_exposes_tool_execute_before"
            in gateway_status.get("hook_diagnostics", {}),
            "gateway status hook diagnostics should include dist tool hook marker",
        )
        expect(
            isinstance(gateway_status.get("event_audit_enabled"), bool)
            and isinstance(gateway_status.get("event_audit_path"), str)
            and isinstance(gateway_status.get("event_audit_exists"), bool),
            "gateway status should expose event audit toggle and path telemetry",
        )
        expect(
            isinstance(gateway_status.get("plugin_entry_count"), int)
            and isinstance(gateway_status.get("plugin_entries"), list),
            "gateway status should expose plugin entry dedupe telemetry",
        )
        expect(
            isinstance(gateway_status.get("runtime_staleness"), dict)
            and isinstance(gateway_status.get("process_pressure"), dict),
            "gateway status should expose runtime staleness and process pressure telemetry",
        )
        expect(
            isinstance(gateway_status.get("guard_event_counters"), dict),
            "gateway status should expose guard event counters",
        )
        expect(
            isinstance(
                gateway_status.get("guard_event_counters", {}).get(
                    "recent_context_warnings"
                ),
                int,
            )
            and isinstance(
                gateway_status.get("guard_event_counters", {}).get(
                    "recent_compactions"
                ),
                int,
            )
            and isinstance(
                gateway_status.get("guard_event_counters", {}).get(
                    "recent_global_process_pressure_warnings"
                ),
                int,
            )
            and isinstance(
                gateway_status.get("guard_event_counters", {}).get(
                    "recent_global_process_pressure_critical_events"
                ),
                int,
            )
            and isinstance(
                gateway_status.get("guard_event_counters", {}).get(
                    "session_pressure_attribution"
                ),
                list,
            ),
            "gateway status guard counters should include recent window metrics",
        )

        stale_loop_state_path = gateway_cwd / ".opencode" / "gateway-core.state.json"
        stale_loop_state_path.parent.mkdir(parents=True, exist_ok=True)
        stale_loop_state_path.write_text(
            json.dumps(
                {
                    "activeLoop": {
                        "active": True,
                        "sessionId": "bridge-selftest",
                        "startedAt": "2025-01-01T00:00:00Z",
                    },
                    "lastUpdatedAt": "2025-01-01T00:00:00Z",
                    "source": "selftest-fixture",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        result = run_gateway("status", "--json")
        expect(
            result.returncode == 0,
            f"gateway status stale cleanup failed: {result.stderr}",
        )
        gateway_status_stale = parse_json_output(result.stdout)
        expect(
            gateway_status_stale.get("orphan_cleanup", {}).get("changed") is True,
            "gateway status should deactivate stale orphan loop",
        )
        expect(
            gateway_status_stale.get("orphan_cleanup", {}).get("reason")
            == "stale_loop_deactivated",
            "gateway status should report stale orphan reason code",
        )
        expect(
            gateway_status_stale.get("loop_state", {})
            .get("activeLoop", {})
            .get("active")
            is False,
            "gateway status should persist inactive loop after orphan cleanup",
        )

        result = run_gateway(
            "enable",
            "--force",
            "--json",
        )
        expect(result.returncode == 0, f"gateway enable failed: {result.stderr}")
        gateway_enabled = parse_json_output(result.stdout)
        expect(
            gateway_enabled.get("enabled") is True,
            "gateway enable should set plugin entry enabled",
        )

        layered_cfg = json.loads(layered_cfg_path.read_text(encoding="utf-8"))
        plugin_list = layered_cfg.get("plugin")
        if isinstance(plugin_list, list):
            duplicate_spec = (
                "file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core"
            )
            if duplicate_spec not in plugin_list:
                plugin_list.append(duplicate_spec)
            layered_cfg["plugin"] = plugin_list
            layered_cfg_path.write_text(
                json.dumps(layered_cfg, indent=2) + "\n", encoding="utf-8"
            )

        result = run_gateway("doctor", "--json")
        expect(
            result.returncode == 1,
            "gateway doctor should fail when gateway plugin is configured multiple times while enabled",
        )
        gateway_doctor_duplicate = parse_json_output(result.stdout)
        expect(
            any(
                "configured multiple times" in str(item)
                for item in gateway_doctor_duplicate.get("problems", [])
            ),
            "gateway doctor should report duplicate gateway plugin entries as problems",
        )

        result = run_gateway("enable", "--force", "--json")
        expect(
            result.returncode == 0,
            "gateway enable --force should normalize duplicate gateway plugin entries",
        )

        result = run_gateway(
            "enable",
            "--json",
            env_override={"MY_OPENCODE_GATEWAY_FORCE_BUN_AVAILABLE": "0"},
        )
        expect(
            result.returncode == 1,
            "gateway enable should fail safely when bun runtime is unavailable",
        )
        gateway_enable_blocked = parse_json_output(result.stdout)
        expect(
            gateway_enable_blocked.get("reason_code")
            == "gateway_enable_blocked_for_safety"
            and gateway_enable_blocked.get("enabled") is False,
            "gateway enable safety fallback should keep plugin disabled after failed preflight",
        )

        result = run_gateway("disable", "--json")
        expect(result.returncode == 0, f"gateway disable failed: {result.stderr}")
        gateway_disabled = parse_json_output(result.stdout)
        expect(
            gateway_disabled.get("enabled") is False,
            "gateway disable should remove plugin entry",
        )

        result = run_gateway("doctor", "--json")
        expect(result.returncode == 0, f"gateway doctor failed: {result.stderr}")
        gateway_doctor = parse_json_output(result.stdout)
        expect(
            gateway_doctor.get("result") == "PASS",
            "gateway doctor should pass in default disabled mode",
        )
        expect(
            isinstance(gateway_doctor.get("status", {}).get("orphan_cleanup"), dict),
            "gateway doctor should include orphan cleanup telemetry in status",
        )
        expect(
            isinstance(gateway_doctor.get("status", {}).get("hook_diagnostics"), dict),
            "gateway doctor should include hook diagnostics in status",
        )
        expect(
            isinstance(gateway_doctor.get("status", {}).get("process_pressure"), dict)
            and isinstance(
                gateway_doctor.get("status", {}).get("runtime_staleness"), dict
            ),
            "gateway doctor should include process pressure and runtime staleness telemetry",
        )
        expect(
            isinstance(
                gateway_doctor.get("status", {}).get("guard_event_counters"), dict
            ),
            "gateway doctor should include guard event counters telemetry",
        )
        expect(
            isinstance(gateway_doctor.get("remediation_commands"), list),
            "gateway doctor should expose remediation command block",
        )

        audit_fixture_path = gateway_cwd / ".opencode" / "gateway-events-selftest.jsonl"
        audit_fixture_path.parent.mkdir(parents=True, exist_ok=True)
        now_ts = datetime.now(UTC)
        audit_fixture_rows = [
            {
                "timestamp": (now_ts - timedelta(minutes=1)).isoformat(),
                "hook": "global-process-pressure",
                "reason_code": "global_process_pressure_critical_appended",
                "session_id": "session-selftest-critical",
                "max_rss_mb": 11500,
            },
            {
                "timestamp": (now_ts - timedelta(minutes=2)).isoformat(),
                "hook": "global-process-pressure",
                "reason_code": "global_process_pressure_critical_detected_no_append",
                "session_id": "session-selftest-critical",
                "max_rss_mb": 11800,
            },
            {
                "timestamp": (now_ts - timedelta(minutes=3)).isoformat(),
                "hook": "global-process-pressure",
                "reason_code": "global_process_pressure_warning_appended",
                "session_id": "session-selftest-warning",
                "max_rss_mb": 1700,
            },
        ]
        audit_fixture_path.write_text(
            "\n".join(json.dumps(row) for row in audit_fixture_rows) + "\n",
            encoding="utf-8",
        )

        result = run_gateway(
            "doctor",
            "--json",
            env_override={
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_fixture_path)
            },
        )
        expect(
            result.returncode == 0,
            f"gateway doctor with audit fixture failed: {result.stderr}",
        )
        gateway_doctor_critical = parse_json_output(result.stdout)
        expect(
            gateway_doctor_critical.get("result") == "PASS",
            "gateway doctor with audit fixture should stay in pass state",
        )
        expect(
            any(
                "recent critical global pressure" in str(item)
                for item in gateway_doctor_critical.get("warnings", [])
            ),
            "gateway doctor should surface recent critical pressure warning from audit fixture",
        )
        expect(
            "/autopilot pause"
            in gateway_doctor_critical.get("remediation_commands", []),
            "gateway doctor remediation commands should include autopilot pause",
        )
        expect(
            isinstance(gateway_doctor_critical.get("manual_emergency_steps"), list),
            "gateway doctor should expose manual emergency steps",
        )

        result = run_gateway(
            "tune",
            "memory",
            "--json",
            env_override={
                "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_fixture_path)
            },
        )
        expect(
            result.returncode == 0,
            f"gateway tune memory with audit fixture failed: {result.stderr}",
        )
        gateway_tune_critical = parse_json_output(result.stdout)
        expect(
            int(
                gateway_tune_critical.get("status_snapshot", {})
                .get("guard_event_counters", {})
                .get("recent_global_process_pressure_critical_events", 0)
            )
            >= 1,
            "gateway tune memory should report recent critical event counts from audit fixture",
        )
        expect(
            any(
                "critical global process pressure observed" in str(item)
                for item in gateway_tune_critical.get("rationale", [])
            ),
            "gateway tune memory rationale should include critical pressure guidance",
        )
        expect(
            isinstance(
                gateway_tune_critical.get("status_snapshot", {})
                .get("guard_event_counters", {})
                .get("session_pressure_attribution"),
                list,
            ),
            "gateway tune memory should expose session pressure attribution list",
        )

        result = run_gateway("tune", "memory", "--json")
        expect(result.returncode == 0, f"gateway tune memory failed: {result.stderr}")
        gateway_tune = parse_json_output(result.stdout)
        expect(
            gateway_tune.get("result") == "PASS"
            and isinstance(gateway_tune.get("recommended"), dict),
            "gateway tune memory should return pass payload with recommended settings",
        )
        expect(
            isinstance(
                gateway_tune.get("recommended", {})
                .get("globalProcessPressure", {})
                .get("criticalMaxRssMb"),
                int,
            )
            and isinstance(
                gateway_tune.get("recommended", {})
                .get("globalProcessPressure", {})
                .get("autoPauseOnCritical"),
                bool,
            )
            and isinstance(
                gateway_tune.get("recommended", {})
                .get("globalProcessPressure", {})
                .get("criticalPauseAfterEvents"),
                int,
            ),
            "gateway tune memory should include critical RSS auto-pause recommendations",
        )
        expect(
            isinstance(
                gateway_tune.get("recommended", {})
                .get("pressureEscalationGuard", {})
                .get("maxContinueBeforeBlock"),
                int,
            )
            and isinstance(
                gateway_tune.get("recommended", {})
                .get("pressureEscalationGuard", {})
                .get("blockedSubagentTypes"),
                list,
            ),
            "gateway tune memory should include pressure escalation guard recommendations",
        )

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

        analyzer_missing_evidence_diff = tmp / "pr_review_missing_evidence.diff"
        analyzer_missing_evidence_diff.write_text(
            """diff --git a/scripts/new_logic.py b/scripts/new_logic.py
index 1111111..2222222 100644
--- a/scripts/new_logic.py
+++ b/scripts/new_logic.py
@@ -0,0 +1,2 @@
+def compute_total(values):
+    return sum(values)
""",
            encoding="utf-8",
        )
        analyzer_missing_evidence = subprocess.run(
            [
                sys.executable,
                str(PR_REVIEW_ANALYZER_SCRIPT),
                "analyze",
                "--diff-file",
                str(analyzer_missing_evidence_diff),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            analyzer_missing_evidence.returncode == 0,
            "pr-review analyzer should parse synthetic missing-evidence diff",
        )
        analyzer_missing_evidence_report = parse_json_output(
            analyzer_missing_evidence.stdout
        )
        expect(
            analyzer_missing_evidence_report.get("recommendation")
            == "changes_requested",
            "pr-review analyzer should request changes when tests/docs evidence is missing",
        )
        expect(
            set(analyzer_missing_evidence_report.get("missing_evidence", []))
            == {"CHANGELOG", "README", "tests"},
            "pr-review analyzer should report deterministic missing evidence keys",
        )

        analyzer_security_diff = tmp / "pr_review_security.diff"
        analyzer_security_diff.write_text(
            """diff --git a/scripts/unsafe_runner.py b/scripts/unsafe_runner.py
index 3333333..4444444 100644
--- a/scripts/unsafe_runner.py
+++ b/scripts/unsafe_runner.py
@@ -10,0 +11,2 @@
+def run(raw):
+    return eval(raw)
""",
            encoding="utf-8",
        )
        analyzer_security = subprocess.run(
            [
                sys.executable,
                str(PR_REVIEW_ANALYZER_SCRIPT),
                "analyze",
                "--diff-file",
                str(analyzer_security_diff),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            analyzer_security.returncode == 0,
            "pr-review analyzer should parse synthetic security diff",
        )
        analyzer_security_report = parse_json_output(analyzer_security.stdout)
        expect(
            analyzer_security_report.get("recommendation") == "block",
            "pr-review analyzer should block high-severity security findings with hard evidence",
        )
        expect(
            any(
                finding.get("category") == "security"
                for finding in analyzer_security_report.get("findings", [])
                if isinstance(finding, dict)
            ),
            "pr-review analyzer should emit security category findings",
        )

        pr_review_command_report = subprocess.run(
            [
                sys.executable,
                str(PR_REVIEW_COMMAND_SCRIPT),
                "--diff-file",
                str(analyzer_missing_evidence_diff),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            pr_review_command_report.returncode == 0,
            "pr-review command should succeed for synthetic diff",
        )
        pr_review_command_payload = parse_json_output(pr_review_command_report.stdout)
        checklist = pr_review_command_payload.get("checklist", {})
        checks = checklist.get("checks", []) if isinstance(checklist, dict) else []
        expect(
            isinstance(checks, list) and len(checks) >= 4,
            "pr-review command should include deterministic pre-merge checklist entries",
        )

        pr_review_command_doctor = subprocess.run(
            [sys.executable, str(PR_REVIEW_COMMAND_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            pr_review_command_doctor.returncode == 0,
            "pr-review doctor should pass when command and rubric files are present",
        )
        pr_review_doctor_payload = parse_json_output(pr_review_command_doctor.stdout)
        expect(
            pr_review_doctor_payload.get("result") == "PASS"
            and pr_review_doctor_payload.get("analyzer_exists") is True,
            "pr-review doctor should confirm analyzer readiness",
        )

        analyzer_docs_only_diff = tmp / "pr_review_docs_only.diff"
        analyzer_docs_only_diff.write_text(
            """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -10,0 +11,2 @@
+## Notes
+Updated documentation only.
""",
            encoding="utf-8",
        )
        analyzer_docs_only = subprocess.run(
            [
                sys.executable,
                str(PR_REVIEW_ANALYZER_SCRIPT),
                "analyze",
                "--diff-file",
                str(analyzer_docs_only_diff),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            analyzer_docs_only.returncode == 0,
            "pr-review analyzer should parse docs-only diff",
        )
        analyzer_docs_only_report = parse_json_output(analyzer_docs_only.stdout)
        expect(
            analyzer_docs_only_report.get("recommendation") == "approve",
            "pr-review analyzer should avoid false positives for docs-only changes",
        )
        expect(
            not analyzer_docs_only_report.get("findings"),
            "pr-review analyzer should keep docs-only default output low-noise",
        )

        analyzer_tested_change_diff = tmp / "pr_review_tested_change.diff"
        analyzer_tested_change_diff.write_text(
            """diff --git a/scripts/calc.py b/scripts/calc.py
index 1111111..2222222 100644
--- a/scripts/calc.py
+++ b/scripts/calc.py
@@ -1,0 +1,2 @@
+def calc_total(values):
+    return sum(values)
diff --git a/tests/test_calc.py b/tests/test_calc.py
index 3333333..4444444 100644
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -1,0 +1,2 @@
+def test_calc_total():
+    assert True
""",
            encoding="utf-8",
        )
        analyzer_tested_change = subprocess.run(
            [
                sys.executable,
                str(PR_REVIEW_ANALYZER_SCRIPT),
                "analyze",
                "--diff-file",
                str(analyzer_tested_change_diff),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            analyzer_tested_change.returncode == 0,
            "pr-review analyzer should parse tested source-change diff",
        )
        analyzer_tested_change_report = parse_json_output(analyzer_tested_change.stdout)
        expect(
            "tests"
            not in set(analyzer_tested_change_report.get("missing_evidence", [])),
            "pr-review analyzer should not report missing tests when test files changed",
        )

        release_engine_doctor = subprocess.run(
            [sys.executable, str(RELEASE_TRAIN_ENGINE_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            release_engine_doctor.returncode == 0,
            "release-train engine doctor should pass when policy contract exists",
        )
        release_engine_doctor_payload = parse_json_output(release_engine_doctor.stdout)
        expect(
            release_engine_doctor_payload.get("result") == "PASS"
            and release_engine_doctor_payload.get("contract_exists") is True,
            "release-train engine doctor should confirm policy contract wiring",
        )

        release_engine_prepare = subprocess.run(
            [
                sys.executable,
                str(RELEASE_TRAIN_ENGINE_SCRIPT),
                "prepare",
                "--version",
                "0.0.1",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            release_engine_prepare.returncode == 1,
            "release-train prepare should block invalid release preconditions",
        )
        release_engine_prepare_payload = parse_json_output(
            release_engine_prepare.stdout
        )
        expect(
            "changelog_missing_version"
            in set(release_engine_prepare_payload.get("reason_codes", [])),
            "release-train prepare should report missing changelog version evidence",
        )

        release_engine_draft = subprocess.run(
            [
                sys.executable,
                str(RELEASE_TRAIN_ENGINE_SCRIPT),
                "draft",
                "--head",
                "HEAD",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            release_engine_draft.returncode == 0,
            "release-train draft should generate release note entries",
        )
        release_engine_draft_payload = parse_json_output(release_engine_draft.stdout)
        expect(
            release_engine_draft_payload.get("result") == "PASS"
            and isinstance(release_engine_draft_payload.get("entries"), list),
            "release-train draft should emit structured release note entries",
        )

        release_command_doctor = subprocess.run(
            [sys.executable, str(RELEASE_TRAIN_COMMAND_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            release_command_doctor.returncode == 0,
            "release-train command doctor should pass",
        )
        release_command_doctor_payload = parse_json_output(
            release_command_doctor.stdout
        )
        expect(
            release_command_doctor_payload.get("result") == "PASS"
            and release_command_doctor_payload.get("engine_exists") is True,
            "release-train command doctor should confirm engine availability",
        )

        release_command_prepare = subprocess.run(
            [
                sys.executable,
                str(RELEASE_TRAIN_COMMAND_SCRIPT),
                "prepare",
                "--version",
                "0.0.1",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            release_command_prepare.returncode == 1,
            "release-train command should block prepare when preconditions fail",
        )
        release_command_prepare_payload = parse_json_output(
            release_command_prepare.stdout
        )
        expect(
            "reason_codes" in release_command_prepare_payload,
            "release-train command prepare should emit reason codes",
        )

        release_repo = tmp / "release_repo"
        release_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "-b", "main"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )
        subprocess.run(
            ["git", "config", "user.email", "selftest@example.com"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )
        subprocess.run(
            ["git", "config", "user.name", "Selftest"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )
        (release_repo / "Makefile").write_text(
            "validate:\n\t@true\nselftest:\n\t@true\ninstall-test:\n\t@true\n",
            encoding="utf-8",
        )
        (release_repo / "CHANGELOG.md").write_text(
            "## v1.0.0\n\n- baseline release\n\n## v1.1.0\n\n- breaking: incompatible flag removal\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "Makefile", "CHANGELOG.md"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )
        subprocess.run(
            ["git", "commit", "-m", "seed release fixture"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )
        subprocess.run(
            ["git", "tag", "v1.0.0"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )

        release_engine_breaking = subprocess.run(
            [
                sys.executable,
                str(RELEASE_TRAIN_ENGINE_SCRIPT),
                "prepare",
                "--repo-root",
                str(release_repo),
                "--version",
                "1.1.0",
                "--allowed-branch-re",
                ".*",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            release_engine_breaking.returncode == 1,
            "release-train prepare should block changelog breaking mismatches",
        )
        release_engine_breaking_payload = parse_json_output(
            release_engine_breaking.stdout
        )
        expect(
            "version_mismatch_breaking_change"
            in set(release_engine_breaking_payload.get("reason_codes", [])),
            "release-train prepare should report breaking-change version mismatch",
        )

        (release_repo / "CHANGELOG.md").write_text(
            "## v1.0.0\n\n- baseline release\n\n## v1.0.1\n\n- patch follow-up\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "CHANGELOG.md"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )
        subprocess.run(
            ["git", "commit", "-m", "prepare patch release changelog"],
            capture_output=True,
            text=True,
            check=False,
            cwd=release_repo,
        )

        release_publish_dry_run = subprocess.run(
            [
                sys.executable,
                str(RELEASE_TRAIN_COMMAND_SCRIPT),
                "publish",
                "--repo-root",
                str(release_repo),
                "--version",
                "1.0.1",
                "--allowed-branch-re",
                ".*",
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
            release_publish_dry_run.returncode == 0,
            "release-train publish dry-run should pass when preconditions are met",
        )
        release_publish_dry_run_payload = parse_json_output(
            release_publish_dry_run.stdout
        )
        expect(
            release_publish_dry_run_payload.get("result") == "PASS"
            and release_publish_dry_run_payload.get("dry_run") is True,
            "release-train publish dry-run should emit pass payload",
        )

        release_publish_confirmation = subprocess.run(
            [
                sys.executable,
                str(RELEASE_TRAIN_COMMAND_SCRIPT),
                "publish",
                "--repo-root",
                str(release_repo),
                "--version",
                "1.0.1",
                "--allowed-branch-re",
                ".*",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            release_publish_confirmation.returncode == 1,
            "release-train publish should require explicit confirmation when not dry-run",
        )
        release_publish_confirmation_payload = parse_json_output(
            release_publish_confirmation.stdout
        )
        expect(
            "confirmation_required"
            in set(release_publish_confirmation_payload.get("reason_codes", [])),
            "release-train publish should emit confirmation_required reason code",
        )

        hotfix_repo = tmp / "hotfix_repo"
        hotfix_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "-b", "main"],
            capture_output=True,
            text=True,
            check=False,
            cwd=hotfix_repo,
        )
        subprocess.run(
            ["git", "config", "user.email", "selftest@example.com"],
            capture_output=True,
            text=True,
            check=False,
            cwd=hotfix_repo,
        )
        subprocess.run(
            ["git", "config", "user.name", "Selftest"],
            capture_output=True,
            text=True,
            check=False,
            cwd=hotfix_repo,
        )
        (hotfix_repo / "README.md").write_text("hotfix fixture\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"],
            capture_output=True,
            text=True,
            check=False,
            cwd=hotfix_repo,
        )
        subprocess.run(
            ["git", "commit", "-m", "seed hotfix fixture"],
            capture_output=True,
            text=True,
            check=False,
            cwd=hotfix_repo,
        )

        (hotfix_repo / "DIRTY.md").write_text("dirty fixture\n", encoding="utf-8")
        hotfix_start_dirty = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "start",
                "--incident-id",
                "INC-DIRTY",
                "--scope",
                "patch",
                "--impact",
                "sev2",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_start_dirty.returncode == 1,
            "hotfix runtime start should fail on dirty worktree",
        )
        hotfix_start_dirty_payload = parse_json_output(hotfix_start_dirty.stdout)
        expect(
            "dirty_worktree" in set(hotfix_start_dirty_payload.get("reason_codes", [])),
            "hotfix runtime start should emit dirty_worktree reason code",
        )
        (hotfix_repo / "DIRTY.md").unlink(missing_ok=True)

        hotfix_start = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "start",
                "--incident-id",
                "INC-123",
                "--scope",
                "patch",
                "--impact",
                "sev2",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(hotfix_start.returncode == 0, "hotfix runtime start should succeed")
        hotfix_start_payload = parse_json_output(hotfix_start.stdout)
        expect(
            hotfix_start_payload.get("active") is True,
            "hotfix runtime should activate incident mode on start",
        )

        hotfix_checkpoint = subprocess.run(
            [sys.executable, str(HOTFIX_RUNTIME_SCRIPT), "checkpoint", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_checkpoint.returncode == 0,
            "hotfix runtime should create rollback checkpoint",
        )

        hotfix_mark_patch = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "mark-patch",
                "--summary",
                "apply urgent mitigation",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_mark_patch.returncode == 0,
            "hotfix runtime should capture patch timeline event",
        )

        hotfix_validate = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "validate",
                "--target",
                "validate",
                "--result",
                "pass",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_validate.returncode == 0,
            "hotfix runtime should record mandatory validation result",
        )

        hotfix_close_missing_followup = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "close",
                "--outcome",
                "resolved",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_close_missing_followup.returncode == 1,
            "hotfix runtime close should enforce follow-up requirements",
        )
        hotfix_close_missing_followup_payload = parse_json_output(
            hotfix_close_missing_followup.stdout
        )
        expect(
            "followup_issue_required"
            in set(hotfix_close_missing_followup_payload.get("reason_codes", [])),
            "hotfix runtime close should emit followup_issue_required reason code",
        )

        hotfix_close = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "close",
                "--outcome",
                "resolved",
                "--followup-issue",
                "bd-xyz",
                "--deferred-validation-owner",
                "oncall",
                "--deferred-validation-due",
                "2026-02-20",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(hotfix_close.returncode == 0, "hotfix runtime close should succeed")
        hotfix_close_payload = parse_json_output(hotfix_close.stdout)
        expect(
            hotfix_close_payload.get("result") == "PASS",
            "hotfix runtime close should report pass result",
        )

        hotfix_command_status = subprocess.run(
            [sys.executable, str(HOTFIX_COMMAND_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_command_status.returncode == 0,
            "hotfix command status should pass after runtime close",
        )
        hotfix_command_status_payload = parse_json_output(hotfix_command_status.stdout)
        expect(
            hotfix_command_status_payload.get("incident_id") == "INC-123",
            "hotfix command status should proxy runtime incident id",
        )

        hotfix_command_remind = subprocess.run(
            [sys.executable, str(HOTFIX_COMMAND_SCRIPT), "remind", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_command_remind.returncode == 0,
            "hotfix command remind should return actionable reminders",
        )
        hotfix_command_remind_payload = parse_json_output(hotfix_command_remind.stdout)
        expect(
            hotfix_command_remind_payload.get("followup_issue") == "bd-xyz",
            "hotfix command remind should surface close metadata",
        )
        expect(
            isinstance(hotfix_command_remind_payload.get("reminders"), list)
            and len(hotfix_command_remind_payload.get("reminders", [])) >= 2,
            "hotfix command remind should emit reminder list",
        )

        hotfix_command_doctor = subprocess.run(
            [sys.executable, str(HOTFIX_COMMAND_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_command_doctor.returncode == 0,
            "hotfix command doctor should pass when runtime and policy are present",
        )
        hotfix_command_doctor_payload = parse_json_output(hotfix_command_doctor.stdout)
        expect(
            hotfix_command_doctor_payload.get("result") == "PASS",
            "hotfix command doctor should report pass",
        )

        hotfix_command_restart = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_COMMAND_SCRIPT),
                "start",
                "--incident-id",
                "INC-124",
                "--scope",
                "config_only",
                "--impact",
                "sev3",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_command_restart.returncode == 0,
            "hotfix command start should allow reopening a new incident",
        )

        subprocess.run(
            [sys.executable, str(HOTFIX_RUNTIME_SCRIPT), "checkpoint", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "validate",
                "--target",
                "validate",
                "--result",
                "pass",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )

        hotfix_command_close_missing = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_COMMAND_SCRIPT),
                "close",
                "--outcome",
                "resolved",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_command_close_missing.returncode == 1,
            "hotfix command close should enforce follow-up requirements",
        )
        hotfix_command_close_missing_payload = parse_json_output(
            hotfix_command_close_missing.stdout
        )
        expect(
            "followup_issue_required"
            in set(hotfix_command_close_missing_payload.get("reason_codes", [])),
            "hotfix command close should emit followup_issue_required reason code",
        )

        hotfix_rollback_start = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "start",
                "--incident-id",
                "INC-ROLLBACK",
                "--scope",
                "rollback",
                "--impact",
                "sev1",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_rollback_start.returncode == 0,
            "hotfix runtime should allow rollback incident start",
        )
        subprocess.run(
            [sys.executable, str(HOTFIX_RUNTIME_SCRIPT), "checkpoint", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        hotfix_rollback_patch = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "mark-patch",
                "--summary",
                "rollback to stable commit",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_rollback_patch.returncode == 0,
            "hotfix runtime rollback mark-patch should succeed",
        )
        hotfix_rollback_patch_payload = parse_json_output(hotfix_rollback_patch.stdout)
        expect(
            hotfix_rollback_patch_payload.get("event") == "rollback_applied",
            "hotfix runtime should emit rollback_applied for rollback scope",
        )
        subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "validate",
                "--target",
                "validate",
                "--result",
                "pass",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        hotfix_rollback_close = subprocess.run(
            [
                sys.executable,
                str(HOTFIX_RUNTIME_SCRIPT),
                "close",
                "--outcome",
                "rolled_back",
                "--followup-issue",
                "bd-rollback",
                "--deferred-validation-owner",
                "incident-commander",
                "--deferred-validation-due",
                "2026-03-02",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=hotfix_repo,
        )
        expect(
            hotfix_rollback_close.returncode == 0,
            "hotfix runtime rollback close should succeed",
        )

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

        semantic_lsp = evaluate_semantic_capability(
            "rename",
            ["src/example.py"],
            available_binaries={
                "pyright-langserver": True,
                "python3": True,
            },
        )
        expect(
            semantic_lsp.get("result") == "PASS"
            and semantic_lsp.get("adapters", [{}])[0].get("backend") == "lsp",
            "safe-edit adapter should prefer lsp backend for rename when available",
        )

        semantic_extract_blocked = evaluate_semantic_capability(
            "extract",
            ["src/example.py"],
            available_binaries={
                "pyright-langserver": False,
                "python3": False,
            },
            allow_text_fallback=True,
            scope_explicit=True,
        )
        expect(
            semantic_extract_blocked.get("result") == "FAIL"
            and semantic_extract_blocked.get("reason_code")
            == "safe_edit_ast_unavailable",
            "safe-edit adapter should block extract when semantic backends are unavailable",
        )

        semantic_fallback_needs_opt_in = evaluate_semantic_capability(
            "rename",
            ["src/example.py"],
            available_binaries={
                "pyright-langserver": False,
                "python3": False,
            },
            allow_text_fallback=False,
            scope_explicit=True,
        )
        expect(
            semantic_fallback_needs_opt_in.get("result") == "FAIL"
            and semantic_fallback_needs_opt_in.get("reason_code")
            == "safe_edit_fallback_requires_opt_in",
            "safe-edit adapter should require explicit fallback opt-in",
        )

        semantic_fallback_ambiguous = evaluate_semantic_capability(
            "rename",
            ["src/example.py"],
            available_binaries={
                "pyright-langserver": False,
                "python3": False,
            },
            allow_text_fallback=True,
            scope_explicit=True,
            ambiguous_target=True,
        )
        expect(
            semantic_fallback_ambiguous.get("result") == "FAIL"
            and semantic_fallback_ambiguous.get("reason_code")
            == "safe_edit_fallback_blocked_ambiguity",
            "safe-edit adapter should block fallback for ambiguous targets",
        )

        ref_validation_pass = validate_changed_references(
            "def foo():\n    return foo\n",
            "def bar():\n    return bar\n",
            "foo",
            "bar",
        )
        expect(
            ref_validation_pass.get("result") == "PASS"
            and int(ref_validation_pass.get("changed_references", 0)) >= 2,
            "safe-edit adapter should validate changed references for rename paths",
        )

        ref_validation_fail = validate_changed_references(
            "def foo():\n    return foo\n",
            "def bar():\n    return foo\n",
            "foo",
            "bar",
        )
        expect(
            ref_validation_fail.get("result") == "FAIL",
            "safe-edit adapter should fail validation when old references remain",
        )

        safe_edit_status = subprocess.run(
            [sys.executable, str(SAFE_EDIT_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            safe_edit_status.returncode == 0,
            f"safe-edit status should succeed: {safe_edit_status.stderr}",
        )
        safe_edit_status_report = parse_json_output(safe_edit_status.stdout)
        expect(
            isinstance(safe_edit_status_report.get("backend_status"), dict),
            "safe-edit status should report backend availability map",
        )

        safe_edit_plan = subprocess.run(
            [
                sys.executable,
                str(SAFE_EDIT_SCRIPT),
                "plan",
                "--operation",
                "rename",
                "--scope",
                "scripts/*.py",
                "--allow-text-fallback",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            safe_edit_plan.returncode == 0,
            f"safe-edit plan should succeed for scripts scope: {safe_edit_plan.stderr}",
        )
        safe_edit_plan_report = parse_json_output(safe_edit_plan.stdout)
        expect(
            safe_edit_plan_report.get("result") == "PASS"
            and isinstance(safe_edit_plan_report.get("adapters"), list),
            "safe-edit plan should emit adapter decisions for matched files",
        )

        safe_edit_doctor = subprocess.run(
            [sys.executable, str(SAFE_EDIT_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            safe_edit_doctor.returncode == 0,
            f"safe-edit doctor should succeed in test environment: {safe_edit_doctor.stderr}",
        )
        safe_edit_doctor_report = parse_json_output(safe_edit_doctor.stdout)
        expect(
            safe_edit_doctor_report.get("result") == "PASS",
            "safe-edit doctor should report PASS when at least one backend is available",
        )

        lsp_status = subprocess.run(
            [sys.executable, str(LSP_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_status.returncode == 0,
            f"lsp status should succeed: {lsp_status.stderr}",
        )
        lsp_status_report = parse_json_output(lsp_status.stdout)
        expect(
            isinstance(lsp_status_report.get("servers"), list)
            and isinstance(lsp_status_report.get("languages"), dict),
            "lsp status should report servers and language grouping",
        )

        lsp_doctor = subprocess.run(
            [sys.executable, str(LSP_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_doctor.returncode == 0,
            f"lsp doctor should succeed: {lsp_doctor.stderr}",
        )
        lsp_doctor_report = parse_json_output(lsp_doctor.stdout)
        expect(
            lsp_doctor_report.get("result") in {"PASS", "WARN"},
            "lsp doctor should emit PASS or WARN result",
        )

        lsp_goto = subprocess.run(
            [
                sys.executable,
                str(LSP_SCRIPT),
                "goto-definition",
                "--symbol",
                "load_layered_config",
                "--scope",
                "scripts/*.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_goto.returncode == 0,
            f"lsp goto-definition should succeed: {lsp_goto.stderr}",
        )
        lsp_goto_report = parse_json_output(lsp_goto.stdout)
        expect(
            lsp_goto_report.get("backend") == "text"
            and isinstance(lsp_goto_report.get("definitions"), list),
            "lsp goto-definition should report text fallback definitions",
        )

        lsp_refs = subprocess.run(
            [
                sys.executable,
                str(LSP_SCRIPT),
                "find-references",
                "--symbol",
                "load_layered_config",
                "--scope",
                "scripts/*.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_refs.returncode == 0,
            f"lsp find-references should succeed: {lsp_refs.stderr}",
        )
        lsp_refs_report = parse_json_output(lsp_refs.stdout)
        expect(
            lsp_refs_report.get("backend") == "text"
            and isinstance(lsp_refs_report.get("references"), list),
            "lsp find-references should report text fallback references",
        )

        lsp_symbols_document = subprocess.run(
            [
                sys.executable,
                str(LSP_SCRIPT),
                "symbols",
                "--view",
                "document",
                "--file",
                "scripts/config_layering.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_symbols_document.returncode == 0,
            f"lsp symbols document view should succeed: {lsp_symbols_document.stderr}",
        )
        lsp_symbols_document_report = parse_json_output(lsp_symbols_document.stdout)
        expect(
            isinstance(lsp_symbols_document_report.get("symbols"), list),
            "lsp symbols document view should report symbol list",
        )

        lsp_symbols_workspace = subprocess.run(
            [
                sys.executable,
                str(LSP_SCRIPT),
                "symbols",
                "--view",
                "workspace",
                "--query",
                "load",
                "--scope",
                "scripts/*.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_symbols_workspace.returncode == 0,
            f"lsp symbols workspace view should succeed: {lsp_symbols_workspace.stderr}",
        )
        lsp_symbols_workspace_report = parse_json_output(lsp_symbols_workspace.stdout)
        expect(
            isinstance(lsp_symbols_workspace_report.get("symbols"), list),
            "lsp symbols workspace view should report symbol list",
        )

        lsp_prepare_rename = subprocess.run(
            [
                sys.executable,
                str(LSP_SCRIPT),
                "prepare-rename",
                "--symbol",
                "load_layered_config",
                "--new-name",
                "load_cfg",
                "--scope",
                "scripts/*.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_prepare_rename.returncode == 0,
            f"lsp prepare-rename should succeed: {lsp_prepare_rename.stderr}",
        )
        lsp_prepare_rename_report = parse_json_output(lsp_prepare_rename.stdout)
        expect(
            lsp_prepare_rename_report.get("result") in {"PASS", "WARN"},
            "lsp prepare-rename should emit PASS or WARN result",
        )

        lsp_rename_plan = subprocess.run(
            [
                sys.executable,
                str(LSP_SCRIPT),
                "rename",
                "--symbol",
                "load_layered_config",
                "--new-name",
                "load_cfg",
                "--scope",
                "scripts/*.py",
                "--allow-text-fallback",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            lsp_rename_plan.returncode == 0,
            f"lsp rename planning should succeed: {lsp_rename_plan.stderr}",
        )
        lsp_rename_plan_report = parse_json_output(lsp_rename_plan.stdout)
        expect(
            lsp_rename_plan_report.get("applied") is False
            and isinstance(lsp_rename_plan_report.get("validation"), list),
            "lsp rename planning should return validation details without applying",
        )

        cross_language_plan = evaluate_semantic_capability(
            "rename",
            [
                "src/a.py",
                "src/b.ts",
                "src/c.go",
                "src/d.rs",
            ],
            available_binaries={
                "pyright-langserver": True,
                "python3": True,
                "typescript-language-server": True,
                "node": True,
                "gopls": True,
                "go": True,
                "rust-analyzer": True,
                "cargo": True,
            },
        )
        expect(
            cross_language_plan.get("result") == "PASS"
            and len(cross_language_plan.get("adapters", [])) == 4,
            "safe-edit adapter should support deterministic cross-language backend planning",
        )

        expect(
            detect_language("src/a.py") == "python", "safe-edit should detect python"
        )
        expect(
            detect_language("src/a.ts") == "typescript",
            "safe-edit should detect typescript",
        )
        expect(detect_language("src/a.go") == "go", "safe-edit should detect go")
        expect(detect_language("src/a.rs") == "rust", "safe-edit should detect rust")

        for before_text, after_text in (
            (
                "def old_name():\n    return old_name\n",
                "def new_name():\n    return new_name\n",
            ),
            (
                "function old_name() { return old_name }\n",
                "function new_name() { return new_name }\n",
            ),
            (
                "func old_name() { _ = old_name }\n",
                "func new_name() { _ = new_name }\n",
            ),
            (
                "fn old_name() { let _x = old_name; }\n",
                "fn new_name() { let _x = new_name; }\n",
            ),
        ):
            cross_ref = validate_changed_references(
                before_text,
                after_text,
                "old_name",
                "new_name",
            )
            expect(
                cross_ref.get("result") == "PASS",
                "safe-edit changed-reference validation should pass across language samples",
            )

        fallback_scope_block = evaluate_semantic_capability(
            "rename",
            ["src/example.py"],
            available_binaries={
                "pyright-langserver": False,
                "python3": False,
            },
            allow_text_fallback=True,
            scope_explicit=False,
        )
        expect(
            fallback_scope_block.get("result") == "FAIL"
            and fallback_scope_block.get("reason_code")
            == "safe_edit_fallback_blocked_scope",
            "safe-edit fallback should fail when explicit scope is missing",
        )

        fallback_unknown_language = evaluate_semantic_capability(
            "rename",
            ["docs/unknown.txt"],
            available_binaries={
                "pyright-langserver": True,
                "python3": True,
            },
            allow_text_fallback=True,
            scope_explicit=True,
        )
        expect(
            fallback_unknown_language.get("result") == "FAIL"
            and fallback_unknown_language.get("reason_code")
            == "safe_edit_unknown_language",
            "safe-edit adapter should fail deterministically for unsupported file languages",
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

        invalid_todo_transition = validate_todo_transition(
            todo_id="todo-1",
            from_state="pending",
            to_state="done",
        )
        expect(
            isinstance(invalid_todo_transition, dict)
            and invalid_todo_transition.get("code") == "missing_bypass_metadata",
            "todo enforcement should require bypass metadata for pending->done transition",
        )

        valid_bypass_transition = validate_todo_transition(
            todo_id="todo-2",
            from_state="pending",
            to_state="done",
            bypass={
                "bypass_reason": "covered by prior migration",
                "bypass_actor": "owner",
                "bypass_at": "2026-02-13T12:05:00Z",
                "bypass_type": "scope_change",
            },
        )
        expect(
            valid_bypass_transition is None,
            "todo enforcement should allow pending->done with valid bypass metadata",
        )

        bypass_event = build_bypass_event(
            todo_id="todo-2",
            from_state="pending",
            to_state="done",
            at="2026-02-13T12:05:00Z",
            actor="owner",
            bypass={
                "bypass_reason": "covered by prior migration",
                "bypass_actor": "owner",
                "bypass_at": "2026-02-13T12:05:00Z",
                "bypass_type": "scope_change",
            },
        )
        expect(
            bypass_event.get("event") == "todo_bypass"
            and bypass_event.get("bypass", {}).get("type") == "scope_change",
            "todo enforcement should emit deterministic bypass audit event payloads",
        )

        todo_set_violations = validate_todo_set(
            [
                {"id": "todo-1", "state": "in_progress"},
                {"id": "todo-2", "state": "in_progress"},
            ]
        )
        expect(
            any(
                v.get("code") == "multiple_in_progress_items"
                for v in todo_set_violations
            ),
            "todo enforcement should detect multiple in-progress items",
        )

        completion_violations = validate_plan_completion(
            [
                {"id": "todo-1", "state": "done"},
                {"id": "todo-2", "state": "pending"},
            ]
        )
        expect(
            any(v.get("code") == "incomplete_todo_set" for v in completion_violations),
            "todo enforcement should block completion when required todos remain pending",
        )

        remediation = remediation_prompts(completion_violations)
        expect(
            len(remediation) >= 1,
            "todo enforcement should emit actionable remediation prompts",
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
        expect(
            routing_explain_report.get("fallback_reason")
            == "fallback_unavailable_model_to_category",
            "routing explain should report fallback reason for unavailable model scenario",
        )

        routing_explain_no_fallback = subprocess.run(
            [
                sys.executable,
                str(ROUTING_SCRIPT),
                "explain",
                "--category",
                "quick",
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
            routing_explain_no_fallback.returncode == 0,
            "routing explain should succeed for no-fallback scenario",
        )
        routing_explain_no_fallback_report = parse_json_output(
            routing_explain_no_fallback.stdout
        )
        expect(
            routing_explain_no_fallback_report.get("fallback_reason") == "none",
            "routing explain should report explicit no-fallback reason when first candidate is accepted",
        )

        deterministic_trace_a = resolve_model_settings(
            schema=routing_schema,
            requested_category="deep",
            user_overrides={"model": "openai/nonexistent"},
            system_defaults={
                "model": "openai/gpt-5.3-codex",
                "temperature": 0.2,
                "reasoning": "medium",
                "verbosity": "medium",
            },
            available_models={"openai/gpt-5-mini", "openai/gpt-5.3-codex"},
        )
        deterministic_trace_b = resolve_model_settings(
            schema=routing_schema,
            requested_category="deep",
            user_overrides={"model": "openai/nonexistent"},
            system_defaults={
                "model": "openai/gpt-5.3-codex",
                "temperature": 0.2,
                "reasoning": "medium",
                "verbosity": "medium",
            },
            available_models={"openai/gpt-5-mini", "openai/gpt-5.3-codex"},
        )
        expect(
            deterministic_trace_a.get("resolution_trace")
            == deterministic_trace_b.get("resolution_trace"),
            "model routing resolution trace should remain deterministic for identical inputs",
        )

        browser_status = subprocess.run(
            [sys.executable, str(BROWSER_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(browser_status.returncode == 0, "browser status should succeed")
        browser_status_report = parse_json_output(browser_status.stdout)
        expect(
            browser_status_report.get("provider") == "playwright",
            "browser status should default to playwright provider",
        )

        browser_profile = subprocess.run(
            [sys.executable, str(BROWSER_SCRIPT), "profile", "agent-browser"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(browser_profile.returncode == 0, "browser profile switch should succeed")

        browser_write_path_line = next(
            (
                line
                for line in browser_profile.stdout.splitlines()
                if line.startswith("config: ")
            ),
            "",
        )
        expect(
            bool(browser_write_path_line),
            "browser profile output should include config path",
        )
        browser_config_path = Path(
            browser_write_path_line.replace("config: ", "", 1).strip()
        )

        browser_status_after = subprocess.run(
            [sys.executable, str(BROWSER_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            browser_status_after.returncode == 0,
            "browser status should succeed after profile change",
        )
        browser_status_after_report = parse_json_output(browser_status_after.stdout)
        expect(
            browser_status_after_report.get("provider") == "agent-browser",
            "browser status should show updated provider",
        )

        expect(
            browser_config_path.exists(),
            "browser profile should persist to layered config path",
        )
        browser_cfg = load_json_file(browser_config_path)
        browser_cfg.setdefault("browser", {}).setdefault("providers", {}).setdefault(
            "agent-browser", {}
        ).setdefault("doctor", {})["required_binaries"] = ["__missing_browser_binary__"]
        browser_config_path.write_text(
            json.dumps(browser_cfg, indent=2) + "\n", encoding="utf-8"
        )

        browser_doctor = subprocess.run(
            [sys.executable, str(BROWSER_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(browser_doctor.returncode == 0, "browser doctor should succeed")
        browser_doctor_report = parse_json_output(browser_doctor.stdout)
        expect(
            browser_doctor_report.get("result") == "PASS",
            "browser doctor should keep PASS when config is valid",
        )
        warnings_text = "\n".join(browser_doctor_report.get("warnings", []))
        expect(
            "__missing_browser_binary__" in warnings_text,
            "browser doctor should report missing selected-provider dependencies",
        )

        browser_profile_reset = subprocess.run(
            [sys.executable, str(BROWSER_SCRIPT), "profile", "playwright"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            browser_profile_reset.returncode == 0,
            "browser profile should switch back to playwright",
        )
        browser_doctor_playwright = subprocess.run(
            [sys.executable, str(BROWSER_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            browser_doctor_playwright.returncode == 0,
            "browser doctor should succeed after switching back to playwright",
        )
        browser_doctor_playwright_report = parse_json_output(
            browser_doctor_playwright.stdout
        )
        expect(
            browser_doctor_playwright_report.get("provider") == "playwright"
            and browser_doctor_playwright_report.get("selected_ready") is True,
            "browser doctor should report ready selected provider after reset",
        )

        plan_path = tmp / "plan_execution_selftest.md"
        plan_path.write_text(
            """---
id: selftest-plan-001
title: Selftest Plan
owner: selftest
created_at: 2026-02-13T00:00:00Z
version: 1
---

# Plan

- [x] 1. Preserve previously completed setup
- [ ] 2. Execute pending task
- [ ] 3. Capture final checkpoint
""",
            encoding="utf-8",
        )

        start_work = subprocess.run(
            [
                sys.executable,
                str(START_WORK_SCRIPT),
                str(plan_path),
                "--deviation",
                "manual verification note",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(start_work.returncode == 0, "start-work should execute valid plan")
        start_work_report = parse_json_output(start_work.stdout)
        expect(
            start_work_report.get("status") == "completed",
            "start-work should report completed status for fully executed plan",
        )
        expect(
            start_work_report.get("step_counts", {}).get("done") == 3,
            "start-work should complete all plan steps",
        )
        expect(
            start_work_report.get("todo_compliance", {}).get("result") == "PASS",
            "start-work should report PASS todo compliance for valid plan execution",
        )
        expect(
            start_work_report.get("deviation_count", 0) >= 2,
            "start-work should capture precompleted and manual deviations",
        )
        expect(
            isinstance(start_work_report.get("budget"), dict)
            and start_work_report.get("budget", {}).get("result")
            in {"PASS", "WARN", "FAIL"},
            "start-work should include budget runtime evaluation payload",
        )

        budget_policy = resolve_budget_policy(
            {"budget_runtime": {"profile": "balanced"}}
        )
        budget_counters = build_budget_state(
            "2026-02-13T00:00:00Z",
            tool_call_count=5,
            token_estimate=100,
            now_ts="2026-02-13T00:00:05Z",
        )
        budget_eval_ok = evaluate_budget(budget_policy, budget_counters)
        expect(
            budget_eval_ok.get("result") == "PASS",
            "budget runtime should stay PASS when counters are below thresholds",
        )
        config_path = Path(str(start_work_report.get("config") or ""))

        invalid_autopilot_objective = validate_objective(
            {
                "goal": "Ship automation objective",
                "done-criteria": "all checks pass",
                "max-budget": "balanced",
            }
        )
        expect(
            invalid_autopilot_objective.get("result") == "FAIL"
            and "scope" in invalid_autopilot_objective.get("missing_fields", []),
            "autopilot objective validation should fail when required scope is missing",
        )

        autopilot_objective = {
            "goal": "Ship E28 objective",
            "scope": "scripts/autopilot_runtime.py, scripts/selftest.py",
            "done-criteria": [
                "define objective orchestration loop",
                "enforce budget and checkpoints",
                "emit progress and next actions",
            ],
            "max-budget": "conservative",
        }
        autopilot_init = initialize_run(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            objective=autopilot_objective,
            actor="selftest",
        )
        expect(
            autopilot_init.get("result") == "PASS"
            and autopilot_init.get("run", {}).get("status") == "draft",
            "autopilot runtime should initialize in draft state with dry-run requirement",
        )
        init_checkpoint_paths = autopilot_init.get("checkpoint", {}).get("paths", {})
        expect(
            Path(str(init_checkpoint_paths.get("latest", ""))).exists()
            and Path(str(init_checkpoint_paths.get("history", ""))).exists(),
            "autopilot initialization should write checkpoint latest/history files",
        )

        autopilot_run = dict(autopilot_init.get("run", {}))
        autopilot_cycle_1 = execute_cycle(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            run=autopilot_run,
            tool_call_increment=1,
            token_increment=50,
            touched_paths=["scripts/autopilot_runtime.py"],
            now_ts="2026-02-13T00:00:01Z",
        )
        expect(
            autopilot_cycle_1.get("result") == "PASS"
            and autopilot_cycle_1.get("run", {})
            .get("progress", {})
            .get("completed_cycles")
            == 1,
            "autopilot execute cycle should progress bounded cycle completion",
        )
        expect(
            isinstance(autopilot_cycle_1.get("run", {}).get("next_actions", []), list)
            and autopilot_cycle_1.get("run", {}).get("next_actions"),
            "autopilot execute cycle should emit actionable next_actions",
        )

        autopilot_promise_objective = {
            "goal": "Ship continuously until promise token is emitted",
            "scope": "scripts/autopilot_runtime.py",
            "max-budget": "balanced",
            "completion-mode": "promise",
            "completion-promise": "DONE",
        }
        autopilot_promise_init = initialize_run(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            objective=autopilot_promise_objective,
            actor="selftest",
        )
        expect(
            autopilot_promise_init.get("result") == "PASS",
            "autopilot should allow promise-mode objective without explicit done-criteria",
        )
        autopilot_promise_cycle = execute_cycle(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            run=dict(autopilot_promise_init.get("run", {})),
            tool_call_increment=1,
            token_increment=50,
            touched_paths=["scripts/autopilot_runtime.py"],
            now_ts="2026-02-13T00:00:01Z",
        )
        expect(
            autopilot_promise_cycle.get("run", {}).get("status") == "running",
            "autopilot promise mode should remain running when completion promise is not signaled",
        )
        autopilot_promise_complete = execute_cycle(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            run=dict(autopilot_promise_cycle.get("run", {})),
            tool_call_increment=1,
            token_increment=50,
            touched_paths=["scripts/autopilot_runtime.py"],
            completion_signal=True,
            now_ts="2026-02-13T00:00:02Z",
        )
        expect(
            autopilot_promise_complete.get("run", {}).get("status") == "completed"
            and autopilot_promise_complete.get("run", {}).get("reason_code")
            == "autopilot_completion_promise_detected",
            "autopilot promise mode should complete when completion signal is provided",
        )

        autopilot_promise_wallclock_run = dict(autopilot_promise_cycle.get("run", {}))
        autopilot_promise_wallclock_run["started_at"] = "2026-01-01T00:00:00Z"
        autopilot_promise_wallclock_resume = execute_cycle(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            run=autopilot_promise_wallclock_run,
            tool_call_increment=1,
            token_increment=50,
            touched_paths=["scripts/autopilot_runtime.py"],
            now_ts="2026-02-13T00:00:03Z",
        )
        expect(
            autopilot_promise_wallclock_resume.get("run", {}).get("status")
            != "budget_stopped",
            "autopilot promise mode should use rolling wall-clock anchor and avoid stale-start hard stop",
        )

        autopilot_cycle_scope_stop = execute_cycle(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            run=dict(autopilot_cycle_1.get("run", {})),
            tool_call_increment=1,
            token_increment=50,
            touched_paths=["README.md"],
            now_ts="2026-02-13T00:00:01Z",
        )
        expect(
            autopilot_cycle_scope_stop.get("result") == "FAIL"
            and autopilot_cycle_scope_stop.get("run", {}).get("status")
            == "scope_stopped",
            "autopilot execute cycle should hard-stop on out-of-scope paths",
        )
        expect(
            autopilot_cycle_scope_stop.get("run", {}).get("reason_code")
            == "scope_violation_detected"
            and "README.md"
            in autopilot_cycle_scope_stop.get("run", {}).get("scope_violations", []),
            "autopilot scope stop should preserve deterministic scope violation details",
        )

        autopilot_cycle_budget_stop = execute_cycle(
            config={"budget_runtime": {"profile": "balanced"}},
            write_path=config_path,
            run=dict(autopilot_cycle_1.get("run", {})),
            tool_call_increment=500,
            token_increment=500_000,
            touched_paths=["scripts/autopilot_runtime.py"],
            now_ts="2026-02-13T00:00:02Z",
        )
        expect(
            autopilot_cycle_budget_stop.get("result") == "FAIL"
            and autopilot_cycle_budget_stop.get("run", {}).get("status")
            == "budget_stopped",
            "autopilot execute cycle should hard-stop on budget threshold exceedance",
        )
        expect(
            str(
                autopilot_cycle_budget_stop.get("run", {}).get("reason_code", "")
            ).startswith("budget_"),
            "autopilot budget stop should expose deterministic budget reason codes",
        )

        autopilot_integration_report = integrate_controls(
            run={
                **dict(autopilot_cycle_1.get("run", {})),
                "todos": [
                    {"id": "todo-1", "state": "in_progress"},
                    {"id": "todo-2", "state": "in_progress"},
                ],
            },
            write_path=config_path,
            confidence_score=0.42,
            interruption_class="tool_failure",
        )
        expect(
            autopilot_integration_report.get("control_integrations", {})
            .get("manual_handoff", {})
            .get("mode")
            == "manual"
            and autopilot_integration_report.get("run", {}).get("status") == "paused",
            "autopilot integration should trigger manual handoff when confidence drops",
        )
        expect(
            autopilot_integration_report.get("control_integrations", {})
            .get("todo_controls", {})
            .get("result")
            == "FAIL",
            "autopilot integration should surface todo compliance violations",
        )
        expect(
            isinstance(
                autopilot_integration_report.get("control_integrations", {}).get(
                    "checkpoint_count"
                ),
                int,
            ),
            "autopilot integration should include checkpoint count from checkpoint subsystem",
        )

        autopilot_doctor = subprocess.run(
            [sys.executable, str(AUTOPILOT_COMMAND_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(autopilot_doctor.returncode == 0, "autopilot doctor should succeed")
        autopilot_doctor_report = parse_json_output(autopilot_doctor.stdout)
        expect(
            autopilot_doctor_report.get("result") == "PASS",
            "autopilot doctor should report PASS when required modules exist",
        )
        expect(
            isinstance(autopilot_doctor_report.get("gateway_hook_diagnostics"), dict),
            "autopilot doctor should include gateway hook diagnostics",
        )
        expect(
            autopilot_doctor_report.get("gateway_runtime_mode")
            in {"plugin_gateway", "python_command_bridge"}
            and autopilot_doctor_report.get("gateway_runtime_reason_code")
            in {
                "gateway_plugin_ready",
                "gateway_plugin_disabled",
                "gateway_plugin_not_ready",
                "gateway_plugin_runtime_unavailable",
            },
            "autopilot doctor should include deterministic gateway runtime mode diagnostics",
        )

        autopilot_command_start = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "start",
                "--goal",
                "Deliver selftest autopilot flow",
                "--scope",
                "scripts/autopilot_command.py",
                "--done-criteria",
                "verify start output;verify status/report controls",
                "--max-budget",
                "balanced",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_start.returncode == 0,
            "autopilot start should initialize objective runtime",
        )
        autopilot_command_start_report = parse_json_output(
            autopilot_command_start.stdout
        )
        expect(
            autopilot_command_start_report.get("result") == "PASS"
            and autopilot_command_start_report.get("run", {}).get("status") == "draft",
            "autopilot start should persist dry-run-required draft state",
        )

        autopilot_command_status = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "status",
                "--confidence",
                "0.9",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_status.returncode == 0,
            "autopilot status should return integration payload",
        )
        autopilot_command_status_report = parse_json_output(
            autopilot_command_status.stdout
        )
        expect(
            autopilot_command_status_report.get("result") == "PASS"
            and isinstance(
                autopilot_command_status_report.get("control_integrations", {}), dict
            ),
            "autopilot status should include control integration diagnostics",
        )
        expect(
            autopilot_command_status_report.get("gateway_runtime_mode")
            in {"plugin_gateway", "python_command_bridge"}
            and autopilot_command_status_report.get("gateway_runtime_reason_code")
            in {
                "gateway_plugin_ready",
                "gateway_plugin_disabled",
                "gateway_plugin_not_ready",
                "gateway_plugin_runtime_unavailable",
            },
            "autopilot status should expose deterministic gateway runtime routing mode",
        )
        expect(
            autopilot_command_status_report.get("gateway_loop_state_reason_code")
            in {
                "loop_state_available",
                "bridge_state_ignored_in_plugin_mode",
                "state_missing",
            },
            "autopilot status should include deterministic gateway loop state reason code",
        )

        forced_plugin_mode_env = dict(refactor_env)
        forced_plugin_mode_env["MY_OPENCODE_GATEWAY_FORCE_BUN_AVAILABLE"] = "1"
        autopilot_command_status_forced_plugin_mode = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "status",
                "--confidence",
                "0.9",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=forced_plugin_mode_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_status_forced_plugin_mode.returncode == 0,
            "autopilot status should run in forced plugin-mode diagnostics environment",
        )
        autopilot_command_status_forced_plugin_mode_report = parse_json_output(
            autopilot_command_status_forced_plugin_mode.stdout
        )
        forced_reason = autopilot_command_status_forced_plugin_mode_report.get(
            "gateway_loop_state_reason_code"
        )
        expect(
            autopilot_command_status_forced_plugin_mode_report.get(
                "gateway_runtime_mode"
            )
            in {"plugin_gateway", "python_command_bridge"}
            and forced_reason
            in {
                "bridge_state_ignored_in_plugin_mode",
                "loop_state_available",
                "state_missing",
            },
            "autopilot status should expose deterministic loop-state selection in plugin mode",
        )
        if forced_reason == "bridge_state_ignored_in_plugin_mode":
            expect(
                autopilot_command_status_forced_plugin_mode_report.get(
                    "gateway_loop_state"
                )
                is None,
                "autopilot status should hide bridge loop state when plugin mode is active",
            )

        forced_bridge_mode_env = dict(refactor_env)
        forced_bridge_mode_env["MY_OPENCODE_GATEWAY_FORCE_BUN_AVAILABLE"] = "0"
        autopilot_command_status_forced_bridge_mode = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "status",
                "--confidence",
                "0.9",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=forced_bridge_mode_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_status_forced_bridge_mode.returncode == 0,
            "autopilot status should run in forced bridge-mode diagnostics environment",
        )
        autopilot_command_status_forced_bridge_mode_report = parse_json_output(
            autopilot_command_status_forced_bridge_mode.stdout
        )
        expect(
            autopilot_command_status_forced_bridge_mode_report.get(
                "gateway_runtime_mode"
            )
            == "python_command_bridge"
            and autopilot_command_status_forced_bridge_mode_report.get(
                "gateway_runtime_reason_code"
            )
            in {
                "gateway_plugin_runtime_unavailable",
                "gateway_plugin_disabled",
                "gateway_plugin_not_ready",
            },
            "autopilot status should expose deterministic bridge fallback diagnostics when bun is unavailable",
        )

        infer_repo = tmp / "autopilot_infer_repo"
        infer_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "-b", "main"],
            capture_output=True,
            text=True,
            check=False,
            cwd=infer_repo,
        )
        (infer_repo / "src").mkdir(parents=True, exist_ok=True)
        (infer_repo / "src" / "feature.txt").write_text(
            "tracked change\n", encoding="utf-8"
        )
        (infer_repo / "node_modules" / "pkg").mkdir(parents=True, exist_ok=True)
        (infer_repo / "node_modules" / "pkg" / "index.js").write_text(
            "module.exports = {}\n", encoding="utf-8"
        )
        autopilot_command_go_infer = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "go",
                "--goal",
                "validate inferred path filtering",
                "--scope",
                "**",
                "--max-cycles",
                "1",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=infer_repo,
        )
        expect(
            autopilot_command_go_infer.returncode == 0,
            "autopilot go should run with inferred touched paths in git workspace",
        )
        autopilot_command_go_infer_report = parse_json_output(
            autopilot_command_go_infer.stdout
        )
        inferred_paths_any = autopilot_command_go_infer_report.get(
            "inferred_touched_paths", []
        )
        inferred_paths = (
            inferred_paths_any if isinstance(inferred_paths_any, list) else []
        )
        expect(
            "src/feature.txt" in inferred_paths,
            "autopilot inferred touched paths should include regular workspace files",
        )
        expect(
            not any("node_modules/" in str(path) for path in inferred_paths),
            "autopilot inferred touched paths should exclude node_modules files",
        )

        autopilot_command_go_placeholder_goal = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "go",
                "--goal",
                "${ARGUMENTS:-continue}",
                "--max-cycles",
                "1",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=infer_repo,
        )
        expect(
            autopilot_command_go_placeholder_goal.returncode == 0,
            "autopilot go should tolerate template placeholder goal literals",
        )
        autopilot_command_go_placeholder_goal_report = parse_json_output(
            autopilot_command_go_placeholder_goal.stdout
        )
        placeholder_run_any = autopilot_command_go_placeholder_goal_report.get("run")
        placeholder_run = (
            placeholder_run_any if isinstance(placeholder_run_any, dict) else {}
        )
        placeholder_objective_any = placeholder_run.get("objective")
        placeholder_objective = (
            placeholder_objective_any
            if isinstance(placeholder_objective_any, dict)
            else {}
        )
        expect(
            str(placeholder_objective.get("goal") or "")
            == "continue the active user request from current session context until done",
            "autopilot go should normalize placeholder goal literals into inferred default goal",
        )

        autopilot_command_go_missing_goal_value = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "go",
                "--goal",
                "--completion-mode",
                "promise",
                "--max-cycles",
                "1",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=infer_repo,
        )
        expect(
            autopilot_command_go_missing_goal_value.returncode == 0,
            "autopilot go should treat missing --goal value as inferred default",
        )

        autopilot_command_pause = subprocess.run(
            [sys.executable, str(AUTOPILOT_COMMAND_SCRIPT), "pause", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_pause.returncode == 0, "autopilot pause should succeed"
        )
        autopilot_command_pause_report = parse_json_output(
            autopilot_command_pause.stdout
        )
        expect(
            autopilot_command_pause_report.get("status") == "paused",
            "autopilot pause should persist paused status",
        )

        autopilot_command_status_after_pause = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "status",
                "--confidence",
                "0.9",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_status_after_pause.returncode == 0,
            "autopilot status should succeed after pause",
        )
        autopilot_command_status_after_pause_report = parse_json_output(
            autopilot_command_status_after_pause.stdout
        )
        expect(
            autopilot_command_status_after_pause_report.get("run", {}).get("status")
            == "paused",
            "autopilot status should retain paused state after pause transition",
        )

        autopilot_command_resume = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "resume",
                "--confidence",
                "0.9",
                "--tool-calls",
                "1",
                "--token-estimate",
                "50",
                "--touched-paths",
                "scripts/autopilot_command.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_resume.returncode == 0,
            "autopilot resume should execute the next bounded cycle",
        )
        autopilot_command_resume_report = parse_json_output(
            autopilot_command_resume.stdout
        )
        expect(
            autopilot_command_resume_report.get("result") == "PASS"
            and autopilot_command_resume_report.get("run", {})
            .get("progress", {})
            .get("completed_cycles", 0)
            >= 1,
            "autopilot resume should increment cycle progress after resume",
        )

        autopilot_command_start_budget = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "start",
                "--goal",
                "Exercise budget hard stop",
                "--scope",
                "scripts/autopilot_command.py",
                "--done-criteria",
                "force budget threshold",
                "--max-budget",
                "conservative",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_start_budget.returncode == 0,
            "autopilot start should initialize budget-stop verification run",
        )

        autopilot_command_pause_budget = subprocess.run(
            [sys.executable, str(AUTOPILOT_COMMAND_SCRIPT), "pause", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_pause_budget.returncode == 0,
            "autopilot pause should prepare resume budget-stop verification run",
        )

        autopilot_command_resume_budget_stop = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "resume",
                "--confidence",
                "0.9",
                "--tool-calls",
                "999",
                "--token-estimate",
                "999999",
                "--touched-paths",
                "scripts/autopilot_command.py",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_resume_budget_stop.returncode == 1,
            "autopilot resume should fail when budget hard-stop thresholds are exceeded",
        )
        autopilot_command_resume_budget_stop_report = parse_json_output(
            autopilot_command_resume_budget_stop.stdout
        )
        expect(
            autopilot_command_resume_budget_stop_report.get("run", {}).get("status")
            == "budget_stopped"
            and str(
                autopilot_command_resume_budget_stop_report.get("run", {}).get(
                    "reason_code", ""
                )
            ).startswith("budget_"),
            "autopilot resume budget stop should expose deterministic budget reason codes",
        )

        autopilot_command_report = subprocess.run(
            [sys.executable, str(AUTOPILOT_COMMAND_SCRIPT), "report", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_report.returncode == 0,
            "autopilot report should summarize run progress",
        )
        autopilot_command_report_payload = parse_json_output(
            autopilot_command_report.stdout
        )
        expect(
            autopilot_command_report_payload.get("result") == "PASS"
            and isinstance(autopilot_command_report_payload.get("summary", {}), dict),
            "autopilot report should include summary payload",
        )
        expect(
            autopilot_command_report_payload.get("gateway_runtime_mode")
            in {"plugin_gateway", "python_command_bridge"},
            "autopilot report should include gateway runtime mode telemetry",
        )

        autopilot_command_stop = subprocess.run(
            [
                sys.executable,
                str(AUTOPILOT_COMMAND_SCRIPT),
                "stop",
                "--reason",
                "selftest",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(autopilot_command_stop.returncode == 0, "autopilot stop should succeed")
        autopilot_command_stop_report = parse_json_output(autopilot_command_stop.stdout)
        expect(
            autopilot_command_stop_report.get("status") == "stopped"
            and autopilot_command_stop_report.get("reason_code")
            == "autopilot_stop_requested",
            "autopilot stop should persist deterministic stop state",
        )

        autopilot_command_status_after_stop = subprocess.run(
            [sys.executable, str(AUTOPILOT_COMMAND_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_status_after_stop.returncode == 0,
            "autopilot status should succeed after stop",
        )
        autopilot_command_status_after_stop_report = parse_json_output(
            autopilot_command_status_after_stop.stdout
        )
        expect(
            autopilot_command_status_after_stop_report.get("run", {}).get("status")
            == "stopped",
            "autopilot status should retain stopped state after stop transition",
        )

        autopilot_command_resume_after_stop = subprocess.run(
            [sys.executable, str(AUTOPILOT_COMMAND_SCRIPT), "resume", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_resume_after_stop.returncode == 1,
            "autopilot resume should fail when current state is stopped",
        )
        autopilot_command_resume_after_stop_report = parse_json_output(
            autopilot_command_resume_after_stop.stdout
        )
        expect(
            autopilot_command_resume_after_stop_report.get("reason_code")
            == "invalid_state_transition",
            "autopilot resume after stop should expose invalid_state_transition reason code",
        )

        autopilot_command_status_after_resume_attempt = subprocess.run(
            [sys.executable, str(AUTOPILOT_COMMAND_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            autopilot_command_status_after_resume_attempt.returncode == 0,
            "autopilot status should succeed after invalid resume attempt",
        )
        autopilot_command_status_after_resume_attempt_report = parse_json_output(
            autopilot_command_status_after_resume_attempt.stdout
        )
        expect(
            autopilot_command_status_after_resume_attempt_report.get("run", {}).get(
                "status"
            )
            == "stopped",
            "autopilot status should remain stopped after invalid resume attempt",
        )

        forced_budget_config = load_json_file(config_path)
        forced_budget_config["budget_runtime"] = {
            "profile": "conservative",
            "overrides": {
                "wall_clock_seconds": 2,
                "tool_call_count": 2,
                "token_estimate": 10,
            },
        }
        config_path.write_text(
            json.dumps(forced_budget_config, indent=2) + "\n", encoding="utf-8"
        )
        start_work_budget_stop = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), str(plan_path), "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            start_work_budget_stop.returncode == 1,
            "start-work should fail when budget hard thresholds are exceeded",
        )
        start_work_budget_stop_report = parse_json_output(start_work_budget_stop.stdout)
        expect(
            start_work_budget_stop_report.get("status") == "budget_stopped"
            and start_work_budget_stop_report.get("budget", {}).get("result") == "FAIL",
            "start-work should report budget_stopped with FAIL budget payload",
        )
        expect(
            str(
                start_work_budget_stop_report.get("budget", {}).get("reason_code", "")
            ).startswith("budget_"),
            "start-work budget stop should expose deterministic budget reason codes",
        )

        restored_config = load_json_file(config_path)
        restored_config.pop("budget_runtime", None)
        config_path.write_text(
            json.dumps(restored_config, indent=2) + "\n", encoding="utf-8"
        )
        start_work_reset = subprocess.run(
            [
                sys.executable,
                str(START_WORK_SCRIPT),
                str(plan_path),
                "--deviation",
                "manual verification note",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            start_work_reset.returncode == 0,
            "start-work should recover to completed status after clearing forced budget override",
        )

        start_work_status = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(start_work_status.returncode == 0, "start-work status should succeed")
        start_work_status_report = parse_json_output(start_work_status.stdout)
        expect(
            start_work_status_report.get("status") == "completed",
            "start-work status should persist latest run status",
        )

        budget_status = subprocess.run(
            [sys.executable, str(BUDGET_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(budget_status.returncode == 0, "budget status should succeed")
        budget_status_report = parse_json_output(budget_status.stdout)
        expect(
            budget_status_report.get("profile")
            in {"conservative", "balanced", "extended"}
            and isinstance(budget_status_report.get("limits"), dict),
            "budget status should report active profile and limits",
        )

        budget_profile_set = subprocess.run(
            [sys.executable, str(BUDGET_SCRIPT), "profile", "conservative"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            budget_profile_set.returncode == 0,
            "budget profile should update successfully",
        )

        budget_override_set = subprocess.run(
            [
                sys.executable,
                str(BUDGET_SCRIPT),
                "override",
                "--tool-call-count",
                "120",
                "--token-estimate",
                "120000",
                "--reason",
                "selftest",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            budget_override_set.returncode == 0,
            "budget override should accept deterministic positive values",
        )
        budget_override_report = parse_json_output(budget_override_set.stdout)
        expect(
            budget_override_report.get("overrides", {}).get("tool_call_count") == 120
            and budget_override_report.get("override_reason") == "selftest",
            "budget override should persist explicit limits and reason",
        )

        budget_override_invalid = subprocess.run(
            [
                sys.executable,
                str(BUDGET_SCRIPT),
                "override",
                "--tool-call-count",
                "0",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            budget_override_invalid.returncode == 2,
            "budget override should reject non-positive numeric values",
        )
        expect(
            "usage: /budget" in budget_override_invalid.stdout,
            "budget override invalid path should emit usage guidance",
        )

        budget_doctor = subprocess.run(
            [sys.executable, str(BUDGET_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(budget_doctor.returncode == 0, "budget doctor should succeed")
        budget_doctor_report = parse_json_output(budget_doctor.stdout)
        expect(
            budget_doctor_report.get("result") == "PASS",
            "budget doctor should report PASS for valid profile and overrides",
        )

        budget_override_clear = subprocess.run(
            [sys.executable, str(BUDGET_SCRIPT), "override", "--clear", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            budget_override_clear.returncode == 0,
            "budget override clear should remove temporary limits",
        )

        budget_profile_reset = subprocess.run(
            [sys.executable, str(BUDGET_SCRIPT), "profile", "balanced"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            budget_profile_reset.returncode == 0,
            "budget profile should reset to balanced for remaining checks",
        )

        runtime_config_path = Path(str(start_work_report.get("config") or ""))
        runtime_cfg = load_plan_runtime(runtime_config_path)
        runtime_cfg["status"] = "failed"
        runtime_cfg["steps"] = [
            {"ordinal": 1, "state": "done", "idempotent": True},
            {"ordinal": 2, "state": "pending", "idempotent": False},
        ]
        runtime_cfg["resume"] = {
            "enabled": True,
            "attempt_count": 0,
            "max_attempts": 3,
            "trail": [],
        }
        save_plan_runtime(runtime_config_path, runtime_cfg)

        resume_after_seed = subprocess.run(
            [
                sys.executable,
                str(RESUME_SCRIPT),
                "now",
                "--interruption-class",
                "tool_failure",
                "--approve-step",
                "2",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            resume_after_seed.returncode == 0,
            "resume now should complete seeded non-idempotent checkpoint when explicitly approved",
        )

        todo_status = subprocess.run(
            [sys.executable, str(TODO_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(todo_status.returncode == 0, "todo status should succeed")
        todo_status_report = parse_json_output(todo_status.stdout)
        expect(
            todo_status_report.get("result") == "PASS",
            "todo status should pass after compliant start-work run",
        )

        todo_enforce = subprocess.run(
            [sys.executable, str(TODO_SCRIPT), "enforce", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(todo_enforce.returncode == 0, "todo enforce should pass")
        todo_enforce_report = parse_json_output(todo_enforce.stdout)
        expect(
            todo_enforce_report.get("result") == "PASS",
            "todo enforce should report PASS for complete todo set",
        )

        start_work_deviations = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), "deviations", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            start_work_deviations.returncode == 0,
            "start-work deviations should succeed",
        )
        start_work_deviation_report = parse_json_output(start_work_deviations.stdout)
        expect(
            start_work_deviation_report.get("count", 0) >= 2,
            "start-work deviations should return captured deviation entries",
        )

        start_work_background = subprocess.run(
            [
                sys.executable,
                str(START_WORK_SCRIPT),
                str(plan_path),
                "--background",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            start_work_background.returncode == 0,
            "start-work should enqueue background-safe execution",
        )
        start_work_background_report = parse_json_output(start_work_background.stdout)
        expect(
            start_work_background_report.get("status") == "queued"
            and bool(start_work_background_report.get("job_id")),
            "start-work background mode should return queued job id",
        )
        queued_job_id = str(start_work_background_report.get("job_id"))

        bg_run_plan = subprocess.run(
            [
                sys.executable,
                str(BG_MANAGER_SCRIPT),
                "run",
                "--id",
                queued_job_id,
                "--max-jobs",
                "1",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            bg_run_plan.returncode == 0,
            "bg run should execute queued start-work job successfully",
        )

        digest_plan_path = home / ".config" / "opencode" / "digests" / "plan-run.json"
        digest_plan_env = refactor_env.copy()
        digest_plan_env["MY_OPENCODE_DIGEST_PATH"] = str(digest_plan_path)
        digest_after_plan = subprocess.run(
            [sys.executable, str(DIGEST_SCRIPT), "run", "--reason", "manual"],
            capture_output=True,
            text=True,
            env=digest_plan_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            digest_after_plan.returncode == 0,
            "digest run should succeed after start-work execution",
        )
        digest_after_plan_payload = load_json_file(digest_plan_path)
        plan_digest_block = digest_after_plan_payload.get("plan_execution", {})
        expect(
            isinstance(plan_digest_block, dict)
            and plan_digest_block.get("status") == "completed",
            "digest should include completed plan execution recap",
        )
        resume_hints_block = plan_digest_block.get("resume_hints", {})
        expect(
            isinstance(resume_hints_block, dict)
            and resume_hints_block.get("reason_code") == "resume_allowed",
            "digest plan execution recap should include resume hint diagnostics",
        )
        expect(
            plan_digest_block.get("plan_id") == "selftest-plan-001",
            "digest plan execution recap should include plan id",
        )

        invalid_plan_path = tmp / "invalid_plan_execution_selftest.md"
        invalid_plan_path.write_text(
            """---
id: invalid-plan-001
title: Invalid Plan
owner: selftest
created_at: 2026-02-13T00:00:00Z
version: 1
---

# Plan

- [ ] validate command wiring without ordinal
""",
            encoding="utf-8",
        )
        invalid_start_work = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), str(invalid_plan_path), "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            invalid_start_work.returncode == 1,
            "start-work should fail invalid plan artifacts",
        )
        invalid_start_work_report = parse_json_output(invalid_start_work.stdout)
        expect(
            invalid_start_work_report.get("code") == "validation_failed",
            "start-work should report validation_failed for invalid plan format",
        )

        malformed_frontmatter_plan = tmp / "invalid_frontmatter_plan.md"
        malformed_frontmatter_plan.write_text(
            """# Plan

- [ ] 1. Missing metadata should fail
""",
            encoding="utf-8",
        )
        malformed_start_work = subprocess.run(
            [
                sys.executable,
                str(START_WORK_SCRIPT),
                str(malformed_frontmatter_plan),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            malformed_start_work.returncode == 1,
            "start-work should fail when frontmatter is missing",
        )
        malformed_start_work_report = parse_json_output(malformed_start_work.stdout)
        expect(
            malformed_start_work_report.get("code") == "validation_failed",
            "start-work should return validation_failed for missing frontmatter",
        )

        out_of_order_plan = tmp / "invalid_out_of_order_plan.md"
        out_of_order_plan.write_text(
            """---
id: out-of-order-plan
title: Out Of Order Plan
owner: selftest
created_at: 2026-02-13T00:00:00Z
version: 1
---

# Plan

- [ ] 2. Second task appears first
- [ ] 1. First task appears second
""",
            encoding="utf-8",
        )
        out_of_order_start_work = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), str(out_of_order_plan), "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            out_of_order_start_work.returncode == 1,
            "start-work should fail out-of-order step ordinals",
        )
        out_of_order_report = parse_json_output(out_of_order_start_work.stdout)
        expect(
            any(
                violation.get("code") == "out_of_order_ordinals"
                for violation in out_of_order_report.get("violations", [])
                if isinstance(violation, dict)
            ),
            "start-work should surface out_of_order_ordinals violation",
        )

        runtime_config_path = Path(str(start_work_report.get("config") or ""))
        expect(
            runtime_config_path.exists(),
            "start-work should report writable config path",
        )
        runtime_cfg = load_plan_runtime(runtime_config_path)
        runtime_cfg["status"] = "in_progress"
        runtime_cfg["steps"] = [
            {"ordinal": 1, "state": "in_progress"},
            {"ordinal": 2, "state": "in_progress"},
        ]
        save_plan_runtime(runtime_config_path, runtime_cfg)

        start_work_doctor_fail = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            start_work_doctor_fail.returncode == 1,
            "start-work doctor should fail invalid in-progress step recovery state",
        )
        start_work_doctor_fail_report = parse_json_output(start_work_doctor_fail.stdout)
        expect(
            start_work_doctor_fail_report.get("result") == "FAIL",
            "start-work doctor should report FAIL for invalid recovery state",
        )

        todo_enforce_fail = subprocess.run(
            [sys.executable, str(TODO_SCRIPT), "enforce", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            todo_enforce_fail.returncode == 1,
            "todo enforce should fail for invalid runtime todo state",
        )
        todo_enforce_fail_report = parse_json_output(todo_enforce_fail.stdout)
        expect(
            any(
                violation.get("code")
                in ("multiple_in_progress_items", "incomplete_todo_set")
                for violation in todo_enforce_fail_report.get("violations", [])
                if isinstance(violation, dict)
            ),
            "todo enforce should surface compliance violations with deterministic codes",
        )

        start_work_recover = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), str(plan_path), "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            start_work_recover.returncode == 0,
            "start-work should recover by re-running valid plan after invalid runtime state",
        )

        resume_runtime = {
            "status": "failed",
            "steps": [
                {
                    "ordinal": 1,
                    "state": "done",
                    "idempotent": True,
                },
                {
                    "ordinal": 2,
                    "state": "pending",
                    "idempotent": False,
                },
            ],
            "resume": {
                "attempt_count": 0,
                "max_attempts": 3,
                "trail": [],
            },
        }
        resume_eval_blocked = evaluate_resume_eligibility(
            resume_runtime,
            "tool_failure",
        )
        expect(
            resume_eval_blocked.get("eligible") is False
            and resume_eval_blocked.get("reason_code") == "resume_non_idempotent_step",
            "recovery engine should block non-idempotent pending step without explicit approval",
        )

        for interruption_class in (
            "tool_failure",
            "timeout",
            "context_reset",
            "process_crash",
        ):
            class_runtime = {
                "status": "failed",
                "steps": [
                    {"ordinal": 1, "state": "done", "idempotent": True},
                    {"ordinal": 2, "state": "pending", "idempotent": True},
                ],
                "resume": {
                    "enabled": True,
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "last_attempt_at": "2026-02-13T00:00:00Z",
                    "trail": [],
                },
            }
            eval_allowed = evaluate_resume_eligibility(
                class_runtime, interruption_class
            )
            expect(
                eval_allowed.get("eligible") is True
                and eval_allowed.get("reason_code") == "resume_allowed",
                f"recovery engine should allow interruption class {interruption_class} when cooldown has elapsed",
            )

        eval_timeout_cooldown = evaluate_resume_eligibility(
            {
                "status": "failed",
                "steps": [
                    {"ordinal": 1, "state": "done", "idempotent": True},
                    {"ordinal": 2, "state": "pending", "idempotent": True},
                ],
                "resume": {
                    "enabled": True,
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "last_attempt_at": "2026-02-13T00:00:30Z",
                    "trail": [],
                },
            },
            "timeout",
            now_ts="2026-02-13T00:01:00Z",
        )
        expect(
            eval_timeout_cooldown.get("eligible") is False
            and eval_timeout_cooldown.get("reason_code") == "resume_blocked_cooldown",
            "recovery engine should enforce timeout interruption cooldown windows",
        )

        eval_disabled = evaluate_resume_eligibility(
            {
                "status": "failed",
                "steps": [
                    {"ordinal": 1, "state": "done", "idempotent": True},
                    {"ordinal": 2, "state": "pending", "idempotent": True},
                ],
                "resume": {
                    "enabled": False,
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "trail": [],
                },
            },
            "tool_failure",
        )
        expect(
            eval_disabled.get("eligible") is False
            and eval_disabled.get("reason_code") == "resume_disabled",
            "recovery engine should block resume when runtime controls disable automation",
        )

        resume_exec_allowed = execute_resume(
            resume_runtime,
            "tool_failure",
            approved_steps={2},
            actor="selftest",
        )
        expect(
            resume_exec_allowed.get("result") == "PASS"
            and resume_exec_allowed.get("runtime", {}).get("status") == "completed",
            "recovery engine should resume approved non-idempotent step and complete run",
        )

        recover_plan_path = tmp / "recovery_plan_selftest.md"
        recover_plan_path.write_text(
            """---
id: selftest-recovery-plan
title: Recovery Plan
owner: selftest
created_at: 2026-02-13T00:00:00Z
version: 1
---

# Plan

- [ ] 1. Stable resumable setup
- [ ] 2. [non-idempotent] Risky operation requiring explicit approval
""",
            encoding="utf-8",
        )
        recover_start = subprocess.run(
            [sys.executable, str(START_WORK_SCRIPT), str(recover_plan_path), "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            recover_start.returncode == 0, "start-work recover fixture should execute"
        )

        recover_config_path = Path(
            str(parse_json_output(recover_start.stdout).get("config"))
        )
        recover_state = load_plan_runtime(recover_config_path)
        if isinstance(recover_state, dict):
            recover_state["status"] = "failed"
            recover_steps = recover_state.get("steps")
            if isinstance(recover_steps, list) and len(recover_steps) >= 2:
                if isinstance(recover_steps[0], dict):
                    recover_steps[0]["state"] = "done"
                if isinstance(recover_steps[1], dict):
                    recover_steps[1]["state"] = "pending"
                    recover_steps[1]["idempotent"] = False
            recover_state["resume"] = {
                "attempt_count": 0,
                "max_attempts": 3,
                "trail": [],
            }
        save_plan_runtime(recover_config_path, recover_state)

        recover_blocked = subprocess.run(
            [
                sys.executable,
                str(START_WORK_SCRIPT),
                "recover",
                "--interruption-class",
                "tool_failure",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            recover_blocked.returncode == 1,
            "start-work recover should fail for non-idempotent pending step without approval",
        )
        recover_blocked_report = parse_json_output(recover_blocked.stdout)
        expect(
            recover_blocked_report.get("reason_code") == "resume_non_idempotent_step",
            "start-work recover should surface deterministic reason code",
        )
        expect(
            any(
                "--approve-step 2" in str(action)
                for action in (
                    recover_blocked_report.get("resume_hints", {}) or {}
                ).get("next_actions", [])
            ),
            "start-work recover should include resume hints for explicit approval replay",
        )
        expect(
            "requires explicit approval"
            in str(recover_blocked_report.get("reason", "")),
            "start-work recover should provide a human-readable reason",
        )

        recover_state_after_block = load_plan_runtime(recover_config_path)
        if isinstance(recover_state_after_block, dict):
            resume_meta = recover_state_after_block.get("resume")
            if isinstance(resume_meta, dict):
                resume_meta["last_attempt_at"] = "2026-02-13T00:00:00Z"
                resume_meta["attempt_count"] = 0
        save_plan_runtime(recover_config_path, recover_state_after_block)

        recover_allowed = subprocess.run(
            [
                sys.executable,
                str(START_WORK_SCRIPT),
                "recover",
                "--interruption-class",
                "tool_failure",
                "--approve-step",
                "2",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            recover_allowed.returncode == 0,
            "start-work recover should pass when explicit approval is provided",
        )
        recover_allowed_report = parse_json_output(recover_allowed.stdout)
        expect(
            recover_allowed_report.get("result") == "PASS"
            and recover_allowed_report.get("status") == "completed",
            "start-work recover should complete failed run when recovery eligibility is satisfied",
        )
        recover_persistence = recover_allowed_report.get("snapshot", {})
        expect(
            isinstance(recover_persistence, dict)
            and isinstance(recover_persistence.get("snapshot"), dict)
            and recover_persistence.get("snapshot", {}).get("result") == "PASS",
            "start-work recover should persist checkpoint snapshots via snapshot manager",
        )

        recover_runtime = load_plan_runtime(recover_config_path)
        if isinstance(recover_runtime, dict):
            listed_snapshots = list_snapshots(recover_config_path)
            expect(
                bool(listed_snapshots),
                "snapshot manager should list persisted snapshots for active run",
            )
            run_id = str(listed_snapshots[0].get("run_id") or "")
            latest_snapshot = show_snapshot(recover_config_path, run_id, "latest")
            expect(
                latest_snapshot.get("result") == "PASS"
                and isinstance(latest_snapshot.get("snapshot"), dict)
                and latest_snapshot.get("snapshot", {}).get("status")
                == recover_runtime.get("status"),
                "snapshot manager should load latest checkpoint snapshot with matching runtime status",
            )
            prune_report = prune_snapshots(
                recover_config_path,
                max_per_run=10,
                max_age_days=30,
                compress_after_hours=720,
            )
            expect(
                prune_report.get("result") == "PASS",
                "snapshot manager prune should complete successfully with bounded retention policy",
            )

        checkpoint_list = subprocess.run(
            [sys.executable, str(CHECKPOINT_SCRIPT), "list", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(checkpoint_list.returncode == 0, "checkpoint list should succeed")
        checkpoint_list_report = parse_json_output(checkpoint_list.stdout)
        expect(
            int(checkpoint_list_report.get("count", 0)) >= 1,
            "checkpoint list should report at least one snapshot after start-work execution",
        )

        checkpoint_show = subprocess.run(
            [
                sys.executable,
                str(CHECKPOINT_SCRIPT),
                "show",
                "--snapshot",
                "latest",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(checkpoint_show.returncode == 0, "checkpoint show should succeed")
        checkpoint_show_report = parse_json_output(checkpoint_show.stdout)
        expect(
            checkpoint_show_report.get("result") == "PASS"
            and isinstance(checkpoint_show_report.get("snapshot"), dict),
            "checkpoint show should return latest snapshot payload",
        )

        checkpoint_prune = subprocess.run(
            [
                sys.executable,
                str(CHECKPOINT_SCRIPT),
                "prune",
                "--max-per-run",
                "10",
                "--max-age-days",
                "30",
                "--compress-after-hours",
                "720",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(checkpoint_prune.returncode == 0, "checkpoint prune should succeed")
        checkpoint_prune_report = parse_json_output(checkpoint_prune.stdout)
        expect(
            checkpoint_prune_report.get("result") == "PASS",
            "checkpoint prune should return PASS for valid retention settings",
        )

        checkpoint_doctor = subprocess.run(
            [sys.executable, str(CHECKPOINT_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(checkpoint_doctor.returncode == 0, "checkpoint doctor should succeed")
        checkpoint_doctor_report = parse_json_output(checkpoint_doctor.stdout)
        expect(
            checkpoint_doctor_report.get("result") == "PASS",
            "checkpoint doctor should report PASS when snapshots are readable",
        )

        direct_write = write_snapshot(
            recover_config_path,
            {
                "plan": {
                    "path": str(recover_plan_path),
                    "metadata": {"id": "selftest-direct-write"},
                },
                "status": "failed",
                "steps": [
                    {"ordinal": 1, "state": "done", "idempotent": True},
                    {"ordinal": 2, "state": "pending", "idempotent": False},
                ],
                "todo_compliance": {"result": "PASS", "violations": []},
                "started_at": "2026-02-13T00:00:00Z",
            },
            source="error_boundary",
            command_outcomes=[
                {
                    "kind": "tool_use",
                    "name": "selftest",
                    "result": "FAIL",
                    "duration_ms": 1,
                    "reason_code": "selftest_error_boundary",
                    "summary": "direct checkpoint write fixture",
                }
            ],
        )
        expect(
            direct_write.get("result") == "PASS",
            "checkpoint manager should atomically persist direct snapshot writes",
        )
        direct_paths = direct_write.get("paths", {})
        expect(
            isinstance(direct_paths, dict)
            and Path(str(direct_paths.get("latest", ""))).exists()
            and Path(str(direct_paths.get("history", ""))).exists(),
            "checkpoint manager should create latest and history files for direct writes",
        )

        direct_snapshot = direct_write.get("snapshot", {})
        direct_run_id = str(direct_snapshot.get("run_id") or "")
        latest_path = Path(str(direct_paths.get("latest", "")))
        if latest_path.exists() and direct_run_id:
            latest_path.write_text("{", encoding="utf-8")
            corrupted_report = show_snapshot(
                recover_config_path, direct_run_id, "latest"
            )
            expect(
                corrupted_report.get("result") == "FAIL"
                and corrupted_report.get("reason_code") == "checkpoint_schema_invalid",
                "checkpoint manager should fail deterministically on corrupted snapshot payloads",
            )

            latest_path.write_text(
                json.dumps(direct_snapshot, indent=2) + "\n",
                encoding="utf-8",
            )
            tampered_latest = dict(direct_snapshot)
            tampered_latest["status"] = "completed"
            latest_path.write_text(
                json.dumps(tampered_latest, indent=2) + "\n",
                encoding="utf-8",
            )
            mismatch_report = show_snapshot(
                recover_config_path, direct_run_id, "latest"
            )
            expect(
                mismatch_report.get("result") == "FAIL"
                and mismatch_report.get("reason_code")
                == "checkpoint_integrity_mismatch",
                "checkpoint manager should detect integrity mismatches for tampered snapshots",
            )

        retention_run = "selftest-retention"
        retention_history = (
            recover_config_path.parent / "checkpoints" / retention_run / "history"
        )
        retention_history.mkdir(parents=True, exist_ok=True)
        for idx in range(3):
            payload = {
                "snapshot_id": f"cp_retention_{idx}",
                "created_at": f"2026-02-13T00:00:0{idx}Z",
                "run_id": retention_run,
                "status": "in_progress",
            }
            (retention_history / f"cp_retention_{idx}.json").write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
        retention_prune = prune_snapshots(
            recover_config_path,
            max_per_run=1,
            max_age_days=36500,
            compress_after_hours=100000,
        )
        expect(
            retention_prune.get("result") == "PASS"
            and int(retention_prune.get("removed", 0)) >= 2,
            "checkpoint retention prune should enforce bounded history per run",
        )

        compression_run = "selftest-compression"
        compression_history = (
            recover_config_path.parent / "checkpoints" / compression_run / "history"
        )
        compression_history.mkdir(parents=True, exist_ok=True)
        compression_json = compression_history / "cp_compress_0.json"
        compression_json.write_text(
            json.dumps(
                {
                    "snapshot_id": "cp_compress_0",
                    "created_at": "2020-01-01T00:00:00Z",
                    "run_id": compression_run,
                    "status": "failed",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        compression_prune = prune_snapshots(
            recover_config_path,
            max_per_run=50,
            max_age_days=36500,
            compress_after_hours=0,
        )
        expect(
            compression_prune.get("result") == "PASS"
            and int(compression_prune.get("compressed", 0)) >= 1
            and (compression_history / "cp_compress_0.json.gz").exists(),
            "checkpoint prune should rotate old snapshots into compressed history artifacts",
        )

        recover_state_after_allowed = load_plan_runtime(recover_config_path)
        if isinstance(recover_state_after_allowed, dict):
            resume_meta = recover_state_after_allowed.get("resume")
            if isinstance(resume_meta, dict):
                resume_meta["last_attempt_at"] = "2026-02-13T00:00:00Z"
        save_plan_runtime(recover_config_path, recover_state_after_allowed)

        resume_status_ok = subprocess.run(
            [sys.executable, str(RESUME_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            resume_status_ok.returncode == 0,
            "resume status should pass when runtime recovery is eligible",
        )
        resume_status_ok_report = parse_json_output(resume_status_ok.stdout)
        expect(
            resume_status_ok_report.get("reason_code") == "resume_allowed",
            "resume status should report resume_allowed when checkpoint is resumable",
        )
        expect(
            any(
                "resume now" in str(action) or "autopilot status" in str(action)
                for action in (
                    resume_status_ok_report.get("resume_hints", {}) or {}
                ).get("next_actions", [])
            ),
            "resume status should expose actionable resume hints when eligible",
        )

        resume_disable = subprocess.run(
            [sys.executable, str(RESUME_SCRIPT), "disable", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(resume_disable.returncode == 0, "resume disable should succeed")

        resume_status_disabled = subprocess.run(
            [sys.executable, str(RESUME_SCRIPT), "status", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            resume_status_disabled.returncode == 0,
            "resume status should return diagnostics even when resume is disabled",
        )
        resume_status_disabled_report = parse_json_output(resume_status_disabled.stdout)
        expect(
            resume_status_disabled_report.get("reason_code") == "resume_disabled",
            "resume status should expose resume_disabled reason code",
        )
        expect(
            any(
                "plan_execution.resume.enabled" in str(action)
                for action in (
                    resume_status_disabled_report.get("resume_hints", {}) or {}
                ).get("next_actions", [])
            ),
            "resume status should expose enablement playbook when automation is disabled",
        )

        resume_now_disabled = subprocess.run(
            [
                sys.executable,
                str(RESUME_SCRIPT),
                "now",
                "--interruption-class",
                "tool_failure",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            resume_now_disabled.returncode == 1,
            "resume now should fail while resume automation is disabled",
        )
        resume_now_disabled_report = parse_json_output(resume_now_disabled.stdout)
        expect(
            resume_now_disabled_report.get("reason_code") == "resume_disabled",
            "resume now should surface resume_disabled reason code",
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

        auto_slash_detect = detect_intent(
            "can you run doctor diagnostics on this setup?",
            enabled=True,
            enabled_commands={"doctor", "stack", "nvim", "devtools"},
            min_confidence=0.75,
            ambiguity_delta=0.15,
        )
        expect(
            (auto_slash_detect.get("selected") or {}).get("command") == "doctor",
            "auto-slash schema should map clear diagnostic intent to doctor",
        )
        expect(
            (auto_slash_detect.get("selected") or {}).get("slash_command") == "/doctor",
            "auto-slash schema should render doctor slash command without duplicate run subcommand",
        )

        auto_slash_dataset = [
            {"prompt": "run doctor diagnostics", "expected": "doctor"},
            {"prompt": "switch to focus mode", "expected": "stack"},
            {
                "prompt": "install nvim integration minimal and link init",
                "expected": "nvim",
            },
            {"prompt": "install devtools and setup hooks", "expected": "devtools"},
            {"prompt": "write release notes", "expected": None},
        ]
        auto_slash_precision = evaluate_precision(
            auto_slash_dataset,
            enabled=True,
            enabled_commands={"doctor", "stack", "nvim", "devtools"},
            min_confidence=0.75,
            ambiguity_delta=0.15,
        )
        expect(
            auto_slash_precision.get("precision", 0.0) >= 0.95,
            "auto-slash schema precision should remain above target threshold",
        )
        expect(
            auto_slash_precision.get("unsafe_predictions") == 0,
            "auto-slash schema should avoid unsafe predictions on no-command prompts",
        )

        auto_slash_preview = subprocess.run(
            [
                sys.executable,
                str(AUTO_SLASH_SCRIPT),
                "preview",
                "--prompt",
                "run doctor diagnostics in json",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(auto_slash_preview.returncode == 0, "auto-slash preview should succeed")
        auto_slash_preview_report = parse_json_output(auto_slash_preview.stdout)
        expect(
            (auto_slash_preview_report.get("selected") or {}).get("command")
            == "doctor",
            "auto-slash preview should choose doctor for diagnostics prompt",
        )

        auto_slash_execute_preview = subprocess.run(
            [
                sys.executable,
                str(AUTO_SLASH_SCRIPT),
                "execute",
                "--prompt",
                "run doctor diagnostics",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            auto_slash_execute_preview.returncode == 0,
            "auto-slash execute preview should succeed without force",
        )
        auto_slash_execute_preview_report = parse_json_output(
            auto_slash_execute_preview.stdout
        )
        expect(
            auto_slash_execute_preview_report.get("result") == "PREVIEW_ONLY",
            "auto-slash execute should require force in preview-first mode",
        )

        auto_slash_execute_forced = subprocess.run(
            [
                sys.executable,
                str(AUTO_SLASH_SCRIPT),
                "execute",
                "--prompt",
                "run doctor diagnostics",
                "--force",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(
            auto_slash_execute_forced.returncode == 0,
            "auto-slash execute with force should succeed",
        )
        auto_slash_execute_forced_report = parse_json_output(
            auto_slash_execute_forced.stdout
        )
        expect(
            auto_slash_execute_forced_report.get("executed") is True
            and auto_slash_execute_forced_report.get("command_returncode") == 0,
            "auto-slash forced execution should dispatch successfully",
        )

        auto_slash_audit = subprocess.run(
            [sys.executable, str(AUTO_SLASH_SCRIPT), "audit", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(auto_slash_audit.returncode == 0, "auto-slash audit should succeed")
        auto_slash_audit_report = parse_json_output(auto_slash_audit.stdout)
        expect(
            len(auto_slash_audit_report.get("entries", [])) >= 1,
            "auto-slash audit should record forced executions",
        )

        auto_slash_doctor = subprocess.run(
            [sys.executable, str(AUTO_SLASH_SCRIPT), "doctor", "--json"],
            capture_output=True,
            text=True,
            env=refactor_env,
            check=False,
            cwd=REPO_ROOT,
        )
        expect(auto_slash_doctor.returncode == 0, "auto-slash doctor should succeed")
        auto_slash_doctor_report = parse_json_output(auto_slash_doctor.stdout)
        expect(
            auto_slash_doctor_report.get("result") == "PASS",
            "auto-slash doctor should report PASS",
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
                "--browser-profile",
                "playwright",
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
        expect(
            wizard_state.get("profiles", {}).get("browser") == "playwright",
            "wizard should persist selected browser profile",
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

        auto_slash_checks = [
            check
            for check in report.get("checks", [])
            if check.get("name") == "auto-slash"
        ]
        expect(
            bool(auto_slash_checks),
            "doctor summary should include auto-slash check",
        )
        expect(
            auto_slash_checks[0].get("ok") is True,
            "doctor auto-slash check should pass",
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

        browser_checks = [
            check
            for check in report.get("checks", [])
            if check.get("name") == "browser"
        ]
        expect(bool(browser_checks), "doctor summary should include browser check")
        expect(
            browser_checks[0].get("ok") is True,
            "doctor browser check should pass",
        )

        budget_checks = [
            check for check in report.get("checks", []) if check.get("name") == "budget"
        ]
        expect(bool(budget_checks), "doctor summary should include budget check")
        expect(
            budget_checks[0].get("ok") is True,
            "doctor budget check should pass",
        )

        todo_checks = [
            check for check in report.get("checks", []) if check.get("name") == "todo"
        ]
        expect(bool(todo_checks), "doctor summary should include todo check")
        expect(todo_checks[0].get("ok") is True, "doctor todo check should pass")

        safe_edit_checks = [
            check
            for check in report.get("checks", [])
            if check.get("name") == "safe-edit"
        ]
        expect(
            bool(safe_edit_checks),
            "doctor summary should include safe-edit check",
        )
        expect(
            safe_edit_checks[0].get("ok") is True,
            "doctor safe-edit check should pass",
        )

        lsp_checks = [
            check for check in report.get("checks", []) if check.get("name") == "lsp"
        ]
        expect(bool(lsp_checks), "doctor summary should include lsp check")
        expect(
            lsp_checks[0].get("ok") is True,
            "doctor lsp check should pass",
        )

    print("selftest: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"selftest: FAIL - {exc}")
        raise SystemExit(1)
