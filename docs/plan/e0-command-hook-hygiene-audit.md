# E0 Command/Hook Hygiene Audit

Date: 2026-02-19
Related plan: `docs/plan/oh-my-opencode-parity-high-value-plan.md`

## Purpose

Establish a low-cognitive-load command/hook surface before parity expansion.

## Rubric (E0-T1)

A command/hook is considered high-value when it satisfies at least two of:

1. Clear unique user intent (not a duplicate template).
2. Safety value (prevents errors, improves determinism, or hardens execution).
3. Operational value (used in installation/doctor/selftest/validation loops).
4. Learnability value (name and help text are obvious to new users).

A surface is a deprecation candidate when:

- It duplicates behavior and increases naming ambiguity.
- It has no unique safety or operational value.
- It adds migration burden without measurable gain.

## Findings (E0-T2, E0-T3)

Command surface snapshot:

- Total slash commands: 216.
- Missing script references: 0.
- Duplicate-template clusters found: 4.

Duplicate-template clusters and decision:

| Cluster | Decision | Canonical | Migration note |
| --- | --- | --- | --- |
| `complete`, `ac` | keep alias | `complete` | `ac` remains shorthand alias. |
| `model-routing`, `model-profile` | keep compatibility alias | `model-routing` | Prefer `model-routing` in docs and examples. |
| `model-routing-status`, `model-profile-status` | keep compatibility alias | `model-routing-status` | Prefer `model-routing-status` in docs. |
| `autopilot-go`, `continue-work` | keep compatibility alias | `autopilot-go` | Prefer `autopilot-go`; `continue-work` for familiarity. |

Hook surface snapshot:

- Configured hook order vs implemented hook IDs: fully aligned.
- No unregistered or order-only hook IDs detected.

## Implemented improvements (E0-T4, E0-T5)

- Naming policy updated to plain-English first, minimal aliases.
- Greek-themed alias proposal removed to reduce cognitive load.
- Canonical command strategy documented for loop parity:
  - improve existing `/autopilot` and `/autoflow` first,
  - add aliases only when strictly needed for migration/parity.
- Alias descriptions in `opencode.json` updated for clearer canonical direction.

## Automated drift checks (E0-T6)

Added `scripts/hygiene_drift_check.py` and integrated into `make validate`.

Checks enforced:

1. All slash command script references resolve.
2. Duplicate-template clusters must match allowlisted compatibility aliases.
3. Gateway hook order must match implemented hook IDs.

## Validation evidence

- `python3 scripts/hygiene_drift_check.py`
- `make validate`
