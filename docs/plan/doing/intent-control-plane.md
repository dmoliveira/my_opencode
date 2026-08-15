---
status: doing
priority: high
updated: 2026-08-15
---

# Intent Control Plane Roadmap

Codememory epic: `epic_24`
Branch: `feat/intent-coordinator-mvp`

## Outcome

Capture user intent and agent discoveries naturally, reconcile them against
existing Codememory state, and execute a durable dependency graph without
requiring the primary agent to remember every tracking command.

## Sequence

| Task | Status | Dependency | Outcome |
| --- | --- | --- | --- |
| `task_123` Intent graph authority contract | done | none | Versioned proposal, authority, privacy, and replay contract |
| `task_124` Manual intent coordinator MVP | doing | `task_123` | Fresh add-only dry-run and idempotent transactional apply |
| `task_125` Task graph projection | blocked | `task_124` | One-way Codememory projection and drift detection |
| `task_126` Durable intent ingress | blocked | `task_124` | Bounded asynchronous hook outbox |
| `task_127` Proposal-only planner | blocked | `task_126`, `task_122` | Bounded read-only research and typed proposals |
| `task_128` Fenced task leases | ready | none | Atomic claim, heartbeat, expiry, and fencing |
| `task_129` Lease-backed background execution | blocked | `task_128`, `task_125` | Recoverable bounded task workers |
| `task_130` Rolling decomposition qualification | blocked | `task_127`, `task_129` | Coverage and recovery at 50, 250, and 1000 tasks |

`task_122` is owned by the existing Tasker hardening epic. PRs `#708` and
`#709` remain prerequisites for planner integration but do not block the
manual coordinator.

## Current Slice

1. Complete `task_123` with `docs/specs/intent-control-plane.md`.
2. Implement `task_124` as an explicit manual command.
3. Validate schema, reconciliation, replay, and isolated live Codememory use.
4. Deliver through one reviewed PR without enabling automatic hooks or task
   execution.

## Safety Boundaries

- No synchronous LLM, network, or `oc` work in `chat.message` hooks.
- No autonomous task dispatch before fenced leases exist.
- No competing task authority is introduced in this slice.
- No raw user prompt is persisted by default.
- No more than ten combined records and links per MVP proposal.
- Any collision or unresolved item aborts the complete proposal.
- Existing-record reuse and updates are deferred until Codememory offers a
  transactional upsert or expected-revision delta API.

## Validation

- `git diff --check`
- targeted unit tests for the coordinator
- command doctor and schema output
- isolated Codememory dry-run/apply/replay smoke
- `make validate`
- reviewer and verifier pass on the final diff
