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

11. [ ] Thought workflow guardrails parity
   - Goal: align think-mode and thinking-block validator behavior for safer reasoning flows.

12. [ ] Directory guidance depth parity
   - Goal: move from path-notice injection toward richer AGENTS/README content injection with safe truncation.
