# Quickstart

## Install and verify

1. Run the installer script from the repository root.
2. Open OpenCode and run a basic health check.
3. Confirm plugin and gateway status.

## Canonical first-run commands

```text
/doctor run
/plugin status
/mcp status
/notify status
/autoflow status --json
/session handoff --json
/gateway status
```

## Common productivity flows

```text
/init-deep --max-depth 2 --json
/autopilot go --goal "finish current objective" --json
/continuation-stop --reason "manual checkpoint" --json
```

## References

- Full command catalog: `docs/command-handbook.md`
- Deeper architecture notes: `docs/readme-deep-notes.md`
