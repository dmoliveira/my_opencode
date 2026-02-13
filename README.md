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
- 🔔 Built-in `/notify` command to tune notification behavior by level (all, channel, event, per-channel event).
- 🧾 Built-in `/digest` command for session snapshots and optional exit hooks.
- 📡 Built-in `/telemetry` command to manage LangGraph/local event forwarding.
- ✅ Built-in `/post-session` command to configure auto test/lint hooks on session end.
- 🛡️ Built-in `/policy` command for strict/balanced/fast permission-risk presets.
- 🧵 Built-in `/bg` command for minimal background job orchestration and retrieval.
- 🧱 Built-in `/refactor-lite` command for preflighted, safe-first refactor workflows.
- 🩺 Built-in `/doctor` umbrella command for one-shot health checks.
- 💾 Built-in `/config` command for backup/restore snapshots.
- 🧩 Built-in `/stack` bundles for coordinated multi-command profiles.
- 🧠 Built-in `/nvim` command to install and validate deeper `opencode.nvim` keymap integration.
- 🧰 Built-in `/devtools` command to manage external productivity tooling.
- 💸 Better token control by enabling `context7` / `gh_grep` only on demand.
- 🔒 Autonomous-friendly permissions for trusted project paths.
- 🔁 Easy updates by rerunning the installer.
- 🧩 Clear, versioned config for experiments and rollbacks.

## Roadmap plan 🗺️

- Track upcoming orchestration features in `IMPLEMENTATION_ROADMAP.md`.

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

## Ecosystem extensions (optional) 🧰

These are not managed by `opencode.json` plugins, but they pair well with this setup.

### 1) Neovim integration: `opencode.nvim`

- Repo: `nickjvandyke/opencode.nvim`
- Best for editor-native OpenCode workflows (selection-aware prompts, statusline, and provider controls)

Minimal `lazy.nvim` setup:

```lua
{
  "nickjvandyke/opencode.nvim",
  config = function()
    vim.o.autoread = true
    vim.keymap.set({ "n", "x" }, "<leader>oa", function()
      require("opencode").ask("@this: ", { submit = true })
    end, { desc = "Ask opencode" })
    vim.keymap.set({ "n", "x" }, "<leader>os", function()
      require("opencode").select()
    end, { desc = "Select opencode action" })
  end,
}
```

Quick verify inside Neovim:

```vim
:checkhealth opencode
```

Use OpenCode-native setup and diagnostics:

```text
/nvim status
/nvim help
/nvim install minimal --link-init
/nvim install power --link-init
/nvim doctor
/nvim doctor --json
/nvim uninstall --unlink-init
```

Autocomplete-friendly shortcuts:

```text
/nvim-help
/nvim-status
/nvim-install-minimal
/nvim-install-power
/nvim-doctor-json
```

Profiles:
- `minimal`: two keymaps (`<leader>oa`, `<leader>os`) for fast ask/select loops.
- `power`: adds draft ask and health shortcuts for heavier editor-driven workflows.

Installed integration file path:
- `~/.config/nvim/lua/my_opencode/opencode.lua`

When `--link-init` is used, the command appends:
- `require("my_opencode.opencode")` to `~/.config/nvim/init.lua`.

### 2) Rich desktop/web UI: `OpenChamber`

- Repo: `btriapitsyn/openchamber`
- Best for visual session management, remote/browser access, and mobile continuation

Install and run:

```bash
npm install -g @openchamber/web
openchamber --port 3000
```

Useful commands:

```bash
openchamber status
openchamber serve --daemon --port 3111
openchamber stop --port 3111
```

### Evaluation result

- `opencode.nvim`: recommended when your main loop is Neovim and you want context-rich editor prompts.
- `OpenChamber`: recommended when you want a richer visual layer over OpenCode sessions and remote access.
- Keep both optional; core repo behavior remains terminal-first and fully functional without them.

## External productivity tooling (outside OpenCode) ⚙️

Recommended baseline stack:

- `direnv` for per-project environment auto-loading (`.envrc`).
- `gh-dash` for terminal-native GitHub issue/PR/check workflow.
- `ripgrep-all` (`rga`) for broad content search beyond plain source files.
- `pre-commit` + `lefthook` for fast local hooks aligned with CI checks.

Use these directly in OpenCode:

```text
/devtools status
/devtools help
/devtools install all
/devtools doctor
/devtools doctor --json
/devtools hooks-install
```

Autocomplete-friendly shortcuts:

```text
/devtools-help
/devtools-install
/devtools-doctor-json
```

First-time shell setup for direnv (`zsh`):

```bash
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
```

Project setup for direnv:

```bash
cp .envrc.example .envrc
direnv allow
```

Notes:
- This repo ships `lefthook.yml` and `.pre-commit-config.yaml`.
- `gh-dash` is installed as a GitHub CLI extension (`gh extension install dlvhdr/gh-dash`).
- For Node-only repositories, Husky is also a valid alternative to Lefthook.

## Quick install (popular way) ⚡

Run this from anywhere:

```bash
curl -fsSL https://raw.githubusercontent.com/dmoliveira/my_opencode/main/install.sh | bash
```

CI/non-interactive mode:

```bash
curl -fsSL https://raw.githubusercontent.com/dmoliveira/my_opencode/main/install.sh | bash -s -- --non-interactive
```

Run guided setup/reconfigure wizard:

```bash
curl -fsSL https://raw.githubusercontent.com/dmoliveira/my_opencode/main/install.sh | bash -s -- --wizard
```

Run wizard on an existing install:

```bash
~/.config/opencode/my_opencode/install.sh --wizard --reconfigure
```

This will:

- clone or update this repo into `~/.config/opencode/my_opencode`
- link `~/.config/opencode/opencode.json` to this repo config
- enable `/mcp` command backend automatically
- run a post-install self-check (`/mcp status`, `/plugin status`, `/notify status`, `/digest show`, `/telemetry status`, `/post-session status`, `/policy status`, `/config status`, `/bg status`, `/refactor-lite profile --scope scripts/*.py --dry-run --json`, `/stack status`, `/doctor run`, `/plugin doctor`)

## Manual install 🛠️

```bash
git clone https://github.com/dmoliveira/my_opencode.git ~/.config/opencode/my_opencode
ln -sfn ~/.config/opencode/my_opencode/opencode.json ~/.config/opencode/opencode.json
chmod +x ~/.config/opencode/my_opencode/install.sh ~/.config/opencode/my_opencode/scripts/mcp_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/plugin_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/notify_command.py ~/.config/opencode/my_opencode/scripts/session_digest.py ~/.config/opencode/my_opencode/scripts/opencode_session.sh ~/.config/opencode/my_opencode/scripts/telemetry_command.py ~/.config/opencode/my_opencode/scripts/post_session_command.py ~/.config/opencode/my_opencode/scripts/policy_command.py ~/.config/opencode/my_opencode/scripts/doctor_command.py ~/.config/opencode/my_opencode/scripts/config_command.py ~/.config/opencode/my_opencode/scripts/stack_profile_command.py ~/.config/opencode/my_opencode/scripts/install_wizard.py ~/.config/opencode/my_opencode/scripts/nvim_integration_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/devtools_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/background_task_manager.py
```

## Install wizard flow 🧭

The wizard lets each user decide what they want now and reconfigure later.

- Select plugin profile (`lean`, `stable`, `experimental`, or custom plugin-by-plugin).
- Select MCP, policy, telemetry, and post-session defaults.
- Optionally install/uninstall ecosystem integrations (`opencode.nvim`, `OpenChamber`).
- When `opencode.nvim` is selected, wizard bootstraps a minimal integration profile at `~/.config/nvim/lua/my_opencode/opencode.lua`.
- Re-run any time to change choices: `~/.config/opencode/my_opencode/install.sh --wizard --reconfigure`.
- Wizard state is stored in `~/.config/opencode/my_opencode-install-state.json`.

## Stack bundles inside OpenCode 🧩

Use these directly in OpenCode:

```text
/stack status
/stack help
/stack apply focus
/stack apply research
/stack apply quiet-ci
```

Autocomplete-friendly shortcuts:

```text
/stack-help
/stack-focus
/stack-research
/stack-quiet-ci
```

Profiles:
- `focus`: notify focus, telemetry off, post-session disabled, policy strict
- `research`: notify all, telemetry local, post-session enabled with `make selftest`, policy balanced
- `quiet-ci`: notify quiet + no complete event, telemetry off, post-session manual `make validate`, policy strict

## Config backup inside OpenCode 💾

Use these directly in OpenCode:

```text
/config status
/config layers
/config layers --json
/config backup
/config backup --name pre-upgrade
/config list
/config restore <backup-id>
```

Autocomplete-friendly shortcuts:

```text
/config-help
/config-backup
/config-list
/config-layers
/config-layers-json
```

`/config` snapshots all `opencode*.json` files under `~/.config/opencode/` into `~/.config/opencode/my_opencode-backups/`.

`/config layers` shows effective layered config precedence and selected write path.

## Layered config precedence 🧩

`/mcp`, `/plugin`, `/notify`, `/telemetry`, `/post-session`, `/policy`, and `/stack` now resolve configuration with stable layered precedence:

1. `OPENCODE_CONFIG_PATH` (runtime override, highest priority)
2. `.opencode/my_opencode.jsonc` (project override)
3. `.opencode/my_opencode.json`
4. `~/.config/opencode/my_opencode.jsonc` (user override)
5. `~/.config/opencode/my_opencode.json`
6. `~/.config/opencode/opencode.jsonc` (legacy user override)
7. `~/.config/opencode/opencode.json` (legacy user override)
8. bundled `opencode.json` from this repo (base)

Notes:
- Merge behavior is deep for objects and replace-on-write for arrays.
- JSONC files support comments and trailing commas.
- Writes target the highest-precedence existing config path (or `~/.config/opencode/opencode.json` when no override exists).
- Legacy per-command files remain supported for compatibility and env-var override use.

## Unified doctor inside OpenCode 🩺

Use these directly in OpenCode:

```text
/doctor run
/doctor run --json
/doctor help
```

Autocomplete-friendly shortcuts:

```text
/doctor-json
/doctor-help
```

`/doctor` runs diagnostics across `mcp`, `plugin`, `notify`, `digest`, `telemetry`, `post-session`, `policy`, `bg`, and optional `refactor-lite` checks in one pass.

## Refactor workflow backend inside OpenCode 🧱

Use these directly in OpenCode:

```text
/refactor-lite <target>
/refactor-lite <target> --scope scripts/*.py --dry-run --json
/refactor-lite <target> --scope scripts/*.py --run-selftest --json
```

Autocomplete-friendly shortcuts:

```text
/refactor-lite-help
/refactor-lite-dry-run <target> --scope scripts/*.py
```

`/refactor-lite` backend behavior:
- runs deterministic preflight analysis (target search + file map)
- defaults to `--strategy safe` guardrails
- executes verification hooks on non-dry runs (`make validate`, optional `make selftest`)

Strategies:
- `safe` (default): blocks ambiguous broad targets unless scope is narrowed.
- `balanced`: broader analysis with the same verification expectations.
- `aggressive`: explicit opt-in for broad target analysis when ambiguity is acceptable.

Recommended flow:
1. Start with `--dry-run --json` and inspect `preflight.file_map`.
2. Narrow with `--scope` until safe mode is deterministic.
3. Run without `--dry-run` to enforce verification hooks.

## Background jobs inside OpenCode 🧵

Use these directly in OpenCode:

```text
/bg start -- python3 scripts/selftest.py
/bg status
/bg status <job-id>
/bg list
/bg list --status running
/bg read <job-id>
/bg cancel <job-id>
/bg cleanup
/bg doctor --json
/bg status --json
```

Autocomplete-friendly shortcuts:

```text
/bg-help
/bg-list
/bg-running
/bg-doctor-json
/bg-status-json
```

`/bg` uses `~/.config/opencode/my_opencode/bg/` by default with:
- `jobs.json` as authoritative state
- `runs/<job-id>.log` for combined stdout/stderr
- `runs/<job-id>.meta.json` for execution metadata

Examples:
- Basic async start + read: `/bg start -- make validate` then `/bg list --status running` and `/bg read <job-id>`
- Intermediate queue workflow: `/bg enqueue -- make selftest`, `/bg enqueue -- make install-test`, then `/bg run --max-jobs 1`
- Failure/recovery: `/bg start -- python3 -c "import time; time.sleep(5)" --timeout-seconds 1`, inspect with `/bg doctor --json`, then `/bg cleanup`

Notification behavior:
- Background terminal states emit optional alerts through the existing notify stack (`notify` config event/channel rules).
- Set `MY_OPENCODE_BG_NOTIFICATIONS_ENABLED=0` to suppress background notifications without changing global notify settings.

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

## Notification control inside OpenCode 🔔

Use these directly in OpenCode:

```text
/notify status
/notify help
/notify doctor
/notify doctor --json
/notify profile all
/notify profile quiet
/notify profile focus
/notify profile sound-only
/notify profile visual-only
/notify enable all
/notify disable all
/notify enable sound
/notify disable visual
/notify disable complete
/notify enable permission
/notify channel question sound off
/notify channel error visual on
```

Autocomplete-friendly shortcuts:

```text
/notify-help
/notify-doctor
/notify-doctor-json
/notify-profile-all
/notify-profile-focus
/notify-sound-only
/notify-visual-only
```

`/notify` writes preferences into layered config under `notify` (or `OPENCODE_NOTIFICATIONS_PATH` when explicitly set):
- global: `enabled`
- channel: `sound.enabled`, `visual.enabled`
- event: `events.<type>`
- per-event channel: `channels.<type>.sound|visual`

## Session digest inside OpenCode 🧾

Use these directly in OpenCode:

```text
/digest run --reason manual
/digest run --reason manual --run-post
/digest show
/digest doctor
/digest doctor --json
```

Autocomplete-friendly shortcuts:

```text
/digest-run
/digest-run-post
/digest-show
/digest-doctor
/digest-doctor-json
```

The digest command writes to `~/.config/opencode/digests/last-session.json` by default.

For automatic digest-on-exit behavior (including `Ctrl+C`), launch OpenCode through:

```bash
~/.config/opencode/my_opencode/scripts/opencode_session.sh
```

Optional environment variables:
- `MY_OPENCODE_DIGEST_PATH` custom output path
- `MY_OPENCODE_DIGEST_HOOK` command to run after digest is written
- `DIGEST_REASON_ON_EXIT` custom reason label (default `exit`)

When `--run-post` is used, digest also evaluates `post_session` config and stores hook results in the digest JSON.

## Post-session hook inside OpenCode ✅

Use these directly in OpenCode:

```text
/post-session status
/post-session enable
/post-session disable
/post-session set command make test
/post-session set timeout 120000
/post-session set run-on exit,manual
```

Autocomplete-friendly shortcuts:

```text
/post-session-help
/post-session-enable
```

`/post-session` writes to layered config under `post_session` (or `MY_OPENCODE_SESSION_CONFIG_PATH` when explicitly set):
- `post_session.enabled`
- `post_session.command`
- `post_session.timeout_ms`
- `post_session.run_on` (`exit`, `manual`, `idle`)

Typical flow:
1. Configure command with `/post-session set command <your-test-or-lint-command>`
2. Enable with `/post-session enable`
3. Use wrapper `opencode_session.sh` so command runs automatically on exit/Ctrl+C
4. Optionally run now with `/digest run --reason manual --run-post`

## Permission policy profiles inside OpenCode 🛡️

Use these directly in OpenCode:

```text
/policy status
/policy help
/policy profile strict
/policy profile balanced
/policy profile fast
```

Autocomplete-friendly shortcuts:

```text
/policy-help
/policy-profile-strict
/policy-profile-balanced
/policy-profile-fast
```

`/policy` writes profile metadata to layered config under `policy` and applies notification posture under `notify` (legacy path env overrides remain supported).

Profiles:
- `strict`: visual alerts for high-risk events, minimal noise
- `balanced`: visual for all events, sound on risk-heavy events
- `fast`: all channels and events enabled for immediate feedback

## Telemetry forwarding inside OpenCode 📡

Use these directly in OpenCode:

```text
/telemetry status
/telemetry help
/telemetry doctor
/telemetry doctor --json
/telemetry profile off
/telemetry profile local
/telemetry profile errors-only
/telemetry set endpoint http://localhost:3000/opencode/events
/telemetry set timeout 1500
/telemetry enable error
/telemetry disable question
```

Autocomplete-friendly shortcuts:

```text
/telemetry-help
/telemetry-doctor
/telemetry-doctor-json
/telemetry-profile-off
/telemetry-profile-local
```

`/telemetry` writes to layered config under `telemetry` (or `OPENCODE_TELEMETRY_PATH` when explicitly set) and supports:
- global on/off (`enabled`)
- endpoint URL (`endpoint`)
- timeout (`timeout_ms`)
- per-event toggles (`events.complete|error|permission|question`)

For your LangGraph setup, default endpoint target is `http://localhost:3000/opencode/events`.

## Repo layout 📦

- `opencode.json` - global OpenCode config (linked to default path)
- `scripts/mcp_command.py` - backend script for `/mcp`
- `scripts/plugin_command.py` - backend script for `/plugin`
- `scripts/notify_command.py` - backend script for `/notify`
- `scripts/session_digest.py` - backend script for `/digest`
- `scripts/opencode_session.sh` - optional wrapper to run digest on process exit
- `scripts/telemetry_command.py` - backend script for `/telemetry`
- `scripts/post_session_command.py` - backend script for `/post-session`
- `scripts/policy_command.py` - backend script for `/policy`
- `scripts/doctor_command.py` - backend script for `/doctor`
- `scripts/config_command.py` - backend script for `/config`
- `scripts/stack_profile_command.py` - backend script for `/stack`
- `scripts/install_wizard.py` - interactive install/reconfigure wizard
- `scripts/nvim_integration_command.py` - backend script for `/nvim`
- `scripts/devtools_command.py` - backend script for `/devtools`
- `scripts/config_layering.py` - shared layered config + JSONC loader for command scripts
- `install.sh` - one-step installer/updater
- `Makefile` - common maintenance commands (`make help`)
- `.pre-commit-config.yaml` - pre-commit hook definitions
- `lefthook.yml` - fast git hook runner config
- `.envrc.example` - direnv template for local environment variables
- `.github/workflows/ci.yml` - CI checks and installer smoke test

## Maintenance commands 🛠️

```bash
make help
make validate
make selftest
make doctor
make doctor-json
make devtools-status
make hooks-install
make install-test
make release-check
make release VERSION=0.1.1
```

Tip: for local branch testing, installer accepts `REPO_REF`.

Happy shipping! 😄
