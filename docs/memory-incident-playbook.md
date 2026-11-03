# Memory Incident Playbook

Use this when OpenCode memory pressure rises sharply or critical guard events start firing.

## 1) Detect

Run quick diagnostics first:

```bash
/gateway status --json
/gateway doctor --json
```

Look for:
- in `/gateway status --json`: `process_pressure.max_rss_mb` and `guard_event_counters.recent_global_process_pressure_critical_events`
- in `/gateway doctor --json`: `status.process_pressure.max_rss_mb` and `status.guard_event_counters.recent_global_process_pressure_critical_events`
- `remediation_commands` in doctor output

## 2) Stabilize

Pause active continuation work before opening more sessions:

```bash
/autopilot pause
```

Automatic process recovery is disabled for both V1 and V2. The sampled PID
and command do not establish a stable process identity or whether the process
owns a shared service. Do not treat a high-RSS entry as authorization to signal
it. Inspect the affected service and sessions before any manual action.

To inspect candidates without terminating them:

```bash
/gateway recover memory --json
```

Candidates are **unqualified observations**, not a safe termination plan.
The command does not signal processes or resume panes, and preview no longer
updates the pane cache or starts an OpenCode session lookup. `--apply` fails
closed. Thresholds used to select diagnostic candidates remain configurable via
`memoryRecovery`:

```json
{
  "memoryRecovery": {
    "candidateMinFootprintMb": 6000,
    "candidateMinRssMb": 1400,
    "aggregateEnabled": true,
    "aggregateMaxPressureMb": 40960,
    "aggregateCandidateMinFootprintMb": 5000,
    "aggregateCandidateMinRssMb": 1800,
    "aggregateRequireSwapUsedMb": 12000,
    "aggregateRequireContinueSessions": 4,
    "aggregateBatchSize": 1,
    "emergencySwapEnabled": true,
    "emergencySwapUsedMb": 28000,
    "emergencyCandidateMinFootprintMb": 4500,
    "emergencyBatchSize": 1,
    "criticalPressureMb": 10240,
    "criticalSwapUsedMb": 12000
  }
}
```

Aggregate and emergency thresholds can change which candidates are reported;
they do not authorize termination. Resume, compaction, force-kill and automatic
continuation settings do not enable recovery actions.

New protection LaunchAgents cannot be enabled. An existing watcher that loads
this version with `--watch --apply` continues on its configured schedule in
diagnostic-only mode, warns on stderr, and records blocked cycles in its usual
bounded state file. Finite watches still exit and may be restarted by launchd.
The watcher does not signal processes or resume panes. A separately installed
runtime or already-running process may still use older code; updating this
repository does not stop or update it.

Existing LaunchAgent status and reports remain available:

```bash
/gateway protection status --json
/gateway protection report --limit 20 --json
/gateway protection cache --json
```

The `loaded` field reports launchd state, not which code the agent is running.
Status and report mark the local code's automatic recovery as unavailable and
do not claim to have verified a loaded agent's version.

## 3) Recover

Get balanced policy recommendations:

```bash
/gateway tune memory --json
/gateway tune memory --apply --json
```

Apply suggested `globalProcessPressure`, `contextWindowMonitor`, and `preemptiveCompaction` settings.

## 4) Verify

Re-check health after remediation:

```bash
/gateway status --json
/gateway doctor --json
```

Expected outcome:
- lower or stable `max_rss_mb`
- no new critical events in recent window
- clear remediation guidance with no new high-severity blockers
