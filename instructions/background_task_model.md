# Background Task Model

This document defines the local `/bg` execution model. Jobs are either legacy
shell jobs or opt-in task-lease jobs. Codememory remains the authority for task
and session lifecycle in both cases.

## Job Lifecycle

All jobs use these states:

- `queued`: accepted and waiting for dispatch.
- `running`: reserved by one worker. A task-lease worker may still be acquiring
  its lease or waiting at the command gate.
- `completed`: the process exited with code `0` and its result was committed.
- `failed`: the process failed, timed out, or exhausted its attempt limit.
- `cancelled`: explicitly cancelled or stopped by the legacy stale guard.

Task-lease jobs also use `reconciling`. Legacy jobs use it only when their
process group cannot be proven stopped. This state means command effects or
descendants may remain but the worker cannot prove a safe terminal result.
`/bg` never automatically replays a job in this state.

`completed`, `failed`, and `cancelled` are terminal. A runner may enrich their
evidence, but it cannot replace one terminal state with another.

## Execution Modes

Jobs without `execution_mode` are legacy jobs. Their CLI and normal scheduling
remain unchanged. Dispatch reserves each legacy job under `jobs.lock` and uses
an execution token for PID and terminal compare-and-set updates, preventing two
runners from executing the same queued job or overwriting cancellation. The
legacy shell also waits behind a pipe gate until its PID, process group, and
start fingerprint are durable. A worker crash before PID publication therefore
closes the gate without running the command; cancellation or stale cleanup keeps
an older PID-less reservation in `reconciling` instead of claiming containment.

A job with `execution_mode: task_lease` carries an explicit Codememory task,
session, owner, scope, config, lease store, worktree, and TTL. Lease-backed jobs
use a separate capacity limit, so a saturated lease pool does not reduce legacy
throughput. `/bg run --lease-max-concurrency <n>` defaults this pool to `2`.

## Attempts And Retries

Each task-lease dispatch appends an immutable attempt:

```text
acquiring -> starting -> running -> succeeded|failed|cancelled|unknown
```

Once an attempt is terminal it is never reset. A failed attempt may return its
job to `queued`; the next dispatch creates a new attempt and lease identity.
`max_attempts` defaults to `1`. Values above `1` require `retry_safe: true`,
selected with both `--max-attempts <n>` and `--retry-safe` at enqueue time.

Retry safety is a caller assertion. Local lease fencing does not make a shell
command idempotent. Commands that write Git, GitHub, Codememory, network, or
other external state still need native compare-and-set behavior or a stable
end-to-end idempotency key.

## Lease Admission

Lease identity is never guessed or preallocated in `jobs.json`:

1. Under `jobs.lock`, the scheduler reserves capacity and writes an `acquiring`
   attempt with a stable worker ID.
2. After releasing `jobs.lock`, the worker calls `claim_lease()`.
3. `guarded_local_commit()` holds the exact lease while a short callback takes
   `jobs.lock`, persists the returned lease ID and fencing token, and advances
   the attempt to `starting`.
4. Every PID publication and terminal result uses the same attempt identity and
   exact lease guard.

The only nested lock order is lease lock followed by jobs lock. `/bg` never
calls a lease API while it already holds `jobs.lock`. Once a claim may have
committed, an error is not reported as a rollback. A known identity is released
best-effort; an indeterminate identity or store commit fails closed.

## Command Gate And Evidence

Before a task-lease command can run, `/bg` writes a durable prepared receipt and
starts a process-group wrapper blocked on an inherited pipe. PID and process
group are committed under the exact lease before the parent opens that gate.
Legacy jobs use the same pre-exec gate boundary without a task lease or attempt
receipt.

The wrapper writes and syncs one marker before any shell effect:

- `gate_aborted`: the parent closed the pipe without granting execution, so no
  command effect occurred.
- `effect_possible`: execution was granted. Recovery must assume effects may
  have occurred even if the shell failed before producing output.

The reservation stores start fingerprints for both the worker and command
process. Reconciliation requires the PID and start fingerprint to match, plus a
fresh exact lease heartbeat, before treating a worker as live. This prevents a
reused PID or an unrelated thread in the same runner from holding capacity.

Every attempt stores its own bounded log, gate marker, and receipt under
`runs/`. The worker continues draining output after the configured log byte cap
and records truncation. A terminal receipt is synced before its result is
projected into `jobs.json`.

## Heartbeat, Timeout, And Cancellation

Task-lease workers heartbeat at roughly one third of the lease TTL. Holder
mismatch, expiry, clock rollback, or indeterminate lease state stops
authoritative commits and terminates the process group. If execution was
granted, the attempt becomes `unknown` and the job becomes `reconciling`.

Timeout and user cancellation terminate the complete process group, escalating
from `SIGTERM` to `SIGKILL`. Cancellation first fences the active attempt, then
publishes `cancelled` only after the process group settles. An identity mismatch
or a group that remains live moves the job to `reconciling` and preserves its
PID, process group, and start fingerprint for another `/bg cancel` containment
attempt.

Legacy stale handling remains elapsed-time based. Task-lease liveness comes
from the lease heartbeat and is not cancelled by the legacy stale threshold.

## Reconciliation

`/bg reconcile` inspects interrupted task-lease attempts without replaying an
unknown command:

- `acquiring` resumes the same-worker claim, closes the interrupted attempt as
  known pre-start failure, and releases the exact lease.
- `starting` is known pre-effect because the gate cannot open before `running`
  is durably committed.
- `running` plus `gate_aborted` is known pre-effect and may follow the configured
  retry policy.
- A terminal receipt is adopted only while the exact lease still guards the
  attempt. Adoption validates the command and cwd hashes, attempt number,
  process identity, gate marker, log digest, terminal semantics, and complete
  lease identity before changing job state.
- `effect_possible`, missing gate evidence, stale fencing, or an unadoptable
  terminal receipt moves the job to `reconciling`.

Recovery verifies and stops the recorded process group before clearing its
execution slot, even when the task lease has already expired. A process-group
identity mismatch or incomplete bounded log drain also leaves the job in
`reconciling` rather than publishing success.

`/bg run` performs a bounded reconciliation pass before reserving new jobs.
`/bg cleanup` reconciles before applying retention.

## Persistence And Retention

The default store is `~/.config/opencode/my_opencode/bg/`:

- `jobs.json`: authoritative job index.
- `jobs.lock`: stable single-writer lock.
- `runs/<job_id>.log` and `runs/<job_id>.meta.json`: legacy artifacts.
- `runs/<job_id>.legacy_<token>.gate.json`: legacy pre-exec gate evidence.
- `runs/<job_id>.<attempt_id>.log`: bounded task-lease output.
- `runs/<job_id>.<attempt_id>.gate.json`: durable gate boundary.
- `runs/<job_id>.<attempt_id>.receipt.json`: attempt evidence.

JSON publication uses an owner-only temporary file, file sync, atomic replace,
and parent-directory sync. Failed in-memory mutations are not written. A
post-replace durability error is reported as indeterminate instead of rolled
back.

Terminal jobs are retained for `14` days by default, with at most `200`
terminal entries. Pruning removes the job's logs, metadata, gate markers, and
attempt receipts. `reconciling` jobs are nonterminal and are never pruned by
terminal retention.

## Enqueue Example

```bash
python3 scripts/background_task_manager.py enqueue \
  --task-id "$TASK_ID" \
  --session "$SESSION_ID" \
  --owner opencode \
  --scope dmoliveira/my_opencode \
  --codememory-config .codememory/config.sqlite.yaml \
  --lease-state-path ~/.config/opencode/my_opencode/runtime/codememory_task_leases.json \
  --lease-ttl-seconds 300 \
  --max-attempts 1 \
  -- make validate
```
