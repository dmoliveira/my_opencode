---
name: playwright-web-ux
description: Use when browser-first validation, Playwright MCP, implemented web UX review, responsive checks, or accessibility flow testing is needed.
---

## Goal
Validate the real implemented web experience in-browser and produce concrete UX findings with evidence.

## Default Operating Mode
- Use Playwright MCP first for standard website and application UX audits.
- Use `playwright-cli` first for advanced canvas, WebGL, browser-game, or long exploratory sessions where token efficiency and persistent sessions matter.
- Keep the same quality bar in both paths: deterministic state setup, user-visible assertions, and evidence-backed findings.

## Use When
- the user asks for Playwright or browser testing
- the task is an implemented web flow review
- responsive, mobile, or accessibility behavior must be checked
- UX claims need evidence from the live UI

## Do Not Use When
- the work is pure concepting or visual exploration
- the task is backend-only
- static code review is sufficient

## First Steps
- `/browser ensure --json`
- `/mcp profile playwright`
- `/ox-ux --repo <repo>` or use `--target` and `--scope` for a narrower audit.
- For advanced canvas/game flows, install and use CLI skills: `playwright-cli install --skills`.

## Tool Selection Rules
- Quick gate:
  - Use Playwright MCP by default for standard implemented website and app audits.
  - Use `playwright-cli` first when the flow is canvas-heavy, WebGL-based, multi-tab, auth-state-heavy, or needs a long exploratory session.
  - If semantics are weak but the flow is still short, start with MCP and fall back to CLI only when the accessibility tree or refs are insufficient.
- Prefer accessibility snapshots and refs first.
- Use Playwright MCP assertions when you need deterministic visible-state checks.
- Use network and storage controls when auth, retries, offline mode, or error states must be reproduced reliably.
- Use vision mode only when the accessibility tree is insufficient, such as canvas, WebGL, maps, charts, or custom widgets without meaningful ARIA.
- Use `playwright-cli` first when the task needs longer exploratory loops, multiple sessions, browser-game traversal, or token-efficient repeated commands.
- Use screenshots and video as supporting evidence, not as the only proof of correctness.
- Keep only high-signal commands in this skill; use the official CLI docs for the full command catalog.

## Scenario Playbooks

### Standard website or app audit
- Exercise the main journey first.
- Then cover loading, empty, error, success, and mobile states.
- Verify visible copy, hierarchy, responsiveness, and trust cues.

### Auth or dashboard flow
- Save or restore storage state instead of relogging every pass.
- Mock or inspect network when third-party or flaky backend behavior would hide the real UX issue.
- Assert the post-login state explicitly.

### Canvas, WebGL, or browser-game flow
- Start with `playwright-cli` when the UI is mostly non-semantic or coordinate-driven.
- High-value starter moves:
  - use `open --persistent` or `attach --cdp=chrome` for longer sessions
  - use `state-save` / `state-load` for auth-heavy flows
  - use a few tactical helpers such as tab selection, dialog accept, routing, tracing/video, locator generation, or highlight only when they reduce ambiguity
  - use `--raw` or `--json` when you need compact evidence or reusable follow-up automation
- Capture a screenshot, identify coordinates, then use vision-mode or CLI mouse commands.
- Prefer proving navigation, affordance clarity, input feedback, HUD readability, error handling, save/load, and flow comprehension.
- Be explicit when a game scenario is observational UX validation rather than deterministic state proof.

### Bug reproduction and evidence capture
- Record video or tracing for long or timing-sensitive flows.
- Capture the exact failing step, then the expected vs actual visible result.
- Convert the exploratory path into assertions or generated locators when the flow should become repeatable coverage later.

## Working Rules
- Test user-visible behavior, not implementation details.
- Prefer stable accessible interactions and deterministic assertions.
- Start from the main user journey, then check empty, error, loading, and edge states.
- Check desktop and mobile before concluding.
- Prioritize blockers, comprehension issues, and trust-breaking friction before cosmetics.
- Use screenshots only as supporting evidence.
- For browser gaming and canvas-heavy work, define whether the outcome is deterministic automation, reproducible repro evidence, or observational UX review before claiming success.

## Evidence / Done
- Key flows were exercised.
- Desktop and mobile states were checked.
- Top UX issues were prioritized.
- Findings include concrete user impact and suggested fixes.
- For advanced flows, the chosen mode (`MCP` vs `playwright-cli`) and why it was chosen are explicit.

## Output Discipline
- Keep the final readout compact: chosen mode, flows exercised, top findings ranked, and the exact evidence captured.
- Prefer snapshots, `--raw`, or `--json` outputs before verbose console transcripts.
- When no meaningful issue is found, say that directly instead of padding the report.

## References
- `docs/ox-command-pack.md`
- `docs/command-handbook.md`
- `docs/playwright-ux-scenarios.md`
- https://playwright.dev/mcp/introduction
- https://playwright.dev/mcp/capabilities
- https://playwright.dev/mcp/vision-mode
- https://playwright.dev/mcp/tools/network-mocking
- https://playwright.dev/mcp/tools/storage
- https://playwright.dev/mcp/tools/assertions
- https://playwright.dev/mcp/tools/video
- https://playwright.dev/mcp/tools/code-execution
- https://playwright.dev/agent-cli/introduction
- https://playwright.dev/agent-cli/skills
- https://playwright.dev/agent-cli/vision-mode
- https://playwright.dev/docs/best-practices
- https://playwright.dev/docs/locators
