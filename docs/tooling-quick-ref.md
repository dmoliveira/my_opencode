# Tooling Quick Reference

Use this as a fast productivity map for repo-native tooling.

This repo-local quick ref exists because `AGENTS.md` points to `docs/tooling-quick-ref.md` as a startup reference. It keeps the local command surface discoverable even when the sibling `agents_md` repo is not loaded.

## Core references

- `docs/index.md`
- `docs/codememory-workflow.md`
- `docs/codememory-conventions.md`
- `docs/github-cli.md`
- `docs/validation-policy.md`
- `docs/iterative-testing-workflow.md`
- `docs/concise-communication-workflow.md`
- `docs/orchestration-advanced.md`

## Canonical instruction file

- Repo-root `AGENTS.md` is the source of truth.
- Runtime mirrors such as `my_opencode/AGENTS.md` should resolve to the repo-root file via symlink.

## High-value commands in this repo

- `make help`: list available targets
- `make validate`: validate scripts and JSON config
- `make selftest`: run deterministic command self-tests
- `make install-test`: run installer smoke test in a temp `HOME`
- `make doctor` / `make doctor-json`: runtime/plugin diagnostics
- `make gateway-status` / `make gateway-doctor`: gateway plugin status and diagnostics
- `make devtools-status`: external productivity tooling status
- `make release-check`: verify release prerequisites

## Codememory fast path

- `oc current`
- `oc next --scope dmoliveira/my_opencode --limit 5`
- `oc queue --scope dmoliveira/my_opencode --limit 10`
- `oc resume --scope dmoliveira/my_opencode --task <task_id>`
- `oc add task "<title>" ...`
- `oc add session "<title>" --task <task_id> --worktree . --branch <branch> ...`
- `oc report improvement "<title>" --body "<context>" ...`

## Git and GitHub fast path

- `git fetch --all --prune --quiet`
- `git status --short --branch`
- `gh pr status --json currentBranch,createdBy,mergeStateStatus`
- `gh issue list --state open --limit 20 --json number,title,state,url`
- `gh repo view --json name,defaultBranchRef`

## Search and doc review helpers

- `rg -n "pattern" docs -g "*.md"`
- `fd -e md docs`
- `git --no-pager diff --stat`
- `git --no-pager diff --check`

## Local execution defaults

- Prefer JSON or machine-readable output first when a command supports it.
- Prefer worktree branches over editing the protected main project folder.
- Keep shell commands non-interactive and CI-safe.
- Use the smallest validation bundle that matches the active slice.
