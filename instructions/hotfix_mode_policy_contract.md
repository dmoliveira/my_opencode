# Incident Hotfix Mode Policy Contract (Epic 25 Task 25.1)

This contract defines non-skippable safety controls for `/hotfix` workflows so emergency speed does not bypass critical protection.

## Goals

- Shorten time-to-mitigation while preserving minimum release safety guarantees.
- Keep hotfix decisions auditable through deterministic reason codes and timeline events.
- Force post-incident hardening follow-up so temporary shortcuts are reconciled.

## Incident Scope and Activation

`/hotfix start` is allowed only when all activation conditions are true:

1. Incident ticket/reference is present (`--incident-id` required).
2. Change scope is explicitly declared (`--scope` values: `patch`, `rollback`, `config_only`).
3. Operator confirms production impact (`--impact` values: `sev1`, `sev2`, `sev3`).
4. Start command records timestamp, actor, and target branch.

Missing any activation requirement blocks start with `result=FAIL`.

## Mandatory Checks (Cannot Be Skipped)

The following checks are mandatory in all hotfix modes, including reduced validation:

- Repository hygiene
  - working tree is clean before `start` and `close`
  - target branch is current and not behind remote
- Safety checks
  - `make validate` must pass
  - rollback checkpoint must exist before patch apply
- Audit checks
  - timeline includes `started`, `patch_applied`, and `closed` events
  - close requires explicit outcome summary (`resolved`, `mitigated`, or `rolled_back`)

If a mandatory check fails, return `reason_codes` and stop execution.

## Reduced-Scope Validation Profile

Hotfix mode allows accelerated validation, but only within strict limits.

Allowed reduced profile:

- required: `make validate`
- required: targeted test command for changed area (`--target-test` required when code changes)
- optional during incident: full `make selftest` and `make install-test`
- required after closure: deferred full suite (`make selftest`, `make install-test`) within follow-up window

Constraints:

- If changed files include `scripts/` and no `--target-test` is provided, block.
- If scope is `rollback`, patch application is skipped and rollback verification is required.
- If scope is `config_only`, require config doctor check before close.

## Post-Hotfix Follow-Up Requirements

Every hotfix must open and track post-incident hardening work.

Required artifacts at `close`:

1. Follow-up issue id for permanent fix or test hardening.
2. Deferred validation completion plan with owner and due date.
3. Incident timeline export path.

Required follow-up tasks:

- Root-cause and prevention note added to incident record.
- Missing automated tests added or tracked explicitly.
- Any temporary override removed and verified.

## Timeline and Audit Contract

Timeline events must be append-only and include:

- `event`
- `timestamp`
- `actor`
- `details`

Minimum event sequence:

1. `started`
2. `checkpoint_created`
3. `patch_applied` or `rollback_applied`
4. `validation_completed`
5. `closed`

## Reason Codes

Minimum reason-code set:

- `incident_id_required`
- `scope_required`
- `impact_required`
- `dirty_worktree`
- `branch_behind_remote`
- `validate_failed`
- `target_test_required`
- `target_test_failed`
- `rollback_checkpoint_missing`
- `timeline_event_missing`
- `followup_issue_required`
- `deferred_validation_plan_required`
- `config_doctor_required`

All failures must include at least one remediation hint.
