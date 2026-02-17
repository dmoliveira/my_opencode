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

3. [ ] Message-injector utility parity (shared helper surface)
   - Pre-check required: inventory current `hook-message-injector` callsites/utilities to avoid duplicate abstractions.

4. [ ] Session-id fallback parity in transform path
   - Pre-check required: inspect current context-injector session id resolution and available session state sources.

5. [ ] Context collector metadata/introspection parity
   - Pre-check required: verify what metadata APIs already exist after source:id dedupe work.

6. [ ] Injector-level truncation/size guards
   - Pre-check required: review existing context truncation safeguards and audit reason codes.

7. [ ] Integration tests for command -> collector -> transform flow
   - Pre-check required: inventory existing integration coverage to extend rather than duplicate.

8. [ ] Injector reason-code granularity
   - Pre-check required: compare current reason-code catalog with desired injector outcome taxonomy.
