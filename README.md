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
- 🩺 Built-in `/doctor` umbrella command for one-shot health checks.
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
- run a post-install self-check (`/mcp status`, `/plugin status`, `/notify status`, `/digest show`, `/telemetry status`, `/post-session status`, `/policy status`, `/doctor run`, `/plugin doctor`)

## Manual install 🛠️

```bash
git clone https://github.com/dmoliveira/my_opencode.git ~/.config/opencode/my_opencode
ln -sfn ~/.config/opencode/my_opencode/opencode.json ~/.config/opencode/opencode.json
chmod +x ~/.config/opencode/my_opencode/install.sh ~/.config/opencode/my_opencode/scripts/mcp_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/plugin_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/notify_command.py ~/.config/opencode/my_opencode/scripts/session_digest.py ~/.config/opencode/my_opencode/scripts/opencode_session.sh ~/.config/opencode/my_opencode/scripts/telemetry_command.py ~/.config/opencode/my_opencode/scripts/post_session_command.py ~/.config/opencode/my_opencode/scripts/policy_command.py ~/.config/opencode/my_opencode/scripts/doctor_command.py
```

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

`/doctor` runs diagnostics across `mcp`, `plugin`, `notify`, `digest`, `telemetry`, `post-session`, and `policy` in one pass.

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

`/notify` writes preferences to `~/.config/opencode/opencode-notifications.json` with controls at four levels:
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

`/post-session` writes to `~/.config/opencode/opencode-session.json`:
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

`/policy` writes profile metadata to `~/.config/opencode/opencode-policy.json` and applies the corresponding notification posture to `~/.config/opencode/opencode-notifications.json`.

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

`/telemetry` writes to `~/.config/opencode/opencode-telemetry.json` and supports:
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
- `install.sh` - one-step installer/updater
- `Makefile` - common maintenance commands (`make help`)
- `.github/workflows/ci.yml` - CI checks and installer smoke test

## Maintenance commands 🛠️

```bash
make help
make validate
make selftest
make doctor
make doctor-json
make install-test
make release VERSION=0.1.1
```

Tip: for local branch testing, installer accepts `REPO_REF`.

Happy shipping! 😄
