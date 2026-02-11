#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/dmoliveira/my_opencode.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.config/opencode/my_opencode}"
CONFIG_DIR="$HOME/.config/opencode"
CONFIG_PATH="$CONFIG_DIR/opencode.json"

if ! command -v git >/dev/null 2>&1; then
  printf "Error: git is required but not installed.\n" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  printf "Updating existing config repo at %s\n" "$INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --all --prune
  git -C "$INSTALL_DIR" pull --ff-only
else
  if [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR/.git" ]; then
    printf "Error: %s exists and is not a git repository.\n" "$INSTALL_DIR" >&2
    exit 1
  fi
  printf "Cloning config repo into %s\n" "$INSTALL_DIR"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

chmod +x "$INSTALL_DIR/scripts/mcp_command.py" "$INSTALL_DIR/scripts/plugin_command.py"
ln -sfn "$INSTALL_DIR/opencode.json" "$CONFIG_PATH"

printf "\nDone! ✅\n"
printf "Config linked: %s -> %s\n" "$CONFIG_PATH" "$INSTALL_DIR/opencode.json"
printf "\nOpen OpenCode and use:\n"
printf "  /mcp status\n"
printf "  /mcp enable context7\n"
printf "  /mcp disable context7\n"
printf "  /plugin status\n"
printf "  /plugin doctor\n"
printf "  /plugin enable supermemory\n"
printf "  /plugin disable supermemory\n"
