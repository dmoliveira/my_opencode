# Quickstart

## Install and verify

1. Run the installer script from the repository root.
2. Open OpenCode and run a basic health check.
3. Confirm plugin and gateway status.

Startup instructions are loaded from `~/.config/opencode/my_opencode/AGENTS.md` and `~/.config/opencode/my_opencode/instructions/shell_strategy.md`. If you use `./scripts/setup_local_dev_symlinks.sh`, the repo `AGENTS.md` points at the sibling checkout `../agents_md/AGENTS.md` when present and falls back to `../agents.md/AGENTS.md` for older layouts, which keeps your main operating contract centralized for all new sessions without reinstalling OpenCode.

## Canonical first-run commands

Managed MCPs start disabled by default; opt into a focused profile only when you need extra context.

```text
/doctor run
/devtools status
/plugin status
/mcp status
/browser ensure --json
/notify status
/ox
/ox-ux --repo top-uni
/autoflow status --json
/digest run --reason manual
/gateway status
/bg doctor --json
/agent-pool doctor --json
/tmux doctor --json
```

Optional next step when you want lightweight repo or docs context:

```text
/mcp profile research
```

Run `/session handoff --json` after you have at least one indexed digest. If you need to reopen work in a different linked worktree, use `/session handoff --launch-cwd <worktree-path> --fork --json` to get a ready-to-run launch command.

For background runtime ownership, use `/agent-pool` to register or drain visible manual capacity and `/bg` to actually run, inspect, and clean up jobs.

For automation-friendly help output, prefer command-specific help from this repo (for example `python3 scripts/session_command.py help`) because the upstream `opencode --help` banner formatting is not controlled here.

Gateway runtime behavior is primarily tuned through the sidecar config at `.opencode/gateway-core.config.json` (or `MY_OPENCODE_GATEWAY_CONFIG_PATH`). Use that file for normal hook/runtime tuning; if the same gateway keys are also set in root config, the root values still override the sidecar today.

## Common productivity flows

Before you start a task, create a dedicated git worktree branch from the current root branch. Keep the main project folder on `main`, never `git checkout` or `git switch` that folder onto a task branch, and treat the primary project folder on protected branches (`main`, `master`) as edit-blocked by default. Bash usage in that primary protected worktree is limited to inspection, validation, and safe sync/recovery/cleanup commands such as `git fetch`, `git fetch --prune`, `git pull --rebase`, `git pull --rebase --autostash`, `git pull --rebase origin main`, `git merge --no-edit <branch>`, `git merge --ff-only <branch>`, `git worktree add ...`, `git worktree remove ...`, `git branch -d ...`, `git stash push|list|show`, and `oc current|next|queue|resume|done|end-session`. Run those `oc` closeout commands directly from protected `main`; the maintenance helper is only for blocked maintenance bash that needs reroute guidance. Linked worktrees are the place to do normal task mutations, and they stay editable as long as the linked worktree itself is on a non-protected task branch.

```text
/workflow template init ship --json
/delivery start --issue issue-900 --role coder --workflow <workflow.json> --execute --json
/delivery status --json
/ship doctor --json
/init-deep --max-depth 2 --json
/autopilot go --goal "finish current objective" --json
/autoflow start <plan.md> --json
/continuation-stop --reason "manual checkpoint" --json
```

Use this split to stay consistent:

- `/delivery` for normal issue-to-close work
- `/ship` to preflight PR/release readiness before opening or updating a release PR
- `/ship create-pr --issue <id>` when you want the PR template to inherit the latest canonical `/delivery` handoff context for that issue
- `/ship create-pr --issue <id>` also pulls in current `/release-train draft` context so the PR body starts from the latest release narrative
- `/workflow` when you need direct workflow validation or resume controls
- `/autopilot` for open-ended autonomous execution
- `/autoflow` for plan markdown execution
- `/ox-*` when you want a reusable prompt expansion such as UX audit, review/improve, ship, start, wrap, debug, or safe refactor

## OX prompt-pack shortcuts

Use the `ox` namespace when you want stable reusable prompt meaning with a short prefix:

```text
/ox
/ox doctor
/ox ecosystem
/browser ensure --json
/ox-ux --repo top-uni
/ox-review "review this code end to end and improve it"
/ox-ship --goal "prepare this branch for PR"
```

Reference guide: `docs/ox-command-pack.md`

Natural-language shortcut path:

```text
/auto-slash preview --prompt "(playwright) analyze the website and polish the UX" --json
/auto-slash preview --prompt "review this code and improve end to end" --json
```

Continuation loop controls:

```text
/autopilot go --goal "continue active objective" --max-cycles 10 --json
/resume smart --json
/continuation-stop --reason "manual checkpoint" --json
```

## References

- Full command catalog: `docs/command-handbook.md`
- OX prompt-pack contracts: `docs/ox-command-pack.md`
- Operator runbook: `docs/operator-playbook.md`
- Worktree-first execution: `docs/parallel-wt-playbook.md`
- Deeper architecture notes: `docs/readme-deep-notes.md`

Optional external delivery-policy references: search your local clone first when available, then use these public links when you need a canonical shareable reference.

- `https://github.com/dmoliveira/agents.md/blob/main/AGENTS.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/index.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/validation-policy.md`
