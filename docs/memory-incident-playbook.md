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

Phase A recovery command (dry-run first):

```bash
/gateway recover memory
/gateway recover memory --apply
/gateway recover memory --apply --force-kill
```

`recover memory` targets top `high_footprint` entries first on macOS (falls back to `high_rss`) and sends graceful `SIGTERM` before recommending escalation.
When tmux pane mapping is available, recovery now sends `Ctrl+C` first, then falls back to `SIGTERM`, and only uses `SIGKILL` when pressure exceeds `memoryRecovery.forceKillMinPressureMb`.

Pane-aware recovery (Phase B):

```bash
/gateway recover memory --apply --resume --compress --force-kill
/gateway recover memory --apply --resume --compress --continue-prompt --force-kill
/gateway recover memory --watch --apply --resume --compress --force-kill --interval-seconds 20 --max-cycles 6
```

When PID-to-pane mapping is available in tmux, this restarts `opencode --continue` (or `--session <id>`) in the impacted pane and injects `/compact` after resume with safety checks.
Use `--watch` for automated polling and recovery actions in bounded cycles.

Thresholds and recovery criteria are configurable via `memoryRecovery` in your config:

```json
{
  "memoryRecovery": {
    "candidateMinFootprintMb": 4000,
    "candidateMinRssMb": 1400,
    "forceKillMinPressureMb": 12000,
    "aggregateEnabled": true,
    "aggregateMaxPressureMb": 40960,
    "aggregateCandidateMinFootprintMb": 5000,
    "aggregateCandidateMinRssMb": 1800,
    "aggregateRequireSwapUsedMb": 12000,
    "aggregateRequireContinueSessions": 6,
    "aggregateBatchSize": 1,
    "autoContinuePromptOnResume": true,
    "notificationsEnabled": true,
    "notifyBeforeRecovery": true,
    "notifyAfterRecovery": true,
    "criticalPressureMb": 10240,
    "criticalSwapUsedMb": 12000
  }
}
```

Session targeting: pane-aware resume prefers `opencode --session <id>` when a session id (`ses_*`) is visible in tmux pane title, then falls back to a per-pane cache (`~/.config/opencode/my_opencode/runtime/gateway-pane-session-cache.json`), then per-directory latest session, and finally `opencode --continue`.

Aggregate safety net: when no single process crosses `candidateMinFootprintMb`, recovery can still trigger in aggregate mode if total opencode footprint crosses `aggregateMaxPressureMb` and swap/session preconditions are met; it then recovers only the top `aggregateBatchSize` offenders.

LaunchAgent controls from OpenCode:

```bash
/gateway protection status --json
/gateway protection enable --interval-seconds 20 --json
/gateway protection report --limit 20 --json
/gateway protection cache --json
/gateway protection cache --clear --json
/gateway protection disable --json
```

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
