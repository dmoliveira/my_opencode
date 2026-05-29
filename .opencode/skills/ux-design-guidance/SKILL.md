---
name: ux-design-guidance
description: Use when concept UX direction, visual hierarchy, wireframes, icons, palettes, mockups, or artifact planning is needed for web, app, or game flows.
---

## Goal
Produce one strong UX or design direction with minimal tokens and clear next actions.

## Use When
- the user wants concept UX polish or a calmer design direction
- the task needs wireframe, icon, palette, or mockup planning
- a web, app, or game flow needs concept direction, clarity, or hierarchy improvement before browser validation
- artifact planning is needed before implementation

## Do Not Use When
- the real implemented UI should be validated in-browser first
- the task is backend-only
- the task is final code risk review

## First Steps
- For concepting, use `/ox-design ...`.
- If the task turns into implemented web UI validation, switch to `playwright-web-ux` or run `/browser ensure --json`, `/mcp profile playwright`, then `/ox-ux ...`.
- If image generation matters, check `/image access --json` and `/image location show --json`, then use `codex-image-generation` for the prompt-to-PNG flow.

## Working Rules
- Optimize for clarity, hierarchy, trust, feedback, and calm UI.
- Prefer one clear direction over many weak alternatives.
- Treat accessibility and responsiveness as first-class.
- Keep flows and states more important than decoration.
- Store visual outputs under `artifacts/design/`.
- For web, focus on IA, forms, navigation, and responsive states.
- For apps, focus on navigation, reachability, and empty, loading, and error states.
- For games, focus on HUD clarity, feedback loops, affordances, and cognitive load.

## Evidence / Done
- Target flow or surface is explicit.
- Main friction points are named.
- One preferred direction is proposed.
- Artifact or prompt next step is defined when needed.
- If generation is requested, the provider path (`openai_api` vs `codex-experimental`) is made explicit.

## References
- `docs/image-design-workflow.md`
- `codex-image-generation`
- `docs/ox-command-pack.md`
- `docs/command-handbook.md`
- `agent/experience-designer.md`
