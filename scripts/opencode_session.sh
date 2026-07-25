#!/usr/bin/env bash
set -euo pipefail

if ! command -v opencode >/dev/null 2>&1; then
	printf "error: opencode command not found in PATH\n" >&2
	exit 1
fi

DIGEST_REASON_ON_EXIT="${DIGEST_REASON_ON_EXIT:-exit}"
DIGEST_OUTPUT_PATH="${MY_OPENCODE_DIGEST_PATH:-$HOME/.config/opencode/digests/last-session.json}"
DIGEST_HOOK="${MY_OPENCODE_DIGEST_HOOK:-}"
AUTO_DIGEST_ON_EXIT="${MY_OPENCODE_AUTO_DIGEST:-0}"

: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT:=0}"
: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES:=8388608}"
: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS:=5}"

: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH:=$PWD/.opencode/gateway-events.jsonl}"

export MY_OPENCODE_GATEWAY_EVENT_AUDIT
export MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES
export MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS
export MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH

run_digest() {
	if [ -n "$DIGEST_HOOK" ]; then
		python3 "$HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason "$DIGEST_REASON_ON_EXIT" --path "$DIGEST_OUTPUT_PATH" --run-post --hook "$DIGEST_HOOK" >/dev/null 2>&1 || true
	else
		python3 "$HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason "$DIGEST_REASON_ON_EXIT" --path "$DIGEST_OUTPUT_PATH" --run-post >/dev/null 2>&1 || true
	fi
}

if [ "$AUTO_DIGEST_ON_EXIT" = "1" ]; then
	trap run_digest EXIT
fi

opencode "$@"
