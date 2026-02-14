# Auto Slash Detector Contract

This document defines the Epic 10 intent-mapping contract for `/auto-slash`.

## Goals

- detect high-confidence natural-language intent for existing slash commands
- keep behavior deterministic, explainable, and preview-first
- avoid unsafe surprise execution by default

## Supported command families

- `doctor`: diagnostics and setup health checks
- `stack`: profile switch requests (`focus`, `research`, `quiet-ci`)
- `nvim`: Neovim integration install/status/doctor intents
- `devtools`: tooling install/status/hooks intents

## Detection model

- tokenization ignores inline/fenced code regions
- each command has keyword and phrase signals
- candidate score combines keyword coverage and phrase hits
- selection gates:
  - confidence must be `>= min_confidence` (default `0.75`)
  - top candidate must exceed runner-up by `ambiguity_delta` (default `0.15`)

If any gate fails, detector returns `NOOP` with explicit reason (`low_confidence`, `ambiguous`, `no_match`, or `explicit_slash_present`).

## Execution model

- preview-first by default (`preview_first=true`)
- `/auto-slash execute` without `--force` returns `PREVIEW_ONLY`
- forced execution dispatches backend command and records an audit event
- audit entries are appended to `~/.config/opencode/my_opencode/runtime/auto_slash_audit.jsonl`

## Config shape (`auto_slash_detector`)

```json
{
  "enabled": true,
  "preview_first": true,
  "min_confidence": 0.75,
  "ambiguity_delta": 0.15,
  "enabled_commands": ["doctor", "stack", "nvim", "devtools"],
  "last_detection": null
}
```

## Safety constraints

- global disable toggle (`enabled=false`)
- per-command controls (`enable-command`/`disable-command`)
- explicit slash prompts are never re-routed
- low-confidence/ambiguous prompts never auto-execute

## Validation expectations

- representative precision target: `>= 95%`
- unsafe predictions on `expected=None` prompts: `0`
- doctor output must expose precision, unsafe count, and remediations
