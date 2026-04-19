#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PARENT_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AGENTS_MD_LINK_TARGET="../agents_md/AGENTS.md"
AGENTS_DOT_MD_LINK_TARGET="../agents.md/AGENTS.md"

resolve_default_agents_source() {
	local candidate
	for candidate in \
		"$PARENT_ROOT/agents_md/AGENTS.md" \
		"$PARENT_ROOT/agents.md/AGENTS.md"; do
		if [[ -f "$candidate" ]]; then
			printf '%s\n' "$candidate"
			return 0
		fi
	done
	return 1
}

DEFAULT_AGENTS_SOURCE="$(resolve_default_agents_source || true)"
DEFAULT_AGENTS_LINK_TARGET="$DEFAULT_AGENTS_SOURCE"

if [[ "$DEFAULT_AGENTS_SOURCE" == "$PARENT_ROOT/agents_md/AGENTS.md" ]]; then
	DEFAULT_AGENTS_LINK_TARGET="$AGENTS_MD_LINK_TARGET"
elif [[ "$DEFAULT_AGENTS_SOURCE" == "$PARENT_ROOT/agents.md/AGENTS.md" ]]; then
	DEFAULT_AGENTS_LINK_TARGET="$AGENTS_DOT_MD_LINK_TARGET"
fi

MY_OPENCODE_REPO="${MY_OPENCODE_REPO:-$REPO_ROOT}"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
AGENTS_SOURCE_PATH="${AGENTS_SOURCE_PATH:-$DEFAULT_AGENTS_SOURCE}"
AGENTS_LINK_TARGET="$AGENTS_SOURCE_PATH"

if [[ -n "$DEFAULT_AGENTS_SOURCE" && "$AGENTS_SOURCE_PATH" == "$DEFAULT_AGENTS_SOURCE" ]]; then
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

if [[ -z "$AGENTS_SOURCE_PATH" ]]; then
	printf 'error: no default AGENTS source found; expected one of:\n' >&2
	printf '  - %s\n' "$PARENT_ROOT/agents_md/AGENTS.md" >&2
	printf '  - %s\n' "$PARENT_ROOT/agents.md/AGENTS.md" >&2
	printf 'Set AGENTS_SOURCE_PATH to override the source path.\n' >&2
	exit 1
fi

if [[ ! -f "$AGENTS_SOURCE_PATH" ]]; then
	printf 'error: AGENTS source not found at %s\n' "$AGENTS_SOURCE_PATH" >&2
	exit 1
fi

mkdir -p "$OPENCODE_CONFIG_DIR"
mkdir -p "$OPENCODE_CONFIG_DIR/agent"

ln -sfn "$MY_OPENCODE_REPO" "$OPENCODE_CONFIG_DIR/my_opencode"
ln -sfn "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json" "$OPENCODE_CONFIG_DIR/opencode.json"
ln -sfn "$AGENTS_LINK_TARGET" "$MY_OPENCODE_REPO/AGENTS.md"

if [[ -d "$MY_OPENCODE_REPO/agent" ]]; then
	for agent_file in "$MY_OPENCODE_REPO"/agent/*.md; do
		if [[ -e "$agent_file" ]]; then
			ln -sfn "$agent_file" "$OPENCODE_CONFIG_DIR/agent/$(basename "$agent_file")"
		fi
	done
fi

if [[ -d "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" ]]; then
	ln -sfn \
		"$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" \
		"$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest"
fi

printf 'Linked repo: %s -> %s\n' "$OPENCODE_CONFIG_DIR/my_opencode" "$MY_OPENCODE_REPO"
printf 'Linked config: %s -> %s\n' "$OPENCODE_CONFIG_DIR/opencode.json" "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json"
printf 'Linked AGENTS: %s -> %s\n' "$MY_OPENCODE_REPO/AGENTS.md" "$AGENTS_LINK_TARGET"
printf 'Linked agents dir: %s\n' "$OPENCODE_CONFIG_DIR/agent"

if [[ -L "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest" ]]; then
	printf 'Linked plugin alias: %s\n' "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest"
fi

printf 'Done. Restart OpenCode to pick up the updated config, plugin path, and AGENTS instructions.\n'
