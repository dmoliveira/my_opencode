# Generic connect/models workflow for KVForge

When KVForge is serving a local OpenAI-compatible vLLM server, OpenCode can discover and wire it through the generic slash surface.

## Flow

1. Start KVForge normally.
2. In OpenCode, run:

```text
/models
/connect
```

If more than one discovered KVForge server exists:

```text
/connect --name kvforge-gpt-5-4-mini
/connect --model openai/gpt-5.4-mini
```

`/connect` writes the gateway runtime config automatically using the selected discovered server.

## Notes

- KVForge should expose a `served_model_name` alias OpenCode recognizes, e.g. `gpt-5.4-mini`.
- `/models` lists both running and stale discovered entries, with `running: true|false` in the JSON form.
