# Harness optimization audit — wave 3

## Scope

This high-risk wave aligns the gateway with official OpenCode plugin and chat contracts, preserves tuple-form plugin options, and reduces repeated diagnostic latency. Review budget: 3–5 changed-evidence review-and-fix passes.

## Baseline evidence

| Measurement | Baseline |
| --- | ---: |
| Configurable hooks built when second-argument options requested `hooks.enabled=false` | 85 |
| Tuple-form gateway entry detected | no |
| Unrelated tuple preserved after gateway disable | no |
| Official `output.parts` keyword mode detected | no |
| Official `output.parts` think hint added | no |
| Official `output.parts` session guidance added | no |
| `chat.message` callback cost | 23.245µs/call |
| `experimental.text.complete` callback cost | 20.256µs/call |
| Warm gateway doctor runs | 32.480s / 28.119s / 29.280s |
| Runtime session-health component | 22.639s |
| Direct loader smoke component | 9.289s |

The live read-only runtime database held 9,195 sessions, 144,205 messages, and 696,182 parts. Its relevant indexes covered `session(parent_id)`, `message(session_id,time_created,id)`, and `part(message_id,id)`. A read-only candidate prototype returned 9,193 stale-session snapshots with warm runs of 120.87ms, 142.54ms, 121.08ms, 118.16ms, and 117.57ms after one cold 2,358.65ms run. `EXPLAIN QUERY PLAN` used the composite message index and part-message index. These ignored artifacts are under `runtime/harness-wave-3/`.

## Selection decisions

- Selected: official plugin options and tuple-safe mutation because the current behavior loses configuration and defeats explicit startup controls.
- Selected: canonical chat adaptation because official user text is invisible to intended hooks.
- Selected: bounded indexed stale-session queries and successful loader-smoke caching because they target measured 22.6s and 9.3s doctor components.
- Rejected: further callback routing in this wave because measured dispatch cost is only about 20–23µs per call.
- Rejected: new/default-on external plugins and MCPs because none beat local fixes without increasing trusted startup or egress surface. The existing pinned, isolated, disabled Playwright MCP remains sufficient; Playwright CLI requires a distinct future workflow benchmark.

## Contract and config results

- Official second-argument options now merge after legacy runtime config. With `hooks.enabled=false`, the fixed direct fixture recorded `hooks_enabled=false`, zero configured hooks, zero selected hooks, and zero loop attempts instead of the 85-hook baseline. Configurable hook factories are skipped, while the provider-boundary finalizer remains active.
- The no-shim OpenCode host probe loaded the candidate dist from a tuple entry, recorded exactly one safe bootstrap with hooks disabled, created zero project shims, retained no option sentinel, and cleaned its isolated config/audit/log tree.
- Canonical `chat.message` text is snapshotted from ordered `output.parts` before mutation. Tests prove canonical precedence, no-text suppression of legacy fields, and stable array, part, and `output.message` identity.
- Gateway and general plugin mutators recognize string and `[string, options]` entries, preserve unknown/malformed entries and selected option objects, deduplicate matching gateway entries to the first representation, and expose only normalized specs in diagnostics.
- A blocked gateway enable now saves nothing and performs no compatibility-path mutation. Focused tests prove byte-identical config rollback and option non-disclosure.
- The higher-precedence malformed-sidecar policy remains intentionally fail-closed and is unchanged; official options still apply after that established layer policy.

## Runtime diagnostic results

- Production diagnosis remains read-only and performs no schema/index migration. It checks index column prefixes, uses six bounded correlated queries when compatible, and emits an explicit warned legacy fallback otherwise. Every finding query returns at most 20 rows; the exact generic count uses a separate `COUNT(*)` query.
- A frozen scan clock makes candidate/reference parity deterministic. Equal timestamps intentionally select descending ID; focused fixtures cover this correction, all issue types, fresh-child exclusion, missing/wrong-order fallback, arbitrary index names/supersets, and metadata-failure connection cleanup.
- On the live database, one cold bounded run took 494.21ms and five warm runs took 63.61ms, 53.86ms, 52.79ms, 49.78ms, and 50.35ms. The 52.79ms warm median is 99.8% below the original 22.639s component baseline and well below the 1,000ms budget.
- An owner-only `0600` compact snapshot held 9,208 sessions, 9,194 latest-message rows, and 37,719 latest-message parts. It had zero equal-latest-timestamp sessions; legacy and bounded queries returned equal counts and identical semantic SHA-256 `56b231c75a4f5f7ca5248cb2aad6e1a10cd6ac1f2a756efd6e2af88d7af02f9f`. The compact database was deleted after the comparison.
- `EXPLAIN QUERY PLAN` for all six bounded queries used the session-parent, composite message, and part-message indexes with no full message/part scan or group materialization.
- Before loader caching, full doctor runs dropped from the 29.280s baseline median to 8.779s median across three runs; direct-loader variability remained the next selected bottleneck.

## Loader cache and doctor results

- Successful direct-loader results are fingerprinted across gateway command/cache schema, smoke script, plugin dist/package metadata, and resolved OpenCode binary/version/stat/platform. Only an allowlisted PASS summary is eligible; any corrupt, insecure, expired, future, mismatched, skipped, or failed record reruns live, and failures invalidate prior cached success.
- The dedicated cache directory is `0700`, the atomically replaced file is `0600`, symlink paths are rejected, and retained JSON contains only schema, fingerprint, check time, result/reason/exit, and seven per-mode booleans/status fields. It contains no stdout, stderr, environment, plugin options, credentials, or temporary paths.
- `/gateway doctor --fresh --json` bypassed cache reads and ran the real smoke in 8.201s. Five unchanged warm runs took 2.283s, 1.853s, 1.815s, 1.832s, and 1.786s; the 1.832s median is 93.74% below the original 29.280s doctor baseline and below the 5s exit target.

## Browser and model-backed evidence

- No browser MCP probe was repeated; Wave 2 already proved the pinned isolated integration and this wave added no browser dependency.
- The reused projects-only harness preflighted and used exact `openai/gpt-5.4-mini` with the isolated OAuth symlink. Audit evidence recorded exactly one gateway bootstrap and only that model for preflight, Python, and Node runs.
- Python started red, changed only `stats.py`, kept `test_stats.py` hash-identical, and finished green under `python3 -m unittest -v`. Node started red, changed only `slugify.mjs`, kept `slugify.test.mjs` hash-identical, and finished green under `node --test slugify.test.mjs`.
- Candidate source/dist SHA-256 values were `608e1ca986bdb01b72ef10a5e1716ecd060f398aea0b630b816243fc912cd099` and `85eb207664c2d06b5a584f13cadeacb59717e8a0e3670fa3622d8bece08ba970`. Every sandbox used one project shim and no configured plugin entry; retained artifacts passed the credential scan.

## Validation and review

- Contract slice: gateway lint passed; all 720 gateway tests passed on verification; focused Python tests passed; `make validate` and `make selftest` passed; built-plugin and actual host tuple probes passed in tmux.
- Review pass 1 found one valid hidden-mutation blocker, which was fixed and regression-tested. A claimed sidecar issue was confirmed as established fail-closed policy. Changed-evidence re-review returned READY with no blocker findings.
- Indexed-diagnostic review found unbounded Python materialization and a metadata-failure connection leak. The implementation was replaced with bounded queries and explicit cleanup; changed-evidence reviewer and verifier passes reported no blocker, and latest `make selftest` passed.
- Cache/security review returned READY with no blocker. Five focused cache tests, all 26 stdlib tests, critical Ruff rules, `make validate`, and `make selftest` passed before exact-model closure.
