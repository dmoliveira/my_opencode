# Release Notes Draft (2026-03-11) - Post v0.4.19 Rollup

This rollup reviews the merged PRs since the last tagged release, `v0.4.19`, without forcing a new version cut. The main themes are safer protected-worktree flows, broader validation and PR-readiness coverage, a larger hybrid LLM decision rollout across gateway hooks, and final release-automation fixes for docs publishing and CI.

## Highlights
- Worktree and protected-shell safety improved across inspection, restore, `apply_patch`, `gh api`, and post-merge flows.
- Validation evidence now covers more command shapes, shares evidence across guards and sessions, and adds delegated PR-readiness regression coverage.
- Hybrid LLM decision routing expanded across ambiguous gateway hooks, continuation cues, semantic checks, rollout evidence, and task-resume behavior.
- Orchestration reliability improved with stuck-session diagnostics, stronger hook wiring, structured-output parity, and more stable follow-up handling.
- Operator documentation and release automation were tightened with roadmap/playbook updates and a GitHub Pages/docs publishing fix.

## Milestone Sources
- `git range: v0.4.19..HEAD`
- `docs/plan/v0.4.20-flow-milestones-changelog.md`
- `gh pr list --state merged --search "merged:>=2026-03-07" --limit 80 --json number,title,mergedAt,mergeCommit,url`

## Included PRs
- #440 add hybrid LLM decision runtime for ambiguous gateway hooks
- #446 add stuck session health diagnostics
- #452 expand semantic LLM decision coverage
- #454 add delegated PR readiness integration test
- #459 fix CI and docs automation publishing
- #460 reconcile task resume LLM migration
- Guard and worktree safety: [#406](https://github.com/dmoliveira/my_opencode/pull/406), [#407](https://github.com/dmoliveira/my_opencode/pull/407), [#410](https://github.com/dmoliveira/my_opencode/pull/410), [#411](https://github.com/dmoliveira/my_opencode/pull/411), [#412](https://github.com/dmoliveira/my_opencode/pull/412), [#413](https://github.com/dmoliveira/my_opencode/pull/413), [#417](https://github.com/dmoliveira/my_opencode/pull/417), [#423](https://github.com/dmoliveira/my_opencode/pull/423), [#427](https://github.com/dmoliveira/my_opencode/pull/427), [#428](https://github.com/dmoliveira/my_opencode/pull/428), [#429](https://github.com/dmoliveira/my_opencode/pull/429), [#430](https://github.com/dmoliveira/my_opencode/pull/430), [#433](https://github.com/dmoliveira/my_opencode/pull/433), [#437](https://github.com/dmoliveira/my_opencode/pull/437), [#447](https://github.com/dmoliveira/my_opencode/pull/447), and [#459](https://github.com/dmoliveira/my_opencode/pull/459).
- Validation and readiness: [#409](https://github.com/dmoliveira/my_opencode/pull/409), [#415](https://github.com/dmoliveira/my_opencode/pull/415), [#420](https://github.com/dmoliveira/my_opencode/pull/420), [#421](https://github.com/dmoliveira/my_opencode/pull/421), [#422](https://github.com/dmoliveira/my_opencode/pull/422), [#431](https://github.com/dmoliveira/my_opencode/pull/431), [#434](https://github.com/dmoliveira/my_opencode/pull/434), [#435](https://github.com/dmoliveira/my_opencode/pull/435), [#436](https://github.com/dmoliveira/my_opencode/pull/436), and [#454](https://github.com/dmoliveira/my_opencode/pull/454).
- Docs and operator guidance: [#414](https://github.com/dmoliveira/my_opencode/pull/414), [#416](https://github.com/dmoliveira/my_opencode/pull/416), [#419](https://github.com/dmoliveira/my_opencode/pull/419), [#424](https://github.com/dmoliveira/my_opencode/pull/424), [#426](https://github.com/dmoliveira/my_opencode/pull/426), [#438](https://github.com/dmoliveira/my_opencode/pull/438), [#450](https://github.com/dmoliveira/my_opencode/pull/450), and [#458](https://github.com/dmoliveira/my_opencode/pull/458).
- Delegation observability and runtime state: [#418](https://github.com/dmoliveira/my_opencode/pull/418) and [#425](https://github.com/dmoliveira/my_opencode/pull/425).
- Hybrid LLM decisions and hook reliability: [#440](https://github.com/dmoliveira/my_opencode/pull/440), [#442](https://github.com/dmoliveira/my_opencode/pull/442), [#443](https://github.com/dmoliveira/my_opencode/pull/443), [#444](https://github.com/dmoliveira/my_opencode/pull/444), [#445](https://github.com/dmoliveira/my_opencode/pull/445), [#446](https://github.com/dmoliveira/my_opencode/pull/446), [#448](https://github.com/dmoliveira/my_opencode/pull/448), [#449](https://github.com/dmoliveira/my_opencode/pull/449), [#451](https://github.com/dmoliveira/my_opencode/pull/451), [#452](https://github.com/dmoliveira/my_opencode/pull/452), [#453](https://github.com/dmoliveira/my_opencode/pull/453), [#456](https://github.com/dmoliveira/my_opencode/pull/456), [#457](https://github.com/dmoliveira/my_opencode/pull/457), and [#460](https://github.com/dmoliveira/my_opencode/pull/460).

## Notable Callouts
- [#440](https://github.com/dmoliveira/my_opencode/pull/440) introduced the hybrid LLM decision runtime for ambiguous gateway hooks.
- [#446](https://github.com/dmoliveira/my_opencode/pull/446) added stuck-session health diagnostics for faster orchestration triage.
- [#452](https://github.com/dmoliveira/my_opencode/pull/452) expanded semantic LLM decision coverage across the gateway layer.
- [#454](https://github.com/dmoliveira/my_opencode/pull/454) added delegated PR-readiness integration coverage.
- [#459](https://github.com/dmoliveira/my_opencode/pull/459) fixed CI and docs automation publishing, including GitHub Pages bootstrap behavior.
- [#460](https://github.com/dmoliveira/my_opencode/pull/460) reconciled the task-resume LLM migration to keep the new runtime path stable.

## Validation Evidence
- `python3 scripts/release_train_command.py draft --include-milestones --head HEAD --json`
- `python3 scripts/release_note_validation_check.py`
- `python3 scripts/release_note_quality_check.py --json`
- `npm --prefix plugin/gateway-core run lint`
- `make validate`
