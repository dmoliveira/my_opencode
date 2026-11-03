# Proposed Background Store and Artifact Authority

Status: **design only; not implemented or qualified for live use**.
Tracking: `task_181`. This proposal does not authorize migration, deletion,
redaction, recovery, or any background command. The safety hold in
`docs/command-handbook.md` remains in force.

## Problem and Evidence

The background index records paths for logs, metadata, gates, and receipts.
Those paths are data, not authority to read or modify their targets. Synthetic
tests showed that a stored log symlink can truncate or disclose an external
file, and that an existing lock symlink could change its target's permissions.
They did not operate on live jobs. Terminal record pruning and artifact deletion
are deferred; this proposal does not re-enable either operation.

PR #796 narrows two boundaries. The lock refuses observed unsafe targets rather
than repairing an existing lock, and a borrowed parent-directory descriptor is
used for exclusive initial index creation and bounded index reads. A synthetic
parent swap no longer redirects that initialization. An uncertain new index is
preserved. These changes do not qualify later index writeback, artifact access,
indirect readers, or process signals. The index metadata and pathname checks
detect observed changes; they are not atomic compare-and-swap operations.

The remaining source paths include:

| Surface | Current behavior and gap |
| --- | --- |
| Index writeback | `locked_jobs` calls `_atomic_write_json` on `JOBS_PATH`. Its pathname-based replacement can overwrite a different entry after an observation; its temporary-path cleanup also lacks creation-bound ownership. |
| Logs and metadata | Legacy execution opens a stored log path for append; lease output opens one for truncating write. Metadata is published to a stored path. A record can therefore direct access outside the intended run directory. |
| Gates and receipts | The gate writes a marker through a pathname, while prepared and terminal receipts use pathname publication. Resolving or comparing a path before use does not prevent a later replacement. |
| Artifact reads | `_read_json_artifact` reads the full file before checking its size, and `tail_text` reads the full log. Both use a stored path. |
| Indirect readers | Health refresh derives its index path from the config write path; some swarm operations read linked jobs directly. Neither is made safe merely by hardening `locked_jobs`. |

An isolated synthetic test moved an owner-only `0600`, single-link regular file
from outside a private run directory into it under an expected log filename.
Descriptor-relative no-follow opening and name, owner, type, mode, and link
checks all passed, although the inode originated elsewhere. Names, metadata,
hashes, timestamps, and inode observations alone do not authenticate persisted
artifact provenance. No live file or process was involved in that test.

## Required Trust Boundary

The implementation must identify which actor creates and owns each index
generation and artifact, which actors can change its directory or contents,
and what authority survives process restart. A stored path, random-looking ID,
matching digest, cooperative lock, or permission mode is not an authorization.
In particular, filesystem permissions do not separate mutually untrusted actors
that share the same effective UID. An open descriptor pins an inode, but alone
does not stop another same-UID actor from changing that inode's contents through
another reference.

For the full same-UID threat model, a durable origin and writer-exclusion
mechanism independent of the untrusted store is still needed. A proposed
separate owner or OS security boundary must be specified and tested on each
supported platform; a credential readable by the same untrusted actor is not
such a boundary. If the required authority is missing, the operation must stop
without assuming a legacy artifact is owned. An implementation may state a
narrower cooperative-writer assumption for an experiment, but must not use that
experiment to lift the live-use hold.

## Candidate Publication Rules

These are requirements for a future implementation, not guarantees of the
current code:

1. **Create, do not claim.** Derive a validated basename from the bound job,
   attempt, and artifact kind. Against a verified, pinned directory descriptor,
   use supported no-follow, exclusive creation for a new entry. A collision,
   unsafe type, unsupported primitive, or uncertain directory identity must
   stop the operation. Never truncate, append to, chmod, replace, or remove an
   existing entry merely because its name or metadata matches.
2. **Keep authority through use.** Retain the descriptor for the newly created
   inode through its writes and required syncs. Pass explicitly authorized
   descriptors to a child when a gate or output stream needs them; do not pass a
   pathname and reopen it as though it were the same authority. Define descriptor
   inheritance, closure, failure, and child-start ordering for Darwin and Linux.
   This prevents a later pathname replacement from redirecting that descriptor;
   it does not by itself protect against writes to the same inode by other actors.
3. **Preserve uncertainty.** If creation, a partial write, sync, close, or
   publication has an uncertain outcome, retain the new entry and report an
   indeterminate result. Do not unlink a pathname on the assumption that it
   still names the created inode. Do not grant execution or publish a success
   receipt while the required pre-effect evidence is uncertain.
4. **Separate generations.** Prepared and terminal receipts, gate outcomes,
   metadata, and job-index updates need explicit generation and recovery
   semantics. One candidate is a sequence of separately created, no-replace
   generation files, with bounded validation of an exact predecessor chain and
   rejection of observed forks. This is an append-only *participant protocol*,
   not an immutable or authenticated log against same-UID interference.
   Choosing a newest filename, timestamp, hash, or lock holder is not a safe
   recovery decision. Index head selection and atomic writer exclusion remain
   unresolved; no generation scheme is approved for live use yet.
5. **Bound and authorize reads.** A future reader must establish provenance and
   scope before accessing a log, gate, receipt, or metadata file, use a pinned
   directory and no-follow descriptor, and enforce byte and output limits
   during the read. It must reject unsupported types, aliases, malformed or
    ambiguous records, observed replacement, and unverifiable ownership without
    disclosing artifact contents in errors. Before/after checks are observations,
    not an atomic defense against a writer that can change the inode concurrently.
    A pre-open type check can race, and `O_NONBLOCK` does not prove that opening a
    device is harmless; the authority must rule out side-effecting open targets
    or fail before opening them.

Any future durable protocol must specify file and parent-directory durability,
limits, lock ordering, supported filesystems, and failure results. Existing
index or artifact files must not be automatically repaired, migrated,
quarantined, pruned, or deleted as a side effect of discovering that their
authority is uncertain.

## Recovery and Indirect Paths

No durable provenance mechanism is established for existing records or for a
new process reopening an artifact after restart. Until one is qualified, those
cases must remain unavailable or `unknown`, not be treated as a missing file or
an empty log. Legacy jobs and in-flight workers need an explicit compatibility
and quiescence plan; a migration must not overwrite or delete their data. A
matching job ID, receipt, or process fingerprint cannot substitute for it.

The design must also cover every reader and writer that bypasses the central
store lock, including health refresh and swarm job lookup. It must define which
owner provides the verified state to those callers and what they return when
that owner is unavailable. Changing `MY_OPENCODE_BG_DIR` alone does not isolate
the health reader. Operator output and recovery evidence may themselves contain
sensitive identifiers or paths and must be bounded and handled accordingly.

Artifact authority is separate from process containment. Existing PID and group
fingerprint checks are not atomic with signals, and a leaderless group's origin
is not established. A publication fix does not authorize a signal or lift the
background mutation hold. The lifecycle-deletion and ast-grep holds are also
independent.

## Qualification Before Activation

Use synthetic fixtures and isolated checkouts; process-oriented tests must run
where unrelated processes cannot be signalled. At minimum, qualify the exact
implementation on supported Darwin and Linux filesystems for:

- symlink, dangling symlink, hardlink, FIFO, device or other nonregular entry,
  foreign owner, unsafe permissions, oversized data, and malformed or duplicate
  records, with external sentinels and modes unchanged;
- parent, final-name, and inode replacement before open, during read, after
  validation, and during publication, including a same-UID moved-file
  provenance counterexample;
- exclusive-creation collisions, partial writes, short writes, sync and close
  failures, process death at each durability boundary, and restart recovery;
- concurrent cooperating writers and adversarial noncooperating writers,
  duplicate or forked generations, stale readers, and lock replacement;
- descriptor inheritance and lifetime across the worker and gate child, with
  no effect granted when required evidence is absent or indeterminate;
- legacy and in-flight records, health and swarm bypasses, bounded output, and
  preservation of all uncertain artifacts without cleanup or automatic retry.

For each test, record the actor and authority being exercised, not just a passing
path check. Activation also requires a qualified signal-containment design,
end-to-end review of indirect entry points, and updated operator guidance. Until
those gates are met, keep the existing live-use holds.
