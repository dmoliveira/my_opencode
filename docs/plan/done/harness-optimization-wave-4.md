# Harness Optimization Wave 4

## Objective

Ship a fourth evidence-backed harness iteration that removes unsafe or redundant curated third-party plugins, avoids constructing explicitly excluded gateway hooks, makes packed and source gateway defaults identical, and adds an uncached contract-loader diagnostic. Prove the result in tmux with full validation and isolated Python and Node projects using `openai/gpt-5.4-mini`.

## Classification

- Depth: large.
- Risk: high because the work changes installer/plugin policy, gateway hook initialization, packaged runtime contents, and doctor behavior.
- Review budget: 3–5 changed-evidence review-and-fix passes. Stop only after required checks are green and the latest critical review has no blocker.
- Writer policy: one writer in `perf/harness-optimization-wave-4`; read-only discovery/research may fan out to at most two subagents.

## Evidence baseline

- Current runtime status reports only local `gateway-core` enabled; notifier, Morph, and worktree aliases are disabled. All six configured MCPs remain disabled.
- Fresh/noninteractive wizard selection defaults to `lean`, but `PROFILE_MAP["lean"]` enables mutable `@mohak34/opencode-notifier@latest`. A sanitized profile probe confirms lean retains gateway and unknown tuple entries while adding notifier.
- Gateway already owns completion/error/permission/question notifications, so notifier duplicates behavior and introduces another child-process/timer policy surface.
- Official OpenCode v1.18.5 runs plugins in-process with project/client/shell authority. External review found no candidate whose benefit exceeded overlap and supply-chain/data-egress cost. Morph sends full files and edit instructions to a remote API; the worktree repository has no package release/manifest and conflicts with governed worktree delivery; PTY/context-pruning alternatives overlap tmux and gateway memory controls.
- With `hooks.order=["think-mode"]`, 50 plugin constructions create 550 LLM decision runtimes: 11 per initialization. Median construction is 3.833ms and p95 is 4.587ms. Filtering currently happens only after all factories run.
- The default hook order contains `delegation-decision-audit`, but no factory imports or constructs it; only stale source/dist residue remains.
- `npm pack` contains 260 files and zero `config/` entries. A no-sidecar source load sees bundled `llmDecisionRuntime=assist`, while the extracted tarball misses that file and falls back to `disabled`.
- The successful doctor-smoke fingerprint hashes package metadata, routing data, and dist files but omits `config/default-gateway-core.config.json`.
- One cold plus five warm normal-doctor runs passed. Cold was 10.292s; warm median was 1.902s and warm max was 2.350s. The candidate warm median must stay at or below 2.4s and normal doctor must never invoke contract mode.
- Baseline gates: `CI=true npm --prefix plugin/gateway-core test` passes 720/720; focused Python tests pass 11/11; `make validate` and its 26/26 stdlib tests pass.
- Sandbox: tmux session `ai-oc-harness-wave4`, window `wave4`, panes 0–2. Retained evidence lives under ignored `runtime/harness-wave-4/`.

## Durable sequence

### task_2 — Retire curated third-party plugin defaults

1. Replace the active optional catalog with a retired-spec registry for notifier, Morph, and worktree. Preserve backward-compatible status, doctor, profile, and disable/remediation paths, but reject all curated `enable` requests.
2. Make `lean`, legacy `stable`, and legacy `experimental` profiles converge on zero curated external plugins. Applying any profile removes exact retired string/tuple specs while preserving gateway, unknown third-party entries, malformed entries, tuple options, and order.
3. Accept `lean`, `stable`, `experimental`, and `custom` as compatibility inputs, but map all four to the external-free policy, persist only `lean`, clear `custom_plugins`, and never enter the old enable loop. Remove custom default notifier selection and stop presenting obsolete profiles interactively.
4. Doctor must deterministically FAIL when a retired managed spec remains, without exposing tuple options. Status must explain that gateway handles notifications and repository tooling handles edits/worktrees.
5. Update focused tests, selftest expectations, and operator docs. Do not install or enable a replacement: external research selected “add none.”

**Exit:** a fresh noninteractive install and every managed profile retain only gateway plus manually unknown entries; retired specs are removable but not enableable; diagnostics disclose package names only.

### task_3 — Construct only selected gateway hooks

1. Derive disabled and explicit-order sets before hook creation. For a non-empty order, compute an effective dispatch order by inserting required event-driven dependencies immediately before the first consumer: continuation adds stop guard plus keyword detector; global pressure and todo enforcement add stop guard. Deduplicate dependencies deterministically. The construction set equals this effective dispatch set; an empty original order preserves the full default behavior.
2. `safeHook(id, factory)` returns `null` without invoking the factory when `id` is outside the construction set. Pass the effective dependency-expanded order to `resolveHookOrder`, so private state hooks receive relevant events exactly once before consumers. If an explicitly disabled dependency is required, do not construct it and fail closed by excluding its consumer while writing a sanitized `hook_dependency_disabled` bootstrap diagnostic. Never substitute a no-op guard for a selected safety-dependent hook.
3. Keep the provider-boundary secret finalizer independent of configurable hook selection. A one-hook order must still redact provider-boundary secrets.
4. Reuse the selection predicate for semantic summarizer creation. Remove `delegation-decision-audit` from default order and delete its unreferenced source and generated dist residue.
5. Add contract tests proving: minimal order creates zero unrelated LLM runtimes; a selected LLM-backed hook creates only its own runtime; disabled hooks are not constructed; omitted dependencies are inserted and dispatched once before consumers; explicitly disabled dependencies exclude consumers and emit only sanitized diagnostics; explicitly ordered dependencies are not duplicated; full/default order remains compatible; provider redaction survives minimal order.
6. Re-run the 50-iteration tmux benchmark and require zero unrelated runtime factories plus a materially lower median without increasing p95.

**Exit:** explicit selection has no excluded-factory side effects, secret finalization is unchanged, and the minimal-order benchmark reports 11 → 0 LLM runtime constructions per initialization.

### task_4 — Align package defaults and add contract-loader diagnosis

1. Include `config/` in the gateway npm package and change bundled LLM-decision defaults to explicit `disabled`/empty hook modes, matching schema and project policy. Do not enable standalone model calls.
2. Add the bundled default file to doctor-smoke fingerprint inputs so any policy change invalidates a cached PASS.
3. Add a dedicated smoke mode that runs only the existing loader-only `direct` and sanitized `tuple` `opencode debug config` probes. It must use one generated outer temporary root with minimal HOME/projects, the existing allowlisted environment with model fetching/default plugins disabled, no auth/model/server/tool call, and `finally` cleanup across setup errors, timeout, PASS, and FAIL. Contract mode must not create `RUNTIME_ROOT`. Do not reuse legacy path/tarball serve-and-run modes.
4. Give contract mode a 100-second shared aggregate deadline and a 45-second per-probe ceiling. Each probe receives `min(45s, remaining aggregate time)`; the gateway parent timeout is 120 seconds, leaving 20 seconds for projection and cleanup.
5. Add `/gateway doctor --deep [--json]` backed by explicit cache policies: `reuse` for normal direct doctor, `refresh` for direct `--fresh`, and `none` for deep contract mode. Reject `--deep --fresh`. Deep PASS or FAIL must leave an existing direct cache byte-for-byte unchanged and must not create one when absent.
6. Restrict cached summaries to exactly one `mode=direct` PASS result. Project every live PASS/FAIL/SKIP through one status-agnostic allowlist before JSON or text output; never expose or retain options, sentinel values, raw config, environment, stdout/stderr, credentials, plugin paths, or temporary paths. Deep succeeds only with exactly one PASS each for `direct` and `tuple`; any SKIP, missing/duplicate/malformed mode, or FAIL is nonzero without touching cache.
7. Add tests for package contents, source/extracted parity, fingerprint inputs, deep CLI forwarding, cache invariance, no-cache creation, direct-only cache validation, contract-mode invocation, aggregate timeout, cleanup, sanitization canaries, strict two-mode success, and failure propagation.
8. In tmux, require `npm pack --dry-run --json` to contain the bundled config and require isolated source/extracted-package config loads—not serve-and-run smoke modes—to produce identical disabled defaults. Require deep contract doctor and direct cached doctor to pass; warm normal-doctor median must remain at or below 2.4s.

**Exit:** source and packed behavior match, cache validity covers runtime config, deep diagnostics prove direct+tuple host contracts without model/data-egress paths, and normal doctor remains fast.

### task_5 — Audit, realistic E2E, and delivery

1. Record internal and external evidence, selected/deferred decisions, baseline/candidate measurements, and exact validation in `docs/harness-optimization-wave-4-audit-2026-07-26.md`.
2. Run the existing isolated project harness for one Python and one Node project with `openai/gpt-5.4-mini`. Projects must start red, be repaired by the build agent without test edits, and finish green through the candidate plugin.
3. Confirm one candidate gateway source/bootstrap, no retired plugin install/load attempt, no leaked sentinel/credential, and bounded process/session cleanup. Require zero exact occurrences of all three retired specs across retained stdout, stderr, audit, and report artifacts.
4. Deliver no more than four focused commits: external plugin policy; selected-hook construction; package/deep doctor; audit/E2E closure.
5. Re-fetch `origin/main`, check overlaps, push, open PR, wait for CI, complete critical review, squash merge, export/close Codememory, preserve evidence, remove branch/worktree/tmux, and safely sync local `main` without changing user-authored configuration.

**Exit:** realistic projects are green, all checks pass, PR is merged, and cleanup is complete.

## File scope

- `scripts/{plugin_command.py,install_wizard.py,gateway_command.py,gateway_local_plugin_runtime_smoke.py,selftest.py}` and focused tests, including `tests/test_gateway_plugin_runtime_smoke.py`.
- `plugin/gateway-core/{package.json,config/default-gateway-core.config.json,src/index.ts,src/config/schema.ts,test/**,dist/**}`.
- Delete only the unreferenced `plugin/gateway-core/{src,dist}/hooks/delegation-decision-audit/**` residue.
- `docs/command-handbook.md`, this plan, and `docs/harness-optimization-wave-4-audit-2026-07-26.md`.
- Ignored evidence only under `runtime/harness-wave-4/`.

## Safety constraints

- Do not edit root `opencode.json`, root `gateway-core.config.json`, or `.opencode/gateway-core.config.json`. Hash all three before and after. Preserve local `main` changes.
- Run every plugin-profile mutation against an isolated HOME/config. Treat tuple option objects as potentially secret; retained evidence may contain normalized specs only.
- Do not add or enable any external plugin, MCP, PTY server, or cloud/data-egress edit path.
- Keep normal doctor cache security (`0700` directory, `0600` atomic file, no symlink following) and provider-boundary secret finalization.
- Deep doctor is explicit, loader-only, sanitized, and uncached; it must not read, replace, invalidate, or populate the direct-only fast cache. Legacy path/tarball serve-and-run modes remain outside doctor.
- Do not expand into runtime database work, remaining wildcard-event migration, general process-pressure optimization, or permission-policy redesign.

## Validation gates

1. Per-slice: `git diff --check`; Python `py_compile`/Ruff for touched scripts; focused unittest; TypeScript build/lint and focused Node tests.
2. Plugin gates: `CI=true npm --prefix plugin/gateway-core test`, isolated package-content/config-parity probe, one-hook construction benchmark, and normal direct plus dedicated contract-mode direct+tuple smokes. Legacy `--mode all|both|path|tarball` is prohibited from automated Wave 4 validation.
3. Repo gates: `make validate`, `make selftest`, `node scripts/gateway_workflow_scenario_report.mjs`, `make gateway-secret-redaction-smoke`, `pre-commit run --all-files`, and committed-clone `make install-test`.
4. Live tmux gates: one cold and at least five warm normal-doctor timings (warm median <=2.4s), `doctor --fresh`, uncached `doctor --deep`, direct-cache byte invariance across deep PASS/FAIL, protected-config hashes, plugin profile migration, and pane captures.
5. E2E gate: `python3 scripts/harness_wave2_task4_smoke.py projects --repo-root "$PWD" --output-dir runtime/harness-wave-4/exact-model --model openai/gpt-5.4-mini --json` with Python/Node red-to-green proof and no test edits.
6. Reviews: plan critic before implementation; verifier after each meaningful implementation chunk; 3–5 changed-evidence review/fix passes total; final critical reviewer must report no blocker.

## Rollback

- Before merge, each validated slice commit can be reverted independently. After squash merge, revert the Wave 4 squash as a whole or restore the affected files from its parent; do not promise per-slice Git SHAs on `main`.
- Reverting package/deep-doctor code restores direct-only diagnostics and prior package contents; the uncached deep path creates no durable state.
- Reverting selected-hook code restores construct-then-filter behavior; no config migration exists.
- Applying an external-free profile is an intentional one-way user-state migration for exact retired entries, including tuple options. A code revert cannot reconstruct removed options and must never auto-re-enable retired plugins. Manually unknown entries are preserved throughout.

## Deferred

- Any external plugin addition, including Morph, DCP, PTY, notifier, or worktree automation.
- General event-routing migration and process-pressure caching.
- Runtime SQLite backlog already tracked in the separate Codememory epic.
- Credential-backed model calls in CI.
