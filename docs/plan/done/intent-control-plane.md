---
status: done
priority: high
updated: 2026-11-03
---

# Intent Control Plane Roadmap

Codememory epic: `epic_24`
All planned slices are delivered, including rolling decomposition qualification (`task_130`) and proposal-only intake planner (`task_127`). Production protocol `task_122` merged in [PR #754](https://github.com/dmoliveira/my_opencode/pull/754).

## Outcome

Capture user intent and agent discoveries naturally, reconcile them against
existing Codememory state, and execute a durable dependency graph without
requiring the primary agent to remember every tracking command.

## Sequence

| Task | Status | Dependency | Outcome |
| --- | --- | --- | --- |
| `task_123` Intent graph authority contract | done | none | Versioned proposal, authority, privacy, and replay contract |
| `task_124` Manual intent coordinator MVP | done | `task_123` | Fresh add-only dry-run and idempotent transactional apply |
| `task_125` Task graph projection | done | `task_124` | One-way Codememory projection and drift detection |
| `task_126` Durable intent ingress | done | `task_124` | Private bounded local hook outbox and deterministic replay contract |
| `task_127` Proposal-only planner | done | `task_126`, `task_122` | Bounded read-only research and typed proposals |
| `task_128` Fenced task leases | done | none | Atomic claim, heartbeat, expiry, and fencing |
| `task_129` Lease-backed background execution | done | `task_128`, `task_125` | Recoverable bounded task workers |
| `task_130` Rolling decomposition qualification | done | `task_127`, `task_129` | Coverage and recovery at 50, 250, and 1000 tasks |

`task_122` is owned by the Tasker hardening epic and is complete. PR #754
superseded the isolated proposals in PRs #708 and #709; both drafts are closed.
The manual coordinator remains the only intent-proposal graph writer.

## Latest Slice

1. Preserve full hierarchical requirement coverage at 50, 250 and 1000 task
   records using bounded planner/coordinator fragments, independent coverage
   inventory and authoritative task/epic/link readback.
2. Expose bounded read-only frontier advice while retaining native task/session,
   lease and background admission authority for actual execution.
3. Qualify duplicate/replay rejection, lost replies, checkpoint reload and separate
   live-owner versus dead-owner reservation recovery.
4. Gate local model latency and calibrated native CLI operation costs; execute
   two real lease-backed commands at every native scale and defer excess work.

Depth: medium. Risk: medium. Plan critique required a connected native execution
smoke and separate hierarchy oracle; both are included. See
`docs/rolling-decomposition-qualification.md` for measured evidence and limits.

## Safety Boundaries

- The projector performs bounded read-only `oc list|get` calls and never mutates
  Codememory.
- One Codememory scope owns each projection; changing scope fails closed.
- Only projection apply may change managed task semantics.
- Autonomous task dispatch requires the fenced lease and background execution
  contracts delivered by `task_128` and `task_129`.
- Unmanaged workflow nodes remain local execution state, not Codememory tasks.
- No raw user prompt is persisted by default.
- No more than ten combined records and links per MVP proposal.
- Any collision or unresolved item aborts the complete proposal.
- Existing-record reuse and updates are deferred until Codememory offers a
  transactional upsert or expected-revision delta API.

## Validation

- `git diff --check`
- targeted rolling coverage, frontier, checkpoint and process reservation/recovery tests
- complete isolated native 50/250/1000 intake/readback/frontier/execution qualification
- `make validate`
- Ruff and configured pre-commit
- two changed-diff review/fix passes; no repeat review of unchanged diffs
