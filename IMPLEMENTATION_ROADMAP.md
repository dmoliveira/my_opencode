# My OpenCode Implementation Roadmap

This roadmap tracks phased delivery of advanced orchestration features inspired by gaps identified versus `oh-my-opencode`.

## How to use this file

- Task completion: use `[ ]` and `[x]`.
- Epic status values: `planned`, `in_progress`, `paused`, `merged`, `done`, `postponed`.
- Recommendation: move only one epic to `in_progress` at a time.

## Status Playbook

- `planned`: scoped and ready, not started.
- `in_progress`: actively being implemented now.
- `paused`: started but intentionally stopped; can resume any time.
- `merged`: scope absorbed into another epic to avoid duplication.
- `postponed`: intentionally deferred; not expected this cycle.
- `done`: fully implemented, documented, and validated.

## Priority Playbook

- `High`: foundational or high-risk controls; implement in near-term phases.
- `Medium`: meaningful acceleration; schedule after foundations stabilize.
- `Low`: optional power-user capability; defer when capacity is constrained.

## Command Boundary Map

Use this map to avoid overlapping implementations.

- `/start-work` (E14): executes a prepared plan artifact step-by-step.
- `/autoflow` (E22): unified orchestration wrapper for plan/todo/recovery/report primitives.
- `/autopilot` (E28): bounded objective runner on top of `/autoflow` with strict budget control.
- `/loop` (merged into E22/E28): optional loop controls, not a standalone roadmap epic.
- `/hotfix` (E25): constrained emergency path with mandatory minimum safeguards.

## Epic Dashboard

| Epic | Title | Status | Priority | Depends On | br Issue | Notes |
|---|---|---|---|---|---|---|
| E1 | Config Layering + JSONC Support | done | High | - | bd-1g0, bd-208, bd-4j1 | Foundation for most later epics |
| E2 | Background Task Orchestration | done | High | E1 | bd-1ob, bd-3lf, bd-2xo, bd-mb2 | Keep minimal and stable first |
| E3 | Refactor Workflow Command | done | High | E1 | bd-zfx, bd-vc3, bd-2ps, bd-3fr | Safer rollout after config layering |
| E4 | Continuation and Safety Hooks | done | Medium | E1, E2 | bd-1h0, bd-1ex, bd-1dr, bd-3uq | Start with minimal hooks only |
| E5 | Category-Based Model Routing | done | Medium | E1 | bd-2z6, bd-m48, bd-15y, bd-222 | Can partially overlap with E2/E3 |
| E6 | Session Intelligence and Resume Tooling | paused | Medium | E2 | TBD | Resume when core orchestration stabilizes |
| E7 | Tmux Visual Multi-Agent Mode | postponed | Low | E2 | TBD | Optional power-user feature |
| E8 | Keyword-Triggered Execution Modes | done | High | E1, E4 | bd-302, bd-2fb, bd-2zq, bd-3dp | Fast power-mode activation from prompt text |
| E9 | Conditional Rules Injector | done | High | E1 | bd-1q8, bd-3rj, bd-fo8, bd-2ik | Enforce project conventions with scoped rules |
| E10 | Auto Slash Command Detector | paused | Medium | E1, E8 | TBD | Resume only if intent precision stays high in prototypes |
| E11 | Context-Window Resilience Toolkit | done | High | E4 | bd-2tj, bd-n9y, bd-2t0, bd-18e | Improve long-session stability and recovery |
| E12 | Provider/Model Fallback Visibility | done | Medium | E5 | bd-1jq, bd-298, bd-194, bd-2gq | Explain why model routing decisions happen |
| E13 | Browser Automation Profile Switching | done | Medium | E1 | bd-3rs, bd-2qy, bd-f6g, bd-393 | Toggle Playwright/agent-browser with checks |
| E14 | Plan-to-Execution Bridge Command | done | Medium | E2, E3 | bd-1z6, bd-2te, bd-3sg, bd-2bv | Execute validated plans with progress tracking |
| E15 | Todo Enforcer and Plan Compliance | done | High | E14 | bd-l9c | Keep execution aligned with approved checklists |
| E16 | Comment and Output Quality Checker Loop | merged | Medium | E23 | TBD | Merged into E23 (PR Review Copilot) |
| E17 | Auto-Resume and Recovery Loop | in_progress | High | E11, E14 | bd-1ho | Resume interrupted work from checkpoints safely |
| E18 | LSP/AST-Assisted Safe Edit Mode | planned | High | E3 | TBD | Prefer semantic edits over plain text replacements |
| E19 | Session Checkpoint Snapshots | planned | Medium | E2, E17 | TBD | Durable state for rollback and restart safety |
| E20 | Execution Budget Guardrails | planned | High | E2, E11 | TBD | Bound time/tool/token usage for autonomous runs |
| E21 | Bounded Loop Mode Presets | merged | Medium | E22, E28 | TBD | Merged into E22/E28 loop controls |
| E22 | Autoflow Unified Orchestration Command | planned | High | E14, E15, E17, E19, E20 | TBD | One command for plan-run-resume-report lifecycle |
| E23 | PR Review Copilot | planned | High | E3 | TBD | Pre-PR quality, output, and risk review automation |
| E24 | Release Train Assistant | planned | High | E14, E23 | TBD | Validate, draft, and gate releases reliably |
| E25 | Incident Hotfix Mode | planned | Medium | E20, E22 | TBD | Constrained emergency workflow with strict safety |
| E26 | Repo Health Score and Drift Monitor | planned | Medium | E9, E12, E20 | TBD | Operational visibility and continuous diagnostics |
| E27 | Knowledge Capture from Completed Tasks | planned | Medium | E9, E14, E23 | TBD | Convert delivered work into reusable team memory |
| E28 | Autopilot Objective Runner Command | paused | High | E20, E22 | TBD | Start only after real-world Autoflow stability evidence |

## Scope Guardrails

- Keep migration **stable-first**: ship low-risk foundations before advanced orchestration.
- Prefer additive changes and compatibility fallbacks over breaking behavior.
- Do not expand to unrelated feature areas during in-progress epics.

## Value Gate (Before Starting Any Epic)

Start an epic only when all are true:

- Clear user pain is documented and measurable.
- Existing command/profile cannot solve the problem with small changes.
- Expected value is higher than maintenance cost after launch.
- Rollback path is defined and tested.

If any condition is missing, keep the epic `paused` or `postponed`.

## Complexity Budget

- Prefer extending existing commands over introducing new top-level commands.
- Prefer one robust implementation path over multiple experimental variants.
- Defer optional UX layers until core reliability/diagnostics are stable.

## Dependency Rules

- Dependencies must reference earlier or same-phase epics only (no forward references).
- Avoid circular dependencies; when uncertain, split shared prerequisites into a separate task.
- If an epic dependency changes, update both the epic block and dashboard row in the same PR.

## Robustness Gate (High-Risk Epics)

For high-risk automation epics (E20, E22, E28), require:

- A prototype phase with success/failure metrics before full implementation.
- A kill-switch and rollback checklist in the first delivery PR.
- A post-release observation window with explicit go/no-go decision.

## Out of Scope (for this roadmap cycle)

- Full rewrite of existing command scripts in a new language/runtime.
- Broad UI redesign of docs/install flows unrelated to orchestration objectives.
- Large provider/model benchmarking initiatives beyond routing correctness.

## Documentation Standard (All Epics)

Every command-oriented epic must ship all of the following:

- README updates with command purpose and options.
- At least 3 practical examples (basic, intermediate, failure/recovery).
- One end-to-end workflow showing where the command maximizes throughput.

## Task Authoring Simplification Rules

- Prefer one concrete verb per subtask (`define`, `implement`, `integrate`, `verify`, `document`).
- Avoid duplicate subtasks when covered by cross-cutting criteria in `Task C2`.
- Keep subtask text implementation-specific; move generic policy wording to shared sections.

## Epic Start Checklist

- [ ] Epic moved to `in_progress` in this file and dashboard row updated.
- [ ] Matching `br` issue created and linked in dashboard.
- [ ] Worktree branch created using full workflow.
- [ ] Success metrics and risk notes reviewed before implementation starts.

## Epic Finish Checklist

- [ ] All epic tasks/subtasks and exit criteria checked `[x]`.
- [ ] Docs and tests updated and validated (`make validate`, `make selftest`, `make install-test`).
- [ ] PR merged and cleanup completed (branch/worktree removed, main synced).
- [ ] Epic status moved to `done`, dashboard row updated, and weekly log updated.

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Config precedence bugs (E1) break expected behavior | High | Add golden-file tests for precedence + compatibility fallback |
| Background jobs leak state/processes (E2) | High | Add retention cleanup, stale timeout, and cancel-safe handling |
| Refactor workflow too aggressive (E3) | Medium | Default to safe mode and require verification gates |
| Hooks generate noise/regressions (E4) | Medium | Keep hooks opt-in/disableable with deterministic ordering |
| Model routing confusion (E5) | Medium | Expose effective resolution in doctor output and docs |
| Session index growth (E6) | Low | Add retention policy and cleanup command |
| Tmux complexity support burden (E7) | Low | Keep postponed unless strong usage signal appears |
| Keyword mode false positives (E8) alter behavior unexpectedly | Medium | Require explicit keywords and add safe opt-out switch |
| Rules injector over-constrains outputs (E9) | Medium | Add precedence, conflict reporting, and per-rule disable |
| Auto slash misfires on normal prompts (E10) | Medium | Add confidence threshold and preview-before-run mode |
| Context pruning removes needed evidence (E11) | High | Protect critical tools/messages and keep reversible summaries |
| Fallback reporting leaks noisy internals (E12) | Low | Keep verbose chain behind debug/doctor views only |
| Browser profile setup drift (E13) | Medium | Add doctor checks and install verification scripts |
| Plan execution diverges from approved plan (E14) | Medium | Lock plan snapshot and require explicit deviation notes |
| Todo enforcer blocks valid edge workflows (E15) | Medium | Add bypass with explicit annotation + audit trail |
| Auto-resume repeats harmful action (E17) | High | Require idempotency checks and last-step verification |
| LSP/AST mode unavailable in some repos (E18) | Medium | Provide graceful fallback to safe text-mode edits |
| Checkpoint snapshots grow too quickly (E19) | Low | Add retention cap and compression/rotation |
| Budget guardrails too strict for complex tasks (E20) | Medium | Provide profile-based limits and controlled override |
| Autoflow hides too much control and confuses users (E22) | Medium | Keep subcommands explicit and expose dry-run plus explain mode |
| PR copilot misses critical regressions (E23) | Medium | Blend deterministic checks with configurable risk heuristics |
| Release assistant automates wrong tag/version (E24) | High | Enforce explicit version confirmation and dry-run output |
| Hotfix mode bypasses important checks (E25) | High | Keep mandatory minimum verification and post-hotfix audit |
| Health score becomes noisy and ignored (E26) | Medium | Weight high-signal checks and suppress repetitive noise |
| Knowledge capture stores low-quality patterns (E27) | Medium | Add approval workflow and confidence scoring before publish |
| Autopilot over-automation causes unintended actions (E28) | High | Keep objective scope limits, dry-run default, and hard budget caps |

---

## Epic 1 - Config Layering + JSONC Support

**Status:** `paused`
**Priority:** High
**Goal:** Add user/project layered config and JSONC parsing so behavior can be customized per repo without mutating global defaults.
**Depends on:** None

- [x] Task 1.1: Define configuration precedence and file discovery
  - [x] Subtask 1.1.1: Document precedence order (`project` > `user` > bundled defaults)
  - [x] Subtask 1.1.2: Define file paths (`.opencode/my_opencode.jsonc`, `.opencode/my_opencode.json`, `~/.config/opencode/my_opencode.jsonc`, `~/.config/opencode/my_opencode.json`)
  - [x] Subtask 1.1.3: Define merge semantics (object merge, array replacement, explicit overrides)
- [x] Task 1.2: Implement config loader module
  - [x] Subtask 1.2.1: Create parser supporting JSON and JSONC
  - [x] Subtask 1.2.2: Implement precedence-based merge and validation
  - [x] Subtask 1.2.3: Add schema validation and actionable error messages
- [x] Task 1.3: Integrate layered config into command scripts
  - [x] Subtask 1.3.1: Wire loader into `mcp/plugin/notify/telemetry/post-session/policy/stack/nvim/devtools` flows
  - [x] Subtask 1.3.2: Keep existing env var overrides as highest-priority runtime override
  - [x] Subtask 1.3.3: Add compatibility fallback when only legacy files exist
- [x] Task 1.4: Documentation and tests
  - [x] Subtask 1.4.1: Add docs with examples for user/project overrides
  - [x] Subtask 1.4.2: Add selftests for precedence and JSONC behavior
  - [x] Subtask 1.4.3: Add install-test coverage for layered config discovery
- [x] Exit criteria: all command scripts resolve config through shared layered loader
- [x] Exit criteria: precedence + JSONC behavior covered by tests and docs

---

## Epic 2 - Background Task Orchestration (Minimal Safe Version)

**Status:** `done`
**Priority:** High
**Goal:** Add lightweight background job workflows for async research and result retrieval.
**Depends on:** Epic 1

- [x] Task 2.1: Design minimal background task model
  - [x] Subtask 2.1.1: Define job lifecycle (`queued`, `running`, `completed`, `failed`, `cancelled`)
  - [x] Subtask 2.1.2: Define persistent state file format and retention policy
  - [x] Subtask 2.1.3: Define maximum concurrency and stale-timeout defaults
  - [x] Notes: See `instructions/background_task_model.md` for lifecycle transitions, storage schema, and deterministic defaults.
- [x] Task 2.2: Implement background task manager script
  - [x] Subtask 2.2.1: Add enqueue/run/read/list/cancel operations
  - [x] Subtask 2.2.2: Capture stdout/stderr and execution metadata
  - [x] Subtask 2.2.3: Add stale job detection and cleanup
  - [x] Notes: Implemented in `scripts/background_task_manager.py` with deterministic selftest coverage.
- [x] Task 2.3: Expose OpenCode commands
  - [x] Subtask 2.3.1: Add `/bg` command family (`start|status|list|read|cancel`)
  - [x] Subtask 2.3.2: Add autocomplete shortcuts for high-frequency operations
  - [x] Subtask 2.3.3: Integrate with `/doctor` summary checks
  - [x] Notes: Added `/bg` command + shortcuts in `opencode.json` and wired `bg` diagnostics into `scripts/doctor_command.py`.
- [x] Task 2.4: Notifications and diagnostics
  - [x] Subtask 2.4.1: Add optional completion notification via existing notify stack
  - [x] Subtask 2.4.2: Add JSON diagnostics output for background subsystem
  - [x] Subtask 2.4.3: Add docs and examples for async workflows
  - [x] Notes: `scripts/background_task_manager.py` now emits optional notify-aligned alerts and exposes richer `status --json`/`doctor --json` diagnostics.
- [x] Exit criteria: background workflows are deterministic, inspectable, and cancel-safe
- [x] Exit criteria: doctor + docs cover baseline troubleshooting

---

## Epic 3 - Refactor Workflow Command (`/refactor-lite`)

**Status:** `done`
**Priority:** High
**Goal:** Add a safe, repeatable refactor workflow command using existing tools and verification gates.
**Depends on:** Epic 1

- [x] Task 3.1: Define command contract
  - [x] Subtask 3.1.1: Define syntax (`/refactor-lite <target> [--scope] [--strategy]`)
  - [x] Subtask 3.1.2: Define safe defaults and guardrails (`safe` by default)
  - [x] Subtask 3.1.3: Define success/failure output shape
  - [x] Notes: See `instructions/refactor_lite_contract.md`.
- [x] Task 3.2: Implement workflow backend
  - [x] Subtask 3.2.1: Add preflight analysis step (grep + file map)
  - [x] Subtask 3.2.2: Add structured plan preview output
  - [x] Subtask 3.2.3: Add post-change verification hooks (`make validate`, optional `make selftest`)
  - [x] Notes: Implemented in `scripts/refactor_lite_command.py` with deterministic selftest coverage.
- [x] Task 3.3: OpenCode integration
  - [x] Subtask 3.3.1: Add `/refactor-lite` and helper commands to `opencode.json`
  - [x] Subtask 3.3.2: Add installer self-check hints
  - [x] Subtask 3.3.3: Add `/doctor` optional check when command is configured
  - [x] Notes: Added `/refactor-lite` templates, installer hints, and optional `refactor-lite` doctor check.
- [x] Task 3.4: Tests and docs
  - [x] Subtask 3.4.1: Add selftest scenarios for argument parsing and safe-mode behavior
  - [x] Subtask 3.4.2: Add docs for safe vs aggressive strategies
  - [x] Subtask 3.4.3: Add install-test smoke checks
  - [x] Notes: Expanded `/refactor-lite` selftests for missing-target and safe-mode ambiguity handling, plus install smoke coverage.
- [x] Exit criteria: safe mode is default and validates before completion
- [x] Exit criteria: failure output gives actionable remediation

---

## Epic 4 - Continuation and Safety Hooks (Targeted)

**Status:** `done`
**Priority:** Medium
**Goal:** Add minimal lifecycle automation hooks for continuation and resilience without introducing heavy complexity.
**Depends on:** Epic 1, Epic 2

- [x] Task 4.1: Hook framework baseline
  - [x] Subtask 4.1.1: Define hook events (`PreToolUse`, `PostToolUse`, `Stop`) for our scope
  - [x] Subtask 4.1.2: Define hook config and disable list
  - [x] Subtask 4.1.3: Implement deterministic execution order
  - [x] Notes: Added `scripts/hook_framework.py` baseline planner and selftest coverage for deterministic ordering + disabled hook filtering.
- [x] Task 4.2: Initial hooks
  - [x] Subtask 4.2.1: Add continuation reminder hook for unfinished explicit checklists
  - [x] Subtask 4.2.2: Add output truncation safety hook for large tool outputs
  - [x] Subtask 4.2.3: Add basic error recovery hint hook for common command failures
  - [x] Notes: Added `scripts/hook_actions.py` and `/hooks` command for continuation reminders, truncation safety, and common failure recovery hints.
- [x] Task 4.3: Governance and controls
  - [x] Subtask 4.3.1: Add opt-out per hook via config
  - [x] Subtask 4.3.2: Add telemetry-safe logging for hook actions
  - [x] Subtask 4.3.3: Add docs for enabling/disabling hooks
  - [x] Notes: Added `/hooks` config controls (`enable`, `disable`, per-hook toggle), telemetry-safe hook audit logging, and governance docs.
- [x] Task 4.4: Verification
  - [x] Subtask 4.4.1: Add selftests for hook order and disable behavior
  - [x] Subtask 4.4.2: Add install-test smoke checks
  - [x] Subtask 4.4.3: Add doctor check summary for hook health
  - [x] Notes: Added `/hooks doctor --json`, included hook health in unified `/doctor`, and expanded deterministic selftests/install smoke for hook controls.
- [x] Exit criteria: hooks are optional, predictable, and low-noise by default
- [x] Exit criteria: disabling individual hooks is tested and documented

---

## Epic 5 - Category-Based Model Routing

**Status:** `done`
**Priority:** Medium
**Goal:** Introduce category presets (quick/deep/visual/writing) for better cost/performance model routing.
**Depends on:** Epic 1

- [x] Task 5.1: Define category schema
  - [x] Subtask 5.1.1: Define baseline categories and descriptions
  - [x] Subtask 5.1.2: Define category settings (`model`, `temperature`, `reasoning`, `verbosity`)
  - [x] Subtask 5.1.3: Define fallback behavior when model is unavailable
  - [x] Notes: Added baseline schema/validation/resolution helpers in `scripts/model_routing_schema.py` and schema docs in `instructions/model_routing_schema.md`.
- [x] Task 5.2: Implement resolution engine
  - [x] Subtask 5.2.1: Resolve from user override -> category default -> system default
  - [x] Subtask 5.2.2: Add deterministic fallback logging for diagnostics
  - [x] Subtask 5.2.3: Add integration points with `/stack` and wizard profiles
  - [x] Notes: Added `scripts/model_routing_command.py`, deterministic resolution trace in `resolve_model_settings`, and stack/wizard integration for model profile selection.
- [x] Task 5.3: UX and docs
  - [x] Subtask 5.3.1: Add `/model-profile` command surface
  - [x] Subtask 5.3.2: Document practical routing examples by workload
  - [x] Subtask 5.3.3: Add doctor visibility for effective routing
  - [x] Notes: Added `/model-profile` aliases over routing backend, practical workload guidance in README, and `model-routing` coverage in unified `/doctor`.
- [x] Task 5.4: Verification
  - [x] Subtask 5.4.1: Add tests for precedence and fallback
  - [x] Subtask 5.4.2: Add tests for stack integration
  - [x] Subtask 5.4.3: Add install-test checks
  - [x] Notes: Added deterministic fallback-reason assertions in selftest and expanded install smoke routing resolve scenarios.
- [x] Exit criteria: effective model resolution is visible and explainable
- [x] Exit criteria: fallback behavior is deterministic and tested

---

## Epic 6 - Session Intelligence and Resume Tooling

**Status:** `paused`
**Priority:** Medium
**Goal:** Add lightweight session listing/search and structured resume cues.
**Depends on:** Epic 2

- [ ] Task 6.1: Session metadata index
  - [ ] Subtask 6.1.1: Define session metadata store format
  - [ ] Subtask 6.1.2: Record key events and timestamps
  - [ ] Subtask 6.1.3: Add retention and cleanup strategy
- [ ] Task 6.2: Session commands
  - [ ] Subtask 6.2.1: Add `/session list`
  - [ ] Subtask 6.2.2: Add `/session show <id>`
  - [ ] Subtask 6.2.3: Add `/session search <query>`
- [ ] Task 6.3: Resume support
  - [ ] Subtask 6.3.1: Add `resume-hints` output after interrupted workflows
  - [ ] Subtask 6.3.2: Add docs for common recovery playbooks
  - [ ] Subtask 6.3.3: Add optional integration with digest summaries
- [ ] Exit criteria: sessions are searchable and resume hints are practical

---

## Epic 7 - Tmux Visual Multi-Agent Mode

**Status:** `postponed`
**Priority:** Low
**Goal:** Add optional tmux pane orchestration for observing background jobs in real time.
**Depends on:** Epic 2
**Postpone reason:** deliver core orchestration reliability before adding visual runtime complexity.

- [ ] Task 7.1: Design tmux mode constraints
  - [ ] Subtask 7.1.1: Define supported layouts and minimum pane sizes
  - [ ] Subtask 7.1.2: Define server mode and attach requirements
  - [ ] Subtask 7.1.3: Define safe fallback when not inside tmux
- [ ] Task 7.2: Implement tmux integration
  - [ ] Subtask 7.2.1: Spawn background jobs in dedicated panes
  - [ ] Subtask 7.2.2: Stream status and auto-close completed panes
  - [ ] Subtask 7.2.3: Add pane naming and collision handling
- [ ] Task 7.3: UX and docs
  - [ ] Subtask 7.3.1: Add `/tmux` status/config helpers
  - [ ] Subtask 7.3.2: Add shell helper snippets for macOS/Linux
  - [ ] Subtask 7.3.3: Add troubleshooting for pane/orphan cleanup
- [ ] Exit criteria: feature is opt-in, non-disruptive, and gracefully degrades outside tmux

---

## Epic 8 - Keyword-Triggered Execution Modes

**Status:** `done`
**Priority:** High
**Goal:** Enable explicit keywords (for example, `ulw`) to activate high-value execution modes without manual command chaining.
**Depends on:** Epic 1, Epic 4

- [x] Task 8.1: Define keyword dictionary and behavior mapping
  - [x] Subtask 8.1.1: Define reserved keywords (`ulw`, `deep-analyze`, `parallel-research`, `safe-apply`)
  - [x] Subtask 8.1.2: Define mode side-effects and precedence rules
  - [x] Subtask 8.1.3: Define explicit opt-out syntax and defaults
  - [x] Notes: Added `instructions/keyword_execution_modes.md` with deterministic keyword matching, precedence, conflict handling, and opt-out syntax.
- [x] Task 8.2: Implement keyword detector engine
  - [x] Subtask 8.2.1: Parse user prompts and resolve keyword intents
  - [x] Subtask 8.2.2: Apply mode flags to runtime execution context
  - [x] Subtask 8.2.3: Add conflict handling when multiple keywords appear
  - [x] Notes: Added `scripts/keyword_mode_schema.py` + `scripts/keyword_mode_command.py` for deterministic token matching, precedence-aware conflict handling, and persisted keyword mode runtime context.
- [x] Task 8.3: User visibility and control
  - [x] Subtask 8.3.1: Add status command for active mode stack
  - [x] Subtask 8.3.2: Add config toggles to disable selected keywords
  - [x] Subtask 8.3.3: Document examples and anti-patterns
  - [x] Notes: Extended `/keyword-mode` with global enable/disable and per-keyword toggles, surfaced effective mode stack details in status output, and documented examples/anti-patterns in README.
- [x] Task 8.4: Verification
  - [x] Subtask 8.4.1: Add tests for matching accuracy and false positives
  - [x] Subtask 8.4.2: Add install-test smoke scenarios for keyword activation
  - [x] Subtask 8.4.3: Add doctor visibility for keyword subsystem
  - [x] Notes: Expanded selftest/install smoke for false-positive resistance and keyword toggle flows, and added `/doctor` integration via `keyword-mode` diagnostics.
- [x] Exit criteria: keyword activation is deterministic and low-surprise
- [x] Exit criteria: users can disable or override keyword behavior safely

---

## Epic 9 - Conditional Rules Injector

**Status:** `done`
**Priority:** High
**Goal:** Load project/user rule files with optional glob conditions to enforce coding conventions contextually.
**Depends on:** Epic 1

- [x] Task 9.1: Define rule file schema and precedence
  - [x] Subtask 9.1.1: Define frontmatter fields (`globs`, `alwaysApply`, `description`, `priority`)
  - [x] Subtask 9.1.2: Define project/user rule search paths
  - [x] Subtask 9.1.3: Define rule conflict resolution strategy
  - [x] Notes: Added `instructions/conditional_rules_schema.md` with deterministic discovery, matching, precedence, conflict handling, and validation requirements.
- [x] Task 9.2: Implement rule discovery and matching engine
  - [x] Subtask 9.2.1: Discover markdown rule files recursively
  - [x] Subtask 9.2.2: Match rules by file path and operation context
  - [x] Subtask 9.2.3: Inject effective rule set into execution context
  - [x] Notes: Added `scripts/rules_engine.py` with frontmatter parsing, layered discovery, deterministic precedence sorting, duplicate-id conflict reporting, and effective rule stack resolution helpers.
- [x] Task 9.3: Operations and diagnostics
  - [x] Subtask 9.3.1: Add `/rules status` and `/rules explain <path>` commands
  - [x] Subtask 9.3.2: Add per-rule disable list in config
  - [x] Subtask 9.3.3: Add doctor output for rule source and conflicts
  - [x] Notes: Added `scripts/rules_command.py` with status/explain/disable-id/enable-id/doctor workflows, wired `/doctor` integration for rules diagnostics, and added command aliases/install smoke coverage.
- [x] Task 9.4: Verification and docs
  - [x] Subtask 9.4.1: Add tests for glob matching and precedence
  - [x] Subtask 9.4.2: Add docs with examples for team rule packs
  - [x] Subtask 9.4.3: Add install-test smoke checks
  - [x] Notes: Expanded rules selftest/install smoke coverage for precedence/always-apply/disable-id flows and added team rule-pack examples in `instructions/rules_team_pack_examples.md`.
- [x] Exit criteria: applicable rules are explainable for any target file
- [x] Exit criteria: conflicting rules are surfaced with clear remediation

---

## Epic 10 - Auto Slash Command Detector

**Status:** `paused`
**Priority:** Medium
**Goal:** Detect natural-language intent that maps to existing slash commands and optionally execute with guardrails.
**Depends on:** Epic 1, Epic 8

- [ ] Task 10.1: Define intent-to-command mappings
  - [ ] Subtask 10.1.1: Map common intents to existing commands (`/doctor`, `/stack`, `/nvim`, `/devtools`)
  - [ ] Subtask 10.1.2: Define confidence scoring and ambiguity thresholds
  - [ ] Subtask 10.1.3: Define no-op behavior when confidence is low
- [ ] Task 10.2: Implement detection and dispatch
  - [ ] Subtask 10.2.1: Parse prompt intent candidates
  - [ ] Subtask 10.2.2: Resolve best command + argument template
  - [ ] Subtask 10.2.3: Execute with safe preview mode option
- [ ] Task 10.3: Controls and safety
  - [ ] Subtask 10.3.1: Add config toggles (global and per-command)
  - [ ] Subtask 10.3.2: Add audit log for auto-executed commands
  - [ ] Subtask 10.3.3: Add fast cancel/undo guidance in output
- [ ] Task 10.4: Validation
  - [ ] Subtask 10.4.1: Add tests for mapping precision and ambiguity handling
  - [ ] Subtask 10.4.2: Add smoke tests for preview + execute modes
  - [ ] Subtask 10.4.3: Add docs with examples and limitations
- [ ] Exit criteria: detector reduces manual command typing without unsafe surprises
- [ ] Exit criteria: low-confidence intents never auto-execute

---

## Epic 11 - Context-Window Resilience Toolkit

**Status:** `done`
**Priority:** High
**Goal:** Improve long-session reliability with configurable truncation/pruning/recovery policies.
**Depends on:** Epic 4

- [x] Task 11.1: Define resilience policy schema
  - [x] Subtask 11.1.1: Define truncation modes (`default`, `aggressive`)
  - [x] Subtask 11.1.2: Define protected tools/messages list
  - [x] Subtask 11.1.3: Define pruning and recovery notification levels
  - [x] Notes: Added `instructions/context_resilience_policy_schema.md` documenting config shape, truncation modes, protected artifact constraints, notification levels, and validation requirements.
- [x] Task 11.2: Implement context pruning engine
  - [x] Subtask 11.2.1: Add deduplication and superseded-write pruning
  - [x] Subtask 11.2.2: Add old-error input purge with turn thresholds
  - [x] Subtask 11.2.3: Preserve critical evidence and command outcomes
  - [x] Notes: Added `scripts/context_resilience.py` with policy resolution plus deterministic pruning (dedupe, superseded writes, stale error purge, budget trim) while preserving protected artifacts and latest command outcomes.
- [x] Task 11.3: Recovery workflows
  - [x] Subtask 11.3.1: Add automatic resume hints after successful recovery
  - [x] Subtask 11.3.2: Add safe fallback when recovery cannot proceed
  - [x] Subtask 11.3.3: Add diagnostics for pruning/recovery actions
  - [x] Notes: Added recovery-plan generation in `scripts/context_resilience.py` with resume hints, safe fallback actions, and structured pruning/recovery diagnostics.
- [x] Task 11.4: Validation and docs
  - [x] Subtask 11.4.1: Add stress tests for long-session behavior
  - [x] Subtask 11.4.2: Add docs for tuning resilience settings
  - [x] Subtask 11.4.3: Add doctor summary for context resilience health
  - [x] Notes: Added `instructions/context_resilience_tuning.md`, `/resilience` command diagnostics, and unified `/doctor` resilience subsystem checks.
- [x] Exit criteria: long sessions remain stable under constrained context budgets
- [x] Exit criteria: recovery decisions are transparent and auditable

---

## Epic 12 - Provider/Model Fallback Visibility

**Status:** `done`
**Priority:** Medium
**Goal:** Make model routing and provider fallback decisions observable and explainable.
**Depends on:** Epic 5

- [x] Task 12.1: Define explanation model
  - [x] Subtask 12.1.1: Define resolution trace format (requested -> attempted -> selected)
  - [x] Subtask 12.1.2: Define compact vs verbose output levels
  - [x] Subtask 12.1.3: Define redaction rules for sensitive provider details
  - [x] Notes: Added `instructions/model_fallback_explanation_model.md` defining fallback trace shape, output levels, redaction policy, and deterministic reason-code requirements.
- [x] Task 12.2: Implement resolution tracing
  - [x] Subtask 12.2.1: Capture fallback chain attempts in runtime
  - [x] Subtask 12.2.2: Store latest trace per command/session
  - [x] Subtask 12.2.3: Expose trace to doctor and debug commands
  - [x] Notes: Extended `scripts/model_routing_schema.py` with requested/attempted/selected runtime trace payloads and added persisted latest-trace support plus `/model-routing trace` in `scripts/model_routing_command.py`.
- [x] Task 12.3: User-facing command surface
  - [x] Subtask 12.3.1: Add `/routing status` and `/routing explain` commands
  - [x] Subtask 12.3.2: Add examples for category-driven routing outcomes
  - [x] Subtask 12.3.3: Add docs for troubleshooting unexpected model selection
  - [x] Notes: Added `scripts/routing_command.py`, routed aliases in `opencode.json`, and README examples/troubleshooting for compact explainability workflows.
- [x] Task 12.4: Verification
  - [x] Subtask 12.4.1: Add tests for deterministic trace output
  - [x] Subtask 12.4.2: Add tests for fallback and no-fallback scenarios
  - [x] Subtask 12.4.3: Add install-test smoke checks
  - [x] Notes: Expanded `scripts/selftest.py` with deterministic resolution-trace assertions plus fallback/no-fallback routing explain scenarios and added `/routing` smoke hints in `install.sh`.
- [x] Exit criteria: users can explain model/provider selection for every routed task
- [x] Exit criteria: trace output remains readable in default mode

---

## Epic 13 - Browser Automation Profile Switching

**Status:** `done`
**Priority:** Medium
**Goal:** Add first-class profile switching between browser automation engines with install/runtime checks.
**Depends on:** Epic 1

- [x] Task 13.1: Define browser profile model
  - [x] Subtask 13.1.1: Define supported providers (`playwright`, `agent-browser`)
  - [x] Subtask 13.1.2: Define profile settings and defaults
  - [x] Subtask 13.1.3: Define migration behavior for existing installs
  - [x] Notes: Added `instructions/browser_profile_model.md` with provider schema, defaults, migration behavior, and validation contract.
- [x] Task 13.2: Implement profile command backend
  - [x] Subtask 13.2.1: Add `/browser profile <provider>` command
  - [x] Subtask 13.2.2: Add status and doctor checks for selected provider
  - [x] Subtask 13.2.3: Add install helper guidance for missing dependencies
  - [x] Notes: Added `scripts/browser_command.py`, `/browser*` aliases in `opencode.json`, doctor integration, and install/selftest smoke coverage for provider switching and dependency diagnostics.
- [x] Task 13.3: Integrate with wizard and docs
  - [x] Subtask 13.3.1: Add provider selection into install/reconfigure wizard
  - [x] Subtask 13.3.2: Document provider trade-offs and examples
  - [x] Subtask 13.3.3: Add recommended defaults for stable-first users
  - [x] Notes: Extended `scripts/install_wizard.py` with browser profile selection (`--browser-profile`) and updated README install/browser guidance with provider trade-offs plus stable-first recommendations.
- [x] Task 13.4: Verification
  - [x] Subtask 13.4.1: Add tests for profile switching and persistence
  - [x] Subtask 13.4.2: Add smoke tests for status/doctor across providers
  - [x] Subtask 13.4.3: Add install-test checks
  - [x] Notes: Expanded `scripts/selftest.py` to validate provider reset readiness and updated install smoke checks to run `status` and `doctor` across both providers.
- [x] Exit criteria: provider switching is one-command and reversible
- [x] Exit criteria: missing dependency states are diagnosed with exact fixes

---

## Epic 14 - Plan-to-Execution Bridge Command

**Status:** `done`
**Priority:** Medium
**Goal:** Add a command to execute from an approved plan artifact with progress tracking and deviation reporting.
**Depends on:** Epic 2, Epic 3

- [x] Task 14.1: Define plan artifact contract
  - [x] Subtask 14.1.1: Define accepted plan format (markdown checklist + metadata)
  - [x] Subtask 14.1.2: Define validation rules before execution starts
  - [x] Subtask 14.1.3: Define step state transitions and completion semantics
  - [x] Notes: Added `instructions/plan_artifact_contract.md` covering artifact schema, deterministic validation failures, transition rules, and deviation capture requirements for `/start-work`.
- [x] Task 14.2: Implement execution bridge backend
  - [x] Subtask 14.2.1: Add `/start-work <plan>` command implementation
  - [x] Subtask 14.2.2: Execute steps sequentially with checkpoint updates
  - [x] Subtask 14.2.3: Capture and report deviations from original plan
  - [x] Notes: Added `scripts/start_work_command.py` with plan parsing + validation, sequential checkpoint transitions, persisted execution status, and deviation reporting; wired aliases and smoke/selftest coverage.
- [x] Task 14.3: Integrations and observability
  - [x] Subtask 14.3.1: Integrate with background subsystem where safe
  - [x] Subtask 14.3.2: Integrate with digest summaries for end-of-run recap
  - [x] Subtask 14.3.3: Expose execution status in doctor/debug outputs
  - [x] Notes: Added background-safe `/start-work` queueing (`--background` + `/start-work-bg`), digest `plan_execution` recap output, and `/doctor` integration via `/start-work doctor --json`.
- [x] Task 14.4: Validation and docs
  - [x] Subtask 14.4.1: Add tests for plan parsing and execution flow
  - [x] Subtask 14.4.2: Add recovery tests for interrupted plan runs
  - [x] Subtask 14.4.3: Add docs with sample plans and workflows
  - [x] Notes: Expanded `scripts/selftest.py` with additional plan validation/recovery checks and added `instructions/plan_execution_workflows.md` with sample plans plus direct/background/recovery workflows.
- [x] Exit criteria: approved plans can be executed and resumed with clear state
- [x] Exit criteria: deviations are explicitly surfaced and reviewable

---

## Epic 15 - Todo Enforcer and Plan Compliance

**Status:** `done`
**Priority:** High
**Goal:** Enforce explicit checklist progress during execution so outcomes stay aligned with approved plans.
**Depends on:** Epic 14

- [x] Task 15.1: Define compliance model
  - [x] Subtask 15.1.1: Define required todo states (`pending`, `in_progress`, `done`, `skipped`)
  - [x] Subtask 15.1.2: Define rules for one-active-item-at-a-time enforcement
  - [x] Subtask 15.1.3: Define acceptable bypass annotations and audit format
  - [x] Notes: Added `instructions/todo_compliance_model.md` with state model, transition constraints, bypass metadata requirements, and audit event contract.
- [x] Task 15.2: Implement enforcement engine
  - [x] Subtask 15.2.1: Validate state transitions before major actions
  - [x] Subtask 15.2.2: Block completion when required tasks remain unchecked
  - [x] Subtask 15.2.3: Emit actionable remediation prompts on violations
  - [x] Notes: Added `scripts/todo_enforcement.py` and wired `/start-work` to enforce deterministic todo transitions, completion gating, and remediation/audit outputs in runtime state.
- [x] Task 15.3: Integrate command workflows
  - [x] Subtask 15.3.1: Integrate with plan execution command and background runs
  - [x] Subtask 15.3.2: Add `/todo status` and `/todo enforce` diagnostics
  - [x] Subtask 15.3.3: Add docs for compliant workflow patterns
  - [x] Notes: Added `scripts/todo_command.py`, command aliases, doctor integration, and README/install workflow guidance for explicit todo compliance checks.
- [x] Task 15.4: Verification
  - [x] Subtask 15.4.1: Add tests for transition validity and blocking behavior
  - [x] Subtask 15.4.2: Add tests for bypass annotations and logs
  - [x] Subtask 15.4.3: Add install-test smoke scenarios
  - [x] Notes: Expanded `scripts/selftest.py` and install smoke checks for transition gating, completion blocking, bypass metadata validation, and deterministic bypass audit payloads.
- [x] Exit criteria: plan completion cannot be marked done with unchecked required items
- [x] Exit criteria: bypass behavior is explicit, logged, and reviewable

---

## Epic 16 - Comment and Output Quality Checker Loop

**Status:** `merged`
**Priority:** Medium
**Goal:** Scope merged into Epic 23 to keep PR quality logic in one place.
**Merged into:** Epic 23

- [ ] Merged note: keep quality-check rules and output clarity checks under `/pr-review` instead of separate command.

---

## Epic 17 - Auto-Resume and Recovery Loop

**Status:** `in_progress`
**Priority:** High
**Goal:** Resume interrupted workflows from last valid checkpoint with explicit safety checks.
**Depends on:** Epic 11, Epic 14

- [x] Task 17.1: Define resume policy
  - [x] Subtask 17.1.1: Define interruption classes (tool failure, timeout, context reset, crash)
  - [x] Subtask 17.1.2: Define resume eligibility and cool-down rules
  - [x] Subtask 17.1.3: Define max resume attempts and escalation path
  - [x] Notes: Added `instructions/resume_policy_model.md` with interruption classes, deterministic eligibility/cool-down/attempt-limit rules, reason codes, and audit event contract.
- [x] Task 17.2: Implement recovery engine
  - [x] Subtask 17.2.1: Load last safe checkpoint and reconstruct state
  - [x] Subtask 17.2.2: Re-run only idempotent or explicitly approved steps
  - [x] Subtask 17.2.3: Persist resume trail for audit/debugging
  - [x] Notes: Added `scripts/recovery_engine.py` and `/start-work recover` backend path for checkpoint eligibility checks, approval-gated replay, and persisted resume audit trail events.
- [x] Task 17.3: User control surfaces
  - [x] Subtask 17.3.1: Add `/resume status`, `/resume now`, `/resume disable` commands
  - [x] Subtask 17.3.2: Add clear output explaining why resume did/did not trigger
  - [x] Subtask 17.3.3: Document recommended recovery playbooks
  - [x] Notes: Added `scripts/resume_command.py` and `/resume*` aliases with eligibility/status/disable controls, added human-readable recovery reasons via `explain_resume_reason`, and documented recovery playbooks in README.
- [ ] Task 17.4: Verification
  - [ ] Subtask 17.4.1: Add tests for each interruption class
  - [ ] Subtask 17.4.2: Add tests for idempotency safeguards
  - [ ] Subtask 17.4.3: Add install-test scenarios for interrupted flows
- [ ] Exit criteria: interrupted runs can be resumed safely with deterministic outcomes
- [ ] Exit criteria: recovery decisions are visible and auditable

---

## Epic 18 - LSP/AST-Assisted Safe Edit Mode

**Status:** `planned`
**Priority:** High
**Goal:** Prefer semantic edits via language tooling to reduce refactor regressions.
**Depends on:** Epic 3

- [ ] Task 18.1: Define safe-edit capability matrix
  - [ ] Subtask 18.1.1: Define supported operations (`rename`, `extract`, `organize imports`, scoped replace)
  - [ ] Subtask 18.1.2: Define language/tool availability checks
  - [ ] Subtask 18.1.3: Define text-mode fallback when semantic tooling is missing
- [ ] Task 18.2: Implement semantic edit adapters
  - [ ] Subtask 18.2.1: Add LSP adapter for symbol-aware operations
  - [ ] Subtask 18.2.2: Add AST adapter for deterministic structural edits
  - [ ] Subtask 18.2.3: Add diff validation for changed references
- [ ] Task 18.3: Command integration
  - [ ] Subtask 18.3.1: Add `/safe-edit` or mode flag integration with `/refactor-lite`
  - [ ] Subtask 18.3.2: Add status/doctor checks for available semantic tools
  - [ ] Subtask 18.3.3: Document safe-edit best practices and limitations
- [ ] Task 18.4: Verification
  - [ ] Subtask 18.4.1: Add cross-language tests for rename/reference correctness
  - [ ] Subtask 18.4.2: Add fallback tests when LSP/AST unavailable
  - [ ] Subtask 18.4.3: Add install-test smoke checks
- [ ] Exit criteria: semantic mode reduces accidental text-based regressions
- [ ] Exit criteria: fallback behavior is safe and clearly reported

---

## Epic 19 - Session Checkpoint Snapshots

**Status:** `planned`
**Priority:** Medium
**Goal:** Persist periodic snapshots of execution state to improve rollback, restart, and auditability.
**Depends on:** Epic 2, Epic 17

- [ ] Task 19.1: Define snapshot format and lifecycle
  - [ ] Subtask 19.1.1: Define snapshot schema (step state, context digest, command outcomes)
  - [ ] Subtask 19.1.2: Define frequency and trigger points (step boundary, error boundary, timer)
  - [ ] Subtask 19.1.3: Define retention, rotation, and optional compression
- [ ] Task 19.2: Implement snapshot manager
  - [ ] Subtask 19.2.1: Write atomic snapshots with corruption-safe semantics
  - [ ] Subtask 19.2.2: Add list/show/prune operations
  - [ ] Subtask 19.2.3: Integrate with resume/recovery engine
- [ ] Task 19.3: Visibility and tooling
  - [ ] Subtask 19.3.1: Add `/checkpoint list|show|prune` commands
  - [ ] Subtask 19.3.2: Add doctor diagnostics for snapshot health
  - [ ] Subtask 19.3.3: Document rollback/restart examples
- [ ] Task 19.4: Verification
  - [ ] Subtask 19.4.1: Add tests for atomic write and corruption handling
  - [ ] Subtask 19.4.2: Add retention/rotation tests
  - [ ] Subtask 19.4.3: Add install-test checkpoint smoke flows
- [ ] Exit criteria: checkpoints support reliable restart and recovery workflows
- [ ] Exit criteria: snapshot retention stays bounded by policy

---

## Epic 20 - Execution Budget Guardrails

**Status:** `planned`
**Priority:** High
**Goal:** Prevent runaway autonomous runs by enforcing configurable limits for time, tool calls, and token usage.
**Depends on:** Epic 2, Epic 11

- [ ] Task 20.1: Define budget model
  - [ ] Subtask 20.1.1: Define limit dimensions (wall-clock, tool-call count, token estimate)
  - [ ] Subtask 20.1.2: Define profiles (`conservative`, `balanced`, `extended`)
  - [ ] Subtask 20.1.3: Define override and emergency-stop semantics
- [ ] Task 20.2: Implement budget enforcement runtime
  - [ ] Subtask 20.2.1: Track usage counters in real time
  - [ ] Subtask 20.2.2: Block/soft-stop execution at threshold boundaries
  - [ ] Subtask 20.2.3: Emit summary and next-step recommendations on stop
- [ ] Task 20.3: Commands and diagnostics
  - [ ] Subtask 20.3.1: Add `/budget status|profile|override` commands
  - [ ] Subtask 20.3.2: Expose budget consumption in doctor/debug outputs
  - [ ] Subtask 20.3.3: Document budget tuning by workload type
- [ ] Task 20.4: Verification
  - [ ] Subtask 20.4.1: Add tests for threshold crossings and stop behavior
  - [ ] Subtask 20.4.2: Add tests for override and reset flows
  - [ ] Subtask 20.4.3: Add install-test smoke checks
- [ ] Exit criteria: runaway loops are prevented by hard and soft limits
- [ ] Exit criteria: budget stops provide actionable continuation guidance

---

## Epic 21 - Bounded Loop Mode Presets

**Status:** `merged`
**Priority:** Medium
**Goal:** Loop-control scope merged into Epic 22 and Epic 28.
**Merged into:** Epic 22, Epic 28

- [ ] Merged note: expose loop controls as `/autoflow` and `/autopilot` options, not a separate top-level epic.

---

## Epic 22 - Autoflow Unified Orchestration Command

**Status:** `planned`
**Priority:** High
**Goal:** Provide a single command (`/autoflow`) that orchestrates plan execution, enforcement, recovery, and reporting with safe defaults.
**Depends on:** Epic 14, Epic 15, Epic 17, Epic 19, Epic 20

- [ ] Task 22.1: Define `/autoflow` command contract
  - [ ] Subtask 22.1.1: Define subcommands (`start`, `status`, `resume`, `stop`, `report`, `dry-run`)
  - [ ] Subtask 22.1.2: Define input plan requirements and validation errors
  - [ ] Subtask 22.1.3: Define output format for concise and verbose modes
- [ ] Task 22.2: Implement orchestration adapter layer
  - [ ] Subtask 22.2.1: Compose existing plan, todo, budget, checkpoint, and loop primitives
  - [ ] Subtask 22.2.2: Add deterministic state machine transitions
  - [ ] Subtask 22.2.3: Add explain mode showing decisions and fallbacks
- [ ] Task 22.3: Add safety and usability controls
  - [ ] Subtask 22.3.1: Add `dry-run` to preview actions without mutating state
  - [ ] Subtask 22.3.2: Add explicit kill-switch behavior for unsafe or runaway states
  - [ ] Subtask 22.3.3: Add docs and migration guidance from low-level commands
- [ ] Task 22.4: Verification
  - [ ] Subtask 22.4.1: Add integration tests for full lifecycle (`start -> status -> report`)
  - [ ] Subtask 22.4.2: Add recovery tests (`resume` after interruption)
  - [ ] Subtask 22.4.3: Add install-test smoke checks for `/autoflow` happy path
- [ ] Exit criteria: `/autoflow` can run end-to-end flows with auditable outputs
- [ ] Exit criteria: users can always fall back to lower-level commands safely

---

## Epic 23 - PR Review Copilot

**Status:** `planned`
**Priority:** High
**Goal:** Add a command that reviews pending PR changes for risk, quality, and release readiness before merge.
**Depends on:** Epic 3

- [ ] Task 23.1: Define review rubric and risk scoring
  - [ ] Subtask 23.1.1: Define risk categories (security, data loss, migration impact, test coverage)
  - [ ] Subtask 23.1.2: Define confidence and severity scoring model
  - [ ] Subtask 23.1.3: Define required evidence for blocking recommendations
- [ ] Task 23.2: Implement copilot analyzer
  - [ ] Subtask 23.2.1: Parse git diff and classify changed areas
  - [ ] Subtask 23.2.2: Detect missing tests/docs/changelog implications
  - [ ] Subtask 23.2.3: Produce actionable findings with file-level references
- [ ] Task 23.3: Command surface and workflow integration
  - [ ] Subtask 23.3.1: Add `/pr-review` with concise and JSON modes
  - [ ] Subtask 23.3.2: Integrate with pre-merge checklist and doctor output
  - [ ] Subtask 23.3.3: Document triage flow for warnings vs blockers
- [ ] Task 23.4: Verification
  - [ ] Subtask 23.4.1: Add tests for risk detection and false positive control
  - [ ] Subtask 23.4.2: Add tests for missing-evidence behavior
  - [ ] Subtask 23.4.3: Add install-test smoke checks
- [ ] Exit criteria: copilot catches high-risk omissions before merge
- [ ] Exit criteria: outputs are actionable and low-noise in default mode

---

## Epic 24 - Release Train Assistant

**Status:** `planned`
**Priority:** High
**Goal:** Automate release preparation checks, release-note drafting, and tag gating.
**Depends on:** Epic 14, Epic 23

- [ ] Task 24.1: Define release policy contract
  - [ ] Subtask 24.1.1: Define required preconditions (clean tree, tests passing, changelog updated)
  - [ ] Subtask 24.1.2: Define semantic version rules and validation
  - [ ] Subtask 24.1.3: Define rollback strategy for partial release failures
- [ ] Task 24.2: Implement release assistant engine
  - [ ] Subtask 24.2.1: Add preflight checks and blocking diagnostics
  - [ ] Subtask 24.2.2: Generate draft release notes from merged changes
  - [ ] Subtask 24.2.3: Add dry-run publish flow with explicit confirmation step
- [ ] Task 24.3: Command integration
  - [ ] Subtask 24.3.1: Add `/release-train status|prepare|draft|publish`
  - [ ] Subtask 24.3.2: Integrate with existing `make release-check` and changelog flow
  - [ ] Subtask 24.3.3: Document release operator workflow
- [ ] Task 24.4: Verification
  - [ ] Subtask 24.4.1: Add tests for version and changelog mismatch handling
  - [ ] Subtask 24.4.2: Add tests for dry-run vs publish behavior
  - [ ] Subtask 24.4.3: Add install-test smoke checks
- [ ] Exit criteria: releases are blocked when preconditions are unmet
- [ ] Exit criteria: release-note drafts are generated consistently and reviewable

---

## Epic 25 - Incident Hotfix Mode

**Status:** `planned`
**Priority:** Medium
**Goal:** Provide an emergency workflow mode that is faster but still bounded and auditable.
**Depends on:** Epic 20, Epic 22

- [ ] Task 25.1: Define hotfix constraints and policy
  - [ ] Subtask 25.1.1: Define mandatory checks that cannot be skipped
  - [ ] Subtask 25.1.2: Define reduced-scope validation profile
  - [ ] Subtask 25.1.3: Define post-hotfix follow-up requirements
- [ ] Task 25.2: Implement hotfix runtime profile
  - [ ] Subtask 25.2.1: Add constrained budget and tool permission settings
  - [ ] Subtask 25.2.2: Add expedited patch flow with rollback checkpoint
  - [ ] Subtask 25.2.3: Add incident timeline capture for auditability
- [ ] Task 25.3: Command integration and docs
  - [ ] Subtask 25.3.1: Add `/hotfix start|status|close`
  - [ ] Subtask 25.3.2: Add automatic reminder for post-incident hardening tasks
  - [ ] Subtask 25.3.3: Document incident playbooks and escalation notes
- [ ] Task 25.4: Verification
  - [ ] Subtask 25.4.1: Add tests for mandatory guardrail enforcement
  - [ ] Subtask 25.4.2: Add tests for rollback and closure flow
  - [ ] Subtask 25.4.3: Add install-test smoke checks
- [ ] Exit criteria: hotfix mode is faster while preserving mandatory safety controls
- [ ] Exit criteria: each hotfix run produces a clear post-incident audit trail

---

## Epic 26 - Repo Health Score and Drift Monitor

**Status:** `planned`
**Priority:** Medium
**Goal:** Aggregate repository operational signals into a health score with drift alerts.
**Depends on:** Epic 9, Epic 12, Epic 20

- [ ] Task 26.1: Define health model and scoring weights
  - [ ] Subtask 26.1.1: Define high-signal indicators (tests, hooks, stale branches, config drift)
  - [ ] Subtask 26.1.2: Define weighted scoring and status thresholds
  - [ ] Subtask 26.1.3: Define suppression window for repeated alerts
- [ ] Task 26.2: Implement health collector
  - [ ] Subtask 26.2.1: Collect diagnostics from existing command subsystems
  - [ ] Subtask 26.2.2: Detect drift from expected profile/policy baselines
  - [ ] Subtask 26.2.3: Persist score history and trend snapshots
- [ ] Task 26.3: Command and reporting integration
  - [ ] Subtask 26.3.1: Add `/health status|trend|drift`
  - [ ] Subtask 26.3.2: Add JSON export for dashboards/CI
  - [ ] Subtask 26.3.3: Document remediation recommendations by score bucket
- [ ] Task 26.4: Verification
  - [ ] Subtask 26.4.1: Add tests for score determinism and threshold behavior
  - [ ] Subtask 26.4.2: Add tests for drift detection precision
  - [ ] Subtask 26.4.3: Add install-test smoke checks
- [ ] Exit criteria: health score reflects real operational risk with actionable guidance
- [ ] Exit criteria: drift signals are precise enough to avoid alert fatigue

---

## Epic 27 - Knowledge Capture from Completed Tasks

**Status:** `planned`
**Priority:** Medium
**Goal:** Turn completed work into reusable patterns, checklists, and guidance for future runs.
**Depends on:** Epic 9, Epic 14, Epic 23

- [ ] Task 27.1: Define capture schema and quality gates
  - [ ] Subtask 27.1.1: Define entry types (pattern, pitfall, checklist, rule candidate)
  - [ ] Subtask 27.1.2: Define confidence score and approval workflow
  - [ ] Subtask 27.1.3: Define tagging and search metadata
- [ ] Task 27.2: Implement knowledge extraction pipeline
  - [ ] Subtask 27.2.1: Extract signals from merged PRs and task digests
  - [ ] Subtask 27.2.2: Generate draft entries with source links
  - [ ] Subtask 27.2.3: Support review/edit/publish lifecycle
- [ ] Task 27.3: Command and integration surface
  - [ ] Subtask 27.3.1: Add `/learn capture|review|publish|search`
  - [ ] Subtask 27.3.2: Integrate published patterns with rules injector and `/autoflow` workflow docs
  - [ ] Subtask 27.3.3: Document maintenance process for stale entries
- [ ] Task 27.4: Verification
  - [ ] Subtask 27.4.1: Add tests for extraction quality thresholds
  - [ ] Subtask 27.4.2: Add tests for approval/publish permissions
  - [ ] Subtask 27.4.3: Add install-test smoke checks
- [ ] Exit criteria: completed work reliably yields reusable, reviewed guidance
- [ ] Exit criteria: stale/low-confidence knowledge can be pruned safely

---

## Epic 28 - Autopilot Objective Runner Command

**Status:** `planned`
**Priority:** High
**Goal:** Add `/autopilot` as a high-level objective runner that executes bounded autonomous cycles with explicit controls.
**Depends on:** Epic 20, Epic 22

- [ ] Task 28.1: Define command contract and safety defaults
  - [ ] Subtask 28.1.1: Define subcommands (`start`, `status`, `pause`, `resume`, `stop`, `report`)
  - [ ] Subtask 28.1.2: Define required objective fields (`goal`, `scope`, `done-criteria`, `max-budget`)
  - [ ] Subtask 28.1.3: Define safe default behavior (`dry-run` preview before first execution)
- [ ] Task 28.2: Implement objective orchestration loop
  - [ ] Subtask 28.2.1: Break objective into bounded execution cycles
  - [ ] Subtask 28.2.2: Apply budget guardrails and mandatory checkpoints per cycle
  - [ ] Subtask 28.2.3: Emit progress, blockers, and next-step recommendations
- [ ] Task 28.3: Integrate with existing control subsystems
  - [ ] Subtask 28.3.1: Reuse `/autoflow` primitives for plan and state transitions
  - [ ] Subtask 28.3.2: Integrate with todo enforcement and resume/checkpoint systems
  - [ ] Subtask 28.3.3: Add explicit manual handoff mode when confidence drops
- [ ] Task 28.4: Command UX, docs, and workflows
  - [ ] Subtask 28.4.1: Add `/autopilot` examples in `README.md`
  - [ ] Subtask 28.4.2: Add workflow guides (quick-fix objective, feature objective, release objective)
  - [ ] Subtask 28.4.3: Add troubleshooting guide for stopped/paused runs
- [ ] Task 28.5: Verification
  - [ ] Subtask 28.5.1: Add tests for scope bounding and budget cap enforcement
  - [ ] Subtask 28.5.2: Add tests for pause/resume/stop transitions
  - [ ] Subtask 28.5.3: Add install-test smoke scenarios for objective lifecycle
- [ ] Exit criteria: `/autopilot` never exceeds declared objective scope and budget limits
- [ ] Exit criteria: users can inspect and control every run stage with clear status output

---

## Cross-Cutting Delivery Tasks

**Status:** `planned`

- [ ] Task C1: Add release slicing plan by phase
  - [ ] Subtask C1.1: Phase A (low-risk foundation): Epic 1
  - [ ] Subtask C1.2: Phase B (workflow power): Epic 2 + Epic 3
  - [ ] Subtask C1.3: Phase C (advanced automation): Epic 4 + Epic 5
  - [ ] Subtask C1.4: Phase D (control layer): Epic 8 + Epic 9 + Epic 10
  - [ ] Subtask C1.5: Phase E (resilience and observability): Epic 11 + Epic 12
  - [ ] Subtask C1.6: Phase F (workflow expansion): Epic 13 + Epic 14
  - [ ] Subtask C1.7: Phase G (quality and control): Epic 15 + Epic 23
  - [ ] Subtask C1.8: Phase H (recovery and semantic safety): Epic 17 + Epic 18 + Epic 19
  - [ ] Subtask C1.9: Phase I (bounded autonomy): Epic 20 + Epic 22
  - [ ] Subtask C1.10: Phase J (unified orchestration): Epic 22
  - [ ] Subtask C1.11: Phase K (delivery acceleration): Epic 23 + Epic 24 + Epic 25
  - [ ] Subtask C1.12: Phase L (operational intelligence): Epic 26 + Epic 27
  - [ ] Subtask C1.13: Phase M (objective autonomy): Epic 28
  - [ ] Subtask C1.14: Phase N (optional power-user): Epic 6 + Epic 7
- [ ] Task C2: Add acceptance criteria template per epic
  - [ ] Subtask C2.1: Functional criteria
  - [ ] Subtask C2.2: Reliability criteria
  - [ ] Subtask C2.3: Documentation criteria
  - [ ] Subtask C2.4: Validation criteria (`make validate`, `make selftest`, `make install-test`)
  - [ ] Subtask C2.5: Evidence links (PR, commit, test output summary)
  - [ ] Subtask C2.6: Docs quality criteria (`README` updates + command examples + end-to-end workflow guides)
  - [ ] Subtask C2.7: Measurable thresholds (0 failing checks, explicit risk notes, clear rollback path)
- [ ] Task C3: Add tracking cadence
  - [ ] Subtask C3.1: Weekly status update section in this file
  - [ ] Subtask C3.2: Keep one epic `in_progress`
  - [ ] Subtask C3.3: Move deferred work to `postponed` explicitly
  - [ ] Subtask C3.4: Revisit paused/postponed epics at least once per month
- [ ] Task C4: Command UX baseline (quality-of-life required)
  - [ ] Subtask C4.1: Add command autocomplete shortcuts in `opencode.json`
  - [ ] Subtask C4.2: Add command help and doctor JSON outputs
  - [ ] Subtask C4.3: Add code-assistant guidance snippets (inputs, expected outputs, safe defaults)
  - [ ] Subtask C4.4: Add tips/troubleshooting output for common failures
  - [ ] Subtask C4.5: Add hover-like inline explanation docs (what it does, when to use, limits)
  - [ ] Subtask C4.6: Add at least one easy-path command alias for frequent workflows

## Roadmap QA Checklist

Run this checklist for every roadmap refinement pass:

- [ ] No duplicate command ownership across epics.
- [ ] No ambiguous command names (`or equivalent`, placeholder aliases).
- [ ] Dependencies are acyclic and point to existing epics only.
- [ ] Each high-priority epic has explicit safety and rollback notes.
- [ ] Docs requirements are present (`README`, examples, workflow guide).
- [ ] Low-value or high-noise epics are paused/postponed unless a measurable gap exists.

## Weekly Status Updates

Use this log to track what changed week by week.

- [ ] YYYY-MM-DD: update epic statuses, completed checkboxes, and next focus epic

## Execution Queue (Simplified)

- `Now`: E1 -> E2 -> E3 -> E20
- `Next`: E14 -> E15 -> E22
- `Later`: E23 -> E24 -> E26 -> E27
- `Deferred`: E6 (paused), E7 (postponed), E10 (paused), E28 (paused), E16/E21 (merged)

## Decision Log

- [x] 2026-02-12: Adopt stable-first sequencing; prioritize E1 before orchestration-heavy epics.
- [x] 2026-02-12: Keep E6 paused until E1-E5 foundations stabilize.
- [x] 2026-02-12: Keep E7 postponed pending stronger demand for tmux visual mode.
- [x] 2026-02-12: Add E8-E14 as high-value extensions identified from comparative analysis.
- [x] 2026-02-12: Add E15-E21 for enforcement, quality, recovery, semantic editing, checkpointing, budgets, and bounded loops.
- [x] 2026-02-12: Add E22-E27 to unify orchestration and accelerate delivery quality and release reliability.
- [x] 2026-02-13: Add E28 `/autopilot` as a non-duplicated high-value command on top of `/autoflow`.
- [x] 2026-02-13: Pause/postpone lower-confidence epics (E10, E28) until measurable value is proven.
- [x] 2026-02-13: Merge duplicate epic scopes E16 -> E23 and E21 -> E22/E28.
- [x] 2026-02-13: Require command UX baseline (autocomplete, assistant tips, hovers/explanations, QoL aliases) for all new command features.

---

## Current Recommendation

- Start with **Epic 1** next (lowest risk, highest leverage).
- Prioritize **E8-E9** after E1-E5 for fast workflow gains.
- Prioritize **E11-E12** before E13-E14 when stability concerns are high.
- Prioritize **E15 + E20** before E22 to keep autonomy controlled and auditable.
- Prioritize **E22** before E23-E27 so higher-level automation builds on stable primitives.
- Keep **E28** paused until E22 proves stable in production-like workflows.
- Keep **E10** paused unless explicit user-value metrics justify implementation.
- Keep **Epic 6** paused and **Epic 7** postponed until core and control epics stabilize.
