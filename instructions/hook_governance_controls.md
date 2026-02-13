# Hook Governance Controls

Epic 4 Task 4.3 defines operational controls for the initial safety hooks.

## Config controls

`hooks` section in layered config:

```json
{
  "hooks": {
    "enabled": true,
    "disabled": ["truncate-safety"]
  }
}
```

- `hooks.enabled`: global switch for hook execution
- `hooks.disabled`: per-hook opt-out list

## Runtime controls via `/hooks`

- `/hooks enable`
- `/hooks disable`
- `/hooks disable-hook <hook-id>`
- `/hooks enable-hook <hook-id>`
- `/hooks status`

## Telemetry-safe audit logging

Hook executions append JSON lines to:

- default: `~/.config/opencode/hooks/actions.jsonl`
- override: `MY_OPENCODE_HOOK_AUDIT_PATH`

Audit rows include only metadata (timestamp, hook id, category, triggered, exit_code).
Raw `stdout`/`stderr`/payload text are intentionally excluded.
