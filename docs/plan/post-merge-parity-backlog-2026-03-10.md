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

Status: `reviewed` - warn-first baseline plus doc-path exceptions are in place

Why it matters:

- local runtime now covers task-shaping reminders, but still lacks stronger tool-time discipline around direct primary-agent edits during work that should usually be delegated

Evidence:

- intentional divergence remains documented in `docs/upstream-divergence-registry.md`
- local scope today is only `task-resume-info` + `agent-context-shaper`

Suggested slice:

- current baseline in `plugin/gateway-core/src/hooks/direct-work-warning/index.ts` ships as warn-first by default, exposes optional repeated-edit blocking, and supports path-aware documentation exceptions across relative, absolute, `apply_patch`, and `multiedit` payloads; broader policy tuning remains follow-up work

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

1. Decide whether direct-work discipline should gain stronger escalation rules beyond the current warn-first + opt-in block model
2. Revisit `todo-continuation-enforcer` promotion only after fresh live disagreement telemetry is collected

## Continuation note for next AI

- Current branch `wt/claude-hooks-decision` now contains two clean commits: the `claude-code-hooks` divergence decision and the direct-work discipline exception refinement.
- If continuing implementation, the highest-value next step is not more path matching; it is policy design for when repeated direct edits should escalate automatically versus remain warn-only.
- Keep `gateway-core` canonical. If a future compatibility layer is reopened, implement only adapters, not a second hook runtime.
