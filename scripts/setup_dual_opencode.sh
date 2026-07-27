#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MY_OPENCODE_REPO="${MY_OPENCODE_REPO:-$HOME/Codes/Projects/my_opencode}"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
OHMY_CONFIG_HOME="${OHMY_CONFIG_HOME:-$HOME/.config/opencode-ohmy}"
ZSHRC_FILE="${ZSHRC_FILE:-$HOME/.zshrc}"

if [[ ! -d "$MY_OPENCODE_REPO" ]]; then
  echo "my_opencode repo not found at: $MY_OPENCODE_REPO" >&2
  echo "Set MY_OPENCODE_REPO to your repo path and rerun." >&2
  exit 1
fi

mkdir -p "$OPENCODE_CONFIG_DIR"

# Move runtime state under the same namespace lock used by config writers.
python3 "$SCRIPT_DIR/config_layering.py" provision-move \
  --source "$OPENCODE_CONFIG_DIR/my_opencode/runtime/plan_execution.json" \
  --target "$MY_OPENCODE_REPO/runtime/plan_execution.json"

# Ensure ~/.config/opencode/my_opencode points to repo.
python3 "$SCRIPT_DIR/config_layering.py" provision-link \
  --link "$OPENCODE_CONFIG_DIR/my_opencode" \
  --target "$MY_OPENCODE_REPO"

# Ensure default config is the repo opencode.json.
python3 "$SCRIPT_DIR/config_layering.py" provision-link \
  --link "$OPENCODE_CONFIG_DIR/opencode.json" \
  --target "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json"

# Fix Bun file plugin install by providing gateway-core@latest alias if plugin exists.
if [[ -d "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" ]]; then
  ln -sfn "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest"
fi

# Set up isolated oh-my-opencode config home.
mkdir -p "$OHMY_CONFIG_HOME/opencode"
python3 "$SCRIPT_DIR/config_layering.py" provision-json \
  --path "$OHMY_CONFIG_HOME/opencode/opencode.json" \
  --content '{"$schema":"https://opencode.ai/config.json","plugin":["oh-my-opencode@latest"]}'

if [[ -f "$OPENCODE_CONFIG_DIR/oh-my-opencode.json" ]]; then
  python3 "$SCRIPT_DIR/config_layering.py" provision-json \
    --path "$OHMY_CONFIG_HOME/opencode/oh-my-opencode.json" \
    --source "$OPENCODE_CONFIG_DIR/oh-my-opencode.json"
else
  python3 "$SCRIPT_DIR/config_layering.py" provision-json \
    --path "$OHMY_CONFIG_HOME/opencode/oh-my-opencode.json" \
    --content '{"$schema":"https://raw.githubusercontent.com/code-yeongyu/oh-my-opencode/dev/assets/oh-my-opencode.schema.json"}'
fi

# Add zsh alias if missing.
ALIAS_LINE="alias opencode-ohmy='XDG_CONFIG_HOME=$OHMY_CONFIG_HOME opencode'"
python3 "$SCRIPT_DIR/config_layering.py" provision-line \
  --path "$ZSHRC_FILE" \
  --line "$ALIAS_LINE" \
  --if-missing

echo "Done. Default: opencode (my_opencode). Alternate: opencode-ohmy (oh-my-opencode)."
