# Release Notes Draft (2026-03-10) - v0.4.20

## Milestone Sources
- `docs/plan/v0.4.20-flow-milestones-changelog.md`

## Included PRs
- Pending PR from `fix/stuck-session-health` covering commits `27d6faf` and `9a0b2a1`

## Validation Evidence
- `python3 -m py_compile scripts/session_command.py scripts/doctor_command.py scripts/selftest.py`
- Custom `/session doctor --json` pass path with missing runtime DB returned `PASS`
- Custom `/session doctor --json` fail path with temp SQLite runtime DB returned `FAIL` with stuck findings for parent/child mismatch and stale running `question`
- Custom `/doctor run --json` path surfaced the session health problem summary
