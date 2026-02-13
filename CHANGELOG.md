# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Adds
- Added ecosystem extension guidance for `opencode.nvim` (Neovim integration) and `OpenChamber` (desktop/web UI).
- Added install and verification commands for both optional integrations.
- Added `scripts/install_wizard.py` for guided install/reconfigure flows across plugin, MCP, policy, telemetry, post-session, and optional ecosystem integrations.
- Added installer flags `--wizard` and `--reconfigure` for guided setup and repeatable reconfiguration.
- Added `/nvim` command suite with installable Neovim keymap profiles (`minimal`, `power`) plus status/doctor/uninstall flows.
- Added autocomplete shortcuts for Neovim integration workflows and JSON diagnostics.
- Added `/devtools` command suite for external productivity tooling status, doctor, install, and hook bootstrap flows.
- Added `.pre-commit-config.yaml`, `lefthook.yml`, and `.envrc.example` to standardize local productivity setup.
- Added `scripts/config_layering.py` with shared layered config discovery and JSONC parsing support.
- Added `/config layers` (and `--json`) to inspect layered config precedence and effective write path.
- Added `instructions/background_task_model.md` defining lifecycle, storage schema, retention, concurrency, and stale-timeout defaults for Epic 2 background orchestration.

### Changes
- Documented extension evaluation outcomes and when each tool is the better fit.
- Expanded install smoke and self-tests to cover non-interactive wizard execution paths.
- Expanded install smoke and selftest coverage for Neovim integration provisioning.
- Expanded installer and README guidance for direnv, gh-dash, ripgrep-all, and pre-commit + lefthook workflows.
- Updated `/mcp` and `/plugin` to resolve layered project/user config with runtime override support.
- Added selftest coverage for layered config precedence (`project > user > base`) and JSONC parsing.
- Expanded installer/readme/install-test coverage for layered config diagnostics.
- Migrated `/notify`, `/telemetry`, `/post-session`, `/policy`, and `/stack` state to layered config sections with legacy file fallback and env-var compatibility overrides.
- Expanded selftest coverage to validate layered command-state writes for telemetry/policy/post-session flows.

## v0.2.0 - 2026-02-12

### Adds
- Added `/notify` command with granular controls (global, channel, event, and per-event channel), plus shortcut commands and presets.
- Added `/digest` command enhancements including `--run-post`, plus a session wrapper script for digest on exit/Ctrl+C.
- Added `/telemetry` command for LangGraph/local endpoint forwarding with endpoint, timeout, per-event toggles, and diagnostics.
- Added `/post-session` command to configure and run post-session test/lint hooks with timeout and run-on policies.
- Added `/policy` command with `strict`, `balanced`, and `fast` permission-risk presets.
- Added `/notify doctor` and `/digest doctor` diagnostics with JSON output for automation.

### Changes
- Expanded installer self-check and command hints to include notify, digest, telemetry, post-session, and policy workflows.
- Expanded deterministic self-tests and `make install-test` coverage across notify, digest, telemetry, post-session, and policy flows.
- Updated README with complete usage, shortcuts, and configuration guidance for new command groups.

### Fixes
- Hardened notification config parsing to safely handle invalid/non-boolean values.

## v0.1.1 - 2026-02-12

### Adds
- Added `/plugin doctor --json` output for automation and CI integrations.
- Added plugin command next-step suggestions and `/plugin help` guidance output.
- Added autocomplete-friendly shortcut commands like `/plugin-enable-supermemory` and `/plugin-profile-stable`.
- Added GitHub Actions CI workflow for script/config validation and installer smoke tests.
- Added `Makefile` with `help`, `validate`, `doctor`, `doctor-json`, `install-test`, and `release` targets.

### Changes
- Expanded README with maintenance commands and machine-readable diagnostics usage.

### Fixes
- Added `.gitignore` entries for Python cache artifacts.

## v0.1.0 - 2026-02-11

### Adds
- Added portable OpenCode config with global symlink-based install flow.
- Added `/mcp` command with internal toggles for `context7` and `gh_grep`.
- Added `/plugin` command with stable/experimental plugin management.
- Added `/plugin doctor` diagnostics for plugin prerequisites.
- Added `/setup-keys` command for copy-paste API key setup snippets.
- Added installer self-check and `--non-interactive` mode for CI/bootstrap.
- Added MIT license and expanded setup/usage documentation.

### Changes
- Set stable plugin defaults to `notifier`, `supermemory`, `wakatime`.
- Kept `morph` and `worktree` as opt-in experimental plugins.

### Removals
- Removed external helper binaries in favor of internal OpenCode commands.

### Fixes
- Improved plugin management safety so `/plugin enable all` only targets stable plugins.
- Added clearer troubleshooting guidance for missing API key prerequisites.
