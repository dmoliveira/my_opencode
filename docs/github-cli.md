# GitHub CLI Patterns

Use this file for automation-safe GitHub CLI usage in this repo.

## Default split

- Use `gh issue` and `gh pr` for read/status flows.
- Prefer `gh api` for automation-critical writes when deterministic behavior matters.

## Read and status

```bash
gh issue list --state open --limit 20 --json number,title,state,url
gh issue view <id> --json number,title,state,body,url
gh pr status --json currentBranch,createdBy,mergeStateStatus
gh pr view <id> --json number,title,state,url,headRefName,baseRefName
gh pr checks <id>
gh repo view --json name,defaultBranchRef,url
```

## Preferred PR creation

Use `gh api` when wrappers or local guardrails make `gh pr create` less predictable.

```bash
gh api repos/<owner>/<repo>/pulls \
  -f title='docs: title' \
  -f head='<branch>' \
  -f base='main' \
  -f body='## Summary\n- ...\n\n## Validation\n- make validate\n- git diff --check'
```

## Common write operations

```bash
gh issue comment <id> --body "status update"
gh issue close <id>

gh api repos/<owner>/<repo>/issues/<id>/comments -f body='status update'
gh api repos/<owner>/<repo>/issues/<id>/labels -f labels='docs,ready'
```

## Notes

- Keep commands non-interactive and CI-safe.
- Re-check issue/PR state after `git fetch --all --prune --quiet` before implementation.
- Prefer structured `--json` fields for status gathering and final evidence capture.
