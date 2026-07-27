---
status: done
priority: high
updated: 2026-07-27
---

# OpenCode Hardening Wave 7

Date: 2026-07-27
Runtime session: `ses_067d2e945ffe5mebe04ifDBZTc`
Branch: `perf/sqlite-hardening-wave-7`
Codememory: `epic_2`, discovery `task_33`, implementation `task_34` through `task_38`

## Objective

Ship the smallest evidence-backed session, SQLite, and gateway safety improvements that materially improve daily OpenCode use. Keep runtime history read-only, make explicitly redacted session output safe to share, stop new private persistence in the mistake ledger, never surface private fields from legacy ledger rows, prevent unattended OpenCode upgrades, and prove the result with tmux and realistic model-backed validation.

## Classification And Review Budget

- Depth: `large`.
- Risk: `high` because the slice changes privacy contracts, filesystem writes, runtime database diagnosis, and managed OpenCode configuration.
- Review budget: three changed-evidence review/fix passes, stopping only after required checks are green and the latest critical review has no blocker.
- Writer model: one implementation writer; read-only discovery, verification, and review may fan out to at most two subagents.

## Evidence Baseline

- `origin/main` and the worktree both started at `4adb21a`; no open PR overlaps existed at alignment.
- `make validate`: `93/93` Python tests passed.
- `npm --prefix plugin/gateway-core test`: `752/752` tests passed on Node `v26.5.0` after `npm ci`.
- Baseline logs are owner-local under `runtime/harness-wave-7/baseline/`.
- Existing code already satisfies stale backlog tasks `task_10` and `task_11`: atomic temp-file replacement with file and directory `fsync`, plus a cross-process write lock and concurrency regression. Those tasks were closed instead of reimplemented.

## Durable Sequence

- `task_33` blocks `task_34`, `task_35`, `task_36`, and `task_37` through Codememory links `link_44` through `link_47`.
- `task_38` depends on validated completion of `task_34` through `task_37` through `link_48` through `link_51`.
- `task_35` is the implementation/closure evidence for existing `task_15`; `task_15` will be closed only after `task_35` passes its acceptance gates.
- Each implementation task is validated, reviewed, recorded in Codememory, and committed before the next begins. Push and PR creation wait until every slice is green.

## Decisions

### 1. Secure mistake ledger (`task_34`)

Threat model and path contract:

- The canonicalized constructor `options.directory` is the only storage root. Event payload `directory` is never path authority for this hook.
- Wave 7 freezes storage to `.opencode/mistake-ledger.jsonl`. A different configured path fails closed; arbitrary custom paths and the separate `MY_OPENCODE_MISTAKE_LEDGER_PATH` reader override are removed rather than interpreted differently by TypeScript and Python.
- Existing workspace ancestors are never chmodded. A new `.opencode` directory may be created privately; an existing one must be a real, current-user-owned directory that is not group/world writable.
- On POSIX, the final target is opened no-follow, checked through the file descriptor as a regular single-link current-user-owned file, and set to `0600` before append. Final or parent symlinks, hardlinks, non-regular files, ownership mismatches, and unsafe directory modes fail closed with stable error text.
- Platforms without dependable UID and no-follow support fail closed. Protection against a concurrent malicious same-UID process is explicitly outside this portable contract.

Privacy and status contract:

- New rows use the exact allowlist `{ts, category, sourceHook}`. Tool names, output-derived summaries, and runtime session identifiers are not persisted.
- Legacy rows are not rewritten or deleted, but gateway status never returns their private fields.
- Status reads at most a `256 KiB` tail and at most `500` complete records. It reports `window_entry_count`, `window_category_counts`, `invalid_lines`, `truncated`, and a last entry containing only `{ts, category}`. Window counts are never presented as lifetime totals.
- The no-path/no-session/content guarantee applies to the `mistake_ledger` status subtree; broader gateway status redaction remains deferred.
- Victim-unchanged tests cover an ordinary workspace file, payload-directory escape, final and parent symlinks, hardlinks, FIFO/non-regular targets, unsafe modes, an ownership mismatch, and a large legacy canary ledger.

### 2. Share-safe session redaction (`task_35`, completing `task_15`)

Redacted output uses exact schemas and fixed error codes:

- Search success: `result`, `command`, `redacted`, `count`, and records containing only `started_at`, `last_event_at`, and `event_count`.
- Handoff success: `result`, `command`, `redacted`, `started_at`, `last_event_at`, and `event_count`.
- Failure: `result`, `command`, `redacted`, and a fixed `error_code`; no raw exception text.
- Human output is rendered from the same projection. PASS exits `0`; FAIL exits `1`.
- Unredacted schemas remain unchanged. Documentation states that only redacted search and handoff output is share-safe.
- JSON and human tests cover flag and environment-default activation plus canaries in query, target ID, CWD, reason, branch, plan, index/digest paths, malformed digest/index exceptions, and generated commands.

### 3. Timestamp and runtime SQLite correctness (`task_36`)

Checkpoint `36a`:

- Interpret legacy timezone-naive ISO timestamps as UTC before comparisons in `session_metadata_index.py` and `shared_memory_runtime.py`.
- Preserve accepted aware timestamps and existing storage formats; no migration or version bump.

Checkpoint `36b` state machine:

1. Open the upstream database with `mode=ro`.
2. Set `PRAGMA query_only=ON`, verify the readback is `1`, and skip scanning if unavailable.
3. Install a monotonic SQLite progress budget; set busy timeout no greater than that budget. This bounds SQLite execution, not arbitrary OS-level file-open latency.
4. Execute `BEGIN`, establish the snapshot with the first metadata read, and run metadata plus every stale-session query in that transaction.
5. Clear the progress handler, roll back the read transaction, and close on every exit path.

Stable remediation/error codes are `runtime_db_open_failed`, `runtime_query_only_unavailable`, `runtime_schema_incompatible`, `runtime_json1_unavailable`, `runtime_scan_timeout`, and `runtime_query_failed`. Missing schema or JSON1 skips dependent queries and returns no partial findings.

Validation uses separate invariants:

- Quiescent fixture: main database bytes, schema, and row counts remain unchanged; diagnosis creates no database and issues no mutating SQL.
- Concurrent WAL fixture: deterministic thread barriers establish the reader snapshot before the writer commits; all metadata and findings must reflect the same pre-commit snapshot. WAL/SHM byte stability is not asserted while a legitimate writer is active.

No runtime schema/index creation, checkpoint, repair, or mutation is allowed in diagnosis.

### 4. Runtime/tool policy (`task_37`)

- Change managed OpenCode `autoupdate` from automatic installation to the documented `notify` mode.
- Keep every hosted MCP disabled and retain the exact canonical pinned Playwright command.
- Keep the plugin inventory unchanged and adopt no external plugin: candidates lacked immutable provenance, bounded authority, non-overlap, or measured value.
- `scripts/mcp_command.py` is validation context, not an edit target in this slice.
- Add a static managed-config regression for all four assertions above.
- Run an isolated runtime probe: require `opencode --version` to equal `1.18.0`, then run `OPENCODE_CONFIG=<candidate> opencode debug config --pure --print-logs --log-level INFO`. Retain only sanitized version/exit evidence.

### 5. Validation and delivery (`task_38`)

- Retain sanitized tmux evidence for privacy canaries, filesystem attacks, WAL snapshot consistency, deadlines, full validation, and model-backed E2E.
- Deliver only through a reviewed PR and clean the branch/worktree after merge.

## Explicitly Deferred

- Shared-memory colon-key/ranking changes: local inspection found no colon-concatenated ranking identity defect.
- Broad FTS redesign: add a follow-up only if a focused literal-query fixture reproduces a user-visible failure.
- Mistake-ledger history deletion, content migration, retention, rotation, and arbitrary custom storage paths.
- Global gateway audit identity changes and repository-wide support-export redaction.
- Runtime schema/index migrations, WAL checkpoints, and stale-session repair behavior changes.
- Retirement of on-demand hosted MCP profiles; they remain disabled, and removal requires separate compatibility evidence.
- Windows ACL-backed ledger storage; Wave 7 fails closed where the POSIX ownership/no-follow contract cannot be enforced.

## Slice Gates

| Slice | Task | Primary files | Required targeted checks |
| --- | --- | --- | --- |
| Discovery and reviewed plan | `task_33` | this plan, Codememory | critical plan review; `oc plan doctor`; `git diff --check` |
| Ledger privacy and storage | `task_34` | mistake-ledger hook, gateway status, focused tests | victim-unchanged filesystem matrix; bounded legacy canary status; gateway lint/build/tests |
| Session redaction | `task_35` | `scripts/session_command.py`, focused tests/docs | JSON and human canary matrix; unchanged unredacted fixtures |
| Timestamp normalization | `task_36a` | session metadata/shared memory runtime and tests | naive/aware timestamp regressions; Python compile/targeted tests |
| SQLite diagnosis | `task_36b` | `scripts/session_command.py`, runtime DB tests | query-only readback; deterministic WAL snapshot; timeout/error classification; quiescent DB invariants |
| Managed policy | `task_37` | `opencode.json`, config test, audit doc | static policy test; JSON parse; exact runtime version/config probe; MCP doctor |
| Closure | `task_38` | full diff and ignored evidence | full commands below plus realistic model E2E and final remote overlap check |

## Full Closure Commands

```bash
git diff --check
python3 -m py_compile scripts/session_command.py scripts/session_metadata_index.py scripts/shared_memory_runtime.py scripts/gateway_command.py
make validate
make selftest
make install-test
npm --prefix plugin/gateway-core run lint
npm --prefix plugin/gateway-core run build
npm --prefix plugin/gateway-core test
pre-commit run --all-files
```

Also run the repository secret/security smoke, exact package parity checks, and the projects-only realistic E2E with `openai/gpt-5.4-mini`. Browser/MCP E2E is required only if that runtime surface changes. Immediately before merge, fetch `origin`, compare the branch with latest `origin/main`, and inspect open PRs for overlap.

## Acceptance Gates

- No privacy canary occurs in redacted session output or the `mistake_ledger` status subtree.
- Unsafe ledger attempts fail closed and leave every victim unchanged; supported safe files are regular, single-link, current-user-owned, and `0600`.
- Runtime diagnosis returns one coherent pre-commit snapshot under the concurrent WAL fixture and explicit codes for capability, timeout, open, and query failures.
- Quiescent diagnosis leaves main DB bytes, schema, and row counts unchanged and executes no mutating SQL.
- Managed configuration resolves under exact OpenCode `1.18.0`; hosted MCPs remain disabled, Playwright remains exact-pinned, and plugin inventory is unchanged.
- Every slice has a focused validated commit, full checks pass on the final diff, a verifier passes it, and the latest critical reviewer reports no blocker.

## Delivery Sequence

1. Fix plan-review blockers, pass a second critical plan review, close `task_33`, and activate `task_34`.
2. Implement, validate, review, record, and commit `task_34`.
3. Repeat independently for `task_35`, `task_36a`, `task_36b`, and `task_37`.
4. Activate `task_38`, run the full closure matrix and realistic model-backed E2E, then complete the required high-risk review passes.
5. Export owner-only Codememory evidence, push, open the PR, address review/check findings, recheck remote overlap, merge, close tasks/epic, and remove the worktree/branch/tmux sandbox.
