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
Status: `doing`

Tasks:
1. Support `workspaceEdit` resource operations (`RenameFile`, `CreateFile`, `DeleteFile`) in rename planning, with safe blocking when present. `finished`
2. Support `workspaceEdit.changeAnnotations` + per-edit annotation IDs with safer apply policy. `finished`
3. Add mock LSP integration test harness for deterministic protocol CI coverage. `finished`
4. Expose `backend_details` field in `/lsp` JSON outputs (server id/command/path reason). `doing`
5. Add dry-run diff preview output for `/lsp rename` before `--apply`. `doing`

## Validation
Status: `finished`

Tasks:
1. Lint changed scripts (`ruff check`). `finished`
2. Compile changed scripts (`python3 -m py_compile`). `finished`
3. Run selftest suite (`python3 scripts/selftest.py`). `finished`
