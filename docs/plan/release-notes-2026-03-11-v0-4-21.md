# Release Notes Draft (2026-03-11) - v0.4.21

## Milestone Sources
- `docs/plan/v0.4.21-flow-milestones-changelog.md`

## Included PRs
- #450
- #452
- #453
- #456
- #457
- #458
- #459
- #460

## Validation Evidence
- `python3 scripts/release_train_command.py draft --include-milestones --head HEAD --json`
- `python3 scripts/release_note_validation_check.py`
- `python3 scripts/release_note_quality_check.py --json --note docs/plan/release-notes-2026-03-11-v0-4-21.md`
- `npm --prefix plugin/gateway-core run lint`
- `make validate`
