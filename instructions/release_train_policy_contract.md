# Release Train Policy Contract (Epic 24 Task 24.1)

This contract defines deterministic gating rules for `/release-train` so releases are blocked when required evidence is missing.

## Goals

- Enforce repeatable release preconditions before tagging or publishing.
- Keep release decisions auditable with explicit reason codes.
- Provide safe rollback guidance when publish steps partially fail.

## Required Preconditions

All preconditions must pass before `prepare` can return `ready=true`.

1. Workspace integrity
   - Git tree is clean (`git status --porcelain` has no output).
   - Current branch is `main` or an explicitly allowed release branch pattern.
   - Local branch is not behind the tracked remote.
2. Validation evidence
   - Latest `make validate` status is pass.
   - Latest `make selftest` status is pass.
   - Latest `make install-test` status is pass.
3. Release documentation evidence
   - `CHANGELOG.md` contains an entry for the target version.
   - Changelog section includes at least one non-empty bullet in Adds/Changes/Fixes/Removals.
   - README references any newly added top-level release command aliases.
4. Issue lifecycle evidence
   - No open `br` issue labeled as release-blocking.
   - Current release task issue is in `in_progress` or `done` state.

## Semantic Version Rules

Target version must follow `MAJOR.MINOR.PATCH` with no leading zeroes.

- `PATCH` bump: bug fixes, docs, tests, and non-breaking internal improvements.
- `MINOR` bump: backwards-compatible feature additions or command-surface expansion.
- `MAJOR` bump: breaking configuration/schema/CLI behavior changes.

Deterministic checks:

- Reject target versions that are not greater than the latest git tag.
- Reject skips larger than one patch/minor step unless `--allow-version-jump` is provided.
- Require explicit `--breaking-change` flag for major bumps.
- If changelog text includes "breaking" markers and target is not major, block with `reason_code=version_mismatch_breaking_change`.

## Command Contract

`/release-train` subcommands must emit JSON-compatible reason codes for automation.

- `status`
  - Returns current preflight summary and latest evidence timestamps.
- `prepare`
  - Evaluates all preconditions and version rules.
  - Outputs `ready`, `reason_codes`, and actionable remediation.
- `draft`
  - Generates release-note draft from merged changes since previous tag.
  - Never mutates tags or publishes artifacts.
- `publish`
  - Requires `ready=true` and explicit operator confirmation.
  - Must support `--dry-run` mode that exercises all checks without side effects.

## Rollback Strategy for Partial Failures

Rollback behavior is determined by the highest completed publish stage.

1. Pre-tag failure
   - No rollback required; return `reason_code=publish_pre_tag_failure`.
2. Tag created, publish not completed
   - Delete local and remote tag if allowed.
   - Record rollback action with `reason_code=rollback_tag_deleted`.
3. Publish completed but post-publish steps failed
   - Keep published artifact and tag.
   - Emit `reason_code=post_publish_followup_required` and generate follow-up checklist.

Required rollback output fields:

- `publish_stage`
- `rollback_actions`
- `manual_followups`
- `reason_codes`

## Failure Reason Codes

Minimum reason-code set:

- `dirty_worktree`
- `branch_not_allowed`
- `branch_behind_remote`
- `validate_failed`
- `selftest_failed`
- `install_test_failed`
- `changelog_missing_version`
- `changelog_missing_sections`
- `version_not_incremented`
- `version_jump_requires_override`
- `major_requires_breaking_flag`
- `version_mismatch_breaking_change`
- `publish_pre_tag_failure`
- `rollback_tag_deleted`
- `post_publish_followup_required`

All blocking outcomes must include at least one reason code and one remediation hint.
