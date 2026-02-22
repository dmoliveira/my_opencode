# Autopilot Runtime Notes

Autopilot now runs through `gateway-core` hook events plus Python command orchestration.

## Runtime model

- `session.idle` and related lifecycle hooks are handled in `plugin/gateway-core/src/hooks/`
- `/autopilot` remains the canonical command entrypoint
- runtime mode is reported as:
  - `plugin_gateway` when Bun + gateway dist hooks are available and enabled
  - `python_command_bridge` otherwise

## Compatibility

- no compatibility slash aliases are maintained; use `/autopilot` subcommands directly
- no standalone `plugin/autopilot-loop` package is maintained

## Safety invariants

- never exceed configured iteration limits
- never mark promise-mode completion without explicit completion signal
- always support manual stop
- emit deterministic reason codes for terminal states

## Validation checklist

- `python3 scripts/autopilot_command.py doctor --json`
- `python3 scripts/gateway_command.py doctor --json`
- `npm --prefix plugin/gateway-core run test`
- `make selftest`
