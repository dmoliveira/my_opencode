---
name: explore-codebase-patterns
description: Use when finding where something is implemented, identifying local code or doc patterns, or narrowing the smallest relevant file set before editing.
---

## Goal
Find the smallest relevant set of files and local patterns needed to act safely without broad speculative exploration.

## Use When
- the user asks where something is implemented
- the task needs local examples to copy or adapt
- relevant files or modules are still unclear
- discovery is needed before planning or editing

## Do Not Use When
- the target file and local pattern are already obvious
- external framework behavior is the main unknown
- the task is final review or validation rather than discovery

## First Steps
- start with `glob` to find candidate files or directories
- use `grep` to narrow exact symbols, commands, or phrases
- compare 1-3 local examples before proposing an implementation path
- if scope is still broad, delegate `explore` with constrained ownership

## Working Rules
- Prefer repo-local patterns before external references.
- Return candidate files, repeated patterns, and why they matter.
- Separate exact matches from merely similar examples.
- Stop once there is enough context to plan or edit safely.
- Keep discovery outputs concise and implementation-oriented.

## Evidence / Done
- relevant files or modules are explicit
- one or more local patterns were identified
- the recommended starting point is clear
- unnecessary extra exploration was avoided

## References
- `AGENTS.md`
- `docs/tooling-quick-ref.md`
- `docs/orchestration-advanced.md`
