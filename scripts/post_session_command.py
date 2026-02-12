#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path


CONFIG_PATH = Path(
    os.environ.get(
        "MY_OPENCODE_SESSION_CONFIG_PATH", "~/.config/opencode/opencode-session.json"
    )
).expanduser()

VALID_RUN_ON = ("exit", "manual", "idle")


def default_config() -> dict:
    return {
        "post_session": {
            "enabled": False,
            "command": "",
            "timeout_ms": 120000,
            "run_on": ["exit"],
        }
    }


def load_config() -> dict:
    config = default_config()
    if not CONFIG_PATH.exists():
        return config

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    post = data.get("post_session")
    if isinstance(post, dict):
        cfg = config["post_session"]
        if isinstance(post.get("enabled"), bool):
            cfg["enabled"] = post["enabled"]
        if isinstance(post.get("command"), str):
            cfg["command"] = post["command"]
        if isinstance(post.get("timeout_ms"), int) and post["timeout_ms"] > 0:
            cfg["timeout_ms"] = post["timeout_ms"]
        if isinstance(post.get("run_on"), list):
            values = [
                x for x in post["run_on"] if isinstance(x, str) and x in VALID_RUN_ON
            ]
            if values:
                cfg["run_on"] = values
    return config


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def usage() -> int:
    print(
        "usage: /post-session status | /post-session help | /post-session enable | /post-session disable | /post-session set command <shell-command> | /post-session set timeout <ms> | /post-session set run-on <exit|manual|idle|comma-list>"
    )
    return 2


def print_status(config: dict) -> int:
    post = config["post_session"]
    print(f"enabled: {'yes' if post['enabled'] else 'no'}")
    print(f"command: {post['command'] or '(unset)'}")
    print(f"timeout_ms: {post['timeout_ms']}")
    print(f"run_on: {','.join(post['run_on'])}")
    print(f"config: {CONFIG_PATH}")
    return 0


def parse_run_on(value: str) -> list[str] | None:
    items = [x.strip() for x in value.split(",") if x.strip()]
    if not items:
        return None
    for item in items:
        if item not in VALID_RUN_ON:
            return None
    return items


def main(argv: list[str]) -> int:
    config = load_config()
    post = config["post_session"]

    if not argv or argv[0] == "status":
        return print_status(config)

    if argv[0] == "help":
        return usage()

    if argv[0] == "enable":
        post["enabled"] = True
        save_config(config)
        print("post-session: enabled")
        print(f"config: {CONFIG_PATH}")
        return 0

    if argv[0] == "disable":
        post["enabled"] = False
        save_config(config)
        print("post-session: disabled")
        print(f"config: {CONFIG_PATH}")
        return 0

    if argv[0] == "set":
        if len(argv) < 3:
            return usage()

        key = argv[1]
        if key == "command":
            command = " ".join(argv[2:]).strip()
            post["command"] = command
            save_config(config)
            print("command: updated")
            print(f"config: {CONFIG_PATH}")
            return 0

        if key == "timeout":
            try:
                timeout = int(argv[2])
            except ValueError:
                print("error: timeout must be integer milliseconds")
                return 1
            if timeout <= 0:
                print("error: timeout must be greater than zero")
                return 1
            post["timeout_ms"] = timeout
            save_config(config)
            print(f"timeout_ms: {timeout}")
            print(f"config: {CONFIG_PATH}")
            return 0

        if key == "run-on":
            value = " ".join(argv[2:]).strip()
            run_on = parse_run_on(value)
            if not run_on:
                print("error: run-on must be a comma-list using exit,manual,idle")
                return 1
            post["run_on"] = run_on
            save_config(config)
            print(f"run_on: {','.join(run_on)}")
            print(f"config: {CONFIG_PATH}")
            return 0

        return usage()

    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
