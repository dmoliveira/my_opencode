# Runtime DB schema

OpenCode runtime history lives in `~/.local/share/opencode/opencode.db` by default.

Use these read-only inspection patterns:

```text
sqlite3 -readonly ~/.local/share/opencode/opencode.db ".tables"
sqlite3 -readonly ~/.local/share/opencode/opencode.db ".schema session"
sqlite3 -readonly ~/.local/share/opencode/opencode.db "PRAGMA table_info(part);"
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
