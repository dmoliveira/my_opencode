#!/usr/bin/env python3

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import layering_report  # type: ignore


CONFIG_DIR = Path(
    os.environ.get("OPENCODE_CONFIG_DIR", "~/.config/opencode")
).expanduser()
BACKUP_DIR = CONFIG_DIR / "my_opencode-backups"
MANIFEST_PATH = BACKUP_DIR / "manifest.json"
UNSUPPORTED_TOP_LEVEL_KEYS = {"observability", "model_routing"}


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def usage() -> int:
    print(
        "usage: /config status | /config layers [--json] | /config help | /config backup [--name <label>] | /config list | /config restore <backup-id> | /config sanitize [--apply] [--json] | /config safe-start [--no-apply]"
    )
    return 2


def ensure_manifest() -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST_PATH.exists():
        data = {"backups": []}
        MANIFEST_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return data
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_manifest(data: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def discover_files() -> list[Path]:
    files = []
    for path in CONFIG_DIR.glob("opencode*.json"):
        if path.is_file():
            files.append(path)
    files.sort()
    return files


def command_status() -> int:
    manifest = ensure_manifest()
    print(f"config_dir: {CONFIG_DIR}")
    print(f"backup_dir: {BACKUP_DIR}")
    print(f"tracked_backups: {len(manifest.get('backups', []))}")
    print("next:")
    print("- /config layers")
    print("- /config backup")
    print("- /config list")
    print("- /config sanitize --apply")
    print("- /config safe-start")
    return 0


def command_sanitize(argv: list[str]) -> int:
    apply_changes = "--apply" in argv
    json_output = "--json" in argv
    if any(arg not in ("--apply", "--json") for arg in argv):
        return usage()

    files = discover_files()
    findings: list[dict[str, object]] = []
    removed_total = 0

    for file_path in files:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(
                {
                    "file": str(file_path),
                    "result": "invalid_json",
                    "error": str(exc),
                    "removed_keys": [],
                }
            )
            continue

        if not isinstance(payload, dict):
            findings.append(
                {
                    "file": str(file_path),
                    "result": "not_object",
                    "removed_keys": [],
                }
            )
            continue

        removed_keys = sorted(
            [key for key in UNSUPPORTED_TOP_LEVEL_KEYS if key in payload]
        )
        if removed_keys and apply_changes:
            for key in removed_keys:
                payload.pop(key, None)
            file_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        removed_total += len(removed_keys)
        findings.append(
            {
                "file": str(file_path),
                "result": "updated" if removed_keys and apply_changes else "ok",
                "removed_keys": removed_keys,
            }
        )

    result = "PASS"
    payload = {
        "result": result,
        "apply": apply_changes,
        "files_checked": len(files),
        "removed_keys_total": removed_total,
        "findings": findings,
        "unsupported_keys": sorted(UNSUPPORTED_TOP_LEVEL_KEYS),
    }

    if json_output:
        print(json.dumps(payload, indent=2))
    else:
        print(f"result: {result}")
        print(f"apply: {'yes' if apply_changes else 'no'}")
        print(f"files_checked: {len(files)}")
        print(f"removed_keys_total: {removed_total}")
        for item in findings:
            removed = item.get("removed_keys", [])
            removed_text = (
                ",".join(removed) if isinstance(removed, list) and removed else "(none)"
            )
            print(f"- {item.get('file')}: {item.get('result')} removed={removed_text}")
    return 0


def command_safe_start(argv: list[str]) -> int:
    if any(arg not in ("--no-apply",) for arg in argv):
        return usage()
    sanitize_args: list[str] = []
    if "--no-apply" not in argv:
        sanitize_args.append("--apply")
    sanitize_code = command_sanitize(sanitize_args)
    if sanitize_code != 0:
        return sanitize_code
    print("safe_start: ready")
    print("next: start or continue opencode session")
    print("next: run /gateway status --json when debugging runtime hooks")
    return 0


def command_layers(argv: list[str]) -> int:
    json_output = "--json" in argv
    if any(arg not in ("--json",) for arg in argv):
        return usage()

    report = layering_report()
    if json_output:
        print(json.dumps(report, indent=2))
        return 0

    print("config layers")
    print("-------------")
    if report["env_override"]:
        print(f"env_override: {report['env_override']}")
    for layer in report["layers"]:
        state = "active" if layer["exists"] else "missing"
        print(
            f"- p{layer['priority']}: {layer['name']} [{layer['kind']}] {state} ({layer['path']})"
        )
    print(f"write_path: {report['write_path']}")
    return 0


def command_backup(argv: list[str]) -> int:
    label = None
    if "--name" in argv:
        idx = argv.index("--name")
        if idx + 1 >= len(argv):
            return usage()
        label = argv[idx + 1]

    files = discover_files()
    if not files:
        print(f"error: no opencode*.json files found in {CONFIG_DIR}")
        return 1

    manifest = ensure_manifest()
    backup_id = now_stamp()
    if label:
        clean = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in label)
        backup_id = f"{backup_id}-{clean}"[:80]

    target_dir = BACKUP_DIR / backup_id
    target_dir.mkdir(parents=True, exist_ok=False)

    copied = []
    for src in files:
        dst = target_dir / src.name
        shutil.copy2(src, dst)
        copied.append(src.name)

    record = {
        "id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": copied,
    }
    manifest.setdefault("backups", []).append(record)
    save_manifest(manifest)

    print(f"backup: {backup_id}")
    print(f"files: {', '.join(copied)}")
    print(f"path: {target_dir}")
    return 0


def command_list() -> int:
    manifest = ensure_manifest()
    backups = manifest.get("backups", [])
    if not backups:
        print("no backups yet")
        print(f"backup_dir: {BACKUP_DIR}")
        return 0

    print("backups:")
    for item in reversed(backups[-20:]):
        files = ",".join(item.get("files", []))
        print(f"- {item.get('id')} ({item.get('created_at')}) [{files}]")
    print(f"backup_dir: {BACKUP_DIR}")
    return 0


def command_restore(argv: list[str]) -> int:
    if not argv:
        return usage()
    backup_id = argv[0]
    manifest = ensure_manifest()
    match = None
    for item in manifest.get("backups", []):
        if item.get("id") == backup_id:
            match = item
            break
    if not match:
        print(f"error: backup not found: {backup_id}")
        return 1

    source_dir = BACKUP_DIR / backup_id
    if not source_dir.exists():
        print(f"error: backup directory missing: {source_dir}")
        return 1

    restored = []
    for file_name in match.get("files", []):
        src = source_dir / file_name
        if not src.exists():
            continue
        dst = CONFIG_DIR / file_name
        shutil.copy2(src, dst)
        restored.append(file_name)

    print(f"restored: {backup_id}")
    print(f"files: {', '.join(restored) if restored else '(none)'}")
    print(f"config_dir: {CONFIG_DIR}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        return command_status()
    if argv[0] == "layers":
        return command_layers(argv[1:])
    if argv[0] == "help":
        return usage()
    if argv[0] == "backup":
        return command_backup(argv[1:])
    if argv[0] == "list":
        return command_list()
    if argv[0] == "restore":
        return command_restore(argv[1:])
    if argv[0] == "sanitize":
        return command_sanitize(argv[1:])
    if argv[0] == "safe-start":
        return command_safe_start(argv[1:])
    return usage()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
