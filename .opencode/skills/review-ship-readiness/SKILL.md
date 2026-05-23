---
name: review-ship-readiness
description: Use when blocker-first review, ship readiness, validation evidence, or final release confidence is needed before merge or delivery.
---

## Goal
Decide whether a slice is ship-ready and surface only the highest-value blockers or follow-ups.

## Use When
- the user asks for a review before merge or release
- the task needs a blocker-first quality pass
- validation evidence needs a final readout
- ship-ready vs follow-up status is unclear

## Do Not Use When
- the work is still in early exploration or planning
- implementation has not reached a validation gate yet
- the request is pure UX concepting or browser execution

## First Steps
- Inspect the current diff and validation evidence.
- Check whether required gates already ran on the current diff.
- Verify whether any blocker remains before calling the slice done.

## Working Rules
- Prioritize blockers, regressions, and merge risks before polish.
- Distinguish blocker, non-blocker, and future-follow-up clearly.
- Review the current diff and latest validation state together.
- Do not ask for broader changes when the slice already meets its stated goal.
- Prefer a short ship/no-ship conclusion with evidence.

## Evidence / Done
- Ship-ready or blocked status is explicit.
- Blocker findings, if any, are concrete and scoped.
- Latest validation state is reflected accurately.
- Follow-up items are separated from merge blockers.

## References
- `AGENTS.md`
- `docs/validation-policy.md`
- `docs/orchestration-advanced.md`
- `docs/github-cli.md`
