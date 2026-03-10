# Post-Merge Parity Backlog - 2026-03-10

Branch: `wt/post-merge-parity-backlog`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-post-merge-parity-backlog`

## Purpose

Capture the next high-value parity work after PR `#443` merged the hook hardening and atlas-inspired task shaping slices.

## Completed baseline

- gateway LLM decision hook bindings are corrected
- hook startup and runtime failure handling are hardened
- atlas-inspired post-task and pre-task shaping are present locally
- continuity wording is canonicalized
- agent metadata discovery is dynamic

## Remaining high-value backlog

### 1. Atlas runtime parity: direct-edit and tool-time enforcement

Status: `proposed`

Why it matters:

- local runtime now covers task-shaping reminders, but still does not mirror the stronger Atlas-style tool-time behavior for execution discipline and direct-edit avoidance

Evidence:

- intentional divergence remains documented in `docs/upstream-divergence-registry.md`
- local scope today is only `task-resume-info` + `agent-context-shaper`

Suggested slice:

- prototype one additional runtime behavior in gateway-core that warns or blocks when delegated work drifts into direct edits without the expected orchestration flow

### 2. `claude-code-hooks` compatibility decision

Status: `proposed`

Why it matters:

- this is the clearest remaining upstream hook-surface divergence; if transcript or Claude-session compatibility becomes a requirement, it needs an explicit implementation track instead of staying implied parity

Evidence:

- documented as intentional divergence in `docs/upstream-divergence-registry.md`

Suggested slice:

- decide explicitly between (a) keep divergence closed, or (b) open a compatibility epic with concrete event mapping requirements

### 3. Parity tracker normalization after merge

Status: `done`

Why it matters:

- tracker state needed normalization because the core parity hardening work had already merged in `#443`

Evidence:

- normalized in `docs/plan/current-roadmap-tracker.md` by replacing the merged parity slices with a single post-merge backlog triage stream and moving the merged work into `done`

Suggested slice:

- completed in this worktree

### 4. LLM decision rollout completion

Status: `active`

Why it matters:

- the roadmap still has an unfinished mixed-signal `todo-continuation-enforcer` fallback rollout, which is the main remaining live runtime-control stream adjacent to parity work

Evidence:

- `docs/plan/current-roadmap-tracker.md`
- `docs/plan/status/in_progress/llm-decision-hooks-plan.md`

Suggested slice:

- finish shadow-first rollout, gather workflow evidence, then either promote or explicitly defer

## Recommended execution order

1. Finish the `todo-continuation-enforcer` rollout decision
2. Decide whether Atlas direct-edit/tool-time enforcement is still in scope
3. Decide whether `claude-code-hooks` compatibility should remain a closed divergence
