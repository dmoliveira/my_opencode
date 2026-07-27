# OpenCode hardening Wave 7 audit

Date: 2026-07-27

## Outcome

Wave 7 closes seven safety and reliability gaps without enabling a new external
runtime dependency:

- the mistake ledger now writes a fixed, owner-only categorical schema and
  rejects unsafe paths and filesystem objects;
- explicitly redacted session search and handoff output now use narrow,
  share-safe schemas;
- legacy timezone-naive session timestamps are interpreted as UTC before
  ordering or scoring;
- runtime SQLite diagnosis is query-only, snapshot-coherent, deadline-bounded,
  and explicit about unsupported capabilities;
- managed OpenCode updates now notify instead of installing automatically;
- managed hosted MCPs stay disabled, Playwright stays exact-pinned, and the
  managed plugin inventory stays unchanged;
- immutable provider-boundary blocks now record only structural diagnostics,
  without weakening fail-closed secret handling or logging matched content.

No new MCP, plugin, telemetry exporter, hosted service, or unattended updater is
enabled by default.

## Delivered slices

### Private mistake ledger

The gateway writes only to `.opencode/mistake-ledger.jsonl` under the canonical
workspace directory. On supported POSIX systems it rejects symlinks, hardlinks,
non-regular targets, ownership mismatches, unsafe parent modes, and unsupported
no-follow or UID checks. New rows contain only `ts`, `category`, and
`sourceHook`; the final file is `0600`.

Gateway status reads a bounded `256 KiB` tail and at most 500 complete records.
It exposes windowed categorical counts and a last entry containing only `ts`
and `category`. Private fields from legacy rows remain on disk but never appear
in the status projection.

### Share-safe session output

Redacted search and handoff output now use exact JSON and human projections.
They omit query text, target IDs, CWD, branch, reason, plan text, generated
commands, sidecar paths, and raw exception messages. Failures return fixed error
codes. Unredacted output keeps its existing schema.

Only explicitly redacted search and handoff output is documented as share-safe.

### Timestamp and SQLite correctness

Legacy timezone-naive ISO timestamps are treated as UTC in session metadata and
shared-memory ordering. Existing aware timestamps and storage formats are
unchanged.

Runtime diagnosis opens the upstream OpenCode database with `mode=ro`, enables
and verifies `PRAGMA query_only=ON`, installs a monotonic progress budget, and
runs metadata plus stale-session queries inside one read transaction. Every exit
path clears the handler, rolls back, and closes. Missing schema, JSON1,
query-only support, timeout, open, and query failures return stable remediation
codes instead of partial findings.

The concurrent WAL fixture establishes the reader snapshot before a writer
commits and proves all findings come from that one pre-commit snapshot. The
quiescent fixture proves main database bytes, schema, and row counts remain
unchanged and that diagnosis issues no mutating SQL.

### Managed runtime policy

Managed `opencode.json` now uses `"autoupdate": "notify"`. OpenCode `1.18.0`
accepted the isolated candidate configuration. Hosted MCPs remain disabled, the
canonical Playwright command remains exact-pinned, and the plugin inventory is
unchanged.

Reviewed notifier, context-pruning, PTY, and editing candidates did not clear
the provenance, authority, overlap, and measured-value gate. No external plugin
was adopted.

### Provider-boundary diagnostics

A first realistic Python model fixture failed closed with `immutable_match`
after tool results. The retained report found no credential material and no
fixture changes, but the old error did not identify a safe structural location
or pattern index.

The redactor now adds only `match_target`, numeric `pattern_index`, and a closed
`location_code` to immutable-match audit rows. It never records the matched
value, regex source, arbitrary key or path, provider payload, preview, or hash.
Traversal, mutation, configured-pattern authority, and block decisions are
unchanged. The failure did not reproduce on the committed diagnostic candidate;
the final Python and Node model fixtures both passed.

## Validation evidence

Executable validation passed on committed candidate `037c30a` in tmux session
`ai-oc-sqlite-wave7`:

- Python `3.14.6`: `py_compile`, `make validate`, and `make selftest`; unittest
  discovery passed `128/128`.
- Node `26.5.0` and Node `22.23.1`: gateway lint, build, and full tests passed
  `761/761` on each runtime.
- Workflow scenarios passed `20/20` at the required 100% threshold on both Node
  runtimes.
- Provider-boundary secret smoke passed with canaries absent, the redaction token
  present, one bootstrap, safe audit output, and no host credentials forwarded.
- Realistic model E2E used exact `openai/gpt-5.4-mini`; preflight, Python, and
  Node passed, only `stats.py` and `slugify.mjs` changed in their disposable
  fixtures, test hashes stayed unchanged, and sandbox cleanup was confirmed.
- Gateway direct and tuple contract probes passed and cleaned their artifacts.
- An initial repo-root `npm --prefix plugin/gateway-core pack` invocation failed
  with `ENOENT`. The corrected
  `npm pack ./plugin/gateway-core --dry-run --json` command passed and reported
  `@my_opencode/gateway-core@0.1.1` with 263 files. Corrected evidence is
  retained at `runtime/harness-wave-7/final/package-dry-run-v2.json`.
- `make install-test`, `pre-commit run --all-files`, and `git diff --check`
  passed. The tracked worktree was restored clean after generated validation
  output.
- The sanitized live SQLite scan verified query-only mode, a complete coherent
  `indexed_snapshot`, and a 1,104 ms duration under the 5,000 ms budget.

Owner-local machine-readable evidence is retained under
`runtime/harness-wave-7/`, including `baseline/`, `final/`, and `model-e2e/`.
The final model report is
`runtime/harness-wave-7/model-e2e/report.json`.

## Review record

The high-risk review budget was met with critical plan review, independent
slice verification, security and architecture advice, and critical final-diff
reviews. Review findings tightened filesystem authority, legacy-ledger output,
SQLite snapshot semantics, timeout classification, and provider diagnostics.
The latest diagnostics review reported no blocker findings, and all checks were
green on unchanged committed evidence.

## Residual risks

- Credential-backed model proof depends on the trusted host OAuth store and
  provider availability, so CI does not run it. The earlier intermittent
  immutable match remains intentionally fail-closed; a recurrence now yields
  safe structural evidence instead of matched content.
- OpenCode `1.18.0` still fails to load the local gateway through optional
  `path` and packed `file:` forms. Required direct and tuple contracts pass;
  managed configuration remains on its existing supported entry.
- Legacy mistake-ledger rows are not migrated or deleted. The bounded status
  projection hides their private fields, but local retention remains an
  operator concern.
- The ledger's ownership and no-follow contract is POSIX-specific. Unsupported
  platforms fail closed until an ACL-backed implementation is added.
- SQLite's progress handler bounds database execution, not arbitrary OS-level
  file-open latency. Diagnosis remains read-only and reports open failures
  explicitly.

## Rollback

Revert `037c30a`, `9688d47`, `1f63d4e`, `f099597`, `8f49670`, and `e62d3d5` in
reverse delivery order, then rebuild `plugin/gateway-core/dist/**`. The planning
commit `3235255` and this closure document can be reverted independently.
