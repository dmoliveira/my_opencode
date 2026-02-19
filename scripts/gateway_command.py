#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = getattr(datetime, "UTC", timezone.utc)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config_layering import load_layered_config, resolve_write_path, save_config  # type: ignore
from gateway_reason_codes import (  # type: ignore
    BRIDGE_STATE_IGNORED_IN_PLUGIN_MODE,
    GATEWAY_PLUGIN_DISABLED,
    GATEWAY_PLUGIN_NOT_READY,
    GATEWAY_PLUGIN_READY,
    GATEWAY_PLUGIN_RUNTIME_UNAVAILABLE,
    LOOP_STATE_AVAILABLE,
)
from gateway_plugin_bridge import (  # type: ignore
    cleanup_orphan_loop,
    gateway_plugin_entries,
    gateway_loop_state_path,
    gateway_plugin_spec,
    load_gateway_loop_state,
    plugin_enabled,
    set_plugin_enabled,
)


# Prints usage for gateway command.
def usage() -> int:
    print(
        "usage: /gateway status [--json] | /gateway enable [--force] [--json] | /gateway disable [--json] | /gateway doctor [--json] | /gateway tune memory [--apply] [--json] | /gateway recover memory [--apply] [--resume] [--compress] [--continue-prompt] [--force-kill] [--watch] [--interval-seconds <n>] [--max-cycles <n>] [--json] | /gateway protection <status|enable|disable|report|cache> [--interval-seconds <n>] [--max-cycles <n>] [--limit <n>] [--clear] [--json]"
    )
    return 2


# Emits payload in JSON or compact text form.
def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


# Loads writable layered config data and path.
def load_config() -> tuple[dict[str, Any], Path]:
    config, _ = load_layered_config()
    return config, resolve_write_path()


# Returns gateway plugin package path under local config.
def plugin_dir(home: Path) -> Path:
    return home / ".config" / "opencode" / "my_opencode" / "plugin" / "gateway-core"


def gateway_event_audit_enabled() -> bool:
    raw = os.environ.get("MY_OPENCODE_GATEWAY_EVENT_AUDIT", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def gateway_event_audit_path(cwd: Path) -> Path:
    raw = os.environ.get("MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return cwd / ".opencode" / "gateway-events.jsonl"


def gateway_event_counters(cwd: Path) -> dict[str, Any]:
    path = gateway_event_audit_path(cwd)
    if not path.exists():
        return {
            "audit_path": str(path),
            "total_events": 0,
            "context_warnings_triggered": 0,
            "compactions_triggered": 0,
            "global_process_pressure_warnings": 0,
            "global_process_pressure_critical_events": 0,
            "recent_window_minutes": 30,
            "recent_context_warnings": 0,
            "recent_compactions": 0,
            "recent_global_process_pressure_warnings": 0,
            "recent_global_process_pressure_critical_events": 0,
            "session_pressure_attribution": [],
            "last_critical_triggered_at": None,
            "last_triggered_at": None,
        }

    total_events = 0
    context_warnings = 0
    compactions = 0
    global_pressure_warnings = 0
    global_pressure_critical_events = 0
    recent_context_warnings = 0
    recent_compactions = 0
    recent_global_pressure_warnings = 0
    recent_global_pressure_critical_events = 0
    attribution: dict[str, dict[str, Any]] = {}
    recent_window_minutes = 30
    now_utc = datetime.now(UTC)
    last_triggered_at: str | None = None
    last_critical_triggered_at: str | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                total_events += 1
                reason_code = str(payload.get("reason_code") or "")
                session_id = str(payload.get("session_id") or "").strip()
                event_time: datetime | None = None
                for key in ("timestamp", "ts", "time"):
                    event_time = parse_iso(payload.get(key))
                    if event_time is not None:
                        break
                in_recent_window = False
                if event_time is not None:
                    delta_seconds = (now_utc - event_time).total_seconds()
                    in_recent_window = (
                        0 <= delta_seconds <= (recent_window_minutes * 60)
                    )
                if reason_code == "context_warning_appended":
                    context_warnings += 1
                    if in_recent_window:
                        recent_context_warnings += 1
                elif reason_code == "session_compacted_preemptively":
                    compactions += 1
                    if in_recent_window:
                        recent_compactions += 1
                elif reason_code in {
                    "global_process_pressure_warning_appended",
                    "global_process_pressure_warning_detected_no_append",
                }:
                    global_pressure_warnings += 1
                    if in_recent_window:
                        recent_global_pressure_warnings += 1
                    if session_id:
                        row = attribution.setdefault(
                            session_id,
                            {
                                "session_id": session_id,
                                "warning_events": 0,
                                "critical_events": 0,
                                "observed_global_rss_mb": 0.0,
                                "last_event_at": None,
                            },
                        )
                        row["warning_events"] = int(row["warning_events"]) + 1
                elif reason_code in {
                    "global_process_pressure_critical_appended",
                    "global_process_pressure_critical_detected_no_append",
                }:
                    global_pressure_critical_events += 1
                    if in_recent_window:
                        recent_global_pressure_critical_events += 1
                    if session_id:
                        row = attribution.setdefault(
                            session_id,
                            {
                                "session_id": session_id,
                                "warning_events": 0,
                                "critical_events": 0,
                                "observed_global_rss_mb": 0.0,
                                "last_event_at": None,
                            },
                        )
                        row["critical_events"] = int(row["critical_events"]) + 1
                rss_value = payload.get("max_rss_mb")
                if (
                    session_id
                    and isinstance(rss_value, (int, float))
                    and in_recent_window
                ):
                    row = attribution.setdefault(
                        session_id,
                        {
                            "session_id": session_id,
                            "warning_events": 0,
                            "critical_events": 0,
                            "observed_global_rss_mb": 0.0,
                            "last_event_at": None,
                        },
                    )
                    row["observed_global_rss_mb"] = max(
                        float(row["observed_global_rss_mb"]), float(rss_value)
                    )
                if reason_code in {
                    "context_warning_appended",
                    "session_compacted_preemptively",
                    "global_process_pressure_warning_appended",
                    "global_process_pressure_warning_detected_no_append",
                    "global_process_pressure_critical_appended",
                    "global_process_pressure_critical_detected_no_append",
                }:
                    if event_time is not None:
                        last_triggered_at = event_time.isoformat()
                        if session_id and session_id in attribution:
                            attribution[session_id]["last_event_at"] = (
                                event_time.isoformat()
                            )
                    else:
                        for key in ("timestamp", "ts", "time"):
                            value = payload.get(key)
                            if isinstance(value, str) and value.strip():
                                last_triggered_at = value.strip()
                                if session_id and session_id in attribution:
                                    attribution[session_id]["last_event_at"] = (
                                        value.strip()
                                    )
                                break
                if reason_code in {
                    "global_process_pressure_critical_appended",
                    "global_process_pressure_critical_detected_no_append",
                }:
                    if event_time is not None:
                        last_critical_triggered_at = event_time.isoformat()
                    else:
                        for key in ("timestamp", "ts", "time"):
                            value = payload.get(key)
                            if isinstance(value, str) and value.strip():
                                last_critical_triggered_at = value.strip()
                                break
    except (OSError, UnicodeDecodeError):
        return {
            "audit_path": str(path),
            "total_events": 0,
            "context_warnings_triggered": 0,
            "compactions_triggered": 0,
            "recent_window_minutes": recent_window_minutes,
            "recent_context_warnings": 0,
            "recent_compactions": 0,
            "global_process_pressure_warnings": 0,
            "recent_global_process_pressure_warnings": 0,
            "global_process_pressure_critical_events": 0,
            "recent_global_process_pressure_critical_events": 0,
            "session_pressure_attribution": [],
            "last_critical_triggered_at": None,
            "last_triggered_at": None,
            "read_error": True,
        }

    attribution_rows = sorted(
        [
            row
            for row in attribution.values()
            if isinstance(row.get("last_event_at"), str)
            and (
                (
                    lambda dt: (
                        dt is not None
                        and 0
                        <= (now_utc - dt).total_seconds()
                        <= (recent_window_minutes * 60)
                    )
                )(parse_iso(row.get("last_event_at")))
            )
        ],
        key=lambda row: (
            int(row.get("critical_events") or 0),
            float(row.get("observed_global_rss_mb") or 0),
            int(row.get("warning_events") or 0),
        ),
        reverse=True,
    )[:5]
    for row in attribution_rows:
        row["attribution_scope"] = "global_sample_observed_during_session_event"

    return {
        "audit_path": str(path),
        "total_events": total_events,
        "context_warnings_triggered": context_warnings,
        "compactions_triggered": compactions,
        "recent_window_minutes": recent_window_minutes,
        "recent_context_warnings": recent_context_warnings,
        "recent_compactions": recent_compactions,
        "global_process_pressure_warnings": global_pressure_warnings,
        "recent_global_process_pressure_warnings": recent_global_pressure_warnings,
        "global_process_pressure_critical_events": global_pressure_critical_events,
        "recent_global_process_pressure_critical_events": recent_global_pressure_critical_events,
        "session_pressure_attribution": attribution_rows,
        "last_critical_triggered_at": last_critical_triggered_at,
        "last_triggered_at": last_triggered_at,
    }


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def runtime_staleness(home: Path) -> dict[str, Any]:
    runtime_path = (
        home
        / ".config"
        / "opencode"
        / "my_opencode"
        / "runtime"
        / "autopilot_runtime.json"
    )
    if not runtime_path.exists():
        return {
            "exists": False,
            "path": str(runtime_path),
            "status": None,
            "is_stale_running": False,
            "age_minutes": None,
            "blockers": [],
        }
    try:
        payload = json.loads(runtime_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "exists": True,
            "path": str(runtime_path),
            "status": None,
            "is_stale_running": False,
            "age_minutes": None,
            "blockers": [],
            "read_error": True,
        }
    runtime = payload if isinstance(payload, dict) else {}
    status = str(runtime.get("status") or "").strip().lower()
    blockers_any = runtime.get("blockers")
    blockers = blockers_any if isinstance(blockers_any, list) else []
    updated_at = parse_iso(runtime.get("updated_at"))
    age_minutes: int | None = None
    if updated_at is not None:
        age_minutes = int((datetime.now(UTC) - updated_at).total_seconds() / 60)
    is_stale_running = (
        status == "running" and age_minutes is not None and age_minutes >= 30
    )
    return {
        "exists": True,
        "path": str(runtime_path),
        "status": status or None,
        "is_stale_running": is_stale_running,
        "age_minutes": age_minutes,
        "blockers": [str(item) for item in blockers if isinstance(item, str)],
    }


def process_pressure(config: dict[str, Any] | None = None) -> dict[str, Any]:
    def is_opencode_command(command: str) -> bool:
        lowered = command.strip().lower()
        if not lowered:
            return False
        return bool(re.search(r"(^|[\s/])opencode(\s|$)", lowered))

    def parse_elapsed_seconds(value: str) -> int:
        text = value.strip()
        if not text:
            return 0
        days = 0
        clock = text
        if "-" in text:
            parts = text.split("-", 1)
            try:
                days = int(parts[0])
            except ValueError:
                days = 0
            clock = parts[1] if len(parts) > 1 else ""
        chunks = clock.split(":")
        try:
            nums = [int(item) for item in chunks]
        except ValueError:
            return 0
        hours = 0
        minutes = 0
        seconds = 0
        if len(nums) == 3:
            hours, minutes, seconds = nums
        elif len(nums) == 2:
            minutes, seconds = nums
        elif len(nums) == 1:
            seconds = nums[0]
        return max(0, days * 86400 + hours * 3600 + minutes * 60 + seconds)

    def duration_threshold_seconds(raw: Any) -> int:
        text = str(raw or "").strip().lower()
        match = re.match(
            r"^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$",
            text,
        )
        if not match:
            return 0
        value = int(match.group(1))
        unit = match.group(2)
        if unit in {"s", "sec", "secs", "second", "seconds"}:
            return value
        if unit in {"m", "min", "mins", "minute", "minutes"}:
            return value * 60
        if unit in {"h", "hr", "hrs", "hour", "hours"}:
            return value * 3600
        return value * 86400

    def size_to_mb(raw: Any) -> float:
        text = str(raw or "").strip().upper()
        if not text:
            return 0.0
        match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([KMGTP])(?:B)?$", text)
        if not match:
            return 0.0
        value = float(match.group(1))
        unit = match.group(2)
        factors = {
            "K": 1 / 1024,
            "M": 1.0,
            "G": 1024.0,
            "T": 1024.0 * 1024.0,
            "P": 1024.0 * 1024.0 * 1024.0,
        }
        return round(value * factors.get(unit, 0.0), 1)

    def resolve_self_session(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        by_pid = {
            int(row["pid"]): row for row in rows if isinstance(row.get("pid"), int)
        }
        current = os.getpid()
        visited: set[int] = set()
        while current > 1 and current not in visited:
            visited.add(current)
            row = by_pid.get(current)
            if row is None:
                break
            if is_opencode_command(str(row.get("command") or "")):
                cwd = ""
                try:
                    lsof = subprocess.run(
                        ["lsof", "-a", "-p", str(current), "-d", "cwd", "-Fn"],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=2,
                    )
                    if lsof.returncode == 0:
                        for item in lsof.stdout.splitlines():
                            if item.startswith("n"):
                                cwd = item[1:].strip()
                                break
                except Exception:
                    cwd = ""
                return {
                    "pid": current,
                    "cpu_pct": float(row.get("cpu_pct") or 0),
                    "mem_pct": float(row.get("mem_pct") or 0),
                    "rss_mb": float(row.get("rss_mb") or 0),
                    "elapsed": str(row.get("elapsed") or ""),
                    "elapsed_seconds": int(row.get("elapsed_seconds") or 0),
                    "cwd": cwd,
                }
            current = int(row.get("ppid") or 0)
        return None

    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pcpu=,pmem=,rss=,etime=,tty=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return {
            "sampled": False,
            "opencode_process_count": 0,
            "continue_process_count": 0,
            "max_rss_mb": 0,
            "high_rss": [],
            "self_session": None,
        }
    if result.returncode != 0:
        return {
            "sampled": False,
            "opencode_process_count": 0,
            "continue_process_count": 0,
            "max_rss_mb": 0,
            "high_rss": [],
            "self_session": None,
        }

    rows: list[dict[str, Any]] = []
    rows_by_pid: dict[int, dict[str, Any]] = {}
    opencode_process_count = 0
    continue_process_count = 0
    max_rss_kb = 0
    opencode_rss_total_mb = 0.0
    high_rss: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=7)
        if len(parts) < 8:
            continue
        (
            pid_text,
            ppid_text,
            cpu_text,
            mem_text,
            rss_text,
            elapsed_text,
            tty_text,
            command,
        ) = parts
        lowered = command.lower()
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        try:
            ppid = int(ppid_text)
        except ValueError:
            ppid = 0
        try:
            cpu_pct = float(cpu_text)
        except ValueError:
            cpu_pct = 0.0
        try:
            mem_pct = float(mem_text)
        except ValueError:
            mem_pct = 0.0
        try:
            rss_kb = int(rss_text)
        except ValueError:
            rss_kb = 0
        row = {
            "pid": pid,
            "ppid": ppid,
            "cpu_pct": cpu_pct,
            "mem_pct": mem_pct,
            "rss_mb": round(rss_kb / 1024, 1),
            "elapsed": elapsed_text,
            "elapsed_seconds": parse_elapsed_seconds(elapsed_text),
            "tty": tty_text,
            "command": command,
        }
        rows.append(row)
        rows_by_pid[pid] = row
        if not is_opencode_command(command):
            continue
        opencode_process_count += 1
        opencode_rss_total_mb += round(rss_kb / 1024, 1)
        if "--continue" in lowered:
            continue_process_count += 1
        if rss_kb > max_rss_kb:
            max_rss_kb = rss_kb
        if rss_kb >= 1_000_000:
            command_preview = command.strip()
            if command_preview:
                try:
                    command_preview = shlex.join(shlex.split(command_preview)[:8])
                except ValueError:
                    command_preview = command_preview[:180]
            high_rss.append(
                {
                    "pid": pid,
                    "rss_mb": round(rss_kb / 1024, 1),
                    "elapsed": elapsed_text,
                    "command": command_preview,
                }
            )

    top_footprint_by_pid: dict[int, float] = {}
    try:
        top_result = subprocess.run(
            ["top", "-l", "1", "-stats", "pid,command,mem"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if top_result.returncode == 0:
            for raw_line in top_result.stdout.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                match = re.match(r"^(\d+)\s+(\S+)\s+([0-9.]+\s*[KMGTP](?:B)?)$", line)
                if not match:
                    continue
                pid = int(match.group(1))
                command_name = match.group(2).lower()
                if pid not in rows_by_pid:
                    continue
                if not (
                    "opencode" in command_name
                    or is_opencode_command(str(rows_by_pid[pid].get("command") or ""))
                ):
                    continue
                top_footprint_by_pid[pid] = size_to_mb(match.group(3))
    except Exception:
        top_footprint_by_pid = {}

    max_footprint_mb = 0.0
    high_footprint: list[dict[str, Any]] = []
    for pid, footprint_mb in top_footprint_by_pid.items():
        if footprint_mb > max_footprint_mb:
            max_footprint_mb = footprint_mb
        if footprint_mb >= 1024:
            row = rows_by_pid.get(pid, {})
            high_footprint.append(
                {
                    "pid": pid,
                    "footprint_mb": round(footprint_mb, 1),
                    "rss_mb": float(row.get("rss_mb") or 0.0),
                    "elapsed": str(row.get("elapsed") or ""),
                    "command": str(row.get("command") or "")[:180],
                }
            )

    opencode_footprint_total_mb = round(sum(top_footprint_by_pid.values()), 1)

    swap_total_mb = 0.0
    swap_used_mb = 0.0
    swap_free_mb = 0.0
    try:
        swap_result = subprocess.run(
            ["sysctl", "vm.swapusage"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if swap_result.returncode == 0:
            text = swap_result.stdout
            total_match = re.search(r"total\s*=\s*([0-9.]+\s*[KMGTP](?:B)?)", text)
            used_match = re.search(r"used\s*=\s*([0-9.]+\s*[KMGTP](?:B)?)", text)
            free_match = re.search(r"free\s*=\s*([0-9.]+\s*[KMGTP](?:B)?)", text)
            swap_total_mb = size_to_mb(total_match.group(1) if total_match else "")
            swap_used_mb = size_to_mb(used_match.group(1) if used_match else "")
            swap_free_mb = size_to_mb(free_match.group(1) if free_match else "")
    except Exception:
        swap_total_mb = 0.0
        swap_used_mb = 0.0
        swap_free_mb = 0.0

    self_session = resolve_self_session(rows)
    pressure_cfg_any = (
        config.get("globalProcessPressure") if isinstance(config, dict) else {}
    )
    pressure_cfg = pressure_cfg_any if isinstance(pressure_cfg_any, dict) else {}
    operator = (
        "all"
        if str(pressure_cfg.get("selfSeverityOperator") or "").strip().lower() == "all"
        else "any"
    )
    high_cpu = float(pressure_cfg.get("selfHighCpuPct") or 100)
    high_rss_threshold = float(pressure_cfg.get("selfHighRssMb") or 10240)
    high_elapsed_seconds = duration_threshold_seconds(
        pressure_cfg.get("selfHighElapsed") or "5h"
    )
    high_label = str(pressure_cfg.get("selfHighLabel") or "HIGH").strip() or "HIGH"
    low_label = str(pressure_cfg.get("selfLowLabel") or "LOW").strip() or "LOW"

    conditions: list[bool] = []
    cpu_match = bool(
        self_session
        and high_cpu > 0
        and float(self_session.get("cpu_pct") or 0) >= high_cpu
    )
    rss_match = bool(
        self_session
        and high_rss_threshold > 0
        and float(self_session.get("rss_mb") or 0) >= high_rss_threshold
    )
    elapsed_match = bool(
        self_session
        and high_elapsed_seconds > 0
        and int(self_session.get("elapsed_seconds") or 0) >= high_elapsed_seconds
    )
    if high_cpu > 0:
        conditions.append(cpu_match)
    if high_rss_threshold > 0:
        conditions.append(rss_match)
    if high_elapsed_seconds > 0:
        conditions.append(elapsed_match)
    is_high = False
    if conditions:
        is_high = all(conditions) if operator == "all" else any(conditions)

    if self_session is not None:
        self_session["severity"] = high_label if is_high else low_label
        self_session["severity_operator"] = operator
        self_session["thresholds"] = {
            "cpu_pct": high_cpu,
            "rss_mb": high_rss_threshold,
            "elapsed_seconds": high_elapsed_seconds,
        }
        self_session["matches"] = {
            "cpu": cpu_match,
            "rss": rss_match,
            "elapsed": elapsed_match,
        }

    return {
        "sampled": True,
        "opencode_process_count": opencode_process_count,
        "continue_process_count": continue_process_count,
        "max_rss_mb": round(max_rss_kb / 1024, 1),
        "opencode_rss_total_mb": round(opencode_rss_total_mb, 1),
        "max_footprint_mb": round(max_footprint_mb, 1),
        "max_pressure_mb": round(max(round(max_rss_kb / 1024, 1), max_footprint_mb), 1),
        "opencode_footprint_total_mb": opencode_footprint_total_mb,
        "high_rss": high_rss[:5],
        "high_footprint": sorted(
            high_footprint,
            key=lambda item: float(item.get("footprint_mb") or 0.0),
            reverse=True,
        )[:5],
        "swap": {
            "total_mb": swap_total_mb,
            "used_mb": swap_used_mb,
            "free_mb": swap_free_mb,
        },
        "self_session": self_session,
    }


# Returns gateway-core hook diagnostics for source and dist artifacts.
def hook_diagnostics(pdir: Path) -> dict[str, Any]:
    src_index = pdir / "src" / "index.ts"
    src_hook_files = [
        pdir / "src" / "hooks" / "autopilot-loop" / "index.ts",
        pdir / "src" / "hooks" / "continuation" / "index.ts",
        pdir / "src" / "hooks" / "safety" / "index.ts",
    ]
    dist_index = pdir / "dist" / "index.js"
    dist_hook_files = [
        pdir / "dist" / "hooks" / "autopilot-loop" / "index.js",
        pdir / "dist" / "hooks" / "continuation" / "index.js",
        pdir / "dist" / "hooks" / "safety" / "index.js",
    ]

    content = ""
    if dist_index.exists():
        try:
            content = dist_index.read_text(encoding="utf-8")
        except OSError:
            content = ""

    autopilot_loop_content = ""
    autopilot_loop_path = pdir / "dist" / "hooks" / "autopilot-loop" / "index.js"
    if autopilot_loop_path.exists():
        try:
            autopilot_loop_content = autopilot_loop_path.read_text(encoding="utf-8")
        except OSError:
            autopilot_loop_content = ""

    continuation_content = ""
    continuation_path = pdir / "dist" / "hooks" / "continuation" / "index.js"
    if continuation_path.exists():
        try:
            continuation_content = continuation_path.read_text(encoding="utf-8")
        except OSError:
            continuation_content = ""

    safety_content = ""
    safety_path = pdir / "dist" / "hooks" / "safety" / "index.js"
    if safety_path.exists():
        try:
            safety_content = safety_path.read_text(encoding="utf-8")
        except OSError:
            safety_content = ""

    return {
        "source_index_exists": src_index.exists(),
        "source_hooks_exist": all(path.exists() for path in src_hook_files),
        "dist_index_exists": dist_index.exists(),
        "dist_hooks_exist": all(path.exists() for path in dist_hook_files),
        "dist_exposes_tool_execute_before": '"tool.execute.before"' in content,
        "dist_exposes_command_execute_before": '"command.execute.before"' in content,
        "dist_exposes_chat_message": '"chat.message"' in content,
        "dist_exposes_messages_transform": '"experimental.chat.messages.transform"'
        in content,
        "dist_autopilot_handles_slashcommand": "tool.execute.before"
        in autopilot_loop_content
        and "slashcommand" in autopilot_loop_content,
        "dist_continuation_handles_session_idle": "session.idle"
        in continuation_content,
        "dist_safety_handles_session_deleted": "session.deleted" in safety_content,
        "dist_safety_handles_session_error": "session.error" in safety_content,
    }


# Resolves effective bun availability with optional deterministic overrides.
def bun_runtime_available() -> bool:
    forced = (
        os.environ.get("MY_OPENCODE_GATEWAY_FORCE_BUN_AVAILABLE", "").strip().lower()
    )
    if forced in {"1", "true", "yes", "on"}:
        return True
    if forced in {"0", "false", "no", "off"}:
        return False
    return shutil.which("bun") is not None


# Resolves active gateway runtime mode and deterministic reason code.
def gateway_runtime_mode(
    *, enabled: bool, bun_available: bool, hooks: dict[str, Any]
) -> dict[str, Any]:
    required_dist_flags = [
        "dist_exposes_tool_execute_before",
        "dist_exposes_command_execute_before",
        "dist_exposes_chat_message",
        "dist_exposes_messages_transform",
        "dist_autopilot_handles_slashcommand",
        "dist_continuation_handles_session_idle",
        "dist_safety_handles_session_deleted",
        "dist_safety_handles_session_error",
    ]
    missing = [flag for flag in required_dist_flags if hooks.get(flag) is not True]
    plugin_ready = (
        enabled
        and bun_available
        and hooks.get("dist_index_exists") is True
        and not missing
    )
    mode = "plugin_gateway" if plugin_ready else "python_command_bridge"
    reason_code = GATEWAY_PLUGIN_READY
    if not enabled:
        reason_code = GATEWAY_PLUGIN_DISABLED
    elif not bun_available:
        reason_code = GATEWAY_PLUGIN_RUNTIME_UNAVAILABLE
    elif not plugin_ready:
        reason_code = GATEWAY_PLUGIN_NOT_READY
    return {
        "mode": mode,
        "reason_code": reason_code,
        "missing_hook_capabilities": missing,
    }


# Returns loop state filtered for active runtime mode semantics.
def mode_loop_state(
    runtime_mode: str, loop_state: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    source = str(loop_state.get("source") or "") if isinstance(loop_state, dict) else ""
    if runtime_mode == "plugin_gateway" and source == "python-command-bridge":
        return None, BRIDGE_STATE_IGNORED_IN_PLUGIN_MODE
    if loop_state:
        return loop_state, LOOP_STATE_AVAILABLE
    return None, "state_missing"


# Computes gateway runtime status payload.
def status_payload(
    config: dict[str, Any],
    home: Path,
    cwd: Path,
    *,
    cleanup_orphans: bool = False,
    orphan_max_age_hours: int = 12,
) -> dict[str, Any]:
    pdir = plugin_dir(home)
    cleanup: dict[str, Any] | None = None
    if cleanup_orphans:
        cleanup_path, changed, reason = cleanup_orphan_loop(
            cwd, max_age_hours=orphan_max_age_hours
        )
        cleanup = {
            "attempted": True,
            "changed": changed,
            "reason": reason,
            "state_path": str(cleanup_path) if cleanup_path else None,
        }
    loop_state = load_gateway_loop_state(cwd)
    enabled = plugin_enabled(config, home)
    bun_available = bun_runtime_available()
    hooks = hook_diagnostics(pdir)
    runtime_mode = gateway_runtime_mode(
        enabled=enabled,
        bun_available=bun_available,
        hooks=hooks,
    )
    filtered_loop_state, loop_state_reason = mode_loop_state(
        runtime_mode["mode"], loop_state
    )
    gateway_entries = gateway_plugin_entries(config, home)
    payload = {
        "result": "PASS",
        "enabled": enabled,
        "plugin_spec": gateway_plugin_spec(home),
        "plugin_entry_count": len(gateway_entries),
        "plugin_entries": gateway_entries,
        "plugin_dir": str(pdir),
        "plugin_dir_exists": pdir.exists(),
        "plugin_dist_exists": (pdir / "dist" / "index.js").exists(),
        "bun_available": bun_available,
        "npm_available": shutil.which("npm") is not None,
        "hook_diagnostics": hooks,
        "runtime_mode": runtime_mode["mode"],
        "runtime_reason_code": runtime_mode["reason_code"],
        "missing_hook_capabilities": runtime_mode["missing_hook_capabilities"],
        "loop_state_path": str(gateway_loop_state_path(cwd)),
        "loop_state": filtered_loop_state,
        "loop_state_reason_code": loop_state_reason,
        "event_audit_enabled": gateway_event_audit_enabled(),
        "event_audit_path": str(gateway_event_audit_path(cwd)),
        "event_audit_exists": gateway_event_audit_path(cwd).exists(),
        "guard_event_counters": gateway_event_counters(cwd),
        "runtime_staleness": runtime_staleness(home),
        "process_pressure": process_pressure(config),
    }
    if cleanup is not None:
        payload["orphan_cleanup"] = cleanup
    return payload


# Ensures Bun/OpenCode compatibility aliases for local file plugins.
def ensure_file_plugin_compat(home: Path, pdir: Path) -> dict[str, Any]:
    if not pdir.exists():
        return {"applied": False, "reason": "plugin_dir_missing"}
    if not bun_runtime_available():
        return {"applied": False, "reason": "bun_unavailable"}

    alias_path = pdir.parent / "gateway-core@latest"
    cache_home = Path(
        os.environ.get("XDG_CACHE_HOME", str(home / ".cache"))
    ).expanduser()
    cache_plugin_path = (
        cache_home
        / "opencode"
        / "node_modules"
        / f"file:{pdir.parent}"
        / "gateway-core"
    )

    alias_path.parent.mkdir(parents=True, exist_ok=True)
    cache_plugin_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.unlink(missing_ok=True)
    cache_plugin_path.unlink(missing_ok=True)
    alias_path.symlink_to(pdir)
    cache_plugin_path.symlink_to(pdir)

    return {
        "applied": True,
        "reason": "ok",
        "latest_alias_path": str(alias_path),
        "cache_alias_path": str(cache_plugin_path),
    }


# Returns hard safety problems that should block non-forced enable.
def enable_safety_problems(status: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if status.get("plugin_dir_exists") is not True:
        problems.append("gateway plugin directory is missing")
    if status.get("plugin_dist_exists") is not True:
        problems.append("gateway plugin dist build is missing")
    if status.get("bun_available") is not True:
        problems.append("bun runtime is unavailable")
    hooks_any = status.get("hook_diagnostics")
    hooks = hooks_any if isinstance(hooks_any, dict) else {}
    required_dist_flags = [
        "dist_exposes_tool_execute_before",
        "dist_exposes_command_execute_before",
        "dist_exposes_chat_message",
        "dist_exposes_messages_transform",
        "dist_autopilot_handles_slashcommand",
        "dist_continuation_handles_session_idle",
        "dist_safety_handles_session_deleted",
        "dist_safety_handles_session_error",
    ]
    missing = [flag for flag in required_dist_flags if hooks.get(flag) is not True]
    if missing:
        problems.append(
            "gateway-core dist is missing required hook capabilities: "
            + ", ".join(missing)
        )
    return problems


# Enables gateway plugin spec in opencode config.
def command_enable(as_json: bool, *, force: bool = False) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, cfg_path = load_config()
    set_plugin_enabled(config, home, True)
    save_config(config, cfg_path)
    payload = status_payload(config, home, Path.cwd())
    payload["compat"] = ensure_file_plugin_compat(home, plugin_dir(home))
    payload["config"] = str(cfg_path)
    problems = enable_safety_problems(payload)
    if problems and not force:
        set_plugin_enabled(config, home, False)
        save_config(config, cfg_path)
        fallback = status_payload(config, home, Path.cwd())
        fallback["result"] = "FAIL"
        fallback["reason_code"] = "gateway_enable_blocked_for_safety"
        fallback["problems"] = problems
        fallback["config"] = str(cfg_path)
        fallback["quick_fixes"] = [
            "install bun and run /gateway doctor",
            "run npm run build in plugin/gateway-core",
            "run /gateway enable --force to bypass safeguard",
        ]
        emit(fallback, as_json=as_json)
        return 1
    emit(payload, as_json=as_json)
    return 0


# Disables gateway plugin spec in opencode config.
def command_disable(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, cfg_path = load_config()
    set_plugin_enabled(config, home, False)
    save_config(config, cfg_path)
    payload = status_payload(config, home, Path.cwd())
    payload["config"] = str(cfg_path)
    emit(payload, as_json=as_json)
    return 0


# Shows gateway plugin status.
def command_status(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, _ = load_config()
    emit(
        status_payload(config, home, Path.cwd(), cleanup_orphans=True),
        as_json=as_json,
    )
    return 0


# Runs gateway plugin diagnostics with quick fixes.
def command_doctor(as_json: bool) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, _ = load_config()
    status = status_payload(config, home, Path.cwd(), cleanup_orphans=True)

    problems: list[str] = []
    warnings: list[str] = []
    if not status["plugin_dir_exists"]:
        warnings.append("gateway plugin directory is missing")
    if not status["plugin_dist_exists"]:
        warnings.append("gateway plugin is not built (dist/index.js missing)")
    if status["enabled"] and not status["plugin_dist_exists"]:
        problems.append("gateway plugin enabled without built dist assets")
    if status["enabled"] and not status["bun_available"]:
        warnings.append("gateway plugin is enabled but bun is not available")
    if status.get("bun_available") is True and status.get("enabled") is not True:
        warnings.append(
            "gateway plugin runtime is available but disabled; enable for plugin-first mode"
        )
    plugin_entry_count = int(status.get("plugin_entry_count") or 0)
    if plugin_entry_count > 1:
        message = "gateway plugin is configured multiple times; keep one canonical file: entry to avoid duplicate hook registration"
        if status.get("enabled") is True:
            problems.append(message)
        else:
            warnings.append(message)

    runtime_stale_any = status.get("runtime_staleness")
    runtime_stale = runtime_stale_any if isinstance(runtime_stale_any, dict) else {}
    if runtime_stale.get("is_stale_running") is True:
        age_minutes = runtime_stale.get("age_minutes")
        warnings.append(
            f"autopilot runtime appears stale in running state ({age_minutes} minutes since update); consider /autopilot pause then /autopilot status"
        )
    blockers_any = runtime_stale.get("blockers")
    blockers = blockers_any if isinstance(blockers_any, list) else []
    if blockers and runtime_stale.get("status") == "running":
        warnings.append(
            "autopilot runtime is running with blockers present; inspect /autopilot report before continuing"
        )

    process_pressure_any = status.get("process_pressure")
    process_pressure_status = (
        process_pressure_any if isinstance(process_pressure_any, dict) else {}
    )
    continue_count = int(process_pressure_status.get("continue_process_count") or 0)
    opencode_count = int(process_pressure_status.get("opencode_process_count") or 0)
    max_rss_mb = float(process_pressure_status.get("max_rss_mb") or 0)
    max_footprint_mb = float(process_pressure_status.get("max_footprint_mb") or 0)
    max_pressure_mb = float(process_pressure_status.get("max_pressure_mb") or 0)
    high_rss_any = process_pressure_status.get("high_rss")
    high_rss = high_rss_any if isinstance(high_rss_any, list) else []
    high_footprint_any = process_pressure_status.get("high_footprint")
    high_footprint = high_footprint_any if isinstance(high_footprint_any, list) else []
    swap_any = process_pressure_status.get("swap")
    swap = swap_any if isinstance(swap_any, dict) else {}
    swap_used_mb = float(swap.get("used_mb") or 0)
    if continue_count >= 3:
        warnings.append(
            f"detected {continue_count} concurrent opencode --continue processes; this can accelerate memory pressure"
        )
        if continue_count >= 5:
            warnings.append(
                "pressure escalation guard may block non-essential reviewer/verifier task escalations until pressure drops"
            )
    if opencode_count >= 8:
        warnings.append(
            f"detected {opencode_count} concurrent opencode-related processes; consider pruning stale sessions"
        )
    if max_pressure_mb >= 1400 or high_rss or high_footprint:
        warnings.append(
            "detected high opencode memory pressure (rss/footprint); capture /gateway status --json baseline and reduce concurrent long-lived sessions"
        )
    if swap_used_mb >= 12_000:
        warnings.append(
            "detected elevated swap usage; memory pressure may persist despite low per-process RSS"
        )
    if max_pressure_mb >= 10240:
        problems.append(
            "detected critical opencode memory pressure (>10GB rss/footprint); current-session continuation should be auto-paused by global process pressure guard"
        )

    counters_any = status.get("guard_event_counters")
    counters = counters_any if isinstance(counters_any, dict) else {}
    critical_events_recent = int(
        counters.get("recent_global_process_pressure_critical_events") or 0
    )
    if critical_events_recent >= 1:
        warnings.append(
            "recent critical global pressure event(s) detected; prioritize recovery flow before opening new long-running sessions"
        )

    remediation_commands: list[str] = []
    manual_emergency_steps: list[str] = []
    if max_pressure_mb >= 10240 or critical_events_recent >= 1:
        remediation_commands = [
            "/gateway status --json",
            "/autopilot pause",
            "/gateway tune memory --json",
            "/gateway recover memory",
        ]
        manual_emergency_steps = [
            "use PID-targeted termination from process_pressure.high_footprint or process_pressure.high_rss entries when recovery commands are insufficient",
        ]

    hooks_any = status.get("hook_diagnostics")
    hooks = hooks_any if isinstance(hooks_any, dict) else {}
    if hooks and hooks.get("source_index_exists") is not True:
        warnings.append("gateway-core source index is missing")
    if hooks and hooks.get("source_hooks_exist") is not True:
        warnings.append("gateway-core source hook files are incomplete")
    if status["plugin_dist_exists"] and hooks:
        required_dist_flags = [
            "dist_exposes_tool_execute_before",
            "dist_exposes_command_execute_before",
            "dist_exposes_chat_message",
            "dist_exposes_messages_transform",
            "dist_autopilot_handles_slashcommand",
            "dist_continuation_handles_session_idle",
            "dist_safety_handles_session_deleted",
            "dist_safety_handles_session_error",
        ]
        missing = [flag for flag in required_dist_flags if hooks.get(flag) is not True]
        if missing:
            problems.append(
                "gateway-core dist is missing required hook capabilities: "
                + ", ".join(missing)
            )

    report = {
        "result": "PASS" if not problems else "FAIL",
        "status": status,
        "warnings": warnings,
        "problems": problems,
        "quick_fixes": [
            "/gateway disable",
            "/gateway enable",
            "run npm run build in plugin/gateway-core",
            "install bun if file plugins must auto-install",
            "dedupe gateway plugin entries in config to a single file:<...>/gateway-core spec",
            "run /autopilot report to inspect blockers and stale runtime status",
        ],
        "remediation_commands": remediation_commands,
        "manual_emergency_steps": manual_emergency_steps,
    }
    emit(report, as_json=as_json)
    return 0 if not problems else 1


def command_tune_memory(as_json: bool, *, apply: bool = False) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, config_path = load_config()
    status = status_payload(config, home, Path.cwd(), cleanup_orphans=True)
    counters_any = status.get("guard_event_counters")
    counters = counters_any if isinstance(counters_any, dict) else {}
    process_any = status.get("process_pressure")
    process = process_any if isinstance(process_any, dict) else {}

    warnings_count = int(counters.get("recent_context_warnings") or 0)
    compactions_count = int(counters.get("recent_compactions") or 0)
    global_pressure_count = int(
        counters.get("recent_global_process_pressure_warnings") or 0
    )
    global_pressure_critical_count = int(
        counters.get("recent_global_process_pressure_critical_events") or 0
    )
    continue_count = int(process.get("continue_process_count") or 0)
    max_rss_mb = float(process.get("max_rss_mb") or 0)
    max_pressure_mb = float(process.get("max_pressure_mb") or max_rss_mb)
    swap_any = process.get("swap")
    swap = swap_any if isinstance(swap_any, dict) else {}
    swap_used_mb = float(swap.get("used_mb") or 0)
    opencode_total_pressure_mb = float(
        process.get("opencode_footprint_total_mb")
        or process.get("opencode_rss_total_mb")
        or 0
    )
    audit_enabled = status.get("event_audit_enabled") is True

    current = {
        "contextWindowMonitor": config.get("contextWindowMonitor", {}),
        "preemptiveCompaction": config.get("preemptiveCompaction", {}),
        "globalProcessPressure": config.get("globalProcessPressure", {}),
        "pressureEscalationGuard": config.get("pressureEscalationGuard", {}),
        "memoryRecovery": config.get("memoryRecovery", {}),
    }
    recommended = {
        "contextWindowMonitor": {
            "warningThreshold": 0.72,
            "reminderCooldownToolCalls": 14,
            "minTokenDeltaForReminder": 30000,
            "defaultContextLimitTokens": 128000,
            "guardMarkerMode": "both",
            "guardVerbosity": "normal",
            "maxSessionStateEntries": 512,
        },
        "preemptiveCompaction": {
            "warningThreshold": 0.8,
            "compactionCooldownToolCalls": 12,
            "minTokenDeltaForCompaction": 40000,
            "defaultContextLimitTokens": 128000,
            "guardMarkerMode": "both",
            "guardVerbosity": "normal",
            "maxSessionStateEntries": 512,
        },
        "globalProcessPressure": {
            "enabled": True,
            "checkCooldownToolCalls": 2,
            "reminderCooldownToolCalls": 6,
            "criticalReminderCooldownToolCalls": 10,
            "criticalEscalationWindowToolCalls": 25,
            "criticalPauseAfterEvents": 1,
            "criticalEscalationAfterEvents": 3,
            "warningContinueSessions": 3,
            "warningOpencodeProcesses": 7,
            "warningMaxRssMb": 1400,
            "criticalMaxRssMb": 10240,
            "autoPauseOnCritical": True,
            "notifyOnCritical": True,
            "guardMarkerMode": "both",
            "guardVerbosity": "normal",
            "maxSessionStateEntries": 1024,
        },
        "pressureEscalationGuard": {
            "enabled": True,
            "maxContinueBeforeBlock": 5,
            "blockedSubagentTypes": [
                "reviewer",
                "verifier",
                "explore",
                "librarian",
                "general",
            ],
            "allowPromptPatterns": [
                "blocker",
                "critical",
                "sev0",
                "sev1",
                "check failed",
                "pressure-override",
            ],
        },
        "memoryRecovery": {
            "candidateMinFootprintMb": 4000,
            "candidateMinRssMb": 1400,
            "forceKillMinPressureMb": 12000,
            "aggregateEnabled": True,
            "aggregateMaxPressureMb": 40960,
            "aggregateCandidateMinFootprintMb": 5000,
            "aggregateCandidateMinRssMb": 1800,
            "aggregateRequireSwapUsedMb": 12000,
            "aggregateRequireContinueSessions": 6,
            "aggregateBatchSize": 1,
            "autoContinuePromptOnResume": True,
            "notificationsEnabled": True,
            "notifyBeforeRecovery": True,
            "notifyAfterRecovery": True,
            "criticalPressureMb": 10240,
            "criticalSwapUsedMb": 12000,
        },
    }
    rationale: list[str] = [
        "keep guard markers trigger-only to avoid steady-state noise",
        "use dual marker mode for Nerd Font + plain fallback readability",
        "cap per-session state maps to limit long-runtime memory growth",
    ]
    if not audit_enabled:
        rationale.append(
            "event audit is disabled; recent trigger counters may be incomplete"
        )
    if warnings_count >= 5:
        rationale.append(
            "high warning frequency in recent window; increase reminder cooldown or token delta"
        )
    if compactions_count >= 3:
        rationale.append(
            "frequent compactions in recent window; increase compaction cooldown and minimum token delta"
        )
    if global_pressure_count >= 3:
        rationale.append(
            "global process pressure repeatedly hit recent thresholds; many concurrent sessions are saturating memory"
        )
    if global_pressure_critical_count >= 1:
        rationale.append(
            "critical global process pressure observed (>10GB RSS); continuation auto-pause should activate for the triggering current session"
        )
    if continue_count >= 3:
        rationale.append(
            "multiple concurrent --continue sessions detected; prune stale sessions to reduce pressure"
        )
    if max_pressure_mb >= 10240:
        rationale.append(
            "max opencode pressure is above 10GB now; expect immediate critical guard behavior and session-level continuation pause"
        )
    if swap_used_mb >= 12_000:
        rationale.append(
            "swap usage is elevated; process RSS can look low while memory pressure remains critical"
        )
    if opencode_total_pressure_mb >= 40_960 and continue_count >= 6:
        rationale.append(
            "aggregate opencode pressure is high despite no single process crossing critical threshold; aggregate recovery candidates should be considered"
        )

    payload = {
        "result": "PASS",
        "profile": "memory-balanced",
        "mode": "apply" if apply else "report",
        "status_snapshot": {
            "runtime_mode": status.get("runtime_mode"),
            "process_pressure": process,
            "guard_event_counters": counters,
        },
        "current": current,
        "recommended": recommended,
        "rationale": rationale,
        "next_steps": [
            "apply recommended values under contextWindowMonitor and preemptiveCompaction",
            "run /gateway status --json and /gateway doctor --json",
            "collect 20-30 minute baseline with MY_OPENCODE_GATEWAY_EVENT_AUDIT=1",
            "optionally set MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES and MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS for rotated audit retention",
        ],
    }
    if apply:
        applied_sections: list[str] = []
        for section, values in recommended.items():
            current_section = config.get(section)
            merged = dict(current_section) if isinstance(current_section, dict) else {}
            merged.update(values)
            config[section] = merged
            applied_sections.append(section)
        save_config(config, config_path)
        payload["applied"] = {
            "config_path": str(config_path),
            "sections": applied_sections,
        }
    emit(payload, as_json=as_json)
    return 0


def command_recover_memory(
    as_json: bool,
    *,
    apply: bool = False,
    resume: bool = False,
    compress: bool = False,
    continue_prompt: bool = False,
    force_kill: bool = False,
) -> int:
    def normalize_tty(value: str) -> str:
        text = str(value or "").strip()
        if text.startswith("/dev/"):
            return text.replace("/dev/", "", 1)
        return text

    def pid_ttys(pids: list[int]) -> dict[int, str]:
        if not pids:
            return {}
        try:
            proc = subprocess.run(
                ["ps", "-o", "pid=,tty=", "-p", ",".join(str(pid) for pid in pids)],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
        except Exception:
            return {}
        if proc.returncode != 0:
            return {}
        mapping: dict[int, str] = {}
        for raw in proc.stdout.splitlines():
            parts = raw.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            mapping[pid] = normalize_tty(parts[1])
        return mapping

    def tmux_panes_by_tty() -> dict[str, dict[str, Any]]:
        try:
            proc = subprocess.run(
                [
                    "tmux",
                    "list-panes",
                    "-a",
                    "-F",
                    "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_tty}\t#{pane_dead}\t#{pane_current_command}\t#{pane_title}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
        except Exception:
            return {}
        if proc.returncode != 0:
            return {}
        mapping: dict[str, dict[str, Any]] = {}
        for raw in proc.stdout.splitlines():
            cols = raw.split("\t")
            if len(cols) < 8:
                continue
            tty = normalize_tty(cols[4])
            if not tty:
                continue
            mapping[tty] = {
                "session_name": cols[0],
                "window_index": cols[1],
                "pane_index": cols[2],
                "pane_id": cols[3],
                "pane_tty": cols[4],
                "pane_dead": cols[5],
                "pane_current_command": cols[6],
                "pane_title": cols[7],
            }
        return mapping

    def pane_is_safe(pane: dict[str, Any]) -> bool:
        dead = str(pane.get("pane_dead") or "").strip()
        command = str(pane.get("pane_current_command") or "").strip().lower()
        safe_commands = {"bash", "zsh", "sh", "fish", "login", "tmux"}
        return dead == "0" and command in safe_commands

    def send_to_pane(pane_id: str, text: str) -> bool:
        try:
            proc = subprocess.run(
                ["tmux", "send-keys", "-t", pane_id, text, "C-m"],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
            return proc.returncode == 0
        except Exception:
            return False

    def notify_user(title: str, message: str, subtitle: str = "") -> bool:
        if sys.platform != "darwin":
            return False
        safe_title = title.replace('"', "'")
        safe_message = message.replace('"', "'")
        safe_subtitle = subtitle.replace('"', "'")
        script = f'display notification "{safe_message}" with title "{safe_title}"' + (
            f' subtitle "{safe_subtitle}"' if safe_subtitle else ""
        )
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
            return proc.returncode == 0
        except Exception:
            return False

    def send_ctrl_c(pane_id: str) -> bool:
        try:
            proc = subprocess.run(
                ["tmux", "send-keys", "-t", pane_id, "C-c"],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
            return proc.returncode == 0
        except Exception:
            return False

    def pane_current_command(pane_id: str) -> str:
        try:
            proc = subprocess.run(
                [
                    "tmux",
                    "display-message",
                    "-p",
                    "-t",
                    pane_id,
                    "#{pane_current_command}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        return proc.stdout.strip().lower()

    def pid_process_context(pids: list[int]) -> dict[int, dict[str, str]]:
        if not pids:
            return {}
        try:
            proc = subprocess.run(
                [
                    "ps",
                    "eww",
                    "-o",
                    "pid=,command=",
                    "-p",
                    ",".join(str(pid) for pid in pids),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=6,
            )
        except Exception:
            return {}
        if proc.returncode != 0:
            return {}
        output: dict[int, dict[str, str]] = {}
        for raw in proc.stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            record: dict[str, str] = {}
            for key in ("PWD", "TMUX_PANE"):
                match = re.search(rf"\b{key}=([^\s]+)", parts[1])
                if match:
                    record[key.lower()] = match.group(1)
            output[pid] = record
        return output

    session_cache: dict[str, str] = {}

    def extract_session_id(text: str) -> str:
        match = re.search(r"\b(ses_[A-Za-z0-9]+)\b", str(text or ""))
        return match.group(1) if match else ""

    pane_session_cache_path = (
        Path(os.environ.get("HOME") or str(Path.home())).expanduser()
        / ".config"
        / "opencode"
        / "my_opencode"
        / "runtime"
        / "gateway-pane-session-cache.json"
    )

    def load_pane_session_cache() -> dict[str, str]:
        if not pane_session_cache_path.exists():
            return {}
        try:
            payload = json.loads(pane_session_cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        rows_any = payload.get("panes")
        rows = rows_any if isinstance(rows_any, dict) else {}
        out: dict[str, str] = {}
        for pane_key, session_value in rows.items():
            pane_text = str(pane_key or "").strip()
            session_text = str(session_value or "").strip()
            if pane_text and session_text.startswith("ses_"):
                out[pane_text] = session_text
        return out

    def save_pane_session_cache(cache: dict[str, str]) -> None:
        pane_session_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "panes": cache,
        }
        pane_session_cache_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    pane_session_cache = load_pane_session_cache()

    def latest_session_for_cwd(cwd: str) -> str:
        value = str(cwd or "").strip()
        if not value:
            return ""
        if value in session_cache:
            return session_cache[value]
        try:
            proc = subprocess.run(
                ["opencode", "session", "list", "--format", "json", "-n", "1"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                cwd=value,
            )
        except Exception:
            session_cache[value] = ""
            return ""
        if proc.returncode != 0:
            session_cache[value] = ""
            return ""
        try:
            payload = json.loads(proc.stdout)
        except Exception:
            session_cache[value] = ""
            return ""
        entries = payload if isinstance(payload, list) else []
        if not entries or not isinstance(entries[0], dict):
            session_cache[value] = ""
            return ""
        session_id = str(entries[0].get("id") or "")
        session_cache[value] = session_id
        return session_id

    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    config, _ = load_config()
    recovery_any = config.get("memoryRecovery") if isinstance(config, dict) else {}
    recovery = recovery_any if isinstance(recovery_any, dict) else {}

    def parse_float(raw: Any, default: float) -> float:
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
        return default

    def parse_int(raw: Any, default: int) -> int:
        try:
            value = int(raw)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
        return default

    candidate_min_footprint_mb = parse_float(
        recovery.get("candidateMinFootprintMb"), 4000.0
    )
    candidate_min_rss_mb = parse_float(recovery.get("candidateMinRssMb"), 1400.0)
    force_kill_min_pressure_mb = parse_float(
        recovery.get("forceKillMinPressureMb"), 12000.0
    )
    auto_continue_prompt = recovery.get("autoContinuePromptOnResume") is True
    continue_prompt_enabled = continue_prompt or auto_continue_prompt
    notifications_enabled = recovery.get("notificationsEnabled") is not False
    notify_before_recovery = recovery.get("notifyBeforeRecovery") is not False
    notify_after_recovery = recovery.get("notifyAfterRecovery") is not False
    aggregate_enabled = recovery.get("aggregateEnabled") is not False
    aggregate_max_pressure_mb = parse_float(
        recovery.get("aggregateMaxPressureMb"), 40_960.0
    )
    aggregate_candidate_min_footprint_mb = parse_float(
        recovery.get("aggregateCandidateMinFootprintMb"), 5_000.0
    )
    aggregate_candidate_min_rss_mb = parse_float(
        recovery.get("aggregateCandidateMinRssMb"), 1_800.0
    )
    aggregate_require_swap_used_mb = parse_float(
        recovery.get("aggregateRequireSwapUsedMb"), 12_000.0
    )
    aggregate_require_continue_sessions = parse_int(
        recovery.get("aggregateRequireContinueSessions"), 6
    )
    aggregate_batch_size = max(1, parse_int(recovery.get("aggregateBatchSize"), 1))

    status = status_payload(config, home, Path.cwd(), cleanup_orphans=False)
    process_any = status.get("process_pressure")
    process = process_any if isinstance(process_any, dict) else {}
    max_pressure_now_mb = float(
        process.get("max_pressure_mb") or process.get("max_rss_mb") or 0
    )
    swap_any = process.get("swap") if isinstance(process, dict) else {}
    swap = swap_any if isinstance(swap_any, dict) else {}
    swap_used_mb = float(swap.get("used_mb") or 0)
    continue_count = int(process.get("continue_process_count") or 0)
    opencode_total_pressure_mb = float(
        process.get("opencode_footprint_total_mb")
        or process.get("opencode_rss_total_mb")
        or 0
    )

    candidates: list[dict[str, Any]] = []
    candidate_mode = "primary"
    aggregate_trigger = False
    aggregate_reason = ""
    high_footprint_any = process.get("high_footprint")
    high_footprint = high_footprint_any if isinstance(high_footprint_any, list) else []
    for entry in high_footprint:
        if not isinstance(entry, dict):
            continue
        try:
            pid = int(entry.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 1:
            continue
        footprint_mb = float(entry.get("footprint_mb") or 0)
        if footprint_mb < candidate_min_footprint_mb:
            continue
        candidates.append(
            {
                "pid": pid,
                "footprint_mb": footprint_mb,
                "rss_mb": float(entry.get("rss_mb") or 0),
                "elapsed": str(entry.get("elapsed") or ""),
                "command": str(entry.get("command") or ""),
            }
        )

    if not candidates:
        high_rss_any = process.get("high_rss")
        high_rss = high_rss_any if isinstance(high_rss_any, list) else []
        for entry in high_rss:
            if not isinstance(entry, dict):
                continue
            try:
                pid = int(entry.get("pid") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid <= 1:
                continue
            rss_mb = float(entry.get("rss_mb") or 0)
            if rss_mb < candidate_min_rss_mb:
                continue
            candidates.append(
                {
                    "pid": pid,
                    "footprint_mb": 0.0,
                    "rss_mb": rss_mb,
                    "elapsed": str(entry.get("elapsed") or ""),
                    "command": str(entry.get("command") or ""),
                }
            )

    if not candidates and aggregate_enabled:
        aggregate_trigger = (
            opencode_total_pressure_mb >= aggregate_max_pressure_mb
            and swap_used_mb >= aggregate_require_swap_used_mb
            and continue_count >= aggregate_require_continue_sessions
        )
        if aggregate_trigger:
            candidate_mode = "aggregate"
            aggregate_reason = (
                f"opencode_total_pressure_mb={opencode_total_pressure_mb:.1f} "
                f"swap_used_mb={swap_used_mb:.1f} continue_count={continue_count}"
            )
            for entry in high_footprint:
                if not isinstance(entry, dict):
                    continue
                try:
                    pid = int(entry.get("pid") or 0)
                except (TypeError, ValueError):
                    pid = 0
                if pid <= 1:
                    continue
                footprint_mb = float(entry.get("footprint_mb") or 0)
                if footprint_mb < aggregate_candidate_min_footprint_mb:
                    continue
                candidates.append(
                    {
                        "pid": pid,
                        "footprint_mb": footprint_mb,
                        "rss_mb": float(entry.get("rss_mb") or 0),
                        "elapsed": str(entry.get("elapsed") or ""),
                        "command": str(entry.get("command") or ""),
                    }
                )
            if not candidates:
                high_rss_any = process.get("high_rss")
                high_rss = high_rss_any if isinstance(high_rss_any, list) else []
                for entry in high_rss:
                    if not isinstance(entry, dict):
                        continue
                    try:
                        pid = int(entry.get("pid") or 0)
                    except (TypeError, ValueError):
                        pid = 0
                    if pid <= 1:
                        continue
                    rss_mb = float(entry.get("rss_mb") or 0)
                    if rss_mb < aggregate_candidate_min_rss_mb:
                        continue
                    candidates.append(
                        {
                            "pid": pid,
                            "footprint_mb": 0.0,
                            "rss_mb": rss_mb,
                            "elapsed": str(entry.get("elapsed") or ""),
                            "command": str(entry.get("command") or ""),
                        }
                    )

    candidates = sorted(
        candidates,
        key=lambda item: max(
            float(item.get("footprint_mb") or 0), float(item.get("rss_mb") or 0)
        ),
        reverse=True,
    )
    if candidate_mode == "aggregate":
        candidates = candidates[:aggregate_batch_size]

    actions: list[dict[str, Any]] = []
    pids = [int(item.get("pid") or 0) for item in candidates]
    ttys = pid_ttys(pids)
    process_ctx = pid_process_context(pids)
    panes = tmux_panes_by_tty() if resume else {}
    autopilot_pause_attempted = False
    autopilot_pause_ok = False
    if apply:
        autopilot_pause_attempted = True
        pause_script = Path(__file__).resolve().parent / "autopilot_command.py"
        try:
            pause = subprocess.run(
                [sys.executable, str(pause_script), "pause", "--json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
            )
            autopilot_pause_ok = pause.returncode == 0
        except Exception:
            autopilot_pause_ok = False

    for entry in candidates:
        pid = int(entry.get("pid") or 0)
        if pid <= 1:
            continue
        tty = normalize_tty(ttys.get(pid, ""))
        pane = panes.get(tty, {}) if tty else {}
        ctx = process_ctx.get(pid, {})
        cwd = str(ctx.get("pwd") or "")
        tmux_pane_env = str(ctx.get("tmux_pane") or "")
        if resume and not pane and tmux_pane_env:
            pane = {
                "pane_id": tmux_pane_env,
                "pane_dead": "0",
                "pane_current_command": pane_current_command(tmux_pane_env),
            }
        pane_id = str(pane.get("pane_id") or "")
        pane_title = str(pane.get("pane_title") or "")
        session_id = extract_session_id(pane_title)
        session_id_source = "pane_title" if session_id else ""
        if not session_id and pane_id:
            cached_session = str(pane_session_cache.get(pane_id) or "")
            if cached_session:
                session_id = cached_session
                session_id_source = "pane_cache"
        if not session_id:
            session_id = latest_session_for_cwd(cwd)
            session_id_source = "cwd_latest" if session_id else ""
        if pane_id and session_id and session_id_source == "pane_title":
            pane_session_cache[pane_id] = session_id
            save_pane_session_cache(pane_session_cache)
        if not apply:
            actions.append(
                {
                    "pid": pid,
                    "action": "terminate",
                    "result": "planned",
                    "tty": tty or None,
                    "cwd": cwd or None,
                    "session_id": session_id or None,
                    "session_id_source": session_id_source or None,
                    "pane": pane or None,
                    "resume_planned": bool(resume and pane_id),
                    "compress_planned": bool(resume and compress and pane_id),
                }
            )
            continue

        pane_ref = ""
        if pane:
            pane_ref = (
                f"{pane.get('session_name') or '?'}:"
                f"{pane.get('window_index') or '?'}"
                f".{pane.get('pane_index') or '?'}"
            )
        reason_bits = [
            f"pid={pid}",
            f"rss={float(entry.get('rss_mb') or 0):.1f}MB",
            f"footprint={float(entry.get('footprint_mb') or 0):.1f}MB",
            f"pressure={max_pressure_now_mb:.1f}MB",
        ]
        if notifications_enabled and notify_before_recovery:
            before_sent = notify_user(
                "OpenCode Recovery",
                "Graceful recovery starting",
                f"{pane_ref or tty or 'no-pane'} | {' '.join(reason_bits)}",
            )
            actions.append(
                {
                    "pid": pid,
                    "action": "notify_before",
                    "result": "sent" if before_sent else "failed",
                    "pane": pane or None,
                    "tty": tty or None,
                    "session_id": session_id or None,
                    "session_id_source": session_id_source or None,
                }
            )

        interrupted = False
        if pane_id:
            interrupt_action = {
                "pid": pid,
                "action": "interrupt",
                "signal": "CTRL_C",
                "tty": tty or None,
                "cwd": cwd or None,
                "session_id": session_id or None,
                "session_id_source": session_id_source or None,
                "pane": pane or None,
            }
            sent_interrupt = send_ctrl_c(pane_id)
            interrupt_action["sent"] = sent_interrupt
            if sent_interrupt:
                interrupt_deadline = time.time() + 4
                while time.time() < interrupt_deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        interrupted = True
                        break
                    except PermissionError:
                        break
                    time.sleep(0.2)
            interrupt_action["result"] = "interrupted" if interrupted else "still_alive"
            actions.append(interrupt_action)

        if interrupted:
            action = {
                "pid": pid,
                "action": "terminate",
                "signal": "CTRL_C",
                "result": "interrupted",
                "tty": tty or None,
                "cwd": cwd or None,
                "session_id": session_id or None,
                "session_id_source": session_id_source or None,
                "pane": pane or None,
            }
        else:
            try:
                os.kill(pid, signal.SIGTERM)
                action: dict[str, Any] = {
                    "pid": pid,
                    "action": "terminate",
                    "signal": "SIGTERM",
                    "result": "sent",
                    "tty": tty or None,
                    "cwd": cwd or None,
                    "session_id": session_id or None,
                    "session_id_source": session_id_source or None,
                    "pane": pane or None,
                }
            except ProcessLookupError:
                actions.append(
                    {
                        "pid": pid,
                        "action": "terminate",
                        "signal": "SIGTERM",
                        "result": "not_found",
                    }
                )
                continue
            except PermissionError:
                actions.append(
                    {
                        "pid": pid,
                        "action": "terminate",
                        "signal": "SIGTERM",
                        "result": "permission_denied",
                    }
                )
                continue

        terminated = False
        deadline = time.time() + 6
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                terminated = True
                break
            except PermissionError:
                break
            time.sleep(0.2)
        if terminated:
            action["result"] = "terminated"
        else:
            allow_force_kill = (
                force_kill and max_pressure_now_mb >= force_kill_min_pressure_mb
            )
            if allow_force_kill:
                try:
                    os.kill(pid, signal.SIGKILL)
                    action["result"] = "killed"
                    action["signal_escalated"] = "SIGKILL"
                except ProcessLookupError:
                    action["result"] = "terminated"
                except PermissionError:
                    action["result"] = "alive_after_timeout"
                    action["next_step"] = f"kill -9 {pid}"
            else:
                action["result"] = "alive_after_timeout"
                action["next_step"] = f"kill -9 {pid}"
                if force_kill and not allow_force_kill:
                    action["force_kill_skipped_reason"] = (
                        f"max_pressure_mb={max_pressure_now_mb:.1f} below forceKillMinPressureMb={force_kill_min_pressure_mb:.1f}"
                    )

        if resume:
            action["resume_attempted"] = False
            action["compress_attempted"] = False
            if pane_id and action["result"] in {"terminated", "killed", "not_found"}:
                safe_ready = False
                last_cmd = str(pane.get("pane_current_command") or "").strip().lower()
                wait_deadline = time.time() + 8
                while time.time() < wait_deadline:
                    last_cmd = pane_current_command(pane_id)
                    probe = {"pane_dead": "0", "pane_current_command": last_cmd}
                    if pane_is_safe(probe):
                        safe_ready = True
                        break
                    time.sleep(0.4)

                if safe_ready:
                    resume_cmd = (
                        f"opencode --session {session_id}"
                        if session_id
                        else "opencode --continue"
                    )
                    resumed = send_to_pane(pane_id, resume_cmd)
                    action["resume_attempted"] = True
                    action["resume_ok"] = resumed
                    action["resume_command"] = resume_cmd
                    if resumed and pane_id and session_id:
                        pane_session_cache[pane_id] = session_id
                        save_pane_session_cache(pane_session_cache)
                    if resumed and compress:
                        time.sleep(2)
                        cmd_name = pane_current_command(pane_id)
                        if cmd_name == "opencode":
                            compressed = send_to_pane(pane_id, "/compact")
                            action["compress_attempted"] = True
                            action["compress_ok"] = compressed
                        else:
                            action["compress_attempted"] = False
                            action["compress_skipped_reason"] = (
                                f"pane command is '{cmd_name or 'unknown'}'"
                            )
                    if resumed and continue_prompt_enabled:
                        time.sleep(1)
                        cmd_name = pane_current_command(pane_id)
                        if cmd_name == "opencode":
                            continued = send_to_pane(pane_id, "continue")
                            action["continue_prompt_attempted"] = True
                            action["continue_prompt_ok"] = continued
                        else:
                            action["continue_prompt_attempted"] = False
                            action["continue_prompt_skipped_reason"] = (
                                f"pane command is '{cmd_name or 'unknown'}'"
                            )
                else:
                    action["resume_skipped_reason"] = (
                        f"pane_not_ready_for_resume(last_command='{last_cmd or 'unknown'}')"
                    )
            elif not pane_id:
                action["resume_skipped_reason"] = "no_tmux_pane_mapping"
            elif action["result"] not in {"terminated", "killed", "not_found"}:
                action["resume_skipped_reason"] = "target_process_still_alive"

        actions.append(action)

        if notifications_enabled and notify_after_recovery:
            after_summary = (
                f"result={action.get('result')} "
                f"resume={'ok' if action.get('resume_ok') else 'no'} "
                f"session={session_id or '-'}"
            )
            after_sent = notify_user(
                "OpenCode Recovery",
                "Recovery step finished",
                f"{pane_ref or tty or 'no-pane'} | {after_summary}",
            )
            actions.append(
                {
                    "pid": pid,
                    "action": "notify_after",
                    "result": "sent" if after_sent else "failed",
                    "pane": pane or None,
                    "tty": tty or None,
                    "session_id": session_id or None,
                    "session_id_source": session_id_source or None,
                }
            )

    after_status = (
        status_payload(config, home, Path.cwd(), cleanup_orphans=False)
        if apply
        else None
    )

    payload = {
        "result": "PASS",
        "mode": "apply" if apply else "dry_run",
        "options": {
            "resume": resume,
            "compress": compress,
            "continue_prompt": continue_prompt_enabled,
            "force_kill": force_kill,
        },
        "policy": {
            "candidate_min_footprint_mb": candidate_min_footprint_mb,
            "candidate_min_rss_mb": candidate_min_rss_mb,
            "force_kill_min_pressure_mb": force_kill_min_pressure_mb,
            "aggregate_enabled": aggregate_enabled,
            "aggregate_max_pressure_mb": aggregate_max_pressure_mb,
            "aggregate_candidate_min_footprint_mb": aggregate_candidate_min_footprint_mb,
            "aggregate_candidate_min_rss_mb": aggregate_candidate_min_rss_mb,
            "aggregate_require_swap_used_mb": aggregate_require_swap_used_mb,
            "aggregate_require_continue_sessions": aggregate_require_continue_sessions,
            "aggregate_batch_size": aggregate_batch_size,
            "auto_continue_prompt_on_resume": auto_continue_prompt,
            "notifications_enabled": notifications_enabled,
            "notify_before_recovery": notify_before_recovery,
            "notify_after_recovery": notify_after_recovery,
        },
        "status_snapshot": {
            "runtime_mode": status.get("runtime_mode"),
            "process_pressure": process,
            "guard_event_counters": status.get("guard_event_counters"),
        },
        "autopilot_pause": {
            "attempted": autopilot_pause_attempted,
            "ok": autopilot_pause_ok,
        },
        "candidate_mode": candidate_mode,
        "aggregate_trigger": aggregate_trigger,
        "aggregate_reason": aggregate_reason,
        "candidate_count": len(candidates),
        "candidates": candidates[:8],
        "actions": actions,
        "recommended_commands": [
            "/gateway status --json",
            "/gateway doctor --json",
            "/gateway recover memory --apply --force-kill",
        ],
        "next_steps": [
            "run /gateway recover memory --apply when pressure remains critical",
            "resume in impacted pane with opencode --continue",
            "run /gateway recover memory --apply --resume --compress for pane-aware recovery",
        ],
    }
    if after_status is not None:
        payload["post_recovery_snapshot"] = {
            "runtime_mode": after_status.get("runtime_mode"),
            "process_pressure": after_status.get("process_pressure"),
            "guard_event_counters": after_status.get("guard_event_counters"),
        }
    emit(payload, as_json=as_json)
    return 0


def command_recover_memory_watch(
    as_json: bool,
    *,
    apply: bool,
    resume: bool,
    compress: bool,
    continue_prompt: bool,
    force_kill: bool,
    interval_seconds: int,
    max_cycles: int,
) -> int:
    config, _ = load_config()
    recovery_any = config.get("memoryRecovery") if isinstance(config, dict) else {}
    recovery = recovery_any if isinstance(recovery_any, dict) else {}

    def parse_float(raw: Any, default: float) -> float:
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
        return default

    critical_threshold = parse_float(recovery.get("criticalPressureMb"), 10_240.0)
    critical_swap_mb = parse_float(recovery.get("criticalSwapUsedMb"), 12_000.0)
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    runtime_dir = home / ".config" / "opencode" / "my_opencode" / "runtime"
    state_path = runtime_dir / "gateway-protection-state.json"

    def load_state() -> dict[str, Any]:
        if not state_path.exists():
            return {"version": 1, "updated_at": "", "runs": []}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {"version": 1, "updated_at": "", "runs": []}

    def save_state(run_row: dict[str, Any]) -> None:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        state = load_state()
        runs_any = state.get("runs")
        runs = runs_any if isinstance(runs_any, list) else []
        runs.append(run_row)
        state["version"] = 1
        state["updated_at"] = datetime.now(UTC).isoformat()
        state["runs"] = runs[-500:]
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    cycles: list[dict[str, Any]] = []
    cycle_index = 0
    script_path = Path(__file__).resolve()

    while True:
        if max_cycles > 0 and cycle_index >= max_cycles:
            break
        cycle_index += 1
        started_at = datetime.now(UTC).isoformat()
        command = [
            sys.executable,
            str(script_path),
            "recover",
            "memory",
            "--json",
        ]
        if apply:
            command.append("--apply")
        if resume:
            command.append("--resume")
        if compress:
            command.append("--compress")
        if continue_prompt:
            command.append("--continue-prompt")
        if force_kill:
            command.append("--force-kill")
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except Exception as exc:
            row = {
                "cycle": cycle_index,
                "started_at": started_at,
                "result": "error",
                "error": str(exc),
            }
            cycles.append(row)
            if not as_json:
                print(
                    f"watch cycle={cycle_index} result=error error={str(exc)[:120]}",
                    flush=True,
                )
            break

        payload: dict[str, Any] | None = None
        stdout = proc.stdout.strip()
        if stdout:
            try:
                parsed = json.loads(stdout)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = None

        snapshot_any = (
            payload.get("status_snapshot") if isinstance(payload, dict) else {}
        )
        snapshot = snapshot_any if isinstance(snapshot_any, dict) else {}
        process_any = (
            snapshot.get("process_pressure") if isinstance(snapshot, dict) else {}
        )
        process = process_any if isinstance(process_any, dict) else {}
        max_pressure_mb = float(process.get("max_pressure_mb") or 0)
        opencode_total_pressure_mb = float(
            process.get("opencode_footprint_total_mb")
            or process.get("opencode_rss_total_mb")
            or 0
        )
        swap_any = process.get("swap") if isinstance(process, dict) else {}
        swap = swap_any if isinstance(swap_any, dict) else {}
        swap_used_mb = float(swap.get("used_mb") or 0)
        candidate_count = (
            int(payload.get("candidate_count") or 0) if isinstance(payload, dict) else 0
        )
        action_count = (
            len(payload.get("actions") or [])
            if isinstance(payload, dict) and isinstance(payload.get("actions"), list)
            else 0
        )
        aggregate_triggered = (
            bool(payload.get("aggregate_trigger"))
            if isinstance(payload, dict)
            else False
        )
        triggered = (
            candidate_count > 0
            or max_pressure_mb >= critical_threshold
            or swap_used_mb >= critical_swap_mb
            or aggregate_triggered
        )
        row = {
            "cycle": cycle_index,
            "started_at": started_at,
            "returncode": proc.returncode,
            "result": "PASS" if proc.returncode == 0 else "FAIL",
            "triggered": triggered,
            "max_pressure_mb": max_pressure_mb,
            "opencode_total_pressure_mb": opencode_total_pressure_mb,
            "swap_used_mb": swap_used_mb,
            "candidate_count": candidate_count,
            "action_count": action_count,
            "aggregate_trigger": aggregate_triggered,
        }
        if isinstance(payload, dict):
            row["mode"] = payload.get("mode")
            actions_any = payload.get("actions")
            if isinstance(actions_any, list) and actions_any:
                row["actions_preview"] = actions_any[:3]
        if proc.returncode != 0 and proc.stderr.strip():
            row["stderr"] = proc.stderr.strip()[:400]
        cycles.append(row)
        save_state(row)

        if not as_json:
            print(
                "watch"
                f" cycle={cycle_index}"
                f" result={row['result']}"
                f" triggered={'yes' if triggered else 'no'}"
                f" pressure_mb={max_pressure_mb:.1f}"
                f" swap_mb={swap_used_mb:.1f}"
                f" candidates={candidate_count}"
                f" actions={action_count}",
                flush=True,
            )

        if proc.returncode != 0:
            break
        if max_cycles > 0 and cycle_index >= max_cycles:
            break
        time.sleep(max(1, interval_seconds))

    report = {
        "result": "PASS"
        if cycles and all(item.get("result") == "PASS" for item in cycles)
        else "FAIL",
        "mode": "watch",
        "state_path": str(state_path),
        "options": {
            "apply": apply,
            "resume": resume,
            "compress": compress,
            "continue_prompt": continue_prompt,
            "force_kill": force_kill,
            "interval_seconds": interval_seconds,
            "max_cycles": max_cycles,
            "critical_pressure_mb": critical_threshold,
            "critical_swap_mb": critical_swap_mb,
        },
        "cycle_count": len(cycles),
        "cycles": cycles,
    }
    emit(report, as_json=as_json)
    return 0 if report["result"] == "PASS" else 1


def command_protection(
    as_json: bool,
    action: str,
    *,
    interval_seconds: int,
    max_cycles: int,
    limit: int,
    clear_cache: bool,
) -> int:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    label = "com.my_opencode.gateway-protection"
    launch_dir = home / "Library" / "LaunchAgents"
    plist_path = launch_dir / f"{label}.plist"
    log_dir = home / ".config" / "opencode" / "my_opencode" / "logs"
    stdout_log = log_dir / "gateway-protection.stdout.log"
    stderr_log = log_dir / "gateway-protection.stderr.log"
    runtime_state = (
        home
        / ".config"
        / "opencode"
        / "my_opencode"
        / "runtime"
        / "gateway-protection-state.json"
    )
    pane_cache_path = (
        home
        / ".config"
        / "opencode"
        / "my_opencode"
        / "runtime"
        / "gateway-pane-session-cache.json"
    )

    def read_report_rows() -> list[dict[str, Any]]:
        if not runtime_state.exists():
            return []
        try:
            payload = json.loads(runtime_state.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows_any = payload.get("runs") if isinstance(payload, dict) else []
        rows = rows_any if isinstance(rows_any, list) else []
        output: list[dict[str, Any]] = []
        for item in rows:
            if isinstance(item, dict):
                output.append(item)
        return output

    def read_pane_cache() -> dict[str, str]:
        if not pane_cache_path.exists():
            return {}
        try:
            payload = json.loads(pane_cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        panes_any = payload.get("panes") if isinstance(payload, dict) else {}
        panes = panes_any if isinstance(panes_any, dict) else {}
        out: dict[str, str] = {}
        for pane_id, session_id in panes.items():
            pane_text = str(pane_id or "").strip()
            session_text = str(session_id or "").strip()
            if pane_text and session_text.startswith("ses_"):
                out[pane_text] = session_text
        return out

    def is_loaded() -> bool:
        proc = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=6,
        )
        return proc.returncode == 0

    if action == "status":
        payload = {
            "result": "PASS",
            "label": label,
            "plist_path": str(plist_path),
            "plist_exists": plist_path.exists(),
            "loaded": is_loaded(),
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "state_path": str(runtime_state),
            "state_exists": runtime_state.exists(),
            "pane_cache_path": str(pane_cache_path),
            "pane_cache_exists": pane_cache_path.exists(),
        }
        emit(payload, as_json=as_json)
        return 0

    if action == "cache":
        if clear_cache:
            pane_cache_path.parent.mkdir(parents=True, exist_ok=True)
            pane_cache_path.write_text(
                json.dumps(
                    {"updated_at": datetime.now(UTC).isoformat(), "panes": {}},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        panes = read_pane_cache()
        payload = {
            "result": "PASS",
            "label": label,
            "action": "cache",
            "cleared": clear_cache,
            "path": str(pane_cache_path),
            "entry_count": len(panes),
            "panes": panes,
        }
        emit(payload, as_json=as_json)
        return 0

    if action == "report":
        rows = read_report_rows()
        n = max(1, limit)
        tail = rows[-n:]
        triggered_rows = [item for item in tail if item.get("triggered")]
        payload = {
            "result": "PASS",
            "label": label,
            "action": "report",
            "loaded": is_loaded(),
            "state_path": str(runtime_state),
            "state_exists": runtime_state.exists(),
            "total_rows": len(rows),
            "returned_rows": len(tail),
            "triggered_rows": len(triggered_rows),
            "rows": tail,
        }
        emit(payload, as_json=as_json)
        return 0

    if action == "disable":
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
        payload = {
            "result": "PASS",
            "label": label,
            "action": "disable",
            "loaded": is_loaded(),
            "plist_path": str(plist_path),
        }
        emit(payload, as_json=as_json)
        return 0

    if action == "enable":
        launch_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        script_path = Path(__file__).resolve()
        max_cycles_args = []
        if max_cycles > 0:
            max_cycles_args = [
                "    <string>--max-cycles</string>",
                f"    <string>{max_cycles}</string>",
            ]
        program_lines = [
            "    <string>python3</string>",
            f"    <string>{script_path}</string>",
            "    <string>recover</string>",
            "    <string>memory</string>",
            "    <string>--watch</string>",
            "    <string>--apply</string>",
            "    <string>--resume</string>",
            "    <string>--compress</string>",
            "    <string>--continue-prompt</string>",
            "    <string>--force-kill</string>",
            "    <string>--interval-seconds</string>",
            f"    <string>{max(1, interval_seconds)}</string>",
            *max_cycles_args,
            "    <string>--json</string>",
        ]
        plist = "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
                '<plist version="1.0">',
                "<dict>",
                "  <key>Label</key>",
                f"  <string>{label}</string>",
                "  <key>ProgramArguments</key>",
                "  <array>",
                *program_lines,
                "  </array>",
                "  <key>EnvironmentVariables</key>",
                "  <dict>",
                "    <key>MY_OPENCODE_GATEWAY_EVENT_AUDIT</key>",
                "    <string>1</string>",
                "    <key>MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES</key>",
                "    <string>524288</string>",
                "    <key>MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS</key>",
                "    <string>5</string>",
                "    <key>PATH</key>",
                f"    <string>{os.environ.get('PATH', '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')}</string>",
                "  </dict>",
                "  <key>RunAtLoad</key>",
                "  <true/>",
                "  <key>KeepAlive</key>",
                "  <true/>",
                "  <key>StandardOutPath</key>",
                f"  <string>{stdout_log}</string>",
                "  <key>StandardErrorPath</key>",
                f"  <string>{stderr_log}</string>",
                "</dict>",
                "</plist>",
                "",
            ]
        )
        plist_path.write_text(plist, encoding="utf-8")
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
        bootstrap = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
        if bootstrap.returncode == 0:
            try:
                subprocess.run(
                    ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=8,
                )
            except subprocess.TimeoutExpired:
                pass
        payload = {
            "result": "PASS" if bootstrap.returncode == 0 else "FAIL",
            "label": label,
            "action": "enable",
            "plist_path": str(plist_path),
            "loaded": is_loaded(),
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "bootstrap_returncode": bootstrap.returncode,
            "bootstrap_stderr": bootstrap.stderr.strip()[:300],
        }
        emit(payload, as_json=as_json)
        return 0 if bootstrap.returncode == 0 else 1

    return usage()


# Dispatches gateway command subcommands.
def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = False
    force = False
    apply = False
    resume = False
    compress = False
    continue_prompt = False
    force_kill = False
    watch = False
    interval_seconds = 20
    max_cycles = 0
    limit = 20
    clear_cache = False
    if "--json" in args:
        args.remove("--json")
        as_json = True
    if "--force" in args:
        args.remove("--force")
        force = True
    if "--apply" in args:
        args.remove("--apply")
        apply = True
    if "--resume" in args:
        args.remove("--resume")
        resume = True
    if "--compress" in args:
        args.remove("--compress")
        compress = True
    if "--continue-prompt" in args:
        args.remove("--continue-prompt")
        continue_prompt = True
    if "--force-kill" in args:
        args.remove("--force-kill")
        force_kill = True
    if "--clear" in args:
        args.remove("--clear")
        clear_cache = True
    if "--watch" in args:
        args.remove("--watch")
        watch = True
    if "--interval-seconds" in args:
        idx = args.index("--interval-seconds")
        if idx + 1 >= len(args):
            return usage()
        value = args[idx + 1]
        del args[idx : idx + 2]
        try:
            interval_seconds = max(1, int(value))
        except ValueError:
            return usage()
    if "--max-cycles" in args:
        idx = args.index("--max-cycles")
        if idx + 1 >= len(args):
            return usage()
        value = args[idx + 1]
        del args[idx : idx + 2]
        try:
            max_cycles = max(0, int(value))
        except ValueError:
            return usage()
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 >= len(args):
            return usage()
        value = args[idx + 1]
        del args[idx : idx + 2]
        try:
            limit = max(1, int(value))
        except ValueError:
            return usage()
    if not args:
        return command_status(as_json)
    cmd = args.pop(0)
    if cmd in {"help", "--help", "-h"}:
        return usage()
    if cmd == "tune":
        if len(args) == 1 and args[0] == "memory":
            return command_tune_memory(as_json, apply=apply)
        return usage()
    if cmd == "recover":
        if len(args) == 1 and args[0] == "memory":
            if watch:
                return command_recover_memory_watch(
                    as_json,
                    apply=apply,
                    resume=resume,
                    compress=compress,
                    continue_prompt=continue_prompt,
                    force_kill=force_kill,
                    interval_seconds=interval_seconds,
                    max_cycles=max_cycles,
                )
            return command_recover_memory(
                as_json,
                apply=apply,
                resume=resume,
                compress=compress,
                continue_prompt=continue_prompt,
                force_kill=force_kill,
            )
        return usage()
    if cmd == "protection":
        if len(args) != 1:
            return usage()
        action = args[0]
        if action not in {"status", "enable", "disable", "report", "cache"}:
            return usage()
        return command_protection(
            as_json,
            action,
            interval_seconds=interval_seconds,
            max_cycles=max_cycles,
            limit=limit,
            clear_cache=clear_cache,
        )
    if args:
        return usage()
    if cmd == "status":
        return command_status(as_json)
    if cmd == "enable":
        return command_enable(as_json, force=force)
    if cmd == "disable":
        return command_disable(as_json)
    if cmd == "doctor":
        return command_doctor(as_json)
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
