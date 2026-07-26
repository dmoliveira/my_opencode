# Harness Optimization Wave 3

## Objective

Ship three evidence-backed improvements that align the gateway with the OpenCode 1.18 plugin contract, preserve configured plugin options, repair canonical chat-message handling, and make repeated gateway diagnostics materially faster. Prove the result with deterministic tests, live read-only runtime measurements, and isolated exact-model projects in tmux.

## Classification

- Depth: large.
- Risk: high because the work changes runtime plugin configuration, message adaptation, and SQLite health classification.
- Review budget: 3–5 changed-evidence review-and-fix passes. Stop once all required checks are green and the latest review has no blocker.

## Evidence baseline

- Official OpenCode 1.18 declarations define `Plugin(input, options?)`, tuple plugin entries as `[string, PluginOptions]`, and `chat.message` user content in `output.parts`.
- Passing `{ "hooks": { "enabled": false } }` as the second plugin argument still constructs 85 hooks, proving that gateway options are ignored.
- Gateway and plugin config mutators do not detect tuple-form gateway entries and delete unrelated tuple entries.
- An official-shaped chat payload leaves keyword mode unset and does not activate think-mode or session-guidance behavior because three hooks cannot see `output.parts` text.
- Three warm `/gateway doctor` runs took 32.480s, 28.119s, and 29.280s. Component measurement attributed 22.639s to the runtime session scan and 9.289s to the direct loader smoke.
- The live read-only runtime database contained 9,195 sessions, 144,205 messages, and 696,182 parts. It already had indexes on `session(parent_id)`, `message(session_id,time_created,id)`, and `part(message_id,id)`.
- An ignored read-only indexed-snapshot prototype scanned 9,193 stale candidates with a 120.87ms warm median after one cold run. Its plan used the message and part indexes and did not materialize full message/part grouping.
- Chat and text-complete callback loops cost only about 20–23 microseconds per call in the fixed benchmark. Further callback routing is not selected for this wave.
- No reviewed external plugin or MCP justified new default-on startup or data-egress surface. The existing disabled `@playwright/mcp@0.0.78 --isolated` exposes 68 tools; `@playwright/cli` remains deferred unless a future workflow benchmark proves a distinct benefit.

## Durable sequence

### task_2 + task_3 — Align OpenCode plugin contracts

1. Accept the official second plugin-options argument with runtime await-compatibility while retaining synchronous legacy access for the existing 253-call test surface. Test both direct access and `await GatewayCorePlugin(ctx, options)`. Merge precedence is sidecar layers, then legacy `ctx.config`, then official options; recursively merge objects and replace arrays/scalars using existing semantics.
2. Honor `hooks.enabled=false` before configurable hook factories are created. Keep the provider-boundary finalizer and direct non-hook callbacks active.
3. Recognize official plugin entries as strings or two-element `[string, object]` lists. Preserve unknown and malformed entries verbatim, identify valid tuples by their first element, retain the first configured representation/options, and remove only matching entries on disable.
4. Make `/plugin` profiles and enable/disable operations tuple-safe. Diagnostics expose normalized package specs only and never option objects.
5. Stage `/gateway enable` in memory and save only after safety checks pass, so a blocked enable cannot destroy an existing tuple or its options.
6. At the gateway `chat.message` boundary, snapshot ordered text from canonical `output.parts` before hooks mutate it. Reuse the same parts/part references and expose the snapshot through the internal compatibility properties. Canonical parts win when present; legacy input fields remain the fallback. Never treat `output.message` as prompt text.
7. Test official and legacy payloads, multipart/no-text input, once-per-session behavior, tuple round trips, duplicate matching entries, malformed entries, option precedence, early hook disablement, provider-boundary retention, rollback, and diagnostic non-disclosure. Assert `output.parts` array/part identity, leave `output.message` untouched, and suppress legacy prompt fallback when canonical parts exist but contain no text.
8. Extend the local runtime smoke with an actual host-loader probe in tmux using an isolated HOME/config, no project shim, and one tuple entry pointing to the candidate dist with `hooks.enabled=false`. Discard raw `opencode debug config` output because it echoes configured options; retain only a sanitized audit-derived result proving one bootstrap, `hooks_enabled=false`, and no option sentinel in the audit. Use `finally` cleanup for isolated config/audit/log files, return no temporary paths, and assert that zero project shims and only sentinel-free sanitized evidence remain. Pair this with the direct callback fixture proving `hook_count=0`.

**Exit:** an isolated tuple-loaded gateway reports zero configurable hooks when options disable them; tuple contents survive every mutator; official chat payloads drive keyword/think/reminder behavior only when those hooks are enabled; the protected repository sidecar remains unchanged.

### task_4a — Replace full-history stale-session scans

1. Inject and freeze one `now_ms` and cutoff per scan. Define latest records as `ORDER BY time_created DESC, id DESC LIMIT 1`; require exact legacy parity when timestamps are unique and treat equal-timestamp selection as an intentional deterministic correction validated against an explicit `id DESC` oracle.
2. Replace repeated full-table `ROW_NUMBER`/`GROUP BY` scans with a stale-session snapshot that uses correlated indexed latest-message/latest-part lookups and an indexed `has_any_child` lookup over all sessions, including fresh children. Do not create, migrate, or hard-code indexes in the upstream runtime database.
3. Detect required index column prefixes rather than relying on index names. Preserve the legacy scanner as an explicit compatibility fallback with a warning when the session-parent, message-session/time/id, or part-message prefixes are unavailable. Preserve all current classifications, annotations, per-type limits, generic count, severity, warnings, and repair inputs. Keep the production connection read-only.
4. Expand the disposable SQLite fixture coverage for every issue type, zero findings, equal timestamps, stale-parent/fresh-child exclusion, terminal/incomplete children, text parts, old running parts, missing-index fallback, malformed schema, and dry-run/apply repair parity.
5. Compare legacy and candidate semantics on one owner-only compact snapshot using the same injected `now_ms`. Canonical parity excludes only scan duration and its latency warning; retain only counts, hashes, query-plan summaries, and timings in tracked evidence.
6. Benchmark six runs, discard the first, and require a warm median below the existing 1,000ms latency budget. Require indexed session-parent, message, and part searches and no full message/part grouping in `EXPLAIN QUERY PLAN`. Use table-driven tests to prove arbitrary index names and valid supersets are accepted while missing or wrong-order column prefixes trigger the warned legacy fallback.

**Exit:** deterministic and compact-snapshot classifications match, repairs are unchanged, and the warm live scan median is below 1,000ms.

### task_4b — Cache successful direct-loader smoke and close E2E

1. Cache only successful direct-loader smoke summaries for 15 minutes under the XDG cache directory. Add `/gateway doctor --fresh [--json]` to bypass cache reads and execute the live smoke exactly once.
2. Key cache validity by a schema version, relevant plugin runtime files, smoke script, resolved OpenCode binary/version/stat, and platform. Validate schema and `0 <= age < 900`. Corrupt, future-dated, expired, mismatched, skipped, or failed evidence always runs the live smoke; failures are never cached, and a forced live non-PASS invalidates any same-key cached PASS.
3. Reject symlink cache paths, use a `0700` directory and same-directory atomic replacement to a `0600` file. Store only `schema`, `fingerprint`, `checked_at`, and an allowlisted result containing `result`, `reason`, `exit`, and per-mode `mode`, `result`, `run_exit`, `audit_exists`, `bootstrap_seen`, `plugin_install_failed`, and `plugin_resolve_failed`. Store no stdout, stderr, environment values, plugin options, credentials, runtime text, or temporary paths.
4. Preserve doctor result semantics and report cache hit, check time, age, and a non-secret fingerprint. Add an explicit deep/fresh path that bypasses the cache.
5. Add `python3 -m unittest discover -s tests -p 'test_*.py'` to `make validate` so new runtime database and cache tests run in CI.
6. In tmux, capture one cold plus at least five warm doctor timings, actual `--fresh` behavior, cache invalidation, and tuple/options runtime behavior. Reuse—not recreate or broaden—the existing Wave 2 project harness: `python3 scripts/harness_wave2_task4_smoke.py projects --repo-root "$PWD" --output-dir runtime/harness-wave-3/exact-model --model openai/gpt-5.4-mini --json`. Do not repeat the Wave 2 MCP scope. Authentication or model unavailability is a blocker, not permission to substitute.

**Exit:** the median of at least five unchanged warm doctor runs is at least 80% faster than the 29.280s baseline median and within 5s; `/gateway doctor --fresh --json` executes the real smoke; exact-model projects start red, are fixed by the build agent without test edits, and finish green with one candidate gateway source and one bootstrap event.

## File scope

- `plugin/gateway-core/src/{index.ts,config/load.ts}` and generated `dist/**`.
- Focused gateway tests for plugin options and canonical chat payloads.
- `scripts/{gateway_plugin_bridge.py,plugin_command.py,gateway_command.py,gateway_local_plugin_runtime_smoke.py,session_command.py,selftest.py}`.
- `tests/test_session_runtime_database.py` plus focused plugin/cache tests if clearer than expanding selftest alone.
- `Makefile`, this plan, and `docs/harness-optimization-wave-3-audit-2026-07-26.md`.

## Safety constraints

- Hash root `opencode.json`, root `gateway-core.config.json`, and `.opencode/gateway-core.config.json` when present before/after. Do not edit the repository sidecar or overwrite root user configuration. Run every config mutator against an isolated HOME/config, and require blocked enablement to leave config bytes unchanged.
- Treat plugin option objects as potentially secret. Never print, audit, hash into retained plaintext, or return them from status/doctor.
- Diagnose the live OpenCode database read-only. Run every repair mutation only against disposable fixture copies.
- Preserve the provider-boundary secret finalizer when configurable hooks are disabled.
- Do not add or enable any external plugin or MCP by default.
- Do not expand into callback-routing cleanup, runtime retention, retroactive secret scrubbing, or unsupported callback removal.

## Validation gates

1. Per-slice targeted TypeScript/Python tests, generated build, lint/ruff/compile, JSON validation, and `git diff --check`.
2. Full `npm --prefix plugin/gateway-core test`, `make validate`, `make selftest`, workflow scenarios, direct bootstrap, doctor, provider-boundary smoke, pre-commit, and committed-clone install test.
3. Live read-only SQL parity, query-plan, and performance evidence in tmux session `ai-oc-harness-wave3`.
4. Exact-model Python and Node project runs through the candidate built plugin, followed by bounded process/session cleanup and artifact credential scan.
5. Three separately validated commits maximum: contract alignment, indexed diagnostics, and loader-cache/E2E closure.
6. Complete 3–5 changed-evidence reviews, then PR/CI/overlap check/squash merge, Codememory closeout, branch/worktree cleanup, and main autostash-sync preserving user changes.

## Rollback

- Revert the loader-cache commit to restore an always-live smoke and remove the non-authoritative cache file.
- Revert the indexed-diagnostics commit to restore legacy SQL; no schema or data migration exists.
- Revert the contract-alignment commit to restore prior plugin adaptation; no user config migration is required.

## Deferred

- Remaining wildcard-hook migration and unsupported callback cleanup.
- Runtime-history retention or database maintenance.
- External context-pruning, browser CLI, cloud sandbox, broad agent-suite, or telemetry plugins.
- Credential-backed model calls in CI.
