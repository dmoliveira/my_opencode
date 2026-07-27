from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path


def _write_flood(descriptor: int, total_bytes: int) -> None:
    remaining = total_bytes
    chunk = b"x" * (64 * 1024)
    while remaining:
        try:
            written = os.write(descriptor, chunk[:remaining])
        except BrokenPipeError:
            return
        remaining -= written


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if scenario == "normal":
        os.write(sys.stdout.fileno(), b"normal stdout\n")
        os.write(sys.stderr.fileno(), b"normal stderr\n")
        return 0
    if scenario == "stdout-flood":
        _write_flood(sys.stdout.fileno(), int(sys.argv[2]))
        return 0
    if scenario == "ignore-term":
        marker = Path(sys.argv[2])

        def observe_term(_signum: int, _frame: object) -> None:
            marker.write_text("TERM\n", encoding="utf-8")

        signal.signal(signal.SIGTERM, observe_term)
        while True:
            time.sleep(0.05)
    if scenario == "inherited-pipe":
        child_pid = os.fork()
        if child_pid == 0:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                time.sleep(0.05)
        os.write(sys.stdout.fileno(), f"child={child_pid}\n".encode("ascii"))
        return 0
    if scenario == "mcp":
        for line in sys.stdin.buffer:
            request = json.loads(line)
            request_id = request.get("id")
            if request_id is None:
                continue
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"request_id": request_id},
            }
            os.write(
                sys.stdout.fileno(),
                (json.dumps(response, separators=(",", ":")) + "\n").encode(
                    "utf-8"
                ),
            )
        return 0
    raise RuntimeError(f"unknown scenario: {scenario}")


if __name__ == "__main__":
    raise SystemExit(main())
