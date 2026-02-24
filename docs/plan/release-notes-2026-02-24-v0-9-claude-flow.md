# Release Notes Draft (2026-02-24) - v0.9 Claude-Flow Upgrades

## Summary

- Completed the full v0.9 Claude-style flow roadmap end-to-end (E1-E6) with small merged PR slices.
- Added higher-level execution controls for rollback, contract-gated plan execution, local review, recovery triage, narrative generation, and intent routing.
- Kept command surface canonical while adding deterministic selftest coverage and doc parity for each new flow.

## Included Pull Requests

- [#308](https://github.com/dmoliveira/my_opencode/pull/308) - add checkpoint create/restore rollback flow
- [#309](https://github.com/dmoliveira/my_opencode/pull/309) - add contract-enforced plan run command
- [#310](https://github.com/dmoliveira/my_opencode/pull/310) - add structured local review command
- [#311](https://github.com/dmoliveira/my_opencode/pull/311) - add resume smart failure triage bundle
- [#312](https://github.com/dmoliveira/my_opencode/pull/312) - add changes explain narrative command
- [#313](https://github.com/dmoliveira/my_opencode/pull/313) - add intent router do/ship command gates

## Highlights

- Rollback UX: `/checkpoint create|restore` now supports explicit overwrite confirmation and run-id mismatch guardrails.
- Contract execution: `/plan run` requires explicit objective/scope/acceptance/stop sections before runtime delegation.
- Pre-PR quality pass: `/review local` surfaces correctness/risk/tests/docs/migration sections plus remediation hints.
- Recovery triage: `/resume smart` emits structured diagnostics and likely fix paths for faster recovery loops.
- Handoff/release writing: `/changes explain` provides deterministic `why|risk|verify` narrative output from diff evidence.
- Intent routing: `/do` and `/ship` map high-level intent to canonical guarded workflows (autopilot and release preflight).

## Validation Evidence

- `make validate`
- `make selftest`
- `make install-test`
- `pre-commit run --all-files`

## Milestone Sources

- `docs/plan/v0.9-claude-flow-upgrades-plan.md`
- `docs/plan/v0.9-claude-flow-milestones-changelog.md`
