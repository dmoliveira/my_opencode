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
- for a match, `preview_first=true` makes `/auto-slash execute` without `--force` return `PREVIEW_ONLY`; when it is false, execution can proceed without `--force`
- a matched execution dispatches the backend and records an audit event if preview is bypassed or disabled
- audit entries are appended to `~/.config/opencode/my_opencode/runtime/auto_slash_audit.jsonl`

**Safety hold:** Do not execute prompts that route to held background diagnostics
or ast-grep installation. A devtools install intent without a recognized target
can resolve to `install all`, which includes ast-grep. `/doctor` accesses the
background store. `/auto-slash doctor --json` may suggest executing `/doctor`;
disregard that suggestion when background state must be preserved. See
`docs/command-handbook.md` for current restrictions.

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
