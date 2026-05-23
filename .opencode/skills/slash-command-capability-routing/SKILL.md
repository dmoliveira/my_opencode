---
name: slash-command-capability-routing
description: Use when choosing which repo slash command family should handle a task, then hand off to the narrower workflow or skill.
---

## Goal
Choose the smallest slash-command family that matches the task instead of restating command selection logic from scratch.

## Use When
- the user wants the right repo command for a task
- multiple slash-command families could fit
- the task needs routing between browser, design, runtime, or workflow commands
- command discovery is the bottleneck, not implementation logic

## Do Not Use When
- the task already names the exact command to run
- a skill-specific workflow already covers the execution path after command family selection
- plain bash or code editing is clearly the right tool

## First Steps
- identify whether the task is browser validation, design concepting, tmux/live-state, MCP control, workflow execution, or repo delivery
- choose the narrowest command family first
- prefer JSON or doctor/status variants when discovery is needed

## Working Rules
- Route to the narrowest command family first, then hand off to the specific workflow or skill.
- Use `/ox-design` for concepting and `/browser ensure --json`, `/mcp profile playwright`, then `/ox-ux` for real implemented web UI validation.
- Use `/tmux` for terminal-session state, not browser state.
- Use `/mcp` for managed MCP profiles and server toggling.
- Use `/workflow`, `/delivery`, or `/ship` for reusable delivery orchestration.
- Use doctor/status/help variants before deeper mutation when capability is unclear.

## Evidence / Done
- chosen command family matches the task category
- the routing reason is explicit
- fallback path is clear if the first command family is unavailable
- no broader command set was used without need

## References
- `docs/command-handbook.md`
- `docs/quickstart.md`
- `docs/ox-command-pack.md`
- `docs/image-design-workflow.md`
- `docs/orchestration-advanced.md`
