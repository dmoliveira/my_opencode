# Dynamic injection and prompt-cache audit — 2026-07-28

## Conclusion

Dynamic gateway hooks are not currently causing a broad same-session cache
failure. Across recent repository sessions, 97.0% of assistant turns reported a
provider cache read. The material gap is at the first turn of a new session:
only 0–2.8% of first turns reported a cache read, depending on model.

Two early-prefix issues are worth fixing:

1. OpenCode `1.18.5` routes OpenAI prompt caching with the runtime session ID,
   preventing useful affinity between otherwise identical new sessions.
2. Long reusable concise-mode guidance is emitted after the unique runtime
   session block, shortening the exact prefix reusable by providers without a
   caller cache key.

Most other dynamic hooks mutate the current user message, newest tool result,
or synthetic continuation tail. Those additions increase tokens but do not
invalidate an already cached prefix, so this slice leaves them unchanged.
First-turn rates include prompts below the 1,024-token eligibility threshold;
the comparison is an operational baseline, not a causal estimate of avoidable
misses.

## Runtime evidence

Source: read-only queries against the local OpenCode `message` and `session`
tables. Window: the 48 hours ending 2026-07-28. Scope: sessions whose directory
starts with the repository path. An assistant turn counts as a cache hit when
`message.data.tokens.cache.read > 0`.

| Population | Turns | Turns with cache read | Hit rate |
| --- | ---: | ---: | ---: |
| All assistant turns | 6,900 | 6,693 | 97.0% |
| First turn, `openai/gpt-5.6-sol` | 64 | 1 | 1.6% |
| First turn, `openai/gpt-5.4-mini` | 36 | 1 | 2.8% |
| First turn, `openai/gpt-5.4` | 35 | 0 | 0.0% |

The seven-day normalized token view tells the same story for established
sessions. `cache.read / (input + cache.read)` was 96.4% for GPT-5.6 Sol, 90.1%
for GPT-5.4 Mini, and 88.9% for GPT-5.4. These are provider-reported usage
fields, not gateway fingerprints or HTTP response-cache hits.

Reproducible first-turn query shape:

```sql
WITH ranked AS (
  SELECT
    m.session_id,
    m.time_created,
    m.data,
    row_number() OVER (
      PARTITION BY m.session_id
      ORDER BY m.time_created, m.id
    ) AS rn
  FROM message AS m
  JOIN session AS s ON s.id = m.session_id
  WHERE json_extract(m.data, '$.role') = 'assistant'
    AND m.time_created >= (strftime('%s', 'now', '-2 days') * 1000)
    AND s.directory LIKE '<repo-path>%'
)
SELECT
  json_extract(data, '$.providerID') AS provider,
  json_extract(data, '$.modelID') AS model,
  count(*) AS first_turns,
  sum(CASE
    WHEN coalesce(json_extract(data, '$.tokens.cache.read'), 0) > 0
    THEN 1 ELSE 0
  END) AS first_turn_cache_hits
FROM ranked
WHERE rn = 1
GROUP BY provider, model;
```

## Injection review

| Surface | Dynamic inputs | Cache effect | Decision |
| --- | --- | --- | --- |
| Stable rules, `AGENTS.md`, `README.md`, Codex guidance | File content and model | Stable until source changes | Keep before runtime markers |
| Concise-mode system guidance | Mode, source, skill body | Reusable across sessions when unchanged | Move before session context |
| Runtime session context | Session ID | Unique every session | Keep last among managed system blocks |
| Context and Codex message injection | Current-turn context | Tail-only | Keep |
| Tool-result reminders and recovery | Counters, pressure, git state, retries | Newest tool-result tail | Keep; audit verbosity separately |
| Delegated task headers | Trace UUID, parent session, worktree, routing | High-entropy child-prompt prefix | Defer; parser/lifecycle risk is higher |

The direct mutation inventory behind this classification is:

- `session-runtime-system-context`, `rules-injector`,
  `directory-agents-injector`, `directory-readme-injector`, and
  `codex-header-injector` consume the system transform. The rules, directory,
  and Codex blocks use stable insertion before managed runtime markers.
- `auto-slash-command`, `context-injector`, `codex-header-injector`,
  `think-mode`, `thinking-block-validator`, and `agent-user-reminder` mutate
  the current user-message parts. `compaction-context-injector` does the same
  for a summarize command.
- `assistant-message-timestamp`, plus fallback paths in `context-injector` and
  `codex-header-injector`, consume the messages transform. They update message
  history or the newest applicable message, after the system prefix.
- Pressure, retry, continuation, validation, and task-lifecycle hooks append
  reminders to the newest tool result or create a new continuation message.
  None insert content ahead of the system prompt.

> **Correction — 2026-08-04:** `assistant-message-timestamp` no longer consumes
> the messages transform. Transform-time timestamps mislabeled stored assistant
> replies and introduced avoidable dynamic provider input. The opt-in hook now
> decorates only terminal/lifecycle output; the `context-injector` and
> `codex-header-injector` fallback paths remain provider-visible. The validation
> table below records the original 2026-07-28 slice, not this correction.

> **Delegation correction — 2026-08-04:** `agent-model-resolver` now keeps
> resolved agent/category/trace identity in task arguments, gateway metadata,
> and audit events instead of repeating model, tool, parent-session, worktree,
> and inferred-router prose in the child provider prompt. The trace marker
> remains for lifecycle/fallback compatibility, and `agent-context-shaper`
> retains one bounded focus line. In the named fixed fixture (`explore`,
> `/workspace/project`, `session-parent`, `trace-fixed`, and `Inspect code
> paths`), resolver-generated provider input falls from 497 to 32 characters:
> 465 fewer characters (93.6%). The composed fixed fixture has 208 generated
> characters after the focus line is included. This is a direct input-size
> reduction; it does not claim a cache-hit or provider-budget improvement.
> Telemetry reason code `agent_model_routing_hint_injected` is replaced by
> `agent_model_routing_resolved`, with `resolver_prompt_context=trace_only`.

> **Runtime-context correction — 2026-08-04:** The default `lite` managed
> context now substitutes a versioned compact runtime contract only for the
> built-in fallback or the exact reviewed canonical concise-skill fingerprint.
> Unknown/custom bodies fail open to passthrough, while `review`/`commit`, mode
> precedence, off behavior, reloads, managed ordering, and the session cache
> boundary remain unchanged. In the fixed canonical + `session-fixed` fixture,
> concise/session context falls from 1,548 to 656 characters: 892 fewer (57.6%).
> The mode source remains in state/audit rather than provider prose. This is a
> recurring input/context reduction, not evidence of cache-hit, latency, cost,
> or provider-budget improvement.

Do not raise `contextInjector.minDeltaChars` solely to chase cache hits. Small
differences below that threshold are consumed, so an aggressive threshold can
silently discard relevant context.

## Implemented improvements

### Stable OpenAI routing key

The gateway replaces only OpenCode's upstream default key when all of these are
true:

- stable-key routing is enabled;
- the model provider is exactly `openai` and the provider identity is absent or
  also `openai`;
- the current key is a string exactly equal to the runtime session ID; and
- scope, model, agent, and session inputs are complete.

The key is a bounded, privacy-safe routing hint:

```text
ocpc-v1:<24-hex-scope-digest>:n<shard-count>:s<session-shard>
```

The scope hashes the Git common directory, provider, model, and normalized
agent. Linked worktrees therefore share routing affinity without exposing local
paths. The default is one shard; increase only after measured traffic approaches
OpenAI's approximately 15 requests/minute-per-key guidance. Exact prompt-token
matching still controls cache reuse, so the key is not authorization, response
caching, or a cache-poisoning trust boundary.

Rollback requires a restart after setting:

```json
{
  "promptCache": {
    "stableKeyEnabled": false,
    "shardCount": 1
  }
}
```

### Stable managed system order

Managed blocks are recognized only when their first line begins with an exact
runtime marker. Duplicate or stale managed blocks are rebuilt in this order:

```text
stable provider/repository guidance
runtime_concise_mode
runtime_session_context
```

Unmanaged text that merely mentions a marker later in the block is preserved.
Instruction authority is unchanged; only order within gateway-managed system
content changes.

### Privacy-safe measurement

After all system transforms and provider-boundary redaction, the gateway records
a local `prompt_cache_prefix_observed` event containing an exact SHA-256 of
`JSON.stringify(cacheableSystemPrefix)`, entry/character counts, and whether the
session marker was present. The cache key, scope identity, scope digest, and path
are never included. These fields are not in the OTLP attribute allowlist.

## Provider constraints

- OpenAI requires exact initial-prefix matches and starts automatic caching at
  1,024 prompt tokens. GPT-5.6 uses `prompt_cache_key` for its more reliable
  matching, reports cache writes separately, and bills writes at 1.25 times the
  uncached input rate. Source:
  <https://developers.openai.com/api/docs/guides/prompt-caching>.
- Anthropic requires exact content through an explicit breakpoint; its serialized
  order is tools, system, then messages. Source:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>.
- Gemini implicit caching favors large common prefixes but does not publish an
  exact matching or routing-key contract. Source:
  <https://ai.google.dev/gemini-api/docs/generate-content/caching>.

## Validation evidence

Validated from the candidate worktree on 2026-07-28:

| Check | Result |
| --- | --- |
| Gateway TypeScript build and lint | PASS |
| Focused config, routing, runtime-order, audit-security tests | 56/56 PASS |
| Full gateway Node suite | 801/801 PASS |
| `make validate` | 216 Python tests PASS, 1 skipped; repository checks PASS |
| `make selftest` and `make install-test` | PASS |
| `pre-commit run --all-files` | PASS |
| Native `gateway-resume-redaction-e2e` with OpenCode `1.18.5` | PASS |

The native E2E captured `/v1/responses`, verified the stable wire key and local
audit fields, rejected cache key/scope disclosure, preserved a history larger
than 2 MiB, retained reasoning ciphertext, redacted the mutable secret, and
removed its sandbox.

## Follow-up criteria

After deployment and restart, compare at least seven days of provider usage:

- first-turn cache-hit rate by provider/model;
- same-session cache-hit rate, which should remain at or above the current 95%
  operating floor;
- cached-token share and cold-write frequency; and
- rate-limit or latency changes by configured shard count.

Delegation-header reordering should remain a separate task. It spans trace
parsers, lifecycle supervision, fallback policy, and external tooling, and its
benefit should be measured after the stable routing key is active.
