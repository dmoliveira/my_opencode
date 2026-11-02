# Rolling Decomposition Qualification

Date: 2026-11-03. Codememory: `task_130` / `epic_24`.

## Scope

This qualifies deterministic, finite hierarchical fixture intake through the real
proposal-only planner and sole-writer coordinator, complete graph readback, bounded
frontier advice, and the existing lease-backed execution boundary. It does not
qualify arbitrary natural-language decomposition quality, cross-host execution,
PostgreSQL parity, or 1000 simultaneous/real command completions.

Counts are task records, excluding epics. Every three-task fragment has one epic,
one foundation task and two dependent children; a partial final fragment preserves
exact task counts. Maximum proposal size is nine combined records/links, below
the unchanged coordinator limit of ten. Independent requirement inventory and
separate authoritative hierarchy/link checks prevent projection-only coverage
from being mistaken for complete intent coverage.

## Commands

```bash
make rolling-decomposition-live PYTHON=python3.12
python3 scripts/rolling_decomposition_qualification.py --sizes 9
python3 -m unittest discover -s tests -p 'test_rolling_decomposition.py'
python3 -m unittest discover -s tests -p 'test_background_task_manager.py' -k scaled_process
```

## Latency Gates

Nine-task native calibration measured 3.372 s / 28 intake calls and 5.690 s / 47
source calls, approximately 0.12 s per native launch on this host. Gates use
0.20 s per operation plus a complete process-timeout reserve, fixed before the
full runs. For task count `N`, `G = ceil(N/3)`, and `L = 2N - G`:

- intake: `30 + 0.20 * (8G + 16)` seconds;
- authoritative source: `max(30, 10 + 0.20 * (2L + 17))` seconds;
- local projection/replay/tamper/checkpoint/rolling model: 30 seconds;
- connected native two-process execution: 60 seconds.

These are single-host baseline qualification thresholds, not service SLOs. Intake
and double scans scale with bounded CLI operation counts. The full operation timeout
must fit in the remaining stage budget before any subprocess starts. Operator
policies that increase per-call timeouts can therefore fail admission earlier.

## Validation Evidence

The full native run passed on macOS with Python 3.12.16 and the installed `oc`
launcher against isolated SQLite stores. Exact machine-readable output is in
`docs/rolling-decomposition-qualification.json`. Every stage stayed below its
predeclared budget; every scenario removed its temporary root.

| Tasks | Epics / fragments | Intake seconds / budget | Intake calls | Source seconds / budget | Source calls | Local seconds | Real process seconds |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 17 | 15.249 / 60.4 | 125 | 22.639 / 46.6 | 183 | 0.007 | 1.648 |
| 250 | 84 | 72.834 / 167.6 | 593 | 103.343 / 179.8 | 849 | 0.031 | 1.659 |
| 1000 | 334 | 293.346 / 567.6 | 2343 | 413.472 / 679.8 | 3349 | 0.196 | 1.730 |

All three scenarios preserved exact task/epic/hierarchy/dependency counts, passed
prepared/applied/conflicting replay and duplicate-title gates, completed the
fixture frontier model with peak two, recovered a checkpoint, and executed exactly
two real lease-backed commands while deferring the third ready queued command.

Evidence provenance: the full-scale run started before review added explicit
parent-process projection override rebinding and dedicated subprocess operation
IDs. Neither host task-graph override was set in that run (verified). The final-code
nine-task native smoke was rerun after both corrections: intake 3.481 s, source
5.678 s, local 0.003 s, real execution 1.593 s; all gates and root cleanup passed.
All-size local regression tests additionally cover the final sandbox guard, with
external graph/lock sentinels unchanged. The dedicated operation IDs retain the
same bounded probe/mutation policy classes; they change inventory attribution,
not native intake, projection or execution semantics.

The configured full repository validation and two changed-diff implementation
reviews accompany these measurements. Review findings on sandbox overrides and
human-readable frontier visibility were repaired before delivery.

The independent-process queue qualification distinguishes live-owner reload from
dead-owner recovery and checks persisted attempt identities, not only returned
job IDs. Native fixtures verify prepared-receipt recovery, no-op applied replay,
conflicting replay, new-ID duplicate rejection, exact task/epic/hierarchy counts,
byte-stable projection, tamper rejection, checkpoint replay and bounded frontier
completion. Every native scale executes two real fenced commands, defers a third
ready queued command, and excludes a dependency-blocked task.

## Authority And Recovery Limits

Frontier output is advice; it is neither an atomic reservation nor authorization
to execute. The native store, current session/task identity, exact task lease and
background capacity checks remain the admission boundary. Large model completions
are fixture evidence only. Ambiguous post-effect attempts retain their existing
reconciliation/quarantine contract; owner loss does not authorize blind replay.

The fresh-only coordinator produces a forest of bounded fragments. Existing-record
hierarchy reconciliation and general semantic rolling decomposition remain separate
capabilities, rather than being inferred from this finite qualification.
