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

| Epic | Title | Status | Priority | Depends On | Notes |
|---|---|---|---|---|---|
| E1 | Config Layering + JSONC Support | planned | High | - | Foundation for most later epics |
| E2 | Background Task Orchestration | planned | High | E1 | Keep minimal and stable first |
| E3 | Refactor Workflow Command | planned | High | E1 | Safer rollout after config layering |
| E4 | Continuation and Safety Hooks | planned | Medium | E1, E2 | Start with minimal hooks only |
| E5 | Category-Based Model Routing | planned | Medium | E1 | Can partially overlap with E2/E3 |
| E6 | Session Intelligence and Resume Tooling | paused | Medium | E2 | Resume when core orchestration stabilizes |
| E7 | Tmux Visual Multi-Agent Mode | postponed | Low | E2 | Optional power-user feature |

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

## Cross-Cutting Delivery Tasks

**Status:** `planned`

- [ ] Task C1: Add release slicing plan by phase
  - [ ] Subtask C1.1: Phase A (low-risk foundation): Epic 1
  - [ ] Subtask C1.2: Phase B (workflow power): Epic 2 + Epic 3
  - [ ] Subtask C1.3: Phase C (advanced automation): Epic 4 + Epic 5
  - [ ] Subtask C1.4: Phase D (optional power-user): Epic 6 + Epic 7
- [ ] Task C2: Add acceptance criteria template per epic
  - [ ] Subtask C2.1: Functional criteria
  - [ ] Subtask C2.2: Reliability criteria
  - [ ] Subtask C2.3: Documentation criteria
  - [ ] Subtask C2.4: Validation criteria (`make validate`, `make selftest`, `make install-test`)
- [ ] Task C3: Add tracking cadence
  - [ ] Subtask C3.1: Weekly status update section in this file
  - [ ] Subtask C3.2: Keep one epic `in_progress`
  - [ ] Subtask C3.3: Move deferred work to `postponed` explicitly

## Weekly Status Updates

Use this log to track what changed week by week.

- [ ] YYYY-MM-DD: update epic statuses, completed checkboxes, and next focus epic

---

## Current Recommendation

- Start with **Epic 1** next (lowest risk, highest leverage).
- Keep **Epic 6** paused until Epics 1-5 stabilize.
- Keep **Epic 7** postponed unless there is strong demand for visual tmux orchestration.
