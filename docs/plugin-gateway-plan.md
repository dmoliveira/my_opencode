# Gateway Core Operating Plan

`gateway-core` is the only supported plugin runtime in this repository.

## Current architecture

- plugin runtime: `plugin/gateway-core`
- config entry: `file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core`
- command bridge: Python command scripts in `scripts/`
- hook orchestration: TypeScript hooks under `plugin/gateway-core/src/hooks/`
- fallback mode when Bun is unavailable: `python_command_bridge`

## Locked decisions

- keep Python for slash-command orchestration and diagnostics
- keep TypeScript for event-driven hook execution
- do not maintain separate plugin packages for autopilot loop behavior
- keep deterministic reason-code reporting for runtime routing and guardrails

## Quality gates

- `make validate`
- `npm --prefix plugin/gateway-core run lint`
- `npm --prefix plugin/gateway-core run test`
- `make selftest`
- `make install-test`

## Backlog

1. tighten hook performance budgets for long sessions
2. add gateway-core dist parity checks into install smoke output summary
3. document hook-level troubleshooting recipes by reason code
4. keep command surface minimal; add aliases only when they reduce repeated friction
