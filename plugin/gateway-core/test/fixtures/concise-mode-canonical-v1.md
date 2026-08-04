Use this module when the user or runtime explicitly wants lower-token answers without losing technical substance. If the runtime exposes `/gateway concise status` or equivalent mode status, treat that as the canonical signal.

## Persistence

Active only when the user or runtime enables it. Missing or unknown mode means `off`. Some runtimes persist the chosen mode at repo scope until it changes or is turned off explicitly.

## Rules

- Remove filler, pleasantries, and weak hedging first.
- Keep technical terms, file paths, identifiers, commands, and exact errors unchanged.
- `lite`: concise but sentence-based.
- `full`: terse fragments OK when meaning stays obvious.
- `ultra`: strongest compression; use only when readability remains safe.
- Code blocks unchanged.

## Relax mode for clarity

Use fuller language for:

- destructive warnings
- security/privacy guidance
- multi-step procedures where order matters
- repeated confusion or explicit requests for more detail

## Pattern

Useful terse pattern:

- `[problem]. [cause]. [fix]. [next step].`

## Source of truth

For mode semantics, examples, and disable guidance, see `docs/concise-communication-workflow.md`.
