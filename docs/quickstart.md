# Quickstart

## Install and verify

1. Run the installer script from the repository root.
2. Open OpenCode and run a basic health check.
3. Confirm plugin and gateway status.

Startup instructions are loaded from `~/.config/opencode/my_opencode/AGENTS.md` and `~/.config/opencode/my_opencode/instructions/shell_strategy.md`. If you use `./scripts/setup_local_dev_symlinks.sh`, the repo `AGENTS.md` points at the sibling checkout `../agents_md/AGENTS.md` when present and falls back to `../agents.md/AGENTS.md` for older layouts, which keeps your main operating contract centralized for all new sessions without reinstalling OpenCode.

## Canonical first-run commands [h:79a9eb20]
 [h:b29cb517]
Google Drive MCP starts enabled for project access; other managed MCPs start disabled. Use `/mcp profile minimal` to disable all managed MCPs, or enable a focused profile when you need extra context. [h:5ec50bf5]
 [h:90502280]
Required first-run checks: [h:bf437ec9]
 [h:92b53b41]
```text [h:be7b1450]
/doctor run [h:e0fa3cbe]
/devtools status [h:edbb473e]
/plugin status [h:014e2cdb]
/mcp status [h:5435d065]
/notify status [h:2890edfb]
/gateway concise status --json [h:8674ea32]
``` [h:1c9a971a]
 [h:7f7f70d2]
Optional capability checks when you need them: [h:371d5a53]
 [h:69822f88]
```text [h:4d0a35db]
/browser ensure --json [h:eed56897]
/image doctor --json [h:d70ff749]
/autoflow status --json [h:b4a6e840]
/gateway status [h:ba871087]
/bg doctor --json [h:d5f4c4e1]
/agent-pool doctor --json [h:478f2820]
/tmux doctor --json [h:ae3cceae]
``` [h:0a584b58]
 [h:47685be0]
For browser UX work, use the verified CLI path first:
- `/devtools install playwright-cli` verifies `@playwright/cli@0.1.17` before exact on-demand execution.
- Use a unique `-s=<session>` value and close only that session when the flow ends.
- Use `/browser ensure --json` plus `/mcp profile playwright` when integrated MCP network, storage, assertion, or vision tools are the better fit.
- See `docs/playwright-ux-scenarios.md` for both paths. Do not install external CLI skill bundles.

On Darwin arm64, `/devtools install ast-grep` installs only pinned `ast-grep 0.45.0` after archive, binary, and version verification. First set `OPENCODE_DEVTOOLS_CACHE_ROOT` and `OPENCODE_DEVTOOLS_BIN_ROOT` to pre-existing absolute owner-only (`0700`) directories; see `docs/command-handbook.md` for the setup commands. Other host tools remain observation/manual-only, and Playwright CLI remains an explicit install outside `install all`.

Exploratory examples after startup is healthy: [h:9e27aaf8]
 [h:e0a80255]
```text [h:f71fe560]
/ox [h:a4484e02]
/ox-ux --repo top-uni [h:997ec94a]
/ox-design --goal "explore a design direction for this app" [h:7360f925]
/digest run --reason manual [h:c26b764a]
``` [h:df2941d1]
 [h:f9e58fe7]
Optional next step when you want lightweight repo or docs context:

```text
/mcp profile research
```

Run `/session handoff --json` after you have at least one indexed digest. If you need to reopen work in a different linked worktree, use `/session handoff --launch-cwd <worktree-path> --fork --json` to get a ready-to-run launch command.

For background runtime ownership, use `/agent-pool` to register or drain visible manual capacity and `/bg` to actually run, inspect, and clean up jobs.

For automation-friendly help output, prefer command-specific help from this repo (for example `python3 scripts/session_command.py help`) because the upstream `opencode --help` banner formatting is not controlled here.

For low-token command execution defaults, use `docs/silent-first-command-defaults.md` to prefer JSON, quiet, or short forms before expanding to verbose logs.

Gateway runtime behavior uses layered sidecars: `~/.config/opencode/my_opencode/gateway-core.config.json` is the global base, the active project `.opencode/gateway-core.config.json` overrides it, and explicit plugin options apply last. Set `MY_OPENCODE_GATEWAY_CONFIG_PATH` only when one replacement sidecar should bypass the automatic global/project layers. Arrays replace the lower layer; nested objects merge. A malformed layer clears itself and lower-precedence sidecar state; a later valid project override can rebuild the effective config.

That same sidecar file also carries the operator-facing default concise-mode setting (`conciseMode.enabled` + `conciseMode.defaultMode`) consumed by `/gateway concise ...` and the gateway system-context hook.

OpenCode `1.18.18` also loads the local execution-status sidebar through `tui.json`. After installation and restart, its right panel shows the native session title plus deterministic `Last` and `Next` milestones. See `docs/execution-status-sidebar.md` for configuration, privacy bounds, and the no-model live smoke.

## Common productivity flows

Before you start a task, create a dedicated git worktree branch from the current root branch. Keep the main project folder on `main`, never `git checkout` or `git switch` that folder onto a task branch, and treat the primary project folder on protected branches (`main`, `master`) as edit-blocked by default. Bash usage in that primary protected worktree is limited to inspection, validation, safe sync/recovery/cleanup commands, and narrowly scoped bootstrap-safe repo wiring such as `date`, `git fetch`, `git fetch --all --prune --quiet`, `git pull --rebase`, `git pull --rebase --autostash`, `git pull --rebase origin main`, `git merge --no-edit <branch>`, `git merge --ff-only <branch>`, `git remote -v|get-url|add|set-url`, `git push -u origin main`, `git worktree add ...`, `git worktree remove ...`, `git branch -d ...`, `git stash push|list|show`, `gh auth status`, `gh pr view|checks`, `gh repo view|create|edit`, `gh api user`, exact non-interactive npm bootstrap forms (`npm install --yes`, `npm ci --yes` with only `--no-audit|--no-fund|--silent|--ignore-scripts`, and `npm init -y`), and `oc current|next|queue|add task|add session|resume|done|end-session` (including scoped/format arguments). Run those already-allowed commands directly from protected `main`; the maintenance helper is only for blocked maintenance bash that needs reroute guidance. Linked worktrees are the place to do normal task mutations, and they stay editable as long as the linked worktree itself is on a non-protected task branch.

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
/ox-design --focus wireframes,icons,palette
/image prompt --kind wireframe --subject "settings page" --goal "simpler hierarchy" --json
/ox-review "review this code end to end and improve it"
/ox-review "review the latest work, polish it, and fix inconsistencies"
/ox-ship --goal "prepare this branch for PR"
```

Reference guide: `docs/ox-command-pack.md`

Natural-language shortcut path:

```text
/auto-slash preview --prompt "(playwright) analyze the website and polish the UX" --json
/auto-slash preview --prompt "review this code and improve end to end" --json
/auto-slash preview --prompt "review the latest work, polish it, and fix inconsistencies" --json
```

Continuation loop controls:

```text
/autopilot go --goal "continue active objective" --max-cycles 10 --json
/resume smart --json
/continuation-stop --reason "manual checkpoint" --json
```

## References

- Full command catalog: `docs/command-handbook.md`
- Reliability/E2E review runbook: `docs/plan/opencode-reliability-review-runbook.md`
- Silent-first command defaults: `docs/silent-first-command-defaults.md`
- OX prompt-pack contracts: `docs/ox-command-pack.md`
- Operator runbook: `docs/operator-playbook.md`
- Worktree-first execution: `docs/parallel-wt-playbook.md`
- Deeper architecture notes: `docs/readme-deep-notes.md`

Optional external delivery-policy references: search your local clone first when available, then use these public links when you need a canonical shareable reference.

- `https://github.com/dmoliveira/agents.md/blob/main/AGENTS.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/index.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/validation-policy.md`
