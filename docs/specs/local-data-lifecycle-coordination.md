# Proposed Local-Data Lifecycle Coordination Contract

Status: **design only; not implemented or approved for source mutation**.
Tracking: `task_26`. This document defines requirements and test cases for a
future coordinator. It is not an operator runbook, an authorization, an apply
token, or evidence that any current command meets the contract.

## Purpose and Limits

A lifecycle request can span runtime history, session sidecars, shared memory,
and Codememory. Their owners do not share a transaction. A crash or failed owner
operation can therefore leave a request partly applied, and a timeout does not
prove that an owner made no change. A coordinator must report these situations
without inventing atomicity, silently retrying, or discarding recovery evidence.
Here, an **effect** means a change to an in-scope source; a journal or backup can
still be created even when no source effect occurs.

The following requirements concern source removal or source redaction. A
sanitized export, reversible archive, counts-only summary, or snapshot hash is
not the same effect. Backups, WAL files, indexes, quarantine, exports, and
external copies may retain the original content. Even a successful logical
removal does not prove physical or secure erasure.

## Current Owner Boundaries

| Owner | Available evidence | Gap for this contract |
| --- | --- | --- |
| OpenCode V2 runtime | Session listing and cascading deletion exist. In a disposable 2.2.5 probe, a child created between pages was missed before a parent delete removed it. | The inspected delete accepts a session ID without a revision-bound descendant set. Listing or the process-local activity endpoint does not exclude all writers. |
| Session sidecars | The index and digest have owner-side private read/write primitives and distinct cooperative locks. | The index is not a complete artifact or reference inventory; no per-session, cross-artifact removal contract is established. Separate locks do not by themselves freeze every writer. |
| Shared memory | The owner has archive preview/apply, explicit transaction outcomes, and a read-only scoped candidate fingerprint. | Cleanup is archival, not erasure. The fingerprint is not source-identity-bound, authorized, or compared by a conditional source-removal operation. |
| Codememory | Disposable tests showed revision-bound stale-plan rejection after archive and restore, exact request replay for an archive, and native backup/check/restore to a new destination. | Those observations qualify only the tested reversible archive and recovery cases. They do not establish erasure, live recovery readiness, or cross-store atomicity. |

No owner currently qualifies for this cross-store source-removal contract on the
evidence above. Do not wrap an unconditional delete, write direct SQL, remove
SQLite sidecars, or treat a coordinator's lock as an owner write fence.

## Admission Before Any Owner Effect

A future implementation must reject the entire request before its first owner
effect unless all of the following are established for **every** in-scope owner:

1. **Exact authorized manifest.** Bind an explicit principal's authorization to
   the action, each owner and source identity, scope, candidate identities,
   descendants, expected owner revisions, execution order and dependencies, and
   included and excluded artifact classes. Approval of one generation, an
   offline preview, or a digest alone is not approval of later generations or
   broader cascades. A missing, ambiguous, truncated, duplicate, or unsupported
   inventory is not an empty inventory. Unknown external copies remain explicitly
   unknown.
2. **Owner-enforced binding.** For each operation, the owner must atomically
   compare the authorized source generation and complete affected set with the
   effect, or provide enforceable writer exclusion that covers every relevant
   writer throughout the necessary interval. A cooperative coordinator lock,
   timestamp, repeated read, caller-supplied `stopped` flag, or process-local
   activity list is not sufficient. A fence must remain effective through an
   in-flight owner operation even if the coordinator dies.
3. **Recovery appropriate to that owner.** Identify a private recovery artifact,
   its source generation and scope, and integrity result. Restore a copy of that
   exact artifact to a disposable destination and verify readback of the expected
   scope with a compatible owner version; opening the file alone is insufficient.
   Bind the artifact to the pre-effect generation under the same owner protection;
   an old or unrelated backup is insufficient. No recovery check authorizes
   overwriting a live destination. Record retention separately: recovery artifacts
   can retain the data the request seeks to remove.
4. **Durable coordination and owner capability.** Before dispatch, establish the
   journal and exclusive coordinator authority described below, and verify each
   owner's supported effect, result, and reconciliation contract. Revalidate
   source identity, manifest binding, authorization, recovery, and any fencing
   at the owner boundary. An unexpected source, owner, config, backend, revision,
   descendant, or authorization change invalidates the affected admission; it
   never expands the approved set automatically. An expected prior effect is
   checked against its authorized postcondition and cannot authorize a new
   candidate or a changed effect at a later step.

The admission check is not a substitute for an owner-side conditional effect.
The coordinator must not begin the first owner merely because earlier owners
qualify while a later required owner is unsupported. Authorization must also
cover the possibility of partial completion; this contract does not promise an
automatic cross-store rollback.

## Journal and Dispatch Ordering

The intended journal is owner-private and local-sensitive. It must bind a unique
request ID to an immutable versioned manifest, exact owner/backend identity,
per-owner request IDs and candidate generations, authorization reference,
recovery reference, and state transitions. Bind each owner-assigned operation ID
when that owner supplies one. Its integrity and origin must be verified; an
attacker-supplied JSON file, hash, process exit code, or matching identifier is
not owner evidence. Do not put source contents, secrets, raw transcripts, or
unbounded owner output in the journal or diagnostics. Even selectors, paths,
hashes, request IDs, and recovery references can be sensitive.

The future implementation must specify and test its supported filesystem and
durability primitives. At minimum it needs exclusive journal creation or a
verified existing identity, serialized writers, atomic state publication, file
and directory durability, bounded private reads, and protection against aliases,
replacement, and unauthorized access. A lock or fencing epoch only coordinates
participants that enforce it; it cannot stop an independent owner writer.
Concurrent coordinators must not dispatch the same step unless the owner itself
provides a qualified concurrent-idempotency guarantee. Do not recover an
uncertain journal publication by selecting an assumed generation.

For each owner that needs a source effect, in the approved order:

1. Persist the prepared request and owner-specific preconditions durably. This is
   intent, not a success or no-effect receipt.
2. Under the current coordinator authority, persist and confirm an
   `effect_possible` marker **before** invoking the owner. Do not dispatch when
   that marker's durability is uncertain. If the process dies after the marker,
   recovery must assume the owner may have run, even if dispatch actually had
   not started.
3. Invoke only the bound owner operation. Observe its result through the verified
   owner channel and validate operation identity, affected scope, outcome, and
   durability against that owner's contract. Missing, malformed, mismatched, or
   contradictory output is not a no-effect result.
4. Durably record the validated outcome and its evidence before proceeding to
   another owner. If recording is uncertain, stop. A successful owner result in
   memory is not a durable receipt.

The coordinator must be able to distinguish its own pre-dispatch state from
another in-flight coordinator; otherwise it stops as `unknown`. Lease expiry or
process cancellation alone does not prove the owner stopped or rolled back.
Owner responses and journals do not establish authority outside their explicit
trust boundary. An implementation must state its attacker model; inability to
enforce authorization or integrity against an in-scope actor is a blocker.
Document out-of-scope same-user or administrator interference explicitly rather
than claiming that these requirements prevent it.

## Outcomes and Reconciliation

Each requested owner has one conservative outcome; no outcome implies an
unexamined owner's state. An owner-qualified read-only observation may establish
a `verified_noop` without dispatching a source effect; its evidence must still be
recorded durably before the coordinator advances:

| Outcome | Required evidence | Coordinator behavior |
| --- | --- | --- |
| `not_started` | Durable, unambiguous proof that no owner dispatch for this step was possible, including no competing dispatcher. | Report no effect for this step. A later attempt still requires valid admission. |
| `verified_noop` | The owner proves that the complete authorized affected set is empty for the bound source generation, with the required protection. | Record the no-op; missing or incomplete inventory is not proof of emptiness. |
| `committed` | A validated, durable owner receipt for the exact request, generation, and effect, with any owner-specific postcondition verified. | Preserve the receipt; do not repeat this effect merely because a later owner fails. |
| `rolled_back` | Owner evidence establishes that rollback completed with no lasting in-scope effects, including effects outside its primary store. | Stop the request; any new attempt needs valid admission and owner-specific retry rules. |
| `unknown` | An effect may have occurred, or journal, process, identity, durability, or owner evidence is missing or contradictory. | Stop dispatching other steps and preserve the journal and recovery artifacts. Only a qualified exact replay of the original step may be used for reconciliation as described below. |

An `effect_possible` step without a valid terminal receipt projects to `unknown`,
including a crash before the owner was actually invoked. An owner-reported
commit followed by uncertain journal durability is also `unknown` until an
authoritative reconciliation establishes the outcome. A failed command or
successful cancellation is not automatically a rollback. Do not substitute a
count, absence from a listing, a new snapshot hash, or an exit status for the
owner's operation-specific proof.

Individual owner commits do not establish a simultaneous cross-store end state.
To report that the requested sources are clean at completion, the implementation
must keep effective owner protection through all final checks, or provide an
equivalent owner-enforced proof of a consistent end state. Verify the expected
postcondition and absence of unapproved changes for each included owner before
releasing protection. Without such proof, report the observed individual outcomes
and an uncertain aggregate; do not turn time-separated observations into a
cross-store success claim. A verified end state is an observation at that
protected point, not a promise that future writers cannot recreate data.

Reconciliation first contains or accounts for all in-flight dispatchers and
checks the original owner/backend and exact operation identity. It may adopt an
authoritative terminal receipt, establish a proven no-effect result, or remain
`unknown`. Exact replay can be used for reconciliation only if that particular
owner has a tested contract covering concurrent and lost-response cases, retains
complete idempotency history for the relevant period, and accepts the **same**
request ID and unchanged payload against the same backend. A replay is not
necessarily a read: if the original dispatch never reached the owner, replay may
perform the first effect. The owner must atomically return the established result,
or, when it can prove the request was never applied, revalidate the original
authorization, binding, recovery and fencing conditions before applying it at
most once. A missing or expired idempotency record alone does not prove no effect.
If these conditions cannot be established, do not replay. Never infer that a
different request ID or a repeated unconditional cascading delete is safe. A new
attempt after a proven rollback is distinct from replay and requires fresh
preconditions.

Aggregate reporting must distinguish: no source effects; all requested effects
committed or verified as no-ops within the approved scope; a known partial result;
and an uncertain result. The no-effects case must not imply that the requested
sources were inspected or clean; distinguish failed admission from a verified
all-no-op request. Any unknown step or uncertain journal takes precedence over a
known-partial label. Include per-owner outcomes and unexamined artifact classes,
not a single success flag. Do not claim full sanitization, descendant coverage,
or physical erasure merely because every attempted owner returned success. A
request with one committed owner and one rolled-back owner is partial, not
globally rolled back; compensation or restoration is a separate, explicitly
authorized owner operation with its own receipt and failure handling. A known
partial result describes the established operation history, not proof that its
committed owners are still clean when protection has been lost.

## Required Qualification Before Implementation Is Enabled

These are acceptance tests to implement, **not tests already passed**. Run them
only against synthetic stores, processes, identities, backups, and destinations.

- Reject before dispatch if any owner, candidate set, descendant page, source
  identity, authorization, recovery artifact, or fencing capability is absent,
  truncated, stale, mismatched, duplicated, or unsupported. Assert no mutating
  owner call.
- Distinguish a complete owner-bound empty set from a missing or incomplete
  inventory. Do not turn a later absence into proof that an unknown dispatch was
  a no-op.
- Insert, update, remove, and recreate candidates between preview and commit,
  including a child between listing pages and an archive/restore ABA sequence.
  The owner must reject the stale affected set or prove effective exclusion.
- Crash or fail before journal preparation, during journal publication, after
  `effect_possible`, before owner invocation, during the effect, after owner
  commit, and before or during terminal-receipt persistence. Assert no blind
  replay and no dispatch to a later owner after uncertainty.
- Inject rollback failure, a lost response, contradictory or forged receipts,
  partial output, source or backend replacement, coordinator lease expiry,
  competing coordinators, a still-running owner, and journal tampering. Unknown
  must stay unknown until owner-specific evidence justifies reconciliation.
- Test exact replay with the same request ID and payload only for a qualifying
  owner, including concurrent submissions, lost responses, expired idempotency
  history, changed payloads, and backend swaps. When the original dispatch never
  reached the owner, verify that replay checks the original preconditions before
  its first effect. Non-idempotent owners must not be retried automatically.
- Exercise committed/rolled-back/unknown combinations across owners. Verify
  partial and uncertain aggregate results, no automatic compensation, no later
  dispatch after failure, preserved recovery material, and no false erasure
  claim. Recreate data in an earlier owner between later steps and during final
  verification; without an effective fence, cross-store success must not be
  reported. Verify a disposable restore and readback without replacing an
  existing destination.
- Test private file permissions, no-follow and alias handling, bounded parsing,
  redacted diagnostics, and secret canaries. Confirm that all test mutations
  remain inside disposable roots and that no real store or service is accessed.

Until each admitted owner passes its own binding, recovery, reconciliation, and
fault-injection gates, the coordinator and task remain blocked. The existing
`scripts/data_lifecycle_command.py` is an offline planner and read-only
inventory, not an implementation of this specification.
