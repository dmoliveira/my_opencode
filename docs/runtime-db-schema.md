# Runtime DB schema

OpenCode runtime history lives in a platform-specific `opencode.db` path by default. This repo resolves it automatically in `scripts/session_command.py`, prefers `MY_OPENCODE_RUNTIME_DB_PATH` when set, and commonly lands at `~/.local/share/opencode/opencode.db` on Linux or `~/Library/Application Support/opencode/opencode.db` on macOS. Use `/session doctor --json` or `/gateway doctor --json` to confirm the exact resolved `runtime_db_path` before direct SQLite inspection when needed.

Use these read-only inspection patterns:

```text
sqlite3 -readonly <runtime_db_path_from_session_doctor> ".tables"
sqlite3 -readonly <runtime_db_path_from_session_doctor> ".schema session"
sqlite3 -readonly <runtime_db_path_from_session_doctor> "PRAGMA table_info(part);"
```

On protected branches, keep direct SQLite inspection to narrow read-only forms such as `.tables`, `.schema`, `PRAGMA table_info(...)`, and `SELECT ...`.

Core tables:

- `session`: one row per OpenCode session. Important scalar columns include `id`, `project_id`, `parent_id`, `directory`, `title`, `time_created`, and `time_updated`.
- `message`: one row per message. Structured fields like role live inside the JSON `data` column.
- `part`: one row per message part. Structured fields like part type, tool name, tool state, and text live inside the JSON `data` column.

Common query gotchas:

- use `session.directory`, not `session.cwd`
- use `json_extract(message.data, '$.role')`, not `message.role`
- use `json_extract(part.data, '$.type')`, not `part.type`
- use `json_extract(part.data, '$.tool')` and `json_extract(part.data, '$.state.status')` for tool parts
- avoid `REGEXP` unless you register a custom SQLite function; stock `sqlite3` here does not provide it

Examples:

```sql
SELECT id, directory, title
FROM session
ORDER BY time_updated DESC
LIMIT 20;
```

```sql
SELECT
  p.session_id,
  json_extract(m.data, '$.role') AS role,
  json_extract(p.data, '$.type') AS part_type,
  json_extract(p.data, '$.tool') AS tool_name,
  datetime(p.time_created / 1000, 'unixepoch') AS created_at
FROM part p
JOIN message m ON m.id = p.message_id
WHERE json_extract(p.data, '$.type') = 'tool'
ORDER BY p.time_created DESC
LIMIT 20;
```

```sql
SELECT
  p.session_id,
  substr(json_extract(p.data, '$.state.input.command'), 1, 160) AS command,
  json_extract(p.data, '$.state.metadata.exit') AS exit_code
FROM part p
WHERE json_extract(p.data, '$.type') = 'tool'
  AND json_extract(p.data, '$.tool') = 'bash'
  AND lower(coalesce(json_extract(p.data, '$.state.input.command'), '')) LIKE '%sqlite%'
ORDER BY p.time_created DESC
LIMIT 20;
```

## Backup and recovery

Use the SQLite online backup API rather than copying a live `opencode.db` file. `/session snapshot-runtime --json` creates a verified private bundle for the exact active runtime path, while `/session repair-stale --apply --json` creates a consistent pre-repair `backup_path` automatically. Keep either artifact outside synced or shared directories because runtime history can contain prompts, paths, tool inputs, and tool output.

The snapshot command defaults to `${XDG_STATE_HOME:-~/.local/state}/my_opencode/runtime-history-snapshots`; override it with `--output-dir` or `MY_OPENCODE_RUNTIME_SNAPSHOT_OUTPUT_DIR`. It preflights space for two logical copies plus reserve, uses SQLite Online Backup, runs `quick_check` by default or full `integrity_check` with `--full-integrity-check`, hashes the result, and asks the installed OpenCode binary to open a disposable isolated copy. A successful application open establishes readability only; it is not an import or restoration contract.

Each published bundle is a private `0700` directory containing exactly:

```text
runtime.sqlite3  # 0600 consistent SQLite backup
manifest.json    # 0600 source/application metadata, hash, checks, timing, limits
```

A completed Online Backup represents a consistent state reached while the backup ran, not necessarily the state at invocation. It does not write database or WAL content. With an active WAL database, the read-only SQLite reader can update transient coordination/read-mark bytes in the source SHM file. The command repeatedly rejects unsafe source generations and database identity replacement, but Python's path-based SQLite source API cannot exclude a malicious same-UID swap-and-restore race. Backup output, manifest creation, hashing, checks, and cleanup stay bound to open staging descriptors. Publication uses an atomic no-replace rename. If that rename succeeds but destination-directory synchronization fails, the command reports the existing bundle as committed with uncertain durability instead of deleting it.

For an offline manual export, first stop OpenCode writers, then use the SQLite CLI backup command:

```text
sqlite3 <runtime_db_path> ".backup '<destination>/opencode-runtime-backup.sqlite3'"
sqlite3 -readonly <destination>/opencode-runtime-backup.sqlite3 "PRAGMA integrity_check;"
```

There is no supported `/session` import command. For emergency manual restoration, preserve the current database first, stop OpenCode, and use SQLite's restore command rather than overwriting files while a WAL writer is active:

```text
sqlite3 <runtime_db_path> ".backup '<destination>/opencode-runtime-before-restore.sqlite3'"
sqlite3 <runtime_db_path> ".restore '<source>/opencode-runtime-backup.sqlite3'"
sqlite3 -readonly <runtime_db_path> "PRAGMA integrity_check;"
```

Do not run restore against an active OpenCode process. Use `/session doctor --json` after recovery to verify table compatibility, JSON1 support, journal mode, and stale-session findings.

## Store boundaries

This repository operates separate local stores with different ownership and safety rules:

| Store | Default location | Owner | Mutation rule |
| --- | --- | --- | --- |
| OpenCode runtime history | platform-specific `opencode.db` | OpenCode | Inspect content read-only; use `/session repair-runtime-permissions` only for descriptor-bound mode narrowing, and `/session repair-stale` only with preview, scope, backup, and explicit apply. |
| Shared memory | `~/.config/opencode/my_opencode/runtime/shared_memory.db` | my_opencode | Use lifecycle commands; export before import/cleanup/compression. |
| Codememory task graph | `.codememory/codememory.sqlite3` | Codememory | Use `oc`; do not hand-edit or mix it with runtime-history recovery. |
| Session sidecars | `~/.config/opencode/sessions/index.json`, `~/.config/opencode/digests/last-session.json`, and `${XDG_STATE_HOME:-~/.local/state}/my_opencode/quarantine/session-index` | my_opencode | Require current-user-owned regular single-link `0600` files; preview permission repair before explicit apply. |

A backup or restore applies to exactly one store. Never replace the OpenCode runtime DB with shared-memory or Codememory artifacts, and do not run destructive operations while the owning process is active.

## Runtime-artifact privacy

`/session doctor` reports one exact runtime directory and its database, WAL, and SHM permission states. `/session repair-runtime-permissions --json` is a mutation-free preview. Add `--apply` only when its `--db-path`, if supplied, exactly matches current runtime resolution. Apply narrows the current-user-owned runtime directory to `0700`, the existing main database to `0600`, and every safely bound WAL/SHM generation present at stable completion to `0600`. The command opens through verified parent authority with `O_NOFOLLOW`, checks file type, owner, link count, mode, device, inode, and path identity, then uses descriptor-bound `fchmod`. It does not replace files, write database content, delete sidecars, or run SQLite maintenance.

The live chmod path tolerates SQLite size and timestamp changes while preserving identity/security checks. Parent and database repairs happen before a fixed three-attempt WAL/SHM convergence loop. Missing WAL/SHM files are valid; linked, symlinked, foreign-owned, non-regular, permission-adding, replaced, or persistently churning targets fail closed. `changed_count` counts completed descriptor mode changes, and `partial=true` means an earlier narrowing remains after a later failure. Stop OpenCode and retry when convergence fails. Restoring `0644` or another broader mode is a manual emergency-only rollback that can expose private history; the command never performs it.

After the active database is `0600`, the tested Darwin OpenCode `1.18.10` SQLite runtime recreated WAL and SHM as `0600` under umask `0022`, and `PRAGMA quick_check` returned `ok`. Treat that as a tested runtime contract, not a guarantee for every SQLite VFS or future build. Fresh main-database creation remains umask-dependent and is outside this remediation command: allow OpenCode to create its store, then preview/apply hardening. The `0700` parent is the lasting confidentiality boundary. Restart OpenCode after installing this configuration change, then repeat doctor and a controlled write/recreation check before relying on a new runtime version.

## Session-sidecar privacy

The session index and last-session digest are local-sensitive state. New parent directories are created as `0700`; sidecars, persistent lock files, and quarantine artifacts are `0600`. Reads are bounded to 16 MiB for the index and 1 MiB for the digest. Readers reject symlinks, hard links, non-regular files, foreign ownership, permissive modes, unsafe ancestors, and identity changes before parsing content. Unsupported platforms fail closed.

Treat these persisted values as sensitive:

- working directories, session IDs, plan IDs, plan paths, and digest/index/quarantine paths;
- reasons, branches, branch headers, Git status previews, and change counts;
- plan status, resume hints, interruption details, timestamps, and event history;
- post-session command text and results;
- quarantine checksums, byte counts, and local recovery metadata.

Local doctor and recovery output may include paths, modes, reason codes, quarantine checksums, and byte counts. It is intended for the operator on the same machine. Only the fixed projections from `/session search --redact` and `/session handoff --redact` are share-safe. Do not copy unredacted doctor, digest, index, handoff, or quarantine output into tickets or chat.

`/session doctor` is observation-only. Use `/session repair-sidecars --json` for a mutation-free preview and add `--apply` only after reviewing both active targets. Apply narrows safe permissions in place and preserves bytes and inode identity. Missing and already-private files are no-ops. Aliased, linked, foreign-owned, non-regular, unsafe, or permission-adding repairs are blocked before either target changes. The command never repairs lock files, directories, or quarantine artifacts.

A permissive corrupt index is not parsed or quarantined. First narrow it explicitly with `/session repair-sidecars --apply --json`; then rerun `/digest run --reason manual`. The second command can classify the unchanged bytes and publish an independent private quarantine artifact. Never replace, reset, delete, or rebuild a corrupt active index automatically.

## Recovery drill checklist

1. Stop the process that owns the affected store; do not delete WAL/SHM files by hand.
2. Record `/session doctor --json` output and copy the affected database using SQLite `.backup`.
3. Run `PRAGMA integrity_check` on the backup. If it fails, quarantine the original with owner-only permissions and restore the latest verified backup.
4. For a malformed session index, inspect the hash-addressed quarantine copy reported by `/digest run`, leave the active file unchanged until writers are stopped, repair or replace it from a known-good copy, then rerun `/digest run --reason manual` and `/session doctor --json`.
5. For a failed shared-memory import or lifecycle operation, export the current store first, restore the pre-operation export, and verify recall/order before re-enabling writers.
6. Confirm recovery with the owner command (`/session doctor`, shared-memory status, or `oc plan doctor`) and record the incident without copying sensitive runtime content into tickets.

## Sanitization and deletion

Treat local AI history as sensitive data. Before deleting or redacting any store, stop its owner, create a verified SQLite backup/export, and list the target path with `ls -l` or the owner status command. Prefer store-level operations that show scope and counts first; never recursively remove a parent configuration directory.

For runtime history, use an isolated copy to test a query or restoration path before replacing the live database. For shared memory, export first and use lifecycle `--dry-run` before cleanup/compression. For session sidecars, preserve malformed files for recovery analysis rather than overwriting them. For Codememory, use `oc` state changes rather than direct SQLite edits.

## Operator dashboard fields

Use `/doctor run --json` for the consolidated session and shared-memory checks. The session check exposes `runtime_db_path`, `runtime_db_size_bytes`, `runtime_db_scan_duration_ms`, `runtime_db_scan_timeout_ms`, query-only verification, snapshot/scan completion, remediation codes, journal mode, SQLite version, JSON1 support, required-table compatibility, stale finding counts, `runtime_permission_status`, `runtime_permission_reason_code`, `runtime_permission_apply_allowed`, and `runtime_permission_findings`. Missing schema or JSON1 support skips stale queries instead of returning partial findings. The shared-memory check reports its store path and active/archive counts. Session-index update output reports its result, stable reason code, corruption kind, active path, quarantine path/checksum/byte count/reuse state, recovery steps, retention policy, and pruning totals. These fields are designed for automation-safe local dashboards; do not scrape human-formatted output or publish local paths and hashes.

`stuck_findings` contains sessions backed by structural lifecycle evidence, such as a latest running tool whose completion state is inconsistent with its delegated child. `generic_stale_findings` contains age-based incomplete assistant history without that structural evidence; it is not a confirmed stuck classification. `generic_stale_count` is the uncapped logical count, while the returned generic rows are capped at 20. Indexed and compatibility scans select one latest message per session and one latest part per message by `time_created DESC, id DESC`; equal-age parent/child results then order by parent ID and child ID, and single-session results order by session ID. These stable tie-breaks are applied before the 20-row limits and before lifecycle predicates are evaluated.

## Backup retention policy

Keep at least three verified runtime-history backups: the latest pre-repair backup, the latest successful manual/export backup, and one older recovery point. Store backups outside synchronized project directories with owner-only permissions. Before pruning a backup, run `PRAGMA integrity_check` on the candidate and retain any backup referenced by an unresolved incident. Automated cleanup must be previewable and must never delete the only verified backup.

## Optional encrypted backups

Use an external, organization-approved encryption tool such as `age` or your platform key-management service; do not place keys, passphrases, or recipient secrets in repository configuration. Encrypt only after creating and integrity-checking the SQLite backup. Keep the plaintext backup only for the minimum recovery window, verify decryption into a temporary owner-only directory, and run `PRAGMA integrity_check` again before a restore drill.

## Restore verification

Verify every restore against a disposable copy before touching the live runtime store: run `PRAGMA integrity_check`, inspect expected table/index inventory through `/session doctor --json`, compare a bounded session count or known session ID, and confirm the restored database remains readable with a read-only URI. Only then stop OpenCode, preserve the current store as a rollback backup, restore, and re-run the same checks.

## Corruption quarantine

When a local store is malformed, preserve it before any recovery write: remove group/world access from the recovery copy, place it outside active configuration, record its SHA-256 checksum and integrity-check output, then restore only from a verified backup. Do not rename or delete `-wal`/`-shm` files while the owning process is running.

Session-index writers classify invalid UTF-8, malformed JSON, invalid v1 containers, and invalid v1 session records as corruption. Every existing index is opened without following the final path component and must be a stable, current-user-owned regular single-link file before parsing. While holding the cooperative index lock, a corrupt source that passes those checks is copied byte-for-byte and published as one `0600` hash-addressed artifact in a `0700` quarantine directory. The default directory is `${XDG_STATE_HOME:-~/.local/state}/my_opencode/quarantine/session-index`; set `MY_OPENCODE_SESSION_INDEX_QUARANTINE_DIR` to use another private path outside active configuration. Existing byte-identical artifacts are reused; collisions, unsafe paths, and unsupported security primitives fail closed without claiming preservation. The active corrupt file is never moved, deleted, reset, or rebuilt automatically. Unsupported versions and ordinary I/O failures are reported without quarantine. Reader commands stay read-only and never create quarantine artifacts.

Successful preservation still returns `FAIL`: stop session-index writers, inspect the reported quarantine path and checksum locally, repair or replace the active index from a verified source, run `/digest run --reason manual`, and finish with `/session doctor --json`. `/digest show` remains observational, while `/digest run`, `/digest doctor`, session readers, and the consolidated doctor return nonzero for an unavailable corrupt index. Redacted search and handoff expose only the fixed `session_index_unavailable` code.

## Shared-memory retention profiles

Use `memory-lifecycle cleanup --older-days <n> --scope <scope> --namespace <exact-name> --dry-run --json` before archival. A conservative profile keeps 30 days of unpinned records; a focused project profile can use a shorter period only after exporting a verified recovery artifact. Pinned records are excluded from cleanup. Dry-run opens an existing store without initialization or command-authored source writes, reports actual and projected counts, and returns at most 20 content-free candidate records; the unredacted output remains local-sensitive because it contains IDs and exact filter metadata. Apply the exact same filters and age shown by preview, then use `memory-lifecycle restore --id <id>` for an explicit single-record undo.

## Pinned-memory lifecycle

Pin only durable, high-signal records needed across sessions. Cleanup never archives pinned records; compression preserves every pinned duplicate and archives only eligible unpinned copies. Cleanup and compression acquire one immediate transaction before planning any apply, then commit once or roll back completely. A failure with `transaction_outcome=unknown` means the commit may already be durable; inspect and export current state before retrying. Lifecycle operations do not create automatic exports: export to a private path before broad apply, use explicit restore for one ID, and import the verified export for full rollback.

## Temporary-file policy

Create local data intermediates only with owner-controlled temporary files in the destination directory, flush and fsync before atomic replacement, and remove failed intermediates. Never use predictable names for exports, recovery copies, or sidecars. Keep decrypted restore material in an owner-only temporary directory and remove it only after verification and handoff are complete.

## SQLite status dashboard

Use `/doctor run --json` as the operator dashboard entry point. It includes the session doctor’s resolved path, candidate paths, index inventory, database/WAL footprint, configured budget, latency, schema compatibility, and sidecar permissions; it also includes shared-memory health. Alert on `WARN`/`FAIL`, schema mismatch, FTS mismatch, unsafe permissions, budget breach, and unexpected WAL growth.

## Incident bundle

A local incident bundle should contain machine-readable doctor output, store paths, schema/index/permission/size fields, remediation codes, integrity-check results, and checksums of quarantined backups. Exclude prompts, tool inputs/outputs, raw memory content, session reasons, CWD, branch previews, and encryption material. Generate support artifacts from redacted output only.

## Support export

Only `/session search --redact` and `/session handoff --redact` (or those commands with `MY_OPENCODE_SESSION_REDACT_DEFAULT=true`) have a share-safe output contract. The consolidated doctor output remains local and sensitive: it can contain store paths and runtime identifiers, so do not share it directly. Build support artifacts from the allowlisted redacted search/handoff fields, inspect them locally, and remove anything not required for the case. Never send a live database, SQLite WAL/SHM file, session index, digest, backup, or encryption metadata unless an approved secure transfer and explicit operator authorization exist.

## Storage telemetry history

Persist only bounded aggregate telemetry—timestamp, store category, byte footprint, WAL bytes, scan duration, schema state, and remediation codes. Do not persist paths, record content, session IDs, prompts, or user identifiers. Retain a short rolling window and use it for trend alerts, not audit reconstruction.

## Large-history fixture coverage

Performance fixtures should include realistic session/message/part cardinalities, equal-timestamp ties, active WAL files, representative JSON payload shapes, and bounded diagnostic output. Measure query latency and memory use against the configured scan budget; fixtures must contain synthetic data only.

## WAL and concurrent-writer fixtures

Test diagnostics against a live WAL database with deterministic barriers: establish the query-only reader snapshot first, commit a writer transaction second, then prove metadata and findings stay on the same pre-commit snapshot. Keep the busy timeout at or below the SQLite progress budget. Assert main-database bytes, schema, and row counts only in a separate quiescent fixture; WAL/SHM bytes can legitimately change while a writer is active.

## Interrupted-backup fixtures

Exercise interruption before backup creation, during SQLite online backup, after backup integrity verification, and before restore replacement. Confirm no partial artifact is treated as verified, source history remains untouched, failed temporary files are quarantined or removed safely, and a known-good backup remains recoverable.

## Import rollback fixtures

Create malformed and conflicting export fixtures that fail before, during, and after validation. Verify checksum/schema failures cause zero mutation; transactional failures leave counts/content unchanged; pre-import exports remain usable; and `--dry-run`, `--conflict skip`, and overwrite behavior produce deterministic JSON summaries.

## Compatibility matrix

Supported runtime diagnostics require verifiable SQLite query-only mode, JSON1, and window-function support; shared memory additionally uses WAL, FTS5 when available, foreign keys, and a compatible schema version. Runtime scans execute inside one explicit read transaction with a bounded progress handler and always roll back before close. Doctor output is authoritative for the installed runtime’s version, capability, snapshot, completion, journal, FTS, and schema state. Treat unsupported features as explicit remediation codes rather than attempting in-place upgrades of an upstream OpenCode database.

## Session-history archival

Archive runtime history by creating a verified SQLite backup/export, recording its integrity result and retention class, then applying the archival policy only while OpenCode is stopped. Do not delete selected rows from an upstream OpenCode database as a routine operation; retain a rollback copy and validate restored readability before changing the live store.

## Per-project shared-memory isolation

Set `MY_OPENCODE_SHARED_MEMORY_PATH` to a project-owned, owner-only SQLite path when isolation is required. Keep default shared memory only for intentionally cross-project context. Back up, export, retain, and restore each isolated store independently; do not point multiple unrelated projects at the same path without an explicit shared-memory policy.

## Optional analytics

Analytics are opt-in only. Collect aggregate health counters and latency/size buckets, never raw SQLite content, paths, IDs, prompts, commands, or backup metadata. Default to disabled, make the effective setting visible in status output, and provide a deletion/reset path for any local aggregate history.
