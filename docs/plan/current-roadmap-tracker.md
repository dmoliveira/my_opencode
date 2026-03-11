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

None for this wave right now. Most recent merges are `#406`, `#409`, and `#414`.

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

Status: done

Goal:
- auto-wire model-routing resolution into normal execution entrypoints without leaking transient routing metadata into persisted state

Delivered:
- entrypoint routing integration implemented
- response-level routing metadata added to relevant outputs
- persistence leakage prevented
- routing selftests expanded
- PR `#406` merged

Remaining:
- monitor for regressions as new command/runtime slices land

### E5 Selftest and Doctor Stabilization

Status: done

Goal:
- keep validation green as canonical-command and routing changes land

Delivered:
- fixed layered config discovery for post-session digest execution
- switched forced auto-slash execute coverage to a stable dispatch path
- corrected auto-slash precision accounting
- PR `#409` merged

Remaining:
- watch for unrelated selftest drift after future main-branch guard updates

### E6 Roadmap Memory and Handoff Tracking

Status: done

Goal:
- keep a durable roadmap note with epics, active work, and handoff-ready next tasks

Delivered:
- added tracker at `docs/plan/current-roadmap-tracker.md`
- PR `#414` merged

Remaining:
- keep this tracker updated at each milestone boundary

## Doing Now

| Item | Status | Notes |
|---|---|---|
| Post-merge guard behavior verification | doing | Validate protected-main behavior in real operator flows after `#423`. |
| Canonical guidance drift watch | doing | Keep active docs canonical-first as command/runtime surfaces evolve. |
| LLM decision hooks planning | doing | Active plan lives under `docs/plan/status/in_progress/llm-decision-hooks-plan.md`; current checkpoint includes refreshed rollout guidance, passing semantic/workflow scenario coverage, wired `todo-continuation-enforcer` fallback, and `delegation-fallback-orchestrator` as the next promotion candidate pending fresh disagreement evidence. |
| Post-merge parity backlog triage | doing | Active backlog lives in `docs/plan/post-merge-parity-backlog-2026-03-10.md`; use it to sequence remaining divergence decisions and any reopened parity slices. |

## Done Recently

| Item | Status | Notes |
|---|---|---|
| Reconstructed current initiative from git/OpenCode history | done | Reviewed reflog, prompt history, logs, and checkpoints. |
| Merged model routing entrypoint PR | done | `#406` merged after refresh-from-main and CI pass. |
| Merged selftest follow-up PR | done | `#409` merged after refresh-from-main and CI pass. |
| Orchestration reliability hardening wave documented | done | Fresh-session continuation summary now lives in `docs/plan/status/in_progress/orchestration-reliability-continuation-2026-03-10.md`, covering merged PRs `#442`, `#446`, `#449`, `#451`, and `#454`. |
| Merged roadmap tracker PR | done | `#414` merged after branch freshness refresh and CI pass. |
| Merged canonical docs guidance PR | done | `#419` merged after CI pass and branch refresh. |
| Merged workflow resume/runtime guard PR | done | `#420` merged after CI success. |
| Merged E2/E3 guard hardening slice | done | `#423` merged with chained protected-command parsing and branch-freshness fallback guidance updates. |
| Final canonical active-doc sweep complete | done | Active operator docs now keep compatibility aliases explicitly secondary. |
| Synced local `main` while preserving local docs edit | done | Used targeted stash + `git pull --rebase` + stash pop for `docs/plan/docs-automation-summary.md`. |
| Reviewed parity plan against upstream runtime behavior | done | Identified crossed hook LLM bindings, missing safe hook creation, and remaining intentional divergence around Atlas runtime injection and Claude compatibility hooks. |
| Committed parity hardening gateway fixes | done | Created `55ad23f` to fix LLM hook bindings, add safe hook startup isolation, and refresh parity tracking evidence. |
| Committed Atlas post-task reminder prototype | done | Created `fa270cf` to add local verification/reminder shaping for delegated task results. |
| Committed Atlas pre-task shaping prototype | done | Created `d090f80` to prepend delegated task focus guidance before subagent execution. |
| Merged parity hardening and atlas shaping PR | done | `#443` merged to `main`, including E2E gateway hook-failure hardening in `b9a7f05`. |
| Normalized parity tracker after merge | done | Replaced merged parity execution slices with a single post-merge backlog triage stream and moved remaining decisions into `docs/plan/post-merge-parity-backlog-2026-03-10.md`. |

## Next Tasks

1. Continue post-merge verification for protected-main guard behavior in real operator flows.
2. Monitor branch-freshness guard fallbacks in live PR merge/update workflows.
3. Keep active docs canonical-first as new command/runtime slices land.
4. Land the `task-resume-info` semantic migration through the centralized LLM runtime with shadow-first rollout.
5. Land the `mistake-ledger` semantic deferral migration with audit assertions and shadow-first rollout.
6. Accumulate a fresh live disagreement window, then rerun rollout reporting before promoting `delegation-fallback-orchestrator`; keep `todo-continuation-enforcer` and `validation-evidence-ledger` in shadow until then.
7. Expand the semantic decision inventory so every ambiguous classification path is tracked by `done` / `doing` / `pending` status band.
8. Keep this tracker and the CLI todo list synchronized at each task handoff.

## Handoff Notes

- Before starting new implementation, re-check that local `main` matches the latest remote `main`.
- Use a dedicated worktree for each new slice, even for docs/tracking follow-ups when practical.
- Keep the CLI todo list and this tracker aligned: epics here, active steps in the runtime todo list.
