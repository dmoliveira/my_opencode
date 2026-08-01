---
status: doing
priority: high
updated: 2026-07-30
---

# Safe Scoped Shared-Memory Lifecycle

## Objective

Complete Codememory `task_28` by making shared-memory cleanup and compression previewable, scoped, private, atomic, and explicitly recoverable while preserving existing apply-by-default and JSON compatibility.

## Classification and boundaries

- Depth: large; the slice spans the SQLite owner, lifecycle CLI, tests, command registration, selftest, and operator docs.
- Risk: high because cleanup/compression archive durable memory and feed a global gateway alias.
- Use synthetic temporary stores only in tests. Never inspect or mutate live shared memory.
- Preserve no-filter whole-store behavior, explicit `--dry-run`, mutation-by-default, export/import v2, and `/gateway concise compress`.
- Exclude task_29 import redesign, migrations, automatic exports, broad connection cleanup, new deletion behavior, and archive batch IDs.

## Command contract

```text
/memory-lifecycle cleanup [--older-days N] [--scope session|repo|shared] [--namespace TEXT] [--dry-run] [--json]
/memory-lifecycle compress [--scope session|repo|shared] [--namespace TEXT] [--dry-run] [--json]
/memory-lifecycle restore --id ID [--json]
```

- Scope is canonical and validated; namespace is trimmed, nonempty, exact, case-sensitive, and never inferred. Both filters combine with `AND`.
- Invalid values, duplicates, and leftover arguments fail before SQLite opens.
- Cleanup retains the existing 30-day default when `--older-days` is omitted.
- Cleanup uses chronological SQLite comparison, not lexical timestamp ordering.
- No filters retain whole-store behavior and report that scope explicitly.

## Preview and privacy contract

1. Dry-run never calls writable `connect()` or `initialize()`, creates no parent/database/WAL/SHM/journal/backup, and issues no command-authored durable write.
2. An absent store returns an empty preview without creating anything. An unreadable or incompatible existing store fails unchanged; no writable fallback exists.
3. Resolve the configured database once. A valid target is one regular, single-link file; a configured symlink may name it, while dangling symlinks, hard-link aliases, orphan sidecars, and nonregular database/sidecar entries fail closed. Derive DB/WAL/SHM/journal paths only from the canonical target and open entries with no-follow semantics.
4. A checkpointed store with no WAL/SHM/journal is read into a verified in-memory SQLite image while a nonblocking POSIX shared record lock fences SQLite writers. Read through the locked descriptor, compare source device/inode/links/size/mtime/ctime before and after, ensure the canonical name still identifies that inode, and reject any appearing sidecar. Validate the SQLite header, normalize only the private image’s WAL read/write header bytes to rollback mode, require `Connection.deserialize`, and pass `PRAGMA quick_check`. This avoids opening the source through a WAL-capable VFS and never changes source bytes.
5. On Darwin/Linux with SQLite 3.22+, a store with existing WAL and SHM sidecars opens the standard Unix VFS with `mode=ro&cache=private&vfs=unix&readonly_shm=1`; it never uses `immutable=1`. After pinning `BEGIN`, recheck canonical DB/WAL/SHM identity; validate WAL and duplicate SHM headers, checksums, matching salts, frame sizing, every SHM-committed frame’s page/salt/rolling checksum, and the SHM snapshot frame checksum; then run `quick_check`. A committed row resident in WAL must be visible without changing source artifacts. Missing, malformed, mismatched, unreadable, replaced, or nonregular sidecars fail without creation; an active rollback journal always fails closed. There is no writable or disk-staging fallback.
6. Both paths enable and verify query-only mode, use a bounded busy timeout, start `BEGIN`, and perform schema/version validation before counts. Unsupported platforms, locking, or SQLite features fail closed.
7. Tests cover a checkpointed WAL store without sidecars and prove the deserialize branch, a contending checkpointed writer, a quiescent external writer holding a committed WAL-only row, canonical symlink resolution, unsafe aliases, malformed/mismatched sidecars, a valid WAL missing SHM, a corrupt committed frame, and a partial trailing frame. Before/after DB/WAL/SHM/journal hashes, device/inode, mode, owner, links, size, `mtime_ns`, `ctime_ns`, and directory inventory remain equal; `atime` is excluded. Concurrent-writer tests assert blocking/failure rather than claiming WAL/SHM byte stability while that writer changes them.
8. `candidate_count` is uncapped. `candidate_sample` is deterministic and capped at 20, with only `id`, canonical `scope`, `reason_code`, and compression `keeper_id`. It excludes namespace, title, content, summary, tags, links, source references, session IDs, CWD, and timestamps.
9. The entire unredacted lifecycle payload is local-sensitive because filters may expose exact namespace metadata and samples expose local IDs.

## Output contract

| Field | Type and semantics |
| --- | --- |
| `result`, `command` | Existing result and command names. |
| `dry_run` | Boolean for cleanup/compress; absent on restore. |
| `scope`, `namespace` | Exact applied filters or `null`; preserve legacy `scope: null`. |
| `whole_store` | `true` only when both filters are absent. |
| `candidate_count` | Uncapped planned archive count; `null` when planning did not complete. |
| `candidate_sample` | At most 20 allowlisted metadata rows. Cleanup reason is `older_than_cutoff`; compression reason is `duplicate_unpinned`. |
| `candidate_sample_truncated` | `candidate_count > len(candidate_sample)` when the count is known; false before planning. Failure samples are empty and report true when a known nonzero plan is intentionally withheld. |
| `changed_count` | Zero for preview and verified nonpublication; committed update count for successful apply; `null` when commit outcome is unknown. |
| `entry_count`, `archive_count` | Actual counts after successful preview/apply; `null` on failure to avoid unverified post-failure claims. |
| `projected_entry_count`, `projected_archive_count` | Preview projection; equal actual counts after successful apply; `null` on failure. |
| `moved`, `removed` | Existing aliases: preview candidate count or committed changed count; zero on verified nonpublication and `null` when commit outcome is unknown. |
| `before`, `after` | Compression’s existing actual active counts. Dry-run keeps `after == before`; projected fields carry the preview delta. |
| `automatic_export`, `recovery_steps` | Always `false` and bounded static guidance; no generated path or content. |
| transaction fields | `transaction_outcome=not_started|rolled_back|committed|unknown`, `commit_attempted`, and failure-only `failure_phase=open|begin|plan|archive|commit`. Dry-run is `not_started`; successful apply is `committed`. |
| failure fields | Nonzero `FAIL` with stable `reason_code`, local `error`, empty sample, and no partial-success claim. Pre-plan failures use unknown candidate/count fields; verified rollback uses zero change aliases; commit ambiguity uses a `*_commit_outcome_unknown` reason and null change aliases. |

## Candidate selection

### Cleanup

- Select active, unpinned rows older than the cutoff after applying scope/namespace filters.
- Order candidates by chronological age then stable ID.

### Compression

- Filter before grouping.
- Use collision-safe tagged tuple identities:
  - `("source", source_type, source_ref)` when both source fields exist;
  - `("content", scope, namespace, title, summary, content)` otherwise.
- Source-backed identity requires both fields to remain nonempty after trimming and uses the trimmed values.
- Keeper order is `julianday(updated_at) DESC`, `julianday(created_at) DESC`, raw `updated_at DESC`, raw `created_at DESC`, then stable `id DESC`; invalid dates sort after valid dates.
- Preserve every pinned duplicate. If any pinned row exists, only unpinned duplicates are candidates and `keeper_id` is the newest pinned row under that order. Without pins, retain one newest row under the same order.
- Compression candidates and samples order by candidate ID ascending. Cleanup orders by chronological age ascending then ID ascending.

## Apply and recovery contract

1. Apply opens normally, executes `BEGIN IMMEDIATE` before candidate selection, selects and mutates on one connection, uses one operation timestamp, and commits once.
2. Apply tracks `open`, `begin`, `plan`, `archive`, and `commit` phases. Counts and success payload are computed before commit; no unguarded database work follows a successful commit. Connection finalization errors are caught as additive warnings and cannot replace the committed success result. Busy, planner, update, or commit failure while the transaction remains active must roll back and verify `in_transaction=false`, reporting `transaction_outcome=rolled_back` and zero committed changes. A failure before transaction acquisition is `not_started`.
3. If `commit()` raises after the transaction is no longer active, or rollback cannot be verified, publication is ambiguous: return nonzero with `transaction_outcome=unknown`, `commit_attempted=true` for commit ambiguity, a stable `*_commit_outcome_unknown` reason, and null changed/alias counts. Never claim rollback. Recovery guidance instructs the operator to inspect/export before retrying.
4. FTS continues to mirror all canonical rows, active and archived; status-only archive/restore does not delete FTS rows. Doctor retains active `memory_count` and additively reports `archive_count` and `total_memory_count`; it compares FTS against total rows.
5. No automatic export is created. Preview/apply output states `automatic_export=false` and provides bounded pre-export, single-ID restore, and full-import recovery guidance.
6. Restore uses the same transaction-outcome semantics. Its ordinary outcomes are additive and deterministic:
   - archived ID: `PASS`, `reason_code=memory_restored`, `outcome=restored`, `restored=1`, `changed=true`;
   - active ID: idempotent `PASS`, `reason_code=already_active`, `outcome=already_active`, `restored=0`, `changed=false`, timestamp unchanged;
   - missing ID: nonzero `FAIL`, `reason_code=memory_not_found`, `outcome=not_found`, `restored=0`, `changed=false`.

## Test matrix

1. Absent and initialized dry-runs prove physical non-writing behavior and that writable connect/initialize are unreachable.
2. Scope-only, namespace-only, combined, mismatch, invalid scope, duplicate/unknown flags, and unfiltered behavior are covered for cleanup and compression.
3. Candidate sample tests seed secrets in every excluded field, exceed 20 candidates, assert deterministic order/truncation, and inspect plain plus JSON output for leakage.
4. Mixed-offset cleanup timestamps and delimiter-containing duplicate fields freeze chronological and tuple-key behavior.
5. Zero, one, and multiple pinned duplicate groups prove every pin survives and eligible unpinned rows archive.
6. SQL trace proves `BEGIN IMMEDIATE` precedes candidate selection. Real writer lock plus injected planner, mid-update, and pre-publication commit failures prove complete rollback and zero committed reporting. Commit-then-raise tests for cleanup, compression, and restore prove durable publication is reported as unknown rather than rollback; a post-commit close failure preserves committed success with a warning.
7. FTS rows remain canonically equal across archive/restore; search hides archived rows and reveals restored rows; doctor is ready when FTS equals total rows and warns when one of at least two seeded FTS rows is missing. `/memory doctor` preserves the additive total/archive fields.
8. Restore success, repeat no-op, and missing-ID failure assert exact exit codes, existing `command`/`id`/`restored` keys, new fields, and timestamp stability. Duplicate `--id`, blank ID, unknown flags, and trailing arguments fail before open.
9. Compatibility assertions freeze legacy aliases, export v2/checksum behavior, no-filter `/gateway concise compress`, and additive command registration.

## Ordered slices

1. Add focused failing unit contracts in `tests/test_memory_lifecycle_command.py`.
2. Add the storage-owner read-only connection helper and doctor total-row invariant.
3. Implement shared parsing, filters, private samples, deterministic plans, and atomic mutation/restore helpers in `memory_lifecycle_command.py`.
4. Add one CLI-level selftest flow and update command/config/operator documentation.
5. Run focused, full, review, PR, merge, and cleanup gates.

## Production-to-test mapping

| Production seam | Required focused evidence |
| --- | --- |
| `shared_memory_runtime.connect_readonly` | Absent, locked in-memory checkpointed image, writer interleaving, WAL-only row through Unix read-only SHM, canonical symlink, hard-link/dangling rejection, missing/malformed/mismatched/nonregular sidecars, rollback journal, unsupported/open failure, quick-check, and filesystem invariants. |
| `shared_memory_runtime.doctor_report` | Active/archive/total compatibility, ready total-row FTS, stale nonempty FTS, and `/memory doctor` propagation. |
| Lifecycle parser/planners | Pre-open rejection, filters, privacy, cap/order, timestamps, tuple collisions, all-pin retention, and no-filter aliases. |
| Lifecycle transactional executor/restore | BEGIN ordering, real lock, planner/mid-update/pre-commit rollback, commit ambiguity, exact successful mutation, restore ambiguity, and three ordinary restore outcomes. |
| Gateway/config/docs | Unchanged applying gateway alias test, additive registration, usage/plain/JSON contracts, and selftest smoke. |
| Import/export | Production unchanged; regression-only export v2/checksum and import tests preserve the task_29 boundary. |

## Validation and review gates

1. Contract gate: critical changed-evidence plan review approves the revised hybrid preview and transaction-outcome contracts before delivery.
2. Preview gate: physical non-writing, privacy, selector, and compatibility tests pass; reviewer finds no live-path or output leak.
3. Mutation gate: contention/fault rollback, pin retention, FTS, restore, and gateway alias tests pass; reviewer finds no partial-commit or race gap.
4. Ship gate: Python compile, focused shared-memory suites, `git diff --check`, `make validate`, `make selftest`, `make install-test`, pre-commit, independent verifier, critical full-diff review, PR CI, and post-merge CI pass.

Review budget: three to five changed-evidence review/fix passes. Stop once all required checks are green and the latest critical review has no blocker.
