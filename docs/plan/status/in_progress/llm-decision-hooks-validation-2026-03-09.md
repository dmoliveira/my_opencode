# LLM Decision Hooks Validation - 2026-03-09

Branch: `plan/llm-decision-hooks`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-llm-decision-hooks`

## Scope

Fresh-session simulation evidence for the centralized LLM decision runtime slices shipped in this branch so far:

- `agent-model-resolver`
- `agent-denied-tool-enforcer`
- `auto-slash-command`

## Real simulation results

### 1. Resolver route classification

Scenario:

- prompt asks for official docs and upstream reference
- expected route: `librarian`

Observed:

- result char: `L`
- meaning: `route_librarian`
- outcome: resolver rewrote delegated subagent to `librarian`

### 2. Mutation classifier

Scenario:

- prompt asks to prepare exact code changes and commit-ready edits
- expected mutation class: mutating

Observed:

- result char: `M`
- meaning: `mutating_requested`
- outcome: enforce-mode path can block read-only subagent delegation

### 3. Denied-tool implication classifier

Scenario:

- prompt asks to shell out and inspect git directly
- expected tool implication class: denied tool implied

Observed:

- result char: `D`
- meaning: `denied_tool_implied`
- first run latency: about `5.4s`
- second run latency: `0ms` from cache

### 4. Auto slash ambiguous doctor intent

Scenario:

- prompt: `can you inspect the environment health and tell me what is wrong`
- expected slash: `/doctor`

Observed before refinement:

- raw output was non-compliant explanatory text
- result: invalid response
- root cause: prompt framed the task as slash-command choice instead of simple diagnostics classification

Refinement:

- changed AI instruction to `Classify this request for diagnostics intent. D=diagnostics_or_health_check, N=not_diagnostics.`

Observed after refinement:

- result char: `D`
- meaning: `route_doctor`
- first hook run latency: about `7.2s`
- second identical hook run latency: `0ms` from cache
- final rewritten text: tagged `/doctor`

### 5. Auto slash adversarial/high-risk prompt

Scenario:

- prompt: `please install and configure devtools for me`
- expected behavior: no AI rewrite

Observed:

- latency: about `1ms`
- output unchanged
- result: correctly skipped due to high-risk install/configure guard

### 6. Provider error ambiguous wording

Scenario:

- error text: `Service temporarily saturated, please retry later`
- expected class: provider overloaded/unavailable

Observed:

- result char: `O`
- meaning: `provider_overloaded`
- first run latency: about `5.8s`
- second identical run latency: `0ms` from cache
- outcome: provider hint injection can now recover when deterministic retry-reason parsing misses vendor wording

## Validation commands

- `npm --prefix plugin/gateway-core run build`
- `npm --prefix plugin/gateway-core run lint`
- `node --test plugin/gateway-core/test/auto-slash-command-hook.test.mjs plugin/gateway-core/test/llm-decision-runtime.test.mjs plugin/gateway-core/test/runtime-delegation-hooks.test.mjs plugin/gateway-core/test/config-load.test.mjs`
- `node scripts/gateway_llm_disagreement_report.mjs .opencode/gateway-events.jsonl`
- `node scripts/gateway_llm_disagreement_report.mjs .opencode/gateway-events.jsonl --markdown-out docs/plan/status/in_progress/llm-disagreement-rollout-report.md`
- `node scripts/gateway_llm_disagreement_report.mjs .opencode/gateway-events.jsonl --thresholds path/to/llm-rollout-thresholds.json`
- Baseline thresholds template: `docs/plan/status/in_progress/llm-rollout-thresholds.template.json`

## Key takeaways

- centralized single-char decisions are working in real `opencode run` flows
- cache materially improves hot-repeat latency
- prompt wording matters a lot for compliance; classification framing works better than action framing
- high-risk prompts should stay on deterministic skip paths
- provider-style vendor wording benefits from AI fallback when canonical regexes miss the phrasing
- disagreement audits can now be aggregated into rollout recommendations with `scripts/gateway_llm_disagreement_report.mjs`
- the same report can now emit a markdown artifact for daily human review with `--markdown-out`
- rollout recommendations can now be tuned per hook with a thresholds JSON passed to `--thresholds`
- the repo now carries a checked-in starter policy at `docs/plan/status/in_progress/llm-rollout-thresholds.template.json`
- initial shadow-to-assist hook candidates are tracked in `docs/plan/status/in_progress/llm-rollout-promotion-candidates.md`
- per-hook assist rollout is now supported through `llmDecisionRuntime.hookModes`

### 7. Delegation fallback ambiguous failure output

Scenario:

- task delegation fails with ambiguous runtime wording: `The task delegation could not proceed because the request shape was not accepted by the runtime.`
- expected class: invalid arguments
- expected next retry behavior: remove explicit subagent and fall back to `category=general`

Observed:

- result char: `I`
- meaning: `delegation_invalid_arguments`
- first classification latency: about `5.7s`
- next retry rewrite latency: `0ms`
- final retry mutation:
  - `subagent_type` removed
  - `category` changed to `general`
  - fallback hint prepended to prompt/description

Outcome:

- ambiguous failure text now triggers the same fallback flow that was previously limited to deterministic string matches

### 8. Validation evidence ambiguous wrapper command

Scenario:

- command: `./scripts/ci-check tests/api smoke`
- deterministic matcher does not recognize it
- expected class: test evidence

Observed:

- result char: `T`
- meaning: `test`
- first classification latency: about `8.3s`
- second identical classification latency: `0ms` from cache

Outcome:

- wrapper-style validation commands can now contribute ledger evidence even when they do not match the built-in regex catalog
- note: when replayed inside the real repo plugin stack, `done-proof-enforcer` still enforced the repo's broader required markers (`validation`, `lint`); that surfaced as an environment/config expectation rather than a regression in the new classifier path

Locked by test:

- `plugin/gateway-core/test/validation-evidence-ledger-hook.test.mjs` now includes a repo-style integration case proving that LLM-derived `test` evidence alone does not satisfy broader `done-proof-enforcer` marker requirements like `validation` and `lint`

### 9. PR body semantic section fallback

Scenario:

- PR body uses semantic equivalents instead of exact headers
- body:
  - `## Why this change matters`
  - `## Checks performed`

Observed:

- summary decision char: `Y`
- summary meaning: `summary_present`
- validation decision char: `Y`
- validation meaning: `validation_present`
- first summary latency: about `8.6s`
- first validation latency: about `5.2s`
- repeated validation decision latency: `0ms` from cache

Outcome:

- `pr-body-evidence-guard` can now accept semantically valid PR body structure even when headings are not exact `## Summary` and `## Validation`

### 10. Done-proof semantic completion evidence fallback

Scenario:

- completion text says `Completed smoke verification and regression checks successfully.`
- exact marker `test` is absent
- expected semantic result: treat this as test-equivalent wording

Observed:

- decision char: `Y`
- meaning: `test_present`
- first decision latency: about `5.1s`
- repeated identical decision latency: `0ms` from cache

Outcome:

- `done-proof-enforcer` can now accept semantically valid completion evidence wording when text fallback is allowed and ledger evidence is still missing
