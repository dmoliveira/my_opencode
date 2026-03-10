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

Run `/session handoff --json` after you have at least one indexed digest. If you need to reopen work in a different linked worktree, use `/session handoff --launch-cwd <worktree-path> --fork --json` to get a ready-to-run launch command.

For automation-friendly help output, prefer command-specific help from this repo (for example `python3 scripts/session_command.py help`) because the upstream `opencode --help` banner formatting is not controlled here.

Gateway runtime behavior is primarily tuned through the sidecar config at `.opencode/gateway-core.config.json` (or `MY_OPENCODE_GATEWAY_CONFIG_PATH`). Use that file for normal hook/runtime tuning; if the same gateway keys are also set in root config, the root values still override the sidecar today.

## Common productivity flows

Before you start a task, create a dedicated git worktree branch from the current root branch. Keep the main project folder on `main`, never `git checkout` or `git switch` that folder onto a task branch, and treat the primary project folder on protected branches (`main`, `master`) as edit-blocked by default. Bash usage in that primary protected worktree is limited to inspection, validation, and sync/setup commands such as `git fetch`, `git fetch --prune`, `git pull --rebase`, `git worktree add ...`, and `git stash push|pop|list|show`. Linked worktrees are the place to do normal task mutations, and they stay editable as long as the linked worktree itself is on a non-protected task branch.

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
- `/autopilot` for open-ended autonomous execution
- `/autoflow` for plan markdown execution

## References

- Full command catalog: `docs/command-handbook.md`
- Operator runbook: `docs/operator-playbook.md`
- Worktree-first execution: `docs/parallel-wt-playbook.md`
- Deeper architecture notes: `docs/readme-deep-notes.md`

Optional external delivery-policy references: search your local clone first when available, then use these public links when you need a canonical shareable reference.

- `https://github.com/dmoliveira/agents.md/blob/main/AGENTS.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/index.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/validation-policy.md`
