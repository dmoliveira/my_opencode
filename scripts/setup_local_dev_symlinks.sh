#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_AGENTS_LINK_TARGET="../agents_md/AGENTS.md"
DEFAULT_AGENTS_SOURCE="$(cd "$REPO_ROOT/.." && pwd)/agents_md/AGENTS.md"

MY_OPENCODE_REPO="${MY_OPENCODE_REPO:-$REPO_ROOT}"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
AGENTS_SOURCE_PATH="${AGENTS_SOURCE_PATH:-$DEFAULT_AGENTS_SOURCE}"
AGENTS_LINK_TARGET="$AGENTS_SOURCE_PATH"

if [[ "$AGENTS_SOURCE_PATH" == "$DEFAULT_AGENTS_SOURCE" ]]; then
	AGENTS_LINK_TARGET="$DEFAULT_AGENTS_LINK_TARGET"
fi

if [[ ! -d "$MY_OPENCODE_REPO" ]]; then
	printf 'error: repo not found at %s\n' "$MY_OPENCODE_REPO" >&2
	exit 1
fi

if [[ ! -f "$MY_OPENCODE_REPO/opencode.json" ]]; then
	printf 'error: opencode.json not found at %s\n' "$MY_OPENCODE_REPO/opencode.json" >&2
	exit 1
fi

if [[ ! -f "$AGENTS_SOURCE_PATH" ]]; then
	printf 'error: AGENTS source not found at %s\n' "$AGENTS_SOURCE_PATH" >&2
	exit 1
fi

mkdir -p "$OPENCODE_CONFIG_DIR"

ln -sfn "$MY_OPENCODE_REPO" "$OPENCODE_CONFIG_DIR/my_opencode"
ln -sfn "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json" "$OPENCODE_CONFIG_DIR/opencode.json"
ln -sfn "$AGENTS_LINK_TARGET" "$MY_OPENCODE_REPO/AGENTS.md"

if [[ -d "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" ]]; then
	ln -sfn \
		"$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" \
		"$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest"
fi

printf 'Linked repo: %s -> %s\n' "$OPENCODE_CONFIG_DIR/my_opencode" "$MY_OPENCODE_REPO"
printf 'Linked config: %s -> %s\n' "$OPENCODE_CONFIG_DIR/opencode.json" "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json"
printf 'Linked AGENTS: %s -> %s\n' "$MY_OPENCODE_REPO/AGENTS.md" "$AGENTS_LINK_TARGET"

if [[ -L "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest" ]]; then
	printf 'Linked plugin alias: %s\n' "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest"
fi

printf 'Done. Restart OpenCode to pick up the updated config, plugin path, and AGENTS instructions.\n'
