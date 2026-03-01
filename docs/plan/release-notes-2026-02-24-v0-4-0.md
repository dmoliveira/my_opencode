# Release Notes Draft (2026-02-24) - v0.4.0

## Summary

- Finalized the flow-automation milestone wave with v1.0 and v1.1 tracked upgrades.
- Expanded command-level operational safety and continuity workflows for hotfix, ship, review, changes, and doctor paths.
- Kept command-doc parity and deterministic selftest coverage in lockstep for each flow addition.

## Included Pull Requests

- [#315](https://github.com/dmoliveira/my_opencode/pull/315) - harden flow intents and standardize reason codes
- [#316](https://github.com/dmoliveira/my_opencode/pull/316) - add flow follow-up commands and exports

## Highlights

- Hotfix flow: stricter close gates plus postmortem template output with explicit incident linkbacks.
- Ship flow: release preflight + PR scaffolding + guarded `create-pr` confirmation path.
- Review flow: checklist generation now supports artifact writes via `--write <path>`.
- Doctor flow: reason-code registry export via `/doctor reason-codes --json`.

## Validation Evidence

- `make validate`
- `make selftest`
- `make install-test`
- `pre-commit run --all-files`

## Milestone Sources

- `docs/plan/v0.4.0-flow-milestones-changelog.md`
- `docs/plan/v1.0-claude-flow-plus-plan.md`
- `docs/plan/v1.1-flow-followups-plan.md`
