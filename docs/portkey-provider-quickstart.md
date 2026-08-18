# Portkey provider quickstart (OpenCode)

`opencode.json` now includes optional `portkey-openai`, `portkey-claude`, and `portkey-gemini` providers for smoke-testing current models through Portkey, without changing the repo default model.

## Required env

```bash
export PORTKEY_API_KEY="..."
```

If your shell/runtime currently exposes `PORTKEYAI_API_KEY`, map it once before running OpenCode:

```bash
export PORTKEY_API_KEY="$PORTKEYAI_API_KEY"
```

## Required Portkey route selection (virtual key)

```bash
export PORTKEY_OPENAI_VIRTUAL_KEY="<virtual-key-id>"
export PORTKEY_OPENAI_FOUNDRY_VIRTUAL_KEY="<virtual-key-id>"
export PORTKEY_CLAUDE_VIRTUAL_KEY="<virtual-key-id>"
export PORTKEY_GEMINI_VIRTUAL_KEY="<virtual-key-id>"
```

The current workspace returns zero **saved config routes** (`/v1/configs`), so `x-portkey-config: pc-...` ids are not usable here. Use `x-portkey-virtual-key` for routing.

Quick discovery command:

```bash
curl -fsS "https://api.portkey.ai/v1/virtual-keys" \
  -H "x-portkey-api-key: ${PORTKEY_API_KEY}" \
  -H "accept: application/json" \
  -H "user-agent: Mozilla/5.0"
```

Pick active virtual key ids by family (OpenAI, Claude/Bedrock, Gemini/Vertex).

## Added model sets (tested)

- OpenAI (reliability-curated)
  - `portkey-openai/@azure-openai-useast2-nonprod/gpt-5.6-luna`
  - `portkey-openai/@azure-openai-useast2-nonprod/gpt-5.6-terra`
  - `portkey-openai/@azure-openai-useast2-nonprod/gpt-5.6-sol`
- OpenAI Foundry (alternative route, reliability-curated)
  - `portkey-openai-foundry/@azure-foundry-useast2-nonprod/gpt-5-mini`
- Claude
  - `portkey-claude/@bedrock-use1-nonprod/global.anthropic.claude-opus-4-8`
  - `portkey-claude/@bedrock-use1-nonprod/global.anthropic.claude-opus-4-7`
  - `portkey-claude/@bedrock-use1-nonprod/global.anthropic.claude-opus-4-6-v1`
  - `portkey-claude/@bedrock-use1-nonprod/global.anthropic.claude-sonnet-4-6`
  - `portkey-claude/@bedrock-use1-nonprod/global.anthropic.claude-sonnet-4-5-20250929-v1:0`
  - `portkey-claude/@bedrock-use1-nonprod/global.anthropic.claude-haiku-4-5-20251001-v1:0`
- Gemini
  - `portkey-gemini/@vertex-ai-global-nonprod/gemini-3.5-flash`
  - `portkey-gemini/@vertex-ai-global-nonprod/gemini-3.1-pro-preview`
  - `portkey-gemini/@vertex-ai-global-nonprod/gemini-3.1-flash-lite-preview`
  - `portkey-gemini/@vertex-ai-global-nonprod/gemini-2.5-pro`
  - `portkey-gemini/@vertex-ai-global-nonprod/gemini-2.5-flash`
  - `portkey-gemini/@vertex-ai-global-nonprod/gemini-2.5-flash-lite`

## Response caching and provider prompt caching

Portkey response caching is enabled by default for these providers through:

```json
"x-portkey-config": "{\"cache\":{\"mode\":\"simple\",\"max_age\":3600}}"
```

Notes:
- This is an exact-response cache: the first identical request is typically `MISS`; subsequent identical requests become `HIT`.
- To change TTL, edit `max_age` in `opencode.json`.
- It does **not** make changing agent conversations cheaper. Provider prompt caching is separate and needs provider-specific request support and usage telemetry.

For all providers, keep reusable instructions and tools at the start of the request, and append session, user, tool, and changing repository context afterwards.

| Provider family | Prompt-cache behavior | Gateway guidance |
| --- | --- | --- |
| OpenAI / Azure OpenAI | Exact common prefixes are cacheable; supported API routes may use a stable `prompt_cache_key`. | Keep repo-level policy stable and use a repo/provider/model-scoped key only when the active route supports it. |
| Anthropic / Bedrock Claude | Explicit cache breakpoints (`cache_control`) cache tools, system blocks, and message prefixes. | Keep stable rules and local instructions before session-specific context; configure breakpoints in the provider adapter, not the generic Portkey response-cache header. |
| Gemini / Vertex | Gemini 2.5+ can implicitly cache repeated prefixes; explicit cached content has its own TTL. | Reuse stable leading instructions and avoid per-turn context duplication. |

Before claiming savings, collect provider usage fields for input, cache-read, and cache-write tokens. Portkey response-cache hits alone are not evidence of prompt-cache savings.

The implementation evidence and dynamic-hook review are recorded in
`docs/prompt-cache-dynamic-injection-audit-2026-07-28.md`.

## Rate-limit mitigation for OpenAI route

OpenCode may issue a hidden `title` generation request using the configured `small_model` before/around the main `build` request. If both share the same constrained OpenAI virtual key, you can see intermittent `too_many_requests` even on early turns.

This repo sets:

```json
"small_model": "portkey-gemini/@vertex-ai-global-nonprod/gemini-2.5-flash-lite"
```

That shifts hidden small-model traffic to the Gemini virtual key and reduces contention on `PORTKEY_OPENAI_VIRTUAL_KEY`.

### Codex routing note

In this workspace, Codex routes responded successfully on the Portkey `/v1/responses` API. The same routes returned `The requested operation is unsupported` on `/v1/chat/completions`, so behavior in OpenCode depends on which OpenAI API surface the active client path uses.

### OpenAI reliability curation note

OpenAI and Foundry model lists in `opencode.json` are intentionally curated to known-working routes here. This reduces model-selection failures in `/models` when virtual-key backends expose mixed support.

### Azure OpenAI vs Azure Foundry note

In current tests for `gpt-5-mini`, both `azure-openai-useast2-nonprod` and `azure-foundry-useast2-nonprod` returned the same rate-limit headers (`10 RPM`, `10000 TPM`). Foundry is now enabled as an alternative route, but it may not improve throttling unless backend limits differ in your workspace.

### Context-injector cache tuning (toggle)

To reduce cache misses from tiny synthetic-context drift, gateway now supports context-injector dedupe controls.

Create or edit `.opencode/gateway-core.config.json`:

```json
{
  "contextInjector": {
    "dedupeEnabled": true,
    "minDeltaChars": 120,
    "dedupeNormalizeWhitespace": true
  }
}
```

If you also define `contextInjector` in repo-root `opencode.json`, root config values take precedence over sidecar defaults.

- Set `dedupeEnabled: false` to disable dedupe quickly.
- Increase `minDeltaChars` only with stale-context tests: differences below the
  threshold are consumed rather than deferred.
- Set `minDeltaChars: 0` to only skip exact duplicates.
- Keep `dedupeNormalizeWhitespace: true` (default) to treat formatting-only drift as duplicate.

### Stable OpenAI cache routing (default)

The gateway replaces only OpenCode's session-scoped default
`prompt_cache_key`. Custom, absent, non-string, conflicting-provider, and
non-OpenAI keys are preserved.

```json
{
  "promptCache": {
    "stableKeyEnabled": true,
    "shardCount": 1
  }
}
```

- `stableKeyEnabled: true` is the default.
- Linked Git worktrees share a hashed repository scope; paths and cache keys are
  not written to gateway audit.
- Keep one shard until measured traffic approaches OpenAI's per-key routing
  guidance. Valid values are integers from `1` through `64`.
- Set `stableKeyEnabled: false` and restart OpenCode to restore the upstream
  session key.

### Session runtime context cache tuning (toggle)

To reduce cross-session cache fragmentation, you can disable runtime session-id system context injection while keeping concise-mode behavior.

```json
{
  "sessionRuntimeSystemContext": {
    "enabled": true,
    "injectSessionIdContext": false,
    "injectSessionIdWhenConciseModeOnly": false
  }
}
```

- `injectSessionIdContext: true` (default): preserve strict runtime session-id guidance in system prompt.
- `injectSessionIdContext: false`: remove that per-session marker from system prompt to improve cache reuse across sessions.
- `injectSessionIdWhenConciseModeOnly: true`: inject runtime session-id context only when concise mode context is active.
- Restart OpenCode after saving these settings.

### Cache-optimized sidecar profile (recommended baseline)

Use this when your priority is prompt-cache hit rate over strict per-session runtime id injection.

```json
{
  "contextInjector": {
    "dedupeEnabled": true,
    "minDeltaChars": 120,
    "dedupeNormalizeWhitespace": true
  },
  "promptCache": {
    "stableKeyEnabled": true,
    "shardCount": 1
  },
  "sessionRuntimeSystemContext": {
    "enabled": true,
    "injectSessionIdContext": false,
    "injectSessionIdWhenConciseModeOnly": false
  }
}
```

Save this in `.opencode/gateway-core.config.json`, then restart OpenCode.

If root `opencode.json` also sets the same keys, root values still win.

Quick rollback profile (strict runtime id semantics):

```json
{
  "promptCache": {
    "stableKeyEnabled": false,
    "shardCount": 1
  },
  "sessionRuntimeSystemContext": {
    "enabled": true,
    "injectSessionIdContext": true,
    "injectSessionIdWhenConciseModeOnly": false
  }
}
```

Restart OpenCode after applying the rollback profile.
