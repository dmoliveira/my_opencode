# KVForge discovery workflow

`my_opencode` can discover a live KVForge server from `~/.kvforge/server.json` and wire the gateway LLM decision runtime automatically.

## Flow

1. Start KVForge normally (`make wizard` or `uv run kvforge up ...`).
2. In OpenCode, run:

```text
/kvforge status
/kvforge models
/kvforge connect
```

`/kvforge connect` updates `.opencode/gateway-core.config.json` with:

- `llmDecisionRuntime.enabled = true`
- `llmDecisionRuntime.command = opencode`
- `llmDecisionRuntime.allowStandaloneOpencode = true`
- `llmDecisionRuntime.model = openai/<served_model_name>`
- `llmDecisionRuntime.env.OPENAI_BASE_URL = http://127.0.0.1:<port>/v1`
- `llmDecisionRuntime.env.OPENAI_API_KEY = dummy`

## Notes

- The KVForge server should expose a `served_model_name` alias that OpenCode recognizes, for example `gpt-5.4-mini`.
- `/kvforge connect --name my-local-llm` lets you store a friendlier local connection label in config metadata.
