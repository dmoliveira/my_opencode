#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/setup_safety.py" runtime
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

resolve_default_repo_root() {
	local git_common_dir
	git_common_dir="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
	if [[ -n "$git_common_dir" && -d "$git_common_dir" ]]; then
		cd "$git_common_dir/.." && pwd
		return 0
	fi
	printf '%s\n' "$REPO_ROOT"
}

DEFAULT_REPO_ROOT="$(resolve_default_repo_root)"
PARENT_ROOT="$(cd "$DEFAULT_REPO_ROOT/.." && pwd)"
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

MY_OPENCODE_REPO="${MY_OPENCODE_REPO:-$DEFAULT_REPO_ROOT}"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
AGENTS_SOURCE_PATH="${AGENTS_SOURCE_PATH:-$DEFAULT_AGENTS_SOURCE}"
AGENTS_LINK_TARGET="$AGENTS_SOURCE_PATH"

if [[ ! -d "$MY_OPENCODE_REPO" ]]; then
	printf 'error: repo not found at %s\n' "$MY_OPENCODE_REPO" >&2
	exit 1
fi
MY_OPENCODE_REPO="$(cd "$MY_OPENCODE_REPO" && pwd)"

if [[ -n "$DEFAULT_AGENTS_SOURCE" && "$AGENTS_SOURCE_PATH" == "$DEFAULT_AGENTS_SOURCE" && "$(cd "$MY_OPENCODE_REPO/.." && pwd)" == "$PARENT_ROOT" ]]; then
	AGENTS_LINK_TARGET="$DEFAULT_AGENTS_LINK_TARGET"
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

if [[ "$AGENTS_SOURCE_PATH" != /* ]]; then
	AGENTS_SOURCE_PATH="$(cd "$(dirname "$AGENTS_SOURCE_PATH")" && pwd)/$(basename "$AGENTS_SOURCE_PATH")"
	AGENTS_LINK_TARGET="$AGENTS_SOURCE_PATH"
fi

python3 "$SCRIPT_DIR/setup_safety.py" links \
	--repo "$MY_OPENCODE_REPO" --config-dir "$OPENCODE_CONFIG_DIR" \
	--agents-target "$AGENTS_LINK_TARGET"

mkdir -p "$OPENCODE_CONFIG_DIR"
mkdir -p "$OPENCODE_CONFIG_DIR/agent"

python3 "$SCRIPT_DIR/config_layering.py" provision-link \
	--link "$OPENCODE_CONFIG_DIR/my_opencode" \
	--target "$MY_OPENCODE_REPO"
python3 "$SCRIPT_DIR/config_layering.py" provision-link \
	--link "$OPENCODE_CONFIG_DIR/opencode.json" \
	--target "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json"
python3 "$SCRIPT_DIR/setup_safety.py" links \
	--repo "$MY_OPENCODE_REPO" --config-dir "$OPENCODE_CONFIG_DIR" \
	--agents-target "$AGENTS_LINK_TARGET" --create

if [[ -d "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-sidebar" ]]; then
	if [[ ! -f "$MY_OPENCODE_REPO/tui.json" || ! -f "$SCRIPT_DIR/tui_config.py" ]]; then
		printf 'error: gateway-sidebar TUI configuration helper is missing\n' >&2
		exit 1
	fi
	if [[ -z "$(command -v npm)" ]]; then
		printf 'error: npm is required to build gateway-sidebar\n' >&2
		exit 1
	fi
	(
		cd "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-sidebar"
		npm ci --yes --no-audit --no-fund --silent
		npm run build --silent
	) || {
		printf 'error: gateway-sidebar plugin build failed\n' >&2
		exit 1
	}
	python3 "$SCRIPT_DIR/tui_config.py" ensure-execution-sidebar \
		--config "$OPENCODE_CONFIG_DIR/tui.json" \
		--plugin-path "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-sidebar" || {
		printf 'error: gateway-sidebar TUI configuration failed\n' >&2
		exit 1
	}
fi

printf 'Linked repo: %s -> %s\n' "$OPENCODE_CONFIG_DIR/my_opencode" "$MY_OPENCODE_REPO"
printf 'Linked config: %s -> %s\n' "$OPENCODE_CONFIG_DIR/opencode.json" "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json"
printf 'Linked AGENTS: %s -> %s\n' "$MY_OPENCODE_REPO/AGENTS.md" "$AGENTS_LINK_TARGET"
printf 'Linked agents dir: %s\n' "$OPENCODE_CONFIG_DIR/agent"

printf 'Done. Restart OpenCode to pick up the updated config, plugin path, and AGENTS instructions.\n'
