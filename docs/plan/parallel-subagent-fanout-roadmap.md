# Parallel Subagent Fan-Out Roadmap

This file is the main execution list for parallel subagent fan-out reliability and efficiency work.

## How To Use This File

- Status buckets:
  - `todo`: not started
  - `doing`: active now
  - `done`: implemented, merged, and validated by the scenario gate listed here
  - `watch`: shipped, but still worth monitoring in live use
- Only mark an item `done` after the matching validation scenario has been rerun successfully.
- Keep the primary project folder on `main` for sync/inspection/setup only; do all implementation in linked worktrees.

## Goal

Allow efficient same-session parallel subagent execution without false blocking, while keeping protected `main` safe and linked worktrees flexible.

## Current Conclusion

- Core same-session parallel fan-out now works in live repros for mixed and same-type subagents.
- The biggest real defects were not the fan-out idea itself, but delegation identity loss, ambiguous trace-less cleanup, and guard scope being evaluated against the wrong directory.
- The main remaining risk is edge-case event-shape ambiguity when completion events arrive without stable delegation identity.

## Assumptions

- Parent session ids are shared across multiple delegated subagent runs.
- Parallelism is expected within one parent session when delegations are meaningfully distinct.
- The primary project folder on protected `main` should stay restricted.
- Linked worktrees are the correct place for normal mutations, even when the parent session started on `main`.
- Safety beats eager cleanup when lifecycle completion is ambiguous.

## Direction

- Prefer stable structured delegation identity over prompt/output parsing.
- Scope lifecycle/concurrency cleanup per delegation, not per parent session.
- Evaluate guards against the actual tool target (`workdir`, `cwd`, target file path), not just session root.
- Keep protected-`main` restrictions focused on the primary worktree, not linked worktrees.
- Keep scenario-based verification attached to each delivered improvement.

## Source Trail

- PR `#404` - `harden parallel delegation cleanup`
- PR `#408` - `fix live parallel delegation trace recovery`
- PR `#410` - `quiet ambiguous delegation warnings`
- PR `#411` - `allow env-prefixed protected inspection`
- PR `#412` - `allow safe main worktree setup commands`
- PR `#413` - `fix guard targeting for linked worktrees`

## Scenario Gate

Use these scenarios before marking related items `done`.

- `S1`: mixed same-session fan-out succeeds (`explore` + `strategic-planner`)
- `S2`: same-type same-session fan-out succeeds (`explore` + `explore`)
- `S3`: follow-up delegation after a parallel wave succeeds without false blocking
- `S4`: protected `main` still allows safe inspection/sync/setup commands
- `S5`: primary-`main` session targeting a linked worktree can mutate in the linked worktree
- `S6`: protected `main` session targeting a linked worktree is not falsely blocked by branch/worktree guards
- `S7`: ambiguous completion paths stay safe and non-destructive

## Epic Dashboard

| Epic | Status | Goal | Validation Gate |
|---|---|---|---|
| E1 Delegation Identity | done | Preserve stable per-delegation identity through `task` lifecycle events | S1, S2, S3 |
| E2 Safe Cleanup + Retry State | done | Avoid wrong reservation/lifecycle cleanup under ambiguity | S2, S3, S7 |
| E3 Warning Noise Reduction | done | Remove confusing user-facing ambiguity text while keeping audits | S3, S7 |
| E4 Protected Main Inspection + Setup Policy | done | Allow safe inspection/sync/setup commands on protected `main` | S4 |
| E5 Effective Target Guarding | done | Enforce restrictions on the real target worktree/path, not session root fallback | S5, S6 |
| E6 Parallel Efficiency Follow-Ups | doing | Reduce residual fallback logic and improve throughput/observability | future S1-S7 reruns |

## Epics And Tasks

### E1 Delegation Identity

Status: `done`

- [x] Propagate delegation trace and metadata through gateway-managed task payloads
- [x] Recover trace/subagent/category from structured metadata before parsing text fallbacks
- [x] Track runtime state per delegation instead of per session only
- [x] Validate live mixed and same-type same-session fan-out (`S1`, `S2`)

Notes:

- Delivered mainly in PR `#408`.

### E2 Safe Cleanup + Retry State

Status: `done`

- [x] Prevent ambiguous trace-less `after` events from clearing the wrong running/reserved entry
- [x] Prune stale reservations safely instead of falsely blocking future work forever
- [x] Keep lifecycle failure state tied to the correct delegation key
- [x] Validate follow-up delegation behavior and ambiguity safety (`S3`, `S7`)

Notes:

- Delivered across PR `#404` and PR `#408`.

### E3 Warning Noise Reduction

Status: `done`

- [x] Remove user-visible ambiguous completion warning text from successful flows
- [x] Keep internal audit evidence for ambiguous cleanup skip events
- [x] Validate successful delegations no longer rely on noisy warning output (`S3`, `S7`)

Notes:

- Delivered in PR `#410`.

### E4 Protected Main Inspection + Setup Policy

Status: `done`

- [x] Allow `git --no-pager ...` inspection commands on protected `main`
- [x] Allow env-prefixed protected inspection commands used by automation wrappers
- [x] Allow safe setup/recovery commands on protected `main`:
  - `git worktree add ...`
  - `git stash push ...`
  - `git stash pop`
  - `git stash list`
  - `git stash show ...`
- [x] Keep mutation commands blocked on protected `main`
- [x] Validate protected-main command surface (`S4`)

Notes:

- Delivered in PR `#411` and PR `#412`.

### E5 Effective Target Guarding

Status: `done`

- [x] Resolve guard scope from actual `workdir` / `cwd`
- [x] Resolve guard scope from actual target file path
- [x] Support absolute and relative linked-worktree target paths
- [x] Keep primary-worktree restrictions applied only to the actual primary worktree
- [x] Keep linked-worktree mutations allowed when the actual target is linked
- [x] Align docs with the enforced policy
- [x] Validate main-session to linked-worktree scenarios (`S5`, `S6`)

Notes:

- Delivered in PR `#413`.

### E6 Parallel Efficiency Follow-Ups

Status: `doing`

- [ ] Replace remaining prompt/output parsing fallbacks with mandatory structured delegation ids
- [ ] Add a distinct child run id separate from parent session id for every subagent run
- [ ] Require structured completion payloads for `task` `after` events (`traceId`, `subagentType`, result status)
- [x] Add runtime stress/e2e coverage for 3-5 concurrent subagents with varied completion order
- [ ] Add observability counters for fallback matches, ambiguous cleanup skips, and stale prunes
- [ ] Re-check whether any other guard still uses session-root fallback instead of effective target resolution
- [ ] Only mark this epic `done` after future reruns of S1-S7 pass under stress conditions

## Doing Now

- Active slice: structured child delegation run id via task metadata, with trace/output parsing fallbacks still kept as backup until scenario reruns pass.
- Current focus: expand runtime stress coverage for 3-5 same-session subagents and use the results to expose any remaining false-blocking edges.

## Watch List

- `watch`: completion events with missing trace, missing metadata, and no parsable structured hint can still fall back to ambiguity-safe behavior instead of exact cleanup.
- `watch`: fresh worktrees still need dependencies bootstrapped before local validation.

## Exit Criteria For This Roadmap

Consider this track stable when all are true:

- `E1` through `E5` remain green in repeated live use
- `E6` has a concrete structured-id follow-up plan underway or delivered
- stress reruns show no false parallel blocking in same-session fan-out
- protected `main` remains safe while linked worktrees stay flexible
