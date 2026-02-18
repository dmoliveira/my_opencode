#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, TextIO


DEFAULT_REASON_CODES = {"long_turn_warning"}


def default_audit_path(cwd: Path) -> Path:
    raw = os.environ.get("MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return cwd / ".opencode" / "gateway-events.jsonl"


def coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def open_and_seek(path: Path, *, from_start: bool) -> tuple[TextIO, int]:
    handle = path.open("r", encoding="utf-8", errors="replace")
    if from_start:
        return handle, 0
    handle.seek(0, os.SEEK_END)
    return handle, int(handle.tell())


def iter_lines(
    path: Path, *, follow: bool, from_start: bool, poll_interval: float
) -> Iterable[str]:
    handle, _ = open_and_seek(path, from_start=from_start)
    try:
        while True:
            line = handle.readline()
            if line:
                yield line
                continue
            if not follow:
                break
            time.sleep(max(0.1, poll_interval))
    finally:
        handle.close()


def build_alert(payload: dict[str, object], path: Path) -> dict[str, object]:
    return {
        "kind": "turn_watch_alert",
        "reason_code": str(payload.get("reason_code") or ""),
        "ts": str(
            payload.get("ts") or payload.get("timestamp") or payload.get("time") or ""
        ),
        "session_id": str(payload.get("session_id") or ""),
        "elapsed_ms": coerce_int(payload.get("elapsed_ms")),
        "warning_threshold_ms": coerce_int(payload.get("warning_threshold_ms")),
        "turn_started_at": str(payload.get("turn_started_at") or ""),
        "source_path": str(path),
    }


def emit_alert(alert: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(alert, separators=(",", ":")), flush=True)
        return
    print(
        "ALERT"
        f" reason={alert.get('reason_code') or ''}"
        f" ts={alert.get('ts') or ''}"
        f" session={alert.get('session_id') or ''}"
        f" elapsed_ms={alert.get('elapsed_ms') if alert.get('elapsed_ms') is not None else ''}"
        f" threshold_ms={alert.get('warning_threshold_ms') if alert.get('warning_threshold_ms') is not None else ''}"
        f" turn_started_at={alert.get('turn_started_at') or ''}",
        flush=True,
    )


def parse_headers(entries: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in entries:
        text = raw.strip()
        if not text:
            continue
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        headers[key] = value
    return headers


def send_webhook(
    alert: dict[str, object],
    *,
    webhook_url: str,
    timeout_s: float,
    headers: dict[str, str],
) -> tuple[bool, str]:
    payload = json.dumps(alert, separators=(",", ":")).encode("utf-8")
    request_headers = {
        "content-type": "application/json",
        "user-agent": "my-opencode-gateway-turn-watch/1.0",
        **headers,
    }
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.5, timeout_s)) as response:
            status = int(getattr(response, "status", 200))
            if 200 <= status < 300:
                return True, ""
            return False, f"non-2xx status={status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_error status={exc.code}"
    except urllib.error.URLError as exc:
        return False, f"url_error reason={exc.reason}"
    except TimeoutError:
        return False, "timeout"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream simplified long-turn alerts from gateway event audit JSONL.",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Path to gateway-events.jsonl (defaults to MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH or .opencode/gateway-events.jsonl)",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Follow file for new alerts (tail -f behavior).",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Read from beginning instead of end when starting.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds when following (default: 1.0).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit alerts as compact JSON lines.",
    )
    parser.add_argument(
        "--reason-code",
        action="append",
        default=[],
        help="Reason code filter (repeatable). Defaults to long_turn_warning.",
    )
    parser.add_argument(
        "--min-elapsed-ms",
        type=int,
        default=0,
        help="Minimum elapsed_ms required to emit an alert.",
    )
    parser.add_argument(
        "--webhook-url",
        default="",
        help="Optional HTTPS endpoint to POST each emitted alert as JSON.",
    )
    parser.add_argument(
        "--webhook-timeout-s",
        type=float,
        default=5.0,
        help="Webhook POST timeout in seconds (default: 5.0).",
    )
    parser.add_argument(
        "--webhook-header",
        action="append",
        default=[],
        help="Extra webhook header in 'Name: Value' form (repeatable).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    path = Path(args.path).expanduser() if args.path else default_audit_path(Path.cwd())
    reason_codes = {
        item.strip() for item in args.reason_code if item.strip()
    } or DEFAULT_REASON_CODES
    webhook_url = str(args.webhook_url or "").strip()
    webhook_headers = parse_headers(list(args.webhook_header or []))
    if not path.exists() and not args.follow:
        print(f"gateway-turn-watch: audit file not found: {path}", file=sys.stderr)
        return 1
    if not path.exists() and args.follow:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    for line in iter_lines(
        path,
        follow=args.follow,
        from_start=args.from_start,
        poll_interval=args.poll_interval,
    ):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        reason_code = str(payload.get("reason_code") or "").strip()
        if reason_code not in reason_codes:
            continue
        elapsed_ms = coerce_int(payload.get("elapsed_ms"))
        if elapsed_ms is not None and elapsed_ms < args.min_elapsed_ms:
            continue
        alert = build_alert(payload, path)
        emit_alert(alert, as_json=bool(args.json))
        if webhook_url:
            ok, detail = send_webhook(
                alert,
                webhook_url=webhook_url,
                timeout_s=float(args.webhook_timeout_s),
                headers=webhook_headers,
            )
            if not ok:
                print(
                    f"gateway-turn-watch: webhook delivery failed ({detail})",
                    file=sys.stderr,
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
