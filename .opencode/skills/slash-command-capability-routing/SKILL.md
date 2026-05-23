---
name: slash-command-capability-routing
description: Use when choosing the right repo slash command family such as /ox-*, /browser, /image, /tmux, /mcp, /workflow, or related runtime controls.
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
- a skill-specific workflow already covers the execution path
- plain bash or code editing is clearly the right tool

## First Steps
- identify whether the task is browser validation, design concepting, tmux/live-state, MCP control, workflow execution, or repo delivery
- choose the narrowest command family first
- prefer JSON or doctor/status variants when discovery is needed

## Working Rules
- Use `/ox-design` for concepting and `/ox-ux` or `/browser` for real implemented UI validation.
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
