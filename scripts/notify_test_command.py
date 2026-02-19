#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EVENTS = ("complete", "error", "permission", "question")
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def _select_events(raw: list[str]) -> list[str]:
    selected = [item.strip().lower() for item in raw if item.strip()]
    if not selected or "all" in selected:
        return list(EVENTS)
    ordered: list[str] = []
    for event in EVENTS:
        if event in selected:
            ordered.append(event)
    return ordered


def _hook_payload(event: str, label: str, cwd: Path) -> tuple[str, dict[str, Any]]:
    if event == "complete":
        return (
            "session.idle",
            {
                "directory": str(cwd),
                "properties": {"message": f"{label}: complete"},
            },
        )
    if event == "error":
        return (
            "session.error",
            {
                "directory": str(cwd),
                "properties": {"message": f"{label}: error"},
            },
        )
    if event == "permission":
        return (
            "permission.requested",
            {
                "directory": str(cwd),
                "properties": {
                    "permission": f"{label}: permission check",
                    "action": "notify-test",
                },
            },
        )
    return (
        "tool.execute.before",
        {
            "directory": str(cwd),
            "input": {"tool": "question"},
            "properties": {"question": f"{label}: question check"},
        },
    )


def _event_sound(event: str) -> str:
    sounds = {
        "complete": "Glass",
        "error": "Basso",
        "permission": "Purr",
        "question": "Ping",
    }
    return sounds.get(event, "default")


def _icon_path(event: str) -> Path:
    return REPO_ROOT / "assets" / "notify-icons" / "v1" / f"{event}.png"


def _run(command: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        timeout_detail = f"command timed out after {timeout:.1f}s"
        stderr = f"{stderr}\n{timeout_detail}".strip()
        return subprocess.CompletedProcess(command, 124, stdout=stdout, stderr=stderr)


def _send_hook(
    event: str,
    label: str,
    cwd: Path,
    dry_run: bool,
) -> dict[str, Any]:
    event_type, payload = _hook_payload(event, label, cwd)
    script = (
        "(async()=>{"
        "const mod=await import('./plugin/gateway-core/dist/hooks/notify-events/index.js');"
        "const [eventType,payloadRaw,directory]=process.argv.slice(1);"
        "const payload=JSON.parse(payloadRaw);"
        "const hook=mod.createNotifyEventsHook({directory,enabled:true,cooldownMs:0,style:'detailed'});"
        "await hook.event(eventType,payload);"
        "console.log('ok');"
        "})().catch((e)=>{console.error(String(e));process.exit(1);});"
    )
    command = ["node", "-e", script, event_type, json.dumps(payload), str(cwd)]
    if dry_run:
        return {
            "event": event,
            "method": "hook",
            "ok": True,
            "dry_run": True,
            "command": command,
            "payload": payload,
        }
    result = _run(command, timeout=4.0)
    return {
        "event": event,
        "method": "hook",
        "ok": result.returncode == 0,
        "dry_run": False,
        "command": command,
        "payload": payload,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _send_terminal_notifier(
    event: str,
    label: str,
    sender: str,
    include_sound: bool,
    ignore_dnd: bool,
    dry_run: bool,
) -> dict[str, Any]:
    notifier = shutil.which("terminal-notifier") or ""
    if not notifier:
        return {
            "event": event,
            "method": "terminal-notifier",
            "ok": False,
            "dry_run": dry_run,
            "error": "terminal-notifier is not installed",
        }

    title = f"my_opencode {event} test"
    subtitle = "notify test harness"
    message = f"{label}: {event}"
    command = [
        notifier,
        "-title",
        title,
        "-subtitle",
        subtitle,
        "-message",
        message,
        "-group",
        f"my_opencode.notify-test.{event}.{int(time.time() * 1000)}",
    ]
    icon = _icon_path(event)
    if icon.exists():
        command.extend(["-appIcon", str(icon), "-contentImage", str(icon)])
    if include_sound:
        command.extend(["-sound", _event_sound(event)])
    if sender.strip():
        command.extend(["-sender", sender.strip()])
    if ignore_dnd:
        command.append("-ignoreDnD")

    if dry_run:
        return {
            "event": event,
            "method": "terminal-notifier",
            "ok": True,
            "dry_run": True,
            "command": command,
        }

    result = _run(command, timeout=4.0)
    return {
        "event": event,
        "method": "terminal-notifier",
        "ok": result.returncode == 0,
        "dry_run": False,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _send_osascript(
    event: str, label: str, include_sound: bool, dry_run: bool
) -> dict[str, Any]:
    osascript = shutil.which("osascript") or ""
    if not osascript:
        return {
            "event": event,
            "method": "osascript",
            "ok": False,
            "dry_run": dry_run,
            "error": "osascript is not available",
        }

    title = f"my_opencode {event} test"
    subtitle = "notify test harness"
    message = f"{label}: {event}"
    script = (
        f"display notification {json.dumps(message)} "
        f"with title {json.dumps(title)} "
        f"subtitle {json.dumps(subtitle)}"
    )
    if include_sound:
        script = f"{script} sound name {json.dumps(_event_sound(event))}"
    command = [osascript, "-e", script]

    if dry_run:
        return {
            "event": event,
            "method": "osascript",
            "ok": True,
            "dry_run": True,
            "command": command,
        }

    result = _run(command)
    return {
        "event": event,
        "method": "osascript",
        "ok": result.returncode == 0,
        "dry_run": False,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _list_terminal_notifier_entries() -> list[dict[str, str]]:
    notifier = shutil.which("terminal-notifier") or ""
    if not notifier:
        return []
    result = _run([notifier, "-list", "ALL"], timeout=6.0)
    if result.returncode != 0:
        return []
    rows: list[dict[str, str]] = []
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return rows
    for line in lines[1:]:
        cols = line.split("\t")
        while len(cols) < 5:
            cols.append("")
        rows.append(
            {
                "group": cols[0],
                "title": cols[1],
                "subtitle": cols[2],
                "message": cols[3],
                "delivered_at": cols[4],
            }
        )
    return rows


def _print_text(report: dict[str, Any]) -> None:
    print("notify test")
    print("-----------")
    print(f"method: {report['method']}")
    print(f"events: {', '.join(report['events'])}")
    print(f"dry_run: {report['dry_run']}")
    for row in report["results"]:
        status = "PASS" if row.get("ok") else "FAIL"
        detail = row.get("error") or row.get("stderr") or row.get("stdout") or "ok"
        print(f"- {row['event']}: {status} ({detail})")
    if report.get("terminal_notifier_recent"):
        print("terminal-notifier recent entries:")
        for row in report["terminal_notifier_recent"][:8]:
            print(f"- {row['title']} | {row['message']} | {row['delivered_at']}")
    print(f"result: {report['result']}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="/notify-test",
        description="Notification test harness for hook, terminal-notifier, and osascript paths.",
    )
    parser.add_argument(
        "--method",
        choices=("hook", "terminal-notifier", "osascript"),
        default="hook",
    )
    parser.add_argument(
        "--event",
        action="append",
        choices=("all",) + EVENTS,
        default=["all"],
        help="Notification event to send (repeatable).",
    )
    parser.add_argument(
        "--label",
        default="notification probe",
        help="Label prefix in notification messages.",
    )
    parser.add_argument(
        "--sender",
        default="",
        help="terminal-notifier sender bundle id (macOS only).",
    )
    parser.add_argument(
        "--pause-ms",
        type=int,
        default=350,
        help="Pause between notifications in milliseconds.",
    )
    parser.add_argument("--no-sound", action="store_true")
    parser.add_argument("--ignore-dnd", action="store_true")
    parser.add_argument(
        "--list", action="store_true", help="Show recent terminal-notifier rows."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    selected = _select_events(args.event)
    include_sound = not args.no_sound
    cwd = Path.cwd().resolve()

    results: list[dict[str, Any]] = []
    for index, event in enumerate(selected):
        if args.method == "hook":
            row = _send_hook(event, args.label, cwd, args.dry_run)
        elif args.method == "terminal-notifier":
            row = _send_terminal_notifier(
                event,
                args.label,
                args.sender,
                include_sound,
                args.ignore_dnd,
                args.dry_run,
            )
        else:
            row = _send_osascript(event, args.label, include_sound, args.dry_run)
        results.append(row)
        if index + 1 < len(selected) and args.pause_ms > 0:
            time.sleep(args.pause_ms / 1000)

    success = all(bool(row.get("ok")) for row in results)
    report: dict[str, Any] = {
        "result": "PASS" if success else "FAIL",
        "method": args.method,
        "events": selected,
        "dry_run": bool(args.dry_run),
        "results": results,
    }
    if args.list:
        report["terminal_notifier_recent"] = _list_terminal_notifier_entries()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_text(report)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
