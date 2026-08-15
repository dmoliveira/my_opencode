---
status: doing
priority: high
updated: 2026-08-15
---

# Intent Control Plane Roadmap

Codememory epic: `epic_24`
Current slice: `task_129`

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
| `task_127` Proposal-only planner | blocked | `task_126`, `task_122` | Bounded read-only research and typed proposals |
| `task_128` Fenced task leases | done | none | Atomic claim, heartbeat, expiry, and fencing |
| `task_129` Lease-backed background execution | doing | `task_128`, `task_125` | Recoverable bounded task workers |
| `task_130` Rolling decomposition qualification | blocked | `task_127`, `task_129` | Coverage and recovery at 50, 250, and 1000 tasks |

`task_122` is owned by the existing Tasker hardening epic. PRs `#708` and
`#709` remain prerequisites for planner integration but do not block the
manual coordinator.

## Current Slice

1. Keep existing unleased `/bg` jobs compatible while reserving each execution
   atomically so concurrent runners cannot duplicate work.
2. Add opt-in task-lease jobs with immutable attempts, separate bounded
   capacity, exact fenced commits, and durable execution evidence.
3. Retry only explicitly retry-safe commands and quarantine every ambiguous
   post-start outcome for reconciliation instead of replaying it.
4. Preserve Codememory as task lifecycle authority and document that local
   leases cannot fence arbitrary Git, GitHub, network, or subprocess effects.

## Safety Boundaries

- The projector performs bounded read-only `oc list|get` calls and never mutates
  Codememory.
- One Codememory scope owns each projection; changing scope fails closed.
- Only projection apply may change managed task semantics.
- No autonomous task dispatch before fenced leases exist.
- Unmanaged workflow nodes remain local execution state, not Codememory tasks.
- No raw user prompt is persisted by default.
- No more than ten combined records and links per MVP proposal.
- Any collision or unresolved item aborts the complete proposal.
- Existing-record reuse and updates are deferred until Codememory offers a
  transactional upsert or expected-revision delta API.

## Validation

- `git diff --check`
- targeted background reservation, fencing, retry, and reconciliation tests
- live lease-backed execution smoke against isolated jobs and lease stores
- `make validate`
- reviewer and verifier pass on the final diff
