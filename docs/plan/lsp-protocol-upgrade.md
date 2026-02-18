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

## Validation
Status: `finished`

Tasks:
1. Lint changed scripts (`ruff check`). `finished`
2. Compile changed scripts (`python3 -m py_compile`). `finished`
3. Run selftest suite (`python3 scripts/selftest.py`). `finished`
