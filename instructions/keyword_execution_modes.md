# Keyword Execution Modes

Epic 8 Task 8.1 defines the baseline contract for keyword-triggered execution modes.

## Reserved keywords

- `ulw`: ultra-lightweight execution for low-latency responses
- `deep-analyze`: high-depth analysis mode with stronger verification expectations
- `parallel-research`: permit parallelizable research tool usage when safe
- `safe-apply`: favor conservative edits and stronger pre-apply validation

Keywords are case-insensitive and match only as standalone tokens after punctuation-aware tokenization.

## Detection and matching rules

1. Tokenize prompt text by whitespace and punctuation boundaries.
2. Normalize tokens to lowercase.
3. Match only exact keyword tokens (no partial substring matching).
4. Ignore matches inside inline code fences and quoted literal command examples when context indicates documentation intent.

These rules reduce false positives and keep activation deterministic.

## Mode side-effects

Each keyword maps to mode flags that will be applied by the runtime detector engine in Task 8.2.

- `ulw`
  - prefers concise response style
  - lowers autonomous breadth for non-essential exploration
  - keeps safety constraints unchanged
- `deep-analyze`
  - increases analysis depth and evidence gathering
  - requires explicit reasoning trace availability for critical decisions
  - favors stronger verification before concluding
- `parallel-research`
  - enables parallelizable read/search activity where tools support safe parallel execution
  - does not bypass ordering when operations are stateful or dependent
- `safe-apply`
  - enforces conservative edit strategy defaults
  - requires stronger pre-apply checks before material code changes
  - discourages aggressive refactors unless explicitly requested

## Precedence and conflict handling

When multiple keywords are present, resolve in this deterministic order:

1. `safe-apply`
2. `deep-analyze`
3. `parallel-research`
4. `ulw`

Resolution model:

- Combine non-conflicting flags across all matched keywords.
- For conflicting flags, keep the value from the highest-precedence keyword.
- Record a conflict note for diagnostics (Task 8.3 visibility).

## Opt-out syntax and defaults

Default behavior:

- Keyword activation is enabled.
- No keyword present means standard execution behavior.

Prompt-level opt-out syntax:

- `no-keyword-mode`: disables all keyword activation for the current request.
- `no-<keyword>` token (for example `no-ulw`, `no-deep-analyze`) disables only that keyword for the current request.

Config-level opt-out defaults (for Task 8.3):

- maintain a disabled-keyword list in layered config
- allow global disable of keyword detection

## Deliverables for downstream tasks

- Task 8.2 consumes this file as the normative detector contract.
- Task 8.3 exposes active keyword stack, conflicts, and disable controls.
- Task 8.4 validates matching accuracy, false-positive resistance, and install-test/doctor visibility.
