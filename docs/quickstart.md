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
/digest run --reason manual
/gateway status
```

Optional next step when you want lightweight repo or docs context:

```text
/mcp profile research
```

Run `/session handoff --json` after you have at least one indexed digest.

## Common productivity flows

```text
/workflow template init ship --json
/delivery start --issue issue-900 --role coder --workflow <workflow.json> --execute --json
/delivery status --json
/init-deep --max-depth 2 --json
/autopilot go --goal "finish current objective" --json
/autoflow start <plan.md> --json
/continuation-stop --reason "manual checkpoint" --json
```

Use this split to stay consistent:

- `/delivery` for normal issue-to-close work
- `/workflow` when you need direct workflow validation or resume controls
- `/autopilot` for open-ended autonomous execution; `/do` is the shorthand alias
- `/autoflow` for plan markdown execution

## References

- Full command catalog: `docs/command-handbook.md`
- Operator runbook: `docs/operator-playbook.md`
- Deeper architecture notes: `docs/readme-deep-notes.md`
