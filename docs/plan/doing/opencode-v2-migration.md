# OpenCode V2 migration inventory

Status: in progress. This inventory identifies surfaces to investigate; it is not evidence of compatibility.

## Confirmed incompatibilities

| Surface | Evidence | Required work |
| --- | --- | --- |
| Gateway loader | `opencode.json` configures `plugin/gateway-core/dist/index.js`, a V1 function export. OpenCode 2.2.5 reports no loaded plugins. | Implement and load a V2 plugin directory; verify activation before claiming protection. |
| Gateway hooks | `plugin/gateway-core/src/index.ts` dispatches V1 tool, command, chat, transform and event hooks. | Map each hook to V2 semantics, explicitly document missing equivalents, test ordering and failure handling. |
| Gateway client | `plugin/gateway-core/src/index.ts` and hooks including `session-recovery`, `continuation`, `preemptive-compaction`, and `todo-continuation-enforcer` use V1 session client methods and message shapes. | Port clients and verify session identity, cancellation, and message conversion. |
| Security | The inactive gateway contains shell and tool guards, output secret filtering and provider-boundary redaction. | Test all relevant request kinds and transports against a controlled provider, including resume and compaction; do not claim protection based only on plugin loading. |
| Sidebar | `plugin/gateway-sidebar/src/index.tsx` requires 1.18.18 and uses the V1 TUI API. | Port slots, state, events, theme and cleanup to the V2 TUI API; test in a real terminal. |
| Live tests | `scripts/gateway_execution_status_live_smoke.py` and `scripts/gateway_resume_redaction_e2e.py` pin 1.18.18 and the former calls V1 endpoints. | Keep V1 coverage distinct and add V2 live tests with a controlled local provider. |

## Further audit required

- `scripts/session_command.py` and `scripts/runtime_history_snapshot.py` inspect or repair runtime SQLite data. Verify V2 paths and schemas using disposable snapshots; never assume a V1 write is safe against a V2 database.
- `scripts/tui_config.py`, `tui.json`, and installer/config tooling target V1 terminal settings. V2 uses global `cli.json`; check migration and preserve existing user settings.
- Search scripts that invoke OpenCode or construct requests, including live smoke scripts and the LLM decision runtime, against V2 CLI and server contracts.
- Verify effective agent permissions and tool names, slash commands, model selection, skills and MCP connections in V2. Supported V1 configuration should not be rewritten merely for syntax.
- Inspect the installed runtime separately: `~/.config/opencode/my_opencode` currently points to `my_opencode-runtime-main`, not this repository's main checkout. Do not overwrite local runtime state.

## Sequence and gates

1. Make diagnostics explicitly report the missing V2 gateway; do not substitute file presence for live activation.
2. Port security-sensitive request and tool boundaries, client calls and lifecycle events. Gate on unit tests and a controlled-provider V2 end-to-end test for each supported request transport and kind.
3. Port remaining gateway behavior and sidebar with feature-specific tests, including cleanup/reload and terminal observation through tmux.
4. Audit database and config tooling with disposable data; port incompatible operations without destructive access to user data.
5. Run the full repository checks and V2 live suite, review security and migration behavior, then deliver by PR and synchronize local main and the separate runtime safely.

## Progress

Experimental, unconfigured adapters cover V2 model-context and native transport redaction, successful tool-output redaction, two shell guards, and write/protected-worktree guards. `make gateway-v2-slice-smoke` builds and exercises them with isolated OpenCode processes, synthetic data, disposable Git worktrees and a localhost provider. The live checks cover a late context mutation before the HTTP hook, rejection of unsupported HTTP content, allowed and blocked shell commands, tool-output redaction, and linked versus primary worktree writes.

These are **not** complete gateway protection or parity. In particular, transport-hook ordering and non-native providers, WebSocket behavior, images and other encodings, large/resumed histories, all four request kinds live, tool errors, command and event lifecycles, and the remaining guards require validation. The adapters are intentionally not registered in the user's configuration.

Reference: <https://opencode.ai/v2/docs/migrate-v1> and <https://opencode.ai/v2/docs/build/plugins/migrate-v1>.
