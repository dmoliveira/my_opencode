# Release Milestone Automation Runbook

Use this runbook to create milestone changelog docs, generate release-note drafts, and publish docs-first milestone releases in a consistent way.

## Scope

This runbook targets release-documentation milestones where code is already merged and the release slice mainly packages prior PRs.

## Inputs

- target milestone release version (for example `v0.4.5`)
- release date in `YYYY-MM-DD`
- set of milestone PRs that should be included
- prior milestone changelog files under `docs/plan/`

## Canonical Workflow

1) Create milestone changelog document

- Add `docs/plan/vX.Y.Z-flow-milestones-changelog.md`
- Include a timeline table with: milestone, scope, PR link, merged timestamp, merge commit
- Source merge metadata from `gh pr view <number> --json number,title,mergedAt,mergeCommit,url`

- Refresh v0.4 index after adding milestone docs:

```bash
python3 scripts/update_release_index.py
```

2) Generate release-notes draft from milestone sources

- Use `/release-train rollup` via script:

```bash
python3 scripts/release_train_command.py rollup \
  --title "Release Notes Draft (YYYY-MM-DD) - vX-Y-Z" \
  --milestone docs/plan/vX.Y.Z-flow-milestones-changelog.md \
  --write docs/plan/release-notes-YYYY-MM-DD-vX-Y-Z.md
```

- Ensure `## Milestone Sources`, `## Included PRs`, and `## Validation Evidence` sections are present.

3) Run validation gates before publishing docs

```bash
make validate
make selftest
make install-test
pre-commit run --all-files
```

4) Open small PR for release docs

- Branch naming: `feat/vX-Y-Z-release-docs`
- Keep diff scoped to release changelog and release-notes docs
- Merge only after CI checks are green

5) Publish release tag and notes

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes-file docs/plan/release-notes-YYYY-MM-DD-vX-Y-Z.md
```

6) Optional release-train dry-run verification (no publish side effects)

```bash
python3 scripts/release_train_command.py publish \
  --version X.Y.Z \
  --create-tag \
  --create-release \
  --notes-file docs/plan/release-notes-YYYY-MM-DD-vX-Y-Z.md \
  --allowed-branch-re ".*" \
  --dry-run \
  --json
```

- This check is useful for validating deterministic reason codes and publish planning behavior.
- For docs-only release repackaging where changelog/version gates are intentionally not advanced, `gh release create` remains the canonical publish path.

## Lightweight Checklist (Docs-Only Milestones)

- milestone changelog file added and reviewed
- release-notes draft generated from milestone sources
- full validation gates passed (`validate`, `selftest`, `install-test`, `pre-commit`)
- docs PR merged to `main`
- release tag published with release-notes file
- local `main` synced and clean after publish

## v0.4.x Cadence Examples

- `v0.4.2`: `docs/plan/v0.4.2-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-2.md`
- `v0.4.3`: `docs/plan/v0.4.3-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-3.md`
- `v0.4.4`: `docs/plan/v0.4.4-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-4.md`
- `v0.4.5`: `docs/plan/v0.4.5-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-5.md`
- `v0.4.6`: `docs/plan/v0.4.6-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-6.md`
- `v0.4.7`: `docs/plan/v0.4.7-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-7.md`
- `v0.4.8`: `docs/plan/v0.4.8-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-8.md`
- `v0.4.9`: `docs/plan/v0.4.9-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-9.md`
- `v0.4.10`: `docs/plan/v0.4.10-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-10.md`
- `v0.4.11`: `docs/plan/v0.4.11-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-11.md`
- `v0.4.12`: `docs/plan/v0.4.12-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-12.md`
- `v0.4.13`: `docs/plan/v0.4.13-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-13.md`
- `v0.4.14`: `docs/plan/v0.4.14-flow-milestones-changelog.md` + `docs/plan/release-notes-2026-03-01-v0-4-14.md`

Reference index for all v0.4.x milestones: `docs/plan/v0.4-release-index.md`.

Example dry-run verification evidence: `docs/plan/release-train-dry-run-verification-2026-03-01.md`.

These examples model the expected flow: consolidate merged PR milestones first, then generate release notes, validate, merge docs PR, and publish the milestone tag.
