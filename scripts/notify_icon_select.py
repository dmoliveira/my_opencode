#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


EVENTS = ("complete", "error", "permission", "question")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select generated notification icon candidates and update manifest.",
    )
    parser.add_argument("--version", required=True, help="Icon pack version (e.g. v1).")
    parser.add_argument(
        "--event", required=True, choices=EVENTS, help="Event to update."
    )
    parser.add_argument(
        "--candidate-index",
        required=True,
        type=int,
        help="1-based candidate index from manifest candidates list.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    version_dir = root / "assets" / "notify-icons" / args.version
    manifest_path = version_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"manifest missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    events = manifest.get("events")
    if not isinstance(events, dict) or args.event not in events:
        raise SystemExit(f"event not found in manifest: {args.event}")

    event_data = events[args.event]
    if not isinstance(event_data, dict):
        raise SystemExit(f"invalid event payload for {args.event}")
    candidates = event_data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SystemExit(f"no candidates found for {args.event}")

    index = args.candidate_index - 1
    if index < 0 or index >= len(candidates):
        raise SystemExit(
            f"candidate-index out of range for {args.event}: 1..{len(candidates)}"
        )

    selected = candidates[index]
    if not isinstance(selected, str) or not selected:
        raise SystemExit("selected candidate path is invalid")

    source = root / selected
    if not source.exists():
        raise SystemExit(f"selected candidate file not found: {source}")

    target = version_dir / f"{args.event}.png"
    target.write_bytes(source.read_bytes())
    event_data["selected"] = selected
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"selected {args.event} candidate #{args.candidate_index}: {selected}")
    print(f"updated icon: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
