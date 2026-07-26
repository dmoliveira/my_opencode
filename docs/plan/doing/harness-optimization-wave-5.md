# Harness Optimization Wave 5

Status: doing

Depth: large

Risk: high
Review budget: 3-5 changed-evidence review/fix passes

## Objective

Harden the remaining trust boundaries in the OpenCode gateway, make plugin and hook configuration exact, and replace shim-only model proof with configured-tuple Python and Node project delivery. Keep managed profiles external-free unless a measured, isolated pilot proves unique value.

## Baseline and decisions

- Branch `perf/harness-optimization-wave-5` starts at merged Wave 4 commit `fc7486a7903fa0257ceeeabb1f29c0328926a8e4`.
- Main's user-authored `opencode.json` and `gateway-core.config.json` edits are outside this worktree and must remain unchanged.
- Tmux sandbox: `ai-oc-harness-wave5`, window `wave5`, panes `baseline`, `runtime`, and `e2e`.
- Baseline gates pass after dependency installation: 726 gateway tests, 36 Python tests, and `make validate`.
- Reproduced defects are retained under `runtime/harness-wave-5/`:
  - `npm test || true` is classified as test evidence.
  - a fresh session reuses evidence after the tracked worktree becomes dirty.
  - a misspelled dangerous-command guard is accepted as an explicit hook plan.
  - audit output retains an Authorization canary, is created as `0644`, and follows a symlink.
  - `plugin disable notifier` also removes the Morph entry.
- A live `openai/gpt-5.4-mini` contract probe proved the real host shape: `input.callID`, `input.args.command`, and authoritative numeric `output.metadata.exit`. Successful evidence can therefore use stable call correlation and fail closed on exit status.
- External review found no managed plugin whose value exceeds overlap, authority, startup, egress, or supply-chain cost. Do not add notifier, Morph, worktree, PTY, cloud memory, Braintrust, type-inject, or testing-wrapper plugins.
- `@tarquinen/opencode-dcp@3.1.14` remains a separate default-off experiment only if long-session token pressure is first measured. It is not part of managed Wave 5 scope.

### External candidate gate

| Candidate | Immutable evidence | Authority / egress / overlap | Decision |
| --- | --- | --- | --- |
| `@tarquinen/opencode-dcp@3.1.14` | commit `85b6f5ceba144fee9e65eb28dc36cab1b960e418`, npm integrity present, AGPL-3.0-or-later | transforms system/messages, adds a tool and updater; overlaps native/gateway compaction; required 15% token-pressure gain is not measured | defer, gate closed |
| `opencode-supermemory@2.0.10` | git head `625f9b49e20ce083e41b3a05ea36fa3a49f2f697`, npm provenance | exports project knowledge/queries/summaries; overlaps local memory and Codememory | reject |
| `@braintrust/trace-opencode@0.1.0` | git head `2a1b918d05090695d53f82077065c008a7201f69`, npm provenance | exports prompts, tool arguments/results, user/host/workspace metadata; overlaps local opt-in audit | reject |
| `@nick-vi/opencode-type-inject@1.5.2` | commit `d30fb6601d91c9601515651d90e50758df5caa4a`; license declaration inconsistent | injects type context/tools and token/CPU cost; overlaps native LSP/typecheck gates | reject |
| `opencode-playwright-test-agents@0.1.0` | source-only; npm package absent | writes global config and mutable `@playwright/mcp@latest`; overlaps pinned Playwright MCP | reject |

Wave 4 already covers notifier, Morph, worktree, and PTY rejection. Wave 5 retains those decisions rather than repeating their implementation work.

## Non-goals

- No protobuf OTLP exporter or observability SDK.
- No cross-process durable telemetry spool or retries.
- No cryptographic validation attestation.
- No broad wildcard-hook or process-pressure rewrite.
- No credential-backed model calls in CI.
- No changes to protected root configs or unrelated active wave plans.

## Slice 1 — Validation evidence trust boundary (`task_2`)

Target commit: `fix: bind validation evidence to repository state`

Files:

- `plugin/gateway-core/src/hooks/shared/validation-command-matcher.ts`
- `plugin/gateway-core/src/hooks/validation-evidence-ledger/{index.ts,evidence.ts}`
- `plugin/gateway-core/src/index.ts`
- `scripts/completion_gates.py`
- focused gateway tests and completion-gate selftests
- generated `plugin/gateway-core/dist/**` artifacts corresponding to this slice

Implementation:

1. Accept one standalone recognized validation command only. Reject shell control operators, pipelines, redirects, backgrounding, command substitution, and `cd` wrappers.
2. Treat the ledger as a fixed boundary observer: invoke it after every other `tool.execute.before` hook and before mutable `tool.execute.after` hooks. Key the pending run only by non-empty `input.callID`, bind it to the session, classify final `input.args.command`, and require the same call/session plus finite numeric `output.metadata.exit === 0`. Missing or mismatched fields discard evidence; sequence, injected metadata, text, and boolean fallbacks are forbidden.
3. Keep LLM command classification as telemetry only; it cannot create ledger evidence.
4. Capture a bounded `git-state-v1` fingerprint before and after validation. Canonical components are:
   - lowercase `git rev-parse --verify HEAD` output;
   - SHA-256 of raw `git diff --cached --binary --no-ext-diff --no-textconv --no-renames HEAD -- . ':(exclude).opencode/runtime/validation-evidence.json'` bytes;
   - SHA-256 of raw `git diff --binary --no-ext-diff --no-textconv --no-renames -- . ':(exclude).opencode/runtime/validation-evidence.json'` bytes plus NUL-sorted `git ls-files --others --exclude-standard -z` entries;
   - each untracked entry frames strict round-trippable UTF-8 path bytes, `file` or `symlink` type, executable bit, size, and SHA-256 of file bytes or `readlink` bytes. Never follow symlinks; reject special files.
   - exclude exactly `.opencode/runtime/validation-evidence.json`; ignored files are absent by Git definition. Bound captures to 2,048 untracked entries, 4 MiB per entry, 16 MiB aggregate untracked content, and 16 MiB per Git diff. Frame every field as label, decimal byte length, NUL, then bytes before the final SHA-256.
   If capture fails, exceeds bounds, or changes during validation, record nothing.
5. Persist schema-v2 worktree evidence only. Keep session evidence in memory and bind all records to the exact fingerprint. Reset accumulated categories whenever the fingerprint differs. Old boolean-only state is untrusted.
6. Write evidence atomically with owner-only permissions and reject unsafe parents, symlink targets, non-regular targets, and multiply linked targets.
7. Make Python completion gates validate the same schema, file safety, key, and current fingerprint.

Acceptance:

- Swallowed failures and text-only output remain unvalidated.
- Standalone commands with exit zero validate even with empty stdout.
- Non-zero exit never validates.
- HEAD, staged, unstaged, untracked, deleted, renamed, or symlink-state changes invalidate evidence.
- Byte-identical clean or dirty state can be reused by a new session.
- Old, malformed, oversized, permissive, symlinked, or hard-linked evidence fails closed.
- Node-written evidence passes Python validation against shared golden vectors; path encoding, file type/mode, bounds, and stale-category reset are covered.

Checks:

- focused matcher/ledger/done-proof/PR-guard Node tests
- completion-gate Python/selftest coverage
- TypeScript build and lint
- live-shaped rewritten-command/`callID` contract tests plus the retained host probe
- fingerprint benchmark: 20 warm repetitions against `origin/main` and candidate in the same tmux pane; retain median/p95 JSON and require candidate p95 below 300 ms

## Slice 2 — Private audit and bounded OTLP (`task_3`)

Target commit: `fix: sanitize gateway audit and bound telemetry export`

Files:

- `plugin/gateway-core/src/audit/event-audit.ts`
- `plugin/gateway-core/src/hooks/shared/hook-dispatch.ts`
- focused event-audit and dispatch tests
- default/config documentation when protocol wording changes
- generated `plugin/gateway-core/dist/**` artifacts corresponding to this slice

Implementation:

1. Apply bounded recursive local sanitization before any persistence or export. Redact sensitive keys and Bearer/Basic/API-key/token/password patterns, truncate strings and collections, handle cycles, and replace sanitizer failures with a minimal safe envelope.
2. Generate `ts` after sanitization so callers cannot spoof it. Sanitize hook failures before local audit and stderr surfacing.
3. Write JSONL with one bounded `O_APPEND|O_NOFOLLOW` record, owner-only directories/files, target and parent checks, and safe rotation. Reject symlinks, non-regular files, and hard links.
4. Export only an allowlist of low-cardinality scalar metadata. Exclude commands, prompts, paths, titles/messages, raw errors, headers, bodies, outputs, and nested objects; hash session identifiers.
5. Support `http/json` honestly and make it the default. Explicit `http/protobuf` disables export rather than sending mismatched JSON.
6. Resolve and snapshot an immutable sink context at enqueue time: endpoint, `http/json` protocol, service, and parsed headers. Queue the already sanitized/allowlisted event with that sink; never re-read another directory's configuration while draining.
7. Use batch size one for Wave 5. Bound export to one request in flight and a global queue of 256, bounded bodies, timeout clamped to 100-2,000 ms, unref'd timers, no retry, and drop-oldest counters. Consume/cancel response bodies and check status without blocking process exit. Expose deterministic test-only flush/reset/stats that retain no header values.

Acceptance:

- Authorization/error/command/message canaries never appear in local or OTLP payloads.
- Audit and rotated files are `0600`; unsafe targets are unchanged.
- A hanging or failing collector cannot create unbounded requests or keep the process alive.
- JSON exports use the correct content type; protobuf configuration sends nothing.
- Audit-disabled median per call is no more than 10% or 0.005 ms above `origin/main`, whichever is larger. Enabled safe-metadata median and p95 over 10,000 events, repeated 25 times in isolated processes, stay below a 25% regression unless a documented security cost is approved before merge.

Checks:

- focused audit/dispatch tests, including canaries, permissions, symlinks, hard links, rotation, cycles, queue overflow, two-sink isolation, flush/reset, 500 responses, and hanging fetch
- a child-process hanging-collector probe must exit inside the clamped timeout; an unresolved in-process mock alone is insufficient
- Node build/lint and gateway security tests

## Slice 3 — Exact configuration identities (`task_4`)

Target commit: `fix: enforce exact hook and plugin configuration`

Files:

- `plugin/gateway-core/src/hooks/registry.ts`
- `plugin/gateway-core/src/index.ts`
- `plugin/gateway-core/src/config/load.ts`
- `plugin/gateway-core/src/llm-decision-bindings.ts`
- registry/contract tests
- `scripts/plugin_command.py`
- `scripts/install_wizard.py`
- `tests/test_plugin_config_entries.py` and focused selftests
- generated `plugin/gateway-core/dist/**` artifacts corresponding to this slice

Implementation:

1. Validate effective raw config before lossy coercion. Use the canonical default hook order as the known-ID manifest; reject unknown or duplicate `hooks.order`/`hooks.disabled` values. Preserve all four valid LLM modes, including explicit `disabled`, and validate hook-mode keys against the LLM binding manifest rather than every hook.
2. Validate dependency endpoints/cycles and use stable topological expansion. Add validation-ledger dependencies for done-proof and PR evidence consumers. Empty order means all hooks in the existing priority baseline with only the minimum stable dependency moves; provider-boundary finalization remains independent.
3. Make named retired-plugin disable remove only exact string/tuple entries for that alias, preserving all other entries, options, malformed values, and order. Absent named disable is a byte-stable success. `disable all` and `profile lean` retain all-retired removal semantics.
4. Preflight the installer state destination before external mutations. Maintain one result per logical profile; persist only successful actions, require all substeps for a multi-command post-session profile, and preserve prior values for skipped or failed actions, including fresh-state failure. Write state atomically as `0600` and reject symlink, hard-link, non-regular, or unsafe-parent targets.

Acceptance:

- Typos fail explicitly instead of silently disabling guards.
- Explicit later dependencies move before consumers exactly once; disabled dependencies still block consumers.
- `disable notifier` preserves Morph/worktree/unknown entries; all/profile paths remove every retired entry.
- Failed wizard actions do not claim requested profiles as applied.
- A host-loader typo probe proves invalid hook config fails startup/tool execution closed instead of silently skipping gateway protection.

Checks:

- registry/contract Node tests
- plugin-entry and installer Python tests
- `python3 -m py_compile` and critical Ruff rules on touched Python

## Slice 4 — Configured-tuple exact-model proof and delivery (`task_5`)

Target commit: `test: close harness optimization wave 5`

Files:

- `scripts/harness_wave2_task4_smoke.py`
- new focused Python harness tests
- `docs/harness-optimization-wave-5-audit-2026-07-27.md`
- this plan moved to `docs/plan/done/`
- generated candidate `plugin/gateway-core/dist/**` verified clean and committed before live use

Implementation:

1. Build candidate gateway dist immediately before live validation, require no tracked changes afterward, and bind retained reports to committed HEAD plus source/dist hashes.
2. Configure exactly one gateway tuple entry with options selecting `noninteractive-shell-guard`; create no project shim and retain built-in default auth support required by the OAuth store. Do not set `OPENCODE_DISABLE_DEFAULT_PLUGINS`.
3. Require one gateway bootstrap, hooks enabled, only `openai/gpt-5.4-mini`, zero project plugin shims, and at least one `runtime_session_env_prefixed` event for each project fixture.
4. Preserve red-to-green Python/Node tests, implementation-only edits, unchanged test hashes, process deadlines/cleanup, sanitized retained artifacts, and credential scans.
5. Record external candidate decisions, before/after defects, performance evidence, validation, and rollback guidance in the audit.

Acceptance:

- Preflight, Python project, and Node project pass with the configured tuple and exact model.
- Only `stats.py` and `slugify.mjs` change in their respective fixtures.
- No project shim, retired plugin, unsupported external plugin, credential material, or temporary path is retained.
- Reports prove one tuple, OAuth-store-only auth, no forwarded API key, built-in auth retained, and no raw tuple spec/options or temporary path retained.
- Latest verifier and critical reviewer report no blocker.

## Final validation matrix

Run from current HEAD in tmux and retain logs under `runtime/harness-wave-5/`:

1. `git diff --check origin/main...HEAD`
2. `CI=true npm --prefix plugin/gateway-core test`
3. `npm --prefix plugin/gateway-core run lint`
4. `python3 -m unittest discover -s tests -p 'test_*.py'`
5. `python3 -m py_compile <touched Python files>`
6. critical Ruff rules for touched Python, plus parent/current full-Ruff comparison
7. `make validate`
8. `make selftest`
9. `node scripts/gateway_workflow_scenario_report.mjs`
10. `make gateway-secret-redaction-smoke`
11. package dry-run/extracted parity and direct+tuple runtime contract probes
12. `pre-commit run --all-files`
13. committed-clone `make install-test`
14. exact-model configured-tuple Python and Node E2E with `openai/gpt-5.4-mini`
15. require a clean tracked tree after every TypeScript build, after pre-commit, and before exact-model execution

## Review and delivery

1. Before Slice 1, freshly fetch/check GitHub overlaps; run `oc current`, `oc next`, `oc queue`, and resume the Wave 5 task/session. The epic owns `task_2`-`task_5`; task dependencies are durable, `task_5` depends transitively on tasks 2-4, and only the current slice is active.
2. Review the plan before tracked implementation.
3. Validate and verify each changed slice before its commit; include matching generated dist artifacts in that commit.
4. Run a critical final reviewer against the full diff and retained evidence.
5. Fetch and compare `origin/main`, check overlaps, push, open a PR, wait for CI, and merge only when clean.
6. Before deleting the worktree, credential-scan and copy sanitized `runtime/harness-wave-5/` evidence to durable main-local storage, verify file counts and hashes, export Codememory, confirm the Wave 5 export has all tasks/epic/session closed, and run the worktree-scoped `oc plan doctor`.
7. Remove branch/worktree/tmux, sync protected `main` with autostash, preserve user config hashes, and restore balanced model routing.

## Rollback

- Each slice is independently revertible in reverse commit order.
- Evidence schema v2 intentionally invalidates v1; rollback restores the prior file reader but must not treat mixed schemas as trusted.
- OTLP remains opt-in. Disabling export or reverting the audit slice does not affect core hook dispatch.
- Configuration strictness can be reverted without restoring retired plugins.
- E2E harness changes do not alter runtime defaults.
