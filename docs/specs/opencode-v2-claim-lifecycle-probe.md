# V2 execution-claim lifecycle probe

Status: **synthetic measurement only**. This is not a stale-session detector,
repair authorization, gateway activation check, or security boundary. The V2
gateway, execution-status adapter and sidebar remain unconfigured.

## Run

With Python 3.11+ and a selected OpenCode **2.2.5** executable:

```sh
make gateway-v2-claim-lifecycle-probe OPENCODE_BIN=/path/to/opencode
```

The command does not install dependencies or alter project configuration. The
script also accepts `--temp-parent <directory>` and emits one bounded JSON
report. Other reported executable versions fail closed.

**Use an independently verified OS sandbox whenever preserving local data
matters.** The private home, localhost credentials, selected executable hash,
and ownership checks are not filesystem containment and cannot defeat
same-user swap-and-restore races. Verify filesystem-write, outbound-network and
signal restrictions separately.

## Measurement

An authenticated, PID-checked, unregistered private server loads an owned
fixture plugin and a synthetic localhost provider. The controller creates two
sessions and correlates plugin trace IDs to those sessions before releasing an
interruption. It holds the target at a real native context hook while a peer
reaches the provider with a synthetic marker and completes. The plugin then
calls native `session.interrupt` and `session.wait` for the target.

At each controlled stage, SQLite opens **only the fixture database** in
read-only, query-only mode and reads two bound session IDs in one transaction.
The report contains boolean claim/busy/idle presence and a resume-attempt count,
not session IDs, timestamps, prompts, raw rows, or credentials. The controller
does not write session data, but a SQLite WAL reader may update the fixture's
SHM coordination bytes. Absence or presence is an observation, not proof of
ownership, staleness, or successful recovery.

The selected 2.2.5 feasibility control observed a claim while the target was
active, no claim for an unstarted session or a completed peer, and no claim for
the target after accepted interruption and native wait. Upstream
[2.2.5 session execution](https://github.com/anomalyco/opencode/blob/9bbb8ce18c80f099e0e448775f59d965ead40a21/packages/core/src/session/execution.ts)
also records claims as write-ahead intent and deliberately preserves them on
shutdown interruption. Its
[restart implementation](https://github.com/anomalyco/opencode/blob/9bbb8ce18c80f099e0e448775f59d965ead40a21/packages/core/src/session/execution/restart.ts)
describes managed-server recovery after the previous owner is confirmed dead;
unregistered servers do not automatically perform that sweep. Those are source
observations, not proof that a selected executable matches that source.

This probe does **not** test shutdown, crashes, managed restart, background job
recovery, multiple services, live owner identity, V2-native diagnosis, or
repair. Do not clear a claim or run V1 repairs based on these measurements. It
also does not replace strict snapshot application validation.

## Retention and teardown

Case and version fixture roots are retained on success and failure. They may
contain synthetic credentials, prompts and runtime metadata; inspect them
before sharing or cleaning up. Reports include their basenames, the selected
executable hash and checked process/socket teardown. Teardown does not prove
that no process escaped the checked group. Fixture identity and executable
hash checks do not prevent transient substitution by a same-user actor.
