# Post-Merge Parity Backlog - 2026-03-10

Branch: `wt/post-merge-parity-backlog`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-post-merge-parity-backlog`

## Purpose

Capture the next high-value parity work after PR `#443` merged the hook hardening and delegation-focused task shaping slices.

## Completed baseline

- gateway LLM decision hook bindings are corrected
- hook startup and runtime failure handling are hardened
- delegation-focused post-task and pre-task shaping are present locally
- continuity wording is canonicalized
- agent metadata discovery is dynamic

## Remaining high-value backlog

### 1. Delegation-first direct-work discipline

Status: `in_progress`

Why it matters:

- local runtime now covers task-shaping reminders, but still lacks stronger tool-time discipline around direct primary-agent edits during work that should usually be delegated

Evidence:

- intentional divergence remains documented in `docs/upstream-divergence-registry.md`
- local scope today is only `task-resume-info` + `agent-context-shaper`

Suggested slice:

- first slice implemented in `plugin/gateway-core/src/hooks/direct-work-warning/index.ts`; it ships as warn-first by default, exposes optional repeated-edit blocking, and now supports path-aware documentation exceptions while broader policy tuning remains follow-up work

### 2. `claude-code-hooks` compatibility decision

Status: `reviewed` - keep divergence closed for now

Why it matters:

- this is the clearest remaining upstream hook-surface divergence; if transcript or Claude-session compatibility becomes a requirement, it needs an explicit implementation track instead of staying implied parity

Evidence:

- documented as intentional divergence in `docs/upstream-divergence-registry.md`

Suggested slice:

- decision captured in `docs/plan/claude-code-hooks-decision-2026-03-11.md`: keep divergence closed unless direct Claude transcript/session compatibility becomes a real requirement

### 3. Parity tracker normalization after merge

Status: `done`

Why it matters:

- tracker state needed normalization because the core parity hardening work had already merged in `#443`

Evidence:

- normalized in `docs/plan/current-roadmap-tracker.md` by replacing the merged parity slices with a single post-merge backlog triage stream and moving the merged work into `done`

Suggested slice:

- completed in this worktree

### 4. LLM decision rollout completion

Status: `reviewed` - keep in shadow for now

Why it matters:

- the roadmap still has an unfinished mixed-signal `todo-continuation-enforcer` fallback rollout, but the core hook wiring, tests, and workflow scenarios are already present on `main`

Evidence:

- `docs/plan/current-roadmap-tracker.md`
- `docs/plan/status/in_progress/llm-decision-hooks-plan.md`
- `plugin/gateway-core/src/hooks/todo-continuation-enforcer/index.ts`
- `plugin/gateway-core/test/todo-continuation-enforcer-hook.test.mjs`
- `docs/plan/status/in_progress/workflow-scenario-report.md`

Suggested slice:

- do not re-implement the hook in this worktree; rollout decision captured in `docs/plan/status/in_progress/todo-continuation-rollout-decision-2026-03-10.md` keeps it in `shadow` until live disagreement telemetry exists

## Recommended execution order

1. Extend delegation-first direct-work discipline beyond warn-only reminders
2. Revisit `todo-continuation-enforcer` promotion only after fresh live disagreement telemetry is collected
