---
status: done
priority: high
updated: 2026-07-30
---

# SQLite Failure-Mode Regression Coverage

## Objective

Complete Codememory `task_22` with deterministic automated coverage for locked databases, malformed JSON, logical index/schema failures, interrupted operations, permission failures, and safe repair behavior. This work starts after PRs #673 and #674; their session-sidecar tests remain regression gates rather than duplicate scope.

## Classification and constraints

- Depth: large.
- Risk: high because fixtures exercise runtime-history repair, online backup, WAL behavior, and shared-memory transactions.
- Use synthetic temporary databases only. Never open or mutate a live user store.
- Use barriers, pre-acquired locks, and injected faults. Do not use timing sleeps.
- Keep waits bounded and assert SQLite primary result codes where available.
- Runtime history stays read-only except explicit stale-repair fixtures. Shared memory owns and may initialize its schema.
- Test logical missing/wrong indexes and schema versions, not physical page corruption.
- Do not add public reason codes, migrations, restore automation, WAL deletion/checkpoint behavior, or sidecar behavior.

## Behavioral matrix

### Runtime-history SQLite

1. A real rollback-journal lock fixture sets and verifies `journal_mode=DELETE`, pre-acquires `BEGIN EXCLUSIVE`, and injects a short busy timeout. Diagnosis returns `runtime_query_failed`, leaves scan completion false, emits no partial findings, and preserves logical state. WAL remains a separate concurrent-reader snapshot fixture.
2. Malformed relevant/latest `message.data` or `part.data` fails closed as `runtime_query_failed`; it is never normalized. Schema and JSON1 preflight take precedence, so a missing schema reports `runtime_schema_incompatible` before row JSON is evaluated.
3. Missing or wrong index prefixes select `legacy_fallback`, retain equivalent findings, and create no schema objects.
4. Missing required tables return `runtime_schema_incompatible` with no stale queries or partial findings.
5. Injected open/permission denial returns `runtime_db_open_failed` and creates no database or backup. A POSIX chmod smoke is conditional on a non-root host.
6. Online backup is queryable, passes `PRAGMA integrity_check`, and includes a committed row still resident in a nonempty WAL while its writer remains open with auto-checkpoint disabled.
7. Backup faults use a deterministic UUID and an unrelated sibling sentinel. A destination-open failure may create the expected partial path before raising; a separate `source.backup()` interruption occurs after both connections open. Both close every opened connection, remove only the current partial artifact, and preserve the sibling.
8. Repair preview and unconfirmed generic apply produce no backup or mutation.
9. Scoped apply creates a pre-state backup that passes `PRAGMA integrity_check` and has canonical rows equal to the pre-apply source. Repair changes only selected stale evidence while retaining unrelated rows and unknown JSON fields.
10. A compare-and-swap race uses a `stale_running_tool` candidate and, after candidate scan but before `BEGIN IMMEDIATE`, atomically changes either `message.time.completed` or `part.state.status` to a terminal value. It leaves the raced JSON bytes exact and reports `repaired_count == 0` and `repairs == []`.
11. A first-round commit failure after an update rolls back all logical changes and reports zero committed repairs. Repair reports are staged per transaction and published only after its commit; a later failed round must not hide reports from an earlier committed round.

### Shared-memory SQLite

1. Two pre-opened WAL connections exercise a real `BEGIN IMMEDIATE` writer lock. The contender uses a finite busy timeout, raises with `(sqlite_errorcode & 0xFF) == sqlite3.SQLITE_BUSY`, and commits no row.
2. Malformed persisted `tags_json` or `links_json` raises during materialization without changing rows.
3. An absent store initializes schema v1; a dropped owned secondary index is recreated without row changes. The incompatible-version fixture starts as a fully formed WAL store and changes only the stored version; opening may repeat idempotent schema/journal setup, but it must raise with rows and version unchanged. Fail-before-write version handling is outside this task.
4. Injected open/permission denial leaves an existing logical store unchanged. A POSIX chmod smoke is conditional.
5. Malformed import JSON preserves the current `json.JSONDecodeError` contract; checksum mismatch, incompatible export schema, and invalid entry containers return their existing failure envelopes. Every case occurs before database connection or backup. Structured malformed-JSON output is outside this task.
6. A fault on the second imported row rolls back the first. Canonical `memories` and conditional `memory_fts` rows remain unchanged. The pre-import export remains checksum-valid and imports successfully into a second empty temporary store with canonical equality. FTS availability is injected so host capabilities do not select the expected result.
7. Every lifecycle-import test patches `MY_OPENCODE_SHARED_MEMORY_PATH`, reloads `shared_memory_runtime` and then `memory_lifecycle_command`, and asserts the effective database path is below the active temporary directory before calling the command.

## Existing coverage and delta map

| Area | Classification | Exact delta |
| --- | --- | --- |
| Runtime indexed/fallback equivalence | Extend `tests/test_session_runtime_database.py:239-307` | Add pre/post `sqlite_master` and canonical-row equality; do not add a parallel fallback test. |
| Runtime open/schema/JSON1 failures | Extend `tests/test_session_runtime_database.py:401-500` | Add schema/file nonmutation and a spy proving stale queries do not run. |
| Runtime WAL snapshot/nonmutation | Reuse `tests/test_session_runtime_database.py:546-641` | Add only the committed-uncheckpointed-WAL online-backup case. |
| Runtime backup readability | Extend `tests/test_session_runtime_database.py:67-80` | Add integrity check, WAL row, destination-open cleanup, and mid-backup interruption. |
| Runtime lock and malformed queried JSON | New in `tests/test_session_runtime_database.py` | Add rollback-journal lock and message/part cases with empty partial output. |
| Runtime repair preview/apply | Reuse `scripts/selftest.py:2930-3149` | Add direct preview/gating spies, CAS race, scoped backup assertions, and transaction-report rollback tests only. |
| Shared-memory timestamps/order | Reuse `tests/test_shared_memory_runtime.py` | Keep unchanged. |
| Shared-memory failure modes | New `tests/test_shared_memory_failure_modes.py` | Add contention, malformed rows/imports, schema/index/version, permission, and import rollback cases. |
| Session sidecars/index/promotion | Reuse task_14 suites | Validation-only; no duplicate tests or edits. |

## Mutation evidence

- Quiescent diagnosis: compare SHA-256, canonical rows, and sorted `sqlite_master` entries.
- Active WAL/lock: compare logical rows after releasing the writer; WAL/SHM byte stability is not required.
- Failed repair: the pre-repair backup is the only allowed new durable artifact.
- Shared-memory schema initialization/index repair: only declared schema objects may change; rows and schema version remain stable.
- Failed import: compare canonical `memories` plus conditional `memory_fts` rows/counts, validate the pre-import export checksum, and import that export into a second empty temporary store for canonical comparison.

## Production-code boundary

Work test-first. A deterministic regression may expose an existing cleanup or reporting defect. A production edit is allowed only when all of the following are true:

1. the new test proves a frozen invariant above;
2. the edit is the smallest local correction at the exercised seam;
3. it adds no command, schema, migration, or public reason code;
4. focused old and new tests remain green; and
5. the runtime/security review gate explicitly approves it.

The only permitted production corrections are:

1. `_backup_runtime_database` closes the source when destination creation fails, closes both connections after an interrupted backup, and removes only its deterministic partial artifact.
2. `_repair_runtime_stuck_sessions` stages reports per transaction and extends the committed report list only after `commit()` succeeds.

Shared-memory version preflight redesign, structured malformed-import output, or broad lifecycle connection cleanup becomes a separate Codememory task.

## Ordered slices

1. Extend existing cases in `tests/test_session_runtime_database.py`, then add only the new lock, relevant malformed JSON, backup-fault/WAL, repair CAS, and committed-report cases.
2. Add `tests/test_shared_memory_failure_modes.py` for lock, malformed rows/imports, schema/index handling, permission errors, and import rollback.
3. Apply only test-proven local production corrections allowed by the boundary above.
4. Run existing session-sidecar/index/promotion suites unchanged, then full validation and delivery.

## Validation and review gates

1. Contract review: this plan receives `APPROVE` before runtime work.
2. Runtime-history gate: tests embed 20 bounded, self-cleaning iterations for rollback-journal lock, barrier-driven concurrent WAL snapshot, and CAS interleaving. These loops run identically under targeted local commands and normal unittest discovery in Darwin and Ubuntu CI. Reviewer finds no unsafe fixture or incorrect mutation claim.
3. Shared-memory gate: tests embed 20 bounded, self-cleaning iterations only for real WAL writer contention. Deterministic interrupted-import injection runs once. Injected permission and FTS-unavailable tests are mandatory; POSIX chmod smoke may skip only for root/unsupported hosts and restores modes in `finally`.
4. Ship gate: existing sidecar suites, one Darwin Python 3.11+ run, Ubuntu CI Python 3.11/3.12, `make validate`, `make selftest`, `make install-test`, pre-commit, full-diff review, and PR CI are green. Post-merge CI is closeout evidence after merge.
