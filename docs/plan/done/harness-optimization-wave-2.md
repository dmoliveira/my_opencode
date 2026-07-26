# Harness Optimization Wave 2

## Objective

Ship three separately validated commits that harden provider-boundary secret handling, remove measurable transform overhead, pin the existing disabled browser integration, and prove the harness with deterministic transport plus realistic model-backed projects in tmux.

## Evidence baseline

- A reproducible built-plugin call recorded `experimental.chat.messages.transform hook_count=86` in the ignored sandbox artifact `runtime/harness-wave-2/dispatch-baseline.jsonl`; the tracked audit will retain the command and result.
- The default secret assignment pattern begins with PCRE-style `(?i)` but is compiled with JavaScript `new RegExp(..., "g")`, so it is silently discarded.
- The semantic summarizer runs after the 12k/220-line truncator but requires 20k/400 lines, making it unreachable under defaults.
- Microsoft `@playwright/mcp@0.0.78` is Apache-2.0 with integrity `sha512-XLTUeA6mEN9sQ+hJ4dfG8EIkDbxS0K3Trc2RBkUJuf02TgE2FQRNTMtq/aJfhyRMINsRl/Ybc4sxcWLtFn4/TQ==`. Keep all six currently used capabilities; pinning and isolation—not capability removal—are the safe enhancement.
- Reviewed community plugins were rejected as default-on dependencies because they duplicate the gateway or expand trusted startup/data-egress surface. The provider-boundary finalizer is the new locally invented capability.

## Durable sequence

### task_2 — Harden provider-boundary secret redaction

1. Centralize pattern compilation; support leading `(?i)`, `(?m)`, and `(?s)` flags and reject malformed patterns using index-only errors.
2. Fix `secret-leak-guard` to redact every supported tool-output channel and declare only `tool.execute.after`.
3. Add a dedicated provider-boundary finalizer outside configurable hook ordering. It runs after all message hooks and auto-slash unwrapping, and after all system hooks. `hooks.order`, `hooks.disabled`, and `hooks.enabled` cannot remove it. Exact config: `secretLeakGuard.providerBoundaryEnabled` defaults to `true`; the finalizer is active only when both `secretLeakGuard.enabled` and `secretLeakGuard.providerBoundaryEnabled` are true. Any compilation, traversal, mutation, or audit exception rejects the transform/provider request.
4. Field policy uses an explicit mutable-path allowlist:
   - redact message `info.system`, summary title/body/diff content, error messages, text/reasoning content, subtask prompt/description, file source text, and tool state input values/output/error/title;
   - treat IDs, roles, types, tool names, provider/model IDs, filenames, URLs, object keys, and opaque metadata as immutable: scan and block dispatch on a configured-pattern match rather than rewriting them;
   - scan unknown string fields and unknown part types, blocking on a match rather than silently passing it;
   - use iterative traversal with cycle/depth/node/text bounds and reject provider dispatch on any exhaustion or unexpected mutation error.
5. Audit only surface, counts, scanned chars/nodes, and reason codes. Never include pattern text or matched plaintext.
6. Add the isolated localhost OpenAI-compatible capture smoke to task_2: fresh HOME/XDG, direct built-plugin shim, fake key/local provider only, request/control marker received, every synthetic canary absent, redaction token/audit present, no raw body retained. Inspect isolated SQLite separately and explicitly report whether plaintext persisted locally.

**task_2 exit:** runtime-shaped fixtures, all channels, inline flags, malformed patterns, immutable/unknown fields, cycles/bounds, generic hooks disabled/order variants, and localhost transport capture all pass.

### task_3 — Reduce transform dispatch overhead (depends on task_2)

1. Before implementation, re-capture the 86-hook baseline with a fixed explicit gateway fixture, isolated HOME/environment, and recorded fixture hash, source/dist commit, command, total count, and selected/actual count in the tracked audit. Then default semantic summarization off and do not construct it while disabled.
2. When explicitly enabled, force it into the effective order before truncation even for empty/legacy/custom hook orders; lower its priority below truncation as the implicit fallback.
3. Add exact `tool.execute.after` subscriptions to summarizer and truncator.
4. Route message/system transform loops through `hooksForEvent`; audit total, selected, and actual loop counts while the security finalizer remains outside that loop.
5. Reproduce the same baseline call and require at least 12 fewer message-transform loop attempts. Rerun the localhost provider capture after routing changes.

**task_3 exit:** disabled construction, implicit/explicit ordering, selected-count audit, transform regression suite, and repeated transport capture pass.

### task_4 — Pin browser tooling and prove E2E (depends on task_3)

1. Centralize Playwright defaults at `@playwright/mcp@0.0.78`, add `--isolated`, and preserve all current `testing,network,storage,vision,devtools,pdf` capabilities.
2. Migrate only exact known legacy `@latest` defaults. Preserve custom commands/args and emit doctor warnings instead of rewriting them.
3. Doctors report package spec, pinned state, isolation state, legacy arguments, and capability coverage. Keep MCP disabled.
4. In tmux, run a real MCP `initialize` and `tools/list` probe against the pinned command.
5. In tmux, run fixed no-dependency Python and Node fixtures with exact model `openai/gpt-5.4-mini`; the build agent must edit implementation only, run native tests, and leave both green. Each fixture uses an isolated config with a direct shim to the worktree `dist/index.js`, no installed gateway entry, and an explicit audit path. Require `gateway_runtime_bootstrap`, candidate source/dist hash evidence, exactly one gateway plugin source, the observed exact model, and native tests green. Model/auth preflight failure is a concrete blocker, not a silent substitution.

**task_4 exit:** provenance, legacy/custom migration tests, MCP inventory, exact-model E2E, pane capture, bounded timeout, artifact secret scan, and session cleanup pass.

## File scope

- `plugin/gateway-core/src/{index.ts,config/schema.ts,config/load.ts}`
- `plugin/gateway-core/src/hooks/{secret-leak-guard,semantic-output-summarizer,tool-output-truncator}/**`
- `plugin/gateway-core/src/hooks/shared/secret-redaction.ts`
- Corresponding tests and generated `dist/**`
- `scripts/{playwright_defaults.py,mcp_command.py,browser_command.py,gateway_secret_redaction_live_smoke.py,selftest.py}`
- `opencode.json`, `Makefile`, focused browser/security docs, tracked wave audit, and this plan

## Safety constraints

- Synthetic secrets only. Never print, retain, or audit matched plaintext or raw provider request bodies.
- Provider-boundary redaction prevents configured plaintext patterns from future egress; it does not erase local DB, logs, snapshots, or prior artifacts and does not claim universal secret detection.
- Do not edit `.opencode/gateway-core.config.json`; main has overlapping user-authored settings. Record its hash before/after.
- Do not disable primary-worktree/workflow-conformance guards.
- Do not install new community runtime plugins or enable Playwright by default.
- Use the isolated direct-plugin pattern, not installed-dist replacement, for the security smoke.

## Validation gates

1. Targeted TypeScript/Python tests, build/lint/ruff/compile, JSON validation, package provenance, and MCP protocol probe.
2. Full gateway tests, `make validate`, `make selftest`, workflow scenarios, direct bootstrap, doctors, pre-commit, and committed-clone install test.
3. Tmux session `ai-oc-harness-wave2`: capture baseline, transport smoke, pinned MCP inventory, and exact-model Python/Node project runs.
4. Run 3–5 changed-evidence review/fix cycles for this high-risk slice; never duplicate review on unchanged evidence.
5. Use separate validated commits for task_2, task_3, and task_4, then PR/CI/overlap/squash merge, Codememory export/close, worktree cleanup, and main autostash-sync preserving user changes.

## Rollback

Revert the focused commits. Playwright remains disabled. Provider-boundary handling can be explicitly disabled only through its security config, and summarizer behavior can be restored by enabling it; effective ordering remains pre-truncation.

## Deferred

- Remaining wildcard-hook migration.
- Retroactive DB/log/snapshot secret scrubbing.
- README/workflow guard changes overlapping user state.
- External context-pruning, cloud sandbox, telemetry, or broad agent-suite plugins.
- Credential-backed CI model calls.
