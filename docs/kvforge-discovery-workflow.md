# KVForge discovery workflow

`my_opencode` can discover a live KVForge server from `~/.kvforge/server.json` and `~/.kvforge/servers/*.json`, then wire the gateway LLM decision runtime automatically.

## Flow

1. Start KVForge normally (`make wizard` or `uv run kvforge up ...`).
2. In OpenCode, run:

```text
/kvforge status
/kvforge models
/kvforge connect
```

When more than one KVForge server record exists, select one explicitly:

```text
/kvforge connect --name kvforge-gpt-5-4-mini
/kvforge connect --model openai/gpt-5.4-mini
```

`/kvforge connect` updates `.opencode/gateway-core.config.json` with:

- `llmDecisionRuntime.enabled = true`
- `llmDecisionRuntime.command = opencode`
- `llmDecisionRuntime.allowStandaloneOpencode = true`
- `llmDecisionRuntime.model = openai/<served_model_name>`
- `llmDecisionRuntime.env.OPENAI_BASE_URL = http://127.0.0.1:<port>/v1`
- `llmDecisionRuntime.env.OPENAI_API_KEY = dummy`

## Notes

- KVForge should expose a `served_model_name` alias that OpenCode recognizes, for example `gpt-5.4-mini`.
- The default no-flag `/kvforge connect` path uses the current live server when only one is running.
