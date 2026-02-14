# Repo Health Score Policy Contract (Epic 26 Task 26.1)

This contract defines the score model used by `/health` workflows so diagnostics become a stable, actionable operational signal.

## Goals

- Aggregate existing subsystem diagnostics into one score that reflects real operational risk.
- Keep score transitions deterministic so repeated runs with the same inputs produce the same result.
- Prevent alert fatigue with suppression windows for repeated drift findings.

## Indicator Model

The score is computed from high-signal indicators already available in the project:

1. Validation health (`make validate`, `make selftest`, `make install-test` outcomes).
2. Git hygiene and release readiness (clean tree, changelog/version alignment, release preflight).
3. Runtime policy drift (budget profile drift, hooks disabled, policy/profile mismatch).
4. Automation reliability (background job failures, recovery eligibility failures, doctor subsystem failures).
5. Operational freshness (stale work branches, stale deferred follow-up items, stale checkpoints requiring prune).

Each indicator must publish:

- `indicator_id`
- `status` (`pass`, `warn`, `fail`)
- `weight`
- `reason_codes`
- `observed_at`

## Weighted Scoring

Base score starts at `100` and subtracts weighted penalties.

Penalty map:

- `pass`: `0 * weight`
- `warn`: `0.5 * weight`
- `fail`: `1.0 * weight`

Default weights:

- validation health: `35`
- git/release hygiene: `20`
- runtime policy drift: `20`
- automation reliability: `15`
- operational freshness: `10`

Total weight must equal `100`. If custom weights are provided, normalize and record `weight_normalized=true` in output.

## Status Thresholds

Health status derives from final score:

- `healthy`: `score >= 85`
- `degraded`: `60 <= score < 85`
- `critical`: `score < 60`

Escalation rules:

- Any `fail` on validation health forces minimum status `degraded` even if score remains >= 85.
- Two or more `fail` indicators force `critical` unless overridden by explicit suppression policy.

## Drift Alert Suppression

To avoid repeated noise, drift alerts are suppressed per `(indicator_id, reason_code)` key.

- Default suppression window: `24h`.
- Critical failures ignore suppression and always emit alerts.
- Suppressed alerts still increment counters and are stored in history.
- Operator can force emission with `--force-alert`.

Required suppression metadata:

- `suppression_key`
- `first_seen_at`
- `last_emitted_at`
- `suppressed_count`
- `window_seconds`

## Output Contract

`/health status --json` must return:

- `score` (0-100)
- `status` (`healthy|degraded|critical`)
- `indicators` (detailed per-indicator records)
- `reason_codes` (aggregate, deduplicated)
- `suppression` summary (`active`, `suppressed_count`)
- `next_actions` (ordered remediation suggestions)

## Reason Codes

Minimum reason-code set:

- `validation_suite_failed`
- `release_hygiene_failed`
- `policy_drift_detected`
- `automation_failure_detected`
- `freshness_stale_signal`
- `critical_indicator_forced_status`
- `suppression_window_active`

All non-pass outcomes must include at least one remediation recommendation.
