#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from bounded_subprocess import BoundedCommandError, run_bounded  # type: ignore

VALIDATION_CATEGORIES = {"lint", "test", "typecheck", "build", "security", "custom"}
EVIDENCE_MODES = {"ledger_only", "text_fallback", "hybrid"}
FINGERPRINT_VERSION = "git-state-v1"
EVIDENCE_RELATIVE_PATH = b".opencode/runtime/validation-evidence.json"
MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_UNTRACKED_FILES = 2_048
MAX_UNTRACKED_FILE_BYTES = 4 * 1024 * 1024
MAX_UNTRACKED_TOTAL_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024


def _split_tokens(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        normalized = raw.replace(";", ",").replace("\n", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(item)
    return out


def marker_category(marker: str) -> str | None:
    value = marker.strip().lower()
    if not value:
        return None
    if "lint" in value:
        return "lint"
    if "test" in value:
        return "test"
    if any(token in value for token in ("type", "tsc", "mypy", "pyright")):
        return "typecheck"
    if any(token in value for token in ("build", "compile")):
        return "build"
    if any(token in value for token in ("security", "audit", "semgrep", "codeql")):
        return "security"
    return None


def derive_markers(
    required_validation: list[str], required_markers: list[str]
) -> list[str]:
    markers = [item.strip().lower() for item in required_markers if item.strip()]
    for category in required_validation:
        token = category.strip().lower()
        if token and token != "custom":
            markers.append(token)
    return _dedupe([item for item in markers if item])


def normalize_completion_gates(
    raw: Any, *, fallback_markers: list[str] | None = None
) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    required_validation = [
        item.lower()
        for item in _split_tokens(source.get("required_validation"))
        if item.lower() in VALIDATION_CATEGORIES
    ]
    required_markers = [
        item.lower() for item in _split_tokens(source.get("required_markers"))
    ]
    if fallback_markers:
        required_markers.extend(
            [item.lower() for item in fallback_markers if str(item).strip()]
        )
    required_markers = derive_markers(required_validation, required_markers)
    evidence_mode = str(source.get("evidence_mode") or "hybrid").strip().lower()
    if evidence_mode not in EVIDENCE_MODES:
        evidence_mode = "hybrid"
    return {
        "required_validation": _dedupe(required_validation),
        "required_markers": required_markers,
        "required_task_ids": _dedupe(
            [item for item in _split_tokens(source.get("required_task_ids"))]
        ),
        "required_owner": str(source.get("required_owner") or "").strip(),
        "allow_bypass": bool(source.get("allow_bypass", False)),
        "evidence_mode": evidence_mode,
    }


def _git_bytes(directory: Path, args: list[str], *, operation: str) -> bytes:
    completed = run_bounded(
        ["git", *args],
        operation=operation,
        cwd=str(directory),
        capture_output=True,
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            completed.args,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    if len(completed.stdout) > MAX_GIT_OUTPUT_BYTES:
        raise ValueError("git output exceeds fingerprint budget")
    return completed.stdout


def _frame(digest: Any, label: str, value: bytes | str) -> None:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    digest.update(label.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(len(payload)).encode("ascii"))
    digest.update(b"\0")
    digest.update(payload)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_file_no_follow(path: Path, expected_size: int) -> bytes:
    if expected_size > MAX_UNTRACKED_FILE_BYTES:
        raise ValueError("untracked file exceeds fingerprint budget")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size:
            raise ValueError("untracked file changed during fingerprinting")
        chunks: list[bytes] = []
        remaining = expected_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) != expected_size:
            raise ValueError("untracked file changed during fingerprinting")
        return content
    finally:
        os.close(descriptor)


def _contained_path(root: Path, raw_path: bytes) -> tuple[Path, str]:
    relative_text = raw_path.decode("utf-8", errors="strict")
    if relative_text.encode("utf-8") != raw_path:
        raise ValueError("git path is not canonical UTF-8")
    relative_path = Path(relative_text)
    if not relative_text or relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("git path is outside the worktree")
    absolute = Path(os.path.abspath(root / relative_path))
    if os.path.commonpath((str(root), str(absolute))) != str(root):
        raise ValueError("git path is outside the worktree")
    return absolute, relative_text


def git_state_fingerprint(
    directory: Path,
    *,
    diagnostics: list[str] | None = None,
) -> dict[str, str] | None:
    try:
        root_text = _git_bytes(
            directory,
            ["rev-parse", "--show-toplevel"],
            operation="completion_git_repo_root",
        ).decode(
            "utf-8", errors="strict"
        ).strip()
        root = Path(root_text).resolve()
        head = _git_bytes(
            root,
            ["rev-parse", "--verify", "HEAD"],
            operation="completion_git_head",
        ).decode(
            "ascii", errors="strict"
        ).strip().lower()
        if not root_text or len(head) not in {40, 64} or any(
            char not in "0123456789abcdef" for char in head
        ):
            return None
        staged = _git_bytes(
            root,
            [
                "diff",
                "--cached",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "HEAD",
                "--",
                ".",
                ":(exclude).opencode/runtime/validation-evidence.json",
            ],
            operation="completion_git_staged_diff",
        )
        tracked = _git_bytes(
            root,
            [
                "diff",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
                ".",
                ":(exclude).opencode/runtime/validation-evidence.json",
            ],
            operation="completion_git_tracked_diff",
        )
        untracked = sorted(
            entry
            for entry in _git_bytes(
                root,
                ["ls-files", "--others", "--exclude-standard", "-z"],
                operation="completion_git_untracked_files",
            ).split(b"\0")
            if entry and entry != EVIDENCE_RELATIVE_PATH
        )
        if len(untracked) > MAX_UNTRACKED_FILES:
            raise ValueError("untracked file count exceeds fingerprint budget")
        worktree_digest = hashlib.sha256()
        _frame(worktree_digest, "tracked", tracked)
        total_bytes = 0
        for raw_path in untracked:
            absolute, _ = _contained_path(root, raw_path)
            state = os.lstat(absolute)
            if stat.S_ISLNK(state.st_mode):
                kind = "symlink"
                content = os.readlink(os.fsencode(absolute))
                if isinstance(content, str):
                    content = os.fsencode(content)
            elif stat.S_ISREG(state.st_mode):
                kind = "file"
                content = _read_regular_file_no_follow(absolute, state.st_size)
            else:
                raise ValueError("unsupported untracked file type")
            total_bytes += len(content)
            if (
                len(content) > MAX_UNTRACKED_FILE_BYTES
                or total_bytes > MAX_UNTRACKED_TOTAL_BYTES
            ):
                raise ValueError("untracked content exceeds fingerprint budget")
            _frame(worktree_digest, "path", raw_path)
            _frame(worktree_digest, "type", kind)
            _frame(worktree_digest, "executable", "1" if state.st_mode & 0o111 else "0")
            _frame(worktree_digest, "size", str(len(content)))
            _frame(worktree_digest, "content-sha256", _sha256(content))
        index_digest = _sha256(staged)
        worktree_value = worktree_digest.hexdigest()
        final = hashlib.sha256()
        _frame(final, "version", FINGERPRINT_VERSION)
        _frame(final, "root", str(root))
        _frame(final, "head", head)
        _frame(final, "index", index_digest)
        _frame(final, "worktree", worktree_value)
        return {
            "version": FINGERPRINT_VERSION,
            "root": str(root),
            "head": head,
            "index": index_digest,
            "worktree": worktree_value,
            "digest": final.hexdigest(),
        }
    except BoundedCommandError as exc:
        if diagnostics is not None and exc.reason_code not in diagnostics:
            diagnostics.append(exc.reason_code)
        return None
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        return None


def validation_evidence_path(directory: Path) -> Path:
    fingerprint = git_state_fingerprint(directory)
    root = Path(fingerprint["root"]) if fingerprint else directory.resolve()
    return root / ".opencode" / "runtime" / "validation-evidence.json"


def worktree_evidence_key(directory: Path) -> str:
    fingerprint = git_state_fingerprint(directory)
    return fingerprint["root"] if fingerprint else ""


def _safe_evidence_file(path: Path) -> bool:
    try:
        runtime_state = os.lstat(path.parent)
        opencode_state = os.lstat(path.parent.parent)
        file_state = os.lstat(path)
    except OSError:
        return False
    return bool(
        stat.S_ISDIR(runtime_state.st_mode)
        and not stat.S_ISLNK(runtime_state.st_mode)
        and runtime_state.st_mode & 0o077 == 0
        and stat.S_ISDIR(opencode_state.st_mode)
        and not stat.S_ISLNK(opencode_state.st_mode)
        and opencode_state.st_mode & 0o022 == 0
        and stat.S_ISREG(file_state.st_mode)
        and not stat.S_ISLNK(file_state.st_mode)
        and file_state.st_nlink == 1
        and file_state.st_mode & 0o077 == 0
        and file_state.st_size <= MAX_EVIDENCE_BYTES
    )


def load_validation_snapshot(
    directory: Path,
    *,
    diagnostics: list[str] | None = None,
) -> dict[str, Any]:
    fingerprint = git_state_fingerprint(directory, diagnostics=diagnostics)
    if not fingerprint:
        return {}
    path = Path(fingerprint["root"]) / ".opencode" / "runtime" / "validation-evidence.json"
    if not _safe_evidence_file(path):
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != 2:
        return {}
    worktrees = payload.get("worktrees")
    if not isinstance(worktrees, dict):
        return {}
    record = worktrees.get(fingerprint["root"])
    if not isinstance(record, dict) or record.get("fingerprint") != fingerprint:
        return {}
    snapshot = record.get("evidence")
    if not isinstance(snapshot, dict):
        return {}
    if not all(
        isinstance(snapshot.get(category), bool)
        for category in ("lint", "test", "typecheck", "build", "security")
    ) or not isinstance(snapshot.get("updatedAt"), str):
        return {}
    return snapshot


def _missing_validation(
    snapshot: dict[str, Any], required_validation: list[str]
) -> list[str]:
    missing: list[str] = []
    for category in required_validation:
        if category == "custom":
            missing.append(category)
            continue
        if snapshot.get(category) is not True:
            missing.append(category)
    return missing


def evaluate_completion_gates(
    gates: dict[str, Any],
    *,
    directory: Path,
    completed_task_ids: list[str] | None = None,
    current_owner: str = "",
    completion_text: str = "",
) -> dict[str, Any]:
    normalized = normalize_completion_gates(gates)
    diagnostics: list[str] = []
    snapshot = load_validation_snapshot(directory, diagnostics=diagnostics)
    required_validation = list(normalized.get("required_validation") or [])
    required_markers = list(normalized.get("required_markers") or [])
    required_task_ids = list(normalized.get("required_task_ids") or [])
    required_owner = str(normalized.get("required_owner") or "").strip()
    evidence_mode = str(normalized.get("evidence_mode") or "hybrid").strip().lower()
    lower_text = completion_text.lower()
    missing_validation = _missing_validation(snapshot, required_validation)
    missing_markers: list[str] = []
    for marker in required_markers:
        category = marker_category(marker)
        if (
            category
            and category in required_validation
            and category not in missing_validation
        ):
            continue
        if evidence_mode in {"text_fallback", "hybrid"} and marker in lower_text:
            continue
        if (
            evidence_mode == "ledger_only"
            and category
            and snapshot.get(category) is True
        ):
            continue
        if category is None and evidence_mode == "ledger_only":
            missing_markers.append(marker)
            continue
        if marker not in missing_markers:
            missing_markers.append(marker)
    completed = set(completed_task_ids or [])
    missing_task_ids = [
        task_id for task_id in required_task_ids if task_id not in completed
    ]
    owner_mismatch = bool(
        required_owner
        and current_owner.strip()
        and required_owner != current_owner.strip()
    )
    blockers: list[str] = []
    blockers.extend([f"validation:{item}" for item in missing_validation])
    blockers.extend([f"marker:{item}" for item in missing_markers])
    blockers.extend([f"task:{item}" for item in missing_task_ids])
    if owner_mismatch:
        blockers.append(f"owner:{required_owner}")
    return {
        "result": "PASS" if not blockers else "FAIL",
        "reason_code": "completion_gates_satisfied"
        if not blockers
        else "completion_gates_blocked",
        "gates": normalized,
        "evidence": snapshot,
        "missing_validation": missing_validation,
        "missing_markers": missing_markers,
        "missing_task_ids": missing_task_ids,
        "owner_mismatch": owner_mismatch,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }
