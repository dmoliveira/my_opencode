---
name: tmux-sandbox
description: Use when persistent tmux sessions are needed to run, inspect, or validate live CLI services and long-running terminal workflows.
---

## Goal
Use tmux as a persistent sandbox for live-state validation, service inspection, and recoverable terminal workflows.

## Use When
- a service must stay running during testing
- logs or terminal state must be observed over time
- a CLI workflow is long-running or multi-step
- the task needs resumable terminal context

## Do Not Use When
- a one-shot command is enough
- static inspection answers the question
- browser-first validation is the real need

## First Steps
- `/tmux doctor --json`
- `/tmux status --json`
- Use a clear session name such as `ai-oc-<task>`.

## Working Rules
- Keep panes focused by role: app, logs, tests, shell.
- Prefer non-interactive commands inside panes when possible.
- Capture useful pane output before cleanup.
- Avoid leaving stale sessions behind.
- Make the persistence vs cleanup decision explicit before finishing.

## Evidence / Done
- session name is known
- running process or service state was observed
- relevant pane output was captured
- cleanup or keep-alive status was stated

## References
- `docs/iterative-testing-workflow.md`
- `docs/quickstart.md`
- `docs/readme-deep-notes.md`
- https://man.openbsd.org/tmux
- https://raw.githubusercontent.com/wiki/tmux/tmux/Advanced-Use.md
