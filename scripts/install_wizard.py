#!/usr/bin/env python3

import argparse
import copy
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
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

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_owned_by_current_user(state: os.stat_result, label: str) -> None:
    if hasattr(os, "getuid") and state.st_uid != os.getuid():
        raise OSError(f"{label} is not owned by the current user")


def preflight_state_path(path: Path | None = None) -> os.stat_result | None:
    target = path or STATE_PATH
    parent = target.parent
    try:
        parent_state = parent.lstat()
    except FileNotFoundError:
        parent.mkdir(parents=True, mode=0o700)
        parent_state = parent.lstat()
    if not stat.S_ISDIR(parent_state.st_mode) or stat.S_ISLNK(parent_state.st_mode):
        raise OSError(f"unsafe install state parent: {parent}")
    _assert_owned_by_current_user(parent_state, "install state parent")
    if stat.S_IMODE(parent_state.st_mode) & 0o022:
        raise OSError(f"writable install state parent: {parent}")

    try:
        target_state = target.lstat()
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(target_state.st_mode)
        or stat.S_ISLNK(target_state.st_mode)
        or target_state.st_nlink != 1
    ):
        raise OSError(f"unsafe install state file: {target}")
    _assert_owned_by_current_user(target_state, "install state file")
    if stat.S_IMODE(target_state.st_mode) & 0o022:
        raise OSError(f"writable install state file: {target}")
    return target_state


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
    state = preflight_state_path()
    if state is None:
        return {"managed": {}, "profiles": {}}
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(STATE_PATH, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != state.st_dev
            or opened.st_ino != state.st_ino
        ):
            raise OSError(f"install state changed during validation: {STATE_PATH}")
        _assert_owned_by_current_user(opened, "install state file")
        if stat.S_IMODE(opened.st_mode) & 0o022:
            raise OSError(f"writable install state file: {STATE_PATH}")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            payload = json.load(handle)
            after_read = os.fstat(handle.fileno())
            if (
                after_read.st_dev != opened.st_dev
                or after_read.st_ino != opened.st_ino
                or after_read.st_nlink != opened.st_nlink
                or after_read.st_mode != opened.st_mode
                or after_read.st_size != opened.st_size
                or after_read.st_mtime_ns != opened.st_mtime_ns
                or after_read.st_ctime_ns != opened.st_ctime_ns
            ):
                raise OSError(f"install state changed while reading: {STATE_PATH}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise ValueError("install state must be a JSON object")
    return payload


def save_state(data: dict) -> None:
    preflight_state_path()
    payload = dict(data)
    payload["updated_at"] = now_iso()
    payload["profiles"] = data.get("profiles", {})
    payload["managed"] = data.get("managed", {})
    encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{STATE_PATH.name}.", suffix=".tmp", dir=STATE_PATH.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        preflight_state_path()
        os.replace(temporary_path, STATE_PATH)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(STATE_PATH.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


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
    del custom_aliases
    if profile != "lean":
        print(f"Plugin profile '{profile}' is retired; applying external-free lean policy")
    return run_repo_script("plugin_command.py", "profile", "lean")


def normalize_plugin_profile(profile: str) -> tuple[str, list[str]]:
    if profile != "lean":
        print(
            f"Plugin profile '{profile}' is retired; normalizing saved state to lean"
        )
    return "lean", []


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
        "--mcp-profile",
        choices=["minimal", "research", "context7", "ghgrep", "google-drive"],
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
        "--model-profile",
        choices=["quick", "balanced", "deep", "critical", "visual", "writing"],
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

    try:
        state = load_state()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: install state preflight failed: {exc}")
        return 1
    raw_profiles = state.get("profiles", {})
    raw_managed = state.get("managed", {})
    prev_profiles = copy.deepcopy(raw_profiles) if isinstance(raw_profiles, dict) else {}
    profiles = copy.deepcopy(prev_profiles)
    managed = copy.deepcopy(raw_managed) if isinstance(raw_managed, dict) else {}

    def is_managed_installed(name: str) -> bool:
        value = managed.get(name, {})
        return isinstance(value, dict) and bool(value.get("installed"))

    print("my_opencode install wizard")
    print("-------------------------")
    if args.reconfigure:
        print("mode: reconfigure existing setup")
    else:
        print("mode: fresh or guided setup")

    requested_plugin_profile = args.plugin_profile or choose(
        "Plugin profile",
        ["lean"],
        "lean",
        args.non_interactive,
    )
    plugin_profile, custom_plugins = normalize_plugin_profile(
        requested_plugin_profile
    )

    mcp_profile = args.mcp_profile or choose(
        "MCP profile",
        ["google-drive", "minimal", "research", "context7", "ghgrep"],
        prev_profiles.get("mcp", "google-drive"),
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
        ["quick", "balanced", "deep", "critical", "visual", "writing"],
        prev_profiles.get("model_routing", "balanced"),
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
            "install" if is_managed_installed("opencode_nvim") else "skip",
            args.non_interactive,
        )
        openchamber_action = args.openchamber or choose(
            "OpenChamber integration",
            ["install", "uninstall", "skip"],
            "install" if is_managed_installed("openchamber") else "skip",
            args.non_interactive,
        )

    print("\nApplying configuration...")
    failures: list[str] = []

    def record_failure(label: str) -> None:
        if label not in failures:
            failures.append(label)

    plugin_result = apply_plugin_profile(
        plugin_profile, custom_aliases=custom_plugins
    )
    if plugin_result == 0:
        profiles["plugin"] = plugin_profile
        profiles["custom_plugins"] = custom_plugins
    else:
        record_failure("plugin profile")

    if run_repo_script("mcp_command.py", "profile", mcp_profile) == 0:
        profiles["mcp"] = mcp_profile
    else:
        record_failure("mcp profile")
    if run_repo_script("policy_command.py", "profile", policy_profile) == 0:
        profiles["policy"] = policy_profile
    else:
        record_failure("policy profile")
    if notify_profile != "skip":
        if run_repo_script("notify_command.py", "profile", notify_profile) == 0:
            profiles["notify"] = notify_profile
        else:
            record_failure("notify profile")
    if run_repo_script("telemetry_command.py", "profile", telemetry_profile) == 0:
        profiles["telemetry"] = telemetry_profile
    else:
        record_failure("telemetry profile")
    if run_repo_script("model_routing_command.py", "set-category", model_profile) == 0:
        profiles["model_routing"] = model_profile
    else:
        record_failure("model routing profile")
    if run_repo_script("browser_command.py", "profile", browser_profile) == 0:
        profiles["browser"] = browser_profile
    else:
        record_failure("browser profile")

    post_results: list[int] = []
    if post_profile == "disabled":
        post_results.append(run_repo_script("post_session_command.py", "disable"))
    elif post_profile == "manual-validate":
        post_results.append(run_repo_script("post_session_command.py", "enable"))
        post_results.append(
            run_repo_script(
                "post_session_command.py", "set", "command", "make validate"
            )
        )
        post_results.append(
            run_repo_script(
                "post_session_command.py", "set", "run-on", "manual"
            )
        )
    elif post_profile == "exit-selftest":
        post_results.append(run_repo_script("post_session_command.py", "enable"))
        post_results.append(
            run_repo_script(
                "post_session_command.py", "set", "command", "make selftest"
            )
        )
        post_results.append(
            run_repo_script(
                "post_session_command.py",
                "set",
                "run-on",
                "exit,manual",
            )
        )
    if post_results and all(result == 0 for result in post_results):
        profiles["post_session"] = post_profile
    else:
        record_failure("post-session profile")

    if not args.skip_extras:
        if opencode_nvim_action == "install":
            nvim_results = [install_opencode_nvim()]
            if nvim_results[0] == 0:
                nvim_results.append(
                    run_repo_script(
                        "nvim_integration_command.py", "install", "minimal"
                    )
                )
            if all(result == 0 for result in nvim_results):
                managed["opencode_nvim"] = {
                    "installed": True,
                    "path": str(OPENCODE_NVIM_PATH),
                    "repo": OPENCODE_NVIM_REPO,
                }
                profiles["opencode_nvim"] = opencode_nvim_action
            else:
                record_failure("opencode.nvim profile")
        elif opencode_nvim_action == "uninstall":
            nvim_state = managed.get("opencode_nvim", {})
            if isinstance(nvim_state, dict) and nvim_state.get("installed"):
                nvim_results = [
                    run_repo_script("nvim_integration_command.py", "uninstall"),
                    uninstall_opencode_nvim(),
                ]
                if all(result == 0 for result in nvim_results):
                    managed["opencode_nvim"] = {
                        "installed": False,
                        "path": str(OPENCODE_NVIM_PATH),
                    }
                    profiles["opencode_nvim"] = opencode_nvim_action
                else:
                    record_failure("opencode.nvim profile")
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
                profiles["openchamber"] = openchamber_action
            else:
                record_failure("OpenChamber profile")
        elif openchamber_action == "uninstall":
            openchamber_state = managed.get("openchamber", {})
            if isinstance(openchamber_state, dict) and openchamber_state.get(
                "installed"
            ):
                chosen_manager = (
                    openchamber_state.get("manager") or manager or ""
                )
                if uninstall_openchamber(chosen_manager) == 0:
                    managed["openchamber"] = {
                        "installed": False,
                        "package": OPENCHAMBER_PACKAGE,
                        "manager": chosen_manager,
                    }
                    profiles["openchamber"] = openchamber_action
                else:
                    record_failure("OpenChamber profile")
            else:
                print("Skipping OpenChamber uninstall (not wizard-managed)")

    next_state = dict(state)
    next_state["profiles"] = profiles
    next_state["managed"] = managed
    try:
        save_state(next_state)
        print(f"\nState saved: {STATE_PATH}")
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: install state save failed: {exc}")
        record_failure("install state")

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
