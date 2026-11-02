---
status: doing
priority: high
updated: 2026-11-03
---

# Intent Control Plane Roadmap

Codememory epic: `epic_24`
Delivered slice: proposal-only intake planner (`task_127`). Next slice: rolling decomposition qualification (`task_130`). Production protocol `task_122` merged in [PR #754](https://github.com/dmoliveira/my_opencode/pull/754).

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
| `task_130` Rolling decomposition qualification | ready | `task_127`, `task_129` | Coverage and recovery at 50, 250, and 1000 tasks |

`task_122` is owned by the Tasker hardening epic and is complete. PR #754
superseded the isolated proposals in PRs #708 and #709; both drafts are closed.
The manual coordinator remains the only intent-proposal graph writer.

## Latest Slice

1. Collect a bounded read-only research packet for an explicit user/agent source,
   optionally binding the original ingress envelope without consuming it.
2. Let the calling agent synthesize a version-1 proposal from that packet. No
   planner command invokes an LLM or grants the synthesizer additional tools.
3. Admit only complete record/link assessments, current evidence and a matching
   source; emit an advisory artifact without graph, state or spool writes.
4. Keep deterministic coordinator preview/apply separate from planning. Validate
   the complete ingress → research → synthesis → plan → preview handoff.

Depth: medium. Risk: medium (new offline read-only path). Maximum two fixed
file-reading workers; no new agent subprocesses. See
`docs/specs/intent-control-plane.md` for bounds, cancellation and schema.

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
- targeted planner schema, provenance, path-race, bounds, coverage and cancellation tests
- isolated ingress/research/synthesis/plan handoff and native coordinator preview smoke
- `make validate`
- Ruff and configured pre-commit
- two changed-diff review/fix passes; no repeat review of unchanged diffs
