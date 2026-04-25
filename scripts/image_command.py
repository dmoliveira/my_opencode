#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
DEFAULT_SIZE = os.environ.get("OPENAI_IMAGE_SIZE", "1024x1024")
DEFAULT_QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "high")
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "design"
OPENAI_IMAGES_URL = os.environ.get("OPENAI_IMAGES_API_URL", "https://api.openai.com/v1/images/generations")
KIND_TO_DIR = {
    "wireframe": "wireframes",
    "icon": "icons",
    "palette": "palettes",
    "mockup": "mockups",
    "hero": "hero",
    "typography": "typography",
    "component": "exports",
    "game-ui": "mockups",
    "concept": "exports",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "design-artifact"


def artifact_root() -> Path:
    return DEFAULT_ARTIFACT_ROOT


def build_status_payload() -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    root = artifact_root()
    return {
        "result": "PASS",
        "artifact_root": str(root),
        "artifact_root_exists": root.exists(),
        "default_model": DEFAULT_MODEL,
        "default_size": DEFAULT_SIZE,
        "default_quality": DEFAULT_QUALITY,
        "api_key_configured": bool(api_key),
        "api_url": OPENAI_IMAGES_URL,
        "access_model": "api-key-backed-openai-images",
        "supported_subcommands": ["status", "doctor", "setup-keys", "access", "prompt", "generate"],
    }


def doctor_payload() -> dict[str, Any]:
    payload = build_status_payload()
    problems: list[str] = []
    warnings: list[str] = []
    if not payload["api_key_configured"]:
        problems.append("OPENAI_API_KEY is not set")
    if not str(payload["default_model"]).strip():
        problems.append("default model is empty")
    if not payload["artifact_root_exists"]:
        warnings.append("artifact root will be created on first generate run")
    payload.update({
        "result": "FAIL" if problems else "PASS",
        "problems": problems,
        "warnings": warnings,
        "quick_fixes": [
            "export OPENAI_API_KEY='sk-...'",
            "optional: export OPENAI_IMAGE_MODEL='gpt-image-1'",
            "run /image generate --dry-run first to confirm output path",
        ],
    })
    return payload


def emit(payload: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("result") == "PASS" else 1
    for key, value in payload.items():
        if isinstance(value, (list, dict)):
            print(f"{key}: {json.dumps(value, indent=2)}")
        else:
            print(f"{key}: {value}")
    return 0 if payload.get("result") == "PASS" else 1


def build_prompt(kind: str, subject: str, goal: str, style: str, notes: str) -> str:
    templates = {
        "wireframe": "Create a clean product wireframe for {subject}. Emphasize UX hierarchy, clear spacing, low-fidelity structure, and implementation-ready screen organization.",
        "icon": "Create a consistent icon concept for {subject}. Keep the style crisp, simple, product-ready, and readable at small sizes.",
        "palette": "Create a polished product design palette for {subject}. Balance contrast, accessibility, calm hierarchy, and implementation-ready semantic color roles.",
        "mockup": "Create a polished UI mockup for {subject}. Focus on strong hierarchy, modern product polish, clear states, and implementation-friendly layout decisions.",
        "hero": "Create a hero visual concept for {subject}. Make it product-friendly, clear, high-signal, and suitable for marketing or onboarding surfaces.",
        "typography": "Create typography direction for {subject}. Focus on readability, product clarity, and a consistent visual rhythm.",
        "component": "Create a reusable UI component visual concept for {subject}. Focus on states, spacing, and implementation-ready structure.",
        "game-ui": "Create a game UI concept for {subject}. Focus on readability, mood, HUD clarity, menu hierarchy, and player-friendly interaction cues.",
        "concept": "Create a strong design concept for {subject}. Focus on UX clarity, hierarchy, and a coherent visual direction.",
    }
    base = templates.get(kind, templates["concept"]).format(subject=subject or "this interface")
    parts = [base]
    if goal:
        parts.append(f"Primary goal: {goal}.")
    if style:
        parts.append(f"Style direction: {style}.")
    if notes:
        parts.append(f"Extra constraints: {notes}.")
    parts.append("Produce one strong direction rather than many unrelated ideas.")
    return " ".join(part.strip() for part in parts if part.strip())


def resolve_output_path(kind: str, subject: str, output: str | None) -> Path:
    if output:
        path = Path(output)
        return path if path.is_absolute() else REPO_ROOT / path
    subdir = KIND_TO_DIR.get(kind, "exports")
    stem = slugify(subject or kind)
    return artifact_root() / subdir / f"{stem}.png"


def write_sidecar(image_path: Path, payload: dict[str, Any]) -> None:
    image_path.with_suffix('.json').write_text(json.dumps(payload, indent=2) + "\n", encoding='utf-8')

def setup_keys() -> int:
    print("setup keys")
    print("----------")
    print("export OPENAI_API_KEY='sk_your_key_here'")
    print("export OPENAI_IMAGE_MODEL='gpt-image-1'  # optional override")
    print("then run: /image doctor --json")
    return 0


def access_payload() -> dict[str, Any]:
    return {
        "result": "PASS",
        "access_model": "api-key-backed-openai-images",
        "supports_chatgpt_plan_entitlement": False,
        "summary": (
            "/image uses OpenAI image API access through OPENAI_API_KEY. "
            "ChatGPT plan access in OpenCode does not automatically unlock this command."
        ),
        "required_env": ["OPENAI_API_KEY"],
        "optional_env": ["OPENAI_IMAGE_MODEL", "OPENAI_IMAGE_SIZE", "OPENAI_IMAGE_QUALITY"],
        "notes": [
            "OpenCode chat/model access and OpenAI image API access are separate concerns.",
            "Use /image doctor --json to verify API-backed image access for this runtime.",
            "Use /ox-design when you want design guidance without calling the image API.",
        ],
    }


def call_openai_image_api(*, prompt: str, model: str, size: str, quality: str) -> tuple[bytes, dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    body = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "response_format": "b64_json",
    }
    req = request.Request(
        OPENAI_IMAGES_URL,
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with request.urlopen(req, timeout=180) as response:
            response_body = response.read().decode('utf-8')
    except error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'OpenAI API error {exc.code}: {detail}') from exc
    except error.URLError as exc:
        raise RuntimeError(f'OpenAI API request failed: {exc}') from exc
    parsed = json.loads(response_body)
    data = parsed.get('data') or []
    if not data or not isinstance(data, list):
        raise RuntimeError('OpenAI API response did not include image data')
    first = data[0] or {}
    b64_json = first.get('b64_json')
    if not isinstance(b64_json, str) or not b64_json.strip():
        raise RuntimeError('OpenAI API response missing data[0].b64_json')
    return base64.b64decode(b64_json), parsed


def command_prompt(args: argparse.Namespace) -> int:
    prompt = args.prompt or build_prompt(args.kind, args.subject, args.goal, args.style, args.notes)
    output_path = resolve_output_path(args.kind, args.subject or args.goal or args.kind, args.output)
    payload = {
        'result': 'PASS',
        'kind': args.kind,
        'prompt': prompt,
        'suggested_output': str(output_path),
        'artifact_root': str(artifact_root()),
        'model': args.model or DEFAULT_MODEL,
        'size': args.size or DEFAULT_SIZE,
        'quality': args.quality or DEFAULT_QUALITY,
    }
    return emit(payload, as_json=args.json)


def command_generate(args: argparse.Namespace) -> int:
    prompt = args.prompt or build_prompt(args.kind, args.subject, args.goal, args.style, args.notes)
    output_path = resolve_output_path(args.kind, args.subject or args.goal or args.kind, args.output)
    metadata = {
        'kind': args.kind,
        'prompt': prompt,
        'model': args.model or DEFAULT_MODEL,
        'size': args.size or DEFAULT_SIZE,
        'quality': args.quality or DEFAULT_QUALITY,
        'generated_at': utc_now(),
        'api_url': OPENAI_IMAGES_URL,
        'artifact_path': str(output_path),
        'runtime_session_id': os.environ.get('OPENCODE_SESSION_ID', '').strip() or None,
        'subject': args.subject or None,
        'goal': args.goal or None,
        'style': args.style or None,
        'notes': args.notes or None,
    }
    if args.dry_run:
        payload = {'result': 'PASS', 'dry_run': True, **metadata}
        return emit(payload, as_json=args.json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image_bytes, response_payload = call_openai_image_api(
        prompt=prompt,
        model=metadata['model'],
        size=metadata['size'],
        quality=metadata['quality'],
    )
    output_path.write_bytes(image_bytes)
    metadata['openai_response_summary'] = {
        'created': response_payload.get('created'),
        'data_count': len(response_payload.get('data') or []),
    }
    write_sidecar(output_path, metadata)
    payload = {'result': 'PASS', 'output': str(output_path), 'metadata': str(output_path.with_suffix('.json')), **metadata}
    return emit(payload, as_json=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='/image', description='Generate repo-native design artifacts under artifacts/design/.')
    subparsers = parser.add_subparsers(dest='subcommand')

    status_parser = subparsers.add_parser('status')
    status_parser.add_argument('--json', action='store_true')

    doctor_parser = subparsers.add_parser('doctor')
    doctor_parser.add_argument('--json', action='store_true')

    subparsers.add_parser('setup-keys')

    access_parser = subparsers.add_parser('access')
    access_parser.add_argument('--json', action='store_true')

    def add_generation_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument('--kind', default='concept')
        subparser.add_argument('--subject', default='')
        subparser.add_argument('--goal', default='')
        subparser.add_argument('--style', default='')
        subparser.add_argument('--notes', default='')
        subparser.add_argument('--prompt', default='')
        subparser.add_argument('--output', default='')
        subparser.add_argument('--model', default='')
        subparser.add_argument('--size', default='')
        subparser.add_argument('--quality', default='')
        subparser.add_argument('--json', action='store_true')

    prompt_parser = subparsers.add_parser('prompt')
    add_generation_args(prompt_parser)

    generate_parser = subparsers.add_parser('generate')
    add_generation_args(generate_parser)
    generate_parser.add_argument('--dry-run', action='store_true')
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.subcommand in {None, 'status'}:
        return emit(build_status_payload(), as_json=getattr(args, 'json', False))
    if args.subcommand == 'doctor':
        return emit(doctor_payload(), as_json=bool(args.json))
    if args.subcommand == 'setup-keys':
        return setup_keys()
    if args.subcommand == 'access':
        return emit(access_payload(), as_json=bool(args.json))
    if args.subcommand == 'prompt':
        return command_prompt(args)
    if args.subcommand == 'generate':
        return command_generate(args)
    parser.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
