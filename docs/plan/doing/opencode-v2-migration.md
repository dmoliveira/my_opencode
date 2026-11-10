# OpenCode V2 migration inventory

Status: in progress. This inventory identifies surfaces to investigate; it is not evidence of compatibility.

The [isolated dependency-profile qualification](../../specs/opencode-v2-dependency-profile.md)
tests owned dispatch and generation fencing with synthetic child runtimes only.
It neither ports the backend guard nor grants parent-session authority.

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

The experimental V2 execution sidebar is a separate, unconfigured TUI plugin
under `plugin/gateway-sidebar-v2`. It reads the existing private, bounded status
format for the displayed session's location. Its unit tests and isolated tmux
smoke cover status updates and plugin unload/reload on OpenCode 2.2.6. It does
not provide a V2 status writer or establish gateway security parity; leave it
unconfigured until the V2 gateway and its activation gates are complete.

```sh
npm ci --prefix plugin/gateway-sidebar-v2 --ignore-scripts
npm --prefix plugin/gateway-sidebar-v2 run typecheck
npm --prefix plugin/gateway-sidebar-v2 test
npm --prefix plugin/gateway-sidebar-v2 run test:live -- --opencode-bin /path/to/opencode-2.2.6
```

The separate [native dependency-boundary probe](../../specs/opencode-v2-dependency-boundary-contract.md)
measures the installed 2.2.5 built-in shell with synthetic fixtures only. It does
not enable the gateway or qualify dependency installation authority; terminal
binding, raw-result guarantees and lifecycle revocation remain separate gates.
Native shell permission and `tool.use` policy denied directly submitted and
late-mutated command text in the synthetic controls. They did not prevent a
trusted later hook from changing the shell and `BASH_ENV` so that an owned
startup file ran the same denied command. This is a process-binding limitation,
not a claim that policies sandbox plugin code.

Experimental, unconfigured adapters cover V2 model-context and native transport redaction, tool-output and error redaction, two shell guards, and write/protected-worktree guards. `make gateway-v2-slice-smoke` builds and exercises them with isolated OpenCode processes, synthetic data, disposable Git worktrees and a localhost provider. The live checks cover a late context mutation before the HTTP hook, rejection of unsupported HTTP content, allowed and blocked shell commands, tool-output redaction, sanitized tool errors and redactor failures, explicit permission denial, interactive rejection with or without feedback, one running-tool interruption, and linked versus primary worktree writes. The error adapter accepts only OpenCode 2.2.5 and replaces the error with a host `Tool.Error` containing a redacted or generic message and no original metadata. For plain permission rejection it retains the decline prototype only after checking the internal 2.2.5 shape, and shadows common inherited fields with safe values. Prototype behavior is not fully audited, and this dependency on V2 internals needs security review and regression coverage for each supported runtime. Other cancellation and control-flow errors remain unverified.

These are **not** complete gateway protection or parity. Prototype-shape checks do not authenticate inherited methods: a forged decline prototype matching the checked keys can expose a synthetic secret through custom inspection. This is a confirmed blocker to activating the error adapter; use a trusted host-provided decline type or otherwise establish safe inherited behavior before enabling it. Transport-hook ordering and non-native providers, WebSocket behavior, images and other encodings, large/resumed histories, all four request kinds live, other error paths, command and event lifecycles, and the remaining guards also require validation. The adapters are intentionally not registered in the user's configuration.

The 2.2.5 permission smoke also measures three synthetic controls. A rejection caught directly from `ctx.permission.assert` in a tool owned by the fixture is the same cause later exposed to its after-hook; a fresh object with that observed prototype still stops the step. Dropping the cause or throwing a generic error from the after-hook instead allows a tool result to reach the model. These observations neither authenticate an arbitrary tool's cause nor establish that the observed prototype is safe to retain; they do not authorize the adapter. The smoke fails if the pinned host does not reproduce the controls, rather than assuming another version has the same behavior.

The isolated V2 runtime created `session_v2`, `session_message`, and `session_part` tables. The legacy stale-session scanner reports an incompatible schema and refuses repairs when a `session_v2` table or view exists, case-insensitively, even if old V1 tables remain. A scoped repair retains scan errors rather than reporting success, including an incomplete rescan after a committed repair round. Database path resolution honors `OPENCODE_DB` and explicit XDG data directories without falling back to an unrelated existing database; a separately started service may still have different environment variables. V2-native diagnosis and repair remain unimplemented. The standalone installer, local setup scripts, and gateway diagnostics run their executable-version probes in disposable homes; installer and setup refuse V2 or an unidentifiable executable before installation or configuration changes. Gateway enable also refuses incompatible executables even with `--force`. These probes do not establish the version or protection of a separate service. The local development setup refuses conflicting instruction and agent paths rather than replacing them.

Runtime snapshot application validation still uses the V1-only `--pure db` command. The snapshot flow rejects V2 and unidentifiable validator versions without publishing a bundle; the version of that executable does not establish the source service version. A synthetic V2 `session list --standalone` control opened its selected database but changed the disposable copy, so it is not a qualified replacement for the current strict-copy validation.

The tasker E2E evaluator examines both V1 `bash` and V2 `shell` event records and rejects incomplete or unrecognized evidence, including delegated tools whose nested execution it cannot see. This is a post-run check, not a sandbox. Both tasker harness entrypoints reject V2 and unidentifiable selected executables before fixture creation. This executable-version probe does not verify a separate service or protect against replacement after the probe. The live harness still uses V1 invocation and plugin configuration and is not qualified for V2; event parsing is not a harness port.

The opt-in LLM decision helper now rejects incomplete, ambiguous, errored or tool-bearing event streams, as well as synthetic or ignored text, before accepting or caching a decision. This checks output after execution, not tool prevention or event completeness. Its `allowStandaloneOpencode` setting does not add V2 `--standalone`; a child environment does not prove what a separate service receives. The V2 decision helper and gateway remain unqualified.

The legacy `/mcp` helper refuses an observed native or ambiguous `mcp.servers` layout, including during the locked mutation, rather than claiming a V1 toggle changed the V2 entry. Its resolved layers do not cover every OpenCode configuration source or prove a running service's state; this guard is not a V2 MCP management port.

The legacy `/plugin` helper similarly refuses an observed native or ambiguous `plugins` key, including during locked mutations. Its results describe only helper-resolved legacy configuration, not loaded plugins or active gateway hooks; it does not port V2 plugin management.

The [auxiliary redaction probe](../../specs/opencode-v2-auxiliary-redaction-probe.md) exercises native context, title, generate and compaction request hooks against an owned localhost provider, with unprotected controls and separate system/message canaries. It measures those synthetic requests only; it does not verify compaction completion, other transports, later-hook ordering or gateway protection.

Reference: <https://opencode.ai/v2/docs/migrate-v1> and <https://opencode.ai/v2/docs/build/plugins/migrate-v1>.
