# Concise Communication Workflow

Use this module when the user, runtime, or repo default wants lower-token, higher-density answers without losing technical accuracy.

## Mode model

- `off`: normal repo communication style
- `lite`: remove filler and hedging, keep normal sentence structure
- `full`: prefer short direct fragments while keeping technical terms exact
- `ultra`: strongest safe compression only

## Precedence

1. explicit user request
2. runtime/plugin mode
3. repo default in `AGENTS.md`

If a runtime exposes concise controls, treat its effective mode status output as the source of truth.

## Core rules

- Preserve technical substance; remove fluff first.
- Keep code blocks, commands, identifiers, filenames, flags, and exact errors unchanged.
- Short fragments are fine when meaning stays obvious.
- Expand again when compression would hide risk, blockers, or ordering.

## Good concise targets

- validation summaries
- progress updates
- review summaries
- PR/release notes
- routine operational status

## When to relax concise mode

- destructive or irreversible warnings
- security/privacy guidance where nuance matters
- multi-step instructions where compressed wording could reorder meaning
- repeated confusion or explicit requests for more detail

## Boundaries

- Do not compress away blocker evidence, validation evidence, or final state.
- Do not force terse output when clarity would become unsafe.
- Keep the module easy to disable or override.
