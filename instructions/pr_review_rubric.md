# PR Review Copilot Rubric (Epic 23 Task 23.1)

This contract defines deterministic, low-noise risk scoring for `/pr-review`.

## Goals

- Catch merge blockers before review fatigue sets in.
- Keep default output concise and actionable.
- Prefer conservative blocker decisions (high confidence + concrete evidence).

## Risk Categories

Use one or more categories per finding. Categories are ordered by default impact.

1. `security`
   - Signals: auth/permission changes, secret handling, input validation, command execution, dependency risk.
2. `data_loss`
   - Signals: delete/migrate paths, destructive defaults, non-reversible writes, retention policy changes.
3. `migration_impact`
   - Signals: config/schema/CLI contract changes, compatibility removals, upgrade-path ambiguity.
4. `test_coverage`
   - Signals: behavior changes without matching test updates, removed assertions, missing failure-path coverage.
5. `docs_changelog`
   - Signals: command or workflow changes without README/changelog updates, operator runbook drift.

## Severity Model

Severity captures user impact if merged as-is.

- `S0` (`none`): informational only; no action required.
- `S1` (`low`): minor clarity/maintenance issue; merge can proceed.
- `S2` (`medium`): meaningful risk or missing guardrail; requires reviewer attention.
- `S3` (`high`): likely regression/security/data-loss/migration break; default is block.

## Confidence Model

Confidence captures evidence strength.

- `C0` (`hypothesis`): weak signal, no direct diff evidence.
- `C1` (`suggestive`): indirect evidence, plausible but uncertain.
- `C2` (`strong`): direct diff evidence with clear traceability.
- `C3` (`verified`): direct evidence plus validation failure or deterministic rule match.

## Evidence Contract

Every finding must include:

- `file_refs`: at least one `path:line` reference.
- `rationale`: one sentence linking signal to risk.
- `recommended_action`: one concrete remediation step.

Additional requirements for blocker recommendations (`recommendation = block`):

- Minimum thresholds: `severity >= S3` and `confidence >= C2`.
- Include one `hard_evidence` item:
  - failing validation/check output, or
  - deterministic policy violation (contract/rule mismatch), or
  - explicit missing migration/rollback path for breaking change.
- If any blocker threshold is not met, downgrade to `needs_review`.

## Recommendation Mapping

Map findings to one of four outcomes:

- `approve`: no findings above `S1`, or only `S0`/`S1` with `C0`/`C1`.
- `needs_review`: at least one `S2` finding or confidence below blocker threshold.
- `changes_requested`: repeated `S2` findings with `C2+` and concrete remediations.
- `block`: one or more findings meeting blocker evidence contract.

Tie-break rule for low-noise defaults:

- If severity/confidence disagree, choose the less severe recommendation unless hard evidence exists.

## Output Shape Requirements

- Concise mode: max 5 top findings, sorted by `(severity desc, confidence desc)`.
- JSON mode: include full findings list plus aggregate counts by category/severity.
- Always include:
  - `summary`
  - `recommendation`
  - `blocking_reasons` (empty when not blocked)
  - `missing_evidence` list for downgraded potential blockers.

## Determinism Rules

- Same diff and same rule set must produce same category/severity/confidence outputs.
- Avoid speculative blockers without file-level evidence.
- Treat missing tests/docs/changelog as first-class findings, not optional hints.
