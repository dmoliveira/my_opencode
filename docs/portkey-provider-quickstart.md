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
  - `portkey-openai/@azure-openai-useast2-nonprod/gpt-5-mini`
  - `portkey-openai/@azure-openai-useast2-nonprod/gpt-5.3-codex`
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

## Prompt caching

Prompt caching is enabled by default for these Portkey providers through:

```json
"x-portkey-config": "{\"cache\":{\"mode\":\"simple\",\"max_age\":3600}}"
```

Notes:
- First identical request is typically `MISS`; subsequent identical requests become `HIT`.
- To change TTL, edit `max_age` in `opencode.json`.

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
- Increase `minDeltaChars` to skip more small context deltas.
- Set `minDeltaChars: 0` to only skip exact duplicates.
- Keep `dedupeNormalizeWhitespace: true` (default) to treat formatting-only drift as duplicate.

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

### Cache-optimized sidecar profile (recommended baseline)

Use this when your priority is prompt-cache hit rate over strict per-session runtime id injection.

```json
{
  "contextInjector": {
    "dedupeEnabled": true,
    "minDeltaChars": 120,
    "dedupeNormalizeWhitespace": true
  },
  "sessionRuntimeSystemContext": {
    "enabled": true,
    "injectSessionIdContext": false,
    "injectSessionIdWhenConciseModeOnly": false
  }
}
```

Save this in `.opencode/gateway-core.config.json`.

If root `opencode.json` also sets the same keys, root values still win.

Quick rollback profile (strict runtime id semantics):

```json
{
  "sessionRuntimeSystemContext": {
    "enabled": true,
    "injectSessionIdContext": true
  }
}
```
