#!/usr/bin/env python3

import json
import os
import shutil
import sys
from pathlib import Path


NVIM_CONFIG_DIR = Path(
    os.environ.get("MY_OPENCODE_NVIM_CONFIG_DIR", "~/.config/nvim")
).expanduser()
INTEGRATION_FILE = NVIM_CONFIG_DIR / "lua" / "my_opencode" / "opencode.lua"
INIT_FILE = NVIM_CONFIG_DIR / "init.lua"
PLUGIN_DIR = Path(
    os.environ.get(
        "MY_OPENCODE_NVIM_PLUGIN_DIR",
        "~/.local/share/nvim/site/pack/opencode/start/opencode.nvim",
    )
).expanduser()
REQUIRE_LINE = 'require("my_opencode.opencode")'

PROFILES = {
    "minimal": """local M = {}

function M.setup()
  vim.o.autoread = true

  vim.keymap.set({ "n", "x" }, "<leader>oa", function()
    require("opencode").ask("@this: ", { submit = true })
  end, { desc = "OpenCode Ask" })

  vim.keymap.set({ "n", "x" }, "<leader>os", function()
    require("opencode").select()
  end, { desc = "OpenCode Select" })
end

M.setup()
return M
""",
    "power": """local M = {}

local function ask_current()
  require("opencode").ask("@this: ", { submit = true })
end

local function ask_current_draft()
  require("opencode").ask("@this: ")
end

function M.setup()
  vim.o.autoread = true

  vim.keymap.set({ "n", "x" }, "<leader>oa", ask_current, { desc = "OpenCode Ask" })
  vim.keymap.set({ "n", "x" }, "<leader>oA", ask_current_draft, { desc = "OpenCode Ask Draft" })
  vim.keymap.set({ "n", "x" }, "<leader>os", function()
    require("opencode").select()
  end, { desc = "OpenCode Select" })
  vim.keymap.set("n", "<leader>or", function()
    vim.cmd("checkhealth opencode")
  end, { desc = "OpenCode Health" })
end

M.setup()
return M
""",
}


def usage() -> int:
    print(
        "usage: /nvim status | /nvim help | /nvim snippet <minimal|power> | /nvim install <minimal|power> [--link-init] | /nvim doctor [--json] | /nvim uninstall [--unlink-init]"
    )
    return 2


def plugin_installed() -> bool:
    return (PLUGIN_DIR / ".git").exists() or (PLUGIN_DIR / "lua").exists()


def integration_installed() -> bool:
    return INTEGRATION_FILE.exists()


def init_linked() -> bool:
    if not INIT_FILE.exists():
        return False
    text = INIT_FILE.read_text(encoding="utf-8")
    return REQUIRE_LINE in text


def ensure_init_link() -> None:
    INIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if INIT_FILE.exists():
        content = INIT_FILE.read_text(encoding="utf-8")
        if REQUIRE_LINE in content:
            return
        append_prefix = "\n" if content and not content.endswith("\n") else ""
        INIT_FILE.write_text(
            content + append_prefix + REQUIRE_LINE + "\n", encoding="utf-8"
        )
        return
    INIT_FILE.write_text(REQUIRE_LINE + "\n", encoding="utf-8")


def remove_init_link() -> None:
    if not INIT_FILE.exists():
        return
    lines = INIT_FILE.read_text(encoding="utf-8").splitlines()
    filtered = [line for line in lines if line.strip() != REQUIRE_LINE]
    data = "\n".join(filtered).strip()
    if data:
        INIT_FILE.write_text(data + "\n", encoding="utf-8")
    else:
        INIT_FILE.unlink()


def print_status() -> int:
    print(f"nvim_binary: {'found' if shutil.which('nvim') else 'missing'}")
    print(f"opencode_nvim: {'installed' if plugin_installed() else 'missing'}")
    print(f"integration_file: {'present' if integration_installed() else 'missing'}")
    print(f"init_link: {'present' if init_linked() else 'missing'}")
    print(f"plugin_path: {PLUGIN_DIR}")
    print(f"integration_path: {INTEGRATION_FILE}")
    print(f"init_path: {INIT_FILE}")
    print("next:")
    print("- /nvim install minimal --link-init")
    print("- /nvim install power --link-init")
    print("- /nvim doctor")
    return 0


def print_snippet(profile: str) -> int:
    if profile not in PROFILES:
        return usage()
    print(PROFILES[profile])
    return 0


def install_profile(profile: str, link_init: bool) -> int:
    if profile not in PROFILES:
        return usage()
    INTEGRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    INTEGRATION_FILE.write_text(PROFILES[profile], encoding="utf-8")
    if link_init:
        ensure_init_link()
    print(f"installed_profile: {profile}")
    print(f"integration_path: {INTEGRATION_FILE}")
    if link_init:
        print(f"init_path: {INIT_FILE}")
    return 0


def uninstall_profile(unlink_init: bool) -> int:
    if INTEGRATION_FILE.exists():
        INTEGRATION_FILE.unlink()
    if unlink_init:
        remove_init_link()
    print(f"integration_path: {INTEGRATION_FILE}")
    print("status: removed")
    return 0


def collect_doctor() -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    if not shutil.which("nvim"):
        warnings.append("nvim binary not found in PATH")
    if not plugin_installed():
        problems.append("opencode.nvim plugin is not installed")
    if not integration_installed():
        problems.append(
            "integration file is missing (run /nvim install minimal --link-init)"
        )
    if integration_installed() and not init_linked():
        warnings.append("init.lua does not require my_opencode.opencode")

    return {
        "result": "PASS" if not problems else "FAIL",
        "plugin_path": str(PLUGIN_DIR),
        "integration_path": str(INTEGRATION_FILE),
        "init_path": str(INIT_FILE),
        "nvim_binary": "found" if shutil.which("nvim") else "missing",
        "opencode_nvim": "installed" if plugin_installed() else "missing",
        "integration_file": "present" if integration_installed() else "missing",
        "init_link": "present" if init_linked() else "missing",
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "install plugin: git clone https://github.com/nickjvandyke/opencode.nvim ~/.local/share/nvim/site/pack/opencode/start/opencode.nvim",
            "create integration: /nvim install minimal --link-init",
            "validate in nvim: :checkhealth opencode",
        ]
        if warnings or problems
        else [],
    }


def print_doctor(json_output: bool) -> int:
    report = collect_doctor()
    if json_output:
        print(json.dumps(report, indent=2))
        return 0 if report["result"] == "PASS" else 1

    print("nvim doctor")
    print("-----------")
    print(f"nvim_binary: {report['nvim_binary']}")
    print(f"opencode_nvim: {report['opencode_nvim']}")
    print(f"integration_file: {report['integration_file']}")
    print(f"init_link: {report['init_link']}")
    print(f"plugin_path: {report['plugin_path']}")
    print(f"integration_path: {report['integration_path']}")
    print(f"init_path: {report['init_path']}")
    if report["warnings"]:
        print("warnings:")
        for item in report["warnings"]:
            print(f"- {item}")
    if report["problems"]:
        print("problems:")
        for item in report["problems"]:
            print(f"- {item}")
        print("quick_fixes:")
        for item in report["quick_fixes"]:
            print(f"- {item}")
        print("result: FAIL")
        return 1
    print("result: PASS")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return print_status()

    if argv[0] == "help":
        return usage()

    if argv[0] == "snippet":
        if len(argv) < 2:
            return usage()
        return print_snippet(argv[1])

    if argv[0] == "install":
        if len(argv) < 2:
            return usage()
        link_init = any(arg == "--link-init" for arg in argv[2:])
        return install_profile(argv[1], link_init)

    if argv[0] == "doctor":
        json_output = len(argv) > 1 and argv[1] == "--json"
        if len(argv) > 1 and not json_output:
            return usage()
        return print_doctor(json_output)

    if argv[0] == "uninstall":
        unlink_init = len(argv) > 1 and argv[1] == "--unlink-init"
        if len(argv) > 1 and not unlink_init:
            return usage()
        return uninstall_profile(unlink_init)

    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
