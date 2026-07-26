# Harness Optimization Wave 4 Audit

Completed on 2026-07-27 from the dedicated `perf/harness-optimization-wave-4` worktree. The work was classified as large and high risk. Planning received three blocker-first critical reviews before implementation.

## Scope and decision

Wave 4 addressed three measured gaps:

1. The default `lean` installer profile enabled mutable `@mohak34/opencode-notifier@latest`, even though gateway-core already owns completion, error, permission, and question notifications.
2. A gateway configured with only `think-mode` still created 11 unrelated LLM decision runtimes during every initialization.
3. The source plugin loaded `config/default-gateway-core.config.json`, but the npm package omitted that file. Source defaults enabled `assist`; packed defaults silently fell back to `disabled`.

No third-party plugin was added. OpenCode plugins execute in-process with project, client, and shell access, so an addition needs clear value beyond its supply-chain, authority, and data-egress cost. The reviewed candidates did not meet that bar:

- Notifier duplicated gateway behavior and added subprocess, sound, and timer policy.
- Morph Fast Apply sent complete files and edit instructions to a remote service and introduced another privileged write path.
- The reviewed worktree plugin had no packaged release or CI and conflicted with this repository's governed worktree, validation, PR, and cleanup flow.
- Context-pruning and PTY candidates overlapped gateway memory controls and the tmux sandbox.

The resulting policy keeps the local gateway-core plugin and native repository tooling. Exact legacy notifier, Morph, and worktree specs remain recognizable for safe removal, but managed enable paths reject them.

## External evidence

- OpenCode v1.18.5 release: <https://github.com/anomalyco/opencode/releases/tag/v1.18.5>
- Official plugin model and sequential hook behavior: <https://opencode.ai/docs/plugins/>
- Official permission model: <https://opencode.ai/docs/permissions/>
- Notifier 0.2.8: <https://registry.npmjs.org/@mohak34%2Fopencode-notifier/0.2.8>
- Notifier reviewed commit: <https://github.com/mohak34/opencode-notifier/commit/509382c0cb03c5036d84ef873e84c8ba2d92d2d0>
- Morph Fast Apply v1.11.0: <https://github.com/JRedeker/opencode-morph-fast-apply/releases/tag/v1.11.0>
- Morph reviewed commit: <https://github.com/JRedeker/opencode-morph-fast-apply/commit/7f347df7d17f13f1f24083de9ae4b9b2d173d1fb>
- Worktree reviewed commit: <https://github.com/kdcokenny/opencode-worktree/commit/77c2262f1c2c71077284643232cc85f6d05e06c0>

## Implementation

### External-free managed profiles

- `lean`, legacy `stable`, legacy `experimental`, and installer `custom` inputs normalize to `lean` and persist no curated external plugins.
- Exact retired string and `[spec, options]` tuple entries are removed. Gateway entries, unknown plugins, malformed entries, tuple options, and order are preserved.
- Retired aliases are disable-only. Enable attempts return nonzero without modifying configuration bytes.
- Plugin doctor returns `FAIL` while an exact retired entry remains and reports normalized specs only. Tuple option objects are never printed.

### Selected-hook construction

- Explicit orders now construct only selected hooks plus deterministic stateful dependencies.
- Omitted stop/keyword dependencies are inserted once before consumers. An explicitly disabled dependency excludes its consumer and emits a sanitized `hook_dependency_disabled` audit event.
- The provider-boundary secret finalizer remains independent of configurable hook selection.
- The unused `delegation-decision-audit` default-order entry and source/dist residue were removed.

### Package parity and deep diagnosis

- Gateway packages now include `config/default-gateway-core.config.json`.
- Bundled LLM decision defaults are explicitly `disabled` with empty hook modes, matching schema and project policy.
- The doctor-smoke fingerprint includes the bundled config, so policy changes invalidate old direct-loader evidence.
- `/gateway doctor --deep --json` runs only loader-level direct and tuple `opencode debug config` probes. It uses isolated temporary homes, a 45-second per-probe ceiling, a 100-second shared deadline, and a 120-second parent timeout.
- Deep mode is uncached. It neither reads nor changes the normal direct-loader cache. PASS, FAIL, and SKIP results pass through the same fixed-field projector; raw output, paths, environment, options, and credentials are discarded.

## Measurements

| Measurement | Baseline | Candidate | Result |
| --- | ---: | ---: | --- |
| LLM runtime factories per minimal initialization | 11 | 0 | 100% removed |
| Minimal initialization median, 50 runs | 3.833ms | 0.040ms | 98.95% lower |
| Minimal initialization p95 | 4.587ms | 0.176ms | 96.16% lower |
| Packaged config files | 0 | 1 | bundled default included |
| Source no-sidecar LLM mode | `assist` | `disabled` | safe policy |
| Packed no-sidecar LLM mode | `disabled` (missing file) | `disabled` (loaded file) | source parity |
| Normal doctor cold run | 10.292s | 7.229s | 29.76% lower |
| Normal doctor warm median, five runs | 1.902s | 2.006s | 5.47% variance; below 2.4s SLO |
| Deep direct+tuple doctor | unavailable | 10.186s | PASS, uncached |

The deep PASS left the existing direct cache byte-for-byte unchanged. Its retained SHA-256 was `dc52c4ff5f3fcac1ae44b33b5b22e41e6a8beb9d002f8a839c2b2f0220c755bc`.

## Real-project E2E

The existing isolated project harness ran in tmux with `openai/gpt-5.4-mini`:

```text
python3 scripts/harness_wave2_task4_smoke.py projects \
  --repo-root "$PWD" \
  --output-dir runtime/harness-wave-4/exact-model \
  --model openai/gpt-5.4-mini \
  --json
```

Results:

- Preflight resolved the exact model and observed one candidate gateway bootstrap.
- The Python fixture started red, changed only `stats.py`, preserved `test_stats.py`, and finished green.
- The Node fixture started red, changed only `slugify.mjs`, preserved `slugify.test.mjs`, and finished green.
- Each fixture observed only `openai/gpt-5.4-mini` and one candidate bootstrap.
- The retained E2E set contained zero occurrences of all three retired plugin specs and zero credential-pattern hits across 20 files.

## Validation evidence

- `CI=true npm --prefix plugin/gateway-core test`: 726/726 PASS.
- `npm --prefix plugin/gateway-core run lint`: PASS.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 36/36 PASS.
- Focused plugin profile, doctor cache, contract cleanup, timeout, sanitization, and package tests: PASS.
- `make validate`: PASS.
- `make selftest`: PASS after updating the stale layered-config assertion to the new retired-state wording.
- `node scripts/gateway_workflow_scenario_report.mjs`: all scenarios correct.
- `make gateway-secret-redaction-smoke`: PASS; canaries absent, audit safe, no host credentials forwarded.
- Critical Ruff rules (`E9,F63,F7,F82`) on touched Python: PASS.
- Full Ruff still reports the same 27 baseline findings in `scripts/gateway_command.py`; no new critical finding was introduced. The touched smoke script retains two pre-existing non-critical findings (`EXE001`, `PLW1509`).
- Package dry-run and extracted-package parity: PASS.
- Tmux session `ai-oc-harness-wave4`, window `wave4`, retained pane captures for baselines, candidate probes, validation, and E2E.

## Safety and rollback

- Root `opencode.json`, root `gateway-core.config.json`, and `.opencode/gateway-core.config.json` were not edited. Main-worktree user changes remain separate.
- Applying an external-free profile intentionally removes exact retired tuple entries and their options. A code revert cannot reconstruct those options and must not re-enable retired plugins.
- Deep diagnostics create no durable state. Reverting the package/doctor slice restores direct-only diagnosis.
- Selected-hook construction has no config or data migration and can be reverted independently before squash delivery.

## Deferred

- External plugins, including notifier, Morph, dynamic context pruning, and PTY servers.
- General wildcard-event migration and process-pressure optimization.
- Runtime SQLite hardening already tracked in its separate Codememory epic.
- Credential-backed model calls in CI.
