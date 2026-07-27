# Harness Optimization Wave 6

Status: done

Depth: large

Risk: high

Review budget: 3-5 changed-evidence review/fix passes

## Objective

Fix reproduced portability, delegation-lifecycle, and LSP transport defects; add one measured, pinned browser workflow without a global install; retire an unsafe dormant MCP default; and prove the candidate on realistic Python and Node projects with `openai/gpt-5.4-mini`.

## Baseline and decisions

- Branch `perf/harness-optimization-wave-6` starts at merged Wave 5 commit `e9521c3ddde9d3a7f68df17086de35c485445475`.
- Main user-authored `opencode.json` and `gateway-core.config.json` edits remain outside this worktree and must be preserved byte-for-byte during final sync.
- No Wave 6 branch or PR existed at intake.
- Tmux sandbox: `ai-oc-harness-wave6`, window `wave6`, panes `baseline`, `runtime`, and `e2e`.
- `make validate` passes with a resolved supported Python but fails under Apple CLT Python 3.9 when `bash -lc` changes `PATH`; union syntax establishes Python 3.10 parsing and `datetime.UTC` establishes Python 3.11 as the actual runtime minimum.
- The default delegation order runs concurrency, lifecycle, and telemetry consumers against one shared child-session link. All three currently delete that link on `session.deleted`, so only the first consumer observes it.
- The LSP RPC client times only initial readability. Partial headers/bodies and an unread stderr pipe can exceed the configured timeout or deadlock.
- Broad 87-hook event-subscription and notification rewrites are too risky for this wave. Only the three touched delegation hooks may receive exact event metadata backed by parity tests.
- External research rejected cloud memory, tracing, context-pruning, type injection, GitHub-agent automation, and always-on hosted MCPs because their authority, egress, overlap, or maintenance cost exceeds measured value.
- Official Playwright CLI `@playwright/cli@0.1.17` passed the isolated stop/go gate:
  - Apache-2.0, Node `>=18`, exact npm integrity `sha512-VBw6y3p8eqOqmjKg07IkWSPGKJkpIhMRNDFI6DOYsDD6fAfcI1XYEWMLWyhSZQ0B/Oc2KN49eq4XqE64PUPHBg==`;
  - no install/prepare lifecycle script in the 15-file tarball;
  - isolated Chrome flow opened a local Todo app, added an item, produced a 245-byte accessibility snapshot and screenshot, then closed with zero orphan processes;
  - pinned MCP emitted 41,397 bytes for 68 tool schemas before a flow, while the fixed CLI flow retained 664 result bytes, a conservative 98.4% schema-overhead reduction.
- The CLI is accepted only as an optional exact-`npx` path. It must not be globally installed, added to required `install all`, made default-on, or allowed to install mutable upstream skills.
- Firecrawl is disabled in bundled config but unpinned and enabled by managed `web` and `all` profiles. Retire it from new defaults while preserving and allowing explicit disablement of existing custom entries.

### External evidence

- OpenCode `v1.18.5`: <https://github.com/anomalyco/opencode/releases/tag/v1.18.5>
- Playwright CLI guidance: <https://playwright.dev/agent-cli/introduction>
- Playwright CLI `v0.1.17`: <https://github.com/microsoft/playwright-cli/releases/tag/v0.1.17>
- Playwright MCP guidance: <https://playwright.dev/mcp/introduction>
- Firecrawl MCP source: <https://github.com/firecrawl/firecrawl-mcp-server>

## Non-goals

- No broad wildcard-hook migration, parallel event dispatch, notification queue rewrite, or process-pressure rewrite.
- No Python 3.9/3.10 compatibility backport and no hidden automatic interpreter search.
- No global npm install, browser-profile persistence, default-on browser process, or automatic external skill installation.
- No machine-specific native reference, credential-backed CI service, or API-key forwarding to model/browser subprocesses.
- No changes to Wave 5 validation-ledger, audit/OTLP, or exact plugin-identity guarantees without new failing evidence.

## Slice 1 — Deterministic Python runtime contract (`task_2`)

Target commit: `fix: enforce supported Python runtime`

Files: `Makefile`, `install.sh`, `.github/workflows/ci.yml`, `tests/test_makefile_python_runtime.py`, and `scripts/selftest.py` only when an existing installer assertion must change.

Implementation:

1. Declare `PYTHON ?= python3` and Python 3.11 as the minimum supported runtime.
2. Add a side-effect-free `python-check` target that reports the selected executable/version and fails before importing repository modules.
3. Route every Python invocation in all Makefile recipes through `$(PYTHON)` and attach `python-check` to every Python-backed target without affecting `help`.
4. Preserve explicit `PYTHON=/absolute/path` overrides. Do not search common filesystem locations or silently select another interpreter.
5. Make `install.sh` reject its PATH-selected `python3` below 3.11 before copying or mutating configuration; the error names the selected executable/version and tells the operator to fix `PATH`.
6. Add a dedicated Python 3.11 CI job running the runtime-contract test, `make validate`, and `make selftest`; retain the existing Python 3.12/Node 22 job.

Acceptance:

- A dynamically resolved supported interpreter passes `make python-check`; `/usr/bin/python3` 3.9 fails with the minimum-version diagnostic.
- The focused test parses the complete Makefile and proves no recipe line invokes bare `python3`.
- `PYTHON=<resolved-supported-path> make validate` passes in tmux; no ARM-Homebrew path is encoded in tracked files.
- Installer dry-run under Python 3.9 exits before mutation; supported dry-run/selftests retain behavior.
- Required Python 3.11 CI has zero skips or failures.

## Slice 2 — Delegation terminal-event fan-out (`task_3`)

Target commit: `fix: fan out delegation terminal lifecycle`

Files:

- `plugin/gateway-core/src/index.ts`
- `plugin/gateway-core/src/hooks/shared/delegation-child-session.ts`
- new `plugin/gateway-core/src/hooks/shared/delegation-terminal-dispatch.ts`
- `plugin/gateway-core/src/hooks/delegation-concurrency-guard/index.ts`
- `plugin/gateway-core/src/hooks/subagent-lifecycle-supervisor/index.ts`
- `plugin/gateway-core/src/hooks/subagent-telemetry-timeline/index.ts`
- new `plugin/gateway-core/test/delegation-terminal-fanout.integration.test.mjs`
- `plugin/gateway-core/test/hook-registry.test.mjs`
- only matching generated files under `plugin/gateway-core/dist/index.*` and `dist/hooks/{shared/delegation-child-session,shared/delegation-terminal-dispatch,delegation-concurrency-guard,subagent-lifecycle-supervisor,subagent-telemetry-timeline}/**`

Coordinator-owned terminal-state model:

1. This wave coordinates only unambiguous terminal events: completed/failed assistant `message.updated` and `session.deleted`. The first of those events wins.
2. `session.idle` is explicitly excluded from centralized qualification/cleanup because lifecycle may classify it as active, probe-failed, or recently unknown. Existing idle probe/recovery behavior and link ownership remain unchanged in this slice.
3. Every coordinated terminal consumer uses a non-destructive child-link lookup. The coordinator clears the link once in `finally` after all selected hooks were attempted.
4. A later coordinated terminal event sees no link and is an idempotent no-op. Completion followed by deletion emits completion reason codes only; deletion reason codes are required only when deletion is first.
5. A shared extractor normalizes child session ID and terminal qualification for message/deletion. Tests prove active, probe-failed, and recent-unknown idle events do not enter the coordinator or gain new cleanup behavior.

Dispatch behavior:

1. Add a narrowly testable `dispatchDelegationTerminalHooks` coordinator used by the real plugin adapter only for completed/failed assistant messages and deletion.
2. On terminal events, continue after hook failures, retain the first fatal (`critical || blocked`) error by dispatch order, complete fan-out/cleanup, then rethrow it. Noncritical failures remain audited and are not promoted.
3. Preserve existing fail-fast behavior for nonterminal events.
4. Add exact event subscriptions only to the three consumers, covering every current branch with parity assertions.
5. Preserve hook IDs, priorities, default order, reason codes, config shape, and reservation semantics.

Acceptance:

- If deletion is first, one event emits exactly one each of `delegation_concurrency_child_deleted_released`, `subagent_lifecycle_child_deleted_reconciled`, and `subagent_telemetry_child_deleted_reconciled` with matching parent/child-run/trace metadata, independent of order.
- If message completion/failure is first, all three matching transitions occur once and a later deletion is a no-op. Idle remains outside coordinator semantics.
- Real `GatewayCorePlugin(...).event(...)` tests cover all six consumer orders, each disabled subset, duplicate/unknown/parent events, interleaved children, and reusable follow-up delegation state.
- Idle regression tests cover active, probe-failed, and recent-unknown lifecycle states and prove the new coordinator is not invoked and introduces no additional cleanup.
- Coordinator fake-hook tests cover one fatal plus noncritical failures, exact first-fatal precedence, full later-hook execution, `finally` cleanup, and rethrow.
- Source/dist parity, lint/build, and full gateway tests pass on current Node and Node 22.

## Slice 3 — Deadline-safe LSP transport (`task_4`)

Target commit: `fix: bound LSP framing and process cleanup`

Files: `scripts/lsp_rpc_client.py`, new `tests/test_lsp_rpc_client.py`, and new `tests/fixtures/fake_lsp_server.py`.

Implementation:

1. Use one absolute `time.monotonic()` deadline across request serialization, complete stdin write/flush, response headers, server-request replies, and response body.
2. Replace `select` plus blocking pipe reads with owned cross-platform stdout reader, stderr drainer, and stdin writer pumps. Bounded queues/buffers communicate with the request thread; timeout teardown closes pipes and terminates/kills the child so blocked pump threads unwind.
3. Cap headers at 64 KiB, bodies at 16 MiB, queued stdout chunks, write queue depth, and retained stderr tail. Reject malformed, negative, conflicting, or oversized `Content-Length` deterministically.
4. Respond to server-to-client requests with JSON-RPC `Method not found`; ignore notifications; continue waiting for the matching client response without resetting the absolute deadline.
5. On initialization/write/read failure, timeout, malformed framing, EOF, shutdown timeout, terminate, or kill: close all streams, stop/join owned pumps, and `wait()` until `poll()` is non-`None`.
6. Preserve public methods, request IDs, successful result shapes, text fallback, and caller-visible timeout category. The pump design supports Python 3.11+ on macOS, Linux, and Windows pipes.

Acceptance:

- Fragmented headers/bodies and a server request succeed within one deadline.
- A fake server that never reads stdin receives a payload larger than pipe capacity; the client times out, kills/reaps it, and joins every pump.
- Mid-header/body stalls and stderr floods cannot exceed timeout plus 0.5 seconds.
- Malformed/oversized length, wrong IDs, EOF, failed initialization, and shutdown escalation are deterministic.
- Tests assert closed streams, dead owned threads, empty/closed queues, and non-`None` process `poll()` after every failure.
- A required tmux smoke against `CLANGD_BIN="$(command -v clangd)"` opens a tiny C file and completes initialize/open/shutdown/exit within 30 seconds. Missing `clangd` is a merge blocker, not a passing skip.
- Focused tests, `py_compile`, critical Ruff, `make validate`, and `make selftest` pass.

## Slice 4 — Browser tooling adoption and MCP retirement (`task_5`)

Target commits: `feat: add verified Playwright CLI path` and `chore: retire managed Firecrawl MCP`.

### Slice 4A — Optional verified Playwright CLI

Files:

- `scripts/playwright_defaults.py`
- `scripts/devtools_command.py`
- new `tests/test_devtools_command.py`
- `scripts/selftest.py` only for existing devtools contract assertions
- `scripts/harness_wave2_task4_smoke.py`
- `tests/test_harness_wave2_task4_smoke.py`
- `.opencode/skills/playwright-web-ux/SKILL.md`
- `docs/quickstart.md`, `docs/command-handbook.md`, `docs/playwright-ux-scenarios.md`, and `docs/ox-command-pack.md`

Implementation:

1. Centralize exact CLI version, package spec, Apache-2.0 license, expected SRI, source revision, Node `>=18`, and safe command beside MCP defaults.
2. Handle npm targets before the existing Homebrew requirement. `install all` remains Homebrew/gh-only and never includes the CLI.
3. `/devtools install playwright-cli` first runs `npm view` for the exact spec in an owner-only versioned cache with empty isolated user/global npm config, fixed public registry, provider/token/secret environment keys removed, and `npm_config_ignore_scripts=true`. Compare version/license/SRI to checked-in expectations before any package execution.
4. Only after provenance matches, run exact `npx --yes @playwright/cli@0.1.17 --version` with the same isolated npm config/cache and ignored lifecycle scripts. Require Node 18+ and exact version output; never use a global install or mutable fallback.
5. Status/doctor report readiness, exact invocation, expected integrity, missing binaries, and drift without executing package/browser code. Optional absence cannot fail ordinary doctor.
6. Make the audited skill CLI-first for standard coding-agent flows. Use unique session names and scoped `close`; reserve `close-all`/`kill-all` for a fully owned isolated HOME/cache gate. Never run `install --skills`.
7. Add a backward-compatible `cli` mode and `--scenario-label wave6` to `scripts/harness_wave2_task4_smoke.py`; preserve existing `all`, `mcp`, and `projects` semantics. CLI mode creates an owner-only temporary HOME/cache/workspace and local Todo fixture/server, verifies metadata/SRI before execution, uses empty npm config and ignored scripts, then runs exact version/open/fill/click/snapshot/screenshot/scoped-close commands with a unique session and machine-checks visible `1 items` plus the added text.
8. CLI mode records every exit, bounded artifact path, before/after sandbox inventory, scoped closure, owned child PIDs, and zero surviving owned processes; only its temporary sandbox may change. Timeout cleanup targets only its owned process group and never calls host-wide `kill-all`.
9. Require exactly 68 MCP tools and keep old defaults backward-compatible. Exact-model output is explicitly directed to `runtime/harness-wave-6/exact-model-e2e`.

Acceptance:

- Metadata/SRI is verified before exact package execution; modified metadata fails closed.
- Tests prove Linux without Homebrew can use the npm target, Node <18 fails, secrets and host `.npmrc` are unavailable, lifecycle scripts are ignored, no global install occurs, and `all` excludes the CLI.
- Harness `cli` mode proves the exact Todo flow, unique session/scoped close, expected snapshot text, sandbox-only file delta, bounded artifacts, and zero surviving owned PIDs within 300 seconds.
- Active docs contain no `install --skills`, unpinned CLI command, or unconditional `kill-all` guidance.
- Disabled MCP remains pinned at `@playwright/mcp@0.0.78`, provenance passes, and inventory is exactly 68 tools.

### Slice 4B — Firecrawl retirement compatibility

Files:

- `scripts/mcp_command.py`
- new `tests/test_mcp_command.py`
- `scripts/selftest.py` only for existing MCP contract assertions
- `opencode.json`
- `README.md`
- `docs/command-handbook.md`

State model:

1. Active managed servers exclude Firecrawl. `enable all` and every profile operate only on active servers.
2. Firecrawl is a retired disable-only target. `enable firecrawl` fails without mutation. `disable firecrawl` changes only `enabled` on an existing entry and is a byte-stable no-op when absent; it never creates defaults.
3. `disable all` disables active servers and any configured retired entry without changing custom command/url/options. Profiles also force an existing retired entry disabled while preserving all other fields.
4. Doctor exposes only retired name/configured/status/reason, never custom endpoint or command text. Enabled retired entries warn with `/mcp disable firecrawl`; disabled/absent retired state is healthy.
5. Remove the unpinned Firecrawl entry from bundled `opencode.json`, managed defaults, `web`, `all`, help enable targets, and active-name docs.

Acceptance:

- New profiles never create or enable Firecrawl.
- Existing custom Firecrawl commands/options remain structurally equal before/after profile or disable except `enabled: false`.
- Absent disable performs no write; retired enable fails; `enable all` excludes and `disable all` safely disables configured retirement state.
- Human and JSON status/doctor never print a retired custom command or URL.

## Delivery — realistic project proof (`task_6`)

Files: this plan (moved to `docs/plan/done/`), new `docs/harness-optimization-wave-6-audit-2026-07-27.md`, and sanitized ignored evidence under `runtime/harness-wave-6/`.

1. Commit each validated slice separately with runtime session `ses_067d2e945ffe5mebe04ifDBZTc` in telemetry.
2. Build the committed gateway candidate and prove source/dist/package parity.
3. Run the parameterized harness explicitly:

   ```bash
   "$PYTHON_BIN" scripts/harness_wave2_task4_smoke.py projects      --repo-root "$PWD"      --output-dir "$PWD/runtime/harness-wave-6/exact-model-e2e"      --scenario-label wave6      --model openai/gpt-5.4-mini      --timeout-seconds 1200      --json
   ```

   The harness must use isolated HOME, OAuth-store-only auth, one exact committed candidate tuple, no project shim, and no API-key forwarding. Its noninteractive-guard tuple proves realistic Python/Node completion but does not claim deletion coverage.
4. Complete both realistic fixtures while preserving tests and touching only intended application source.
5. Prove terminal fan-out separately through `delegation-terminal-fanout.integration.test.mjs`, retaining same-trace reason codes and reusable follow-up state.
6. Sanitize evidence, run reviews, deliver/merge one PR, close/export Codememory, remove tmux/worktree/branches, and sync main while preserving user config hashes.

## Validation matrix

Before any gate, record `PYTHON_BIN` as a `command -v` resolved Python 3.11+ path, `NODE_BIN` as current Node, and `NODE22_BIN` as an exact Node 22 path. A missing required runtime, browser, dynamically resolved `clangd`, provider auth store, registry response, or command is a blocker; it is never recorded as a passing skip.

| Cell | Command family | Timeout | Artifact | Pass rule |
| --- | --- | ---: | --- | --- |
| Baseline | Apple Python `make python-check`; supported `make validate`; version/head capture | 300 s | `runtime/harness-wave-6/baseline/` | reproduced unsupported failure and supported exit 0 |
| Python contract | `"$PYTHON_BIN" -m unittest tests.test_makefile_python_runtime`; installer probes | 120 s | `runtime/harness-wave-6/python-runtime/` | all tests pass; no bare recipe Python |
| Delegation | build plus `node --test test/delegation-terminal-fanout.integration.test.mjs test/hook-registry.test.mjs` | 300 s | `runtime/harness-wave-6/delegation/` | exact transitions, cleanup, and fatal precedence pass |
| LSP | focused unittest and required real `clangd` smoke | 120 s / 30 s | `runtime/harness-wave-6/lsp/` | all fake cases and real lifecycle pass with zero leaks |
| Browser/tooling | focused devtools/MCP/harness tests; metadata/tarball/CLI Todo/MCP inventory | 300 s | `runtime/harness-wave-6/playwright-gate/` | exact provenance, 68 tools, no host writes/orphans/secrets |
| Python full | unittest discovery, `make validate`, `make selftest` | 900 s | `runtime/harness-wave-6/final/python/` | zero failures/skips in required contract cells |
| Node full | lint/build/tests/scenarios on current Node and Node 22 | 900 s each | `runtime/harness-wave-6/final/node-{current,22}/` | zero failures and no test-count regression |
| Package/install | npm package dry-run/extract parity and committed-clone `make install-test` | 600 s | `runtime/harness-wave-6/final/package/` | exact hashes and exit 0 |
| Exact model | parameterized Python/Node projects command above | 1200 s | `runtime/harness-wave-6/exact-model-e2e/` | report PASS, one model/bootstrap, tests unchanged |
| Security | sanitized artifact scans | 120 s | `runtime/harness-wave-6/final/security/` | zero credential/home/temp/raw-tuple/API-key matches |
| Pre-PR | diff check, full selected suite, pre-commit, clean tracked tree | 1200 s | `runtime/harness-wave-6/final/summary.json` | all exits 0 at committed head |

### Executable gate contract

- Python runtime:

  ```bash
  make python-check PYTHON=/usr/bin/python3                 # expected exit 2 on local Python 3.9
  make python-check PYTHON="$PYTHON_BIN"                    # expected exit 0
  "$PYTHON_BIN" -m unittest tests.test_makefile_python_runtime
  PYTHON="$PYTHON_BIN" make validate
  ```

- Delegation and gateway:

  ```bash
  npm --prefix plugin/gateway-core run build
  node --test plugin/gateway-core/test/delegation-terminal-fanout.integration.test.mjs     plugin/gateway-core/test/hook-registry.test.mjs
  npm --prefix plugin/gateway-core run lint
  npm --prefix plugin/gateway-core test
  PATH="$(dirname "$NODE22_BIN"):$PATH" npm --prefix plugin/gateway-core test
  ```

- LSP:

  ```bash
  "$PYTHON_BIN" -m unittest tests.test_lsp_rpc_client
  "$PYTHON_BIN" -m ruff check --select E9,F63,F7,F82 scripts/lsp_rpc_client.py     tests/test_lsp_rpc_client.py tests/fixtures/fake_lsp_server.py
  CLANGD_BIN="$(command -v clangd)" REQUIRE_REAL_CLANGD=1 "$PYTHON_BIN" -m unittest     tests.test_lsp_rpc_client.RealClangdSmokeTest
  ```

  The real-smoke command must report one passed test and no skip; `CLANGD_BIN="$(command -v clangd)"` and its version are recorded before execution.

- Browser/MCP:

  ```bash
  "$PYTHON_BIN" -m unittest tests.test_devtools_command tests.test_mcp_command tests.test_harness_wave2_task4_smoke
  "$PYTHON_BIN" scripts/devtools_command.py install playwright-cli
  "$PYTHON_BIN" scripts/harness_wave2_task4_smoke.py cli --repo-root "$PWD" --output-dir "$PWD/runtime/harness-wave-6/playwright-cli" --scenario-label wave6 --timeout-seconds 300 --json
  "$PYTHON_BIN" scripts/harness_wave2_task4_smoke.py mcp --repo-root "$PWD" --output-dir "$PWD/runtime/harness-wave-6/playwright-mcp" --scenario-label wave6 --timeout-seconds 300 --json
  ```

  Both harness browser commands run inside `ai-oc-harness-wave6:e2e`. `cli` must report `PASS`, a unique session, Todo snapshot assertions, sandbox-only writes, scoped close, and zero surviving owned PIDs.

- Full closure:

  ```bash
  PYTHON="$PYTHON_BIN" make validate
  PYTHON="$PYTHON_BIN" make selftest
  npm --prefix plugin/gateway-core run lint
  npm --prefix plugin/gateway-core test
  node scripts/gateway_workflow_scenario_report.mjs --fail-below 100
  PATH="$(dirname "$NODE22_BIN"):$PATH" npm --prefix plugin/gateway-core test
  PATH="$(dirname "$NODE22_BIN"):$PATH" node scripts/gateway_workflow_scenario_report.mjs --fail-below 100
  git diff --check
  pre-commit run --all-files
  ```

Retained evidence is copied and sanitized before worktree deletion. Any timeout, skip in a required cell, missing artifact, nonzero exit, credential/path leak, or orphan process fails the gate.

## Review gates

1. Architecture review completed before code.
2. Plan critic must approve scope, dependencies, migration safety, and validation before Slice 1.
3. Per-slice verifier runs after each changed batch; no duplicate pass on unchanged evidence.
4. Final critical reviewer audits full diff/evidence; repeat only after fixes.
5. CI/pre-merge requires green CI, latest `origin/main`, overlap check, and affected reruns only after change.

## Deferred or rejected

- Defer broad event indexing, rules-injector bounds, async notifications, session-map infrastructure, and digest persistence hardening.
- Defer deletion of custom Firecrawl entries; retire only managed defaults and preserve user data.
- Reject global/mutable Playwright installs, external skill installation, and default-on browser/MCP processes.
- Reject Type Inject, DCP/Sleev, cloud memory, external tracing, GitHub Action agents, and always-on hosted MCPs.
- Retain disabled MCPs with unique on-demand value; disabled entries have no process cost.
