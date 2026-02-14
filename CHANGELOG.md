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
- Added `instructions/todo_compliance_model.md` defining todo states, transition enforcement, bypass metadata, and compliance audit event format for Epic 15 Task 15.1.
- Added `scripts/todo_enforcement.py` with deterministic todo transition/completion validation and remediation hint helpers for Epic 15 Task 15.2.
- Added `scripts/todo_command.py` with `/todo status` and `/todo enforce` diagnostics for runtime compliance visibility.
- Added `/todo`, `/todo-status`, and `/todo-enforce` aliases in `opencode.json`.
- Added `instructions/resume_policy_model.md` defining interruption classes, resume eligibility/cool-down rules, attempt limits, escalation semantics, and deterministic reason codes for Epic 17 Task 17.1.
- Added `scripts/recovery_engine.py` implementing checkpoint loading, eligibility evaluation, idempotency gating, and persisted resume decision/transition trail events for Epic 17 Task 17.2.
- Added `scripts/resume_command.py` with `/resume status`, `/resume now`, and `/resume disable` runtime controls for Epic 17 Task 17.3.
- Added `/resume`, `/resume-status`, `/resume-now`, and `/resume-disable` aliases in `opencode.json`.
- Added interruption-class verification coverage for recovery eligibility and cooldown behavior across `tool_failure`, `timeout`, `context_reset`, and `process_crash`.
- Added `instructions/safe_edit_capability_matrix.md` defining Epic 18 Task 18.1 safe-edit operations, backend capability matrix, language/tool readiness checks, and guarded text fallback rules.
- Added `scripts/safe_edit_adapters.py` implementing deterministic semantic backend selection (LSP/AST/text fallback) and changed-reference validation helpers for Epic 18 Task 18.2.
- Added `scripts/safe_edit_command.py` with `/safe-edit status|plan|doctor` command surface and `/safe-edit*` aliases in `opencode.json` for Epic 18 Task 18.3.
- Added cross-language safe-edit verification coverage for semantic planning and changed-reference correctness across Python/TypeScript/Go/Rust fixtures.
- Added `instructions/checkpoint_snapshot_lifecycle.md` defining Epic 19 Task 19.1 snapshot schema, trigger cadence, retention, and rotation/compression rules.
- Added `scripts/checkpoint_snapshot_manager.py` implementing atomic checkpoint writes, integrity-aware load/list operations, and retention/rotation pruning with optional compression.
- Added `scripts/checkpoint_command.py` with `/checkpoint list|show|prune|doctor` checkpoint visibility and maintenance commands.
- Added deterministic checkpoint verification coverage for atomic writes, corrupted payload handling, integrity mismatch detection, bounded retention, and gzip rotation behavior.
- Added `instructions/execution_budget_model.md` defining Epic 20 Task 20.1 budget dimensions, profile defaults, threshold semantics, and override/emergency-stop rules.
- Added `scripts/execution_budget_runtime.py` implementing budget policy resolution, counter tracking, and threshold evaluation for runtime guardrails.
- Added `scripts/budget_command.py` with `/budget status|profile|override|doctor` controls for execution budget visibility and tuning.
- Added `/budget`, `/budget-status`, `/budget-profile`, `/budget-override`, and `/budget-doctor-json` aliases in `opencode.json`.
- Added `instructions/autoflow_command_contract.md` defining Epic 22 Task 22.1 `/autoflow` subcommands, validation/error contract, output schema modes, lifecycle states, and safety defaults.
- Added `scripts/autoflow_adapter.py` implementing Epic 22 Task 22.2 primitive composition and deterministic transition/explain logic for unified orchestration.
- Added `scripts/autoflow_command.py` with `/autoflow start|status|resume|stop|report|dry-run` command controls, including non-mutating dry-run and explicit kill-switch stop behavior.
- Added `/autoflow`, `/autoflow-status`, `/autoflow-report`, `/autoflow-dry-run`, and `/autoflow-stop` aliases in `opencode.json`.
- Added `instructions/pr_review_rubric.md` defining Epic 23 Task 23.1 deterministic risk categories, severity/confidence scoring, blocker evidence thresholds, and low-noise recommendation mapping for `/pr-review`.
- Added `scripts/pr_review_analyzer.py` implementing Epic 23 Task 23.2 diff parsing, changed-area classification, missing evidence detection, and deterministic rubric-aligned findings/recommendation output for PR risk triage.
- Added `scripts/pr_review_command.py` implementing Epic 23 Task 23.3 `/pr-review` command integration with concise/JSON review output, pre-merge checklist generation, and subsystem doctor diagnostics.
- Added `/pr-review`, `/pr-review-json`, `/pr-review-checklist`, and `/pr-review-doctor` aliases in `opencode.json`.

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
- Updated `/start-work` execution to enforce todo compliance transitions, emit audit events, and block completion when required items remain unchecked.
- Integrated todo compliance checks into `/doctor` summary, installer self-checks, and install-test smoke coverage.
- Expanded selftest coverage for todo transition gating, completion blocking, and bypass audit-event payload validation.
- Marked Epic 17 as in progress and completed Task 17.1 resume-policy definition notes in the roadmap.
- Added `/start-work recover` backend path with explicit interruption class handling and approval-gated replay for non-idempotent pending steps.
- Added human-readable recovery reason output (`reason`) for resume eligibility/execution responses and documented recovery playbooks in README.
- Expanded install smoke flow to include interrupted-run replay scenarios with non-idempotent approval gating for `/resume now`.
- Marked Epic 18 as in progress and completed Task 18.1 safe-edit capability definition notes in the roadmap.
- Expanded selftest coverage for safe-edit adapter backend selection, guarded fallback failure modes, and changed-reference validation behavior.
- Integrated `safe-edit` diagnostics into unified `/doctor` and expanded README/install guidance with semantic planning examples.
- Expanded fallback verification for missing-scope and unsupported-language failure modes, and added `/safe-edit plan` installer smoke coverage.
- Marked Epic 19 as in progress and completed Task 19.1 checkpoint lifecycle definition notes in the roadmap.
- Integrated checkpoint snapshot persistence into `/start-work` and `/start-work recover`, and expanded selftest coverage for checkpoint list/show/prune behavior.
- Integrated checkpoint diagnostics into unified `/doctor`, expanded README command examples, and added selftest coverage for `/checkpoint` command flows.
- Expanded installer self-check smoke flow and command hints to include `/checkpoint list|show|prune|doctor` lifecycle checks.
- Marked Epic 20 as in progress and completed Task 20.1 execution budget model definition notes in the roadmap.
- Integrated budget runtime evaluation into `/start-work` and `/start-work recover`, including `budget_stopped` hard-stop behavior and actionable continuation recommendations.
- Integrated budget diagnostics into unified `/doctor` summary checks and expanded selftest/install smoke coverage for budget profile+override workflows.
- Updated README and roadmap notes to document budget workload tuning commands and Epic 20 Task 20.3 completion.
- Expanded budget verification coverage for invalid override input handling and usage guidance in selftest.
- Marked Epic 20 Task 20.4 complete and promoted Epic 20 status to done in the roadmap.
- Marked Epic 22 as in progress and completed Task 22.1 contract definition notes in the roadmap.
- Expanded selftest coverage with `/autoflow` adapter status and explain-path checks for illegal transitions and resume-gating fallback reason codes.
- Integrated `/autoflow` diagnostics into unified `/doctor`, expanded install smoke with `/autoflow` dry-run/status/report/stop checks, and documented migration guidance from `/start-work` and `/resume` flows.
- Expanded `/autoflow` verification coverage for report lifecycle payloads and approval-gated resume recovery paths in selftest.
- Marked Epic 22 Task 22.4 complete and promoted Epic 22 status to done in the roadmap.
- Marked Epic 23 as in progress and completed Task 23.1 rubric-definition notes in the roadmap.
- Moved `plan_execution` runtime persistence out of `opencode.json` into `~/.config/opencode/my_opencode/runtime/plan_execution.json` to prevent OpenCode startup failures caused by unrecognized top-level config keys.
- Added selftest coverage for `/pr-review` analyzer missing-evidence and blocker-evidence decision paths, and marked Task 23.2 complete in the roadmap.
- Integrated `pr-review` checks into unified `/doctor`, updated installer self-check/hints for PR review workflows, and marked Task 23.3 complete in the roadmap.
- Expanded pr-review verification coverage for risk-detection false-positive control and missing-evidence behavior, and marked Epic 23 Task 23.4/exit criteria complete in the roadmap.
- Added release-train policy contract covering deterministic preflight gates, semantic-version blocking rules, and partial-failure rollback reason codes; marked Epic 24 Task 24.1 complete in the roadmap.
- Added `release_train_engine.py` backend with deterministic release preflight diagnostics, draft-note generation from git history, and confirmation-gated publish dry-run flow; marked Epic 24 Task 24.2 complete in the roadmap.
- Added `/release-train` command integration with aliases, doctor/install smoke wiring, and `make release-check VERSION=x.y.z` preflight gating via release-train diagnostics; marked Epic 24 Task 24.3 complete in the roadmap.
- Expanded release-train verification coverage for breaking-change/version mismatch blocking and publish dry-run vs confirmation gating, and marked Epic 24 Task 24.4/exit criteria complete in the roadmap.
- Added hotfix-mode policy contract for incident activation, mandatory non-skippable checks, reduced validation boundaries, and post-incident follow-up/audit requirements; marked Epic 25 Task 25.1 complete in the roadmap.
- Added `hotfix_runtime.py` backend implementing constrained incident runtime profiles, rollback checkpoint capture, and append-only timeline/closure guardrails; marked Epic 25 Task 25.2 complete in the roadmap.
- Added `/hotfix` command integration with aliases, doctor/install wiring, and post-incident reminder guidance backed by `hotfix_command.py`; marked Epic 25 Task 25.3 complete in the roadmap.
- Expanded hotfix verification coverage for dirty-worktree guardrail blocking, rollback closure lifecycle checks, and install-smoke enforcement of `/hotfix close` follow-up metadata; marked Epic 25 Task 25.4 and exit criteria complete in the roadmap.
- Added health-score policy contract defining indicator schema, weighted threshold model, and drift suppression-window behavior for Epic 26 Task 26.1.

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
