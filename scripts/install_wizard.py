#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_INSTALL_STATE_PATH",
        "~/.config/opencode/my_opencode-install-state.json",
    )
).expanduser()

OPENCODE_NVIM_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_NVIM_PATH",
        "~/.local/share/nvim/site/pack/opencode/start/opencode.nvim",
    )
).expanduser()
OPENCODE_NVIM_REPO = os.environ.get(
    "MY_OPENCODE_NVIM_REPO", "https://github.com/nickjvandyke/opencode.nvim"
)
OPENCHAMBER_PACKAGE = os.environ.get(
    "MY_OPENCODE_OPENCHAMBER_PACKAGE", "@openchamber/web"
)

PLUGIN_ALIASES = ["notifier", "morph", "worktree"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_step(
    args: list[str], *, env: dict | None = None, cwd: Path | None = None
) -> int:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=env or os.environ.copy(),
        cwd=str(cwd or REPO_ROOT),
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def run_repo_script(name: str, *args: str) -> int:
    return run_step([sys.executable, str(REPO_ROOT / "scripts" / name), *args])


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"managed": {}, "profiles": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(data: dict) -> None:
    payload = {
        "updated_at": now_iso(),
        "profiles": data.get("profiles", {}),
        "managed": data.get("managed", {}),
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def choose(
    question: str, options: list[str], default: str, non_interactive: bool
) -> str:
    if non_interactive:
        print(f"{question}: {default} (non-interactive)")
        return default

    print(f"\n{question}")
    for i, item in enumerate(options, start=1):
        marker = " (default)" if item == default else ""
        print(f"  {i}) {item}{marker}")

    while True:
        reply = input("Select option number (Enter for default): ").strip()
        if not reply:
            return default
        if reply.isdigit() and 1 <= int(reply) <= len(options):
            return options[int(reply) - 1]
        print("Invalid selection. Try again.")


def ask_yes_no(question: str, default: bool, non_interactive: bool) -> bool:
    if non_interactive:
        value = "yes" if default else "no"
        print(f"{question}: {value} (non-interactive)")
        return default

    suffix = "Y/n" if default else "y/N"
    while True:
        reply = input(f"{question} [{suffix}]: ").strip().lower()
        if not reply:
            return default
        if reply in ("y", "yes"):
            return True
        if reply in ("n", "no"):
            return False
        print("Please answer yes or no.")


def apply_plugin_profile(profile: str, custom_aliases: list[str] | None = None) -> int:
    if profile != "custom":
        return run_repo_script("plugin_command.py", "profile", profile)

    selected = set(custom_aliases or [])
    code = run_repo_script("plugin_command.py", "profile", "lean")
    if code != 0:
        return code

    for alias in PLUGIN_ALIASES:
        action = "enable" if alias in selected else "disable"
        code = run_repo_script("plugin_command.py", action, alias)
        if code != 0:
            return code
    return 0


def install_opencode_nvim() -> int:
    OPENCODE_NVIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    if (OPENCODE_NVIM_PATH / ".git").exists():
        print(f"Updating opencode.nvim at {OPENCODE_NVIM_PATH}")
        return run_step(
            ["git", "-C", str(OPENCODE_NVIM_PATH), "pull", "--ff-only"], cwd=REPO_ROOT
        )
    if OPENCODE_NVIM_PATH.exists():
        print(f"error: {OPENCODE_NVIM_PATH} exists and is not a git checkout")
        return 1
    print(f"Installing opencode.nvim into {OPENCODE_NVIM_PATH}")
    return run_step(
        ["git", "clone", OPENCODE_NVIM_REPO, str(OPENCODE_NVIM_PATH)], cwd=REPO_ROOT
    )


def uninstall_opencode_nvim() -> int:
    if not OPENCODE_NVIM_PATH.exists():
        print("opencode.nvim is already absent")
        return 0
    shutil.rmtree(OPENCODE_NVIM_PATH)
    print(f"Removed {OPENCODE_NVIM_PATH}")
    return 0


def detect_pkg_manager() -> str | None:
    if shutil.which("npm"):
        return "npm"
    if shutil.which("bun"):
        return "bun"
    return None


def install_openchamber(manager: str) -> int:
    if manager == "npm":
        return run_step(["npm", "install", "-g", OPENCHAMBER_PACKAGE], cwd=REPO_ROOT)
    if manager == "bun":
        return run_step(["bun", "add", "-g", OPENCHAMBER_PACKAGE], cwd=REPO_ROOT)
    print("error: no supported package manager found for OpenChamber (npm or bun)")
    return 1


def uninstall_openchamber(manager: str) -> int:
    if manager == "npm":
        return run_step(["npm", "uninstall", "-g", OPENCHAMBER_PACKAGE], cwd=REPO_ROOT)
    if manager == "bun":
        return run_step(["bun", "remove", "-g", OPENCHAMBER_PACKAGE], cwd=REPO_ROOT)
    print("error: no supported package manager found for OpenChamber uninstall")
    return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive installer/reconfigure wizard for my_opencode"
    )
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--reconfigure", action="store_true")
    parser.add_argument("--skip-extras", action="store_true")
    parser.add_argument(
        "--plugin-profile",
        choices=["lean", "stable", "experimental", "custom"],
    )
    parser.add_argument(
        "--mcp-profile", choices=["minimal", "research", "context7", "ghgrep"]
    )
    parser.add_argument("--policy-profile", choices=["strict", "balanced", "fast"])
    parser.add_argument(
        "--notify-profile",
        choices=["skip", "all", "quiet", "focus", "sound-only", "visual-only"],
    )
    parser.add_argument("--telemetry-profile", choices=["off", "local", "errors-only"])
    parser.add_argument(
        "--post-session-profile",
        choices=["disabled", "manual-validate", "exit-selftest"],
    )
    parser.add_argument(
        "--model-profile", choices=["quick", "deep", "visual", "writing"]
    )
    parser.add_argument("--browser-profile", choices=["playwright", "agent-browser"])
    parser.add_argument("--opencode-nvim", choices=["install", "uninstall", "skip"])
    parser.add_argument("--openchamber", choices=["install", "uninstall", "skip"])
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.non_interactive and not sys.stdin.isatty():
        print(
            "error: wizard requires an interactive terminal (or pass --non-interactive)"
        )
        return 1

    state = load_state()
    prev_profiles = state.get("profiles", {})
    managed = state.get("managed", {})

    print("my_opencode install wizard")
    print("-------------------------")
    if args.reconfigure:
        print("mode: reconfigure existing setup")
    else:
        print("mode: fresh or guided setup")

    plugin_profile = args.plugin_profile or choose(
        "Plugin profile",
        ["lean", "stable", "experimental", "custom"],
        prev_profiles.get("plugin", "lean"),
        args.non_interactive,
    )
    custom_plugins: list[str] = []
    if plugin_profile == "custom":
        base_enabled = set(prev_profiles.get("custom_plugins", ["notifier"]))
        for alias in PLUGIN_ALIASES:
            selected = ask_yes_no(
                f"Enable plugin '{alias}'",
                alias in base_enabled,
                args.non_interactive,
            )
            if selected:
                custom_plugins.append(alias)

    mcp_profile = args.mcp_profile or choose(
        "MCP profile",
        ["minimal", "research", "context7", "ghgrep"],
        prev_profiles.get("mcp", "minimal"),
        args.non_interactive,
    )
    policy_profile = args.policy_profile or choose(
        "Permission/notification policy",
        ["strict", "balanced", "fast"],
        prev_profiles.get("policy", "balanced"),
        args.non_interactive,
    )
    notify_profile = args.notify_profile or choose(
        "Notify profile override (applied after policy)",
        ["skip", "all", "quiet", "focus", "sound-only", "visual-only"],
        prev_profiles.get("notify", "skip"),
        args.non_interactive,
    )
    telemetry_profile = args.telemetry_profile or choose(
        "Telemetry profile",
        ["off", "local", "errors-only"],
        prev_profiles.get("telemetry", "off"),
        args.non_interactive,
    )
    post_profile = args.post_session_profile or choose(
        "Post-session profile",
        ["disabled", "manual-validate", "exit-selftest"],
        prev_profiles.get("post_session", "disabled"),
        args.non_interactive,
    )
    model_profile = args.model_profile or choose(
        "Model routing profile",
        ["quick", "deep", "visual", "writing"],
        prev_profiles.get("model_routing", "quick"),
        args.non_interactive,
    )
    browser_profile = args.browser_profile or choose(
        "Browser automation provider",
        ["playwright", "agent-browser"],
        prev_profiles.get("browser", "playwright"),
        args.non_interactive,
    )

    if args.skip_extras:
        opencode_nvim_action = "skip"
        openchamber_action = "skip"
    else:
        opencode_nvim_action = args.opencode_nvim or choose(
            "opencode.nvim integration",
            ["install", "uninstall", "skip"],
            "install" if managed.get("opencode_nvim", {}).get("installed") else "skip",
            args.non_interactive,
        )
        openchamber_action = args.openchamber or choose(
            "OpenChamber integration",
            ["install", "uninstall", "skip"],
            "install" if managed.get("openchamber", {}).get("installed") else "skip",
            args.non_interactive,
        )

    print("\nApplying configuration...")
    failures: list[str] = []

    if apply_plugin_profile(plugin_profile, custom_aliases=custom_plugins) != 0:
        failures.append("plugin profile")
    if run_repo_script("mcp_command.py", "profile", mcp_profile) != 0:
        failures.append("mcp profile")
    if run_repo_script("policy_command.py", "profile", policy_profile) != 0:
        failures.append("policy profile")
    if notify_profile != "skip":
        if run_repo_script("notify_command.py", "profile", notify_profile) != 0:
            failures.append("notify profile")
    if run_repo_script("telemetry_command.py", "profile", telemetry_profile) != 0:
        failures.append("telemetry profile")
    if run_repo_script("model_routing_command.py", "set-category", model_profile) != 0:
        failures.append("model routing profile")
    if run_repo_script("browser_command.py", "profile", browser_profile) != 0:
        failures.append("browser profile")

    if post_profile == "disabled":
        if run_repo_script("post_session_command.py", "disable") != 0:
            failures.append("post-session disable")
    elif post_profile == "manual-validate":
        if run_repo_script("post_session_command.py", "enable") != 0:
            failures.append("post-session enable")
        if (
            run_repo_script(
                "post_session_command.py", "set", "command", "make validate"
            )
            != 0
        ):
            failures.append("post-session command")
        if run_repo_script("post_session_command.py", "set", "run-on", "manual") != 0:
            failures.append("post-session run-on")
    elif post_profile == "exit-selftest":
        if run_repo_script("post_session_command.py", "enable") != 0:
            failures.append("post-session enable")
        if (
            run_repo_script(
                "post_session_command.py", "set", "command", "make selftest"
            )
            != 0
        ):
            failures.append("post-session command")
        if (
            run_repo_script(
                "post_session_command.py",
                "set",
                "run-on",
                "exit,manual",
            )
            != 0
        ):
            failures.append("post-session run-on")

    if not args.skip_extras:
        if opencode_nvim_action == "install":
            if install_opencode_nvim() == 0:
                if (
                    run_repo_script("nvim_integration_command.py", "install", "minimal")
                    != 0
                ):
                    failures.append("opencode.nvim integration profile")
                managed["opencode_nvim"] = {
                    "installed": True,
                    "path": str(OPENCODE_NVIM_PATH),
                    "repo": OPENCODE_NVIM_REPO,
                }
            else:
                failures.append("opencode.nvim install")
        elif opencode_nvim_action == "uninstall":
            if managed.get("opencode_nvim", {}).get("installed"):
                if run_repo_script("nvim_integration_command.py", "uninstall") != 0:
                    failures.append("opencode.nvim integration uninstall")
                if uninstall_opencode_nvim() == 0:
                    managed["opencode_nvim"] = {
                        "installed": False,
                        "path": str(OPENCODE_NVIM_PATH),
                    }
                else:
                    failures.append("opencode.nvim uninstall")
            else:
                print("Skipping opencode.nvim uninstall (not wizard-managed)")

        manager = detect_pkg_manager()
        if openchamber_action == "install":
            if install_openchamber(manager or "") == 0:
                managed["openchamber"] = {
                    "installed": True,
                    "package": OPENCHAMBER_PACKAGE,
                    "manager": manager,
                }
            else:
                failures.append("OpenChamber install")
        elif openchamber_action == "uninstall":
            if managed.get("openchamber", {}).get("installed"):
                chosen_manager = (
                    managed.get("openchamber", {}).get("manager") or manager or ""
                )
                if uninstall_openchamber(chosen_manager) == 0:
                    managed["openchamber"] = {
                        "installed": False,
                        "package": OPENCHAMBER_PACKAGE,
                        "manager": chosen_manager,
                    }
                else:
                    failures.append("OpenChamber uninstall")
            else:
                print("Skipping OpenChamber uninstall (not wizard-managed)")

    state["profiles"] = {
        "plugin": plugin_profile,
        "custom_plugins": custom_plugins,
        "mcp": mcp_profile,
        "policy": policy_profile,
        "notify": notify_profile,
        "telemetry": telemetry_profile,
        "post_session": post_profile,
        "model_routing": model_profile,
        "browser": browser_profile,
        "opencode_nvim": opencode_nvim_action,
        "openchamber": openchamber_action,
    }
    state["managed"] = managed
    save_state(state)

    print(f"\nState saved: {STATE_PATH}")
    if failures:
        print("Wizard completed with issues:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("Wizard completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
