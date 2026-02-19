#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


EVENTS = ("complete", "error", "permission", "question")


@dataclass(frozen=True)
class EventPrompt:
    title: str
    description: str
    nerd_icon: str
    emoji: str
    accent: str


EVENT_PROMPTS: dict[str, EventPrompt] = {
    "complete": EventPrompt(
        title="completed task",
        description="successful finish, calm confidence",
        nerd_icon="\udb80\udd2c",
        emoji="✅",
        accent="teal",
    ),
    "error": EventPrompt(
        title="error detected",
        description="clear failure, high urgency",
        nerd_icon="\udb80\udd5a",
        emoji="❌",
        accent="red",
    ),
    "permission": EventPrompt(
        title="permission required",
        description="security prompt, lock and shield motif",
        nerd_icon="\udb80\udf3e",
        emoji="🔐",
        accent="amber",
    ),
    "question": EventPrompt(
        title="input needed",
        description="question prompt, actionable guidance",
        nerd_icon="\udb80\udde2",
        emoji="❓",
        accent="blue",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate versioned notification icon packs with OpenAI image API.",
    )
    parser.add_argument(
        "--version", default="v1", help="Icon pack version directory name."
    )
    parser.add_argument("--model", default="gpt-image-1", help="OpenAI image model.")
    parser.add_argument("--size", default="1024x1024", help="Generation size.")
    parser.add_argument(
        "--single-count",
        type=int,
        default=3,
        help="Single-icon candidates per event (default: 3).",
    )
    parser.add_argument(
        "--grid-rows",
        type=int,
        default=3,
        help="Reference grid rows for variation boards (default: 3).",
    )
    parser.add_argument(
        "--grid-cols",
        type=int,
        default=3,
        help="Reference grid columns for variation boards (default: 3).",
    )
    parser.add_argument(
        "--events",
        nargs="*",
        default=list(EVENTS),
        help="Subset of events to generate.",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable that stores OpenAI API key.",
    )
    return parser.parse_args()


def ensure_events(selected: list[str]) -> list[str]:
    events: list[str] = []
    for item in selected:
        key = item.strip().lower()
        if key in EVENT_PROMPTS and key not in events:
            events.append(key)
    if not events:
        raise SystemExit("No valid events selected.")
    return events


def post_json(url: str, payload: dict[str, object], api_key: str) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=90) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def decode_image_bytes(response_payload: dict[str, object]) -> bytes:
    data = response_payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("image response payload missing data")
    first = data[0]
    if not isinstance(first, dict):
        raise ValueError("image response item is not an object")
    if isinstance(first.get("b64_json"), str):
        return base64.b64decode(first["b64_json"])
    if isinstance(first.get("url"), str):
        with urllib.request.urlopen(first["url"], timeout=90) as response:
            return response.read()
    raise ValueError("image response missing b64_json/url fields")


def single_prompt(meta: EventPrompt, index: int, total: int) -> str:
    return (
        "Create one square app-style notification icon on transparent background. "
        f"Theme: {meta.title}. Mood: {meta.description}. Accent color: {meta.accent}. "
        f"Embed a minimalist symbol inspired by nerd icon {meta.nerd_icon} and emoji {meta.emoji}. "
        "No text labels. Crisp edges, high contrast, suitable for macOS notification thumbnail. "
        f"Variation {index} of {total}."
    )


def grid_prompt(meta: EventPrompt, rows: int, cols: int) -> str:
    return (
        f"Generate a {rows}x{cols} grid of distinct square notification icon concepts on transparent background. "
        f"Topic: {meta.title}. Mood: {meta.description}. Accent color: {meta.accent}. "
        f"Each cell should be unique and reflect nerd icon {meta.nerd_icon} plus emoji {meta.emoji} semantics. "
        "No text labels, no watermarks, balanced spacing between cells, crisp vector-like look."
    )


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main() -> int:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(
            f"Missing API key. Set {args.api_key_env} before running icon generation."
        )

    events = ensure_events(args.events)
    root = Path(__file__).resolve().parent.parent
    version_dir = root / "assets" / "notify-icons" / args.version
    grids_dir = version_dir / "grids"
    candidates_dir = version_dir / "candidates"
    manifest_path = version_dir / "manifest.json"
    manifest: dict[str, object] = {
        "version": args.version,
        "model": args.model,
        "size": args.size,
        "events": {},
    }

    for event in events:
        meta = EVENT_PROMPTS[event]
        event_record: dict[str, object] = {
            "grid": "",
            "selected": "",
            "candidates": [],
            "nerd_icon": meta.nerd_icon,
            "emoji_fallback": meta.emoji,
        }

        try:
            grid_payload = post_json(
                "https://api.openai.com/v1/images/generations",
                {
                    "model": args.model,
                    "prompt": grid_prompt(meta, args.grid_rows, args.grid_cols),
                    "size": args.size,
                },
                api_key,
            )
            grid_bytes = decode_image_bytes(grid_payload)
            grid_path = grids_dir / f"{event}-grid.png"
            write_bytes(grid_path, grid_bytes)
            event_record["grid"] = str(grid_path.relative_to(root))
            print(f"generated grid: {grid_path}")
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            print(f"warning: grid generation failed for {event}: {exc}")

        candidates: list[str] = []
        for index in range(1, max(1, args.single_count) + 1):
            payload = post_json(
                "https://api.openai.com/v1/images/generations",
                {
                    "model": args.model,
                    "prompt": single_prompt(meta, index, max(1, args.single_count)),
                    "size": args.size,
                },
                api_key,
            )
            image_bytes = decode_image_bytes(payload)
            candidate_path = candidates_dir / f"{event}-{index}.png"
            write_bytes(candidate_path, image_bytes)
            candidates.append(str(candidate_path.relative_to(root)))
            print(f"generated candidate: {candidate_path}")

        event_record["candidates"] = candidates
        selected = candidates[0] if candidates else ""
        event_record["selected"] = selected
        if selected:
            selected_source = root / selected
            target_path = version_dir / f"{event}.png"
            target_path.write_bytes(selected_source.read_bytes())
            print(f"selected default: {target_path}")
        manifest["events"][event] = event_record

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
