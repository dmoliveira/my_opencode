#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/dmoliveira/my_opencode.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.config/opencode/my_opencode}"
CONFIG_DIR="$HOME/.config/opencode"
CONFIG_PATH="$CONFIG_DIR/opencode.json"
NON_INTERACTIVE=false
SKIP_SELF_CHECK=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --non-interactive)
      NON_INTERACTIVE=true
      ;;
    --skip-self-check)
      SKIP_SELF_CHECK=true
      ;;
    -h|--help)
      printf "Usage: %s [--non-interactive] [--skip-self-check]\n" "$0"
      exit 0
      ;;
    *)
      printf "Error: unknown argument: %s\n" "$1" >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v git >/dev/null 2>&1; then
  printf "Error: git is required but not installed.\n" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf "Error: python3 is required but not installed.\n" >&2
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

if [ "$SKIP_SELF_CHECK" = false ]; then
  printf "\nRunning self-check...\n"
  python3 "$INSTALL_DIR/scripts/mcp_command.py" status
  python3 "$INSTALL_DIR/scripts/plugin_command.py" status
  if ! python3 "$INSTALL_DIR/scripts/plugin_command.py" doctor; then
    if [ "$NON_INTERACTIVE" = true ]; then
      printf "\nSelf-check failed in non-interactive mode.\n" >&2
      exit 1
    fi
    printf "\nSelf-check reported missing prerequisites; setup can continue.\n"
    python3 "$INSTALL_DIR/scripts/plugin_command.py" setup-keys
  fi
fi

printf "\nDone! ✅\n"
printf "Config linked: %s -> %s\n" "$CONFIG_PATH" "$INSTALL_DIR/opencode.json"
printf "\nOpen OpenCode and use:\n"
printf "  /mcp status\n"
printf "  /mcp enable context7\n"
printf "  /mcp disable context7\n"
printf "  /plugin status\n"
printf "  /plugin doctor\n"
printf "  /setup-keys\n"
printf "  /plugin enable supermemory\n"
printf "  /plugin disable supermemory\n"
