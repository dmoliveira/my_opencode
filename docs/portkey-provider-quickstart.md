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

## Optional route selection

```bash
export PORTKEY_OPENAI_CONFIG="pc-..."
```

Use a config id from your own Portkey workspace. Reusing ids from other repos/workspaces will return `Invalid config id passed`.

## Smoke check model ids

- `portkey-openai/gpt-5-mini`
- `portkey-openai/gpt-5-nano`
