#!/usr/bin/env bash
set -euo pipefail

if ! command -v opencode >/dev/null 2>&1; then
  printf "error: opencode command not found in PATH\n" >&2
  exit 1
fi

DIGEST_REASON_ON_EXIT="${DIGEST_REASON_ON_EXIT:-exit}"
DIGEST_OUTPUT_PATH="${MY_OPENCODE_DIGEST_PATH:-$HOME/.config/opencode/digests/last-session.json}"
DIGEST_HOOK="${MY_OPENCODE_DIGEST_HOOK:-}"

run_digest() {
  if [ -n "$DIGEST_HOOK" ]; then
    python3 "$HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason "$DIGEST_REASON_ON_EXIT" --path "$DIGEST_OUTPUT_PATH" --run-post --hook "$DIGEST_HOOK" >/dev/null 2>&1 || true
  else
    python3 "$HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason "$DIGEST_REASON_ON_EXIT" --path "$DIGEST_OUTPUT_PATH" --run-post >/dev/null 2>&1 || true
  fi
}

trap run_digest EXIT

opencode "$@"
