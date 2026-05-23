---
name: runtime-db-inspection
description: Use when read-only SQLite inspection of the OpenCode runtime database is needed for sessions, messages, parts, tool usage, or safe query patterns.
---

## Goal
Inspect the OpenCode runtime SQLite store safely and extract only the evidence needed for the current question.

## Use When
- the task mentions sqlite, runtime DB, sessions, messages, or parts
- runtime history or tool usage needs evidence
- the question is about stored OpenCode session behavior
- safe read-only query patterns are needed

## Do Not Use When
- Codememory or Git state already answers the question
- the task requires mutating runtime state
- broad data forensics is unnecessary

## First Steps
- Use `sqlite3 -readonly ~/.local/share/opencode/opencode.db ".tables"`.
- Use `.schema` or `PRAGMA table_info(...)` before guessing columns.
- Query `session.directory`, not a nonexistent `session.cwd`.
- Use `json_extract(...)` for `message.data` and `part.data` fields.

## Working Rules
- Keep queries read-only and narrow.
- Start from `session`, `message`, and `part` tables.
- Use `json_extract(part.data, '$.tool')` and related JSON paths for tool evidence.
- Avoid `REGEXP` in stock sqlite3 here.
- Prefer one focused query per question instead of a giant ad hoc dump.

## Evidence / Done
- Queried table and JSON paths are explicit.
- Result set answers the current question directly.
- Read-only posture was preserved.
- Follow-up query need is clear if the first pass was insufficient.

## References
- `docs/runtime-db-schema.md`
- `docs/command-handbook.md`
- `AGENTS.md`
