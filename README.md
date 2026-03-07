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

## Support 💛

If this project helps your workflow, please consider supporting ongoing maintenance:

- https://buy.stripe.com/8x200i8bSgVe3Vl3g8bfO00

## Why this setup rocks 🎯

- **One source of truth** for global OpenCode config.
- **Token-aware workflow** by keeping heavy MCPs disabled by default.
- **Instant MCP toggling** with `/mcp` commands in the OpenCode prompt.
- **Portable install** with a one-liner script and symlinked default config path.
- **Worktree-friendly repo** so you can iterate on config safely in feature branches.

## Features and benefits 🌟

- 🧠 Built-in `/mcp` command for `status`, `help`, `doctor`, `profile`, `enable`, and `disable`.
- 🎛️ Built-in `/plugin` command to enable or disable plugins without editing JSON.
- 🔔 Built-in `/notify` command to tune notification behavior by level (all, channel, event, per-channel event).
- 🧾 Built-in `/digest` command for session snapshots and optional exit hooks.
- 📡 Built-in `/telemetry` command to manage LangGraph/local event forwarding.
- ✅ Built-in `/post-session` command to configure auto test/lint hooks on session end.
- 🛡️ Policy profiles available via `/notify policy profile <strict|balanced|fast>`.
- 🧵 Built-in `/bg` command for minimal background job orchestration and retrieval.
- 🧱 Built-in `/refactor-lite` command for preflighted, safe-first refactor workflows.
- 🧠 Built-in `/safe-edit` command for semantic adapter planning and readiness diagnostics.
- 🩺 Built-in `/doctor` umbrella command for one-shot health checks.
- 🤖 Built-in `/agent-doctor` command for custom agent contract and runtime checks.
- 💾 Built-in `/config` command for backup/restore snapshots.
- 🧩 Built-in `/stack` bundles for coordinated multi-command profiles.
- 🌐 Built-in `/browser` command for provider switching and dependency diagnostics.
- ⏱️ Built-in `/budget` command for execution budget profile, override, and diagnostics.
- 🧠 Custom agents for Tab selection: `orchestrator` (primary), plus `explore`, `librarian`, `oracle`, `verifier`, `reviewer`, and `release-scribe` subagents.
- 🧠 Built-in `/nvim` command to install and validate deeper `opencode.nvim` keymap integration.
- 🧰 Built-in `/devtools` command to manage external productivity tooling.
- 🧭 Built-in `/auto-slash` command to map natural-language intent to safe slash command previews.
- 🗺️ Built-in `/autoflow` command for deterministic plan execution (status/report/resume/doctor).
- 🧾 Built-in `/session handoff` for concise continuation summaries with next actions.
- 🧱 Built-in `/init-deep` command to scaffold hierarchical `AGENTS.md` guidance.
- 🛑 Built-in `/continuation-stop` for one-shot continuation shutdown (autopilot stop + resume disable).
- 💸 Better token control with MCP profiles (`minimal`, `research`, `web`, `all`) and on-demand toggling.
- 🔒 Autonomous-friendly permissions for trusted project paths.
- 🔁 Easy updates by rerunning the installer.
- 🧩 Clear, versioned config for experiments and rollbacks.

## Agent roles (Tab menu)

This setup keeps `build` as the default agent, and adds focused specialists for manual selection via `Tab`:

- `orchestrator` (primary): execution lead for complex tasks, with explicit delegation and completion gates.
- `explore` (subagent): read-only internal codebase scout.
- `librarian` (subagent): read-only external docs and OSS evidence researcher.
- `oracle` (subagent): read-only architecture/debug advisor for hard tradeoffs.
- `verifier` (subagent): read-only validation runner for test/lint/build checks.
- `reviewer` (subagent): read-only quality/risk review pass before final delivery.
- `release-scribe` (subagent): read-only PR/changelog/release-notes writer from git evidence.

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
/mcp profile research
/notify status
/autoflow status --json
/session handoff --json
/autopilot go --goal "finish current objective" --json
/gateway status
```

Use `/complete <prefix>` for command discovery, `docs/command-handbook.md` for full command examples, and `docs/operator-playbook.md` for canonical operator flows.

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
- `scripts/autoflow_command.py` - backend script for `/autoflow`
- `scripts/init_deep_command.py` - backend script for `/init-deep`
- `scripts/continuation_stop_command.py` - backend script for `/continuation-stop`
- `scripts/opencode_session.sh` - optional wrapper to run digest on process exit
- `scripts/telemetry_command.py` - backend script for `/telemetry`
- `scripts/post_session_command.py` - backend script for `/post-session`
- `scripts/policy_command.py` - policy profile helper used by `/notify policy ...` and stack presets
- `scripts/doctor_command.py` - backend script for `/doctor`
- `scripts/update_release_index.py` - helper script to regenerate `docs/plan/v0.4-release-index.md`
- `scripts/update_docs_automation_summary.py` - helper script to regenerate `docs/plan/docs-automation-summary.md`
- `scripts/docs_automation_sync_check.py` - checker script for docs automation workflow/pages/summary synchronization
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
