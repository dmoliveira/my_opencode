# Todo Compliance Model

Epic 15 Task 15.1 defines the compliance contract that keeps execution aligned with approved plans.

## Goals

- enforce explicit, auditable todo state progression during plan execution
- prevent silent task skipping by allowing only explicit, reasoned bypass paths
- keep compliance checks deterministic and machine-readable for automation

## Required todo state model

Every tracked todo item must be in exactly one state:

- `pending`: planned but not started
- `in_progress`: actively being executed
- `done`: completed and verified
- `skipped`: intentionally not executed with explicit rationale

Unknown states must fail compliance checks.

## Core enforcement rules

1. Exactly one item may be `in_progress` at a time.
2. Transition order must follow:
   - `pending -> in_progress`
   - `in_progress -> done`
   - `in_progress -> skipped`
3. Direct transitions like `pending -> done` are invalid unless a bypass annotation exists.
4. Plan completion is valid only when all items are `done` or `skipped`.

## Bypass annotations

Bypass is allowed only through explicit metadata attached to the affected item:

- `bypass_reason`: concise justification
- `bypass_actor`: who authorized it
- `bypass_at`: RFC3339 timestamp
- `bypass_type`: one of `risk_acceptance`, `scope_change`, `emergency_hotfix`

Missing any required bypass field must invalidate the bypass.

## Audit event format

Compliance-relevant state transitions should emit append-only events:

```json
{
  "event": "todo_transition",
  "todo_id": "todo-3",
  "from": "pending",
  "to": "in_progress",
  "at": "2026-02-13T12:00:00Z",
  "actor": "diego",
  "compliance": "enforced"
}
```

Bypass usage should emit:

```json
{
  "event": "todo_bypass",
  "todo_id": "todo-5",
  "from": "pending",
  "to": "done",
  "at": "2026-02-13T12:05:00Z",
  "actor": "diego",
  "bypass": {
    "type": "scope_change",
    "reason": "task absorbed into prior step",
    "authorized_by": "owner"
  }
}
```

## Validation outcomes

Compliance checks should return deterministic results:

- `PASS`: all todo states and transitions satisfy rules
- `FAIL`: violations detected; include violation code(s), affected todo id(s), and remediation hints

Reference violation codes:

- `unknown_todo_state`
- `multiple_in_progress_items`
- `invalid_transition`
- `missing_bypass_metadata`
- `incomplete_todo_set`

## Integration targets

- Task 15.2 should implement enforcement engine checks for this model
- Task 15.3 should expose `/todo status` and `/todo enforce` diagnostics with machine-readable outputs
- Task 15.4 should validate normal, bypass, and failure paths with docs/examples
