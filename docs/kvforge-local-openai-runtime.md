# KVForge local OpenAI-compatible runtime

`my_opencode` can point its gateway LLM decision runtime at a KVForge-served local model through native OpenCode provider/model config while keeping the child `opencode run` selector aligned.

## Example gateway config

In `.opencode/gateway-core.config.json`:

```json
{
  "llmDecisionRuntime": {
    "enabled": true,
    "mode": "assist",
    "command": "opencode",
    "model": "kvforge/gpt-5.4-mini",
    "allowStandaloneOpencode": true,
    "env": {}
  }
}
```

If no project-local gateway sidecar exists, `my_opencode` falls back to `~/.config/opencode/my_opencode/gateway-core.config.json` for the same `llmDecisionRuntime` settings.

To expose KVForge as a native custom provider, configure OpenCode root config with provider/model entries such as:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "kvforge": {
      "name": "KVForge",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://127.0.0.1:8000/v1",
        "apiKey": "dummy"
      },
      "models": {
        "gpt-5.4-mini": {
          "name": "gpt-5.4-mini"
        }
      }
    }
  },
  "model": "kvforge/gpt-5.4-mini"
}
```

## Notes

- Use a native custom-provider model id for the child runtime, for example `kvforge/gpt-5.4-mini`.
- On the KVForge side, set `server.served_model_name` to the same alias, for example `gpt-5.4-mini`.
- KVForge serves an OpenAI-compatible API at `/v1`.
- If your KVForge config does not require an API key, a placeholder like `dummy` is still useful because some OpenAI-compatible clients expect a non-empty key field.
- Start KVForge first, then run the OpenCode flow that exercises the LLM decision runtime.
