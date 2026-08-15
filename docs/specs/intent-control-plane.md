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
| `task_graph.json` | Existing execution state; migration to a Codememory projection is tracked by `task_125` |
| `/bg/jobs.json` | Existing process execution state; lease-backed adaptation is tracked by `task_129` |
| OpenCode todos | Session-local presentation only; never durable task authority |

Only one coordinator may apply intent proposals for a repository scope.
Planning and research agents return proposals and must not transition durable
work directly. The MVP serializes coordinators with a local file lock; direct
`oc` writers remain outside that lock and are a documented concurrency limit.

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

## Deferred Work

- Opt-in `chat.message` ingress and durable outbox: `task_126`.
- Proposal-only planner and bounded research: `task_127`.
- Fenced task leases and heartbeats: `task_128`.
- Lease-backed background execution: `task_129`.
- Scale qualification at 50, 250, and 1000 tasks: `task_130`.
