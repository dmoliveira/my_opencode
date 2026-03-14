#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)"

resolve_gateway_config_path() {
	if [ -n "${MY_OPENCODE_GATEWAY_CONFIG_PATH:-}" ]; then
		printf "%s\n" "$MY_OPENCODE_GATEWAY_CONFIG_PATH"
		return 0
	fi
	if [ -f "$PWD/.opencode/gateway-core.config.json" ]; then
		printf "%s\n" "$PWD/.opencode/gateway-core.config.json"
		return 0
	fi
	if [ -f "$HOME/.config/opencode/my_opencode/gateway-core.config.json" ]; then
		printf "%s\n" "$HOME/.config/opencode/my_opencode/gateway-core.config.json"
		return 0
	fi
	printf "%s\n" "$REPO_ROOT/plugin/gateway-core/config/default-gateway-core.config.json"
}

if ! command -v opencode >/dev/null 2>&1; then
	printf "error: opencode command not found in PATH\n" >&2
	exit 1
fi

DIGEST_REASON_ON_EXIT="${DIGEST_REASON_ON_EXIT:-exit}"
DIGEST_OUTPUT_PATH="${MY_OPENCODE_DIGEST_PATH:-$HOME/.config/opencode/digests/last-session.json}"
DIGEST_HOOK="${MY_OPENCODE_DIGEST_HOOK:-}"

: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT:=1}"
: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES:=8388608}"
: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS:=5}"

MY_OPENCODE_GATEWAY_CONFIG_PATH="$(resolve_gateway_config_path)"
: "${MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH:=$PWD/.opencode/gateway-events.jsonl}"

export MY_OPENCODE_GATEWAY_EVENT_AUDIT
export MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES
export MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS
export MY_OPENCODE_GATEWAY_CONFIG_PATH
export MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH

run_digest() {
	if [ -n "$DIGEST_HOOK" ]; then
		python3 "$HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason "$DIGEST_REASON_ON_EXIT" --path "$DIGEST_OUTPUT_PATH" --run-post --hook "$DIGEST_HOOK" >/dev/null 2>&1 || true
	else
		python3 "$HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason "$DIGEST_REASON_ON_EXIT" --path "$DIGEST_OUTPUT_PATH" --run-post >/dev/null 2>&1 || true
	fi
}

trap run_digest EXIT

opencode "$@"
