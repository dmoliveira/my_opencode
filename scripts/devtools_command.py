#!/usr/bin/env python3

import json
import shutil
import subprocess
import sys


TOOLS = {
    "direnv": {"bin": "direnv", "brew": "direnv"},
    "gh-dash": {"bin": "gh", "gh_extension": "dlvhdr/gh-dash"},
    "ripgrep-all": {"bin": "rga", "brew": "ripgrep-all"},
    "pre-commit": {"bin": "pre-commit", "brew": "pre-commit"},
    "lefthook": {"bin": "lefthook", "brew": "lefthook"},
}


def usage() -> int:
    print(
        "usage: /devtools status | /devtools help | /devtools doctor [--json] | /devtools install [all|<tool> ...] | /devtools hooks-install"
    )
    print("tools: direnv, gh-dash, ripgrep-all, pre-commit, lefthook")
    return 2


def installed_path(name: str) -> str | None:
    return shutil.which(TOOLS[name]["bin"])


def gh_extension_installed(repo: str) -> bool:
    if not shutil.which("gh"):
        return False
    out = subprocess.run(
        ["gh", "extension", "list"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        return False
    return repo in out.stdout


def tool_installed(name: str) -> bool:
    if name == "gh-dash":
        return gh_extension_installed(TOOLS[name]["gh_extension"])
    return bool(installed_path(name))


def list_status() -> dict:
    result = {}
    for name in TOOLS:
        path = installed_path(name)
        result[name] = {
            "installed": tool_installed(name),
            "binary": TOOLS[name]["bin"],
            "path": path,
        }
    return result


def print_status() -> int:
    status = list_status()
    for name, data in status.items():
        if data["installed"]:
            print(f"{name}: installed ({data['path']})")
        else:
            print(f"{name}: missing")
    print("next:")
    print("- /devtools install all")
    print("- /devtools hooks-install")
    return 0


def print_doctor(json_output: bool) -> int:
    status = list_status()
    missing = [name for name, data in status.items() if not data["installed"]]
    report = {
        "result": "PASS" if not missing else "FAIL",
        "tools": status,
        "missing": missing,
        "quick_fixes": [
            "run /devtools install all",
            "run /devtools hooks-install",
            'enable direnv hook in your shell: eval "$(direnv hook zsh)"',
        ]
        if missing
        else [],
    }

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print("devtools doctor")
        print("--------------")
        for name, data in status.items():
            state = "PASS" if data["installed"] else "FAIL"
            suffix = data["path"] if data["path"] else "not installed"
            print(f"- {name}: {state} ({suffix})")
        print(f"result: {report['result']}")
        if missing:
            print("quick_fixes:")
            for item in report["quick_fixes"]:
                print(f"- {item}")

    return 0 if report["result"] == "PASS" else 1


def brew_install(formula: str) -> int:
    return subprocess.run(["brew", "install", formula], check=False).returncode


def install_gh_dash() -> int:
    if not shutil.which("gh"):
        print("error: gh CLI is required for gh-dash extension install")
        return 1
    if gh_extension_installed(TOOLS["gh-dash"]["gh_extension"]):
        return subprocess.run(
            ["gh", "extension", "upgrade", "gh-dash"], check=False
        ).returncode
    return subprocess.run(
        ["gh", "extension", "install", TOOLS["gh-dash"]["gh_extension"]],
        check=False,
    ).returncode


def install_tools(targets: list[str]) -> int:
    if not shutil.which("brew"):
        print("error: Homebrew is required for automated install")
        return 1

    names = list(TOOLS.keys()) if not targets or targets == ["all"] else targets
    invalid = [name for name in names if name not in TOOLS]
    if invalid:
        print(f"error: unknown tool(s): {', '.join(invalid)}")
        return usage()

    failed = []
    for name in names:
        if tool_installed(name):
            print(f"{name}: already installed")
            continue
        if name == "gh-dash":
            print("installing gh-dash via gh extension...")
            if install_gh_dash() != 0:
                failed.append(name)
            continue

        print(f"installing {name} via brew...")
        if brew_install(TOOLS[name]["brew"]) != 0:
            failed.append(name)

    if failed:
        print(f"failed installs: {', '.join(failed)}")
        return 1

    return print_status()


def hooks_install() -> int:
    if not shutil.which("lefthook"):
        print("error: lefthook is missing; run /devtools install lefthook")
        return 1
    if not shutil.which("pre-commit"):
        print("error: pre-commit is missing; run /devtools install pre-commit")
        return 1

    installed = subprocess.run(["lefthook", "install"], check=False)
    if installed.returncode != 0:
        return 1
    print("git hooks installed: lefthook (pre-commit managed via lefthook.yml)")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return print_status()
    if argv[0] == "help":
        return usage()
    if argv[0] == "doctor":
        if len(argv) > 2 or (len(argv) == 2 and argv[1] != "--json"):
            return usage()
        return print_doctor(json_output=(len(argv) == 2 and argv[1] == "--json"))
    if argv[0] == "install":
        return install_tools(argv[1:])
    if argv[0] == "hooks-install":
        return hooks_install()
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
