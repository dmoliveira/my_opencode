# my_opencode 🚀

![CI](https://img.shields.io/github/actions/workflow/status/dmoliveira/my_opencode/ci.yml?branch=main&label=CI)
![Latest Release](https://img.shields.io/github/v/release/dmoliveira/my_opencode?label=latest%20release)
![License](https://img.shields.io/github/license/dmoliveira/my_opencode)

> ## Build fast, ship confidently, stay in flow
>
> OpenCode command center for high-signal automation, deterministic validation, and release-ready workflows.
>
> Docs hub: `docs/pages/index.html`
> Support: https://buy.stripe.com/8x200i8bSgVe3Vl3g8bfO00

Welcome to my OpenCode command center! ✨

This repo gives you a clean, portable OpenCode setup with fast MCP controls inside OpenCode itself. Keep autonomous coding smooth, and only turn on external context when you actually need it. ⚡

Start here: `docs/quickstart.md`

## Related playbook repo

For the reusable delivery contract and lighter-weight policy docs that complement this runtime repo, search your local clone first when available, and use these public references when you need a shareable or canonical link:

- `https://github.com/dmoliveira/agents.md/blob/main/AGENTS.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/index.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/validation-policy.md`
- `https://github.com/dmoliveira/agents.md/blob/main/docs/plan/README.md`

Treat them as optional supporting references, not required startup context for every run.

## Support 💛

If this project helps your workflow, please consider supporting ongoing maintenance:

- https://buy.stripe.com/8x200i8bSgVe3Vl3g8bfO00

## Local dev install

For a live local checkout that OpenCode reads directly, use the bootstrap script:

```bash
./scripts/setup_local_dev_symlinks.sh
```

This keeps `~/.config/opencode/my_opencode` pointed at your working repo, keeps `~/.config/opencode/opencode.json` pointed at this repo's `opencode.json`, symlinks repo agents into `~/.config/opencode/agent/`, refreshes `AGENTS.md` from the sibling `../agents_md/AGENTS.md` when present (with `../agents.md/AGENTS.md` as a compatibility fallback), and creates the `plugin/gateway-core@latest` symlink used by the local file-plugin workaround.

New OpenCode sessions now load `~/.config/opencode/my_opencode/AGENTS.md` as a global startup instruction. In the local-dev symlink setup, that file resolves to the sibling checkout at `../agents_md/AGENTS.md` when present (or `../agents.md/AGENTS.md` in older layouts), so edits to the central file propagate automatically to any newly started session, even when launched from an unrelated folder and without rerunning installation.

## Why this setup rocks 🎯

- **One source of truth** for global OpenCode config.
- **Token-aware workflow** by keeping managed MCPs disabled by default.
- **Instant MCP toggling** with `/mcp` commands in the OpenCode prompt.
- **Portable install** with a one-liner script and symlinked default config path.
- **Worktree-first repo**: start each task in a dedicated git worktree branch and keep the main project folder off task branches.

## Features and benefits 🌟

- 🧠 Built-in `/mcp` command for `status`, `help`, `doctor`, `profile`, `enable`, and `disable`.
- 🎛️ Built-in `/plugin` command to enable or disable plugins without editing JSON.
- 🔔 Built-in `/notify` command to tune notification behavior and inspect a repo-local notification inbox feed.
- 🧾 Built-in `/digest` command for session snapshots and optional exit hooks.
- 🧠 Built-in `/memory` command for local shared-memory capture, retrieval, recall, and summarization.
- 📡 Built-in `/telemetry` command to manage LangGraph/local event forwarding.
- ✅ Built-in `/post-session` command to configure auto test/lint hooks on session end.
- 🛡️ Policy profiles available via `/notify policy profile <strict|balanced|fast>`.
- 🧵 Built-in `/bg` command for minimal background job orchestration and retrieval.
- 🧱 Built-in `/refactor-lite` command for preflighted, safe-first refactor workflows.
- 🗂️ Built-in `/reservation` command to manage file reservation state for parallel writer guardrails.
- 🧠 Built-in `/safe-edit` command for semantic adapter planning and readiness diagnostics.
- 🩺 Built-in `/doctor` umbrella command for one-shot health checks.
- 🤖 Built-in `/agent-doctor` command for custom agent contract and runtime checks.
- 💾 Built-in `/config` command for backup/restore snapshots.
- 🧩 Built-in `/stack` bundles for coordinated multi-command profiles.
- 🌐 Built-in `/browser` command for provider switching and dependency diagnostics.
- ⏱️ Built-in `/budget` command for execution budget profile, override, and diagnostics.
- 🧠 Custom runtime agents: `orchestrator` (Tab-visible primary), plus hidden specialists such as `explore`, `librarian`, `oracle`, `verifier`, `reviewer`, `release-scribe`, `experience-designer`, `strategic-planner`, `ambiguity-analyst`, and `plan-critic`.
- 🧠 Built-in `/nvim` command to install and validate deeper `opencode.nvim` keymap integration.
- 🧰 Built-in `/devtools` command to manage external productivity tooling.
- 🧭 Built-in `/auto-slash` command to map natural-language intent to safe slash command previews.
- 🧩 Built-in `/ox` + `/ox-*` prompt-pack commands for reusable automation expansions such as UX audits, review/improve loops, ship readiness, and wrap-up handoffs.
- 🗺️ Built-in `/autoflow` command for deterministic plan execution (status/report/resume/doctor).
- 🧾 Built-in `/session handoff` for concise continuation summaries with next actions.
- 🧱 Built-in `/init-deep` command to scaffold hierarchical `AGENTS.md` guidance.
- 🛑 Built-in `/continuation-stop` for one-shot continuation shutdown (autopilot stop + resume disable).
- 🧰 `/agent-pool` tracks manual visible capacity while `/bg` remains the job execution backend.
- 💸 Better token control with managed MCPs off by default plus MCP profiles (`minimal`, `research`, `web`, `all`) and on-demand toggling.
- 🔒 Autonomous-friendly permissions for trusted project paths.
- 🔁 Easy updates by rerunning the installer.
- 🧩 Clear, versioned config for experiments and rollbacks.

## Agent roles (Tab menu)

This setup keeps `build` as the default agent for quick direct work, exposes `build`, `plan`, `orchestrator`, and `tasker` in the `Tab` switcher, and keeps focused specialists available as hidden secondary subagents:

- `orchestrator` (primary): execution lead for complex tasks, with explicit delegation and completion gates.
- `tasker` (primary): planning-focused Codememory artifact writer for epics, tasks, dependencies, and durable notes.
- `explore` (subagent): read-only internal codebase scout.
- `librarian` (subagent): read-only external docs and OSS evidence researcher.
- `oracle` (subagent): read-only architecture/debug advisor for hard tradeoffs.
- `verifier` (subagent): read-only validation runner for test/lint/build checks.
- `reviewer` (subagent): read-only quality/risk review pass before final delivery.
- `release-scribe` (subagent): read-only PR/changelog/release-notes writer from git evidence.
- `experience-designer` (subagent): read-only browser-first UX/UI specialist for interaction polish, accessibility, and minimalist experience refinement.
- `strategic-planner` (subagent): read-only sequencing and milestone planning specialist.
- `ambiguity-analyst` (subagent): read-only assumptions and unknowns surfacer for unclear scope.
- `plan-critic` (subagent): read-only feasibility and gate-coverage critic for concrete plans.

Default selection note:

- `build` remains the configured `default_agent` in `opencode.json` for speed.
- `plan` remains the built-in planning primary in OpenCode.
- choose `tasker` when you want planning-only capture into Codememory without executing code or mutating repo files.
- choose `orchestrator` when you want end-to-end multi-step execution with delegation and completion gates.
- choose `experience-designer` through delegation or explicit `@experience-designer` when you want a browser-first UX audit, responsive/accessibility review, or high-signal UI polish guidance.
- specialist subagents stay hidden from `Tab` and are meant for delegation or explicit `@agent` invocation.

Agent files live in `agent/*.md` and install globally to `~/.config/opencode/agent/`.
Agent source-of-truth specs live in `agent/specs/*.json` and generate markdown via `scripts/build_agents.py`.

Quick validation:

```text
/agent-doctor
/agent-doctor --json
```

Detailed guide: `docs/agents-playbook.md` 📘

Operating contract: `instructions/agent_operating_contract.md` 🛡️

Autopilot hook migration plan: `docs/autopilot-hook-roadmap.md` 🔁

## Operations Notes

Detailed roadmap history, implementation baselines, and deep-dive capability notes are now maintained in `docs/readme-deep-notes.md` to keep this README focused on day-to-day operator workflows.

Use these references for deeper context:

- `docs/readme-deep-notes.md`
- `docs/plan/oh-my-opencode-parity-high-value-plan.md`
- `docs/upstream-divergence-registry.md`
- `instructions/agent_operating_contract.md`

## Command Handbook 📚

The full slash-command catalog now lives in `docs/command-handbook.md`.

Quickstart commands:

```text
/doctor run
/plugin status
/mcp status
/notify status
/ox
/ox-ux --repo top-uni
/ox-review "review this branch end to end and improve it"
/delivery status --json
/autopilot go --goal "finish current objective" --json
/autoflow status --json
/gateway status
```

Enable MCPs only when the task benefits from extra context, for example with `/mcp profile research`.

Recommended command split:
- `/delivery` for day-to-day issue delivery and closeout
- `/workflow` for lower-level workflow validation and resume control
- `/autopilot` for open-ended autonomous execution
- `/autoflow` for explicit plan-file execution
- `/ox-*` for stable reusable prompt expansions that you want to keep refining over time

Before implementation work, create a dedicated git worktree branch for the task. Do not edit task files from the main project folder, and do not `git checkout` or `git switch` that folder onto a task branch.

Protected branches (`main`, `master`) in the primary project folder are edit-blocked by default, and bash usage there is limited to inspection, validation, exact sync commands, and narrow read-only SQLite inspection such as `sqlite3 -readonly ... .tables`: `git fetch`, `git fetch --prune`, and `git pull --rebase`.

Use `/complete <prefix>` for command discovery, `docs/command-handbook.md` for full command examples, `docs/operator-playbook.md` for canonical operator flows, and `docs/parallel-wt-playbook.md` for the worktree-first execution checklist.

Managed `/mcp` names: `context7`, `gh_grep`, `playwright`, `exa_search`, `firecrawl`, `github`.

Aliases: `ghgrep` -> `gh_grep`, `exa` -> `exa_search`.

Profiles:
- `minimal` -> disable all managed MCPs
- `research` -> `context7`, `gh_grep`
- `web` -> `playwright`, `exa_search`, `firecrawl`
- `all` -> enable all managed MCPs

## Repo layout 📦

- `opencode.json` - global OpenCode config (linked to default path)
- `scripts/mcp_command.py` - backend script for `/mcp`
- `scripts/plugin_command.py` - backend script for `/plugin`
- `scripts/notify_command.py` - backend script for `/notify`
- `scripts/session_digest.py` - backend script for `/digest`
- `scripts/session_command.py` - backend script for `/session`
- `scripts/ox_command.py` - backend script for `/ox` and the `/ox-*` prompt-pack namespace
- `scripts/autoflow_command.py` - backend script for `/autoflow`
- `scripts/init_deep_command.py` - backend script for `/init-deep`
- `scripts/continuation_stop_command.py` - backend script for `/continuation-stop`
- `scripts/opencode_session.sh` - optional wrapper to run digest on process exit and enable `MY_OPENCODE_GATEWAY_EVENT_AUDIT=1` by default with rotation; after a wrapped session, `/gateway continuation report` is the fastest check for recent `todo-continuation-enforcer` activity
- `scripts/telemetry_command.py` - backend script for `/telemetry`
- `scripts/post_session_command.py` - backend script for `/post-session`
- `scripts/policy_command.py` - policy profile helper used by `/notify policy ...` and stack presets
- `scripts/doctor_command.py` - backend script for `/doctor`
- `scripts/update_release_index.py` - helper script to regenerate `docs/plan/v0.4-release-index.md`
- `scripts/update_docs_automation_summary.py` - helper script to regenerate `docs/plan/docs-automation-summary.md`
- `scripts/docs_automation_sync_check.py` - checker script for docs automation workflow/pages/summary synchronization
- `scripts/pages_readiness_check.py` - checker script for remote GitHub Pages readiness and workflow publishing mode
- `scripts/plan_hygiene_check.py` - checker script for stale plan worklog rows missing closure evidence links
- `scripts/update_wave_completion_doc.py` - helper script to generate wave completion docs from merged PR metadata
- `scripts/release_note_validation_check.py` - checker script for release-note validation heading consistency
- `scripts/release_note_quality_check.py` - checker script for release-note quality scoring and triage signals
- `scripts/wave_linkage_check.py` - checker script for completed-wave plan/completion linkage integrity
- `scripts/wave_handoff_summary.py` - helper script for wave transition handoff action summaries
- `scripts/config_command.py` - backend script for `/config`
- `scripts/stack_profile_command.py` - backend script for `/stack`
- `scripts/browser_command.py` - backend script for `/browser`
- `scripts/budget_command.py` - backend script for `/budget`
- `scripts/release_train_engine.py` - release-train backend engine for preflight, draft, and publish gating
- `scripts/release_train_command.py` - `/release-train` command surface and doctor/checklist integration
- `scripts/hotfix_runtime.py` - incident hotfix runtime profile with checkpoint and timeline capture
- `scripts/todo_command.py` - backend script for `/todo`
- `scripts/resume_command.py` - backend script for `/resume`
- `scripts/safe_edit_adapters.py` - semantic safe-edit adapter and validation helpers
- `scripts/safe_edit_command.py` - `/safe-edit` command surface for semantic adapter planning and diagnostics
- `scripts/todo_enforcement.py` - shared todo compliance enforcement helpers
- `scripts/install_wizard.py` - interactive install/reconfigure wizard
- `scripts/nvim_integration_command.py` - backend script for `/nvim`
- `scripts/devtools_command.py` - backend script for `/devtools`
- `scripts/config_layering.py` - shared layered config + JSONC loader for command scripts
- `install.sh` - one-step installer/updater
- `Makefile` - common maintenance commands (`make help`)
- `.pre-commit-config.yaml` - pre-commit hook definitions
- `lefthook.yml` - fast git hook runner config
- `.envrc.example` - direnv template for local environment variables
- `.github/workflows/ci.yml` - CI checks and installer smoke test

## Linked ecosystem references 🔗

Current public ecosystem references wired into the `ox` command pack:

- `my_opencode` runtime: https://github.com/dmoliveira/my_opencode
- `agents.md` playbook: https://github.com/dmoliveira/agents.md
- `Top Uni` browser-first example target: https://dmoliveira.github.io/top-uni/
- `my-cv-public`: https://dmoliveira.github.io/my-cv-public/cv/human/

For the new `ox` namespace command pack, see `docs/ox-command-pack.md`.

## Maintenance commands 🛠️

```bash
make help
make validate
make selftest
make doctor
make doctor-json
make devtools-status
make hooks-install
make install-test
make release-check
make release VERSION=0.1.1
```

Tip: for local branch testing, installer accepts `REPO_REF`.

Happy shipping! 😄
