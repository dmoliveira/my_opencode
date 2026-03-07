# Quickstart

## Install and verify

1. Run the installer script from the repository root.
2. Open OpenCode and run a basic health check.
3. Confirm plugin and gateway status.

## Canonical first-run commands

Managed MCPs start disabled by default; opt into a focused profile only when you need extra context.

```text
/doctor run
/plugin status
/mcp status
/notify status
/autoflow status --json
/session handoff --json
/gateway status
```

Optional next step when you want lightweight repo or docs context:

```text
/mcp profile research
```

## Common productivity flows

```text
/init-deep --max-depth 2 --json
/autopilot go --goal "finish current objective" --json
/continuation-stop --reason "manual checkpoint" --json
```

## References

- Full command catalog: `docs/command-handbook.md`
- Operator runbook: `docs/operator-playbook.md`
- Deeper architecture notes: `docs/readme-deep-notes.md`
