# Changelog

All notable changes to this project are documented in this file.

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
