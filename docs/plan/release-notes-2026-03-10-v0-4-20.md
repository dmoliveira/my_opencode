# Release Notes Draft (2026-03-10) - v0.4.20

## Milestone Sources
- `docs/plan/v0.4.20-flow-milestones-changelog.md`

## Included PRs
- #446
- #449
- #451
- #454
- [#446](https://github.com/dmoliveira/my_opencode/pull/446) - stuck session health diagnostics and doctor summary surfacing
- [#449](https://github.com/dmoliveira/my_opencode/pull/449) - structured-output parity for gating hooks
- [#451](https://github.com/dmoliveira/my_opencode/pull/451) - structured-output parity for non-gating hooks
- [#454](https://github.com/dmoliveira/my_opencode/pull/454) - delegated PR-readiness end-to-end regression

## Validation Evidence
- `npm --prefix plugin/gateway-core run lint`
- `python3 -m py_compile scripts/session_command.py scripts/doctor_command.py scripts/selftest.py`
- Custom `/session doctor --json` pass path with missing runtime DB returned `PASS`
- Custom `/session doctor --json` fail path with temp SQLite runtime DB returned `FAIL` with stuck findings for parent/child mismatch and stale running `question`
- Custom `/doctor run --json` path surfaced the session health problem summary
- `CI=true node --test plugin/gateway-core/test/delegated-pr-readiness.integration.test.mjs`
