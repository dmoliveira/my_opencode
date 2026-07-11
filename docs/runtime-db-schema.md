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

Use the SQLite online backup API rather than copying a live `opencode.db` file. `/session repair-stale --apply --json` now creates a consistent pre-repair `backup_path` automatically. Keep that artifact outside a synced or shared directory because runtime history can contain prompts and tool output.

For a portable manual export, first stop OpenCode writers, then use the SQLite CLI backup command:

```text
sqlite3 <runtime_db_path> ".backup '<destination>/opencode-runtime-backup.sqlite3'"
sqlite3 -readonly <destination>/opencode-runtime-backup.sqlite3 "PRAGMA integrity_check;"
```

To restore, preserve the current database first, stop OpenCode, and use SQLite's restore command rather than overwriting files while a WAL writer is active:

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
| OpenCode runtime history | platform-specific `opencode.db` | OpenCode | Inspect read-only; use `/session repair-stale` only with preview, scope, backup, and explicit apply. |
| Shared memory | `~/.config/opencode/my_opencode/runtime/shared_memory.db` | my_opencode | Use lifecycle commands; export before import/cleanup/compression. |
| Codememory task graph | `.codememory/codememory.sqlite3` | Codememory | Use `oc`; do not hand-edit or mix it with runtime-history recovery. |
| Session sidecars | `~/.config/opencode/sessions/index.json` and digests | my_opencode | Owner-only files; recover malformed data before rewriting. |

A backup or restore applies to exactly one store. Never replace the OpenCode runtime DB with shared-memory or Codememory artifacts, and do not run destructive operations while the owning process is active.

## Recovery drill checklist

1. Stop the process that owns the affected store; do not delete WAL/SHM files by hand.
2. Record `/session doctor --json` output and copy the affected database using SQLite `.backup`.
3. Run `PRAGMA integrity_check` on the backup. If it fails, quarantine the original with owner-only permissions and restore the latest verified backup.
4. For a malformed session index, preserve the file unchanged, repair or replace it from a known-good copy, then run `/digest run` and `/session doctor --json`.
5. For a failed shared-memory import or lifecycle operation, export the current store first, restore the pre-operation export, and verify recall/order before re-enabling writers.
6. Confirm recovery with the owner command (`/session doctor`, shared-memory status, or `oc plan doctor`) and record the incident without copying sensitive runtime content into tickets.

## Sanitization and deletion

Treat local AI history as sensitive data. Before deleting or redacting any store, stop its owner, create a verified SQLite backup/export, and list the target path with `ls -l` or the owner status command. Prefer store-level operations that show scope and counts first; never recursively remove a parent configuration directory.

For runtime history, use an isolated copy to test a query or restoration path before replacing the live database. For shared memory, export first and use lifecycle `--dry-run` before cleanup/compression. For session sidecars, preserve malformed files for recovery analysis rather than overwriting them. For Codememory, use `oc` state changes rather than direct SQLite edits.

## Operator dashboard fields

Use `/doctor run --json` for the consolidated session and shared-memory checks. The session check exposes `runtime_db_path`, `runtime_db_size_bytes`, `runtime_db_scan_duration_ms`, journal mode, SQLite version, JSON1 support, required-table compatibility, and stale finding counts. The shared-memory check reports its store path and active/archive counts. Session-index update output reports its path, retention policy, and pruning totals. These fields are designed for automation-safe dashboards; do not scrape human-formatted output.

## Backup retention policy

Keep at least three verified runtime-history backups: the latest pre-repair backup, the latest successful manual/export backup, and one older recovery point. Store backups outside synchronized project directories with owner-only permissions. Before pruning a backup, run `PRAGMA integrity_check` on the candidate and retain any backup referenced by an unresolved incident. Automated cleanup must be previewable and must never delete the only verified backup.
