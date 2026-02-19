# LSP Protocol Upgrade

Status values:

- `doing`
- `finished`

## Epic P1: Protocol Execution for Existing /lsp Commands

Status: `finished`

Tasks:

1. Add stdio JSON-RPC LSP client utility with initialize/request/shutdown lifecycle. `finished`
2. Route `/lsp goto-definition` and `/lsp find-references` through protocol when matching installed server exists. `finished`
3. Route `/lsp symbols` (document/workspace) through protocol with deterministic text fallback. `finished`
4. Route `/lsp prepare-rename` and `/lsp rename` planning through protocol workspace edits with guarded fallback. `finished`
5. Preserve existing text fallback behavior and reason codes when protocol path is unavailable. `finished`

## Epic P2: WorkspaceEdit documentChanges Support

Status: `finished`

Tasks:

1. Parse `workspaceEdit.documentChanges[*].textDocument.uri` + `edits` for rename planning flows. `finished`
2. Merge `changes` and `documentChanges` edit streams into one deterministic edit plan. `finished`
3. Keep existing guardrails (`--allow-text-fallback`, validation, apply mode) unchanged for fallback behavior. `finished`

## Remaining Roadmap (Ordered)

Status: `finished`

Tasks:

1. Support `workspaceEdit` resource operations (`RenameFile`, `CreateFile`, `DeleteFile`) in rename planning, with safe blocking when present. `finished`
2. Support `workspaceEdit.changeAnnotations` + per-edit annotation IDs with safer apply policy. `finished`
3. Add mock LSP integration test harness for deterministic protocol CI coverage. `finished`
4. Expose `backend_details` field in `/lsp` JSON outputs (server id/command/path reason). `finished`
5. Add dry-run diff preview output for `/lsp rename` before `--apply`. `finished`

See also: `docs/plan/lsp-milestones-changelog.md` for merged PR-by-PR delivery history.

## Post-Roadmap Hardening

Status: `finished`

Tasks:

1. Allow guarded `RenameFile` apply path for `/lsp rename` when explicitly opted-in. `finished`
2. Keep `CreateFile`/`DeleteFile` operations blocked during apply. `finished`
3. Add helper coverage for renamefile validation and apply behavior in selftest. `finished`
4. Enforce diff review thresholds before `/lsp rename --apply` via `max_diff_files` and `max_diff_lines`. `finished`
5. Add `/lsp doctor --verbose` capability probing matrix for protocol command support coverage. `finished`
6. Preflight command execution against required protocol capabilities before issuing LSP requests. `finished`
7. Expose dry-run `CreateFile`/`DeleteFile` operation visibility in `/lsp rename` planning output. `finished`
8. Add explicit `CreateFile`/`DeleteFile` policy flags to `/lsp rename` guardrails while keeping apply blocked for those operations. `finished`
9. Add `/lsp diagnostics --scope` baseline with structured severity summary output. `finished`
10. Add `/lsp code-actions` dry-run listing baseline for `--file` and `--symbol --scope` targeting. `finished`
11. Add guarded `--apply` path for `/lsp code-actions` when selected action contains safe text edits only. `finished`
12. Add explicit capability-missing warning hints across `/lsp` command outputs. `finished`
13. Enhance `/lsp diagnostics` summary with source counts and top diagnostic codes. `finished`

## Validation

Status: `finished`

Tasks:

1. Lint changed scripts (`ruff check`). `finished`
2. Compile changed scripts (`python3 -m py_compile`). `finished`
3. Run selftest suite (`python3 scripts/selftest.py`). `finished`
