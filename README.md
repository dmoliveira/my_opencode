# my_opencode 🚀

Welcome to my OpenCode command center! ✨

This repo gives you a clean, portable OpenCode setup with fast MCP controls inside OpenCode itself. Keep autonomous coding smooth, and only turn on external context when you actually need it. ⚡

## Why this setup rocks 🎯

- **One source of truth** for global OpenCode config.
- **Token-aware workflow** by keeping heavy MCPs disabled by default.
- **Instant MCP toggling** with `/mcp` commands in the OpenCode prompt.
- **Portable install** with a one-liner script and symlinked default config path.
- **Worktree-friendly repo** so you can iterate on config safely in feature branches.

## Features and benefits 🌟

- 🧠 Built-in `/mcp` command for `status`, `enable`, and `disable`.
- 🎛️ Built-in `/plugin` command to enable or disable plugins without editing JSON.
- 🔔 Built-in `/notify` command to tune notification behavior by level (all, channel, event, per-channel event).
- 🧾 Built-in `/digest` command for session snapshots and optional exit hooks.
- 📡 Built-in `/telemetry` command to manage LangGraph/local event forwarding.
- ✅ Built-in `/post-session` command to configure auto test/lint hooks on session end.
- 🛡️ Built-in `/policy` command for strict/balanced/fast permission-risk presets.
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
- 💸 Better token control by enabling `context7` / `gh_grep` only on demand.
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
/agent-doctor-json
```

Detailed guide: `docs/agents-playbook.md` 📘

Operating contract: `instructions/agent_operating_contract.md` 🛡️

Autopilot hook migration plan: `docs/autopilot-hook-roadmap.md` 🔁

## Operations Notes

Detailed roadmap history, implementation baselines, and deep-dive capability notes are now maintained in `docs/readme-deep-notes.md` to keep this README focused on day-to-day operator workflows.

Use these references for deeper context:

- `docs/readme-deep-notes.md`
- `docs/plan/oh-my-opencode-parity-high-value-plan.md`
- `instructions/agent_operating_contract.md`

## MCP control inside OpenCode 🧠

Use these directly in OpenCode:

```text
/mcp status
/mcp help
/mcp doctor
/mcp doctor --json
/mcp profile minimal
/mcp profile research
/mcp profile context7
/mcp profile ghgrep
/mcp enable context7
/mcp disable context7
/mcp enable gh_grep
/mcp disable gh_grep
/mcp enable all
/mcp disable all
```

## Plugin control inside OpenCode 🎛️

Use these directly in OpenCode:

```text
/plugin status
/plugin help
/plugin doctor
/plugin doctor --json
/plugin setup-keys
/plugin profile lean
/plugin profile stable
/plugin profile experimental
/plugin enable notifier
/plugin disable notifier
/plugin enable all
/plugin disable all
```


Global command helper shortcuts:

```text
/complete
/complete auto
/complete autopilot
/ac resume
```

`/complete <prefix>` returns ranked slash command suggestions with descriptions.
`/ac` remains a short alias for `/complete`.

Supported plugin names: `notifier`, `morph`, `worktree`.

`all` applies only to the stable set: `notifier`.

`/plugin doctor` checks the current plugin setup and reports missing prerequisites before you enable additional plugins.

`/plugin doctor --json` prints machine-readable diagnostics for automation.

`/plugin setup-keys` prints exact environment/file snippets for missing API keys.

Profiles:
- `lean` -> no managed plugins (gateway-only baseline)
- `stable` -> `notifier`
- `experimental` -> `stable` + `morph`, `worktree`

For Morph Fast Apply, set `MORPH_API_KEY` in your shell before enabling `morph`.


## Notification control inside OpenCode 🔔

Use these directly in OpenCode:

```text
/notify status
/notify help
/notify doctor
/notify doctor --json
/notify profile all
/notify profile quiet
/notify profile focus
/notify profile sound-only
/notify profile visual-only
/notify enable all
/notify disable all
/notify enable sound
/notify disable visual
/notify disable complete
/notify enable permission
/notify channel question sound off
/notify channel error visual on
```


`/notify` writes preferences into layered config under `notify` (or `OPENCODE_NOTIFICATIONS_PATH` when explicitly set):
- global: `enabled`
- channel: `sound.enabled`, `visual.enabled`
- event: `events.<type>`
- per-event channel: `channels.<type>.sound|visual`

## Session digest inside OpenCode 🧾

Use these directly in OpenCode:

```text
/digest run --reason manual
/digest run --reason manual --run-post
/digest show
/digest doctor
/digest doctor --json
```


The digest command writes to `~/.config/opencode/digests/last-session.json` by default.

For automatic digest-on-exit behavior (including `Ctrl+C`), launch OpenCode through:

```bash
~/.config/opencode/my_opencode/scripts/opencode_session.sh
```

Optional environment variables:
- `MY_OPENCODE_DIGEST_PATH` custom output path
- `MY_OPENCODE_DIGEST_HOOK` command to run after digest is written
- `DIGEST_REASON_ON_EXIT` custom reason label (default `exit`)

When `--run-post` is used, digest also evaluates `post_session` config and stores hook results in the digest JSON.

## Post-session hook inside OpenCode ✅

Use these directly in OpenCode:

```text
/post-session status
/post-session enable
/post-session disable
/post-session set command make test
/post-session set timeout 120000
/post-session set run-on exit,manual
```


`/post-session` writes to layered config under `post_session` (or `MY_OPENCODE_SESSION_CONFIG_PATH` when explicitly set):
- `post_session.enabled`
- `post_session.command`
- `post_session.timeout_ms`
- `post_session.run_on` (`exit`, `manual`, `idle`)

Typical flow:
1. Configure command with `/post-session set command <your-test-or-lint-command>`
2. Enable with `/post-session enable`
3. Use wrapper `opencode_session.sh` so command runs automatically on exit/Ctrl+C
4. Optionally run now with `/digest run --reason manual --run-post`

## Permission policy profiles inside OpenCode 🛡️

Use these directly in OpenCode:

```text
/policy status
/policy help
/policy profile strict
/policy profile balanced
/policy profile fast
```


`/policy` writes profile metadata to layered config under `policy` and applies notification posture under `notify` (legacy path env overrides remain supported).

Profiles:
- `strict`: visual alerts for high-risk events, minimal noise
- `balanced`: visual for all events, sound on risk-heavy events
- `fast`: all channels and events enabled for immediate feedback

## Quality profiles inside OpenCode 🧪

Use these directly in OpenCode:

```text
/quality status
/quality profile fast
/quality profile strict
/quality profile off
/quality doctor
```


`/quality` writes profile metadata to layered config under `quality` with toggles for TS lint/typecheck/tests and Python selftest.

Profiles:
- `off`: disable quality checks for local rapid iteration
- `fast`: lint+typecheck+selftest, skip heavier test passes
- `strict`: run full quality gates (including TS tests)

## Plugin gateway controls 🔌

Use these directly in OpenCode:

```text
/gateway status
/gateway enable
/gateway disable
/gateway doctor
```

Notes:
- `/gateway enable` adds local file plugin entry for `gateway-core` into your config plugin list.
- `/gateway enable` now runs a safety preflight (bun + dist + required hook capabilities) and auto-reverts to disabled when preflight fails.
- use `/gateway enable --force` only if you intentionally want to bypass the preflight safeguard.
- `install.sh` now auto-prefers `plugin_gateway` mode when `bun` is available, and falls back to `python_command_bridge` when not available.
- `/gateway status` and `/gateway doctor` run orphan cleanup before reporting runtime loop state.
- `/gateway doctor --json` now includes `hook_diagnostics` and fails when gateway is enabled without a valid built hook surface.
- set `MY_OPENCODE_GATEWAY_EVENT_AUDIT=1` to write hook dispatch diagnostics to `.opencode/gateway-events.jsonl` (override path with `MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH`).

Gateway orphan cleanup report fields (`--json`):

| Field | Type | Meaning |
|---|---|---|
| `orphan_cleanup.attempted` | `boolean` | `true` when cleanup check was evaluated. |
| `orphan_cleanup.changed` | `boolean` | `true` when active orphan loop was deactivated. |
| `orphan_cleanup.reason` | `string` | Cleanup result reason (`state_missing`, `not_active`, `within_age_limit`, `invalid_started_at`, `stale_loop_deactivated`). |
| `orphan_cleanup.state_path` | `string|null` | Updated state path when cleanup changes were persisted. |

Gateway hook diagnostics fields (`--json`):

| Field | Type | Meaning |
|---|---|---|
| `hook_diagnostics.source_hooks_exist` | `boolean` | Source hook modules exist for autopilot-loop, continuation, and safety. |
| `hook_diagnostics.dist_hooks_exist` | `boolean` | Built dist hook modules exist for autopilot-loop, continuation, and safety. |
| `hook_diagnostics.dist_exposes_tool_execute_before` | `boolean` | Built plugin exports slash-command interception handler. |
| `hook_diagnostics.dist_exposes_chat_message` | `boolean` | Built plugin exports chat-message lifecycle handler. |
| `hook_diagnostics.dist_continuation_handles_session_idle` | `boolean` | Continuation hook handles idle-cycle progression logic. |

## Telemetry forwarding inside OpenCode 📡

Use these directly in OpenCode:

```text
/telemetry status
/telemetry help
/telemetry doctor
/telemetry doctor --json
/telemetry profile off
/telemetry profile local
/telemetry profile errors-only
/telemetry set endpoint http://localhost:3000/opencode/events
/telemetry set timeout 1500
/telemetry enable error
/telemetry disable question
```


`/telemetry` writes to layered config under `telemetry` (or `OPENCODE_TELEMETRY_PATH` when explicitly set) and supports:
- global on/off (`enabled`)
- endpoint URL (`endpoint`)
- timeout (`timeout_ms`)
- per-event toggles (`events.complete|error|permission|question`)

For your LangGraph setup, default endpoint target is `http://localhost:3000/opencode/events`.

## Repo layout 📦

- `opencode.json` - global OpenCode config (linked to default path)
- `scripts/mcp_command.py` - backend script for `/mcp`
- `scripts/plugin_command.py` - backend script for `/plugin`
- `scripts/notify_command.py` - backend script for `/notify`
- `scripts/session_digest.py` - backend script for `/digest`
- `scripts/session_command.py` - backend script for `/session`
- `scripts/opencode_session.sh` - optional wrapper to run digest on process exit
- `scripts/telemetry_command.py` - backend script for `/telemetry`
- `scripts/post_session_command.py` - backend script for `/post-session`
- `scripts/policy_command.py` - backend script for `/policy`
- `scripts/doctor_command.py` - backend script for `/doctor`
- `scripts/config_command.py` - backend script for `/config`
- `scripts/stack_profile_command.py` - backend script for `/stack`
- `scripts/browser_command.py` - backend script for `/browser`
- `scripts/start_work_command.py` - backend script for `/start-work`
- `scripts/autoflow_adapter.py` - orchestration adapter for `/autoflow` transition and explain planning
- `scripts/autoflow_command.py` - unified `/autoflow` command surface with dry-run and kill-switch controls
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
