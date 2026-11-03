# Playwright UX scenarios

Use this guide when the agent should turn a broad “test the UX” request into concrete browser scenarios.

**Safety hold:** Do not run live `/devtools install playwright-cli` or retry it.
Preserve its existing cache, npm config, and attestation files until cache-write
authority and no-clobber publication are qualified. See `docs/command-handbook.md`.
Check any alternative backend independently; this hold does not qualify MCP or
an `npx` invocation as safe for state that must be preserved.

## Operating split

- Choose a browser backend only after confirming its state effects are safe for the task.
- Playwright MCP may help when integrated network, storage, assertion, vision, or host-managed browser tools are needed; assess it independently.
- Use a unique session and close only that session when doing so is safe.

## Scenario matrix

| Scenario | Candidate path, subject to the hold | Why |
| --- | --- | --- |
| Marketing site / docs / landing page | `playwright-cli` | Compact snapshots and repeated interactions |
| Product flow / dashboard / settings | `playwright-cli` | Persistent, token-efficient coding-agent flow |
| Login / auth / returning session | `playwright-cli` or MCP | CLI state reuse; MCP when integrated storage control is needed |
| Offline / retry / degraded backend | MCP | Route mocking and network-state control |
| Canvas / WebGL / browser game | `playwright-cli` | Coordinate and session-heavy exploration |
| Long bug reproduction / walkthrough evidence | `playwright-cli` or MCP+video | Lower token cost and better long-session ergonomics |

## Core scenario templates

### 1. Full website UX pass

- open the home page
- inspect navigation, hero, CTA clarity, and first-scroll comprehension
- check main conversion or discovery flow
- validate loading, empty, error, and success states where relevant
- resize to mobile and re-check core navigation and CTA reachability
- capture top friction points with visible evidence and concrete fixes

### 2. Auth or dashboard flow

- log in or restore saved state
- verify post-login landing clarity and primary next action
- inspect navigation hierarchy, account state, and failure feedback
- simulate stale or missing data when the backend path is flaky
- verify logout, session-expiry, or retry behavior when relevant

### 3. Network and resilience pass

- inspect API requests for the main flow
- mock a success response to stabilize the path if third-party dependencies are noisy
- mock failure responses for empty, error, retry, and partial-data states
- test offline or degraded mode when the product claims resilience

### 4. Canvas, WebGL, or browser-gaming pass

- use `playwright-cli` only if it is independently available and safe for the task
- capture a screenshot and identify the main interactive zones
- test onboarding clarity, HUD readability, input discoverability, pause/settings, and failure/recovery loops
- verify whether actions give immediate visible feedback
- call out when a flow is **observational UX validation** instead of deterministic state proof
- record video when the bug or UX issue unfolds over time

### 5. Repro-to-regression flow

- reproduce the issue in-browser
- capture the exact visible failure
- save video or trace if timing matters
- convert the exploratory path into deterministic assertions or generated locators when follow-up test coverage is warranted

## Tool-selection rules

- Do not bypass the Playwright CLI installation hold with another unqualified installer.
- Use a unique `-s=<session>` value for each owned flow and finish with scoped `close`.
- Do not install external CLI skill bundles. Use `close-all` or `kill-all` only in a fully owned disposable sandbox.
- Prefer accessibility snapshots and refs first.
- Prefer assertions over screenshots for pass/fail claims.
- Use screenshots when refs are missing or you need visual evidence.
- Use vision mode or CLI coordinate input only when the accessibility tree is insufficient.
- Use storage state for login-heavy flows.
- Use network mocking for flaky or third-party dependencies.
- Use video for long reproductions, browser-game loops, and timing-sensitive bugs.
- Use code execution sparingly for iframes, custom waits, clipboard, geolocation, or advanced Playwright API access.

## Evidence checklist

- chosen path is explicit: MCP or `playwright-cli`
- main journey was exercised
- desktop/mobile or equivalent viewport coverage is explicit when relevant
- error/loading/empty edge cases were checked or intentionally scoped out
- evidence includes visible outcome, user impact, and suggested fix
- advanced game/canvas work states whether the result is deterministic proof, repro evidence, or observational UX review
