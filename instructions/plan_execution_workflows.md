# Plan Execution Validation and Workflow Guide

This guide accompanies Epic 14 Task 14.4 and documents validated workflows for `/start-work`.

## Sample plan artifact

Use this baseline plan format:

```markdown
---
id: sample-plan-001
title: Sample implementation plan
owner: diego
created_at: 2026-02-13T00:00:00Z
version: 1
---

# Plan

- [ ] 1. Prepare implementation environment
- [ ] 2. Apply code changes
- [ ] 3. Run verification and summarize results
```

## Primary execution workflow

1. Run `/start-work path/to/plan.md --json`.
2. Verify state with `/start-work status --json`.
3. Review deviations with `/start-work deviations --json`.
4. Run `/start-work doctor --json` before handoff.

## Background-safe workflow

Use queued execution when you want reviewable handoff through the background subsystem:

1. Run `/start-work-bg path/to/plan.md`.
2. Capture returned `job_id`.
3. Execute queued work with `/bg run --id <job-id>`.
4. Inspect logs via `/bg read <job-id> --json`.
5. Confirm final state using `/start-work status --json`.

## Validation failure examples

- Missing frontmatter should fail with `validation_failed` and `missing_frontmatter` violation.
- Out-of-order checklist ordinals should fail with `validation_failed` and `out_of_order_ordinals` violation.
- Non-numbered checklist items should fail with `validation_failed` and `missing_step_ordinal` violation.

## Recovery workflow

When runtime state is inconsistent (for example, multiple steps marked `in_progress`):

1. Run `/start-work doctor --json` to confirm failure diagnostics.
2. Re-run a valid plan with `/start-work path/to/plan.md --json` to restore deterministic state.
3. Re-check with `/start-work doctor --json` and `/doctor run --json`.
4. Run `/digest run --reason manual` to capture end-of-run recap including `plan_execution` summary.

## `/autoflow` knowledge-assisted workflow

Use published knowledge entries to seed safer `/autoflow` execution plans:

1. Run `/learn search --status published --json` to retrieve approved guidance.
2. Review `autoflow_guidance` and `rule_injector_candidates` from search output.
3. Apply relevant guidance before `/autoflow start` or `/autoflow dry-run`.
4. After execution, run `/learn capture --json` to record new outcomes and close the loop.
