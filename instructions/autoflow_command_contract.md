# Autoflow Command Contract

Epic 22 Task 22.1 defines the baseline contract for `/autoflow` orchestration.

## Goals

- provide one deterministic orchestration surface over plan, todo, budget, and recovery primitives
- keep default usage safe and auditable with explicit stop conditions
- preserve machine-readable output for automation while keeping concise human summaries

## Command surface

`/autoflow` supports these subcommands:

- `start <plan.md>`: run orchestration with guardrails
- `status`: show latest orchestration state
- `resume`: attempt deterministic recovery from latest checkpoint/resume context
- `stop`: halt active orchestration and record stop reason
- `report`: emit run summary with deviations, budget, and recovery trail
- `dry-run <plan.md>`: resolve planned actions and safety checks without mutating state

## Input and validation contract

`start` and `dry-run` accept plan artifacts matching `instructions/plan_artifact_contract.md`.

Validation requirements:

- fail before execution when plan metadata/checklist validation fails
- fail when todo compliance preconditions are violated
- fail when runtime state is already non-recoverable and requires operator intervention
- fail when configured budget policy is invalid or contains non-positive overrides

Deterministic validation error shape:

- top-level `result: FAIL`
- stable `code` (for example: `validation_failed`, `todo_non_compliant`, `budget_config_invalid`, `resume_not_eligible`)
- `violations[]` entries with `code`, `message`, and optional `path`/`line`
- `remediation[]` with actionable next commands

## Output modes

### Concise mode (default)

Human-readable summary with:

- final `result` and `status`
- active `phase` (`planning`, `executing`, `paused`, `recovering`, `completed`, `failed`)
- guardrail highlights (todo/budget/recovery)
- 2-4 suggested next commands

### Verbose mode (`--json`)

Machine-readable payload with stable top-level keys:

- `result`, `status`, `phase`
- `plan` (path + metadata)
- `step_counts` (total/done/in_progress/pending/skipped/failed)
- `todo_compliance`, `budget`, `checkpoint`, `resume`
- `deviations` (count + entries)
- `trace` (decision events and fallback reasons)
- `warnings`, `problems`, `quick_fixes`
- `config`

## Lifecycle states

Overall orchestration status values:

- `queued`
- `running`
- `paused`
- `completed`
- `failed`
- `stopped`
- `budget_stopped`
- `resume_required`

State transitions must be deterministic and reject illegal jumps with explicit reason codes.

## Safety defaults

- `dry-run` does not write runtime/checkpoint state
- `start` enforces todo compliance and budget checks before any destructive step
- `stop` requires explicit operator reason and records actor/timestamp
- `resume` is gated by interruption class and idempotency checks

## Integration expectations for Task 22.2+

- compose existing engines from `/start-work`, `/todo`, `/resume`, `/checkpoint`, and budget runtime
- keep reason-code vocabulary stable across subcommands
- ensure `/doctor run --json` can consume `/autoflow` health state without extra parsing rules
