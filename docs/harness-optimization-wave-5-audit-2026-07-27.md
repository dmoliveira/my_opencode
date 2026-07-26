# Harness optimization audit — wave 5

Status: complete
Date: 2026-07-27
Branch: `perf/harness-optimization-wave-5`
Validated code head: `b39cf2a9b266113f77cb4d9f28d2a58738f44a94`
Baseline: `fc7486a7903fa0257ceeeabb1f29c0328926a8e4`

## Objective

Wave 5 hardened the remaining gateway trust boundaries, made hook and plugin
configuration exact, and replaced shim-only model proof with configured-tuple
Python and Node delivery. Managed profiles remain external-free.

## Baseline defects and outcomes

| Baseline defect | Wave 5 outcome |
| --- | --- |
| A swallowed failure such as `npm test || true` could be classified as validation evidence. | Evidence now requires one recognized standalone command, stable call/session identity, numeric exit `0`, and unchanged repository state. |
| Validation evidence could survive a tracked-state change. | Schema-v2 evidence is bound to HEAD, staged, unstaged, untracked, deletion, rename, mode, and symlink state. |
| Unknown hook identities could be accepted and silently disable expected protection. | Raw hook order, disabled lists, dependencies, and LLM hook-mode keys are validated against exact manifests. |
| Audit output could retain an authorization canary in a permissive file and follow an unsafe target. | Local and exported events are bounded and sanitized; owner, mode, symlink, hard-link, and parent checks fail closed. |
| `plugin disable notifier` could remove another tuple entry. | Named disable removes only the exact retired alias and leaves unrelated, unknown, malformed, and ordered entries intact. |
| Exact-model project proof depended on a project-local shim. | Preflight plus Python and Node fixtures load one configured gateway tuple and create no project plugin shim. |

## Shipped slices

1. `1d81e6bdbf83c26e0a3a52fed78f81bb0a0470e3` — repository-bound validation evidence.
   - Correlates `tool.execute.before` and `tool.execute.after` by non-empty call ID and session.
   - Accepts only authoritative finite numeric exit `0`.
   - Persists private schema-v2 evidence against a bounded `git-state-v1` fingerprint.
   - Keeps Node and Python fingerprint validation aligned through shared vectors.
2. `90b2283c03e0864987e5570ef4bd02c52159374c` — private audit and bounded OTLP export.
   - Sanitizes recursively before local persistence or export.
   - Uses private append-only JSONL with safe rotation and unsafe-target rejection.
   - Exports only allowlisted scalar metadata over `http/json`.
   - Bounds the global queue to 256, one request in flight, clamped unref'd timeouts, and no retries.
3. `dc7debe645f01362d09d32d52ea1d2436c2bc0b3` — exact hook and plugin configuration.
   - Preserves all four valid LLM modes, including explicit `disabled`.
   - Expands stable dependencies and blocks consumers when a dependency is disabled.
   - Makes retired-plugin removal exact and absent-target disable byte-stable.
   - Preflights installer state and persists only successful profile actions with atomic private writes.
4. `b39cf2a9b266113f77cb4d9f28d2a58738f44a94` — configured-tuple proof and closeout.
   - Builds and verifies a clean committed gateway candidate before model use.
   - Uses one tuple selecting only `noninteractive-shell-guard` while retaining built-in OAuth support.
   - Adds focused Python and Node fixture, auth, deadline, cleanup, and artifact-safety coverage.
   - Requires owner-only audit parents in exact-model, contract, and secret-redaction sandboxes.

## External candidate decisions

| Candidate | Decision | Reason |
| --- | --- | --- |
| `@tarquinen/opencode-dcp@3.1.14` | Deferred | Default-off only if measured long-session token pressure later proves at least 15% unique value. |
| `opencode-supermemory@2.0.10` | Rejected | Exports project knowledge and overlaps local memory and Codememory. |
| `@braintrust/trace-opencode@0.1.0` | Rejected | Exports prompts, tool data, and metadata while overlapping local opt-in audit. |
| `@nick-vi/opencode-type-inject@1.5.2` | Rejected | Adds context, tools, token/CPU cost, and has inconsistent license declarations. |
| `opencode-playwright-test-agents@0.1.0` | Rejected | The npm package is absent and the source workflow uses mutable remote configuration. |

No managed external plugin was added. Wave 4 rejections for notifier, Morph,
worktree, and PTY plugins remain in force.

## Performance evidence

- Fingerprint benchmark, 20 warm repetitions in one tmux pane:
  - `origin/main`: median `79.554 ms`, p95 `92.876 ms`.
  - candidate: median `31.501 ms`, p95 `36.321 ms`.
  - candidate p95 remained below the `300 ms` gate.
- Audit benchmark, 25 isolated processes:
  - disabled candidate median `0.000662 ms`, below the allowed baseline delta.
  - enabled median ratio `1.204` and p95 ratio `1.212`, both below `1.25`.
- The retained audit benchmark was collected at committed head `1d81e6b` with
  the uncommitted Slice 2 source built into dist. It is Slice 2 performance
  evidence, not a final-head rerun; later slices did not change the benchmarked
  audit or dispatch implementation.
- Evidence: `runtime/harness-wave-5/slice1-fingerprint-benchmark.json` and
  `runtime/harness-wave-5/audit-benchmark.json`.

## Exact-model configured-tuple proof

`runtime/harness-wave-5/exact-model-e2e/report.json` records `PASS` against
`openai/gpt-5.4-mini` at the validated code head.

- Preflight, Python, and Node each recorded exactly one gateway bootstrap and
  observed no other model.
- The Python fixture began red, changed only `stats.py`, preserved
  `test_stats.py`, and finished green.
- The Node fixture began red, changed only `slugify.mjs`, preserved
  `slugify.test.mjs`, and finished green.
- Each project fixture recorded at least one `runtime_session_env_prefixed`
  event from the selected guard.
- Reports prove one tuple, OAuth-store auth, zero forwarded API keys, built-in
  auth retained, zero project shims, aggregate cleanup, and a committed source
  and dist hash.
- The retained E2E scan contains no credential value, temporary sandbox path,
  raw tuple option key, or raw candidate URI. See
  `runtime/harness-wave-5/final-validation/exact-model-e2e-evidence.log`.

The first live preflight exposed a deterministic interaction with the hardened
audit writer: nested audit parents created with permissive mode are rejected
without weakening the running plugin. A two-cell loader probe reproduced zero
audit output for a permissive parent and one bootstrap for an owner-only parent.
The harness now creates and validates `0700` sandbox parents; the localhost
secret smoke safely hardens its owned output directory. Audit files remain
`0600`.

## Validation evidence

The tmux validation summary at
`runtime/harness-wave-5/final-validation/summary.json` records every gate as
`PASS`:

- `git diff --check origin/main...HEAD`.
- `CI=true npm --prefix plugin/gateway-core test`: `744/744`; count retained in
  `runtime/harness-wave-5/final-validation/gateway-tests.log`.
- `npm --prefix plugin/gateway-core run lint`.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: `60/60`; count retained
  in `runtime/harness-wave-5/final-validation/python-tests.log`.
- `python3 -m py_compile` for every touched Python file.
- Critical Ruff rules `E9,F63,F7,F82` on every touched Python file.
- Full Ruff comparison: `21` current findings versus `23` on `origin/main` for
  the comparable touched-file surface, retained in
  `runtime/harness-wave-5/final-validation/ruff-full-comparison.log`.
- `make validate` and `make selftest`.
- `node scripts/gateway_workflow_scenario_report.mjs`.
- `make gateway-secret-redaction-smoke`.
- Package dry-run and extracted default/routing/dist parity.
- Direct and tuple runtime contract probes.
- `pre-commit run --all-files`.
- Committed-clone `make install-test`.
- Exact-model configured-tuple E2E and retained-artifact scan.
- Clean tracked tree after gateway build, pre-commit, and final validation.

Four changed-evidence review/fix passes met the high-risk budget. The latest
critical reviewer approved with no blocker or medium/high finding.

## Residual risks

- Concurrent installer invocations remain last-writer-wins. The installer is a
  single-user CLI, and each individual state write is still atomic and private.
- A failed multi-step profile action cannot undo external mutations that already
  completed; persisted state records only fully successful logical actions.
- Credential-backed E2E depends on a trusted host OAuth store and exact-model
  availability. CI does not run credential-backed model calls.
- OTLP intentionally has no durable cross-process spool or retry queue.
- The DCP experiment remains deferred until measured token pressure justifies it.

## Rollback

- Revert the four commits in reverse order and rebuild
  `plugin/gateway-core/dist/**` after source rollback.
- Evidence schema v2 intentionally invalidates schema v1; rollback must not treat
  mixed-schema records as trusted.
- OTLP is opt-in. Disabling export does not affect core hook dispatch.
- Reverting exact configuration does not restore retired external plugins.
- The configured-tuple harness changes do not alter runtime defaults.
- Root user-authored `opencode.json` and gateway sidecars were not changed by
  this branch.
