# LSP High-Value Delivery Plan

This plan orders LSP parity work by user value.

Status values:
- `doing`: actively in implementation now
- `finished`: implemented and validated

## Epic E1 (P0): LSP Readiness Surface
Status: `finished`
Value: High

Tasks:
1. Add `/lsp status --json` command for installed/missing server visibility (by language and extension).
2. Add `/lsp doctor --json` command with actionable install hints.
3. Wire `/lsp` aliases into `opencode.json`.
4. Add unified `/doctor` check entry for `lsp`.
5. Add selftest coverage for `/lsp status|doctor` and `/doctor` integration.
6. Update README with LSP command usage.

## Epic E2 (P0): Configurable LSP Registry
Status: `finished`
Value: High

Tasks:
1. Add layered LSP server configuration support (project + user scope).
2. Resolve server precedence deterministically.
3. Support server options (`command`, `extensions`, `priority`, `disabled`, optional `env`/`initialization`).
4. Surface configuration diagnostics in `/lsp doctor`.

## Epic E3 (P1): Direct LSP Operations
Status: `doing` (after E2)
Value: Medium-High

Tasks:
1. Add `/lsp goto-definition` and `/lsp find-references`.
2. Add `/lsp symbols` for document/workspace lookup.
3. Add guarded rename flow (`prepare-rename` + `rename`) with safe fallback messaging.
4. Add validation and docs for non-interactive usage.

## Execution Order
1. E1
2. E2
3. E3

Work starts with E1 and proceeds in order.
