# My OpenCode Implementation Roadmap

This roadmap tracks phased delivery of advanced orchestration features inspired by gaps identified versus `oh-my-opencode`.

## How to use this file

- Task completion: use `[ ]` and `[x]`.
- Epic status values: `planned`, `in_progress`, `paused`, `done`, `postponed`.
- Recommendation: move only one epic to `in_progress` at a time.

## Status Playbook

- `planned`: scoped and ready, not started.
- `in_progress`: actively being implemented now.
- `paused`: started but intentionally stopped; can resume any time.
- `postponed`: intentionally deferred; not expected this cycle.
- `done`: fully implemented, documented, and validated.

## Epic Dashboard

| Epic | Title | Status | Priority | Depends On | br Issue | Notes |
|---|---|---|---|---|---|---|
| E1 | Config Layering + JSONC Support | planned | High | - | TBD | Foundation for most later epics |
| E2 | Background Task Orchestration | planned | High | E1 | TBD | Keep minimal and stable first |
| E3 | Refactor Workflow Command | planned | High | E1 | TBD | Safer rollout after config layering |
| E4 | Continuation and Safety Hooks | planned | Medium | E1, E2 | TBD | Start with minimal hooks only |
| E5 | Category-Based Model Routing | planned | Medium | E1 | TBD | Can partially overlap with E2/E3 |
| E6 | Session Intelligence and Resume Tooling | paused | Medium | E2 | TBD | Resume when core orchestration stabilizes |
| E7 | Tmux Visual Multi-Agent Mode | postponed | Low | E2 | TBD | Optional power-user feature |
| E8 | Keyword-Triggered Execution Modes | planned | High | E1, E4 | TBD | Fast power-mode activation from prompt text |
| E9 | Conditional Rules Injector | planned | High | E1 | TBD | Enforce project conventions with scoped rules |
| E10 | Auto Slash Command Detector | planned | Medium | E1, E8 | TBD | Convert natural prompts to command workflows |
| E11 | Context-Window Resilience Toolkit | planned | High | E4 | TBD | Improve long-session stability and recovery |
| E12 | Provider/Model Fallback Visibility | planned | Medium | E5 | TBD | Explain why model routing decisions happen |
| E13 | Browser Automation Profile Switching | planned | Medium | E1 | TBD | Toggle Playwright/agent-browser with checks |
| E14 | Plan-to-Execution Bridge Command | planned | Medium | E2, E3 | TBD | Execute validated plans with progress tracking |

## Scope Guardrails

- Keep migration **stable-first**: ship low-risk foundations before advanced orchestration.
- Prefer additive changes and compatibility fallbacks over breaking behavior.
- Do not expand to unrelated feature areas during in-progress epics.

## Out of Scope (for this roadmap cycle)

- Full rewrite of existing command scripts in a new language/runtime.
- Broad UI redesign of docs/install flows unrelated to orchestration objectives.
- Large provider/model benchmarking initiatives beyond routing correctness.

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

---

## Epic 1 - Config Layering + JSONC Support

**Status:** `planned`
**Priority:** High
**Goal:** Add user/project layered config and JSONC parsing so behavior can be customized per repo without mutating global defaults.
**Depends on:** None

- [ ] Task 1.1: Define configuration precedence and file discovery
  - [ ] Subtask 1.1.1: Document precedence order (`project` > `user` > bundled defaults)
  - [ ] Subtask 1.1.2: Define file paths (`.opencode/my_opencode.jsonc`, `.opencode/my_opencode.json`, `~/.config/opencode/my_opencode.jsonc`, `~/.config/opencode/my_opencode.json`)
  - [ ] Subtask 1.1.3: Define merge semantics (object merge, array replacement, explicit overrides)
- [ ] Task 1.2: Implement config loader module
  - [ ] Subtask 1.2.1: Create parser supporting JSON and JSONC
  - [ ] Subtask 1.2.2: Implement precedence-based merge and validation
  - [ ] Subtask 1.2.3: Add schema validation and actionable error messages
- [ ] Task 1.3: Integrate layered config into command scripts
  - [ ] Subtask 1.3.1: Wire loader into `mcp/plugin/notify/telemetry/post-session/policy/stack/nvim/devtools` flows
  - [ ] Subtask 1.3.2: Keep existing env var overrides as highest-priority runtime override
  - [ ] Subtask 1.3.3: Add compatibility fallback when only legacy files exist
- [ ] Task 1.4: Documentation and tests
  - [ ] Subtask 1.4.1: Add docs with examples for user/project overrides
  - [ ] Subtask 1.4.2: Add selftests for precedence and JSONC behavior
  - [ ] Subtask 1.4.3: Add install-test coverage for layered config discovery
- [ ] Exit criteria: all command scripts resolve config through shared layered loader
- [ ] Exit criteria: precedence + JSONC behavior covered by tests and docs

---

## Epic 2 - Background Task Orchestration (Minimal Safe Version)

**Status:** `planned`
**Priority:** High
**Goal:** Add lightweight background job workflows for async research and result retrieval.
**Depends on:** Epic 1

- [ ] Task 2.1: Design minimal background task model
  - [ ] Subtask 2.1.1: Define job lifecycle (`queued`, `running`, `completed`, `failed`, `cancelled`)
  - [ ] Subtask 2.1.2: Define persistent state file format and retention policy
  - [ ] Subtask 2.1.3: Define maximum concurrency and stale-timeout defaults
- [ ] Task 2.2: Implement background task manager script
  - [ ] Subtask 2.2.1: Add enqueue/run/read/list/cancel operations
  - [ ] Subtask 2.2.2: Capture stdout/stderr and execution metadata
  - [ ] Subtask 2.2.3: Add stale job detection and cleanup
- [ ] Task 2.3: Expose OpenCode commands
  - [ ] Subtask 2.3.1: Add `/bg` command family (`start|status|list|read|cancel`)
  - [ ] Subtask 2.3.2: Add autocomplete shortcuts for high-frequency operations
  - [ ] Subtask 2.3.3: Integrate with `/doctor` summary checks
- [ ] Task 2.4: Notifications and diagnostics
  - [ ] Subtask 2.4.1: Add optional completion notification via existing notify stack
  - [ ] Subtask 2.4.2: Add JSON diagnostics output for background subsystem
  - [ ] Subtask 2.4.3: Add docs and examples for async workflows
- [ ] Exit criteria: background workflows are deterministic, inspectable, and cancel-safe
- [ ] Exit criteria: doctor + docs cover baseline troubleshooting

---

## Epic 3 - Refactor Workflow Command (`/refactor-lite`)

**Status:** `planned`
**Priority:** High
**Goal:** Add a safe, repeatable refactor workflow command using existing tools and verification gates.
**Depends on:** Epic 1

- [ ] Task 3.1: Define command contract
  - [ ] Subtask 3.1.1: Define syntax (`/refactor-lite <target> [--scope] [--strategy]`)
  - [ ] Subtask 3.1.2: Define safe defaults and guardrails (`safe` by default)
  - [ ] Subtask 3.1.3: Define success/failure output shape
- [ ] Task 3.2: Implement workflow backend
  - [ ] Subtask 3.2.1: Add preflight analysis step (grep + file map)
  - [ ] Subtask 3.2.2: Add structured plan preview output
  - [ ] Subtask 3.2.3: Add post-change verification hooks (`make validate`, optional `make selftest`)
- [ ] Task 3.3: OpenCode integration
  - [ ] Subtask 3.3.1: Add `/refactor-lite` and helper commands to `opencode.json`
  - [ ] Subtask 3.3.2: Add installer self-check hints
  - [ ] Subtask 3.3.3: Add `/doctor` optional check when command is configured
- [ ] Task 3.4: Tests and docs
  - [ ] Subtask 3.4.1: Add selftest scenarios for argument parsing and safe-mode behavior
  - [ ] Subtask 3.4.2: Add docs for safe vs aggressive strategies
  - [ ] Subtask 3.4.3: Add install-test smoke checks
- [ ] Exit criteria: safe mode is default and validates before completion
- [ ] Exit criteria: failure output gives actionable remediation

---

## Epic 4 - Continuation and Safety Hooks (Targeted)

**Status:** `planned`
**Priority:** Medium
**Goal:** Add minimal lifecycle automation hooks for continuation and resilience without introducing heavy complexity.
**Depends on:** Epic 1, Epic 2

- [ ] Task 4.1: Hook framework baseline
  - [ ] Subtask 4.1.1: Define hook events (`PreToolUse`, `PostToolUse`, `Stop`) for our scope
  - [ ] Subtask 4.1.2: Define hook config and disable list
  - [ ] Subtask 4.1.3: Implement deterministic execution order
- [ ] Task 4.2: Initial hooks
  - [ ] Subtask 4.2.1: Add continuation reminder hook for unfinished explicit checklists
  - [ ] Subtask 4.2.2: Add output truncation safety hook for large tool outputs
  - [ ] Subtask 4.2.3: Add basic error recovery hint hook for common command failures
- [ ] Task 4.3: Governance and controls
  - [ ] Subtask 4.3.1: Add opt-out per hook via config
  - [ ] Subtask 4.3.2: Add telemetry-safe logging for hook actions
  - [ ] Subtask 4.3.3: Add docs for enabling/disabling hooks
- [ ] Task 4.4: Verification
  - [ ] Subtask 4.4.1: Add selftests for hook order and disable behavior
  - [ ] Subtask 4.4.2: Add install-test smoke checks
  - [ ] Subtask 4.4.3: Add doctor check summary for hook health
- [ ] Exit criteria: hooks are optional, predictable, and low-noise by default
- [ ] Exit criteria: disabling individual hooks is tested and documented

---

## Epic 5 - Category-Based Model Routing

**Status:** `planned`
**Priority:** Medium
**Goal:** Introduce category presets (quick/deep/visual/writing) for better cost/performance model routing.
**Depends on:** Epic 1

- [ ] Task 5.1: Define category schema
  - [ ] Subtask 5.1.1: Define baseline categories and descriptions
  - [ ] Subtask 5.1.2: Define category settings (`model`, `temperature`, `reasoning`, `verbosity`)
  - [ ] Subtask 5.1.3: Define fallback behavior when model is unavailable
- [ ] Task 5.2: Implement resolution engine
  - [ ] Subtask 5.2.1: Resolve from user override -> category default -> system default
  - [ ] Subtask 5.2.2: Add deterministic fallback logging for diagnostics
  - [ ] Subtask 5.2.3: Add integration points with `/stack` and wizard profiles
- [ ] Task 5.3: UX and docs
  - [ ] Subtask 5.3.1: Add `/model-profile` (or equivalent) command surface
  - [ ] Subtask 5.3.2: Document practical routing examples by workload
  - [ ] Subtask 5.3.3: Add doctor visibility for effective routing
- [ ] Task 5.4: Verification
  - [ ] Subtask 5.4.1: Add tests for precedence and fallback
  - [ ] Subtask 5.4.2: Add tests for stack integration
  - [ ] Subtask 5.4.3: Add install-test checks
- [ ] Exit criteria: effective model resolution is visible and explainable
- [ ] Exit criteria: fallback behavior is deterministic and tested

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

**Status:** `planned`
**Priority:** High
**Goal:** Enable explicit keywords (for example, `ulw`) to activate high-value execution modes without manual command chaining.
**Depends on:** Epic 1, Epic 4

- [ ] Task 8.1: Define keyword dictionary and behavior mapping
  - [ ] Subtask 8.1.1: Define reserved keywords (`ulw`, `deep-analyze`, `parallel-research`, `safe-apply`)
  - [ ] Subtask 8.1.2: Define mode side-effects and precedence rules
  - [ ] Subtask 8.1.3: Define explicit opt-out syntax and defaults
- [ ] Task 8.2: Implement keyword detector engine
  - [ ] Subtask 8.2.1: Parse user prompts and resolve keyword intents
  - [ ] Subtask 8.2.2: Apply mode flags to runtime execution context
  - [ ] Subtask 8.2.3: Add conflict handling when multiple keywords appear
- [ ] Task 8.3: User visibility and control
  - [ ] Subtask 8.3.1: Add status command for active mode stack
  - [ ] Subtask 8.3.2: Add config toggles to disable selected keywords
  - [ ] Subtask 8.3.3: Document examples and anti-patterns
- [ ] Task 8.4: Verification
  - [ ] Subtask 8.4.1: Add tests for matching accuracy and false positives
  - [ ] Subtask 8.4.2: Add install-test smoke scenarios for keyword activation
  - [ ] Subtask 8.4.3: Add doctor visibility for keyword subsystem
- [ ] Exit criteria: keyword activation is deterministic and low-surprise
- [ ] Exit criteria: users can disable or override keyword behavior safely

---

## Epic 9 - Conditional Rules Injector

**Status:** `planned`
**Priority:** High
**Goal:** Load project/user rule files with optional glob conditions to enforce coding conventions contextually.
**Depends on:** Epic 1

- [ ] Task 9.1: Define rule file schema and precedence
  - [ ] Subtask 9.1.1: Define frontmatter fields (`globs`, `alwaysApply`, `description`, `priority`)
  - [ ] Subtask 9.1.2: Define project/user rule search paths
  - [ ] Subtask 9.1.3: Define rule conflict resolution strategy
- [ ] Task 9.2: Implement rule discovery and matching engine
  - [ ] Subtask 9.2.1: Discover markdown rule files recursively
  - [ ] Subtask 9.2.2: Match rules by file path and operation context
  - [ ] Subtask 9.2.3: Inject effective rule set into execution context
- [ ] Task 9.3: Operations and diagnostics
  - [ ] Subtask 9.3.1: Add `/rules status` and `/rules explain <path>` commands
  - [ ] Subtask 9.3.2: Add per-rule disable list in config
  - [ ] Subtask 9.3.3: Add doctor output for rule source and conflicts
- [ ] Task 9.4: Verification and docs
  - [ ] Subtask 9.4.1: Add tests for glob matching and precedence
  - [ ] Subtask 9.4.2: Add docs with examples for team rule packs
  - [ ] Subtask 9.4.3: Add install-test smoke checks
- [ ] Exit criteria: applicable rules are explainable for any target file
- [ ] Exit criteria: conflicting rules are surfaced with clear remediation

---

## Epic 10 - Auto Slash Command Detector

**Status:** `planned`
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

**Status:** `planned`
**Priority:** High
**Goal:** Improve long-session reliability with configurable truncation/pruning/recovery policies.
**Depends on:** Epic 4

- [ ] Task 11.1: Define resilience policy schema
  - [ ] Subtask 11.1.1: Define truncation modes (`default`, `aggressive`)
  - [ ] Subtask 11.1.2: Define protected tools/messages list
  - [ ] Subtask 11.1.3: Define pruning and recovery notification levels
- [ ] Task 11.2: Implement context pruning engine
  - [ ] Subtask 11.2.1: Add deduplication and superseded-write pruning
  - [ ] Subtask 11.2.2: Add old-error input purge with turn thresholds
  - [ ] Subtask 11.2.3: Preserve critical evidence and command outcomes
- [ ] Task 11.3: Recovery workflows
  - [ ] Subtask 11.3.1: Add automatic resume hints after successful recovery
  - [ ] Subtask 11.3.2: Add safe fallback when recovery cannot proceed
  - [ ] Subtask 11.3.3: Add diagnostics for pruning/recovery actions
- [ ] Task 11.4: Validation and docs
  - [ ] Subtask 11.4.1: Add stress tests for long-session behavior
  - [ ] Subtask 11.4.2: Add docs for tuning resilience settings
  - [ ] Subtask 11.4.3: Add doctor summary for context resilience health
- [ ] Exit criteria: long sessions remain stable under constrained context budgets
- [ ] Exit criteria: recovery decisions are transparent and auditable

---

## Epic 12 - Provider/Model Fallback Visibility

**Status:** `planned`
**Priority:** Medium
**Goal:** Make model routing and provider fallback decisions observable and explainable.
**Depends on:** Epic 5

- [ ] Task 12.1: Define explanation model
  - [ ] Subtask 12.1.1: Define resolution trace format (requested -> attempted -> selected)
  - [ ] Subtask 12.1.2: Define compact vs verbose output levels
  - [ ] Subtask 12.1.3: Define redaction rules for sensitive provider details
- [ ] Task 12.2: Implement resolution tracing
  - [ ] Subtask 12.2.1: Capture fallback chain attempts in runtime
  - [ ] Subtask 12.2.2: Store latest trace per command/session
  - [ ] Subtask 12.2.3: Expose trace to doctor and debug commands
- [ ] Task 12.3: User-facing command surface
  - [ ] Subtask 12.3.1: Add `/routing status` and `/routing explain` commands
  - [ ] Subtask 12.3.2: Add examples for category-driven routing outcomes
  - [ ] Subtask 12.3.3: Add docs for troubleshooting unexpected model selection
- [ ] Task 12.4: Verification
  - [ ] Subtask 12.4.1: Add tests for deterministic trace output
  - [ ] Subtask 12.4.2: Add tests for fallback and no-fallback scenarios
  - [ ] Subtask 12.4.3: Add install-test smoke checks
- [ ] Exit criteria: users can explain model/provider selection for every routed task
- [ ] Exit criteria: trace output remains readable in default mode

---

## Epic 13 - Browser Automation Profile Switching

**Status:** `planned`
**Priority:** Medium
**Goal:** Add first-class profile switching between browser automation engines with install/runtime checks.
**Depends on:** Epic 1

- [ ] Task 13.1: Define browser profile model
  - [ ] Subtask 13.1.1: Define supported providers (`playwright`, `agent-browser`)
  - [ ] Subtask 13.1.2: Define profile settings and defaults
  - [ ] Subtask 13.1.3: Define migration behavior for existing installs
- [ ] Task 13.2: Implement profile command backend
  - [ ] Subtask 13.2.1: Add `/browser profile <provider>` command
  - [ ] Subtask 13.2.2: Add status and doctor checks for selected provider
  - [ ] Subtask 13.2.3: Add install helper guidance for missing dependencies
- [ ] Task 13.3: Integrate with wizard and docs
  - [ ] Subtask 13.3.1: Add provider selection into install/reconfigure wizard
  - [ ] Subtask 13.3.2: Document provider trade-offs and examples
  - [ ] Subtask 13.3.3: Add recommended defaults for stable-first users
- [ ] Task 13.4: Verification
  - [ ] Subtask 13.4.1: Add tests for profile switching and persistence
  - [ ] Subtask 13.4.2: Add smoke tests for status/doctor across providers
  - [ ] Subtask 13.4.3: Add install-test checks
- [ ] Exit criteria: provider switching is one-command and reversible
- [ ] Exit criteria: missing dependency states are diagnosed with exact fixes

---

## Epic 14 - Plan-to-Execution Bridge Command

**Status:** `planned`
**Priority:** Medium
**Goal:** Add a command to execute from an approved plan artifact with progress tracking and deviation reporting.
**Depends on:** Epic 2, Epic 3

- [ ] Task 14.1: Define plan artifact contract
  - [ ] Subtask 14.1.1: Define accepted plan format (markdown checklist + metadata)
  - [ ] Subtask 14.1.2: Define validation rules before execution starts
  - [ ] Subtask 14.1.3: Define step state transitions and completion semantics
- [ ] Task 14.2: Implement execution bridge backend
  - [ ] Subtask 14.2.1: Add `/start-work <plan>` command implementation
  - [ ] Subtask 14.2.2: Execute steps sequentially with checkpoint updates
  - [ ] Subtask 14.2.3: Capture and report deviations from original plan
- [ ] Task 14.3: Integrations and observability
  - [ ] Subtask 14.3.1: Integrate with background subsystem where safe
  - [ ] Subtask 14.3.2: Integrate with digest summaries for end-of-run recap
  - [ ] Subtask 14.3.3: Expose execution status in doctor/debug outputs
- [ ] Task 14.4: Validation and docs
  - [ ] Subtask 14.4.1: Add tests for plan parsing and execution flow
  - [ ] Subtask 14.4.2: Add recovery tests for interrupted plan runs
  - [ ] Subtask 14.4.3: Add docs with sample plans and workflows
- [ ] Exit criteria: approved plans can be executed and resumed with clear state
- [ ] Exit criteria: deviations are explicitly surfaced and reviewable

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
  - [ ] Subtask C1.7: Phase G (optional power-user): Epic 6 + Epic 7
- [ ] Task C2: Add acceptance criteria template per epic
  - [ ] Subtask C2.1: Functional criteria
  - [ ] Subtask C2.2: Reliability criteria
  - [ ] Subtask C2.3: Documentation criteria
  - [ ] Subtask C2.4: Validation criteria (`make validate`, `make selftest`, `make install-test`)
  - [ ] Subtask C2.5: Evidence links (PR, commit, test output summary)
- [ ] Task C3: Add tracking cadence
  - [ ] Subtask C3.1: Weekly status update section in this file
  - [ ] Subtask C3.2: Keep one epic `in_progress`
  - [ ] Subtask C3.3: Move deferred work to `postponed` explicitly
  - [ ] Subtask C3.4: Revisit paused/postponed epics at least once per month

## Weekly Status Updates

Use this log to track what changed week by week.

- [ ] YYYY-MM-DD: update epic statuses, completed checkboxes, and next focus epic

## Decision Log

- [x] 2026-02-12: Adopt stable-first sequencing; prioritize E1 before orchestration-heavy epics.
- [x] 2026-02-12: Keep E6 paused until E1-E5 foundations stabilize.
- [x] 2026-02-12: Keep E7 postponed pending stronger demand for tmux visual mode.
- [x] 2026-02-12: Add E8-E14 as high-value extensions identified from comparative analysis.

---

## Current Recommendation

- Start with **Epic 1** next (lowest risk, highest leverage).
- Prioritize **E8-E10** after E1-E5 for fast workflow gains.
- Prioritize **E11-E12** before E13-E14 when stability concerns are high.
- Keep **Epic 6** paused and **Epic 7** postponed until core and control epics stabilize.
