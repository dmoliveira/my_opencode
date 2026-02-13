#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/dmoliveira/my_opencode.git}"
REPO_REF="${REPO_REF:-}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.config/opencode/my_opencode}"
CONFIG_DIR="$HOME/.config/opencode"
CONFIG_PATH="$CONFIG_DIR/opencode.json"
NON_INTERACTIVE=false
SKIP_SELF_CHECK=false
RUN_WIZARD=false
WIZARD_RECONFIGURE=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --non-interactive)
      NON_INTERACTIVE=true
      ;;
    --skip-self-check)
      SKIP_SELF_CHECK=true
      ;;
    --wizard)
      RUN_WIZARD=true
      ;;
    --reconfigure)
      WIZARD_RECONFIGURE=true
      ;;
    -h|--help)
      printf "Usage: %s [--non-interactive] [--skip-self-check] [--wizard] [--reconfigure]\n" "$0"
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

if [ -n "$REPO_REF" ]; then
  printf "Checking out repo ref %s\n" "$REPO_REF"
  git -C "$INSTALL_DIR" fetch --all --prune >/dev/null 2>&1 || true
  git -C "$INSTALL_DIR" checkout "$REPO_REF"
fi

chmod +x "$INSTALL_DIR/scripts/mcp_command.py" "$INSTALL_DIR/scripts/plugin_command.py" "$INSTALL_DIR/scripts/notify_command.py" "$INSTALL_DIR/scripts/session_digest.py" "$INSTALL_DIR/scripts/opencode_session.sh" "$INSTALL_DIR/scripts/telemetry_command.py" "$INSTALL_DIR/scripts/post_session_command.py" "$INSTALL_DIR/scripts/policy_command.py" "$INSTALL_DIR/scripts/doctor_command.py" "$INSTALL_DIR/scripts/config_command.py" "$INSTALL_DIR/scripts/stack_profile_command.py" "$INSTALL_DIR/scripts/install_wizard.py" "$INSTALL_DIR/scripts/nvim_integration_command.py" "$INSTALL_DIR/scripts/devtools_command.py" "$INSTALL_DIR/scripts/background_task_manager.py" "$INSTALL_DIR/scripts/refactor_lite_command.py"
ln -sfn "$INSTALL_DIR/opencode.json" "$CONFIG_PATH"

if [ "$RUN_WIZARD" = true ]; then
  printf "\nRunning install wizard...\n"
  WIZARD_ARGS=()
  if [ "$WIZARD_RECONFIGURE" = true ]; then
    WIZARD_ARGS+=("--reconfigure")
  fi
  if [ "$NON_INTERACTIVE" = true ]; then
    WIZARD_ARGS+=("--non-interactive")
  fi
  python3 "$INSTALL_DIR/scripts/install_wizard.py" "${WIZARD_ARGS[@]}"
fi

if [ "$SKIP_SELF_CHECK" = false ]; then
  printf "\nRunning self-check...\n"
  python3 "$INSTALL_DIR/scripts/mcp_command.py" status
  python3 "$INSTALL_DIR/scripts/plugin_command.py" status
  python3 "$INSTALL_DIR/scripts/notify_command.py" status
  python3 "$INSTALL_DIR/scripts/notify_command.py" doctor
  python3 "$INSTALL_DIR/scripts/session_digest.py" show || true
  python3 "$INSTALL_DIR/scripts/session_digest.py" doctor
  python3 "$INSTALL_DIR/scripts/telemetry_command.py" status
  python3 "$INSTALL_DIR/scripts/post_session_command.py" status
  python3 "$INSTALL_DIR/scripts/policy_command.py" status
  python3 "$INSTALL_DIR/scripts/config_command.py" status
  python3 "$INSTALL_DIR/scripts/config_command.py" layers
  python3 "$INSTALL_DIR/scripts/background_task_manager.py" status
  python3 "$INSTALL_DIR/scripts/background_task_manager.py" doctor --json
  python3 "$INSTALL_DIR/scripts/stack_profile_command.py" status
  python3 "$INSTALL_DIR/scripts/nvim_integration_command.py" status
  python3 "$INSTALL_DIR/scripts/devtools_command.py" status
  python3 "$INSTALL_DIR/scripts/doctor_command.py" run || true
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
printf "  /mcp help\n"
printf "  /mcp doctor\n"
printf "  /mcp enable context7\n"
printf "  /mcp disable context7\n"
printf "  /plugin status\n"
printf "  /plugin doctor\n"
printf "  /doctor run\n"
printf "  /notify status\n"
printf "  /notify profile focus\n"
printf "  /notify doctor\n"
printf "  /digest run --reason manual\n"
printf "  /digest-run-post\n"
printf "  /digest show\n"
printf "  /digest doctor\n"
printf "  /telemetry status\n"
printf "  /telemetry profile local\n"
printf "  /post-session status\n"
printf "  /policy profile strict\n"
printf "  /config status\n"
printf "  /config layers\n"
printf "  /config backup\n"
printf "  /bg status\n"
printf "  /bg doctor --json\n"
printf "  /stack apply focus\n"
printf "  /nvim status\n"
printf "  /devtools status\n"
printf "  /devtools install all\n"
printf "  /nvim install minimal --link-init\n"
printf "  ~/.config/opencode/my_opencode/install.sh --wizard --reconfigure\n"
printf "  /doctor-json\n"
printf "  /setup-keys\n"
printf "  /plugin enable supermemory\n"
printf "  /plugin disable supermemory\n"
