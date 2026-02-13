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
- Added `scripts/background_task_manager.py` with enqueue/run/read/list/cancel/cleanup operations, log+metadata capture, and stale/retention cleanup controls.
- Added `/bg` command suite (`start|status|list|read|cancel|cleanup|doctor`) and autocomplete shortcuts (`/bg-help`, `/bg-list`, `/bg-running`, `/bg-doctor-json`).
- Added optional background completion/error notifications that honor existing `/notify` event/channel settings, with `MY_OPENCODE_BG_NOTIFICATIONS_ENABLED` override support.
- Added `/bg-status-json` shortcut and richer background diagnostics payloads (`/bg status --json`, `/bg doctor --json`).
- Added `instructions/refactor_lite_contract.md` defining `/refactor-lite` syntax, guardrails, and success/failure output contract for Epic 3.
- Added `scripts/refactor_lite_command.py` backend with preflight target analysis, structured plan output, and verification hooks (`make validate`, optional `make selftest`).
- Added `/refactor-lite` command templates and shortcuts in `opencode.json`, plus installer hints for dry-run/self-check usage.
- Added `instructions/keyword_execution_modes.md` defining reserved keywords, deterministic precedence rules, and request-level opt-out syntax for Epic 8 Task 8.1.
- Added `scripts/keyword_mode_schema.py` and `scripts/keyword_mode_command.py` to parse prompt keywords, resolve precedence-aware mode flags, and persist keyword mode runtime context.
- Added `/keyword-mode` aliases (`status|detect|apply`) to inspect and apply keyword-triggered execution modes.
- Added keyword mode controls for global enable/disable and per-keyword toggles (`disable-keyword` / `enable-keyword`) with persisted config state.
- Added `instructions/conditional_rules_schema.md` defining rule frontmatter schema, discovery precedence, conflict resolution, and validation requirements for Epic 9 Task 9.1.
- Added `scripts/rules_engine.py` implementing frontmatter parsing, layered rule discovery, path-based matching, deterministic precedence sorting, and duplicate-id conflict reporting.
- Added `scripts/rules_command.py` with `/rules status`, `/rules explain`, per-rule disable/enable controls, and `/rules doctor` diagnostics.
- Added `instructions/rules_team_pack_examples.md` with practical team rule-pack layout and sample rule files.
- Added `instructions/context_resilience_policy_schema.md` defining truncation modes, protected artifacts, and resilience notification levels for Epic 11 Task 11.1.
- Added `scripts/context_resilience.py` implementing resilience policy resolution and deterministic context pruning primitives.
- Added recovery workflow planning in `scripts/context_resilience.py` with resume hints, safe fallback steps, and diagnostics payloads.
- Added `scripts/context_resilience_command.py` with `/resilience status` and `/resilience doctor` stress diagnostics.
- Added `instructions/context_resilience_tuning.md` with practical tuning guidance and operating playbook.
- Added `instructions/model_fallback_explanation_model.md` defining provider/model fallback trace structure, output levels, and redaction rules for Epic 12 Task 12.1.
- Added persistent model-routing trace runtime support with `/model-routing trace --json` for latest requested/attempted/selected fallback diagnostics.
- Added `/routing` command surface (`status`, `explain`) via `scripts/routing_command.py` for compact fallback visibility workflows.
- Added `instructions/browser_profile_model.md` defining Browser Automation profile providers, defaults, migration behavior, and validation rules for Epic 13 Task 13.1.
- Added `scripts/browser_command.py` with `/browser status`, `/browser profile <provider>`, and `/browser doctor` for provider switching and dependency diagnostics.
- Added `/browser`, `/browser-status`, `/browser-profile`, and `/browser-doctor-json` aliases in `opencode.json`.
- Added browser profile selection support to `scripts/install_wizard.py` via `--browser-profile <playwright|agent-browser>`.
- Added `instructions/plan_artifact_contract.md` defining `/start-work` plan metadata/checklist format, validation rules, step transitions, and deviation capture requirements.
- Added `scripts/start_work_command.py` with `/start-work <plan>` execution, persisted checkpoint status, and deviation reporting (`status`, `deviations`).
- Added `/start-work`, `/start-work-status`, and `/start-work-deviations` aliases in `opencode.json`.
- Added `/start-work-bg` and `/start-work-doctor-json` aliases for background-safe queueing and execution health diagnostics.
- Added `instructions/plan_execution_workflows.md` with sample plans and direct/background/recovery workflows for `/start-work`.

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
- Expanded selftest and installer smoke coverage for the background task manager backend.
- Integrated background task diagnostics into `/doctor` summary output.
- Expanded README async workflow examples for `/bg` including failure/recovery troubleshooting.
- Expanded selftest and install smoke coverage for `/refactor-lite` backend preflight and verification behavior.
- Added optional `/doctor` integration check for `refactor-lite` when backend script is present.
- Expanded `/refactor-lite` tests/docs for argument parsing, safe-vs-aggressive strategy guidance, and install smoke coverage.
- Added hook framework baseline module with `PreToolUse`/`PostToolUse`/`Stop` events, config normalization (`hooks.enabled`, `hooks.disabled`, `hooks.order`), and deterministic execution planning.
- Added initial safety hook implementations for continuation reminders, output truncation, and common error recovery hints with a new `/hooks` command wrapper.
- Added hook governance controls with global/per-hook toggles in config and telemetry-safe hook audit logging (`~/.config/opencode/hooks/actions.jsonl`).
- Added hook health diagnostics via `/hooks doctor --json` and wired hook checks into unified `/doctor` diagnostics.
- Added category-routing schema baseline (`quick`, `deep`, `visual`, `writing`) with deterministic fallback behavior and validation helpers.
- Added model-routing resolution engine with deterministic precedence/fallback tracing and integration points in stack profiles and install wizard model profile selection.
- Added `/model-profile` command aliases, practical routing guidance, and unified doctor visibility for model-routing health.
- Tightened model-routing verification coverage with deterministic fallback-reason assertions and expanded install smoke resolve scenarios.
- Expanded keyword mode docs with examples and anti-pattern guidance, plus stronger selftest/install smoke coverage for keyword toggle behavior.
- Added `/keyword-mode doctor --json` diagnostics and integrated keyword subsystem health into unified `/doctor` checks.
- Expanded keyword mode verification for false-positive resistance (partial words and code-literal contexts) and opt-out/toggle smoke scenarios.
- Expanded selftest coverage for conditional rule discovery and effective-stack resolution behavior.
- Added `/doctor` rules subsystem integration and expanded install/selftest coverage for rules command workflows.
- Expanded rules verification to cover always-apply behavior, equal-priority lexical ordering, and richer discovery scenarios.
- Expanded selftest coverage for context resilience policy validation and pruning behavior (dedupe, superseded writes, stale error purge, protected evidence retention).
- Expanded selftest coverage for context recovery outcomes, including resume hints and fallback-path diagnostics.
- Expanded doctor summary coverage to include context resilience subsystem health checks.
- Expanded selftest coverage for model-routing trace persistence and runtime fallback-chain reporting.
- Expanded README guidance with category-driven routing examples and troubleshooting steps for unexpected model selection.
- Expanded routing verification coverage for deterministic trace stability and explicit fallback/no-fallback explain outcomes, and added `/routing` smoke hints in install output.
- Marked Epic 13 as in progress in the roadmap and completed Task 13.1 definition notes.
- Expanded install and selftest coverage for browser provider profile switching and missing dependency guidance.
- Expanded README wizard/browser guidance with provider trade-offs, stable-first defaults, and `/browser` usage examples.
- Expanded browser verification coverage to assert provider reset readiness and added install smoke checks that run browser status/doctor after switching across providers.
- Expanded install/selftest coverage for `/start-work` plan validation, execution state persistence, and deviation diagnostics.
- Expanded `/start-work` integrations with background queue handoff, digest recap payloads, and unified `/doctor` visibility.
- Expanded `/start-work` validation coverage for missing frontmatter, out-of-order ordinals, and recovery from invalid runtime state.

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
