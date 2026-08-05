# Remaining OpenCode improvements — 2026-08-05

Status: reviewed and sequenced
Source revision: `efd98ce`
Codememory owner: `task_78`

## Decision

The next work should emphasize privacy, recoverability, bounded runtime behavior,
and measurement. Further prompt wording changes are not currently justified.
The audit found and immediately fixed one active reliability regression: PR
`#692` makes gateway state-lock turnover retry safely after post-merge main CI
exposed a legitimate two-writer race.

The highest-priority remaining slice is `task_80`, runtime SQLite artifact
permission hardening. It is independent of backup work because tightening file
metadata does not rewrite database content. `task_9`, consistency-preserving
snapshot/export, follows closely because unsupported pruning must not be used to
solve storage growth.

## Evidence

### Runtime storage and privacy

Read-only inspection of the active runtime store found:

| Signal | Observation |
| --- | ---: |
| Main database size | 14,632,271,872 bytes (about 13.6 GiB) |
| Runtime events | 1,779,155 rows; 7,956,635,648 table bytes |
| Parts | 1,098,820 rows; 5,763,227,648 table bytes |
| Messages | 208,132 rows; 352,632,832 table bytes |
| Database, WAL, and SHM modes | `0644` |
| Session-doctor scan | 876.57 ms, indexed snapshot, query-only |
| Stale health findings | 24 targeted; 13 generic |
| Digest sidecar mode | `0644`; existing repair flow reports it |
| Available local capacity | about 323 GiB during this audit |

The runtime `event` table is upstream durable event history, not a disposable
cache. Upstream source exposes ordered aggregate replay and provides no supported
event-retention, prune, live-`VACUUM`, lossless import, or projection-rebuild
contract. Direct row deletion could break replay and is not an acceptable
optimization.

### Provider-cache state

Read-only seven-day repository-scoped usage showed:

| Model | Assistant turns | Turns with cache read | Cached-token share | First-turn cache-read rate |
| --- | ---: | ---: | ---: | ---: |
| GPT-5.6 Sol | 4,533 | 96.4% | 96.1% | 12.4% (13/105) |
| GPT-5.6 Luna | 454 | 88.8% | 83.2% | 6.4% (3/47) |

The latest 24-hour Sol first-turn rate was 15.4% (6/39), but the runtime had not
been restarted after the latest context changes. These samples do not establish
causality or a post-deployment improvement. A clean restart timestamp and seven
complete days are required before another prompt optimization decision.

### Runtime and workflow overhead

- Hook dispatch is serial, but no privacy-safe per-hook latency distribution is
  available. Optimizing dispatch or synchronous audit writes now would be
  speculative.
- At least 23 synchronous subprocess call sites exist. The first bounded slice
  should cover only non-interactive Git/GitHub guards, probes, status checks, and
  metadata calls that currently lack explicit deadlines.
- Recent CI runs complete in roughly 3 minutes 10 seconds to 3 minutes 35
  seconds. Pull-request and post-merge runs repeat substantial work, but a
  coverage-preserving duplicate-run analysis must precede any workflow change.
- `agent-user-reminder` adds a 145-byte suffix when enabled, but it is disabled
  by default and in the observed configuration. It is not an active optimization
  target.

## Ranked roadmap

### P1 — `task_80`: harden runtime SQLite artifact permissions

Scope:

- limit remediation to exact active paths resolved by runtime doctor;
- open with `O_NOFOLLOW`, verify owner/type/link/path identity with `fstat`, and
  apply mode changes with descriptor-bound `fchmod`;
- reject path identity changes and unsafe parent authority;
- provide preview/apply behavior without replacing files or mutating content;
- verify owner-only WAL/SHM recreation after repairing and restarting the
  existing active database; do not claim fresh main-database creation, which
  remains process-umask dependent.

Gate:

- the active runtime directory is `0700`, the existing database and present
  WAL/SHM artifacts are `0600`, and controlled WAL/SHM recreation against the
  tested OpenCode runtime produces `0600` artifacts;
- symlink, hardlink, foreign-owner, non-regular, and path-race targets fail closed;
- normal startup and writes still succeed;
- original modes are recorded, but restoring an insecure mode is manual,
  emergency-only, and carries a confidentiality warning.

Rollback: revert reporting/remediation wiring if compatibility fails. Do not
automatically restore `0644`; any broader-mode restoration is manual,
emergency-only, and carries a confidentiality warning.

### P1 — `task_9`: produce a consistent snapshot/export

Scope:

- use SQLite online backup unless writer quiescence and atomic capture of the
  complete SQLite file set are proven;
- preflight destination capacity for output, temporary data, and safety margin;
- remove partial output on failure;
- record source/application version, bytes, hashes, duration, and whether
  `quick_check` or full `integrity_check` ran;
- open a disposable copy with the same application version.

Gate: two snapshots open read-only and pass their recorded consistency check.
A disposable open proves readability only, not application restoration.

Rollback: remove only disposable/partial artifacts. Never modify the live store
to recover from a failed snapshot exercise.

### P1 — `task_81`: bound Git and GitHub guard subprocesses

Scope only non-interactive guards, probes, status checks, and metadata calls.
Do not apply a blanket deadline to all synchronous subprocesses.

Gate:

- every scoped call has an explicit conservative deadline and distinct timeout
  reason;
- timed-out children are terminated and reaped;
- success, nonzero exit, missing command, and timeout behavior are covered;
- security guards preserve fail-closed behavior;
- ceilings are configurable or isolated by command class.

Rollback: raise or revert a call-site ceiling from measured legitimate duration;
never restore an unbounded security probe.

### P1 — `task_82`: measure cache behavior after restart

Record the deployment/restart timestamp, then capture a 24-hour checkpoint and
seven complete days. Separate all first turns from turns eligible for provider
caching, require at least 30 eligible Sol first turns, and report same-session
hit rate, cached-token share, cold writes, latency, rate-limit behavior, and
sample counts against a matched baseline.

Gate: a qualified measurement report is produced. The task does not claim
causality and does not automatically create another prompt-compaction task.

### P2 — `task_17`: finish stale-diagnostic pagination

Existing behavior already caps each indexed finding class at 20, aggregate
materialization at 100, exposes counts/truncation, and enforces a five-second
SQLite progress timeout. Remaining scope is deterministic summary/cursor
pagination only.

Gate: fixed page cap and ordering, opaque cursor semantics, `has_more` and
truncation fields, and defined behavior when rows change between pages.

### P2 — `task_83`: measure per-hook dispatch latency

Depends on `task_81`. Never persist per-invocation timing events. Emit only
coarse-window aggregate histograms after a minimum sample threshold, keyed by
hook ID and event class. Exclude arguments, paths, prompt content, secrets, and
session identifiers. Report aggregate p50/p95/p99 and optimize only hooks
exceeding a predeclared latency/share gate.

Rollback: disable timing fields without changing request behavior.

### P2 — `task_84`: audit duplicate CI runs

Analyze at least 20 representative pull-request and push runs. Quantify repeated
work, critical path, and check coverage. Close as a no-op if duplication is not
material; create a separate implementation task only when the analysis proves
meaningful savings without removing release gates.

## Existing task reconciliation

- `task_16` is closed: `/session doctor --json` already reports database/WAL
  size, size threshold, scan duration/timeout, query-only state, and explicit
  latency-budget warnings. Unified doctor parity remains `task_21` scope.
- `task_17` is narrowed rather than reprioritized; its broad bounding work is
  already present.
- `task_20` depends on `task_9` so lifecycle documentation reflects the proven
  snapshot contract.
- `task_21` depends on the `task_17` pagination contract and should consume the
  permission-reporting contract from `task_80`; it need not wait for unrelated
  hardening internals.
- `task_24` remains P3 after the unified-doctor contract.

## Dependency summary

```text
task_80 permissions ───────────────┐
                                   ├─> task_21 unified doctor -> task_24 dashboard
task_17 pagination contract ───────┘

task_9 consistent snapshot -> task_20 lifecycle documentation

task_81 subprocess deadlines -> task_83 per-hook latency measurement

restart -> task_82 24h checkpoint -> task_82 seven-day report

task_84 CI analysis -> implementation only if evidence clears its gate
```

## Evidence appendix

Observation timestamp: `2026-08-05T14:00:54+1000`. All runtime queries were
read-only. The committed plan does not store the local path resolved by:

```bash
python3 scripts/session_command.py doctor --json
```

Storage size and row evidence used SQLite `dbstat` and bounded counts:

```sql
SELECT name, sum(pgsize), count(*)
FROM dbstat
WHERE name IN ('event', 'part', 'message')
GROUP BY name;

SELECT count(*) FROM event;
SELECT count(*) FROM part;
SELECT count(*) FROM message;
```

Artifact modes came from `stat` against the doctor-resolved database, WAL, SHM,
and digest paths. Capacity came from `df -h` on the runtime-store filesystem.

Cache populations were assistant messages created in the preceding seven days,
joined to sessions under this repository directory. A cache-read turn had
`$.tokens.cache.read > 0`. First turn used `row_number()` partitioned by session
and ordered by message creation time and ID. The 24-hour query used the same
definition. These queries did not yet separate the provider's 1,024-token
eligibility threshold; that is required by `task_82`.

CI evidence:

- failed main run `30963872652` exposed the lock turnover race;
- PR `#692` merged as `efd98ced81c931263b716f71cfa6f75a017f2dba`;
- PR run `30972655600` and post-merge main run `30972822845` passed both jobs;
- the recent-duration range came from `gh run list --workflow CI --limit 20`.

Links: [PR #692](https://github.com/dmoliveira/my_opencode/pull/692),
[failed main run](https://github.com/dmoliveira/my_opencode/actions/runs/30963872652),
and [green replacement main run](https://github.com/dmoliveira/my_opencode/actions/runs/30972822845).

## Explicit no-go actions

Until upstream publishes a supported lifecycle/rebuild contract, do not:

- delete or prune `event`, `part`, or `message` rows;
- run a live size-reclamation `VACUUM`;
- rewrite the runtime schema;
- treat redacted `opencode export` output as a restoration backup; or
- implement an ad hoc runtime-history import.

The safe path is visibility, privacy hardening, consistency-preserving snapshots,
bounded diagnostics, and an upstream retention request backed by measured table
growth.
