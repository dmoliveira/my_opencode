# LLM Decision Hooks Plan

Date: 2026-03-09
Status: `in_progress`
Branch: `plan/llm-decision-hooks`
Worktree: `/Users/cauhirsch/Codes/Projects/my_opencode-wt-llm-decision-hooks`

## Goal

Upgrade selected gateway decisions from brittle regex and shallow heuristics to a hybrid model:

- keep deterministic guards for hard safety and syntax checks
- add a tiny LLM decision layer for ambiguous semantic classification
- force single-character outputs so hooks stay cheap, auditable, and easy to fall back from

## Decision policy

Use LLM decisions only when all of the following are true:

1. The current logic is semantic, ambiguous, or regex-heavy.
2. A wrong answer is recoverable through fallback or retry.
3. The hook can run under a small context budget.
4. A deterministic fallback remains available.

Do not use LLM decisions for:

- dangerous shell command blocking
- secret detection
- worktree/branch policy guards
- exact command syntax enforcement
- hard merge readiness rules backed by explicit repo state

## Target architecture

## Status snapshot

- Overall status: `in_progress`
- Current checkpoint: runtime plus delegation, validation, PR-body, and done-proof semantic slices are implemented in this worktree and validated with real-session probes
- Current active slice: Epic 5 hardening is active; live rollout is unblocked through the gateway sidecar config path while assist telemetry accumulates
- Current rollout baseline template: `docs/plan/status/in_progress/llm-rollout-thresholds.template.json`
- Initial assist candidates are tracked in `docs/plan/status/in_progress/llm-rollout-promotion-candidates.md`
- Per-hook assist rollout is now supported through `llmDecisionRuntime.hookModes`
- Canonical rollout config example: `docs/plan/status/in_progress/llm-rollout-config.example.json`
- Live runtime config path: `.opencode/gateway-core.config.json` (or `MY_OPENCODE_GATEWAY_CONFIG_PATH`) now carries gateway plugin settings without violating OpenCode root schema
- Scenario reliability fixtures live in `docs/plan/status/in_progress/llm-scenario-fixtures.json`

### Epic status

| Epic | Status | Notes |
|---|---|---|
| Epic 1 - Build the decision runtime | done | Shared runtime, parser, prompt builder, caching, audit metadata, and central config are implemented. |
| Epic 2 - Hybrid delegation decisions | done | `agent-model-resolver` and `agent-denied-tool-enforcer` use the centralized runtime with real simulation evidence. |
| Epic 3 - Medium-risk semantic classifiers | done | `auto-slash-command`, `provider-error-classifier`, `delegation-fallback-orchestrator`, `validation-evidence-ledger`, `pr-body-evidence-guard`, and `done-proof-enforcer` semantic fallback slices are implemented. |
| Epic 4 - Safety, cost, and performance controls | in_progress | Modes, per-hook mode overrides, timeouts, cache TTL, cache size, compact prompts, audit meanings, representative shadow-deferred behavior, disagreement aggregation, rollout recommendations, markdown artifact generation, per-hook threshold tuning, and sidecar-based live config wiring are implemented; assist telemetry collection is now waiting on real traffic volume. |
| Epic 5 - Prompt and protocol hardening | in_progress | Single-char contract, parser tests, prompt refinements, refusal rejection, untrusted-context serialization, stronger adversarial phrase neutralization, mixed-context coverage, hook-specific auto-slash sanitization, successful provider/done-proof mixed-context probes, validation-ledger command sanitization, and sanitized fallback failure classification are in place; remaining work is broader adversarial expansion rather than a known blocking hotspot. |
| Epic 6 - Real scenario simulation loop | in_progress | Each implemented slice has fresh-session simulation evidence recorded in validation docs, and a scenario-report harness now exists for accuracy/latency tracking across representative requests; current checked scenario set is passing at 100% across 5 representative cases. |
| Epic 7 - Rollout and cleanup | pending | No rollout promotion or heuristic removal yet. |

### Task status by backlog item

| Item | Status | Notes |
|---|---|---|
| `agent-model-resolver` | done | Assist/enforce routing with cache and clear meanings shipped. |
| `agent-denied-tool-enforcer` | done | Mutation and denied-tool semantic fallback shipped. |
| denied-tool semantic implication path | done | Implemented inside denied-tool enforcer slice. |
| `auto-slash-command` | done | Ambiguous diagnostics intent uses AI fallback; prompt refined from live failure. |
| `provider-error-classifier` | done | Ambiguous provider wording uses AI fallback. |
| `delegation-fallback-orchestrator` | done | Ambiguous failure output now classifies into fallback reason codes. |
| validation command and output semantic fallback | done | Wrapper command classification shipped in validation ledger. |
| done-proof and PR-body semantic fallback | done | Both `pr-body-evidence-guard` and `done-proof-enforcer` semantic fallback paths are implemented and validated. |

### Epic 1 - Build the decision runtime

Purpose: create one reusable path for tiny-model hook decisions before changing any hook logic.

Tasks:

1. Add a gateway-core decision client wrapper for tiny-model calls with strict timeout, max token, and retry budget.
2. Add a one-character response contract with enum decoding, invalid-response fallback, and audit reason codes.
3. Add prompt templates for binary, multi-class, and abstain-capable decisions.
4. Add context shaping helpers for last-N lines, prompt/description slices, agent metadata, and command/output truncation.
5. Add deterministic fallback modes: `allow`, `block`, `keep_current`, or `skip_ai` per hook.
6. Add telemetry fields for latency, model, prompt bytes, decision char, fallback path, and confidence mode.

Acceptance:

- every AI-assisted hook uses the same wrapper
- every decision is reproducible from logged prompt template id plus truncated inputs
- invalid or slow model responses never block the event loop indefinitely

### Epic 2 - Add hybrid routing for highest-value delegation decisions

Purpose: improve the highest-value semantic decisions first, where regex scoring is weakest and errors are recoverable.

Tasks:

1. Upgrade `plugin/gateway-core/src/hooks/agent-model-resolver/index.ts` to call AI only on low-confidence or no-explicit-choice cases.
2. Keep current regex scoring as tier-0 routing and use AI as tie-breaker or override candidate.
3. Design a one-character routing alphabet for subagent selection plus `K` = keep explicit choice and `N` = no-opinion.
4. Upgrade `plugin/gateway-core/src/hooks/agent-denied-tool-enforcer/index.ts` to classify `R` read-only-safe vs `M` mutating intent when regex signals are ambiguous.
5. Add a denied-tool semantic decision path for implied tool requests, with deterministic literal checks still first.

Acceptance:

- explicit user agent choice still wins unless policy allows override
- deterministic blocks remain in place for obvious violations
- AI is called only in ambiguity bands, not on every delegation

### Epic 3 - Expand to medium-risk semantic classifiers

Purpose: replace secondary regex islands that benefit from contextual reasoning but do not control hard safety.

Tasks:

1. Upgrade `plugin/gateway-core/src/hooks/auto-slash-command/index.ts` to support broader intent-to-command mapping with a compact code table.
2. Upgrade `plugin/gateway-core/src/hooks/provider-error-classifier/index.ts` to classify retry cause from vendor-specific wording.
3. Upgrade `plugin/gateway-core/src/hooks/delegation-fallback-orchestrator/index.ts` failure-cause detection to a tiny-model classifier.
4. Upgrade `plugin/gateway-core/src/hooks/shared/validation-command-matcher.ts` and `plugin/gateway-core/src/hooks/validation-evidence-ledger/index.ts` only for unmatched wrappers or ambiguous outputs.
5. Optionally add semantic fallback validation for `plugin/gateway-core/src/hooks/done-proof-enforcer/index.ts` and `plugin/gateway-core/src/hooks/pr-body-evidence-guard/index.ts` after deterministic markers fail.

Acceptance:

- deterministic fast path still handles the common case
- AI only runs when regex produced `unknown`, `none`, or low-confidence output

### Epic 4 - Safety, cost, and performance controls

Purpose: prevent the AI layer from making the gateway slower, noisier, or less explainable.

Tasks:

1. Add per-hook budgets for timeout, max calls per session, and cooldown windows.
2. Add config flags for `disabled`, `shadow`, `assist`, and `enforce` modes.
3. Start each upgraded hook in shadow mode and compare AI output against current deterministic outcome.
4. Add disagreement audit logs and daily summary tooling for false positive and false negative review.
5. Add model routing defaults to prefer a cheap model such as `openai/gpt-5.1-codex-mini` and allow provider fallback.

Acceptance:

- no hook ships directly to enforce mode without shadow evidence
- cost and latency can be disabled or tightened from config

### Epic 5 - Prompt and protocol hardening

Purpose: keep prompts tiny and outputs reliable enough for event hooks.

Tasks:

1. Standardize prompt format: rule, compressed context, decision alphabet, answer-only instruction.
2. Require exactly one ASCII character in response.
3. Add parser tests for extra whitespace, multi-character answers, refusal text, and empty responses.
4. Add optional two-step pattern for risky hooks: classifier char first, explanation only in audit shadow mode.
5. Add adversarial tests for prompt injection from user content and tool output.

Acceptance:

- single-char parsing is deterministic
- user-provided content cannot redefine the decision alphabet or output contract

### Epic 6 - Real scenario simulation loop

Purpose: validate each shipped feature in a real operator-style run instead of trusting unit coverage alone.

Tasks:

1. After each feature slice, spawn a fresh `opencode` session from a dedicated validation worktree or sandbox repo fixture.
2. Run a scripted scenario that exercises the new hook with realistic prompt history, tool outputs, and failure cases.
3. Capture the model decision char, deterministic fallback result, latency, final user-visible outcome, and audit trail.
4. Compare expected vs actual behavior and refine prompt, alphabet, context shaping, or fallback policy before the next slice.
5. Keep repeating until the scenario is stable across at least one happy path and one adversarial or ambiguous path.

Acceptance:

- every new AI-assisted hook has a real-session simulation result before promotion
- prompt or parser refinements happen in the same slice, not deferred indefinitely
- scenario evidence is logged in docs or validation artifacts for later replay

Latest evidence:

- `docs/plan/status/in_progress/llm-decision-hooks-validation-2026-03-09.md`

### Epic 7 - Rollout and cleanup

Purpose: land changes safely and retire low-value heuristics only after evidence exists.

Tasks:

1. Ship Epic 2 hooks behind config flags in shadow mode.
2. Review disagreement logs and tune prompts, alphabets, and fallback policy.
3. Promote best-performing hooks to assist mode.
4. Promote only proven hooks to enforce mode.
5. Remove obsolete regex branches only after parity evidence is stable.

Acceptance:

- rollout is reversible per hook
- deterministic fallback remains available after launch

## Ordered implementation backlog

Highest value first:

1. `agent-model-resolver`
2. `agent-denied-tool-enforcer`
3. denied-tool semantic implication path
4. `auto-slash-command`
5. `provider-error-classifier`
6. `delegation-fallback-orchestrator`
7. validation command and output semantic fallback
8. done-proof and PR-body semantic fallback

## Why this order

- `agent-model-resolver` and `agent-denied-tool-enforcer` are the biggest semantic bottlenecks today.
- they already contain regex scoring and exception logic, which signals high maintenance cost.
- they are recoverable if the model abstains or falls back.
- command safety, secrets, and worktree policy should remain deterministic because they are hard-guard territory.

## Suggested single-character protocols

- Routing: `E L V R S O A P K N`
  - `E` explore
  - `L` librarian
  - `V` verifier
  - `R` reviewer
  - `S` release-scribe
  - `O` oracle
  - `A` ambiguity-analyst
  - `P` strategic-planner or plan-critic per table version
  - `K` keep explicit choice
  - `N` no-opinion
- Mutation safety: `M R N`
  - `M` mutating
  - `R` read-only-safe
  - `N` unclear
- Denied tool intent: `D A N`
  - `D` denied tool implied
  - `A` allowed/no issue
  - `N` unclear
- Auto slash: command-specific code table plus `N`
- Error class: `R O T A N`
  - `R` retryable rate/limit
  - `O` overload/provider instability
  - `T` token/context issue
  - `A` auth/account tier issue
  - `N` unknown/non-retryable

## Rollout notes

- Phase 1: shadow only, log disagreement, no behavior change.
- Phase 2: assist mode, AI may add hints but deterministic logic still decides.
- Phase 3: enforce mode only where shadow parity is high and fallback remains cheap.

## Validation plan

1. Unit tests for prompt builders, parsers, and fallback behavior.
2. Fixture tests for known routing and mutation-intent cases.
3. Shadow-mode replay on recent audit samples.
4. Latency budget checks for hot hooks.
5. Failure injection tests for timeout, malformed output, and provider outage.
6. Fresh `opencode` simulation after each feature slice with at least one refine-and-rerun loop.

## E2E worktree flow

1. Keep `/Users/cauhirsch/Codes/Projects/my_opencode` on `main` for inspection and sync only.
2. Implement in `/Users/cauhirsch/Codes/Projects/my_opencode-wt-llm-decision-hooks` on `plan/llm-decision-hooks`.
3. Validate from the task worktree and from fresh `opencode` simulation sessions tied to that slice.
4. Merge the branch back to `main` with branch deletion after review.
5. Sync the primary worktree while it remains on `main`, then remove the task worktree.
