# KVForge local OpenAI-compatible runtime

`my_opencode` can now point its gateway LLM decision runtime at a KVForge-served local model by passing a small environment overlay into the child `opencode run` process.

## Example gateway config

In `.opencode/gateway-core.config.json`:

```json
{
  "llmDecisionRuntime": {
    "enabled": true,
    "mode": "assist",
    "command": "opencode",
    "model": "openai/gpt-5.4-mini",
    "allowStandaloneOpencode": true,
    "env": {
      "OPENAI_BASE_URL": "http://127.0.0.1:8000/v1",
      "OPENAI_API_KEY": "dummy"
    }
  }
}
```

## Notes

- Use an OpenCode-known OpenAI model id for the child runtime, for example `openai/gpt-5.4-mini`.
- On the KVForge side, set `server.served_model_name` to the same alias, for example `gpt-5.4-mini`.
- KVForge serves an OpenAI-compatible API at `/v1`.
- If your KVForge config does not require an API key, a placeholder like `dummy` is still useful because some OpenAI-compatible clients expect a non-empty key field.
- Start KVForge first, then run the OpenCode flow that exercises the LLM decision runtime.
