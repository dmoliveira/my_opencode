# E12 Upstream Flexibility Layer

Owner: `br` epic `bd-201`
Date: 2026-02-19
Status: `doing`

## Goal

Add an upstream-compatible interaction layer so teams can execute with either local canonical workflows or upstream-style patterns, without introducing duplicate runtime engines.

## Design Principles

- Canonical runtime remains `my_opencode` (`/autopilot`, `/task`, `/resume`, `/bg`, gateway hooks).
- Upstream compatibility is delivered as thin adapters/aliases, not replacement engines.
- Compatibility features must be explicit, diagnosable, and safely disableable.
- Existing behavior must remain default-safe for current users.

## Scope

In scope:
- Background-agent UX compatibility adapters for upstream-style flows (`run_in_background`, result retrieval).
- Upstream-style agent surface compatibility map (naming/intent adapters to local agents).
- Hook/injection bridge pass for key upstream semantics where local behavior diverges.
- Documentation and migration guidance showing canonical vs compatibility paths.

Out of scope (for this epic):
- OAuth/websearch provider expansion (tracked/deferred separately as E7).
- Replacing local canonical command/runtime families.

## Workstreams

### W1: Background Agent UX Compatibility

- Add compatibility command/tool facade for upstream-style background delegation and retrieval.
- Map facade calls onto local `/bg` + task/delegation pathways.
- Add deterministic status/result schema for compatibility retrieval.

Acceptance:
- Users can run upstream-style background delegation and later retrieve output using compatibility commands.
- Selftest covers enqueue, run, retrieve, and failure paths.

### W2: Agent Surface Compatibility Map

- Define stable mapping from upstream role labels (e.g., Sisyphus/Hephaestus/Prometheus-style intents) to local agents.
- Provide explicit diagnostics showing mapped target + rationale.
- Keep canonical local names as source of truth.

Acceptance:
- Compatibility map is documented and discoverable.
- Commands return clear mapping metadata in JSON mode.

W2 delivered:

- Added `scripts/upstream_agent_compat_command.py` with `status` and `map --role <name>`.
- Added command surfaces `/upstream-agent-map` and `/upstream-agent-map-status`.
- Added selftest coverage for mapping diagnostics (`prometheus` -> `strategic-planner`).

### W3: Injection/Hook Semantic Bridge

- Compare upstream hook expectations vs local hook behavior for execution continuity and planning transitions.
- Fill remaining high-value semantic gaps with hook-level adapters where needed.
- Keep parity checks in drift/watchdog diagnostics.

Acceptance:
- No unresolved high-value semantic delta remains in selected hook set.
- Hook behavior remains warning-safe and non-destructive by default.

W3 delivered:

- Added hook-bridge diagnostics in `scripts/upstream_agent_compat_command.py status` to verify selected high-value bridge hooks are present in gateway schema.
- Added selftest assertions for compatibility status payload shape (`hook_bridge` diagnostics).

### W4: Docs + Rollout Controls

- Add migration guide: upstream-style flow -> local canonical flow.
- Add toggle/config profile for compatibility mode.
- Add doctor output section to confirm compatibility layer health.

Acceptance:
- README + plan docs include examples for both modes.
- `/doctor` or dedicated doctor command reports compatibility readiness.

W4 delivered:

- Added `scripts/upstream_compat_doctor_command.py` for compatibility readiness checks.
- Added `/upstream-compat-doctor` command surface and installer self-check wiring.
- Added README migration examples for compatibility commands and role mapping diagnostics.

## Delivery Sequence

1. W1 baseline (background compatibility facade).
2. W2 mapping + diagnostics.
3. W3 hook semantic deltas.
4. W4 docs/profile/doctor finalize.

## Validation Bundle (per slice)

- `make validate`
- `make selftest`
- targeted command checks for new compatibility adapters

## Initial Slice (W1 baseline)

- [x] Implement W1 baseline command facade and JSON schema.
- [x] Add selftest coverage for one end-to-end background compatibility roundtrip.
- [x] Add short README compatibility example.

Completed in this slice:

- Added `scripts/upstream_bg_compat_command.py` with `call_omo_agent`, `background_output`, and `status` compatibility endpoints mapped to local `/bg` runtime.
- Added slash command surfaces: `/background-agent-call`, `/background-output`, and `/upstream-bg-status`.
- Added install wiring and self-check for compatibility facade, plus README examples.

Validation evidence:

- `make validate`
- `make selftest`
- `python3 scripts/upstream_bg_compat_command.py status --json`
- `python3 scripts/upstream_bg_compat_command.py call_omo_agent --subagent-type explore --prompt "self-check" --command "python3 -c 'print(\"compat-check\")'" --run-in-background true --json`
- `python3 scripts/upstream_bg_compat_command.py background_output --task-id <bg_id> --json`
