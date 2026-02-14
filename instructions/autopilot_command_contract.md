# Autopilot Command Contract (Epic 28 Task 28.1)

This contract defines `/autopilot` objective-runner behavior so autonomous execution remains bounded, inspectable, and safe by default.

## Goals

- Provide one high-level command for objective-driven execution with explicit lifecycle controls.
- Enforce strict scope and budget boundaries before any stateful execution starts.
- Keep every run auditable with deterministic status, report, and reason-code outputs.

## Subcommand Surface

`/autopilot` exposes six primary subcommands:

1. `start` - register and begin a new objective run.
2. `status` - show current lifecycle state, budget usage, and checkpoint position.
3. `pause` - stop autonomous progression while preserving resumable state.
4. `resume` - continue a paused run after re-validation of gates.
5. `stop` - hard-stop execution with explicit reason and final status.
6. `report` - emit structured summary of progress, blockers, and next actions.

All subcommands must support `--json` output.

## Objective Schema

`/autopilot start` requires objective fields:

- `goal` - outcome-oriented statement of intent.
- `scope` - allowed files/modules/workflows; out-of-scope work is blocked.
- `done-criteria` - measurable completion conditions.
- `max-budget` - bounded budget profile or explicit limits.

Optional fields:

- `risk-level` (`low|medium|high`)
- `handoff-mode` (`auto|manual`)
- `approval-policy` (`none|required-before-execute|required-before-merge`)

Missing required fields must fail with `objective_schema_invalid`.

## Lifecycle States

Allowed states and transitions:

- `draft -> running`
- `running -> paused`
- `paused -> running`
- `running -> stopped`
- `paused -> stopped`
- `running -> completed`

Invalid transitions must return `invalid_state_transition`.

## Safe Defaults

Safety defaults are mandatory unless explicitly overridden by policy:

- `start` performs a `dry-run` preview before first execution cycle.
- First stateful cycle is blocked until dry-run output is acknowledged.
- Budget guardrails are evaluated on every cycle boundary.
- Stop-on-risk defaults to enabled when confidence drops below threshold.

Default reason codes:

- `dry_run_required_before_execute`
- `budget_threshold_reached`
- `scope_violation_blocked`
- `confidence_drop_requires_handoff`

## Output Contract

`/autopilot status --json` must include:

- `run_id`
- `state`
- `objective` (goal, scope, done_criteria, max_budget)
- `budget` (limits, counters, ratios)
- `progress` (completed_steps, pending_steps, blockers)
- `next_actions`

`/autopilot report --json` must include:

- `run_id`
- `state`
- `summary`
- `decisions` (guardrails/trade-offs)
- `blockers`
- `recommendations`

All non-pass outcomes must emit at least one remediation hint.

## Safety Invariants

- `/autopilot` never executes outside declared `scope`.
- `/autopilot` never exceeds declared `max-budget`.
- `pause`, `resume`, and `stop` are always operator-accessible.
- Every state change records timestamp, actor, and reason code.
