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

If critical pressure persists, stop only the highest RSS processes listed in `process_pressure.high_rss`.

## 3) Recover

Get balanced policy recommendations:

```bash
/gateway tune memory --json
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
