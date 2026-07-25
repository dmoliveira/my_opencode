# Harness optimization audit — 2026-07-25

## Scope

This audit covered the gateway plugin, configuration layering, agent delegation, skills, diagnostics, deterministic scenarios, and the local OpenCode runtime database. Runtime inspection was read-only until two stale-session repairs were previewed, scoped, backed up, applied, and integrity-checked.

Risk classification: large / high. Review budget: 3–5 review-and-fix passes.

## Runtime evidence

The runtime database was healthy at the SQLite level but oversized and carried stale delegation state.

| Signal | Observed value | Interpretation |
| --- | ---: | --- |
| Sessions / messages / parts | 9,122 / 140,786 / 674,210 | Enough history to expose recurring failures rather than isolated incidents. |
| Tool parts | 226,550 | Main sample used for tool reliability. |
| Tool error or failed states | 8,419 (3.7%) | Most failures came from web retrieval, missing files, policy blocks, and patch mismatches. |
| Task latency | p50 58.7s, p95 231.0s | Delegation is expensive enough to require strict routing and review budgets. |
| 90-day input / cache-read tokens | 1.30B / 17.64B | Prompt and review reuse dominates cost; these aggregates are not a causal benchmark for this patch. |
| Runtime DB footprint | 4.84GB | `part` used about 3.28GB, `event` 902MB, and `message` 227MB. Retention needs a separate previewable design. |
| Stale delegation findings | 3 findings across 2 parent repair targets | Two completed children left one parent tool open; one abandoned child left another parent open. |

Selected 90-day tool outcomes:

| Tool | Completed | Error/failed | Approx. error rate | p95 latency |
| --- | ---: | ---: | ---: | ---: |
| `bash` | 65,243 | 1,079 | 1.6% | 1.83s |
| `read` | 48,048 | 1,325 | 2.7% | 0.63s |
| `webfetch` | 8,985 | 2,313 | 20.5% | 4.54s |
| `apply_patch` | 6,727 | 796 | 10.6% | 1.65s |
| `task` | 5,395 | 86 | 1.6% | 231.0s |

The dominant harness-generated errors were intentional guard blocks: interactive shell commands, protected-branch edits, missing PR validation evidence, stale branches, and unsafe cleanup. Recurring non-policy failures included stale URLs, missing `AGENTS.md` paths, patch-context mismatches, oversized grep records, and historical runtime schema errors. Assistant-level failures in the 90-day window included 493 aborted messages, 191 API errors, 27 unknown errors, four context overflows, and 11 previously recovered stale sessions.

## Confirmed defects

1. Eight workflow guards were registered twice. Several performed filesystem or Git checks, so every matching event paid duplicate work.
2. Hook IDs were not checked for uniqueness. A future duplicate could silently reintroduce the bug.
3. Event subscription support existed but the expensive workflow guards still received unrelated events.
4. The delegation outcome learner ignored `adaptiveDelegationPolicy.enabled` and immediately rewrote task category, prompt, and description after a small failure sample.
5. Project gateway config replaced the global sidecar instead of overriding it. Intended global disables were therefore invisible whenever a project sidecar existed.
6. The session wrapper promoted the automatically selected project sidecar into the explicit replacement environment variable, preventing layered config.
7. Consolidated doctor output counted optional child problems as top-level problems and rendered contradictory states such as a skipped check with a raw `FAIL`.
8. Disabled auto-slash evaluated precision against zero predictions and failed diagnostics even though no routing was active.
9. Scoped stale-session repair suggested an unscoped apply command, reported unrelated global findings, and counted duplicate child findings that mapped to one parent repair target.
10. Delegation health depended on the full event audit even though bounded runtime outcome state already existed.
11. Deterministic workflow scenarios produced reports but did not gate CI.

## Implemented changes

- Removed the eight duplicate guard registrations and made duplicate hook IDs a deterministic initialization error.
- Added exact event subscriptions to the affected guards.
- Added `shadow` and `enforce` modes for outcome learning; `shadow` is the default. Shadow mode preserves task arguments and stores bounded, prompt-free proposal metadata. Disabled mode records nothing.
- Layered gateway config as global home base → project override → explicit plugin options. `MY_OPENCODE_GATEWAY_CONFIG_PATH` remains a deliberate replacement. Arrays replace and nested objects merge; a malformed layer clears itself and lower-precedence sidecar state while allowing a later valid override to rebuild the config.
- Stopped the session wrapper from converting automatic config discovery into an explicit replacement.
- Added normalized `PASS` / `SKIP` / `FAIL` doctor states while preserving raw child results and exit codes. Optional child problems now remain warnings.
- Made disabled auto-slash diagnostics pass with an explicit disabled warning.
- Hardened stale repair with exact session scope in generated commands, deduplicated repair targets, isolated scoped problems, and fixed scope-variable reuse.
- Added runtime-state fallback to delegation health, including per-agent outcomes and shadow/enforced proposal counts without prompt content.
- Added opt-in scenario thresholds and a 100% deterministic workflow gate to CI. LLM scenario correctness now checks both the decision character and its semantic meaning.
- Repaired the two stale parent targets after scoped previews and verified the manual and automatic backups plus the live database with `PRAGMA integrity_check`.
- Tightened the local session-index permission mode from `0644` to `0600`.

## Upstream comparison

The adopted direction matches current maintained harness patterns:

- [OpenCode plugins](https://opencode.ai/docs/plugins/) and [skills](https://opencode.ai/docs/skills/) favor native lifecycle hooks and on-demand skills.
- [Claude Code hooks](https://code.claude.com/docs/en/hooks) and [OpenHands hooks](https://docs.openhands.dev/sdk/guides/hooks) use event-specific matching instead of broadcasting every event.
- [OpenAI Agents tracing](https://openai.github.io/openai-agents-python/tracing/) and [LangSmith evaluation](https://docs.langchain.com/langsmith/evaluation) separate observability from promotion gates.
- [OpenAI human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/) and [OpenHands security](https://docs.openhands.dev/sdk/guides/security) keep enforcement deterministic and reviewable.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) separates thread state from cross-thread memory. This repo keeps the same boundary between runtime state, shared memory, and Codememory.

The audit rejected uncontrolled prompt or code mutation as a default. Self-improvement now means: collect bounded outcomes, generate shadow proposals, evaluate deterministic holdouts, then explicitly promote or roll back a versioned policy.

## Deferred work

These items remain useful but require separate compatibility or data-retention work:

- type the production adapter against the official `@opencode-ai/plugin` contract and remove unsupported/dead hook keys;
- finish indexed event subscriptions for the remaining wildcard hooks and benchmark dispatch cost directly;
- migrate deprecated agent tool declarations to native per-agent permissions;
- replace the hand-written OTLP sender with a batched OpenTelemetry SDK pipeline and attribute allowlist;
- design a previewable runtime-history retention/export command before deleting any of the 4.84GB store;
- add scheduled live-model scenario runs; keep PR gates deterministic and credential-free.

## Validation

Final validation must include the full plugin suite, deterministic workflow gate, Python compile checks, `make validate`, `make selftest`, installer smoke, pre-commit, local path/tarball plugin smoke, runtime doctor, and blocker-first review.
