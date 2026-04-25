# Design artifacts

`artifacts/design/` stores repo-native design work that is relevant enough to review and commit alongside code when it supports the task.

## What belongs here

- wireframes
- icon sets
- palettes
- mockups
- hero concepts
- typography graphics
- source screenshots or references that directly support the design task
- prompt/spec files used to generate or revise those artifacts

## Suggested structure

```text
artifacts/design/
  README.md
  prompts/
  palettes/
  icons/
  wireframes/
  mockups/
  hero/
  typography/
  source/
  exports/
```

Create subdirectories on demand. The `/image` command defaults to this root and will create the parent folders it needs.

## Naming convention

Prefer stable, review-friendly names:

- `wireframes/onboarding-v1.png`
- `wireframes/onboarding-v1.json`
- `icons/settings-gear-v2.png`
- `icons/settings-gear-v2.json`
- `palettes/dashboard-dark-v1.png`
- `palettes/dashboard-dark-v1.json`
- `hero/landing-concept-v1.png`

## Metadata sidecars

When practical, keep a sibling `.json` file with:

- prompt
- model
- source inputs or refs
- timestamp
- task / issue / branch reference
- notes or approval status
- dimensions / quality / style details

The `/image generate` command writes this sidecar automatically.

## Commit guidance

- Commit curated, task-relevant artifacts.
- Avoid large unreviewed batches or throwaway generations.
- If the binary is not worth committing yet, keep the prompt/spec only.
- Treat these artifacts like normal delivery assets when they materially help implementation, review, or design communication.
