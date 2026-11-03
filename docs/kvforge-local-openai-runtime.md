# KVForge local OpenAI-compatible runtime

`my_opencode` can point its gateway LLM decision runtime at a KVForge-served local model through native OpenCode provider/model config while keeping the child `opencode run` selector aligned.

This describes the V1 gateway. The V2 gateway and its decision helper are not qualified or enabled by this example.

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

- `allowStandaloneOpencode` permits the helper process; it does not add the V2 `--standalone` flag or prove that a separate service received the child environment.
- A decision is accepted only from a complete, single-session, tool-free JSON event sequence with one non-synthetic, non-ignored text part and a successful stop. Error events or fields, unrecognized events, duplicate keys and incomplete output are rejected rather than cached. This is a post-run check: it cannot prevent tool execution or prove that the stream contains every action. Its 64 KiB limit applies after output collection, not to subprocess memory use.
- Use a native custom-provider model id for the child runtime, for example `kvforge/gpt-5.4-mini`.
- On the KVForge side, set `server.served_model_name` to the same alias, for example `gpt-5.4-mini`.
- KVForge serves an OpenAI-compatible API at `/v1`.
- If your KVForge config does not require an API key, a placeholder like `dummy` is still useful because some OpenAI-compatible clients expect a non-empty key field.
- Start KVForge first, then run the OpenCode flow that exercises the LLM decision runtime.
