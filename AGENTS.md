# AGENTS.md

## Orchestration quickplay

- Start every implementation task in a dedicated git worktree branch.
- Keep the primary project folder on `main`; use it for sync and inspection only.
- Never `git checkout` or `git switch` the primary project folder onto a task branch.
- If you need parallel work, create additional linked worktrees instead of branching in place.
- For related policy/playbook docs from `agents.md`, prefer a local clone first and use public links only when you need canonical shareable references.

### wt flow

WT execution checklist (use in every run)

1. Confirm the primary project folder is on `main` and not the task branch.
2. Create a dedicated worktree branch from the current root branch before editing files.
3. Run implementation, validation, and review steps from the task worktree.
4. Merge with branch deletion, then sync the primary project folder while it remains on `main`.
5. Remove task worktrees after merge.

### Memory-aware orchestration (default)

Pressure mode matrix (deterministic defaults)

- `LOW`: proceed normally, keep one active implementation track.
- `HIGH`: reduce fan-out, prefer one writer, and finish the current slice before expanding scope.
- `CRITICAL`: stop new implementation, capture blocker evidence, and recover to a smaller safe step.

Print `<CONTINUE-LOOP>` as the final line only when at least one task is still pending after the current cycle.
