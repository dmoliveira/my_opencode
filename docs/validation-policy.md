# Validation Policy

Use validation at key gates so iteration stays fast without skipping quality checks.

This repo-local copy exists because `AGENTS.md`, `README.md`, and quickstart/operator docs point to `docs/validation-policy.md` as an expected local reference during active work. For shareable/canonical policy docs, the sibling `../agents_md/docs/validation-policy.md` file and public `agents.md` repo remain the upstream source.

## Gate policy

- Validation definition gate: before non-trivial implementation, name the checks that prove the slice is done.
- Start gate: fetch/check the remote before implementation so the task still matches the latest branch and PR state.
- During implementation: run quick smoke checks only when they reduce risk or unblock debugging.
- Pre-PR gate: run the selected validation set once on the full current diff.
- Pre-merge gate: re-run validation only if code changed after review or CI reported failures.
- Final remote check: compare with latest `main` and overlapping PRs right before merge.

Validation definition should stay compact but explicit. Name only the checks that matter for the slice: docs validation, lint/unit/integration tests, UX smoke path, frontend/backend behavior, sandbox/live-state run, or a targeted debug harness.

## Risk matrix

- Docs-only: run `git diff --check`; add `make validate` when docs link into generated/config-driven surfaces.
- Low-risk code: run targeted lint/test for the touched area plus one smoke path.
- Iterative or stateful flows: prefer a live smoke path against the running state when that is where failures surface.
- High-risk/runtime/security/migration: run the full required lint/test/build suite.

## Review budget

- Low risk: 1 review/fix pass.
- Medium risk: 2 review/fix passes.
- High risk: 3-5 review/fix passes.

## Fast path

- Use for docs-only or low-blast-radius changes.
- Keep the validation definition to one short statement.
- Run one required validation pass at the pre-PR gate.
- Re-run validation only if the diff changes after review.

## Typical validation bundle in this repo

Choose the smallest set that matches the slice. Common gates referenced across local docs:

```bash
git diff --check
make validate
make selftest
make install-test
npm --prefix plugin/gateway-core run lint
pre-commit run --all-files
```

For current wave/release closure expectations, see `docs/plan/wave-closure-checklist-template.md`.
