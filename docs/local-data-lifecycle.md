# Local Data Lifecycle: Planning and Read-Only Inventory

Task: `task_26`. Status: **partial implementation; source mutation remains blocked**.

## What Is Available

```bash
python3 scripts/data_lifecycle_command.py preview --file /private/staging/request.json
python3 scripts/data_lifecycle_command.py summarize-export --file /private/staging/export.json --store runtime_history
```

These two commands emit JSON to stdout and execute no owner commands, subprocesses,
network calls or writes. There is no `apply` operation and no new slash alias.
The only file read is the explicitly supplied input. Input must be an existing
current-user-owned private regular single-link file (`0600` or stricter) beneath
an owner-controlled, non-group/world-writable parent. The reused sidecar reader
rejects final symlinks and unsafe/user-owned ancestor aliases while allowing
verified root-owned system aliases (for example, macOS `/var`). Parents may be
`0755`; use a private `0700` staging directory outside synchronized repositories
for this workflow. The reader
does not repair permissions, copy unsafe inputs, or create missing files.
The separate shared-memory inventory described below **does inspect** an
explicitly selected source database in an isolated read-only worker.

`preview` returns an `offline_workflow_plan`: a successful plan has `result: PASS`
but **`status: blocked`**, `source_inspected: false`, `affected_count: null`, and
`apply_supported: false`. It is not a deletion preview or a proof that any owner,
backup, scope, descendant inventory, authorization or revision was verified.
Suggested argv arrays describe owner inspection/export/preview only and are never
executed. Those owner commands can have their own cache, export, diagnostic or
audit side effects; a pure planner does not imply write-free owner tooling.

Plans include local-sensitive scope, identifiers and config paths. Keep them
private; they are neither support bundles nor authorization tokens.

## Exact Request Schemas

All requests require exactly `version`, `store`, `action`, and `selector`.
`version` is integer `1`; `action` is `removal` or `redaction`. No arbitrary command,
shell, executable override, backup destination, raw prompt or source path is
accepted. Unknown and missing fields fail closed. Example:

```json
{
  "version": 1,
  "store": "runtime_history",
  "action": "removal",
  "selector": {"session_id": "ses_example", "cli_family": "opencode-v2"}
}
```

| Store | Exact selector fields | Meaning / limits |
| --- | --- | --- |
| `runtime_history` | `session_id`, `cli_family` | One token ID; only caller-asserted `opencode-v2` is supported. Inspect installed owner help before using suggested commands. |
| `session_sidecars` | `session_id` | One token ID or a safely representable owner-generated fallback ID. Indexed session inspection does not prove complete digest, handoff or transcript inventory. |
| `shared_memory` | `scope`, `namespace`, `older_days` | Scope `session`, `repo`, or `shared`, exact namespace, integer age 1–36500 days. Age is a moving predicate; pinned entries are excluded by the owner. |
| `codememory` | `scope`, `artifact_kind`, `record_id`, `config` | Kind `memory` with `memory_<positive integer>`, or `document` with `doc_<positive integer>`; explicit absolute config path with no traversal. Verify the native record's scope matches the expected scope. |

Selector text is nonempty, trimmed, at most 256 characters and excludes controls
and leading option markers, except for the bounded sidecar fallback below. Token
IDs permit ASCII letters/digits, underscores and hyphens. Identifiers and
provenance are caller assertions; the planner does not discover a project, select
a backend, read a source store, or authenticate identity. Cmdline values are
represented as separate argv elements, not shell strings. Do not paste a
JSON-rendered argv array into a shell.

For `session_sidecars` only, the planner also accepts the index owner's fallback
form `<absolute-POSIX-cwd>::<canonical-aware-ISO-datetime>::<lowercase-UUID4>`,
up to 8192 printable characters. It parses from the right because the cwd can
itself contain `::`; the cwd is opaque selector text and is never opened or
verified as a path. A syntactic match does not prove that the owner generated
the ID or that an entry exists. The fallback is a local index ID, not a native
runtime session ID, and does not prove correspondence to one. Its contents can
include spaces, punctuation, and private directory names, so both the request
and successful plan remain local-sensitive. Fallback IDs with nonprintable
characters, unsafe or noncanonical components, or more than 8192 characters
remain unsupported; custom IDs outside the token or fallback forms are not
accepted. This exception does not broaden the `runtime_history` session-ID schema.

## Counts-Only Export Summary

`summarize-export` accepts a JSON object or array and an explicit store label from
the table. It emits only a flat JSON-type histogram, total node count and maximum
depth. Keys count as string nodes; neither key names, values, scalar lengths,
hashes, array positions nor object topology are copied. Equal structure produces
equal summaries regardless of content. The label is **not** detected provenance
or proof of a valid owner export format. Structural counts still disclose
metadata; review them before sharing.

This output is **not restorable**, not a sanitized transcript/export, not source
redaction, and not a secret scan. Do not substitute it for a recovery backup.
Content-free support metadata and recovery material have different purposes.

Both inputs are capped at 2 MiB, 32 nested container levels and 50,000 nodes
(including keys), with 128-character numeric tokens. Preflight limits run before
JSON parsing; traversal also enforces a maximum node depth of 32. Duplicate decoded
keys, nonfinite values including exponent overflow, lone surrogate escapes, invalid
UTF-8 and malformed input fail. Failure reports contain fixed reason codes, not
input paths, content or exception details. Invalid arguments also produce fixed
JSON failures rather than argparse's normal argument echo. Success exits 0;
failure exits 1; help exits 0. No partial plan or summary is emitted on failure.

## Read-Only Shared-Memory Candidate Snapshot

For an explicitly selected shared-memory database, scope, exact namespace and
frozen UTC cutoff, the separate inventory command reports the count and a
fingerprint of the **archive candidates** in one owner snapshot:

```bash
python3 scripts/data_lifecycle_command.py inventory-shared-memory \
  --db-path /private/example/shared-memory.db \
  --scope repo --namespace example --cutoff 2026-01-01T00:00:00Z
```

It uses the same candidate predicate as `/memory-lifecycle cleanup`: active,
unpinned records older than the cutoff, including the owner's date fallback and
scope/namespace filters. The cutoff must be an explicit UTC whole-second instant;
the command does not silently recalculate a moving `--older-days` predicate.

The fingerprint covers a versioned domain, the exact selector, column names and
every value of each selected row in deterministic order. No row values, IDs,
namespace, or path are printed. The process arguments and the resulting count,
cutoff, scope and content-derived hash are **local-sensitive**; hashes can expose
equality or enable guessing and are not automatically safe to share. The digest
is an observation, not a backup, anonymization or secure erasure.

The command uses the existing owner read-only connection and never opens the
source for writing, archives rows, deletes, redacts, creates a backup or creates
a missing source. Its public entry point always starts a separate worker: an
embedded owner reader sharing a process with a writable connection to the same
database can alter transient SHM coordination bytes, even with `readonly_shm=1`.
That was observed on Darwin with SQLite 3.54.1; do not call the private inventory
function inside such a process. Failure emits only a fixed reason code. The
isolated worker has a 30-second deadline, a 128 MiB SQLite hard-heap ceiling,
checks for a 64 MiB limit on each source database/WAL/SHM file, a 1 MiB SQLite
row limit, and limits of 10,000 candidate rows, 128 columns, 256 characters per
column name and 16 MiB serialized candidate data. Linux also enforces a 512 MiB
process address-space ceiling. Some Darwin kernels reject that OS ceiling; on
those systems the source-copy, SQLite-heap and row limits still apply, but they
are **not** a hard ceiling on total Python process memory. Exceeding a limit or
encountering an unsupported store fails rather than returning a partial digest.
The owner reader may follow a configured database symlink to a verified regular,
single-link target; it rejects unsupported sidecars. These checks do not freeze a
concurrent writer or guarantee that file sizes stay fixed throughout inspection;
the sample can become stale immediately after it is taken.

**This is not a source-removal or redaction preview.** `apply_supported`, source
identity binding, authorization, quiescence, verified recovery and cross-store
completeness remain false. The fingerprint is not compared in an owner write
transaction and must not be treated as a token to apply cleanup or deletion.
Pinned/archived records, FTS, other namespaces, other stores, backups and exports
are outside its candidate set. Existing cleanup archives records; it does not
erase their content. The cross-store source-mutation blocker below remains open.

## Owner Workflow Before Source Changes

1. **Authorize exact scope.** Decide removal versus export-only redaction and
   record which sessions/artifacts and descendants are intended. Never infer
   authorization from a successful offline plan or a blanket cleanup request.
2. **Quiesce the owner.** Stop active sessions, background work and sidecar
   writers using their supported owner mechanisms. A caller-provided "stopped"
   flag is not enforceable quiescence. Do not delete SQLite `-wal`/`-shm` files.
3. **Preserve recovery.** Follow `docs/runtime-db-schema.md`: create a private
   SQLite backup or owner export, verify its integrity/checksum and perform a
   disposable restore drill. Avoid plaintext recovery material in Git, cloud
   synchronization, tickets or command logs. Retain unresolved-incident backups.
4. **Inspect and bind candidate inventory.** Use owner-native commands and verify
   exact count, IDs, scope, descendants and expected revisions immediately before
   apply. If the owner cannot bind inventory/quiescence to its mutation, fail
   closed rather than issue generic SQL or recursively remove a directory.
5. **Mutate through the owner only.** This slice deliberately supplies no
   destructive argv and performs no mutations. An independently authorized owner
   action must define retry and partial-failure semantics and rerun its checks.
6. **Verify all stores.** Check the owner, sidecars, search indexes, exports,
   backups and external copies separately. Report partial completion honestly.

### Runtime History

The inspected V2 CLI exposes `opencode session export <sessionID>` and
`opencode session export <sessionID> --sanitize`. The latter creates an export
representation; it does not redact the database and is not a verified recovery
artifact. The installed CLI also exposes cascading session deletion, but no
revision-bound descendant preview was found. Therefore this planner does not
generate a delete command. V1 compatibility is not inferred from V2 help.

In a disposable OpenCode 2.2.5 instance, the installed API described paginated
`parentID` filtering for session listing, but deletion accepted only a session
ID and cascaded to children. Its active-session endpoint described only
foreground drains owned by that OpenCode process. Neither pagination nor that
activity list establishes an atomic descendant inventory or writer exclusion.
In a disposable race probe, a child created after a prior listing was also
removed by a later parent delete. The initial listing included a next cursor,
so this demonstrates a post-observation race, not complete pagination.

### Session Sidecars

Use `python3 scripts/session_command.py show <sessionID> --json` and `doctor --json`
for inspection. In this version, `show`, `current`, and `handoff` reject multiple
parsed index rows for the selected ID rather than choosing one. Unredacted output
uses `session_index_duplicate_id`; redacted handoff retains the share-safe
`session_index_unavailable` error. The check covers only the read snapshot: it
does not validate duplicate JSON keys, prevent later writes, establish source
identity, or cover other files or references in other stores. An index entry is
not a complete list of filesystem artifacts. Preserve corrupt originals via the
existing quarantine workflow. No per-session sidecar delete/redaction contract
is implemented here.

### Shared Memory

Use `python3 scripts/memory_lifecycle_command.py stats --json`, followed by
`cleanup --scope <scope> --namespace <exact-name> --older-days <days> --dry-run --json`
for an owner archive preview. Existing owner export/import and single-ID restore
support recovery; see `docs/runtime-db-schema.md`. Export requires a separately
chosen private destination and does not happen automatically. Cleanup is **archive**,
not physical deletion: pinned rows, original content, FTS, exports and backup
copies are not proven sanitized. A moving age predicate is not an immutable plan.

### Codememory

Use one explicit config, `oc --config <config> get <recordID> --view full --format json`,
and compare the returned scope with the requested scope. The archive owner preview
is `oc --config <config> archive <recordID> --reason <reason> --format json`; it is
limited to memory/doc records and must preserve native reference/revision checks.
No task/session cancellation, direct SQLite mutation or overridden reference check
is added. Archive and operation history are retained, not securely erased.

In a disposable SQLite-backed Codememory graph, archive previews provided a
revision and plan hash. Applying one synthetic plan caused a second plan from
the prior revision to be rejected; repeating the successful request with the
same request ID and hash returned a replay of the same operation. This evidence
applies only to that native reversible archive flow, not erasure or cross-store
retry safety.

## Remaining Blocker For Task 26

The cross-store source-removal/redaction goal is not complete. Safe apply requires
owner-specific, revision-bound candidate inventories; runtime descendant coverage;
enforceable quiescence; verified recovery; explicit authorization; and a defined
cross-store retry/partial-failure contract. Runtime V2 cascading deletion and
sidecar file removal cannot be wrapped safely by treating this plan as approval.
Implementing direct SQL, broad filesystem deletion or a caller-only confirmation
flag would bypass those boundaries. Archive is not a substitute for deletion.
The proposed failure and retry contract is documented in
`docs/specs/local-data-lifecycle-coordination.md`; it is not an implemented
coordinator, an operator runbook, or an authorization to mutate any source.

Validation for the offline planner uses actual CLI subprocesses on disposable
inputs next to sentinel runtime/shared-memory/Codememory SQLite files and
sidecars, checking unchanged bytes, no new files and no privacy canary on either
output stream. It is planner CLI validation, not native deletion validation.
