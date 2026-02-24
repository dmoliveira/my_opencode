# LSP High-Value Delivery Plan

This plan orders LSP parity work by user value.

Status values:
- `planned`: approved for implementation, not started yet
- `doing`: actively in implementation now
- `finished`: implemented and validated

## Epic E1 (P0): LSP Readiness Surface
Status: `finished`
Value: High

Tasks:
1. Add `/lsp status --json` command for installed/missing server visibility (by language and extension). `finished`
2. Add `/lsp doctor --json` command with actionable install hints. `finished`
3. Wire `/lsp` aliases into `opencode.json`. `finished`
4. Add unified `/doctor` check entry for `lsp`. `finished`
5. Add selftest coverage for `/lsp status|doctor` and `/doctor` integration. `finished`
6. Update README with LSP command usage. `finished`

## Epic E2 (P0): Configurable LSP Registry
Status: `finished`
Value: High

Tasks:
1. Add layered LSP server configuration support (project + user scope). `finished`
2. Resolve server precedence deterministically. `finished`
3. Support server options (`command`, `extensions`, `priority`, `disabled`, optional `env`/`initialization`). `finished`
4. Surface configuration diagnostics in `/lsp doctor`. `finished`

## Epic E3 (P1): Direct LSP Operations
Status: `finished`
Value: Medium-High

Tasks:
1. Add `/lsp goto-definition` and `/lsp find-references`. `finished`
2. Add `/lsp symbols` for document/workspace lookup. `finished`
3. Add guarded rename flow (`prepare-rename` + `rename`) with safe fallback messaging. `finished`
4. Add validation and docs for non-interactive usage. `finished`

## Epic E4 (P1): Capability-Aware Execution and UX
Status: `finished`
Value: High

Tasks:
1. Use `/lsp doctor --verbose` capability matrix to preflight command readiness before protocol execution. `finished`
2. Add explicit reason codes when a server is installed but lacks required capability for a command. `finished`
3. Add command-level warnings to nudge users toward supported operations and safer fallbacks. `finished`
4. Extend selftest with deterministic capability-mismatch fixtures for capability preflight and warning behavior. `finished`

## Epic E5 (P1): Safe WorkspaceEdit Expansion
Status: `finished`
Value: High

Tasks:
1. Add explicit dry-run visibility for `CreateFile` and `DeleteFile` resource operations in rename plans. `finished`
2. Add policy guardrails for resource-op classes (`renamefile`, `createfile`, `deletefile`) with opt-in flags. `finished`
3. Keep apply path blocked by default for destructive file operations until policy and validation gates pass. `finished`
4. Add helper tests for policy edge cases (existing target, missing source, out-of-root paths). `finished`

## Epic E6 (P2): Diagnostics and Code Actions Surface
Status: `planned`
Value: Medium-High

Tasks:
1. Add `/lsp diagnostics --scope <glob[,glob...]>` with structured severity/count output. `planned`
2. Add `/lsp code-actions --symbol <name>|--file <path>` dry-run listing with stable JSON schema. `planned`
3. Add guarded apply path for safe code-action edits with the same validation model used by rename. `planned`
4. Document command contracts and add selftest coverage for diagnostics/action payload parsing. `planned`

## Execution Order
1. E1
2. E2
3. E3
4. E4
5. E5
6. E6

Work starts with E1 and proceeds in order.
