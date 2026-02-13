# Checkpoint Snapshot Lifecycle (E19-T1)

This document defines the baseline checkpoint snapshot model for Epic 19.

## Snapshot schema

Each snapshot is a single JSON document with deterministic top-level fields:

- `snapshot_id`: stable unique id (`cp_<timestamp>_<suffix>`).
- `created_at`: RFC3339 UTC timestamp.
- `run_id`: execution/session id associated with the snapshot.
- `source`: trigger source (`step_boundary`, `error_boundary`, `timer`, `manual`).
- `status`: execution status (`in_progress`, `failed`, `completed`, `paused`).
- `step_state`: current plan step summary.
- `context_digest`: compact context health and truncation summary.
- `command_outcomes`: recent command/tool outcomes since the previous snapshot.
- `integrity`: checksum + format version metadata.

`step_state` contract:

- `plan_path`, `step_id`, `step_ordinal`, `step_status`
- `todo_compliance` (`result`, `violations`, `checked_at`)
- `resume_hints` (`eligible`, `reason_code`, `next_actions`)

`context_digest` contract:

- `window_pressure` (`low`, `medium`, `high`)
- `protected_artifacts` (paths or ids)
- `dropped_items` (count only)
- `policy_profile` (active resilience profile id)

`command_outcomes` contract:

- array of bounded entries containing:
  - `kind` (`shell`, `slash_command`, `tool_use`)
  - `name`
  - `result` (`PASS`, `FAIL`, `WARN`)
  - `duration_ms`
  - `reason_code` (optional)
  - `summary`

## Trigger points and frequency

Snapshots are written at deterministic boundaries:

1. Step boundary
   - after step enters `in_progress`
   - after step reaches terminal state (`done`, `failed`, `skipped`)
2. Error boundary
   - immediately after a recoverable error is classified
   - immediately before a forced stop due to unrecoverable error
3. Timer boundary
   - periodic heartbeat every 120 seconds while a plan is `in_progress`
4. Manual boundary
   - explicit `/checkpoint` command request (future Task 19.3)

Coalescing rule:

- if two triggers fire within 3 seconds with no material state change, keep only one snapshot and append trigger source to `source_details`.

## Retention, rotation, and compression

Retention defaults:

- keep the latest 50 snapshots per run id.
- always preserve the latest `failed` snapshot and latest `completed` snapshot for that run.
- prune snapshots older than 14 days unless they are preserved terminal snapshots.

Rotation behavior:

- active file: `checkpoints/<run_id>/latest.json`
- immutable history: `checkpoints/<run_id>/history/<snapshot_id>.json`
- write order: temp file -> fsync -> atomic rename -> update `latest.json`

Compression policy:

- optional gzip for history snapshots older than 24 hours.
- never compress `latest.json`.
- keep checksum metadata for both compressed and uncompressed artifacts.

## Failure semantics

- corrupted snapshot files must not overwrite `latest.json`.
- parser/validation errors return deterministic reason codes:
  - `checkpoint_schema_invalid`
  - `checkpoint_integrity_mismatch`
  - `checkpoint_atomic_write_failed`
  - `checkpoint_retention_prune_failed`

## Non-goals for Task 19.1

- no runtime writer implementation yet (Task 19.2).
- no `/checkpoint` command handlers yet (Task 19.3).
- no end-to-end retention tests yet (Task 19.4).
