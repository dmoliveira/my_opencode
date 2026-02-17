# Injection Parity Tracker

Tracks command/context parity work versus `oh-my-opencode` in execution order.
Each item requires: pre-check existing implementation, WT flow delivery, tests, review, PR, merge, cleanup, and main sync.

## Status Legend

- [ ] pending
- [~] in progress
- [x] completed

## Ordered Items

1. [x] Auto-slash-command parity (detector + `command.execute.before` behavior)
   - Pre-check: existing lightweight natural-language rewrite exists.
   - Gaps addressed in this run: tagged injection wrapping, explicit slash parsing hygiene, `command.execute.before` injection path, excluded command handling, safety hardening (no high-risk install rewrites), and doctor slash rendering parity (`/doctor` instead of `/doctor run`).

2. [x] Compaction-context injector parity
   - Pre-check completed: `preemptive-compaction` exists and triggers summarize, but no dedicated compaction-context prompt injector hook existed in gateway-core.
   - Delivered: added `compaction-context-injector` hook, wired config/defaults, ensured compatibility with `auto-slash-command` across default and custom hook orders, and added dedicated test coverage.

3. [x] Message-injector utility parity (shared helper surface)
   - Pre-check completed: helper previously exposed only `injectHookMessage` and was used by `continuation` + `session-recovery`; no reusable identity/body utility surface existed.
   - Delivered: added shared `resolveHookMessageIdentity` + `buildHookMessageBody` utilities, refactored `injectHookMessage` to use them, and added split-metadata regression tests.

4. [x] Session-id fallback parity in transform path
   - Pre-check completed: context-injector resolved session from payload/message metadata only; no fallback to last known active session id when transform payload omitted session identity.
   - Delivered: context-injector now falls back to the last known active session id for transform payloads with missing session identity, clears fallback state on matching `session.deleted`, and includes regression test coverage for transform fallback behavior.

5. [x] Context collector metadata/introspection parity
   - Pre-check completed: collector supported source:id dedupe and consume, but lacked upstream-like introspection (`getPending().entries`) and metadata passthrough on entries/options.
   - Delivered: added `getPending()` with structured `entries` introspection, added optional metadata on register/entry records, aligned `consume()` with pending-context shape while preserving compatibility, and expanded collector tests for empty shape, metadata roundtrip, and session-isolated consume behavior.

6. [x] Injector-level truncation/size guards
   - Pre-check completed: injector entry points had no size guard and injected pending/ synthetic context verbatim; only tool-output truncation had max-char protections.
   - Delivered: added shared injected-text truncator with bounded output, applied max-char guards to context-injector and hook-message-injector paths, added truncation audit reason codes for chat/transform injections, and expanded tests for oversized and tiny-limit truncation behavior.

7. [x] Integration tests for command -> collector -> transform flow
   - Pre-check completed: hook-level tests existed for command parsing, collector behavior, and transform injection independently, but end-to-end plugin tests covering command/slashcommand -> collector registration -> transform injection chain were missing.
   - Delivered: added integration tests for tool-command and command.execute.before producer paths into collector, negative non-start flow, and one-shot consume behavior across repeated transform calls.

8. [x] Injector reason-code granularity
   - Pre-check completed: injector hooks emitted coarse reason-code coverage (mostly injected-only) with missing granular outcomes for requeue/missing-user/duplicate-context suppression paths.
   - Delivered: expanded injector reason-code taxonomy in shared catalog, wired granular context-injector and compaction-context-injector outcomes (inject, truncate, requeue, duplicate, missing-user, missing-parts), and added audit-backed tests for the new branches.

## Next Batch (Friendly Names)

9. [x] Smart file-rule injector parity
   - Pre-check completed: local rules injector used static per-tool text and lacked file-aware rule discovery, frontmatter matching, and session-compaction cache reset behavior.
   - Delivered: added file-aware rule discovery from common rule directories, frontmatter `applyTo` matching (scalar/inline-array/yaml-list), copilot always-apply support, title/metadata file-path resolution, session dedupe with compaction reset, and expanded integration tests including brace-glob matching.

10. [x] Session guidance + continuation helpers parity
   - Pre-check completed: no direct upstream hook files were available in this checkout, so parity was mapped to local analogs (`agent-user-reminder` and `task-resume-info`) with stronger session-aware guidance and continuation behavior.
   - Delivered: upgraded reminders to session-aware guidance with dedupe/reset on session lifecycle events, strengthened continuation hints for pending loop output, and added comprehensive tests for one-time reminder behavior, compaction reset, continuation hinting, and duplicate suppression.

11. [x] Thought workflow guardrails parity
   - Pre-check completed: no direct upstream implementation files were present in the current checkout, so parity is being delivered through local hook additions (`think-mode` and `thinking-block-validator`) aligned to the documented guardrail goal.
   - Delivered: added session-aware `think-mode` guidance with lifecycle reset semantics, added `thinking-block-validator` for malformed/misordered thinking tags across text parts, wired both hooks into config/loading/default order, and added dedicated hook + config tests.

12. [x] Directory guidance depth parity
    - Pre-check completed: directory AGENTS/README injectors only appended nearest file paths and did not inject file content.
    - Delivered: injectors now append truncated AGENTS/README content excerpts (with path context), added configurable `maxChars` knobs with safe defaults and normalization, and expanded tests for content injection and truncation behavior.

## Next Batch Refresh (Post-12 Gap Scan)

13. [x] Todo-driven continuation enforcer parity
    - Pre-check completed: local continuation flow supports loop state and stop guards, but does not enforce pending todo-driven continuation semantics with upstream-like idle/cooldown behavior. Confirmed on current main there is no existing `todo-continuation-enforcer` hook/config wiring.
    - Delivered: added `todo-continuation-enforcer` hook with pending-marker tracking from task output, idle-time continuation injection with cooldown and failure budget, stop-guard + active-loop skip behavior, config/default/order wiring, and dedicated hook/config regression tests.

14. [x] Compaction todo snapshot restore parity
    - Pre-check completed: local compaction flow preserves context excerpts, but no dedicated compaction todo snapshot/restore hook was found. Confirmed on latest main there is no existing `compaction-todo-preserver` hook/config wiring.
    - Delivered: added `compaction-todo-preserver` hook that snapshots pending todo task output (`<CONTINUE-LOOP>` marker), restores snapshot guidance after `session.compacted`, clears snapshot state on `session.deleted`, and wires config/default/order + dedicated tests.

15. [x] Non-interactive env prefix injection parity
    - Pre-check completed: local noninteractive shell guard blocks risky interactive commands, but does not prepend non-interactive env prefixes to compatible shell commands. Confirmed on latest main there is no existing env-prefix injection path in `noninteractive-shell-guard`.
    - Delivered: added non-interactive env prefix injection for configured bash command prefixes (`git`/`gh` by default), preserved existing interactive-command blocking semantics, added config/load/default wiring (`injectEnvPrefix`, `envPrefixes`, `prefixCommands`), and expanded regression tests for prefix insertion and non-duplication.

16. [ ] Tool error recovery nudges parity (edit + JSON)
    - Pre-check completed: local gateway has generic continuation/session recovery hooks, but no dedicated edit-error/json-error recovery nudges were found.
    - Goal: add focused recovery guidance hooks for edit failures and JSON parse failures.

17. [ ] Provider token-limit auto-recovery parity
    - Pre-check completed: local context-window monitoring and preemptive compaction are proactive, but no provider-specific error-triggered token-limit recovery hook was found.
    - Goal: add provider token-limit recovery handling on error/update events with safe compact/truncation fallback.

18. [ ] Hashline read stability enhancer parity
    - Pre-check completed: local tool output processing covers truncation, but no hashline read enhancer equivalent was found.
    - Goal: evaluate and, if in-scope, add hashline read-output stabilization to improve deterministic follow-up reads.
