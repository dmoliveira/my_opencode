#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
SK_REPO = Path("~/Codes/Projects/sk").expanduser()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
CODEX_GENERATED_IMAGES_DIR = CODEX_HOME / "generated_images"
DEFAULT_PROVIDER = "openai_api"
SUPPORTED_PROVIDERS = ["openai_api", "codex-experimental"]
PROVIDER_PREFERENCE_ENV = "OPENAI_IMAGE_PROVIDER_PREFERENCE"
PROVIDER_PREFERENCE_PATH_ENV = "OPENAI_IMAGE_PROVIDER_CONFIG_PATH"
DEFAULT_OUTPUT_LOCATION = "repo-artifacts"
SUPPORTED_OUTPUT_LOCATIONS = ["repo-artifacts", "cwd-artifacts", "desktop"]
OUTPUT_LOCATION_PREFERENCE_ENV = "OPENAI_IMAGE_OUTPUT_LOCATION_PREFERENCE"
OUTPUT_LOCATION_PREFERENCE_PATH_ENV = "OPENAI_IMAGE_OUTPUT_LOCATION_CONFIG_PATH"
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


def output_location_preference_path() -> Path:
    override = os.environ.get(OUTPUT_LOCATION_PREFERENCE_PATH_ENV, "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else REPO_ROOT / path
    return REPO_ROOT / ".opencode" / "image-output-location.txt"


def validate_output_location(location: str) -> str:
    normalized = location.strip()
    if normalized not in SUPPORTED_OUTPUT_LOCATIONS:
        raise RuntimeError(
            f"Unsupported output location: {normalized}. Supported locations: {', '.join(SUPPORTED_OUTPUT_LOCATIONS)}"
        )
    return normalized


def resolve_output_location(explicit_location: str | None) -> tuple[str, str]:
    if explicit_location:
        return validate_output_location(explicit_location), "arg"
    env_value = os.environ.get(OUTPUT_LOCATION_PREFERENCE_ENV, "").strip()
    if env_value:
        return validate_output_location(env_value), f"env:{OUTPUT_LOCATION_PREFERENCE_ENV}"
    pref_path = output_location_preference_path()
    if pref_path.exists():
        value = pref_path.read_text(encoding="utf-8").strip()
        if value:
            return validate_output_location(value), f"file:{pref_path}"
    return DEFAULT_OUTPUT_LOCATION, "default"


def output_root_for_location(location: str, *, cwd: Path | None = None) -> Path:
    normalized = validate_output_location(location)
    base_cwd = cwd or Path.cwd()
    if normalized == "repo-artifacts":
        return DEFAULT_ARTIFACT_ROOT
    if normalized == "cwd-artifacts":
        return base_cwd / "artifacts" / "design"
    if normalized == "desktop":
        return Path("~/Desktop").expanduser() / "artifacts" / "design"
    raise RuntimeError(f"Unhandled output location: {normalized}")


def output_location_payload() -> dict[str, Any]:
    effective_location, source = resolve_output_location(None)
    pref_path = output_location_preference_path()
    configured_value = pref_path.read_text(encoding="utf-8").strip() if pref_path.exists() else None
    return {
        "result": "PASS",
        "default_output_location": DEFAULT_OUTPUT_LOCATION,
        "supported_output_locations": SUPPORTED_OUTPUT_LOCATIONS,
        "effective_output_location": effective_location,
        "effective_output_location_source": source,
        "resolved_output_root": str(output_root_for_location(effective_location)),
        "preference_file": str(pref_path),
        "preference_file_exists": pref_path.exists(),
        "preference_file_value": configured_value,
        "preference_env": OUTPUT_LOCATION_PREFERENCE_ENV,
        "preference_env_value": os.environ.get(OUTPUT_LOCATION_PREFERENCE_ENV, "").strip() or None,
        "notes": [
            "Precedence: --output-location arg > OPENAI_IMAGE_OUTPUT_LOCATION_PREFERENCE env > repo-local preference file > hardcoded default.",
            "Explicit --output bypasses output-location preference resolution entirely.",
            "repo-artifacts stores under this repo's artifacts/design.",
            "cwd-artifacts stores under the current working directory's artifacts/design.",
            "desktop stores under ~/Desktop/artifacts/design.",
        ],
    }


def set_output_location(location: str) -> dict[str, Any]:
    normalized = validate_output_location(location)
    path = output_location_preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized + "\n", encoding="utf-8")
    payload = output_location_payload()
    payload.update({"updated": True})
    return payload


def clear_output_location() -> dict[str, Any]:
    path = output_location_preference_path()
    if path.exists():
        path.unlink()
    payload = output_location_payload()
    payload.update({"cleared": True})
    return payload


def provider_preference_path() -> Path:
    override = os.environ.get(PROVIDER_PREFERENCE_PATH_ENV, "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else REPO_ROOT / path
    return REPO_ROOT / ".opencode" / "image-provider.txt"


def validate_provider(provider: str) -> str:
    normalized = provider.strip()
    if normalized not in SUPPORTED_PROVIDERS:
        raise RuntimeError(
            f"Unsupported provider: {normalized}. Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return normalized


def resolve_provider(explicit_provider: str | None) -> tuple[str, str]:
    if explicit_provider:
        return validate_provider(explicit_provider), "arg"
    env_value = os.environ.get(PROVIDER_PREFERENCE_ENV, "").strip()
    if env_value:
        return validate_provider(env_value), f"env:{PROVIDER_PREFERENCE_ENV}"
    pref_path = provider_preference_path()
    if pref_path.exists():
        value = pref_path.read_text(encoding="utf-8").strip()
        if value:
            return validate_provider(value), f"file:{pref_path}"
    return DEFAULT_PROVIDER, "default"


def preference_payload() -> dict[str, Any]:
    effective_provider, source = resolve_provider(None)
    pref_path = provider_preference_path()
    configured_value = pref_path.read_text(encoding="utf-8").strip() if pref_path.exists() else None
    return {
        "result": "PASS",
        "default_provider": DEFAULT_PROVIDER,
        "supported_providers": SUPPORTED_PROVIDERS,
        "effective_provider": effective_provider,
        "effective_provider_source": source,
        "preference_file": str(pref_path),
        "preference_file_exists": pref_path.exists(),
        "preference_file_value": configured_value,
        "preference_env": PROVIDER_PREFERENCE_ENV,
        "preference_env_value": os.environ.get(PROVIDER_PREFERENCE_ENV, "").strip() or None,
        "notes": [
            "Precedence: --provider arg > OPENAI_IMAGE_PROVIDER_PREFERENCE env > repo-local preference file > hardcoded default.",
            "The hardcoded stable default remains openai_api.",
            "Use codex-experimental only when you explicitly want the experimental subscription-backed path.",
        ],
    }


def set_preference(provider: str) -> dict[str, Any]:
    normalized = validate_provider(provider)
    path = provider_preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized + "\n", encoding="utf-8")
    payload = preference_payload()
    payload.update({"updated": True})
    return payload


def clear_preference() -> dict[str, Any]:
    path = provider_preference_path()
    if path.exists():
        path.unlink()
    payload = preference_payload()
    payload.update({"cleared": True})
    return payload


def codex_path() -> str | None:
    return shutil.which("codex")


def codex_login_status() -> tuple[bool, str]:
    path = codex_path()
    if not path:
        return False, "codex binary not found"
    try:
        result = subprocess.run(
            [path, "login", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=os.environ.copy(),
        )
    except Exception as exc:  # pragma: no cover
        return False, f"codex login status failed: {exc}"
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0 and output:
        return True, output
    return False, output or f"codex login status exited {result.returncode}"


def codex_image_feature_enabled() -> tuple[bool, str]:
    path = codex_path()
    if not path:
        return False, "codex binary not found"
    try:
        result = subprocess.run(
            [path, "features", "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=os.environ.copy(),
        )
    except Exception as exc:  # pragma: no cover
        return False, f"codex features list failed: {exc}"
    text = (result.stdout or "")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "image_generation":
            enabled = parts[-1].lower() == "true"
            return enabled, line.strip()
    return False, "image_generation feature line not found"


def build_status_payload() -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    codex_logged_in, codex_login_detail = codex_login_status()
    codex_image_enabled, codex_feature_detail = codex_image_feature_enabled()
    root = artifact_root()
    effective_provider, effective_source = resolve_provider(None)
    return {
        "result": "PASS",
        "artifact_root": str(root),
        "artifact_root_exists": root.exists(),
        "default_provider": DEFAULT_PROVIDER,
        "default_output_location": DEFAULT_OUTPUT_LOCATION,
        "default_model": DEFAULT_MODEL,
        "default_size": DEFAULT_SIZE,
        "default_quality": DEFAULT_QUALITY,
        "api_key_configured": bool(api_key),
        "api_url": OPENAI_IMAGES_URL,
        "access_model": "api-key-backed-openai-images",
        "supported_providers": SUPPORTED_PROVIDERS,
        "effective_provider": effective_provider,
        "effective_provider_source": effective_source,
        "preference_file": str(provider_preference_path()),
        "effective_output_location": resolve_output_location(None)[0],
        "effective_output_location_source": resolve_output_location(None)[1],
        "output_location_preference_file": str(output_location_preference_path()),
        "codex": {
            "installed": bool(codex_path()),
            "login_status_ok": codex_logged_in,
            "login_status": codex_login_detail,
            "image_generation_feature_enabled": codex_image_enabled,
            "feature_status": codex_feature_detail,
            "generated_images_dir": str(CODEX_GENERATED_IMAGES_DIR),
        },
        "supported_subcommands": ["status", "doctor", "setup-keys", "access", "preference", "location", "prompt", "generate"],
    }


def doctor_payload() -> dict[str, Any]:
    payload = build_status_payload()
    problems: list[str] = []
    warnings: list[str] = []
    effective_provider = str(payload.get("effective_provider") or DEFAULT_PROVIDER)
    if effective_provider == "openai_api" and not payload["api_key_configured"]:
        problems.append("OPENAI_API_KEY is not set")
    elif effective_provider == "codex-experimental" and not payload["api_key_configured"]:
        warnings.append("OPENAI_API_KEY is not set; openai_api provider is unavailable unless you export the key")
    if not str(payload["default_model"]).strip():
        problems.append("default model is empty")
    if not payload["artifact_root_exists"]:
        warnings.append("artifact root will be created on first generate run")
    codex_info = payload.get("codex", {})
    if not codex_info.get("installed"):
        warnings.append("codex binary not found; codex-experimental provider is unavailable")
    elif not codex_info.get("login_status_ok"):
        warnings.append("codex is installed but not logged in with ChatGPT")
    elif not codex_info.get("image_generation_feature_enabled"):
        warnings.append("codex is logged in but image_generation feature is not enabled")
    payload.update({
        "result": "FAIL" if problems else "PASS",
        "problems": problems,
        "warnings": warnings,
        "quick_fixes": [
            "preferred: printf '%s' \"$OPENAI_API_KEY\" | sk add -k OPENAI_API_KEY --stdin --force",
            "runtime load: export OPENAI_API_KEY=\"$(sk get -k OPENAI_API_KEY)\"",
            "codex experimental check: codex login status && codex features list",
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


def resolve_output_path(kind: str, subject: str, output: str | None, *, output_location: str | None = None) -> Path:
    if output:
        path = Path(output)
        return path if path.is_absolute() else REPO_ROOT / path
    location = validate_output_location(output_location or resolve_output_location(None)[0])
    subdir = KIND_TO_DIR.get(kind, "exports")
    stem = slugify(subject or kind)
    return output_root_for_location(location) / subdir / f"{stem}.png"


def write_sidecar(image_path: Path, payload: dict[str, Any]) -> None:
    image_path.with_suffix('.json').write_text(json.dumps(payload, indent=2) + "\n", encoding='utf-8')

def setup_keys() -> int:
    print("setup keys")
    print("----------")
    print("preferred safe storage: macOS Keychain via your local sk flow")
    if SK_REPO.exists():
        print(f"sk repo: {SK_REPO}")
    print("store once:")
    print("printf '%s' \"$OPENAI_API_KEY\" | sk add -k OPENAI_API_KEY --stdin --force")
    print("load only for the current shell/session:")
    print("export OPENAI_API_KEY=\"$(sk get -k OPENAI_API_KEY)\"")
    print("clear when done:")
    print("unset OPENAI_API_KEY")
    print("fallback if sk is unavailable:")
    print("use another local secret manager or a one-session env injection approach that avoids shell history and committed files")
    print("export OPENAI_IMAGE_MODEL='gpt-image-1'  # optional override")
    print("codex experimental provider uses your signed-in Codex session instead of OPENAI_API_KEY")
    print("then run: /image doctor --json")
    return 0


def access_payload() -> dict[str, Any]:
    codex_logged_in, codex_login_detail = codex_login_status()
    codex_image_enabled, codex_feature_detail = codex_image_feature_enabled()
    effective_provider, effective_source = resolve_provider(None)
    return {
        "result": "PASS",
        "access_model": "api-key-backed-openai-images",
        "supports_chatgpt_plan_entitlement": False,
        "default_provider": DEFAULT_PROVIDER,
        "effective_provider": effective_provider,
        "effective_provider_source": effective_source,
        "experimental_providers": {
            "codex-experimental": {
                "installed": bool(codex_path()),
                "login_status_ok": codex_logged_in,
                "login_status": codex_login_detail,
                "image_generation_feature_enabled": codex_image_enabled,
                "feature_status": codex_feature_detail,
                "generated_images_dir": str(CODEX_GENERATED_IMAGES_DIR),
                "notes": [
                    "Codex experimental provider uses a signed-in local Codex CLI session.",
                    "It currently resolves real artifacts from ~/.codex/generated_images/<thread-id>/ after codex exec completes.",
                    "Treat this provider as experimental until Codex exposes a stronger public artifact contract.",
                ],
            }
        },
        "summary": (
            "/image defaults to OpenAI image API access through OPENAI_API_KEY. "
            "ChatGPT plan access in OpenCode does not automatically unlock that default path. "
            "A separate opt-in codex-experimental provider can use your local signed-in Codex session when available."
        ),
        "required_env": ["OPENAI_API_KEY"],
        "optional_env": [
            "OPENAI_IMAGE_MODEL",
            "OPENAI_IMAGE_SIZE",
            "OPENAI_IMAGE_QUALITY",
            PROVIDER_PREFERENCE_ENV,
            PROVIDER_PREFERENCE_PATH_ENV,
        ],
        "notes": [
            "OpenCode chat/model access and OpenAI image API access are separate concerns.",
            "Preferred secret storage for the API-backed path is your local sk/Keychain flow.",
            "Use /image doctor --json to verify both API-backed and codex experimental access for this runtime.",
            "Use /image preference show|set|clear to manage a repo-local provider preference without changing the hardcoded stable default.",
            "Use /ox-design when you want design guidance without calling an image provider.",
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


def parse_codex_jsonl(text: str) -> dict[str, Any]:
    thread_id = None
    reported_path = None
    events = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if event.get('type') == 'thread.started':
            thread_id = event.get('thread_id')
        item = event.get('item') or {}
        if item.get('type') == 'agent_message' and isinstance(item.get('text'), str):
            reported_path = item.get('text').strip()
    return {'thread_id': thread_id, 'reported_path': reported_path, 'events': events}


def resolve_codex_generated_image(
    thread_id: str,
    *,
    reported_path: str | None = None,
    earliest_mtime: float | None = None,
) -> tuple[Path, str]:
    if not thread_id:
        raise RuntimeError('Codex did not return a thread id')
    thread_dir = CODEX_GENERATED_IMAGES_DIR / thread_id
    if not thread_dir.exists():
        raise RuntimeError(f'Codex generated image cache not found for thread {thread_id}: {thread_dir}')
    images = sorted(thread_dir.glob('*.png'), key=lambda p: p.stat().st_mtime)
    if not images:
        raise RuntimeError(f'No generated PNG found under {thread_dir}')
    fresh_images = images
    if earliest_mtime is not None:
        filtered = [img for img in images if img.stat().st_mtime >= earliest_mtime]
        if filtered:
            fresh_images = filtered

    reported_name = Path(reported_path).name if reported_path else ''
    if reported_name:
        for candidate in reversed(fresh_images):
            if candidate.name == reported_name:
                return candidate, 'reported-path-basename'

    if len(fresh_images) == 1:
        return fresh_images[0], 'single-fresh-image'

    if fresh_images is not images:
        return fresh_images[-1], 'newest-fresh-image'

    return images[-1], 'newest-thread-image'


def call_codex_experimental(*, prompt: str) -> tuple[Path, dict[str, Any]]:
    path = codex_path()
    if not path:
        raise RuntimeError('codex binary not found')
    logged_in, login_detail = codex_login_status()
    if not logged_in:
        raise RuntimeError(f'codex login is unavailable: {login_detail}')
    feature_enabled, feature_detail = codex_image_feature_enabled()
    if not feature_enabled:
        raise RuntimeError(f'codex image generation feature is unavailable: {feature_detail}')
    command = [
        path,
        'exec',
        '--json',
        '--sandbox',
        'workspace-write',
        '--skip-git-repo-check',
        '--ephemeral',
        '--disable',
        'shell_tool',
        prompt,
    ]
    started_at = datetime.now(timezone.utc).timestamp()
    with tempfile.TemporaryDirectory(prefix="codex-image-provider-") as tempdir:
        temp_path = Path(tempdir)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
            cwd=temp_path,
            env=os.environ.copy(),
        )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(f'codex exec failed with exit {result.returncode}: {detail}')
    parsed = parse_codex_jsonl(result.stdout)
    artifact, selection_reason = resolve_codex_generated_image(
        str(parsed.get('thread_id') or ''),
        reported_path=str(parsed.get('reported_path') or '') or None,
        earliest_mtime=started_at,
    )
    return artifact, {
        'thread_id': parsed.get('thread_id'),
        'reported_path': parsed.get('reported_path'),
        'resolved_generated_image': str(artifact),
        'resolved_generated_image_selection': selection_reason,
        'codex_exec_workspace': 'isolated-tempdir',
        'codex_login_status': login_detail,
        'codex_feature_status': feature_detail,
    }


def command_prompt(args: argparse.Namespace) -> int:
    prompt = args.prompt or build_prompt(args.kind, args.subject, args.goal, args.style, args.notes)
    if args.output:
        output_location, output_location_source = "explicit-output", "explicit-output"
    else:
        output_location, output_location_source = resolve_output_location(args.output_location)
    output_path = resolve_output_path(args.kind, args.subject or args.goal or args.kind, args.output, output_location=output_location)
    provider, provider_source = resolve_provider(args.provider)
    payload = {
        'result': 'PASS',
        'provider': provider,
        'provider_source': provider_source,
        'output_location': output_location,
        'output_location_source': output_location_source,
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
    if args.output:
        output_location, output_location_source = "explicit-output", "explicit-output"
    else:
        output_location, output_location_source = resolve_output_location(args.output_location)
    output_path = resolve_output_path(args.kind, args.subject or args.goal or args.kind, args.output, output_location=output_location)
    provider, provider_source = resolve_provider(args.provider)
    metadata = {
        'provider': provider,
        'provider_source': provider_source,
        'output_location': output_location,
        'output_location_source': output_location_source,
        'kind': args.kind,
        'prompt': prompt,
        'model': args.model or DEFAULT_MODEL,
        'size': args.size or DEFAULT_SIZE,
        'quality': args.quality or DEFAULT_QUALITY,
        'generated_at': utc_now(),
        'artifact_path': str(output_path),
        'runtime_session_id': os.environ.get('OPENCODE_SESSION_ID', '').strip() or None,
        'subject': args.subject or None,
        'goal': args.goal or None,
        'style': args.style or None,
        'notes': args.notes or None,
    }
    if provider == 'openai_api':
        metadata['api_url'] = OPENAI_IMAGES_URL
    elif provider == 'codex-experimental':
        metadata['experimental'] = True
        metadata['codex_generated_images_dir'] = str(CODEX_GENERATED_IMAGES_DIR)
    else:
        raise RuntimeError(f'Unsupported provider: {provider}')
    if args.dry_run:
        payload = {'result': 'PASS', 'dry_run': True, **metadata}
        return emit(payload, as_json=args.json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if provider == 'openai_api':
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
    else:
        source_path, codex_metadata = call_codex_experimental(prompt=prompt)
        shutil.copy2(source_path, output_path)
        metadata.update(codex_metadata)
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

    preference_parser = subparsers.add_parser('preference')
    preference_parser.add_argument('action', nargs='?', default='show', choices=['show', 'set', 'clear'])
    preference_parser.add_argument('provider', nargs='?')
    preference_parser.add_argument('--json', action='store_true')

    location_parser = subparsers.add_parser('location')
    location_parser.add_argument('action', nargs='?', default='show', choices=['show', 'set', 'clear'])
    location_parser.add_argument('location', nargs='?')
    location_parser.add_argument('--json', action='store_true')

    def add_generation_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument('--provider', default='')
        subparser.add_argument('--output-location', default='')
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
    if args.subcommand == 'preference':
        if args.action == 'show':
            return emit(preference_payload(), as_json=bool(args.json))
        if args.action == 'set':
            if not args.provider:
                raise RuntimeError('provider is required for /image preference set')
            return emit(set_preference(args.provider), as_json=bool(args.json))
        if args.action == 'clear':
            return emit(clear_preference(), as_json=bool(args.json))
    if args.subcommand == 'location':
        if args.action == 'show':
            return emit(output_location_payload(), as_json=bool(args.json))
        if args.action == 'set':
            if not args.location:
                raise RuntimeError('location is required for /image location set')
            return emit(set_output_location(args.location), as_json=bool(args.json))
        if args.action == 'clear':
            return emit(clear_output_location(), as_json=bool(args.json))
    if args.subcommand == 'prompt':
        return command_prompt(args)
    if args.subcommand == 'generate':
        return command_generate(args)
    parser.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
