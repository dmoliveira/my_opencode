# SQLite Location and Retention Status

```text
/doctor sqlite status
/doctor sqlite status --json
/doctor sqlite status --json --redact
```

Outside the OpenCode command surface, run
`python3 scripts/doctor_command.py sqlite status --json`. This is a concise
operator view over the existing four-store `/doctor sqlite` diagnostic. Existing
`/doctor sqlite` and `/doctor sqlite --json` behavior is unchanged; use them for
full warnings, findings and owner-specific repair guidance.

## Fields

Each of `runtime_history`, `session_sidecars`, `shared_memory`, and `codememory`
has an owner-diagnostic health state, reported location, bounded file metadata,
privacy evidence and retention state. A missing, unsafe, unreported, relative or
unreadable path is `null` or `unknown`, never fabricated as a zero-byte store.

For runtime history, the status includes database/WAL byte counts and the owner
permission result. For sidecars, it shows the index and digest findings when the
owner reports them; this is not an inventory of every sidecar. Shared-memory and
Codememory privacy remain `unknown` unless their owner supplies a privacy result.

`file_metadata` and `wal_metadata` are `lstat` observations of the **final path
component**. Regular-file size, POSIX mode, current-user ownership and link count
are metadata, not proof that parent directories, WAL/SHM siblings, backups or
stored content are private. A final symlink/nonregular file is not followed and
has unknown size. Ancestor components may be symlinks. Each store is sampled at
a different time; this is not an atomic snapshot or an erase guarantee.
An observed nonregular component, non-owner file, multiple hard links, or
group/world mode bits raises a metadata-attention warning. If such an observation
contradicts an earlier runtime-owner `private` result, the dashboard reports
`inconsistent_samples` rather than certifying either observation as current.

The Codememory location comes from the native `oc config --format json` resolver,
including its environment overrides, without connecting to the database. Raw
configuration and database URLs are never copied into the status. If the native
resolver is unavailable or disagrees with the unified doctor's selected path,
status warns and does not present the doctor's health as unqualified `PASS`. A
non-SQLite backend is reported without attempting a local database path.

## Retention Is Not Deletion

- Runtime-history and Codememory automatic retention are **unknown**; this
  dashboard does not infer that either is disabled or that rows may be deleted.
- Session-sidecar limits are the owner's effective **index writer policy**, with
  default fallback possible. They are not retention for runtime transcripts,
  digests, backups or other stores.
- Shared memory reports the owner's default age for an **explicit manual archive
  operation**, not a scheduled cleanup. Pinned records are excluded. Archives,
  FTS, exports and backups are not proven erased by that setting.

See `docs/local-data-lifecycle.md` and `docs/runtime-db-schema.md` before any
source mutation. This status command does not initialize, repair, archive, delete
or change retention for any store. Existing diagnostic subprocesses may use the
owner's normal read/diagnostic mechanisms; the status adds a bounded nonconnecting
Codememory configuration read and metadata-only filesystem observations.

## Privacy and Support

Default output contains absolute local paths and storage metadata and is
**local-sensitive**. `--redact` suppresses the main and sidecar artifact paths;
it does not make sizes, permissions, health or retention metadata automatically
safe to share. No session IDs, prompts, messages, SQL rows, owner error text,
database URLs or secret values are included in this concise view. Inspect any
support artifact locally before sharing. The separate `/session search --redact`
and `/session handoff --redact` contracts remain the supported share-safe paths.
