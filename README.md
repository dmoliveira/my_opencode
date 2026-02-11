# my_opencode 🚀

Welcome to my OpenCode command center! ✨

This repo gives you a clean, portable OpenCode setup with fast MCP controls inside OpenCode itself. Keep autonomous coding smooth, and only turn on external context when you actually need it. ⚡

## Why this setup rocks 🎯

- **One source of truth** for global OpenCode config.
- **Token-aware workflow** by keeping heavy MCPs disabled by default.
- **Instant MCP toggling** with `/mcp` commands in the OpenCode prompt.
- **Portable install** with a one-liner script and symlinked default config path.
- **Worktree-friendly repo** so you can iterate on config safely in feature branches.

## Features and benefits 🌟

- 🧠 Built-in `/mcp` command for `status`, `enable`, and `disable`.
- 🎛️ Built-in `/plugin` command to enable or disable plugins without editing JSON.
- 💸 Better token control by enabling `context7` / `gh_grep` only on demand.
- 🔒 Autonomous-friendly permissions for trusted project paths.
- 🔁 Easy updates by rerunning the installer.
- 🧩 Clear, versioned config for experiments and rollbacks.

## Installed plugin stack 🔌

- `@mohak34/opencode-notifier@latest` - desktop and sound alerts for completion, errors, and permission prompts.
- `opencode-supermemory` - persistent memory across sessions.
- `opencode-wakatime` - tracks OpenCode coding activity and AI line changes in WakaTime.

### Experimental plugin options 🧪

- `github:kdcokenny/opencode-worktree` - git worktree automation with terminal spawning for isolated agent sessions.
- `github:JRedeker/opencode-morph-fast-apply` - high-speed Morph Fast Apply edits for large or scattered code changes.

These two can fail to auto-resolve on some setups and are disabled by default. Enable them only when you want to test them.

## Installed instruction packs 📘

- `instructions/shell_strategy.md` - non-interactive shell strategy rules to avoid hangs and improve autonomous execution.

## Quick install (popular way) ⚡

Run this from anywhere:

```bash
curl -fsSL https://raw.githubusercontent.com/dmoliveira/my_opencode/main/install.sh | bash
```

CI/non-interactive mode:

```bash
curl -fsSL https://raw.githubusercontent.com/dmoliveira/my_opencode/main/install.sh | bash -s -- --non-interactive
```

This will:

- clone or update this repo into `~/.config/opencode/my_opencode`
- link `~/.config/opencode/opencode.json` to this repo config
- enable `/mcp` command backend automatically
- run a post-install self-check (`/mcp status`, `/plugin status`, `/plugin doctor`)

## Manual install 🛠️

```bash
git clone https://github.com/dmoliveira/my_opencode.git ~/.config/opencode/my_opencode
ln -sfn ~/.config/opencode/my_opencode/opencode.json ~/.config/opencode/opencode.json
chmod +x ~/.config/opencode/my_opencode/install.sh ~/.config/opencode/my_opencode/scripts/mcp_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/plugin_command.py
```

## MCP control inside OpenCode 🧠

Use these directly in OpenCode:

```text
/mcp status
/mcp help
/mcp doctor
/mcp doctor --json
/mcp profile minimal
/mcp profile research
/mcp profile context7
/mcp profile ghgrep
/mcp enable context7
/mcp disable context7
/mcp enable gh_grep
/mcp disable gh_grep
/mcp enable all
/mcp disable all
```

MCP autocomplete-friendly shortcuts:

```text
/mcp-help
/mcp-doctor
/mcp-doctor-json
/mcp-profile-minimal
/mcp-profile-research
/mcp-profile-context7
/mcp-profile-ghgrep
```

## Plugin control inside OpenCode 🎛️

Use these directly in OpenCode:

```text
/plugin status
/plugin help
/plugin doctor
/plugin doctor --json
/setup-keys
/plugin enable supermemory
/plugin disable supermemory
/plugin profile lean
/plugin profile stable
/plugin profile experimental
/plugin enable notifier
/plugin disable notifier
/plugin enable all
/plugin disable all
```

Autocomplete-friendly shortcuts:

```text
/plugin-help
/plugin-enable-notifier
/plugin-enable-supermemory
/plugin-enable-wakatime
/plugin-enable-morph
/plugin-enable-worktree
/plugin-profile-lean
/plugin-profile-stable
/plugin-profile-experimental
/plugin-doctor-json
```

Supported plugin names: `notifier`, `supermemory`, `morph`, `worktree`, `wakatime`.

`all` applies only to the stable set: `notifier`, `supermemory`, `wakatime`.

`/plugin doctor` checks the current plugin setup and reports missing prerequisites before you enable additional plugins.

`/plugin doctor --json` (or `/plugin-doctor-json`) prints machine-readable diagnostics for automation.

`/setup-keys` prints exact environment/file snippets for missing API keys.

Profiles:
- `lean` -> `notifier`
- `stable` -> `notifier`, `supermemory`, `wakatime`
- `experimental` -> `stable` + `morph`, `worktree`

For Morph Fast Apply, set `MORPH_API_KEY` in your shell before enabling `morph`.

For WakaTime, configure `~/.wakatime.cfg` with your `api_key` before enabling `wakatime`.

## Repo layout 📦

- `opencode.json` - global OpenCode config (linked to default path)
- `scripts/mcp_command.py` - backend script for `/mcp`
- `scripts/plugin_command.py` - backend script for `/plugin`
- `install.sh` - one-step installer/updater
- `Makefile` - common maintenance commands (`make help`)
- `.github/workflows/ci.yml` - CI checks and installer smoke test

## Maintenance commands 🛠️

```bash
make help
make validate
make doctor
make doctor-json
make install-test
make release VERSION=0.1.1
```

Tip: for local branch testing, installer accepts `REPO_REF`.

Happy shipping! 😄
