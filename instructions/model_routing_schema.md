# Category Routing Schema

Epic 5 Task 5.1 defines the baseline category model for routing behavior.

## Categories

- `quick`: low-latency operational tasks
- `deep`: complex engineering analysis
- `visual`: UI/UX and presentation-heavy work
- `writing`: docs and communication-focused output

## Category settings

Each category defines:

- `model`
- `temperature`
- `reasoning`
- `verbosity`
- `description`

## Fallback behavior

Two deterministic fallback paths are required:

1. unknown category -> `default_category`
2. unavailable model for selected category -> `default_category`

Current implementation lives in `scripts/model_routing_schema.py` with:

- `default_schema()`
- `validate_schema(schema)`
- `resolve_category(schema, requested_category, available_models)`
