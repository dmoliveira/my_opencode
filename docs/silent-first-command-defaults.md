# Silent-first command defaults

Use this guide when you want high-signal command output without burning tokens on long green-path logs.

## Goal

Prefer the lowest-noise output that still preserves:

- failure visibility
- machine-readable status when automation needs it
- enough operator context to make the next decision

Default escalation ladder:

1. silent or structured output first
2. concise human summary second
3. verbose raw logs only on failure, debugging, or explicit request

## Core rule

Pick one of these as the first choice:

- `--json` when another command, wrapper, or runtime parser will consume the output
- quiet/silent flags when you only need pass/fail or artifact side effects
- short/porcelain/stat output when the tool has a stable concise human mode

Only expand to full logs when:

- the command fails
- the command is being debugged
- the user explicitly asks for raw output
- the output itself is the artifact being inspected

## Priority matrix

| Tool family | Silent-first default | Use first when | Escalate to |
|---|---|---|---|
| `curl` | `-fsSL` | fetch body or fail fast | headers, verbose, trace only for network/debug cases |
| `gh` | `--json <fields>` | structured issue/PR/repo/checks queries | full text views only when reviewing prose or comments |
| `git status` | `--short --branch` | worktree state checks | full status only when human explanation matters |
| `git diff` | `--stat` or targeted diff | size/scope checks | full patch only when content review is required |
| `git log` | `--oneline -n <n>` | recent commit style/history | fuller format only for authorship/date/detail review |
| `rg` | narrow include/path first | locate files or matches | wide repo scans only when narrowing fails |
| `npm` | `--silent` where safe | green-path install/bootstrap | normal logs on failure |
| `pnpm` | `--reporter=silent` | green-path install/bootstrap | standard reporter on failure |
| `yarn` | `--silent` | green-path install/bootstrap | normal logs on failure |
| `uv` | concise subcommand output | dependency/test/lint flows | verbose traces only for debugging |
| `pytest` | `-q` | normal passing test runs | `-vv` or failure detail when triaging |
| `ruff` | default concise output | lint/format checks | verbose only when rule-level debugging matters |
| `docker` | targeted inspect/status commands | image/container state checks | streaming logs only when runtime behavior matters |
| `tmux` | focused status/list commands | session existence and layout checks | pane capture only when live-state evidence is required |

## Tool-specific defaults

### `curl`

Preferred first option for simple fetch-or-fail flows:

```bash
curl -fsSL <url>
```

Why:

- `-f` fails on HTTP errors
- `-sS` suppresses progress noise but still prints errors
- `-L` follows redirects when expected

Escalate only if needed:

- add `-I` for headers only
- add `-v` for connection/debug details
- drop `-f` when the HTTP error body is the useful artifact

### `gh`

Prefer JSON over prose when the output feeds the runtime or another script:

```bash
gh pr status --json currentBranch,createdBy,mergeStateStatus
gh issue list --json number,title,state,url
gh repo view --json name,defaultBranchRef
```

Prefer narrow fields over broad JSON dumps.

### `git`

Preferred first options:

```bash
git status --short --branch
git diff --stat
git log --oneline -n 5
```

Escalate to full patch output only when reviewing the actual code/text change.

### `rg`

Reduce output before searching wider:

- limit by path
- limit by file pattern
- search the most likely directory first

Prefer targeted searches like:

```bash
rg "pattern" scripts --glob "*.py"
```

over broad repo-wide scans when the scope is already known.

### package managers

Preferred green-path forms:

```bash
npm install --yes --silent
pnpm install --reporter=silent
yarn install --silent
```

Keep full logs for failure triage, peer-dependency issues, postinstall debugging, or fresh-environment validation where warnings still matter even on success.

### tests and validation

Use quiet success output first:

```bash
pytest -q
ruff check .
uv run pytest -q
```

Escalate only when a failure needs richer context.

### `docker`

Prefer state queries first:

```bash
docker ps
docker images
docker inspect <id>
```

Avoid defaulting to streaming logs unless runtime behavior is the thing being investigated.

## Slash-command and wrapper guidance

When building or refining runtime slash commands:

- prefer `--json` when a wrapper or hook will parse the result
- prefer concise status payloads over mixed prose + status text
- keep human summaries short on success
- print richer diagnostics only on failure paths

Good examples already used in this repo:

- `/gateway concise status --json`
- `/image access --json`
- `/delivery status --json`
- `/workflow status --json`
- `/agent-doctor --json`

## When not to be silent-first

Do **not** suppress detail by default when:

- the command is destructive
- the command is interactive or stateful and logs are the evidence
- the user asked for full output
- the result is ambiguous without full context
- a failure is already being triaged

## Recommended authoring pattern for new commands

For new runtime commands, prefer this order:

1. return a stable JSON payload for automation
2. keep success-path human output to a short summary block
3. attach detailed diagnostics only on warnings/failures
4. document the quiet default and the escalation path together

That keeps the runtime cheap in tokens while preserving debuggability.
