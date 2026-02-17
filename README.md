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
- 🧠 Built-in `/safe-edit` command for semantic adapter planning and readiness diagnostics.
- 🩺 Built-in `/doctor` umbrella command for one-shot health checks.
- 🤖 Built-in `/agent-doctor` command for custom agent contract and runtime checks.
- 💾 Built-in `/config` command for backup/restore snapshots.
- 🧩 Built-in `/stack` bundles for coordinated multi-command profiles.
- 🌐 Built-in `/browser` command for provider switching and dependency diagnostics.
- ⏱️ Built-in `/budget` command for execution budget profile, override, and diagnostics.
- 🧠 Custom agents for Tab selection: `orchestrator` (primary), plus `explore`, `librarian`, `oracle`, `verifier`, `reviewer`, and `release-scribe` subagents.
- 🧠 Built-in `/nvim` command to install and validate deeper `opencode.nvim` keymap integration.
- 🧰 Built-in `/devtools` command to manage external productivity tooling.
- 🧭 Built-in `/auto-slash` command to map natural-language intent to safe slash command previews.
- 💸 Better token control by enabling `context7` / `gh_grep` only on demand.
- 🔒 Autonomous-friendly permissions for trusted project paths.
- 🔁 Easy updates by rerunning the installer.
- 🧩 Clear, versioned config for experiments and rollbacks.

## Agent roles (Tab menu)

This setup keeps `build` as the default agent, and adds focused specialists for manual selection via `Tab`:

- `orchestrator` (primary): execution lead for complex tasks, with explicit delegation and completion gates.
- `explore` (subagent): read-only internal codebase scout.
- `librarian` (subagent): read-only external docs and OSS evidence researcher.
- `oracle` (subagent): read-only architecture/debug advisor for hard tradeoffs.
- `verifier` (subagent): read-only validation runner for test/lint/build checks.
- `reviewer` (subagent): read-only quality/risk review pass before final delivery.
- `release-scribe` (subagent): read-only PR/changelog/release-notes writer from git evidence.

Agent files live in `agent/*.md` and install globally to `~/.config/opencode/agent/`.
Agent source-of-truth specs live in `agent/specs/*.json` and generate markdown via `scripts/build_agents.py`.

Quick validation:

```text
/agent-doctor
/agent-doctor-json
```

Detailed guide: `docs/agents-playbook.md` 📘

Operating contract: `instructions/agent_operating_contract.md` 🛡️

Autopilot hook migration plan: `docs/autopilot-hook-roadmap.md` 🔁

## Roadmap plan 🗺️

- Track upcoming orchestration features in `IMPLEMENTATION_ROADMAP.md`.
- Release slicing baseline (Task C1) now groups delivery into deterministic phases (A-N) with explicit readiness gates per slice.
- Epic acceptance baseline (Task C2) now defines reusable completion criteria for functional behavior, reliability, docs quality, validation gates, and rollback evidence.
- Tracking cadence baseline (Task C3) now requires weekly roadmap status entries, a single active `in_progress` epic, and monthly review of paused/postponed epics.
- Command UX baseline (Task C4) now standardizes shortcut aliases, help/doctor discoverability, and troubleshooting-first quick paths across command families.
- Session intelligence baseline (E6-T1) now records digest-linked session metadata in `~/.config/opencode/sessions/index.json` with retention pruning for stale or oversized histories.
- Session command baseline (E6-T2) now exposes `/session list|show|search` plus `/session doctor` for indexed-session visibility and diagnostics.
- Resume support baseline (E6-T3) now emits actionable `resume_hints` in `/resume` and `/start-work recover` JSON output, and includes resume eligibility hints in digest `plan_execution` snapshots.
- Roadmap status sync marks Epic 6 and Epic 28 complete after verification and aligns dashboard/task state with shipped functionality.
- Dashboard reconciliation now aligns Epic 25-E27 summary statuses with completed implementation sections.
- Epic 18 roadmap task checkboxes now align with previously shipped safe-edit adapter and command-integration completion notes.
- Paused-epic governance now defines measurable exit criteria for E7/E10 promotion, including demand/prototype/safety gates.
- Auto-slash detector now ships with preview-first dispatch, per-command toggles, and execution audit logging for E10 intent routing.

Release slicing gate checklist (per phase):

- command contracts and user workflows are documented (`README` + relevant `instructions/*`)
- validation bundle passes: `make validate`, `make selftest`, `make install-test`
- rollback/remediation notes are explicit for newly introduced runtime controls
- roadmap/checklist/changelog entries are updated before merge

## Safe-edit capability baseline

Epic 18 Task 18.1 defines the semantic safe-edit baseline in:

- `instructions/safe_edit_capability_matrix.md`

Current scope includes:

- supported operations: `rename`, `extract`, `organize_imports`, `scoped_replace`
- operation/backend matrix: preferred LSP/AST path plus guarded text fallback
- deterministic availability checks for language, LSP, and AST readiness
- explicit fallback blocking conditions and reason-code contract for explainability

Task 18.2 implementation baseline:

- adapter module: `scripts/safe_edit_adapters.py`
- operation planner: deterministic backend choice (`lsp`, `ast`, or guarded `text` fallback)
- validation helper: changed-reference verification for rename-like symbol updates

Task 18.3 command integration:

- command module: `scripts/safe_edit_command.py`
- diagnostics: `/safe-edit status --json`, `/safe-edit doctor --json`
- planning surface: `/safe-edit plan --operation <rename|extract|organize_imports|scoped_replace> --scope <glob[,glob...]> [--allow-text-fallback] --json`

Examples:

```text
/safe-edit status --json
/safe-edit plan --operation rename --scope scripts/*.py --json
/safe-edit plan --operation scoped_replace --scope scripts/*.py --allow-text-fallback --json
/safe-edit doctor --json
```

Verification notes:

- selftest now covers cross-language rename/reference validation samples (`python`, `typescript`, `go`, `rust`).
- fallback tests cover explicit-scope gating and unsupported-language failure paths.
- install smoke now exercises `/safe-edit plan` in addition to status/doctor checks.

## Checkpoint snapshot baseline

Epic 19 Task 19.1 defines checkpoint snapshot lifecycle semantics in:

- `instructions/checkpoint_snapshot_lifecycle.md`

Current baseline includes:

- snapshot schema for step state, context digest, command outcomes, and integrity metadata.
- deterministic trigger boundaries (`step_boundary`, `error_boundary`, `timer`, `manual`) with coalescing behavior.
- retention/rotation defaults (bounded history per run plus terminal snapshot preservation).
- optional history compression policy with checksum continuity requirements.

Task 19.2 implementation baseline:

- manager module: `scripts/checkpoint_snapshot_manager.py`
- persistence semantics: atomic writes to `checkpoints/<run_id>/history/<snapshot_id>.json` and `checkpoints/<run_id>/latest.json`
- runtime integration: `/start-work` and `/start-work recover` now persist checkpoint snapshots after state writes
- lifecycle controls: list/show/prune APIs with integrity verification and bounded retention defaults

Task 19.3 visibility tooling:

- command module: `scripts/checkpoint_command.py`
- command surface: `/checkpoint list|show|prune|doctor`
- doctor integration: unified `/doctor run --json` now includes checkpoint health checks

Examples:

```text
/checkpoint list --json
/checkpoint show --snapshot latest --json
/checkpoint prune --max-per-run 50 --max-age-days 14 --json
/checkpoint doctor --json
```

Task 19.4 verification notes:

- selftest verifies atomic checkpoint writes and deterministic corruption/integrity-failure reason codes.
- retention tests verify bounded per-run history and gzip rotation for older snapshots.
- install smoke now exercises `/checkpoint list|show|prune|doctor` alongside `/start-work` recovery flows.

## Execution budget baseline

Epic 20 Task 20.1 defines execution budget guardrail policy in:

- `instructions/execution_budget_model.md`

Current baseline includes:

- budget dimensions for wall-clock duration, tool-call count, and token estimates.
- profile defaults for `conservative`, `balanced`, and `extended` execution envelopes.
- deterministic soft/hard threshold semantics and reason-code contract.
- auditable override and emergency-stop behavior with bounded escalation limits.

Task 20.2 runtime integration:

- runtime module: `scripts/execution_budget_runtime.py`
- `/start-work` and `/start-work recover` now emit budget counters, threshold evaluation, and recommendations in JSON reports
- hard-limit crossings transition run state to `budget_stopped` with deterministic `budget_*` reason codes
- `/start-work status` and `/start-work doctor` include persisted budget diagnostics

Task 20.3 commands and diagnostics:

- command module: `scripts/budget_command.py`
- command surface: `/budget status|profile|override|doctor`
- unified diagnostics: `/doctor run --json` includes budget guardrail health checks
- runtime tuning path: profile switching plus auditable temporary overrides for high-variance workloads

Examples:

```text
/budget status --json
/budget profile conservative
/budget override --tool-call-count 120 --token-estimate 120000 --reason "large refactor" --json
/budget override --clear --json
/budget doctor --json
```

Task 20.4 verification notes:

- selftest covers PASS/WARN/FAIL budget threshold evaluation and `budget_stopped` hard-stop behavior in `/start-work`.
- selftest covers override apply/clear paths plus invalid override input rejection with deterministic usage guidance.
- install smoke includes `/budget status`, `/budget override`, `/budget doctor`, and `/budget override --clear` checks.

## Autoflow contract baseline

Epic 22 Task 22.1 defines unified orchestration command semantics in:

- `instructions/autoflow_command_contract.md`

Current baseline includes:

- `/autoflow` subcommands: `start`, `status`, `resume`, `stop`, `report`, `dry-run`
- deterministic validation/error payload rules with stable reason codes and remediation hints
- concise human output plus structured `--json` schema for automation
- lifecycle status model and safety defaults for dry-run, stop, and recovery gating

Task 22.2 adapter baseline:

- adapter module: `scripts/autoflow_adapter.py`
- primitive composition: `plan`, `todo_compliance`, `budget`, `checkpoint`, `resume`, and `loop_guard`
- deterministic transition matrix for `start|status|resume|stop|report|dry-run`
- explain path that returns trace entries plus fallback intent/reason when transitions are illegal or resume gating fails

Task 22.3 safety and usability controls:

- command module: `scripts/autoflow_command.py`
- kill-switch control: `/autoflow stop --reason <text> --json` sets runtime status to `stopped` with audit metadata
- dry-run control: `/autoflow dry-run <plan.md> --json` previews transition decisions without mutating runtime state
- migration path from low-level commands to `/autoflow`:
  - `/start-work <plan.md>` -> `/autoflow start <plan.md>`
  - `/start-work status --json` -> `/autoflow status --json`
  - `/start-work deviations --json` -> `/autoflow report --json`
  - `/resume now --interruption-class <class> --json` -> `/autoflow resume --interruption-class <class> --json`

Task 22.4 verification notes:

- selftest validates `/autoflow` lifecycle coverage across `start -> status/report` with deterministic payload assertions.
- selftest validates `/autoflow resume` recovery gating for non-idempotent steps and explicit approval replay.
- install smoke validates `/autoflow dry-run`, `/autoflow status`, `/autoflow report`, and `/autoflow stop` happy-path controls.

Runtime storage note:

- `plan_execution` runtime state is persisted to `~/.config/opencode/my_opencode/runtime/plan_execution.json`.
- this avoids invalid top-level keys in `~/.config/opencode/opencode.json` and prevents OpenCode startup config parsing errors.

## PR review rubric baseline

Epic 23 Task 23.1 defines pre-merge risk scoring semantics in:

- `instructions/pr_review_rubric.md`

Current baseline includes:

- deterministic risk categories for `security`, `data_loss`, `migration_impact`, `test_coverage`, and `docs_changelog`.
- explicit severity (`S0-S3`) and confidence (`C0-C3`) scales with conservative blocker thresholds.
- required evidence contract for every finding (`file_refs`, rationale, and remediation), plus hard-evidence gating for blocker recommendations.
- low-noise recommendation mapping (`approve`, `needs_review`, `changes_requested`, `block`) with deterministic tie-break behavior.

Task 23.2 analyzer baseline:

- analyzer module: `scripts/pr_review_analyzer.py`
- parses unified git diffs (`git diff --unified=0`) into file/line evidence and classifies changed areas.
- emits rubric-aligned findings with deterministic severity/confidence and `file_refs`.
- detects missing release evidence (`tests`, `README`, `CHANGELOG`) and folds gaps into recommendation scoring.

Examples:

```text
python3 ~/.config/opencode/my_opencode/scripts/pr_review_analyzer.py analyze --base main --head HEAD --json
python3 ~/.config/opencode/my_opencode/scripts/pr_review_analyzer.py analyze --diff-file /tmp/pr.diff --json
```

Task 23.3 command integration:

- command module: `scripts/pr_review_command.py`
- command surface: `/pr-review`, `/pr-review-json`, `/pr-review-checklist`, `/pr-review-doctor`
- doctor integration: unified `/doctor run --json` includes `pr-review` subsystem readiness

Warning vs blocker triage flow:

- `block`: at least one `S3` finding with `C2+` confidence and hard evidence; do not merge until fixed.
- `changes_requested`: repeated `S2` findings with concrete remediation and missing evidence.
- `needs_review`: medium-risk findings or uncertain evidence requiring reviewer attention.
- `approve`: no meaningful risk findings beyond informational noise.

Examples:

```text
/pr-review --base main --head HEAD --json
/pr-review checklist --base main --head HEAD --json
/pr-review doctor --json
```

Task 23.4 verification notes:

- selftest validates blocker detection for hard-evidence security findings and missing-evidence recommendation behavior.
- selftest validates false-positive control for docs-only diffs (`recommendation=approve`, no findings).
- install smoke validates `/pr-review`, `/pr-review checklist`, and `/pr-review doctor` command paths.

Task 24.1 release policy contract notes:

- release preconditions now require clean git state plus passing `make validate`, `make selftest`, and `make install-test` evidence before publish readiness.
- semantic-version gating now defines deterministic patch/minor/major validation and breaking-change mismatch blocking.
- rollback policy now defines partial-failure handling with explicit reason codes and follow-up guidance.

Task 24.2 release assistant engine notes:

- backend module: `scripts/release_train_engine.py` with `status`, `prepare`, `draft`, `publish`, and `doctor` command flows.
- `prepare` emits deterministic `reason_codes` and remediation for clean-tree, branch, validation, changelog, and semver gating checks.
- `draft` composes release-note entries from git history since the latest (or provided) tag.
- `publish` enforces readiness and explicit confirmation, with dry-run and rollback action metadata.

Task 24.3 command integration notes:

- command module: `scripts/release_train_command.py`
- command surface: `/release-train`, `/release-train-json`, `/release-train-prepare`, `/release-train-draft`, `/release-train-doctor`
- doctor integration: unified `/doctor run --json` now includes `release-train` subsystem readiness checks.
- release-check integration: `make release-check VERSION=x.y.z` now invokes release-train preflight gating.

Examples:

```text
/release-train status --json
/release-train prepare --version 0.3.0 --json
/release-train draft --head HEAD --json
/release-train doctor --json
```

Task 24.4 verification notes:

- selftest validates breaking-change/changelog mismatch blocking with `version_mismatch_breaking_change` reason codes.
- selftest validates publish behavior split between `--dry-run` pass and confirmation-required blocking for live publish.
- install smoke validates `/release-train` status, prepare, draft, and doctor command paths.

Task 25.1 hotfix policy contract notes:

- hotfix activation now requires incident id, declared scope, declared impact, and recorded operator context.
- mandatory guardrails define non-skippable checks for git hygiene, `make validate`, rollback checkpoint, and timeline completeness.
- reduced validation profile allows targeted tests during incident response but requires deferred full-suite follow-up with ownership.
- post-incident closure now requires follow-up issue linkage, deferred validation plan, and timeline export artifacts.

Task 25.2 hotfix runtime notes:

- backend module: `scripts/hotfix_runtime.py` with `start`, `checkpoint`, `mark-patch`, `validate`, `close`, `status`, and `doctor` flows.
- runtime profile now persists constrained budget and tool-permission defaults for incident handling.
- rollback checkpoint and patch/validation events are captured in append-only timeline records.
- closure now enforces follow-up issue linkage and deferred validation ownership metadata.

Task 25.3 hotfix command integration notes:

- command module: `scripts/hotfix_command.py`
- command surface: `/hotfix`, `/hotfix-json`, `/hotfix-start`, `/hotfix-status`, `/hotfix-close`, `/hotfix-remind`, `/hotfix-doctor`
- doctor integration: unified `/doctor run --json` now includes `hotfix` subsystem readiness checks.
- install/self-check integration: installer smoke now exercises hotfix start, checkpoint, validate, status, remind, close, and doctor paths.

Examples:

```text
/hotfix start --incident-id INC-42 --scope patch --impact sev2 --json
/hotfix status --json
/hotfix close --outcome resolved --followup-issue bd-123 --deferred-validation-owner oncall --deferred-validation-due 2026-03-01 --json
/hotfix remind --json
/hotfix doctor --json
```

Task 25.4 hotfix verification notes:

- selftest now validates mandatory guardrail enforcement for dirty-worktree incident start blocking (`reason_code=dirty_worktree`).
- selftest now validates rollback incident flow end-to-end (`scope=rollback`) including `rollback_applied` timeline events and closure with `outcome=rolled_back`.
- install smoke now validates both failure and success closure paths for `/hotfix close` to ensure follow-up metadata remains mandatory.

Task 26.1 health model contract notes:

- policy contract: `instructions/health_score_policy_contract.md`
- indicator model covers validation health, git/release hygiene, policy drift, automation reliability, and operational freshness.
- weighted scoring now defines deterministic penalties and status thresholds (`healthy`, `degraded`, `critical`).
- drift alert suppression now defines per-reason suppression keys, 24h default windows, and critical bypass behavior.

Task 26.2 health collector backend notes:

- backend module: `scripts/health_score_collector.py`
- collector now aggregates repo/runtime health signals across validation targets, git hygiene, policy drift, automation reliability, and freshness debt.
- scoring now applies weighted penalties with forced-status escalation rules from the Epic 26 contract.
- runtime persistence now writes latest and append-only history snapshots plus suppression-window state for repeated drift alerts.

Task 26.3 health command integration notes:

- command module: `scripts/health_command.py`
- command surface: `/health status|trend|drift|doctor`
- JSON export paths: trend and drift output are CLI-friendly JSON payloads for dashboards/CI ingestion.
- remediation guidance now includes score-bucket defaults (`healthy`, `degraded`, `critical`) when indicator-specific actions are missing.

Examples:

```text
/health status --force-refresh --json
/health trend --limit 10 --json
/health drift --json
/health doctor --json
```

Task 26.4 health verification notes:

- selftest now validates score determinism by repeating `/health status --force-refresh --json` on unchanged repository signals.
- selftest now validates drift precision by injecting budget profile drift and asserting `policy_drift_detected` attribution under `runtime_policy_drift`.
- install smoke now validates drift force-refresh behavior under controlled profile drift in temporary config state.

Task 27.1 knowledge capture contract notes:

- policy contract: `instructions/knowledge_capture_policy_contract.md`
- entry taxonomy now defines `pattern`, `pitfall`, `checklist`, and `rule_candidate` capture types.
- confidence scoring now uses deterministic factor weights (`evidence_quality`, `repeatability`, `scope_clarity`, `freshness`) for publish eligibility.
- approval quality gates now require evidence links, confidence thresholds, and reviewer metadata before publication.

Task 27.2 knowledge pipeline backend notes:

- backend module: `scripts/knowledge_capture_pipeline.py`
- extraction pipeline now collects merged-PR signals from git history and task digest signals from JSON digest artifacts.
- draft generation now groups signals by objective key (`E##-T##`) and emits evidence-linked draft entries with deterministic confidence scoring.
- lifecycle transitions now enforce review/publish/archive quality gates with explicit failure reason codes and approval metadata.

Task 27.3 learn command and integration notes:

- command module: `scripts/learn_command.py`
- command surface: `/learn capture|review|publish|search|doctor` with JSON-friendly outputs for automation.
- publish/search outputs now include `rule_injector_candidates` and `autoflow_guidance` so published patterns can be reused by rule workflows and `/autoflow` planning docs.
- maintenance workflow: use `/learn search --status published --json` to inspect stale or low-confidence entries, then archive or refresh entries before they drive automation.

Examples:

```text
/learn capture --limit 20 --json
/learn review --entry-id kc-e27-t2 --summary "reviewed guidance" --confidence 90 --risk medium --json
/learn publish --entry-id kc-e27-t2 --approved-by oncall --json
/learn search --query release --json
/learn doctor --json
```

Task 27.4 learn verification notes:

- selftest now validates extraction quality thresholds by asserting `/learn review` rejects low-confidence drafts.
- selftest now validates publish permissions by enforcing high-risk dual-approval gates before `/learn publish` can succeed.
- install smoke now validates the same high-risk publish guardrail by expecting single-approval failure and second-approval success.

Task 28.1 autopilot contract notes:

- policy contract: `instructions/autopilot_command_contract.md`
- command surface now defines `/autopilot start|go|status|pause|resume|stop|report` with JSON output requirements.
- objective schema now supports dual completion modes: `completion-mode=promise` (default, requires `<promise>DONE</promise>`) and `completion-mode=objective` (done-criteria gates).
- `/autopilot start` and `/autopilot go` infer missing fields for context-first usage and default to promise-based continuous operation.
- safety defaults now require dry-run preview before first stateful cycle and enforce budget/scope guardrails with explicit reason codes.

Task 28.2 autopilot loop backend notes:

- backend module: `scripts/autopilot_runtime.py`
- runtime now validates objective schema and materializes bounded execution cycles from `done-criteria`.
- cycle execution now applies budget guardrails per cycle and writes mandatory checkpoint snapshots for initialization and each cycle evaluation.
- loop payloads now emit deterministic progress counts, blocker reason codes, and next-action recommendations (including budget hard-stop guidance).

Task 28.3 autopilot control-integration notes:

- integration module: `scripts/autopilot_integration.py`
- `/autoflow` bridge reuse now maps autopilot run states into deterministic autoflow transition evaluations.
- control diagnostics now combine todo-enforcement, resume eligibility, and checkpoint-count signals for operator visibility.
- confidence-drop behavior now enforces explicit manual handoff mode (`reason_code=confidence_drop_requires_handoff`) before autonomous progression resumes.

Task 28.4 autopilot command UX/workflow notes:

- command module: `scripts/autopilot_command.py`
- alias set in `opencode.json`: `/autopilot`, `/autopilot-go`, `/continue-work`, `/autopilot-status`, `/autopilot-report`, `/autopilot-pause`, `/autopilot-resume`, `/autopilot-stop`, `/autopilot-doctor`
- objective-mode alias is available as `/autopilot-objective` when you want completion from done-criteria gates instead of promise token.
- canonical flow is `/autopilot*`; Ralph compatibility aliases were removed to simplify command injection paths.
- unified workflow controls now expose `start|go|status|pause|resume|stop|report|doctor` with deterministic JSON payloads and reason codes.
- status/report/go payloads now include gateway bridge telemetry via `gateway_loop_state` and `gateway_orphan_cleanup`.
- legacy `/start-work*` slash commands are removed from active command surface to avoid redundant orchestration paths.
- resume path now supports `--touched-paths <csv>` to enforce objective scope boundaries before cycle execution.

Autopilot gateway telemetry fields (`--json`):

| Field | Type | Meaning |
|---|---|---|
| `gateway_runtime_mode` | `string` | Active routing mode for autopilot controls: `plugin_gateway` when gateway plugin is enabled and hook-complete, otherwise `python_command_bridge`. |
| `gateway_runtime_reason_code` | `string` | Routing decision reason (`gateway_plugin_ready`, `gateway_plugin_disabled`, `gateway_plugin_runtime_unavailable`, `gateway_plugin_not_ready`). |
| `gateway_plugin_enabled` | `boolean` | Whether gateway-core file plugin is currently enabled in layered config. |
| `gateway_bun_available` | `boolean` | Whether `bun` is currently available for host-side file plugin runtime support. |
| `gateway_missing_hook_capabilities` | `string[]` | Missing required dist hook capabilities when plugin mode cannot be selected. |
| `gateway_loop_state` | `object|null` | Current loop state for the active runtime mode; bridge state is hidden when plugin mode is active. |
| `gateway_loop_state_reason_code` | `string` | Loop state selection reason (`loop_state_available`, `bridge_state_ignored_in_plugin_mode`). |
| `gateway_orphan_cleanup.attempted` | `boolean` | Always `true` when status snapshot runs cleanup check. |
| `gateway_orphan_cleanup.changed` | `boolean` | `true` when stale/invalid active loop was deactivated and state file was updated. |
| `gateway_orphan_cleanup.reason` | `string` | Cleanup outcome reason: `state_missing`, `not_active`, `within_age_limit`, `invalid_started_at`, or `stale_loop_deactivated`. |
| `gateway_orphan_cleanup.state_path` | `string|null` | State file path only when cleanup mutated persisted bridge state. |

```bash
# Help/control subcommands (no execution loop)
/autopilot help
/autopilot status --json

# Execution runner (start-or-resume bounded cycles)
/autopilot-go --goal "continue active docs request" --max-cycles 10 --json

# Quick-fix objective (single-script scope)
/autopilot start --goal "patch failing smoke check" --scope "scripts/install.sh" --done-criteria "install-test passes" --max-budget conservative --json
/autopilot status --json
/autopilot report --json

# Context-first one-shot iteration (start-or-resume and run bounded cycles)
/autopilot go --goal "continue active docs request" --max-cycles 10 --json
/autopilot-go-verbose --goal "continue active docs request" --max-cycles 10 --json
/continue-work "finish cheatsheet updates and validations"

# Canonical command surface
/autopilot-go --goal "finish docs checklist end-to-end"
/autopilot-stop --reason "manual"

# Objective-gate completion mode (alternative to promise mode)
/autopilot-objective --goal "close all docs checklists" --scope "docs/**" --done-criteria "all docs updated;checks green" --max-budget balanced

# Feature objective (multi-step implementation)
/autopilot start --goal "ship command UX polish" --scope "scripts/*.py, README.md" --done-criteria "code complete;docs updated;validation green" --max-budget balanced --json
/autopilot pause --json
/autopilot resume --confidence 0.9 --tool-calls 1 --token-estimate 120 --json

# Release objective (high signal, high control)
/autopilot start --goal "prepare release candidate" --scope "CHANGELOG.md, README.md, scripts/**" --done-criteria "release checks pass;notes updated" --max-budget conservative --json
/autopilot stop --reason "manual release hold" --json

# Troubleshooting for paused/stopped runs
/autopilot doctor --json
/autopilot report --json
```

- troubleshooting guide:
  - quote multi-word flag values (`--goal`, `--scope`, `--done-criteria`, `--completion-promise`) using `"..."`.
  - unquoted multi-word values are parsed as extra positional tokens and may fall back to usage output.
  - `/autopilot start` initializes a dry-run-backed objective state; `/autopilot-go` executes bounded cycles.
  - `/autopilot-go --max-cycles <n>` sets an upper bound, not a guaranteed count; runs may finish earlier when completion gates are met.
  - compact output is enabled by default for `/autopilot-go`, `/autopilot-objective`, and `/continue-work`; use `/autopilot-go-verbose` for full cycle payloads.
  - go-style aliases print a debug command line before JSON payloads for traceability.
  - `/autopilot` without a subcommand defaults to go-style execution with inferred fields.
  - `autopilot_runtime_missing`: initialize objective with `/autopilot start ...`.
  - `confidence_drop_requires_handoff`: operator review required before calling `/autopilot resume`.
  - `budget_*`: reduce scope or lower cycle load, then resume with conservative increments.
  - `scope_violation_detected`: remove out-of-scope targets or tighten `--touched-paths` to declared objective scope.
  - `autopilot_stop_requested`: inspect `/autopilot report` and start a fresh run when ready.

Task 28.5 autopilot verification notes:

- selftest now validates scope-bounded cycle execution (`scope_violation_detected`) and budget hard-stop behavior for `/autopilot resume`.
- selftest now validates pause/resume/stop transitions through repeated `/autopilot status` checks after each lifecycle control action.
- install smoke now exercises `/autopilot` objective lifecycle with both in-scope resume and explicit out-of-scope failure scenario (`|| true` guard) before stop/doctor checks.

## Installed plugin stack 🔌

- `@mohak34/opencode-notifier@latest` - desktop and sound alerts for completion, errors, and permission prompts.

### Experimental plugin options 🧪

- `github:kdcokenny/opencode-worktree` - git worktree automation with terminal spawning for isolated agent sessions.
- `github:JRedeker/opencode-morph-fast-apply` - high-speed Morph Fast Apply edits for large or scattered code changes.

These two can fail to auto-resolve on some setups and are disabled by default. Enable them only when you want to test them.

## Installed instruction packs 📘

- `instructions/shell_strategy.md` - non-interactive shell strategy rules to avoid hangs and improve autonomous execution.
- `instructions/release_train_policy_contract.md` - release preflight, semver gating, reason-code, and rollback contract for upcoming `/release-train` flows.
- `instructions/hotfix_mode_policy_contract.md` - incident hotfix activation, mandatory safety checks, reduced validation limits, and follow-up audit contract.
- `instructions/health_score_policy_contract.md` - repo health indicator model, weighted thresholds, and drift suppression-window contract.
- `instructions/knowledge_capture_policy_contract.md` - reusable-learning entry schema, confidence scoring, approval quality gates, and search metadata contract.
- `instructions/autopilot_command_contract.md` - objective runner command surface, lifecycle transitions, required fields, and dry-run-first safety contract.

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
- run a post-install self-check (`/mcp status`, `/plugin status`, `/notify status`, `/digest show`, `/session list --json`, `/session doctor --json`, `/telemetry status`, `/post-session status`, `/policy status`, `/config status`, `/bg status`, `/refactor-lite profile --scope scripts/*.py --dry-run --json`, `/safe-edit status --json`, `/stack status`, `/browser status`, `/doctor run`, `/plugin doctor`)

## Manual install 🛠️

```bash
git clone https://github.com/dmoliveira/my_opencode.git ~/.config/opencode/my_opencode
ln -sfn ~/.config/opencode/my_opencode/opencode.json ~/.config/opencode/opencode.json
chmod +x ~/.config/opencode/my_opencode/install.sh ~/.config/opencode/my_opencode/scripts/mcp_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/plugin_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/notify_command.py ~/.config/opencode/my_opencode/scripts/session_digest.py ~/.config/opencode/my_opencode/scripts/session_command.py ~/.config/opencode/my_opencode/scripts/opencode_session.sh ~/.config/opencode/my_opencode/scripts/telemetry_command.py ~/.config/opencode/my_opencode/scripts/post_session_command.py ~/.config/opencode/my_opencode/scripts/policy_command.py ~/.config/opencode/my_opencode/scripts/doctor_command.py ~/.config/opencode/my_opencode/scripts/config_command.py ~/.config/opencode/my_opencode/scripts/stack_profile_command.py ~/.config/opencode/my_opencode/scripts/browser_command.py ~/.config/opencode/my_opencode/scripts/start_work_command.py ~/.config/opencode/my_opencode/scripts/install_wizard.py ~/.config/opencode/my_opencode/scripts/nvim_integration_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/devtools_command.py
chmod +x ~/.config/opencode/my_opencode/scripts/background_task_manager.py
chmod +x ~/.config/opencode/my_opencode/scripts/todo_command.py ~/.config/opencode/my_opencode/scripts/resume_command.py ~/.config/opencode/my_opencode/scripts/safe_edit_command.py
```

## Install wizard flow 🧭

The wizard lets each user decide what they want now and reconfigure later.

- Select plugin profile (`lean`, `stable`, `experimental`, or custom plugin-by-plugin).
- Select MCP, policy, telemetry, and post-session defaults.
- Select browser automation provider (`playwright` recommended stable-first, `agent-browser` optional).
- Optionally install/uninstall ecosystem integrations (`opencode.nvim`, `OpenChamber`).
- When `opencode.nvim` is selected, wizard bootstraps a minimal integration profile at `~/.config/nvim/lua/my_opencode/opencode.lua`.
- Stable-first recommendation: keep `playwright` unless you specifically rely on `agent-browser` workflows.
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

## Hook framework baseline

Epic 4 starts with a minimal hook framework in `scripts/hook_framework.py`.

- Supported events: `PreToolUse`, `PostToolUse`, `Stop`
- Config section: `hooks.enabled`, `hooks.disabled`, `hooks.order`
- Deterministic ordering for each event:
  1. explicit `hooks.order`
  2. numeric `priority` (ascending)
  3. hook id (lexicographic)

This baseline intentionally ships without default active hooks. Epic 4.2 adds concrete hook implementations.

## Initial safety hooks

Use these directly in OpenCode:

```text
/hooks status
/hooks enable
/hooks disable
/hooks disable-hook truncate-safety
/hooks enable-hook truncate-safety
/hooks doctor
/hooks doctor --json
/hooks run continuation-reminder --json '{"checklist":["update docs","run tests"]}'
/hooks run truncate-safety --json '{"text":"...large output...","max_lines":120,"max_chars":8000}'
/hooks run error-hints --json '{"command":"git status","exit_code":128,"stderr":"fatal: not a git repository"}'
```

Autocomplete-friendly shortcut:

```text
/hooks-help
/hooks-enable
/hooks-disable
/hooks-status
/hooks-doctor
/hooks-doctor-json
```

Hook behavior:
- `continuation-reminder` triggers when checklist items remain unfinished.
- `truncate-safety` clips oversized output and returns warnings with limits used.
- `error-hints` maps common failures (missing command/path, permission, git context, timeout) to actionable hints.

Governance controls:
- global toggle in config: `hooks.enabled`
- per-hook opt-out list: `hooks.disabled`
- telemetry-safe audit log: `~/.config/opencode/hooks/actions.jsonl`
- audit log records only metadata (hook id, category, triggered, exit status), not raw command output

## Category routing schema baseline

Epic 5 starts with a schema contract in `scripts/model_routing_schema.py` and docs in
`instructions/model_routing_schema.md`.

Baseline categories:
- `quick`
- `deep`
- `visual`
- `writing`

Each category includes `model`, `temperature`, `reasoning`, `verbosity`, and `description`.
Fallback behavior is deterministic:
- unknown category -> `default_category`
- unavailable model -> `default_category`

Fallback explanation contract (Epic 12 Task 12.1):
- `instructions/model_fallback_explanation_model.md`
- trace stages: `requested -> attempted -> selected`
- output levels: `compact` and `verbose`
- redaction policy for sensitive provider details

Resolution precedence (Task 5.2):
1. `system_defaults`
2. selected category defaults
3. explicit user overrides
4. model availability fallback (category -> system default)

Use:
```text
/model-routing status
/model-routing set-category deep
/model-routing resolve --category deep --override-model openai/gpt-5.3-codex --json
/model-routing trace --json
```

`/model-routing resolve` now emits a structured fallback trace (`requested -> attempted -> selected`) and persists the latest trace for `/model-routing trace` debug introspection.

Routing command surface (Epic 12 Task 12.3):
```text
/routing status
/routing explain --category deep --available-models openai/gpt-5-mini --json
```

Troubleshooting unexpected model selection:
- run `/routing explain --json` and inspect `fallback_reason`
- confirm `attempted_count` is non-zero and review `resolution_trace.attempted`
- verify available model set passed to resolve commands matches runtime availability

Model-profile aliases:
```text
/model-profile status
/model-profile set visual
/model-profile resolve --category writing
```

Practical routing examples:
- Fast repo hygiene (`git status`, light checks): `quick`
- Architecture/debug planning and complex refactors: `deep`
- UI polish and design-heavy implementation notes: `visual`
- Changelogs, release notes, and long-form docs: `writing`

Integration points:
- `/stack apply <profile>` now sets a routing category (`focus/research -> deep`, `quiet-ci -> quick`).
- install wizard supports `--model-profile <quick|deep|visual|writing>`.

## Browser profile switching

Use:
```text
/browser status
/browser profile playwright
/browser profile agent-browser
/browser doctor --json
```

Provider trade-offs:
- `playwright`: stable-first default and broad compatibility.
- `agent-browser`: optional path when your workflow depends on agent-browser tooling.

Recommended defaults:
- start with `playwright`
- switch to `agent-browser` only when you need those capabilities
- run `/browser doctor --json` after changes to confirm dependency readiness

Wizard support:
- `install_wizard.py` supports `--browser-profile <playwright|agent-browser>`
- interactive wizard includes the same provider choice during fresh setup and reconfigure

## Keyword-triggered execution modes

Epic 8 Task 8.2 adds a deterministic keyword detector engine:

- schema + precedence rules: `scripts/keyword_mode_schema.py`
- command wrapper: `scripts/keyword_mode_command.py`
- dictionary contract: `instructions/keyword_execution_modes.md`

Use:
```text
/keyword-mode status
/keyword-mode detect --prompt "safe-apply deep-analyze review this migration" --json
/keyword-mode apply --prompt "parallel-research deep-analyze inspect API usage" --json
/keyword-mode disable-keyword ulw
/keyword-mode enable-keyword ulw
/keyword-mode disable
/keyword-mode enable
/keyword-mode doctor --json
```

Detector behavior:
- case-insensitive keyword token matching (`ulw`, `deep-analyze`, `parallel-research`, `safe-apply`)
- deterministic precedence for conflicts (`safe-apply` > `deep-analyze` > `parallel-research` > `ulw`)
- prompt-level opt-out support (`no-keyword-mode` and `no-<keyword>` tokens)
- persisted runtime context via `keyword_modes` config section (`active_modes`, `effective_flags`)

Examples:
- basic: `/keyword-mode apply --prompt "safe-apply review this migration" --json`
- intermediate: `/keyword-mode disable-keyword ulw` then `/keyword-mode detect --prompt "ulw deep-analyze audit" --json`
- override path: `/keyword-mode detect --prompt "no-keyword-mode safe-apply deep-analyze" --json`

Anti-patterns:
- avoid mixing contradictory intent keywords casually (`ulw` + `deep-analyze`) unless you expect precedence conflict resolution.
- avoid relying on partial words (`deep` or `safe`) because matching is exact-token only.
- avoid forgetting local opt-outs in copied prompts; `no-keyword-mode` intentionally disables all activation for that request.

## Auto slash command detector

Epic 10 introduces an intent-mapping detector for common command families:

- schema + scoring engine: `scripts/auto_slash_schema.py`
- command wrapper: `scripts/auto_slash_command.py`
- contract guide: `instructions/auto_slash_detector.md`

Use:
```text
/auto-slash status --json
/auto-slash preview --prompt "run doctor diagnostics" --json
/auto-slash execute --prompt "run doctor diagnostics" --json
/auto-slash execute --prompt "run doctor diagnostics" --force --json
/auto-slash disable-command devtools
/auto-slash audit --limit 10 --json
/auto-slash doctor --json
```

Detector behavior:
- maps natural-language prompts to `/doctor`, `/stack`, `/nvim`, or `/devtools`
- enforces confidence + ambiguity thresholds before selecting a command
- defaults to preview-first execution (`execute` requires `--force`)
- keeps per-command enable/disable controls in layered config
- appends forced execution events to runtime audit log for traceability

Examples:
- basic: `/auto-slash preview --prompt "please run doctor diagnostics" --json`
- intermediate: `/auto-slash preview --prompt "switch to focus mode" --json`
- safety path: `/auto-slash execute --prompt "run doctor diagnostics" --json` then rerun with `--force`

Limitations:
- intentionally limited command set to reduce misfire risk
- does not auto-dispatch when prompts already include explicit slash commands
- low-confidence or ambiguous prompts return explicit no-op reasons

## Conditional rules injector

Epic 9 introduces a rules engine for conditional instruction injection:

- schema contract: `instructions/conditional_rules_schema.md`
- team pack examples: `instructions/rules_team_pack_examples.md`
- engine implementation: `scripts/rules_engine.py`
- command wrapper: `scripts/rules_command.py`

Use:
```text
/rules status
/rules explain scripts/selftest.py --json
/rules disable-id style-python
/rules enable-id style-python
/rules doctor --json
```

Rules are discovered from:
- user scope: `~/.config/opencode/rules/**/*.md`
- project scope: `.opencode/rules/**/*.md`

Precedence is deterministic: priority desc, then scope (`project` before `user`), then lexical rule id.

Recommended workflow:
- create project rules under `.opencode/rules/`
- run `/rules status` after edits to validate discovery
- use `/rules explain <path> --json` to verify effective rule stack before relying on behavior

## Plan execution artifact contract

Epic 14 Task 14.1 defines the baseline plan format and execution-state rules for the upcoming `/start-work <plan>` command:

- contract spec: `instructions/plan_artifact_contract.md`
- validation/workflow guide: `instructions/plan_execution_workflows.md`
- backend command: `scripts/start_work_command.py`
- format scope: markdown checklist + YAML metadata frontmatter
- validation scope: deterministic preflight failures with line-level remediation hints
- state model scope: `pending/in_progress/done/skipped` with strict transition semantics

Use:
```text
/start-work path/to/plan.md --json
/start-work-bg path/to/plan.md
/bg run --id <job-id>
/start-work status --json
/start-work deviations --json
/start-work-doctor-json
```

Integration notes:
- use `/start-work-bg` when you want queued, reviewable execution via the background subsystem before running `/bg run`
- `/digest run` now includes a `plan_execution` recap block (status, plan id, step counts, deviation count)
- `/doctor run` includes `start-work` health diagnostics for execution-state visibility

## Todo compliance model

Epic 15 Task 15.1 defines the baseline compliance contract for enforced todo execution:

- compliance spec: `instructions/todo_compliance_model.md`
- required states: `pending`, `in_progress`, `done`, `skipped`
- enforcement: one active item at a time with deterministic transition validation
- bypass path: explicit metadata + audit event requirements for controlled exceptions

Epic 15 Task 15.2 implements the enforcement backend:

- engine module: `scripts/todo_enforcement.py`
- `/start-work` now validates todo transitions before state mutation and blocks completion when required items remain unchecked
- compliance violations now emit deterministic remediation prompts and persisted audit events

Use:
```text
/todo status --json
/todo enforce --json
```

Compliant workflow pattern:
- run `/start-work path/to/plan.md --json`
- inspect `/todo status --json` for current state counts
- gate handoff/closure with `/todo enforce --json`

## Resume policy model

Epic 17 Task 17.1 defines the baseline policy contract for safe auto-resume behavior:

- policy spec: `instructions/resume_policy_model.md`
- interruption classes: `tool_failure`, `timeout`, `context_reset`, `process_crash`
- eligibility gate: checkpoint availability + idempotency + artifact readiness + attempt budget
- safety controls: class-specific cool-down windows and escalation after max attempts

Epic 17 Task 17.2 implements the recovery backend:

- engine module: `scripts/recovery_engine.py`
- backend path: `/start-work recover --interruption-class <tool_failure|timeout|context_reset|process_crash> --json`
- approval gate: non-idempotent pending steps require explicit `--approve-step <ordinal>`
- audit trail: persisted `resume_decision` and `resume_transition` events under runtime `resume.trail`

Epic 17 Task 17.3 adds operator-facing resume controls:

- command module: `scripts/resume_command.py`
- status surface: `/resume status --json` with explicit `reason_code` + human-readable `reason`
- execution control: `/resume now --interruption-class <class> --json`
- safety toggle: `/resume disable --json` to block resume attempts until re-enabled in runtime state
- actionable guidance: `resume_hints.next_actions` describes the next safe recovery command for the current reason code

Use:
```text
/resume status --json
/resume now --interruption-class tool_failure --json
/resume now --interruption-class tool_failure --approve-step 2 --json
/resume disable --json
```

Recovery playbooks:
- `resume_blocked_cooldown`: wait for cooldown and rerun `/resume status --json` until eligible.
- `resume_non_idempotent_step`: explicitly approve only the needed step with `--approve-step <ordinal>`.
- `resume_attempt_limit_reached`: escalate to manual review and restart from `/start-work <plan.md>` after inspection.
- `resume_disabled`: keep disabled during high-risk runs; re-enable by updating runtime `plan_execution.resume.enabled` to `true`.

Digest integration:
- `plan_execution.resume_hints` includes the latest resume eligibility state, reason code, and suggested next actions.
- use `/digest show` after interrupted runs to get lightweight recovery cues without loading full runtime state.

Verification notes:
- selftest now covers all interruption classes (`tool_failure`, `timeout`, `context_reset`, `process_crash`) plus cooldown and disable safeguards.
- install smoke includes interrupted-flow replay with expected non-idempotent block and explicit approval retry.

## Context resilience policy

Epic 11 Task 11.1 defines the baseline policy schema for context-window resilience:

- schema contract: `instructions/context_resilience_policy_schema.md`
- tuning guide: `instructions/context_resilience_tuning.md`
- pruning engine: `scripts/context_resilience.py`
- command diagnostics: `scripts/context_resilience_command.py`

Initial schema covers:
- truncation modes (`default`, `aggressive`)
- protected tools/messages to preserve critical evidence
- pruning/recovery notification levels (`quiet`, `normal`, `verbose`)

Engine behavior currently includes:
- duplicate message pruning for repeated non-protected context entries
- superseded write pruning (older writes to same target path)
- stale error purging once newer successful command outcomes exist beyond threshold
- preservation of protected artifacts and latest command outcomes as critical evidence
- recovery planning with automatic resume hints, safe fallback steps, and pruning diagnostics

Use:
```text
/resilience status --json
/resilience doctor --json
```

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
/plugin-enable-morph
/plugin-enable-worktree
/plugin-profile-lean
/plugin-profile-stable
/plugin-profile-experimental
/plugin-doctor-json
```

Global command helper shortcuts:

```text
/complete
/complete auto
/complete autopilot
/ac resume
/complete-families
/complete-doctor
```

`/complete <prefix>` returns ranked slash command suggestions with descriptions.
`/ac` is a short alias for `/complete`.

Supported plugin names: `notifier`, `morph`, `worktree`.

`all` applies only to the stable set: `notifier`.

Migration note: `supermemory` and `wakatime` were removed from this repo. If either still exists in a layered config override, remove those plugin entries manually or run `/plugin profile lean`.

`/plugin doctor` checks the current plugin setup and reports missing prerequisites before you enable additional plugins.

`/plugin doctor --json` (or `/plugin-doctor-json`) prints machine-readable diagnostics for automation.

`/setup-keys` prints exact environment/file snippets for missing API keys.

Profiles:
- `lean` -> `notifier`
- `stable` -> `notifier`
- `experimental` -> `stable` + `morph`, `worktree`

For Morph Fast Apply, set `MORPH_API_KEY` in your shell before enabling `morph`.

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

## Quality profiles inside OpenCode 🧪

Use these directly in OpenCode:

```text
/quality status
/quality profile fast
/quality profile strict
/quality profile off
/quality doctor
```

Autocomplete-friendly shortcuts:

```text
/quality-status
/quality-profile-fast
/quality-profile-strict
/quality-profile-off
/quality-doctor
```

`/quality` writes profile metadata to layered config under `quality` with toggles for TS lint/typecheck/tests and Python selftest.

Profiles:
- `off`: disable quality checks for local rapid iteration
- `fast`: lint+typecheck+selftest, skip heavier test passes
- `strict`: run full quality gates (including TS tests)

## Plugin gateway controls 🔌

Use these directly in OpenCode:

```text
/gateway status
/gateway enable
/gateway disable
/gateway doctor
```

Shortcuts:

```text
/gateway-status
/gateway-enable
/gateway-disable
/gateway-doctor
```

Notes:
- `/gateway enable` adds local file plugin entry for `gateway-core` into your config plugin list.
- `/gateway enable` now runs a safety preflight (bun + dist + required hook capabilities) and auto-reverts to disabled when preflight fails.
- use `/gateway enable --force` only if you intentionally want to bypass the preflight safeguard.
- `install.sh` now auto-prefers `plugin_gateway` mode when `bun` is available, and falls back to `python_command_bridge` when not available.
- `/gateway status` and `/gateway doctor` run orphan cleanup before reporting runtime loop state.
- `/gateway doctor --json` now includes `hook_diagnostics`, plugin entry dedupe telemetry, and process/runtime pressure diagnostics; it still fails when gateway is enabled without a valid built hook surface.
- set `MY_OPENCODE_GATEWAY_EVENT_AUDIT=1` to write hook dispatch diagnostics to `.opencode/gateway-events.jsonl` (override path with `MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH`).
- trigger-only context warnings now include a Nerd Font marker (`󰚩 Context Guard:`) so pressure events stand out without adding steady-state noise.
- context guard markers now support dual fallback mode (`󰚩 Context Guard [Context Guard]:`) and configurable verbosity (`minimal`, `normal`, `debug`) in gateway hook config.
- context and compaction safeguards now apply across providers (not Anthropic-only), using a configurable default context limit for non-Anthropic providers.
- global multi-session pressure warnings now trigger via `global-process-pressure` when concurrent `--continue` sessions/process counts or RSS exceed thresholds.
- critical global RSS pressure (`>= 10GB` by default) now emits a critical guard event and auto-pauses continuation for the current session.
- critical response now supports a configurable escalation ladder (window + pause/escalation event thresholds) before stronger repeated-critical messaging.
- critical events can trigger local desktop notifications (best effort on macOS/Linux), with audit reason codes for sent/failed notification attempts.
- `/gateway status --json` now reports `guard_event_counters` including session-correlated pressure observations (`session_pressure_attribution`, non-causal) and critical trigger timestamps.
- `/gateway doctor --json` now exposes `remediation_commands` when critical pressure signals are detected.
- `/gateway tune memory --json` now suggests a balanced memory profile based on current pressure/counter telemetry.
- `pressure-escalation-guard` now blocks non-essential reviewer/verifier/explore/librarian/general task escalations while high continuation pressure is active (override via blocker/critical prompt patterns).
- gateway event audit now supports bounded rotation via `MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES` and `MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS`.
- see `docs/memory-incident-playbook.md` for a fast detect/stabilize/recover/verify incident flow.

Gateway event audit baseline (recommended before memory tuning):

```bash
MY_OPENCODE_GATEWAY_EVENT_AUDIT=1 /gateway status --json
MY_OPENCODE_GATEWAY_EVENT_AUDIT=1 /gateway doctor --json
```

- Keep a normal 20-30 minute coding session and compare `process_pressure` plus `runtime_staleness` from `/gateway status --json` before/after.
- Review `.opencode/gateway-events.jsonl` for recurring `context-window-monitor` and `preemptive-compaction` events to confirm cadence is controlled but recurring.

Gateway orphan cleanup report fields (`--json`):

| Field | Type | Meaning |
|---|---|---|
| `orphan_cleanup.attempted` | `boolean` | `true` when cleanup check was evaluated. |
| `orphan_cleanup.changed` | `boolean` | `true` when active orphan loop was deactivated. |
| `orphan_cleanup.reason` | `string` | Cleanup result reason (`state_missing`, `not_active`, `within_age_limit`, `invalid_started_at`, `stale_loop_deactivated`). |
| `orphan_cleanup.state_path` | `string|null` | Updated state path when cleanup changes were persisted. |

Gateway hook diagnostics fields (`--json`):

| Field | Type | Meaning |
|---|---|---|
| `hook_diagnostics.source_hooks_exist` | `boolean` | Source hook modules exist for autopilot-loop, continuation, and safety. |
| `hook_diagnostics.dist_hooks_exist` | `boolean` | Built dist hook modules exist for autopilot-loop, continuation, and safety. |
| `hook_diagnostics.dist_exposes_tool_execute_before` | `boolean` | Built plugin exports slash-command interception handler. |
| `hook_diagnostics.dist_exposes_chat_message` | `boolean` | Built plugin exports chat-message lifecycle handler. |
| `hook_diagnostics.dist_continuation_handles_session_idle` | `boolean` | Continuation hook handles idle-cycle progression logic. |

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
- `scripts/session_command.py` - backend script for `/session`
- `scripts/opencode_session.sh` - optional wrapper to run digest on process exit
- `scripts/telemetry_command.py` - backend script for `/telemetry`
- `scripts/post_session_command.py` - backend script for `/post-session`
- `scripts/policy_command.py` - backend script for `/policy`
- `scripts/doctor_command.py` - backend script for `/doctor`
- `scripts/config_command.py` - backend script for `/config`
- `scripts/stack_profile_command.py` - backend script for `/stack`
- `scripts/browser_command.py` - backend script for `/browser`
- `scripts/start_work_command.py` - backend script for `/start-work`
- `scripts/autoflow_adapter.py` - orchestration adapter for `/autoflow` transition and explain planning
- `scripts/autoflow_command.py` - unified `/autoflow` command surface with dry-run and kill-switch controls
- `scripts/budget_command.py` - backend script for `/budget`
- `scripts/release_train_engine.py` - release-train backend engine for preflight, draft, and publish gating
- `scripts/release_train_command.py` - `/release-train` command surface and doctor/checklist integration
- `scripts/hotfix_runtime.py` - incident hotfix runtime profile with checkpoint and timeline capture
- `scripts/todo_command.py` - backend script for `/todo`
- `scripts/resume_command.py` - backend script for `/resume`
- `scripts/safe_edit_adapters.py` - semantic safe-edit adapter and validation helpers
- `scripts/safe_edit_command.py` - `/safe-edit` command surface for semantic adapter planning and diagnostics
- `scripts/todo_enforcement.py` - shared todo compliance enforcement helpers
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
