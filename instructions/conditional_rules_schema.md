# Conditional Rules Schema

Epic 9 Task 9.1 defines the schema and precedence contract for conditional rule injection.

## Rule sources and discovery

Rules are discovered from layered scopes in deterministic order:

1. user scope: `~/.config/opencode/rules/**/*.md`
2. project scope: `.opencode/rules/**/*.md`

Project scope has higher precedence when two rules have equivalent priority and target overlap.

## Rule file format

Each rule file is markdown with YAML frontmatter.

Required frontmatter fields:

- `description`: short purpose summary
- `priority`: integer from `0` to `100` (higher applies first)

Optional frontmatter fields:

- `globs`: list of file globs where rule applies
- `alwaysApply`: boolean forcing rule application regardless of file path
- `id`: stable rule identifier (fallback: normalized file stem)
- `tags`: list of category tags for diagnostics/reporting

Rule body (markdown after frontmatter) is the instruction payload injected at runtime.

## Matching semantics

- If `alwaysApply` is `true`, the rule always applies.
- Else if `globs` is present, any glob match applies the rule.
- Else the rule is considered inactive by default.

Glob matching uses workspace-relative POSIX-style paths.

## Conflict resolution

Sort and merge rules by deterministic key:

1. descending `priority`
2. scope precedence (`project` before `user`)
3. lexical `id`

Conflicts are resolved by first-writer-wins over normalized rule ids after sorting.

Diagnostics must surface:

- winning rule id and source
- overridden/conflicting rule ids
- effective ordered rule stack for any target path

## Config controls (for Task 9.3)

Planned config controls:

- `rules.enabled` (default `true`)
- `rules.disabled_ids` (list)
- `rules.extra_paths` (additional discovery roots)

## Validation requirements

Reject and report rules when:

- required frontmatter keys are missing
- `priority` is out of range or non-numeric
- `globs` is not a list of strings
- `alwaysApply` is non-boolean

Validation errors should include rule path and actionable remediation.
