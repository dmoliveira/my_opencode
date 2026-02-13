# Model Routing Resolution Engine

Epic 5 Task 5.2 implements deterministic settings resolution and integration points.

## Precedence order

1. `system_defaults`
2. category defaults (`quick`, `deep`, `visual`, `writing`)
3. explicit user overrides
4. availability fallback for `model`

## Deterministic fallback logging

`resolve_model_settings(...)` returns a `trace` array with stable steps:

- `system_default`
- `category_default`
- `user_override`
- `availability_fallback` (when needed)

## Integrations

- `stack_profile_command.py`
  - `focus` -> `set-category deep`
  - `research` -> `set-category deep`
  - `quiet-ci` -> `set-category quick`
- `install_wizard.py`
  - new `--model-profile <quick|deep|visual|writing>` option

## Command wrapper

`scripts/model_routing_command.py` provides:

- `status [--json]`
- `set-category <category>`
- `resolve [overrides] [--json]`
