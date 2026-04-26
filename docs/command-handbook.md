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
/mcp profile playwright
/mcp profile exa
/mcp profile firecrawl
/mcp profile github
/mcp profile web
/mcp profile all
/mcp enable context7
/mcp disable context7
/mcp enable gh_grep
/mcp disable gh_grep
/mcp enable playwright
/mcp disable playwright
/mcp enable exa_search
/mcp disable exa_search
/mcp enable firecrawl
/mcp disable firecrawl
/mcp enable github
/mcp disable github
/mcp enable all
/mcp disable all
```

For browser-first work, start with:

```text
/browser ensure --json
/mcp profile playwright
```

`/browser ensure --json` normalizes the selected browser provider back to `playwright` and returns exact missing dependency guidance when first-run browser friction would otherwise look like “Playwright is not installed”.

Managed MCP names: `context7`, `gh_grep`, `playwright`, `exa_search`, `firecrawl`, `github`.

Default posture: all managed MCPs start disabled until you enable a targeted profile or individual server.

Alias shortcuts: `ghgrep` -> `gh_grep`, `exa` -> `exa_search`.

Profiles:
- `minimal` -> disables all managed MCPs
- `research` -> `context7`, `gh_grep`
- `context7` -> `context7`
- `ghgrep` -> `gh_grep`
- `playwright` -> `playwright`
- `exa` -> `exa_search`
- `firecrawl` -> `firecrawl`
- `github` -> `github`
- `web` -> `playwright`, `exa_search`, `firecrawl`
- `all` -> enables all managed MCPs

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


Supported plugin names: `notifier`, `morph`, `worktree`.

`all` applies only to the stable set: `notifier`.

`/plugin doctor` checks the current plugin setup and reports missing prerequisites before you enable additional plugins.

`/plugin doctor --json` prints machine-readable diagnostics for automation.

`/plugin setup-keys` prints exact environment/file snippets for missing API keys.

Profiles:
- `lean` -> `notifier`
- `stable` -> `notifier`
- `experimental` -> `stable` + `morph`, `worktree`

For Morph Fast Apply, set `MORPH_API_KEY` in your shell before enabling `morph`.

## Design and image workflows 🎨

Use these directly in OpenCode:

```text
/ox-design --goal "explore a calmer onboarding direction"
/ox-design --focus wireframes,icons,palette
/image status
/image access --json
/image preference show --json
/image preference set codex-experimental
/image doctor --json
/image setup-keys
/image prompt --kind wireframe --subject "mobile onboarding" --goal "reduce clutter" --json
/image generate --kind icon --subject "settings gear" --style "minimal, rounded, monochrome" --json
/image generate --provider codex-experimental --kind mockup --subject "mobile onboarding" --goal "cleaner hierarchy" --json
```

Use `/ox-design` for concepting, artifact planning, and image-ready prompt generation.

Use `/image` for explicit image generation into `artifacts/design/`.

Important: `/image` defaults to the OpenAI API path via `OPENAI_API_KEY`; ChatGPT plan access alone does not automatically enable that default path. A separate opt-in `codex-experimental` provider can use your local signed-in Codex session when available.

If you prefer Codex locally, use `/image preference set codex-experimental`. Precedence is: explicit `--provider` > `OPENAI_IMAGE_PROVIDER_PREFERENCE` env > repo-local preference file > hardcoded default.

Preferred safe key storage for this setup: use your local `sk` Keychain flow, then export `OPENAI_API_KEY` only into the current shell right before `/image` usage.

Use `/ox-ux` or `/browser` when the real implemented UI needs browser-first validation.


## Notification control inside OpenCode 🔔

Use these directly in OpenCode:

```text
/notify status
/notify help
/notify doctor
/notify doctor --json
/notify inbox
/notify inbox --limit 10 --json
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

`/notify inbox` reads the repo-local gateway event audit feed from `.opencode/gateway-events.jsonl` (or `MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH` when set). Enable gateway event auditing with `MY_OPENCODE_GATEWAY_EVENT_AUDIT=1` to populate inbox entries, but after a wrapped session use `/gateway continuation report` for the fastest `todo-continuation-enforcer` audit check.

For runtime AI-output injection work, treat the gateway event audit as the fastest way to identify the real render path instead of guessing from nearby lifecycle names. The practical mapping from the timestamp fix is:
- `experimental.chat.messages.transform`: mutate message history or synthetic context before the model call
- `experimental.chat.system.transform`: mutate the system prompt before the model call
- `experimental.text.complete`: mutate the final rendered assistant text that `opencode run` prints to the terminal
- `message.updated` / `message.part.updated` / `message.part.delta`: useful for debugging streaming and message lifecycle state, but not reliable as the final `opencode run` print surface
- `session.idle`: end-of-turn lifecycle signal; too late for terminal text injection in the reproduced timestamp case

Recommended runtime-injection debug loop:
- run `python3 scripts/gateway_command.py status --json` and confirm `runtime_mode` is `plugin_gateway`
- enable audit with `MY_OPENCODE_GATEWAY_EVENT_AUDIT=1`
- smoke test with `opencode run "Tell me one short random fact."`
- inspect `.opencode/gateway-events.jsonl` for the event type that actually fires on the rendered path you care about
- if `opencode run` output is the target, start with `experimental.text.complete` before trying lower-level lifecycle events

The terminal timestamp work landed on `experimental.text.complete` in `plugin/gateway-core/src/index.ts` and `plugin/gateway-core/src/hooks/assistant-message-timestamp/index.ts`. Use that pair as the reference example for future runtime output decoration.

For human-written assistant progress lines in this repo's operating model, prefer host-clock timestamps over inferred timestamps. If you prefix a status line with a time, fetch it from the machine first (for example `date "+%Y-%m-%d %H:%M:%S %Z"`). If that lookup is unavailable, omit the timestamp rather than guessing.

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
- `MY_OPENCODE_GATEWAY_EVENT_AUDIT` audit toggle for hook diagnostics (`opencode_session.sh` defaults to `1`; set `0` to disable)
- `MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BYTES` max audit file size before rotation (`opencode_session.sh` defaults to `8388608`)
- `MY_OPENCODE_GATEWAY_EVENT_AUDIT_MAX_BACKUPS` rotated audit backup count (`opencode_session.sh` defaults to `5`)

When `--run-post` is used, digest also evaluates `post_session` config and stores hook results in the digest JSON.

## Session index and handoff inside OpenCode 📚

Use these directly in OpenCode:

```text
/session list --json
/session show <session-id> --json
/session search <query> --json
/session handoff --json
/session handoff --launch-cwd ../my_opencode-wt-task --fork --json
/session doctor --json
```


`/session handoff` emits a concise continuation summary for the latest indexed session (or a specific `--id`) with suggested next actions. Use `--launch-cwd` to generate a ready-to-run reopen command for a target worktree, and add `--fork` when you want the resumed session to branch from the current one.

If you inspect the runtime SQLite store directly, see `docs/runtime-db-schema.md` for the current table layout, JSON paths, and safe query patterns.

## Shared memory inside OpenCode 🧠

Use these directly in OpenCode:

```text
/memory add --title "Release decision" --content "Use release-train rollups first" --tags release,ops --json
/memory find "release rollups" --json
/memory recall --json
/memory pin <memory-id> --json
/memory summarize --json
/memory promote --source all --json
/memory doctor --json
```

`/memory` stores durable local shared memory in `~/.config/opencode/my_opencode/runtime/shared_memory.db` by default. `/memory-lifecycle` now operates on that same SQLite-backed shared-memory runtime for stats, export, import, cleanup, compress, and doctor flows.

`/memory promote` ingests high-signal local artifacts into shared memory from digests, session index state, workflow history, claims state, and saved doctor reports without calling external services. It also derives internal `memory-ref:` links between related promoted memories where shared session context is available, so recall and handoff flows can carry deterministic session-linked relationships in the returned payloads.

## Claims and workflow coordination 🧩

Use these directly in OpenCode:

```text
/claims claim issue-101 --by agent:orchestrator --json
/claims claim issue-202 --role coder --json
/claims handoff issue-101 --to human:alex --json
/claims accept-handoff issue-101 --json
/claims reject-handoff issue-101 --reason "needs context" --json
/claims expire-stale --hours 48 --apply --json

/reservation status --json
/reservation set --own-paths "plugin/gateway-core/src/**" --active-paths "plugin/gateway-core/src/**,docs/**" --writer-count 2
/reservation export
/reservation clear

/workflow template init ship --json
/workflow validate --file <workflow.json> --json
/workflow run --file <workflow.json> --json
/workflow run --file <workflow.json> --execute --json

/workflow validate --file workflows/ship.json --json
/workflow run --file workflows/ship.json --json
/workflow run --file workflows/ship.json --execute --json
/workflow status --json
/workflow swarm plan --objective "Ship shared memory" --lanes 3 --claim-ids issue-301 --writer-paths scripts/*.py --json
/workflow swarm plan --objective "Custom graph" --graph-file workflows/swarm-custom.json --claim-ids issue-301 --json
/workflow swarm status --json
/workflow swarm doctor --json
/workflow swarm handoff --lane-id lane-2 --to agent:review-1 --json
/workflow swarm accept-handoff --lane-id lane-2 --by agent:review-1 --bg-command "python3 scripts/selftest.py" --json
/workflow swarm complete-lane --lane-id lane-2 --summary "Review completed" --json
/workflow swarm fail-lane --lane-id lane-3 --reason "Verification failed" --json
/workflow swarm reset-lane --lane-id lane-3 --json
/workflow swarm retry-lane --lane-id lane-3 --json
/workflow swarm resolve-failure --lane-id lane-3 --json
/workflow swarm rebalance --lane-id lane-2 --json
/workflow swarm close --reason "manual close" --json
/workflow resume --run-id wf-20260224091500 --execute --json
/workflow stop --reason "manual intervention" --json

/daemon tick --claims-hours 24 --json

/delivery start --issue issue-900 --role coder --workflow <workflow.json> --execute --json
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

<<<<<<< HEAD
Background runtime triage split:

- use `/bg doctor --json` for backend execution health, queue depth, stale-running jobs, and failure triage
- use `/agent-pool doctor --json` and `/agent-pool health --json` for manual capacity registry visibility plus backend health passthrough
- use `/agent-pool drain --id <agent_id> --json` to mark capacity unavailable, and `/bg cleanup --json` to prune stale/terminal backend jobs
=======
`/workflow swarm` is the initial swarm prototype on top of current runtime contracts. It creates inspectable multi-lane plans using `workflow`, `claims`, `agent-pool`, and `reservation` state. Each lane now carries explicit `depends_on` metadata, `path_scopes`, and reservation/access metadata. Read-only lanes are explicitly marked with `reservation_mode: reservation-safe-read`, while write-capable lanes stay `writer-reserved`. You can also author a custom lane graph with `--graph-file`, as long as the graph is acyclic and lane metadata is valid. Write-capable custom lanes may also carry `lease_identity` to pin activation to a specific expected lease owner. `handoff` and `rebalance` mutate lane ownership safely, `accept-handoff` activates a handoff-pending lane and can enqueue controlled background work only for a narrow allowlist (`make validate|selftest|install-test`, `python3 scripts/selftest.py`, `python3 scripts/doctor_command.py`), and `complete-lane`/`fail-lane` add explicit lane outcome transitions with swarm-level progress summaries, follow-up guidance, explicit failure-recovery policy, and deterministic auto-progression of the next planned lane into `handoff-pending` when no other lane is active. Failed lanes can now be `reset-lane` back to `planned`, `retry-lane` into `handoff-pending`, or `resolve-failure` to execute the currently recommended recovery action automatically. Coordination remains conservative; dependency-satisfied read-only lanes can activate in parallel only when reservation-safe read guarantees are present and lane `path_scopes` do not overlap. A tiny write-capable parallel allowlist is now enabled for disjoint `implement` lanes only when lease-backed writer guarantees are present, dependencies are satisfied, writer `path_scopes` do not overlap, and the activating owner matches both the reservation lease owner and any lane-level `lease_identity`. All other write-capable lanes remain serialized. `/reservation set` does not auto-mint lease fields; lease-backed writer guarantees must be supplied explicitly.
>>>>>>> 551182d (Build local shared-memory and swarm execution foundation)

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
/gateway watchdog status
/gateway watchdog doctor
/gateway watchdog set --warning-threshold-seconds 60 --tool-call-threshold 12 --reminder-cooldown-seconds 60
/gateway watchdog disable
/gateway continuation report --minutes 120 --limit 10 --json
/gateway tune memory --json
/gateway recover memory --apply --resume --compress --force-kill
/gateway protection report --limit 20 --json
```

Notes:
- `/gateway enable` adds local file plugin entry for `gateway-core` into your config plugin list.
- `/gateway enable` now runs a safety preflight (bun + dist + required hook capabilities) and auto-reverts to disabled when preflight fails.
- use `/gateway enable --force` only if you intentionally want to bypass the preflight safeguard.
- `install.sh` now auto-prefers `plugin_gateway` mode when `bun` is available, and falls back to `python_command_bridge` when not available.
- `/gateway status` and `/gateway doctor` run orphan cleanup before reporting runtime loop state.
- `/gateway watchdog status` shows the effective long-turn watchdog thresholds and any sidecar overrides.
- `/gateway watchdog doctor` flags disabled pulse injection, overly aggressive thresholds, and missing cooldown protection with quick fix commands.
- `/gateway watchdog set --warning-threshold-seconds <n> --tool-call-threshold <n> [--reminder-cooldown-seconds <n>]` writes long-turn watchdog overrides to `gateway-core.config.json` without editing the main OpenCode config.
- `/gateway watchdog enable` and `/gateway watchdog disable` toggle runtime progress pulse injection from the same sidecar config.
- `/gateway status --json` now includes `mistake_ledger` so operators can see whether validation deferrals are accumulating in `.opencode/mistake-ledger.jsonl`.
- `/gateway doctor --json` now includes `hook_diagnostics` and fails when gateway is enabled without a valid built hook surface.
- `/gateway continuation report --json` summarizes recent `todo-continuation-enforcer` audit events so you can see reason codes, stages, and affected sessions quickly.
- `/gateway continuation report --json` now also exposes `assistant_message_open_todo_events` so you can spot intermediate assistant replies that landed while todos were still open.
- after a wrapped session, `/gateway continuation report` is the fastest check for recent `todo-continuation-enforcer` activity.
- parity and naming differences vs upstream are tracked in `docs/upstream-divergence-registry.md`.
- `scripts/opencode_session.sh` now enables `MY_OPENCODE_GATEWAY_EVENT_AUDIT=1` by default with rotation; set `MY_OPENCODE_GATEWAY_EVENT_AUDIT=0` to disable or override path with `MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH`.
- set `MY_OPENCODE_GATEWAY_DISPATCH_SAMPLE_RATE=<n>` to reduce noisy dispatch audit events (`message.*`, `session.*`, transform dispatch); `1` logs every event, default is `20`.

Debug and troubleshooting guidance:
- if you launch through `scripts/opencode_session.sh`, gateway event audit is on by default; launch plain `opencode` or set `MY_OPENCODE_GATEWAY_EVENT_AUDIT=0` when you want a quiet run.
- with audit enabled, expect small extra CPU/file-I/O overhead and log growth; this is not a direct model token-cost increase by itself.
- after diagnosis, disable audit again to reduce background noise and disk churn.

## Delegation health summary 🧪

Use these directly in OpenCode:

```text
/delegation-health status
/delegation-health status --minutes 120 --json
/delegation-health doctor
/delegation-health doctor --json
```

Notes:
- reads gateway audit events from `.opencode/gateway-events.jsonl` by default (or `MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH`).
- `status` summarizes recent delegation reason codes and per-subagent signal ratios.
- `doctor` warns on mutation-intent blocks / denied-tool enforcement and fails on excessive fallback routing.

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

## Recommended flow map

- `/delivery` -> recommended day-to-day issue delivery surface
- `/workflow` -> lower-level engine behind reusable workflow runs
- `/autopilot` -> open-ended autonomous execution surface
- `/autoflow` -> public deterministic plan-file execution surface
- `/autopilot` and `/autoflow` share the same task-graph mental model; prefer `/autopilot` for open-ended objectives and `/autoflow` for plan-file-driven work
- `/ox-*` provides a stable custom prompt-pack namespace for reusable automation expansions such as UX audits, review/improve loops, ship readiness, task bootstrap, and session wrap-up

- compatibility aliases are listed below; keep operator guidance canonical-first

### Compatibility aliases (secondary)

- `/do` -> shorthand alias for `/autopilot`
- `/plan` -> compatibility/internal contract-checking wrapper; prefer `/autoflow` for new usage
- `/start-work` -> legacy alias path that redirects to `/autoflow`; keep `/autoflow` in new guidance

## OX prompt-pack namespace

Use `ox` when you want a short custom prefix that expands into a repeatable execution contract instead of rewriting the same request each time.

```text
/ox
/ox doctor
/ox ecosystem
/ox-ux --repo top-uni
/ox-review "review this branch end to end and improve it"
/ox-ship --goal "prepare this branch for PR"
/ox-start --scope "new task bootstrap"
/ox-wrap
/ox-debug --target "failing mobile nav"
/ox-refactor --scope scripts/ox_command.py
```

Detailed contracts and ecosystem notes: `docs/ox-command-pack.md`

Natural-language routing examples:

```text
/auto-slash preview --prompt "(playwright) analyze the website and polish the UX" --json
/auto-slash preview --prompt "review this code and improve end to end" --json
/auto-slash preview --prompt "is this branch ready to ship?" --json
```

Continuation/iteration controls stay canonical under the existing loop surface:

```text
/autopilot go --goal "continue active objective" --max-cycles 10 --json
/autopilot resume --json
/resume now --interruption-class tool_failure --json
/resume smart --json
/continuation-stop --reason "manual checkpoint" --json
```

## Complete slash-command index

This index is sourced from `opencode.json` and is used as the complete catalog reference.

```text
/agent-doctor - Validate custom agent contracts and runtime discovery
/agent-catalog - Explore runtime agent catalog and per-agent guidance (list|explain|doctor)
/audit - Inspect runtime audit trail (status|list|report|export|doctor)
/auto-slash - Detect and preview natural-language slash intents
/autopilot - Continue current task autonomously with autopilot guardrails
/autoflow - Run deterministic plan execution flow (start|status|report|resume|doctor)
/agent-pool - Manage manual runtime capacity registry and lifecycle controls (spawn|list|health|drain|logs|doctor); capacity registration does not start workers, and `/bg` remains the execution backend
/continuation-stop - Stop active continuation loops and disable auto-resume
/bg - Manage background jobs as the execution backend (start|status|list|read|cancel|cleanup|doctor)
/browser - Manage browser automation provider profile (status|profile|doctor)
/budget - Manage execution budget controls (status|profile|override|doctor)
/changes - Explain local change narrative for handoff/release notes (explain|--since)
/claims - Manage collaborative issue claims and handoffs (claim|handoff|accept-handoff|reject-handoff|release|expire-stale|status|list|doctor)
/checkpoint - Manage checkpoint snapshots and runtime rollback (create|restore|list|show|prune|doctor)
/config - Backup/restore and sanitize OpenCode config files (status|layers|backup|list|restore|sanitize|safe-start)
/daemon - Manage observability daemon controls (start|stop|status|tick|summary|doctor)
/delivery - Run unified delivery transactions (start|status|handoff|close|doctor)
/delegation-health - Summarize delegation health and detect routing drift (status|doctor)
/devtools - Manage external productivity tools (status|doctor|install|hooks-install)
/digest - Generate or show session digests (run|show)
/doctor - Run diagnostics and reason-code registry export
/gateway - Manage gateway runtime controls (status|enable|disable|doctor|watchdog|continuation report|tune memory|recover memory|protection)
/governance - Manage governance policy profiles and authorizations (status|profile|authorize|revoke|doctor)
/health - Show repo health score and drift insights
/hook-learning - Run hook learning loop controls (pre-command|post-command|route|metrics|doctor)
/hooks - Manage safety hooks (status|help|enable|disable|run)
/hotfix - Run incident hotfix controls with strict close gating, followup linking, and followup-open previews (start|status|close|postmortem|remind|doctor)
/init-deep - Initialize hierarchical AGENTS.md scaffolding for current repo
/learn - Capture and manage reusable task knowledge (capture|review|publish|search|doctor)
/mcp - Manage MCP usage (status|help|doctor|profile|enable|disable)
/memory - Manage shared memory content (add|find|recall|pin|summarize|doctor)
/memory-lifecycle - Manage memory lifecycle ops (stats|cleanup|compress|export|import|doctor)
/model-routing - Manage model routing (status|set-category|resolve|trace|recommend)
/notify - Manage notification controls (status|profile|enable|disable|channel)
/nvim - Manage Neovim OpenCode integration (status|doctor|snippet|install|uninstall)
/ox - Namespace catalog, diagnostics, and ecosystem links for the `/ox-*` prompt-pack family
/ox-debug - Expand a debug-and-fix execution contract with reproduction and regression focus
/ox-refactor - Expand a safe refactor execution contract with bounded scope and validation cues
/ox-review - Expand an end-to-end code review and improvement execution contract
/ox-ship - Expand a ship-readiness validation and PR-prep execution contract
/ox-start - Expand a task-bootstrap execution contract with worktree and scope cues
/ox-ux - Expand a browser-first UX audit and polish execution contract
/ox-wrap - Expand a session wrap-up and handoff execution contract
/plan - Compatibility/internal wrapper for plan execution flows (run|status|doctor); prefer /autoflow
/plugin - Manage plugin usage (status|doctor|setup-keys|profile|enable|disable)
/post-session - Manage post-session hook config (status|enable|disable|set)
/pr-review - Run PR review copilot analysis with checklist output
/reservation - Manage file reservation state for parallel writer guardrails (status|set|clear|export)
/review - Run local review pass with diagnostics and checklist artifacts/findings (local|apply-checklist|doctor)
/refactor-lite - Run safe refactor workflow backend
/release-train - Run release-train workflow controls (status|prepare|draft|rollup|publish with optional --profile docs-only|runtime)
/resume - Manage runtime recovery controls (status|now|smart|disable)
/rules - Inspect conditional rules (status|explain|disable-id|enable-id|doctor)
/safe-edit - Plan semantic safe-edit execution (status|plan|doctor)
/session - Inspect indexed sessions (list|show|search|handoff|doctor)
/ship - Run release intent preflight, readiness diagnostics, delivery/release context summaries, and policy-aware reviewer routing (doctor|create-pr)
/stack - Apply cross-command profile bundles
/telemetry - Manage telemetry forwarding (status|doctor|profile|enable|disable|set)
/todo - Inspect todo compliance state (status|enforce)
/workflow - Run reusable workflow templates and swarm planning (run|validate|list|status|resume|stop|swarm|template|doctor)
```
