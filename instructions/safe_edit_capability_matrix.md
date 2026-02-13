# Safe Edit Capability Matrix (E18-T1)

This matrix defines the semantic-edit baseline before adapter implementation.

## Supported operations

The first safe-edit release targets four operations:

- `rename`: symbol-aware rename with reference updates inside validated scope.
- `extract`: extract function/method/block while preserving behavior and call sites.
- `organize_imports`: deterministic import cleanup/reorder without behavior changes.
- `scoped_replace`: structurally constrained replace for exact node/type matches.

Each operation must declare:

- required semantic backend (`lsp` or `ast`)
- minimum language/tool support
- fallback behavior when semantic backend is unavailable
- post-edit validation requirements

## Operation-to-backend matrix

| Operation | Preferred backend | Secondary backend | Text fallback allowed | Minimum validations |
|---|---|---|---|---|
| `rename` | LSP symbol rename | AST identifier transform | yes (guarded) | `make validate` + changed-reference check |
| `extract` | AST structural transform | LSP code action (if deterministic) | yes (guarded) | `make validate` + behavior-preserving diff check |
| `organize_imports` | LSP organize imports | language formatter/import sorter | yes (guarded) | `make validate` |
| `scoped_replace` | AST node-constrained replace | LSP workspace edit | yes (guarded) | `make validate` + scope-boundary check |

## Language and tool availability checks

Safe-edit eligibility requires a deterministic preflight report.

Per run, resolve:

1. language for each target file (`python`, `typescript`, `javascript`, `go`, `rust`, `unknown`)
2. available semantic tooling in priority order
3. whether operation/backend pair is supported for each file

Expected checks by backend type:

- LSP checks:
  - language server binary available
  - workspace root detected
  - symbol/index query succeeds for at least one target file
- AST checks:
  - parser/toolchain available for language
  - parse succeeds with zero syntax errors for all in-scope files
  - transformation dry-run produces deterministic edit set

If no semantic backend is available, runtime must downgrade to guarded text mode and emit explicit reason codes.

## Deterministic text-mode fallback

Fallback is allowed only when all safeguards pass.

Required safeguards:

- explicit `--allow-text-fallback` intent (or equivalent safe-edit mode default with visible notice)
- scope must be explicit (`--scope`) and finite
- target must be unambiguous under current scope
- preview diff summary must be generated before apply
- `make validate` must pass after apply

Fallback must be blocked when:

- operation is `extract` and structural boundary cannot be proven safely
- rename target appears in mixed semantic contexts (symbol and plain text collisions)
- scope includes generated/vendor files without explicit include override

## Reason code contract

Use deterministic reason codes for explainability and testing:

- `safe_edit_allowed`
- `safe_edit_lsp_unavailable`
- `safe_edit_ast_unavailable`
- `safe_edit_fallback_blocked_scope`
- `safe_edit_fallback_blocked_ambiguity`
- `safe_edit_fallback_requires_opt_in`
- `safe_edit_validation_failed`

## Non-goals for Task 18.1

- no adapter/runtime implementation yet
- no command registration changes yet
- no cross-language mutation behavior yet
