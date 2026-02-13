# Execution Budget Model (E20-T1)

This document defines the baseline execution budget policy for Epic 20.

## Budget dimensions

Budget enforcement tracks three primary dimensions per run:

- `wall_clock_seconds`: elapsed runtime from run start.
- `tool_call_count`: total tool invocations across shell/file/network commands.
- `token_estimate`: rolling estimate of prompt + response tokens consumed.

Optional supporting dimensions:

- `error_burst_count`: consecutive failures without successful step completion.
- `long_running_command_seconds`: max duration of a single blocking command.

All dimensions must be recorded as monotonically increasing counters in runtime state.

## Profile defaults

Budget profiles provide deterministic guardrails by workload type.

### `conservative`

- wall clock: 900 seconds
- tool calls: 80
- token estimate: 80_000
- behavior: strict soft warning at 75%, hard stop at 100%

### `balanced`

- wall clock: 1800 seconds
- tool calls: 180
- token estimate: 180_000
- behavior: soft warning at 80%, hard stop at 100%

### `extended`

- wall clock: 3600 seconds
- tool calls: 360
- token estimate: 360_000
- behavior: soft warning at 85%, hard stop at 100%

Default profile: `balanced`.

## Threshold semantics

- soft threshold: emit warning diagnostics and include continuation guidance.
- hard threshold: block further non-read-only execution and force stop status.
- overage reason codes:
  - `budget_wall_clock_exceeded`
  - `budget_tool_call_exceeded`
  - `budget_token_estimate_exceeded`

When multiple limits are exceeded, all reason codes must be reported, with the first crossed limit set as the primary stop cause.

## Overrides and emergency stop

Overrides are explicit and auditable.

- temporary override fields:
  - `expires_at`
  - `actor`
  - `reason`
  - `delta` per budget dimension
- overrides cannot exceed 2x of profile defaults.
- expired overrides are ignored automatically.

Emergency stop semantics:

- `/budget stop` immediately sets run status to `budget_stopped`.
- no mutating commands may run after emergency stop until explicit reset.
- stop event payload must include `actor`, `reason`, `at`, and current counters.

## Non-goals for Task 20.1

- no runtime counter enforcement yet (Task 20.2).
- no command surface implementation yet (Task 20.3).
- no threshold-crossing test matrix yet (Task 20.4).
