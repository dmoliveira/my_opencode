# Docs Index

Use this page as the fast local entrypoint for repo documentation.

This repo-local index exists because `AGENTS.md` and related startup docs reference `docs/index.md` as an expected local path during active work. For the broader reusable policy set, the sibling `../agents_md/docs/` tree remains the upstream companion source.

## Core workflow

- `../AGENTS.md`: source-of-truth operating contract for the adaptive execution loop
- `codememory-workflow.md`: required Codememory execution, task/session, and handoff flow
- `codememory-conventions.md`: repo-specific Codememory scope and capture rules
- `github-cli.md`: automation-safe `gh` patterns used in this repo
- `validation-policy.md`: validation-definition gate, key-gate validation, and review budget
- `iterative-testing-workflow.md`: optional live-state and sandbox testing guidance
- `concise-communication-workflow.md`: optional concise/terse communication guidance
- `tooling-quick-ref.md`: quick commands and local reference map
- `orchestration-advanced.md`: advanced sequencing, concurrency, and pressure-mode controls

## Runtime/operator docs

- `quickstart.md`: startup path and main command-surface overview
- `operator-playbook.md`: operator-facing execution and incident flow
- `parallel-wt-playbook.md`: worktree-first execution and safe reservation guidance
- `command-handbook.md`: detailed slash-command reference
- `playwright-ux-scenarios.md`: scenario templates for website, dashboard, resilience, and browser-game UX testing
- `silent-first-command-defaults.md`: JSON-first and low-noise command defaults
- `runtime-db-schema.md`: read-only SQLite/runtime inspection notes
- `portkey-provider-quickstart.md`: optional Portkey provider env + smoke-model setup

## Planning and review

- `plan/opencode-reliability-review-runbook.md`: reusable reliability/E2E review campaign runbook
- `specs/e8-plan-handoff-continuity-mapping.md`: continuity and handoff semantics
- `plugin-gateway-plan.md`: gateway/plugin architecture and follow-up planning
- `readme-deep-notes.md`: deeper architecture and release-history notes

## Publishing/docs output

- `pages/index.html`: generated docs hub for static browsing
- `upstream-divergence-registry.md`: intentional local vs upstream behavior differences

## Support

- `../README.md`: top-level project overview and install notes
