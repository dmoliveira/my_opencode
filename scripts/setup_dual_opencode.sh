#!/usr/bin/env bash
set -euo pipefail

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

# Move runtime state into repo if it exists under the old symlink path.
if [[ -f "$OPENCODE_CONFIG_DIR/my_opencode/runtime/plan_execution.json" ]]; then
  mkdir -p "$MY_OPENCODE_REPO/runtime"
  mv "$OPENCODE_CONFIG_DIR/my_opencode/runtime/plan_execution.json" "$MY_OPENCODE_REPO/runtime/" || true
fi

# Ensure ~/.config/opencode/my_opencode points to repo.
rm -f "$OPENCODE_CONFIG_DIR/my_opencode"
ln -sfn "$MY_OPENCODE_REPO" "$OPENCODE_CONFIG_DIR/my_opencode"

# Ensure default config is the repo opencode.json.
ln -sfn "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json" "$OPENCODE_CONFIG_DIR/opencode.json"

# Fix Bun file plugin install by providing gateway-core@latest alias if plugin exists.
if [[ -d "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" ]]; then
  ln -sfn "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core" "$OPENCODE_CONFIG_DIR/my_opencode/plugin/gateway-core@latest"
fi

# Set up isolated oh-my-opencode config home.
mkdir -p "$OHMY_CONFIG_HOME/opencode"
cat > "$OHMY_CONFIG_HOME/opencode/opencode.json" <<'JSON'
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["oh-my-opencode@latest"]
}
JSON

if [[ -f "$OPENCODE_CONFIG_DIR/oh-my-opencode.json" ]]; then
  cp "$OPENCODE_CONFIG_DIR/oh-my-opencode.json" "$OHMY_CONFIG_HOME/opencode/oh-my-opencode.json"
else
  cat > "$OHMY_CONFIG_HOME/opencode/oh-my-opencode.json" <<'JSON'
{
  "$schema": "https://raw.githubusercontent.com/code-yeongyu/oh-my-opencode/dev/assets/oh-my-opencode.schema.json"
}
JSON
fi

# Add zsh alias if missing.
ALIAS_LINE="alias opencode-ohmy='XDG_CONFIG_HOME=$OHMY_CONFIG_HOME opencode'"
if [[ -f "$ZSHRC_FILE" ]]; then
  if ! rg -q "^alias opencode-ohmy=" "$ZSHRC_FILE"; then
    printf "\n%s\n" "$ALIAS_LINE" >> "$ZSHRC_FILE"
  fi
else
  printf "%s\n" "$ALIAS_LINE" >> "$ZSHRC_FILE"
fi

echo "Done. Default: opencode (my_opencode). Alternate: opencode-ohmy (oh-my-opencode)."
