# Current Roadmap Tracker

Tracks the active `my_opencode` improvement wave so any AI can recover context quickly.

## Working Rules

- Keep the primary repo on `main`.
- Start each new implementation task in a dedicated worktree branch from the latest `main`.
- Treat canonical commands as the source of truth; do not reintroduce legacy aliases without a clear migration reason.
- When a workflow is changed, align docs, health checks, and selftests in the same slice.

## Status Legend

- pending
- doing
- done
- blocked

## Active PRs

| PR | Title | Status | Notes |
|---|---|---|---|
| `#406` | `auto-wire model routing into entrypoints` | doing | Entry-point routing work is implemented and under review. |
| `#409` | `fix selftest command dispatch coverage` | doing | Follow-up validation fix separated from `#406`. |

## Current Epics

### E1 Canonical Command Unification

Status: doing

Goal:
- converge overlapping slash-command behavior into a single canonical surface that docs, `/doctor`, and selftests all share

Delivered:
- simplified slash-command surface
- reduced routing/quality command overlap
- merged policy and keyword controls into canonical commands
- aligned doctor checks with canonical command paths
- restored canonical plan-flow command
- refreshed canonical workflow docs and operator guidance

Remaining:
- review for any lingering duplicate surfaces or outdated docs references
- keep future features on canonical commands only

### E2 Worktree-First Runtime Enforcement

Status: doing

Goal:
- stop agents from editing the primary `main` worktree and reinforce full worktree lifecycle behavior

Delivered:
- main/worktree guard work landed in earlier slices
- current operator guidance now assumes worktree-first execution

Remaining:
- keep validating that runtime guards still push agents into the right worktree flow
- document any edge cases discovered during real sessions

### E3 Continuation and Parallel Orchestration Hardening

Status: doing

Goal:
- improve continuation reliability, subagent routing, and parallel execution discipline

Delivered:
- continuation enforcement and reminder hooks were added in prior waves
- delegation/routing/runtime guidance was strengthened

Remaining:
- continue reviewing where agents still stop too early or fail to parallelize safe work
- keep model/effort routing aligned with task class

### E4 Model Routing Integration

Status: doing

Goal:
- auto-wire model-routing resolution into normal execution entrypoints without leaking transient routing metadata into persisted state

Delivered:
- entrypoint routing integration implemented
- response-level routing metadata added to relevant outputs
- persistence leakage prevented
- routing selftests expanded
- PR `#406` opened

Remaining:
- finish PR review/fix cycle for `#406`
- verify any merge follow-ups after review comments

### E5 Selftest and Doctor Stabilization

Status: doing

Goal:
- keep validation green as canonical-command and routing changes land

Delivered:
- fixed layered config discovery for post-session digest execution
- switched forced auto-slash execute coverage to a stable dispatch path
- corrected auto-slash precision accounting
- full `python3 scripts/selftest.py` passed
- PR `#409` opened

Remaining:
- monitor for any additional unrelated regressions uncovered by branch review/merge

## Doing Now

| Item | Status | Notes |
|---|---|---|
| Review and merge `#406` | doing | Main routing work is implemented; next step is review/fix/merge cycle. |
| Review and merge `#409` | doing | Small follow-up PR to keep selftest fixes isolated. |
| Preserve project memory in tracker docs | doing | This file is the live handoff anchor for the current wave. |

## Done Recently

| Item | Status | Notes |
|---|---|---|
| Reconstructed current initiative from git/OpenCode history | done | Reviewed reflog, prompt history, logs, and checkpoints. |
| Opened routing PR | done | `#406` covers entrypoint routing integration. |
| Opened selftest follow-up PR | done | `#409` covers post-session + auto-slash validation fixes. |

## Next Tasks

1. Review PR `#406` comments/checks, fix anything needed in a fresh worktree from latest `main`, and merge when green.
2. Review PR `#409`, merge when green, then sync local `main` again.
3. Re-scan docs and command handbook references for any non-canonical command guidance that still remains.
4. Continue the next orchestration/runtime hardening slice only after both current PRs are settled.

## Handoff Notes

- Before starting new implementation, re-check that local `main` matches the latest remote `main`.
- Use a dedicated worktree for each new slice, even for docs/tracking follow-ups when practical.
- Keep the CLI todo list and this tracker aligned: epics here, active steps in the runtime todo list.
