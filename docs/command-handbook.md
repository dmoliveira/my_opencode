# Command Handbook

This handbook contains the full slash-command reference previously embedded in `README.md`.

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
/complete resume
```

`/complete <prefix>` returns ranked slash command suggestions with descriptions.
When a retired command name is entered, `/complete` returns a canonical replacement hint.

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

## Session index and handoff inside OpenCode 📚

Use these directly in OpenCode:

```text
/session list --json
/session show <session-id> --json
/session search <query> --json
/session handoff --json
/session doctor --json
```


`/session handoff` emits a concise continuation summary for the latest indexed session (or a specific `--id`) with suggested next actions.

## Claims and workflow coordination 🧩

Use these directly in OpenCode:

```text
/claims claim issue-101 --by agent:orchestrator --json
/claims claim issue-202 --role coder --json
/claims handoff issue-101 --to human:alex --json
/claims accept-handoff issue-101 --json
/claims reject-handoff issue-101 --reason "needs context" --json
/claims expire-stale --hours 48 --apply --json

/workflow validate --file workflows/ship.json --json
/workflow run --file workflows/ship.json --json
/workflow run --file workflows/ship.json --execute --json
/workflow status --json
/workflow resume --run-id wf-20260224091500 --execute --json
/workflow stop --reason "manual intervention" --json

/daemon tick --claims-hours 24 --json

/delivery start --issue issue-900 --role coder --workflow workflows/ship.json --execute --json
/delivery status --json
/delivery handoff --issue issue-900 --to human:alex --json
/delivery close --issue issue-900 --json

/audit status --json
/audit list --limit 20 --json
/audit report --days 7 --json
/audit export --path ./runtime-audit-export.json --json

/governance profile strict --json
/governance authorize workflow.execute --ttl-minutes 30 --json
/governance status --json
```


`/claims claim --role <role>` auto-assigns the least-loaded active agent from `/agent-pool` for that role.
`/workflow run` now supports dependency-aware step ordering (`depends_on`) and records per-step execution results (status, timestamps, failure reason codes). Use `--execute` to run guarded command steps.

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

## Notification policy profiles inside OpenCode 🛡️

Use these directly in OpenCode:

```text
/notify policy status
/notify policy help
/notify policy profile strict
/notify policy profile balanced
/notify policy profile fast
```


`/notify policy` applies policy presets while writing policy metadata under `policy` and channel posture under `notify`.

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

## Complete slash-command index

This index is sourced from `opencode.json` and is used as the complete catalog reference.

```text
/agent-doctor - Validate custom agent contracts and runtime discovery
/audit - Inspect runtime audit trail (status|list|report|export|doctor)
/auto-slash - Detect and preview natural-language slash intents
/autopilot - Continue current task autonomously with autopilot guardrails
/autoflow - Run deterministic plan execution flow (start|status|report|resume|doctor)
/agent-pool - Manage runtime agent pool lifecycle (spawn|list|health|drain|logs|doctor)
/continuation-stop - Stop active continuation loops and disable auto-resume
/bg - Manage background jobs (start|status|list|read|cancel|cleanup|doctor)
/browser - Manage browser automation provider profile (status|profile|doctor)
/budget - Manage execution budget controls (status|profile|override|doctor)
/changes - Explain local change narrative for handoff/release notes (explain|--since)
/claims - Manage collaborative issue claims and handoffs (claim|handoff|accept-handoff|reject-handoff|release|expire-stale|status|list|doctor)
/checkpoint - Manage checkpoint snapshots and runtime rollback (create|restore|list|show|prune|doctor)
/complete - Suggest slash commands by prefix (autocomplete helper)
/config - Backup and restore OpenCode config files
/daemon - Manage observability daemon controls (start|stop|status|tick|summary|doctor)
/delivery - Run unified delivery transactions (start|status|handoff|close|doctor)
/do - Route high-level execution intent to autopilot go
/devtools - Manage external productivity tools (status|doctor|install|hooks-install)
/digest - Generate or show session digests (run|show)
/doctor - Run diagnostics and reason-code registry export
/gateway - Manage plugin gateway mode (status|enable|disable|doctor)
/governance - Manage governance policy profiles and authorizations (status|profile|authorize|revoke|doctor)
/health - Show repo health score and drift insights
/hook-learning - Run hook learning loop controls (pre-command|post-command|route|metrics|doctor)
/hooks - Manage safety hooks (status|help|enable|disable|run)
/hotfix - Run incident hotfix controls with strict close gating (start|status|close|postmortem|remind|doctor)
/init-deep - Initialize hierarchical AGENTS.md scaffolding for current repo
/learn - Capture and manage reusable task knowledge (capture|review|publish|search|doctor)
/mcp - Manage MCP usage (status|help|doctor|profile|enable|disable)
/memory-lifecycle - Manage memory lifecycle ops (stats|cleanup|compress|export|import|doctor)
/model-routing - Manage model routing (status|set-category|resolve|trace)
/notify - Manage notification controls (status|profile|enable|disable|channel)
/nvim - Manage Neovim OpenCode integration (status|doctor|snippet|install|uninstall)
/plan - Run contract-enforced plan execution flows (run|status|doctor)
/plugin - Manage plugin usage (status|doctor|setup-keys|profile|enable|disable)
/post-session - Manage post-session hook config (status|enable|disable|set)
/pr-review - Run PR review copilot analysis with checklist output
/review - Run local review pass with diagnostics and checklist artifacts (local|apply-checklist|doctor)
/refactor-lite - Run safe refactor workflow backend
/release-train - Run release-train workflow controls (status|prepare|draft|publish)
/resume - Manage runtime recovery controls (status|now|smart|disable)
/rules - Inspect conditional rules (status|explain|disable-id|enable-id|doctor)
/safe-edit - Plan semantic safe-edit execution (status|plan|doctor)
/session - Inspect indexed sessions (list|show|search|handoff|doctor)
/ship - Run release intent preflight with safety gates, scaffolding, and create-pr flow
/stack - Apply cross-command profile bundles
/telemetry - Manage telemetry forwarding (status|doctor|profile|enable|disable|set)
/todo - Inspect todo compliance state (status|enforce)
/workflow - Run reusable workflow templates (run|validate|list|status|resume|stop|template|doctor)
```
