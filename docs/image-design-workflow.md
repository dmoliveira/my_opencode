# Image and design workflow

Use this workflow when you want structured UX/design help, repo-native visual artifacts, or image generation that feeds real delivery work through either the stable OpenAI API path or the experimental Codex path.

## Command split

- `/ox-design`: concepting, design critique, prompt/spec planning, artifact naming, and UX direction.
- `/image`: direct image prompt/build flow for repo-native artifacts under `artifacts/design/`.
- `/ox-ux`: browser-first audit of the real implemented experience.
- `/browser`: narrow bridge for browser-owned blockers and final visual verification.

## Decision rule

Use image/design generation when the question is:

- what could this look like?
- what icon or palette direction should we try?
- what wireframe or hero concept should we explore?

Use browser review when the question is:

- how does the real thing behave?
- does the implemented UI feel clear and accessible?
- do responsive states, empty states, or auth flows actually work?

## Repo-native artifacts

All generated or curated design outputs should live under:

```text
artifacts/design/
```

That keeps visual work reviewable in Git, easy to reference in PRs, and consistent with the rest of the runtime docs.

## Common flows

### 1) Product design direction

```text
/ox-design --scope "dashboard + settings" --goal "explore a calmer admin direction"
```

### 2) Prepare an image-generation prompt without calling the API

```text
/image prompt --kind wireframe --subject "mobile onboarding" --goal "reduce clutter and increase trust" --json
```

### 3) Generate an icon or mockup into the repo

```text
/image generate --kind icon --subject "settings gear" --style "minimal, rounded, monochrome" --json
/image generate --kind mockup --subject "game inventory screen" --goal "cleaner hierarchy and calmer HUD" --json
/image generate --provider codex-experimental --kind mockup --subject "mobile onboarding" --goal "cleaner hierarchy" --json
```

### 4) Browser validation after concepting

```text
/browser ensure --json
/mcp profile playwright
/ox-ux --scope "implemented onboarding flow"
```

## OpenAI setup

```text
/image access --json
/image preference show --json
/image doctor --json
/image setup-keys
```

Access note:

- `/image` defaults to the API-backed `openai_api` provider and expects `OPENAI_API_KEY` for that path.
- ChatGPT plan access in OpenCode does not automatically unlock the default API-backed path.
- A separate opt-in `codex-experimental` provider can use your signed-in local Codex session when available.
- If you want Codex as your usual local preference, use `/image preference set codex-experimental`; the hardcoded stable default remains `openai_api` when no preference is configured.
- Use `/image access --json` when you want the runtime to explain that distinction explicitly.

Required env:

- `OPENAI_API_KEY`

Preferred safe storage:

- Store the secret once with your local `sk` Keychain flow.
- Load it only into the current shell/session when you want to use `/image`.

```text
printf '%s' "$OPENAI_API_KEY" | sk add -k OPENAI_API_KEY --stdin --force
export OPENAI_API_KEY="$(sk get -k OPENAI_API_KEY)"
unset OPENAI_API_KEY
```

Optional env overrides:

- `OPENAI_IMAGE_MODEL`
- `OPENAI_IMAGE_SIZE`
- `OPENAI_IMAGE_QUALITY`

## Notes

- Use official OpenAI image tooling terminology such as **OpenAI image generation** or **GPT Image models**.
- Do not treat exploratory images as product truth until the implemented UI is reviewed in-browser.
- Prefer one strong direction over noisy batches.
