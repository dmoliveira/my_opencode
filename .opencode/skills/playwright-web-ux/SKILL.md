---
name: playwright-web-ux
description: Use when browser-first validation, Playwright MCP, implemented web UX review, responsive checks, or accessibility flow testing is needed.
---

## Goal
Validate the real implemented web experience in-browser and produce concrete UX findings with evidence.

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
- `/ox-ux --repo <repo>` or use `--target` and `--scope` for a narrower audit

## Working Rules
- Test user-visible behavior, not implementation details.
- Prefer stable accessible interactions and deterministic assertions.
- Start from the main user journey, then check empty, error, loading, and edge states.
- Check desktop and mobile before concluding.
- Prioritize blockers, comprehension issues, and trust-breaking friction before cosmetics.
- Use screenshots only as supporting evidence.

## Evidence / Done
- Key flows were exercised.
- Desktop and mobile states were checked.
- Top UX issues were prioritized.
- Findings include concrete user impact and suggested fixes.

## References
- `docs/ox-command-pack.md`
- `docs/command-handbook.md`
- https://playwright.dev/mcp/introduction
- https://playwright.dev/mcp/tools/assertions
- https://playwright.dev/docs/best-practices
- https://playwright.dev/docs/locators
