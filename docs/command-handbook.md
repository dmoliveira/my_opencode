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

## Complete slash-command index

This index is sourced from `opencode.json` and is used as the complete catalog reference.

```text
/agent-doctor - Validate custom agent contracts and runtime discovery
/auto-slash - Detect and preview natural-language slash intents
/autopilot - Continue current task autonomously with autopilot guardrails
/bg - Manage background jobs (start|status|list|read|cancel|cleanup|doctor)
/browser - Manage browser automation provider profile (status|profile|doctor)
/budget - Manage execution budget controls (status|profile|override|doctor)
/checkpoint - Inspect checkpoint snapshots (list|show|prune|doctor)
/complete - Suggest slash commands by prefix (autocomplete helper)
/config - Backup and restore OpenCode config files
/devtools - Manage external productivity tools (status|doctor|install|hooks-install)
/digest - Generate or show session digests (run|show)
/doctor - Run all diagnostics in one pass
/gateway - Manage plugin gateway mode (status|enable|disable|doctor)
/health - Show repo health score and drift insights
/hooks - Manage safety hooks (status|help|enable|disable|run)
/hotfix - Run incident hotfix controls (start|status|close|remind|doctor)
/keyword-mode - Detect and apply keyword-triggered execution modes
/learn - Capture and manage reusable task knowledge (capture|review|publish|search|doctor)
/mcp - Manage MCP usage (status|help|doctor|profile|enable|disable)
/model-routing - Manage model routing (status|set-category|resolve|trace)
/notify - Manage notification controls (status|profile|enable|disable|channel)
/nvim - Manage Neovim OpenCode integration (status|doctor|snippet|install|uninstall)
/plugin - Manage plugin usage (status|doctor|setup-keys|profile|enable|disable)
/policy - Apply notification policy profiles (strict|balanced|fast)
/post-session - Manage post-session hook config (status|enable|disable|set)
/pr-review - Run PR review copilot analysis with checklist output
/quality - Manage quality profiles and checks (status|profile|doctor)
/refactor-lite - Run safe refactor workflow backend
/release-train - Run release-train workflow controls (status|prepare|draft|publish)
/resume - Manage runtime recovery controls (status|now|disable)
/routing - Explain routing outcomes (status|explain)
/rules - Inspect conditional rules (status|explain|disable-id|enable-id|doctor)
/safe-edit - Plan semantic safe-edit execution (status|plan|doctor)
/session - Inspect indexed sessions (list|show|search|doctor)
/stack - Apply cross-command profile bundles
/telemetry - Manage telemetry forwarding (status|doctor|profile|enable|disable|set)
/todo - Inspect todo compliance state (status|enforce)
```
