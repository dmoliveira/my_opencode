# Plan Artifact Contract

Epic 14 Task 14.1 defines the baseline artifact contract for `/start-work <plan>` execution.

## Goals

- keep plan execution deterministic from a human-reviewed artifact
- fail fast on malformed or unsafe plans with actionable errors
- preserve step progress and deviations in a machine-readable state model

## Accepted artifact format

The command accepts a markdown file with two required sections in this order:

1. metadata frontmatter (YAML)
2. execution checklist body (markdown task list)

Reference skeleton:

```markdown
---
id: plan-2026-02-13-e14t1
title: Example migration plan
owner: diego
created_at: 2026-02-13T10:00:00Z
version: 1
---

# Plan

- [ ] 1. Prepare baseline checks
- [ ] 2. Apply implementation changes
- [ ] 3. Run verification and summarize deltas
```

## Metadata contract

Required keys:

- `id`: stable slug-like identifier (`[a-z0-9][a-z0-9-_]{2,63}`)
- `title`: non-empty human label
- `owner`: actor/team responsible for execution
- `created_at`: RFC3339 timestamp
- `version`: positive integer

Optional keys:

- `depends_on`: array of external references (issue ids, PRs, doc ids)
- `risk_level`: one of `low`, `medium`, `high`
- `timeout_minutes`: integer guardrail for total execution budget

Unknown metadata keys are preserved but ignored by v1 validation.

## Checklist contract

- each executable step must be a top-level markdown checkbox (`- [ ]`)
- step text must start with a numeric ordinal (`1.`, `2.`, `3.`) to keep ordering explicit
- ordinals must be strictly increasing without duplicates
- nested checklist items are treated as notes and are not executable steps
- empty checkbox lines are invalid

## Pre-execution validation rules

Validation must fail before execution when any of these are true:

- missing frontmatter or malformed YAML
- missing required metadata key or invalid key value type/format
- no executable checklist steps
- duplicate or out-of-order ordinals
- all steps already marked complete (`- [x]`) at start

Validation output must include:

- deterministic machine-readable error codes
- file path + line numbers for each violation
- remediation hints for each failed rule

## Step state model and transitions

Each executable step is tracked with one of:

- `pending`
- `in_progress`
- `completed`
- `failed`
- `skipped`

Allowed transitions:

- `pending -> in_progress`
- `in_progress -> completed`
- `in_progress -> failed`
- `in_progress -> skipped`
- `failed -> in_progress` (retry path)

Disallowed transitions must fail with explicit transition error diagnostics.

Completion semantics:

- exactly one step can be `in_progress` at a time
- plan is complete only when all executable steps are `completed` or `skipped`
- any `failed` step keeps the overall plan status in failed/recovery-required state

## Deviation capture requirements

Execution runtime must record deviations from the original artifact, including:

- inserted ad-hoc step not present in the source plan
- skipped required step with rationale
- reordered execution relative to declared ordinal sequence

Deviation records should include step id, timestamp, reason, and actor.

## Integration targets

- Task 14.2 should implement parser/validator + state transition engine for this contract
- Task 14.3 should expose contract/state health through doctor and digest outputs
- Task 14.4 should add parser/transition/recovery tests and user-facing docs with sample plans
