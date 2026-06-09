# Portkey provider quickstart (OpenCode)

`opencode.json` now includes an optional `portkey-openai` provider for smoke-testing small OpenAI-family models through Portkey, without changing the repo default model.

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
```

The current workspace returns zero config routes (`/v1/configs`), so `x-portkey-config` is not usable here. Use `x-portkey-virtual-key` instead.

Quick discovery command:

```bash
curl -fsS "https://api.portkey.ai/v1/virtual-keys" \
  -H "x-portkey-api-key: ${PORTKEY_API_KEY}" \
  -H "accept: application/json" \
  -H "user-agent: Mozilla/5.0"
```

Pick an active OpenAI/Azure OpenAI-backed virtual key id from that response.

## Smoke check model ids

- `portkey-openai/@azure-openai-useast2-nonprod/gpt-5-mini`
- `portkey-openai/@azure-openai-useast2-nonprod/gpt-5-nano`
