---
name: worktree-delivery-pr
description: Use when worktree setup, branch freshness, push, PR creation, checks, merge, or cleanup flow is needed for end-to-end delivery.
---

## Goal
Run the smallest safe worktree-to-PR delivery flow with clear validation and cleanup.

## Use When
- the user wants end-to-end delivery
- a new task needs a dedicated worktree branch
- the task includes push, PR, checks, merge, or cleanup work
- branch freshness or PR guardrails are part of the work

## Do Not Use When
- the task is planning-only
- a narrow file edit is all that is needed and delivery is out of scope
- protected `main` inspection alone answers the question

## First Steps
- `git fetch --all --prune --quiet`
- create a dedicated worktree branch from current `origin/main`
- attach a Codememory task and session to that worktree
- check open PR state before creating a new PR

## Working Rules
- Keep `main` as sync/merge only; do implementation in the task worktree.
- Validate the current diff before commit, then keep commit and push separate.
- Re-check branch freshness before PR create or merge.
- Prefer automation-safe `gh` usage and structured status output.
- After merge, delete the task worktree and sync local `main`.

## Evidence / Done
- worktree branch and Codememory session are explicit
- validation for the delivered diff is recorded
- PR URL, checks state, and merge outcome are captured
- merged worktree cleanup and local `main` sync are complete

## References
- `AGENTS.md`
- `docs/github-cli.md`
- `docs/validation-policy.md`
- `docs/parallel-wt-playbook.md`
- `docs/orchestration-advanced.md`
