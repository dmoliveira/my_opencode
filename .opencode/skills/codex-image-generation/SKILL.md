---
name: codex-image-generation
description: Use when the user wants `/image` generation, Codex image access, `codex-experimental`, PNG output artifacts, or a direct prompt-to-image workflow inside OpenCode.
---

## Goal
Help the agent turn an image request into a concrete `/image` workflow that either returns a repo-native PNG artifact or explains exactly why access is unavailable.

## Use When
- the user asks to generate an image, icon, mockup, wireframe, or concept art
- the request mentions Codex image access, `codex-experimental`, or prompt-to-PNG flow
- the agent needs to know whether `/image` should use OpenAI API access or the local Codex-backed path
- the task needs a real PNG artifact under `artifacts/design/`

## Do Not Use When
- the user only wants concept critique or prompt planning without generation
- the real implemented UI should be validated in-browser instead
- the task is backend-only or code-review-only

## First Steps
- `/image access --json`
- `/image location show --json`
- If local Codex is desired: `/image preference set codex-experimental`
- If the user only needs prompt drafting first: `/image prompt ... --json`
- If the user wants the actual image now: `/image generate ... --json`

## Provider Rules
- Stable default: `openai_api` via `OPENAI_API_KEY`.
- Local experimental option: `codex-experimental` via a signed-in local Codex session.
- ChatGPT plan access alone does **not** automatically unlock the default API-backed image path.
- If the user explicitly wants Codex local image generation, prefer `--provider codex-experimental` or repo-local preference `codex-experimental`.

## Prompt-to-PNG Workflow
1. Check access with `/image access --json`.
2. Check where artifacts will land with `/image location show --json`.
3. Draft the prompt with `/image prompt ... --json` when prompt quality matters.
4. Generate the real artifact with `/image generate ... --json`.
5. Read the JSON response and report:
   - `provider`
   - `output`
   - `metadata`
   - for Codex path also `resolved_generated_image` and `resolved_generated_image_selection`
6. If needed, open the PNG from the returned artifact path and review it before iterating.

## Common Command Patterns

### Draft prompt only
```text
/image prompt --kind wireframe --subject "mobile onboarding" --goal "cleaner hierarchy" --json
```

### Generate a PNG with the stable API-backed path
```text
/image generate --kind icon --subject "settings gear" --style "minimal, rounded, monochrome" --json
```

### Generate a PNG with local Codex access
```text
/image generate --provider codex-experimental --kind mockup --subject "mobile onboarding" --goal "cleaner hierarchy" --json
```

### Make Codex the local preference first
```text
/image preference set codex-experimental
/image generate --kind mockup --subject "game inventory HUD" --goal "clearer spacing and calmer scan path" --json
```

### Force current-working-directory output location
```text
/image location set cwd-artifacts
/image generate --provider codex-experimental --kind mockup --subject "game inventory HUD" --goal "clearer spacing and calmer scan path" --json
```

## What Success Looks Like
- `result` is `PASS`.
- `output` points to the final PNG artifact path.
- `metadata` points to the sidecar JSON file.
- For `codex-experimental`, `resolved_generated_image` points to the underlying Codex cache PNG that was copied into the repo-native artifact path.

## Failure Handling
- If `/image access --json` says the effective provider is `openai_api` and `OPENAI_API_KEY` is missing, either:
  - use `/image setup-keys`, or
  - switch to `codex-experimental` if local Codex image access is available.
- If Codex access is desired, verify from `/image access --json` that:
  - `experimental_providers.codex-experimental.login_status_ok` is true
  - `experimental_providers.codex-experimental.image_generation_feature_enabled` is true
- If access is still blocked, report the exact missing condition instead of guessing.

## Working Rules
- Prefer repo-native artifact paths under `artifacts/design/`.
- Use `/ox-design` when the user wants concept direction before generation.
- Use `/image prompt` when the prompt needs refinement before spending generation effort.
- Use `/image generate --json` when the user wants the actual image file back.
- For game/app UI concepts, keep the prompt focused on hierarchy, affordances, feedback, and cognitive load.

## Evidence / Done
- Effective provider is explicit.
- Output PNG path is explicit.
- Any provider/setup blocker is explicit.
- The returned artifact path is ready for review or iteration.

## References
- `docs/image-design-workflow.md`
- `docs/command-handbook.md`
- `scripts/image_command.py`
