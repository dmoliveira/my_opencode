# Resume Policy Model

Epic 17 Task 17.1 defines the policy contract for safe, deterministic auto-resume behavior.

## Goals

- resume interrupted workflows from the latest known-safe checkpoint without repeating unsafe actions
- keep resume decisions explainable and auditable for operators and tooling
- prevent runaway retry loops through bounded attempts and escalation rules

## Interruption classes

Every interrupted run must be classified into one interruption class:

- `tool_failure`: an external command/tool exits non-zero without hard timeout
- `timeout`: an action exceeds configured wall-clock or tool-level timeout
- `context_reset`: execution context is lost or pruned before current step completes
- `process_crash`: orchestrator/runtime exits unexpectedly (panic, signal, crash)

Unknown classes must fail eligibility checks.

## Resume eligibility rules

A run is resume-eligible only when all conditions hold:

1. A valid checkpoint exists with `status: in_progress` or `status: failed`.
2. The last attempted step is marked idempotent or explicitly resume-approved.
3. Required artifacts (plan snapshot, runtime state, and transition history) are readable.
4. Current resume attempt count is below `max_resume_attempts`.

If any condition fails, auto-resume must not execute and must emit a deterministic reason code.

## Cool-down policy

Resume attempts must respect cool-down windows:

- `tool_failure`: 30 seconds
- `timeout`: 120 seconds
- `context_reset`: 10 seconds
- `process_crash`: 60 seconds

During cool-down, status commands should return `resume_blocked_cooldown` with remaining seconds.

## Max attempts and escalation

- default `max_resume_attempts`: 3 per run
- after exceeding max attempts, set run state to `resume_escalated`
- escalation must require explicit operator action (for example `/resume now --force` in a future task)
- escalation output must include a remediation checklist and latest failure context

## Deterministic reason codes

Resume policy outcomes should use machine-readable reason codes:

- `resume_allowed`
- `resume_missing_checkpoint`
- `resume_unknown_interruption_class`
- `resume_non_idempotent_step`
- `resume_missing_runtime_artifacts`
- `resume_blocked_cooldown`
- `resume_attempt_limit_reached`

## Audit event contract

Resume-relevant decisions should emit append-only audit events:

```json
{
  "event": "resume_decision",
  "run_id": "run-2026-02-13-01",
  "interruption_class": "timeout",
  "eligible": false,
  "reason_code": "resume_blocked_cooldown",
  "cooldown_seconds_remaining": 87,
  "attempt": 2,
  "max_attempts": 3,
  "at": "2026-02-13T12:20:00Z",
  "actor": "system"
}
```

## Integration targets

- Task 17.2 should implement runtime eligibility and cooldown/attempt counters from this contract.
- Task 17.3 should expose `/resume` command outputs using these reason codes.
- Task 17.4 should validate interruption-class coverage, cooldown enforcement, and escalation behavior.
