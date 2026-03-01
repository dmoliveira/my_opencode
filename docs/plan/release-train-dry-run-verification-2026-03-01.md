# Release-Train Dry-Run Verification (2026-03-01)

This note captures a publish dry-run verification after the v0.4.6 milestone release.

## Command

```bash
python3 scripts/release_train_command.py publish \
  --version 0.4.6 \
  --create-tag \
  --create-release \
  --notes-file docs/plan/release-notes-2026-03-01-v0-4-6.md \
  --allowed-branch-re ".*" \
  --dry-run \
  --json
```

## Result

- `result`: `FAIL`
- `reason_codes`:
  - `changelog_missing_version`
  - `publish_tag_already_exists`
  - `version_mismatch_breaking_change`
  - `version_not_incremented`
- `summary_schema_version`: `1.0`

## Interpretation

- The dry-run path correctly returns deterministic guardrail reason codes.
- For docs-only milestone repackaging, direct `gh release create ... --notes-file ...` remains the canonical path.
- `release-train publish` is best used when version/changelog policy gates are intentionally satisfied for a new release increment.
