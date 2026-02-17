# Autopilot Command Contract (Epic 28 Task 28.1)

This contract defines `/autopilot` objective-runner behavior so autonomous execution remains bounded, inspectable, and safe by default.

## Goals

- Provide one high-level command for objective-driven execution with explicit lifecycle controls.
- Enforce strict scope and budget boundaries before any stateful execution starts.
- Keep every run auditable with deterministic status, report, and reason-code outputs.

## Subcommand Surface

`/autopilot` exposes lifecycle subcommands:

1. `start` - register and begin a new objective run.
2. `go` - start-or-resume and execute bounded cycles until a terminal state or cycle cap.
3. `status` - show current lifecycle state, budget usage, and checkpoint position.
4. `pause` - stop autonomous progression while preserving resumable state.
5. `resume` - continue a paused run after re-validation of gates.
6. `stop` - hard-stop execution with explicit reason and final status.
7. `report` - emit structured summary of progress, blockers, and next actions.

All subcommands must support `--json` output.

Subcommand dispatch note:

- `/autopilot help|status|report|doctor|pause|resume|stop` dispatches directly to the requested subcommand.
- `/autopilot` with no subcommand may default to `go` behavior.

## Objective Schema

Objective fields:

- `goal` - outcome-oriented statement of intent.
- `scope` - allowed files/modules/workflows; out-of-scope work is blocked.
- `done-criteria` - measurable completion conditions.
- `max-budget` - bounded budget profile or explicit limits.
- `completion-mode` - `promise` (default) or `objective`.
- `completion-promise` - token text used when `completion-mode=promise` (default: `DONE`).

CLI parsing note:

- Multi-word values passed to `--goal`, `--scope`, `--done-criteria`, and `--completion-promise` should be quoted.
- Example: `--goal "fix docs" --scope "docs/**,README.md"`.

Optional fields:

- `risk-level` (`low|medium|high`)
- `handoff-mode` (`auto|manual`)
- `approval-policy` (`none|required-before-execute|required-before-merge`)

When objective fields are omitted in `start`/`go`, command-layer defaults may be inferred (`goal`, `scope="**"`, `done-criteria=goal`) and surfaced via `inferred_defaults` + warning metadata.
Runtime schema validation still applies after inference; unresolved omissions must fail with `objective_schema_invalid`.

Completion modes:

- `promise` (default): run remains active until completion signal is detected (`<promise>{{completion-promise}}</promise>`), even if cycles are exhausted.
- `objective`: run completes when objective done-criteria cycles are exhausted.

Cycle cap semantics:

- `--max-cycles` is an upper bound per invocation, not a guaranteed iteration count.
- Runs can finish earlier when completion gates are met (objective done-criteria or completion promise).

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

Subcommand dispatch note:

- `/autopilot help|status|report|doctor|pause|resume|stop` must dispatch directly to the requested subcommand.
- `/autopilot` with no subcommand may default to `go` behavior.

## Safety Invariants

- `/autopilot` never executes outside declared `scope`.
- `/autopilot` never exceeds declared `max-budget`.
- `pause`, `resume`, and `stop` are always operator-accessible.
- Every state change records timestamp, actor, and reason code.
