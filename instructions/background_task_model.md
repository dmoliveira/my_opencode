# Background Task Model (E2-T1)

This document defines the minimal safe model for async background jobs.

## Lifecycle

Allowed states:

- `queued`: job accepted and waiting for a worker slot.
- `running`: job process started and monitored.
- `completed`: process exited with code `0`.
- `failed`: process exited non-zero, timed out, or write/read validation failed.
- `cancelled`: explicitly cancelled by user or stale-timeout guard.

State transition rules:

- `queued -> running` when scheduler acquires a slot.
- `running -> completed|failed|cancelled` only once (terminal).
- `queued -> cancelled` allowed for pre-start cancellation.
- Terminal states are immutable except metadata enrichment (`ended_at`, `summary`).

## Persistence format

Storage root:

- `~/.config/opencode/my_opencode/bg/`

Files:

- `jobs.json` (authoritative index; atomic write with temp+rename).
- `runs/<job_id>.log` (stdout/stderr combined stream).
- `runs/<job_id>.meta.json` (execution metadata snapshot).

`jobs.json` schema (minimal):

```json
{
  "version": 1,
  "updated_at": "2026-02-13T00:00:00Z",
  "jobs": [
    {
      "id": "bg_20260213_abc123",
      "command": "python3 scripts/selftest.py",
      "cwd": "/repo/path",
      "created_at": "2026-02-13T00:00:00Z",
      "started_at": null,
      "ended_at": null,
      "status": "queued",
      "exit_code": null,
      "timeout_seconds": 1800,
      "stale_after_seconds": 3600,
      "labels": ["research"],
      "summary": null
    }
  ]
}
```

## Retention policy

- Keep terminal jobs for `14` days by default.
- Keep at most `200` terminal jobs; prune oldest first after TTL pass.
- Keep `running` jobs indefinitely unless stale guard triggers.
- On prune, remove both log and metadata sidecar files.

## Concurrency and stale-timeout defaults

- Max concurrent running jobs: `2`.
- Default execution timeout: `1800s` (30 minutes).
- Default stale timeout (no heartbeat/update): `3600s` (60 minutes).
- Stale handling: mark as `cancelled` with summary reason and attempt process termination.

## Determinism and safety constraints

- Single-writer lock on `jobs.json` to prevent corruption.
- Every state change appends an in-memory event and flushes atomically.
- Read operations never mutate state.
- Cancel is idempotent: cancelling terminal jobs returns success with no-op note.
