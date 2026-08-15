# Intent Control Plane

Date: 2026-08-15
Codememory epic: `epic_24`

## Goal

Convert natural user requests and agent discoveries into a complete, durable
Codememory graph without giving multiple agents direct write authority.

## Authority

| Surface | Authority |
| --- | --- |
| Codememory | Tasks, epics, dependencies, decisions, documents, sessions, and mutation history |
| GitHub | Pull requests, checks, reviews, and merge state |
| Intent proposal | Advisory input awaiting deterministic reconciliation |
| `task_graph.json` | Derived execution view: Codememory-managed tasks are one-way projections; workflow-owned nodes remain local runtime state |
| `codememory_task_leases.json` | Cooperative single-host execution leases and per-task fencing high-water marks; never task lifecycle authority |
| `/bg/jobs.json` | Existing process execution state; lease-backed adaptation is tracked by `task_129` |
| OpenCode todos | Session-local presentation only; never durable task authority |

Only one coordinator may apply intent proposals for a repository scope.
Planning and research agents return proposals and must not transition durable
work directly. The MVP serializes coordinators with a local file lock; direct
`oc` writers remain outside that lock and are a documented concurrency limit.

## Task Graph Projection

`/task project --scope <scope> --check|--apply --json` materializes one
Codememory scope into the existing task graph without writing to Codememory.
`--codememory-config <path>` selects an explicit Codememory config when normal
config discovery is unavailable.

The projector reads every task through complete unfiltered and per-status JSON
listings. It reads authoritative detail for every listed link and repeats the
complete task and link scan after collection. Truncation, unknown statuses,
duplicate identities or dependencies, invalid dependency endpoints, and any
change between scans fail closed.

| Codememory status | Task graph status |
| --- | --- |
| `not-started` | `pending` |
| `doing` | `in_progress` |
| `blocked` | `blocked` |
| `done` | `completed` |
| `failed` | `failed` |
| `canceled` | `canceled` |

A Codememory `depends-on` link from task A to task B becomes `A.blockedBy =
[B]`. Failed, blocked, and canceled prerequisites never satisfy dependents;
workflow-owned `skipped` nodes retain their existing successful-terminal
semantics.

Projected tasks retain their exact Codememory IDs and carry
`metadata.codememory.managed = true`, source scope, status, kind, and schema
version. A canonical SHA-256 fingerprint over managed task semantics and the
scope is stored as the projection revision. The revision is a content revision,
not a Codememory database revision.

Only one scope may own a graph projection. Apply preserves unmanaged local and
workflow nodes, but fails on scope mismatches, ID collisions, malformed state,
invalid local references, or local references to managed tasks that would be
removed. It updates the destination under the task graph lock with a durable
atomic replace. A current apply is byte-stable and does not rewrite the file.

Ordinary task graph readers and writers validate projection metadata,
fingerprint, count, and managed task identity before exposing scheduler state.
They cannot mutate managed fields and fail closed on malformed or tampered
state. `--check` reports source or destination drift without writing; `--apply`
is the only task graph path that may repair managed state.

## Fenced Task Leases

`scripts/task_lease_command.py claim|heartbeat|check|release|status|doctor`
provides the local
execution lease used before autonomous dispatch. Codememory remains task and
session authority. A claim is admitted only after four bounded, read-only
probes against one explicit config and the caller's worktree:

1. `oc config --doctor` must report the selected backend ready.
2. `oc current --scope <scope>` must report the exact active, non-stale
   session, worktree, and task.
3. `oc get <task> --view full` must report that task as `doing` in the same
   scope.
4. A second `oc current --scope <scope>` must still report the same holder,
   rejecting a context switch during the source sample.

Each probe has a two-second maximum and a 256 KiB response cap. The complete
source sample has an eight-second deadline. The store binds to a digest of the
explicit config and backend identity; a changed config or backend fails closed.
The lease layer is SQLite-qualified: PostgreSQL, config environment
placeholders, and `CODEMEMORY_SQLITE_PATH` overrides fail closed so hidden
runtime DSNs cannot bypass backend binding. Source authority is sampled at
claim admission, not continuously asserted.

One active lease may exist per task. Its identity is the exact tuple of task,
session, owner, unique worker ID, lease ID, and fencing epoch. Repeating a
claim from the same session, owner, and worker returns the existing lease while
advancing the observed clock floor. A competing unexpired claim fails. Expiry uses `now >=
expires_at`; heartbeat never revives an expired lease. Reclaim or a new claim
after release increments the persisted per-task epoch, so a stale worker cannot
check, heartbeat, release, or enter a guarded commit after replacement. Epochs
and lease IDs are cooperative identifiers, not credentials or secrets.

The default owner-only state is
`~/.config/opencode/my_opencode/runtime/codememory_task_leases.json` and can be
relocated with `MY_OPENCODE_TASK_LEASE_PATH`. Claims require
`MY_OPENCODE_CODEMEMORY_CONFIG`; binary and default-scope overrides are
`MY_OPENCODE_CODEMEMORY_BIN` and `MY_OPENCODE_CODEMEMORY_SCOPE`. The durability
contract requires POSIX `flock`, no-follow opens, file fsync, atomic replace,
and parent-directory fsync. A stable lock file serializes access while a
separate atomically replaced journal records the previous and next state
digests before replacement. Any uncertain state commit remains `committing`
and blocks every operation rather than choosing an assumed generation.

After stopping every lease worker and inspecting the current state, an operator
may run `python3 scripts/task_lease_command.py doctor --recover-indeterminate
--accept-current-state` to
accept that generation and invalidate every active lease. A detected wall-clock
rollback also fails closed; `python3 scripts/task_lease_command.py doctor
--recover-clock --accept-current-state` likewise invalidates all active leases. Both paths
preserve epoch high-water marks and are manual authority decisions. Successful
status, check, and guarded-commit admission persist the latest observed wall
time so a later rollback cannot revive a lease after that observed point.

`guarded_local_commit()` in `scripts/task_lease_command.py` verifies the exact
unexpired holder and keeps the lease lock through one short callback. It rejects
same-thread reentry. This guard is valid only for cooperative, local, idempotent
effects that use the same lock boundary. GitHub, Git, Codememory, network, and
other external effects remain outside the local transaction and require native
compare-and-swap or end-to-end idempotency before parallel dispatch is safe.

## Lease-Backed Background Execution

`scripts/background_task_manager.py` adapts opt-in `/bg` jobs to the fenced
lease API without changing unleased job admission. Lease-backed jobs carry an
explicit Codememory task/session identity and use a separate capacity pool,
defaulting to two active attempts. Reservation under `jobs.lock` creates a
stable attempt and worker ID. Claim happens after that lock is released, and
the returned lease identity is persisted through `guarded_local_commit()`. The
only nested lock order is therefore lease lock followed by jobs lock.

Attempts are append-only and become `succeeded`, `failed`, `cancelled`, or
`unknown`. A failed attempt can requeue its job only when the caller selected a
bounded `max_attempts` value and explicitly declared the command retry-safe.
The default is one attempt. This is bounded at-least-once execution for commands
with their own idempotency contract, not exactly-once external effects.

Before execution, the worker syncs a prepared receipt and starts a process-group
wrapper behind a pipe gate. The wrapper syncs `gate_aborted` when the parent
exits before granting execution, or `effect_possible` immediately before shell
exec. PID publication and terminal projection are guarded by the exact attempt
and lease identity. Heartbeat loss terminates the process group and quarantines
an effect-possible attempt as `unknown` instead of replaying it.

Worker and command PIDs are paired with process-start fingerprints. A worker is
live only while its fingerprint, exact lease, and projected heartbeat all
remain current. Reconciliation contains the recorded command group even after
lease expiry, then validates terminal receipt hashes, process and gate evidence,
terminal semantics, and the complete lease identity before adoption.

Cancellation fences the current attempt before signalling its process group.
It becomes terminal only after group settlement; failed containment remains
`reconciling` with process identity evidence intact.

`/bg reconcile` recovers known pre-effect interruptions and adopts a durable
terminal receipt only under the still-current exact lease. Missing or ambiguous
post-gate evidence remains `reconciling` for operator disposition. Codememory
continues to own task lifecycle; `/bg/jobs.json` owns only process attempts and
their local evidence.

## Proposal Contract

The MVP accepts UTF-8 JSON with this top-level shape:

```json
{
  "version": 1,
  "proposal_id": "user-request-20260815-01",
  "scope": "dmoliveira/my_opencode",
  "source": {
    "kind": "user",
    "id": "message-id",
    "summary": "Track and coordinate the requested work",
    "content_sha256": "optional lowercase SHA-256",
    "session_id": "optional session id"
  },
  "records": [
    {
      "key": "epic:control-plane",
      "entity_type": "epic",
      "title": "Build intent control plane",
      "kind": "feature",
      "priority": "P1"
    },
    {
      "key": "task:coordinator",
      "entity_type": "task",
      "title": "Build manual intent coordinator",
      "kind": "feature",
      "priority": "P1",
      "goal": "Apply validated intent proposals safely.",
      "summary": "Reconcile records and links with deterministic receipts.",
      "labels": ["codememory", "orchestration"]
    }
  ],
  "links": [
    {
      "from": "epic:control-plane",
      "edge": "parent-of",
      "to": "task:coordinator"
    }
  ]
}
```

Supported record types are `task`, `epic`, `memory`, and `doc`. Proposal keys
are local symbolic references and are never persisted as record IDs.

| Entity | Required fields | Optional fields |
| --- | --- | --- |
| `task` | `key`, `entity_type`, `title` | `kind`, `priority`, `goal`, `summary`, `labels` |
| `epic` | `key`, `entity_type`, `title` | `kind`, `priority`, `goal`, `summary`, `labels` |
| `memory` | `key`, `entity_type`, `title`, `kind`, `body` | `summary`, `labels` |
| `doc` | `key`, `entity_type`, `title`, `doc_type`, `ref` | `summary`, `labels` |

The MVP allows `parent-of`, `depends-on`, `about`, and `doc-for` links only.
Lifecycle-affecting or scheduler-affecting links such as `active-task` and
`blocked-by` are deferred.

## Reconciliation

1. Validate the complete proposal before reading or writing Codememory.
2. Reject more than ten combined records and links in the MVP.
3. Require every link endpoint to reference a record created by the proposal.
4. Validate each link's source and target entity types before any Codememory
   operation.
5. Reject any exact entity-type and title collision in the target scope.
6. Reject the complete proposal when any validation or collision exists.
7. Translate the proposal deterministically into one `oc batch plan` manifest.
8. Persist a prepared receipt before invoking Codememory.
9. Apply records and links with one `oc batch plan` operation.
10. Validate the returned scope, total count, record keys/types/titles/IDs, and
    resolved link IDs against the proposal.
11. Mark the receipt applied only after exact machine-readable output passes.
12. Return created IDs and the receipt without echoing raw source content.

The MVP is fresh and add-only. It does not reuse or update existing records,
link existing records, or change task lifecycle. Existing-record reconciliation
requires transactional aliases/upserts or a future expected-revision delta API.

## Identity And Receipts

Canonical proposal JSON uses sorted object keys, compact separators, NFC
Unicode normalization, preserved array order, and no omitted-field synthesis.
The proposal fingerprint is the SHA-256 of those UTF-8 bytes. The Codememory
request ID is derived only from scope plus `proposal_id`, so changed content
under the same proposal ID conflicts.

Receipts are stored outside the worktree in the configured coordinator state
directory and contain:

```json
{
  "version": 1,
  "proposal_id": "user-request-20260815-01",
  "scope": "dmoliveira/my_opencode",
  "source": {
    "kind": "user",
    "id": "message-id",
    "summary": "Track and coordinate the requested work"
  },
  "fingerprint": "sha256",
  "request_id": "intent_coord_<digest>",
  "actor": "intent-coordinator",
  "status": "prepared",
  "manifest": "deterministic batch YAML",
  "result": null
}
```

Allowed statuses are `prepared` and `applied`. A crash or uncertain command
failure leaves `prepared`; retry resubmits the exact stored manifest and request
ID with the receipt's original actor. An applied receipt returns the stored
result without another write.

Operator-only overrides use `MY_OPENCODE_CODEMEMORY_BIN`,
`MY_OPENCODE_CODEMEMORY_CONFIG`, `MY_OPENCODE_INTENT_COORDINATOR_STATE_DIR`,
and `MY_OPENCODE_INTENT_COORDINATOR_ACTOR`. They are intentionally not exposed
as `/intent` arguments.

## Privacy

- The schema has no raw prompt or attachment field.
- Persist source identity, a concise caller-provided summary, and an optional
  content digest.
- Unknown source and record fields fail validation rather than being retained.
- Proposal files must be regular files and are read once with a hard byte cap.
- Record bodies, summaries, and references are intentional Codememory content;
  callers must not place secrets in them.
- Keep command output free of database paths unless doctor mode is requested.

## Intent Ingress Outbox

The gateway can persist user-message intent before proposal planning. The hook
is disabled by default and performs only bounded local filesystem work; it does
not call an LLM, the network, a subprocess, or `oc`.

`chat.message` identity is the project root, session ID, and message ID. The
message ID uses `input.messageID` when present and otherwise
`output.message.id`. Missing or malformed identity, an empty prompt, a known
non-user role, and input beyond `maxInputChars` are skipped before content is
hashed or the spool is created.

Pending envelopes use this shape:

```json
{
  "version": 1,
  "envelope_id": "intent_ingress_<digest>",
  "project_digest": "lowercase digest",
  "observed_at": "RFC 3339 timestamp",
  "source": {
    "kind": "user",
    "session_id": "OpenCode session ID",
    "message_id": "OpenCode message ID"
  },
  "content": {
    "mode": "metadata",
    "char_count": 42,
    "sha256": "lowercase SHA-256"
  }
}
```

Metadata mode persists no raw prompt. `captureContent=true` adds a
whitespace-normalized preview only after configured secret redaction and caps
it at `maxContentChars`; redaction failure falls back to metadata with an
omission reason. The raw prompt SHA-256 supports integrity and conflict
detection but is not a substitute for secret handling.

The default spool is
`~/.config/opencode/my_opencode/runtime/intent-coordinator/ingress/pending`.
Directories are owner-only (`0700`), envelopes are owner-only (`0600`), and
symlink, ownership, or unsafe writable-ancestor mismatches fail open without
writing through the unsafe path. Each envelope is file-synced before publication
and the pending directory is synced when supported. A published staging hard
link left by interruption is recovered on retry. These ownership and no-follow
guarantees require a POSIX runtime; unsupported platforms fail open without
capturing an envelope.

The spool is unordered storage. Consumers must sort by `observed_at`, then
`envelope_id`. Repeating one identity with the same content SHA-256 is a no-op;
reusing it with changed content is a conflict. `softMaxPendingEntries` applies
globally to the configured pending directory and drops new identities when the
soft limit is reached. Concurrent distinct writers may exceed that approximate
limit briefly. The hook awaits persistence because returning before local sync
would weaken the durability contract; latency is emitted only as bounded local
audit metadata and is never exported by this hook.

## Failure Contract

- Dry-run performs no Codememory mutation.
- Invalid proposals fail before any subprocess starts.
- Apply writes a `prepared` receipt before graph mutation.
- Replaying an `applied` proposal creates zero additional records or links.
- Retrying a `prepared` proposal resubmits its exact manifest and request ID.
- Reusing a proposal ID with changed content fails before Codememory mutation.
- A rejected collision or failed batch leaves no partial graph mutation.
- Codememory command failures return the exact operation and bounded stderr.
- Malformed or incomplete batch results leave the receipt `prepared` for safe
  idempotent recovery.

## Acceptance Gates

- Schema validation covers malformed, oversized, duplicate-key, unknown-field,
  unsupported-edge, and unknown-reference cases.
- Dry-run proves deterministic manifest generation and collision rejection.
- Apply emits one deterministic request ID and a machine-readable receipt.
- Apply verifies exact returned records and links before committing the receipt.
- Same-proposal replay is a no-op with stable created IDs.
- Conflicting replay fails without graph changes.
- Concurrent coordinator attempts serialize on the scope lock.
- Crash recovery from `prepared` resubmits the original manifest.
- Tests use an isolated fake or temporary Codememory store.
- `oc plan doctor` remains healthy after a live isolated smoke run.
- The MVP is single-host and SQLite-qualified; PostgreSQL parity is deferred.
- Intent ingress is inert by default and persists no raw prompt in metadata
  mode.
- Intent ingress tests cover identity fallback, redaction, byte and entry
  bounds, duplicate/conflict behavior, private paths, interruption recovery,
  restart persistence, and deterministic replay order.

## Deferred Work

- Proposal-only planner and bounded research: `task_127`.
- Scale qualification at 50, 250, and 1000 tasks: `task_130`.
