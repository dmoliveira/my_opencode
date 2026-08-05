# Duplicate CI run audit — 2026-08-06

Status: complete; no workflow change recommended
Scope revision: `9438f1b88d8278cc3795ab31e927bf2524c5e64d`
Evidence window: merged PRs `#689` through `#698`
Evidence captured: `2026-08-05T18:16:05Z`

## Decision

Pull-request and post-merge CI repeat a material amount of the same work, but the
audit did not prove that any of it can be suppressed while preserving the
merged-commit gate.

- The 20 selected runs used 6,150 job wall-seconds. This is a runner-time proxy,
  not billed usage.
- Exact, repository-local matched steps accounted for 1,955 seconds, or 31.8%
  of that proxy. The median was 216 seconds per PR/push pair, and 9 of 10 pairs
  cleared both predeclared pair thresholds.
- A broader same-gate comparison accounted for 2,597 seconds, or 42.2%, but it
  includes network-, dependency-, or commit-sensitive work and is not a safe
  suppression estimate.
- The post-merge run for PR `#691` failed on a gateway state-lock race even
  though its tested tree and workflow were byte-identical to the green PR run.
  PR `#692` fixed that race.
- The repository currently has no branch protection or ruleset requiring the
  PR checks. Removing the `push` jobs would therefore remove the only automated
  validation of the final commit on `main`.

Close `task_84` as an audit-only result. Do not change `.github/workflows/ci.yml`
and do not create a separate implementation task from this sample.

## Cohort and attribution

The cohort is the latest 10 consecutive PRs merged to `main` at collection time.
Each pair contains:

1. the final successful `pull_request` run for the merged head SHA; and
2. the `push` run whose head SHA is the PR's final squash-merge commit.

No selected run had a rerun attempt. The failed push for `#691` remained in the
fixed cohort and received zero strict overlap credit.

GitHub reports a PR run's API `head_sha` as the PR head, while checkout uses the
synthetic `refs/pull/<number>/merge` commit. The audit recovered that actual
checkout SHA from each run log, then compared its Git tree and CI workflow blob
with the final `main` commit. This matches GitHub's documented event semantics:
[`pull_request`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
uses the pull-request merge ref, while [`push`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push)
uses the tip commit pushed to the ref.

All 10 pairs had the same tested tree on both sides. All 20 runs also used CI
workflow blob `ec92cd8be97a5c7dad9780b285090f5f10ab2948`.

| PR | Actual PR checkout → `main` commit | PR run / push run | Result | PR + push runner wall-s | PR / push end-to-end-s | Strict overlap | Broader same-gate |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |
| [#698](https://github.com/dmoliveira/my_opencode/pull/698) | `66fda86` → `9438f1b` | [31031737098](https://github.com/dmoliveira/my_opencode/actions/runs/31031737098) / [31032065503](https://github.com/dmoliveira/my_opencode/actions/runs/31032065503) | pass / pass | 325 + 340 | 210 / 227 | 234s (35.2%) | 298s |
| [#697](https://github.com/dmoliveira/my_opencode/pull/697) | `55286c2` → `4d97e3e` | [31025159171](https://github.com/dmoliveira/my_opencode/actions/runs/31025159171) / [31025597228](https://github.com/dmoliveira/my_opencode/actions/runs/31025597228) | pass / pass | 367 + 320 | 227 / 207 | 238s (34.6%) | 300s |
| [#696](https://github.com/dmoliveira/my_opencode/pull/696) | `ecf4376` → `b022a22` | [31016131247](https://github.com/dmoliveira/my_opencode/actions/runs/31016131247) / [31016511226](https://github.com/dmoliveira/my_opencode/actions/runs/31016511226) | pass / pass | 307 + 367 | 205 / 237 | 211s (31.3%) | 263s |
| [#695](https://github.com/dmoliveira/my_opencode/pull/695) | `8f80c8c` → `df2da2a` | [31006554428](https://github.com/dmoliveira/my_opencode/actions/runs/31006554428) / [31006912613](https://github.com/dmoliveira/my_opencode/actions/runs/31006912613) | pass / pass | 307 + 350 | 198 / 250 | 220s (33.5%) | 281s |
| [#694](https://github.com/dmoliveira/my_opencode/pull/694) | `cd313e0` → `13e5758` | [30998545117](https://github.com/dmoliveira/my_opencode/actions/runs/30998545117) / [30998828473](https://github.com/dmoliveira/my_opencode/actions/runs/30998828473) | pass / pass | 297 + 293 | 205 / 198 | 211s (35.8%) | 272s |
| [#693](https://github.com/dmoliveira/my_opencode/pull/693) | `610c51f` → `c4c1d16` | [30974290245](https://github.com/dmoliveira/my_opencode/actions/runs/30974290245) / [30974495796](https://github.com/dmoliveira/my_opencode/actions/runs/30974495796) | pass / pass | 299 + 291 | 203 / 188 | 214s (36.3%) | 273s |
| [#692](https://github.com/dmoliveira/my_opencode/pull/692) | `ebb0f43` → `efd98ce` | [30972655600](https://github.com/dmoliveira/my_opencode/actions/runs/30972655600) / [30972822845](https://github.com/dmoliveira/my_opencode/actions/runs/30972822845) | pass / pass | 266 + 301 | 169 / 193 | 191s (33.7%) | 238s |
| [#691](https://github.com/dmoliveira/my_opencode/pull/691) | `1f9e383` → `c0793bc` | [30963643389](https://github.com/dmoliveira/my_opencode/actions/runs/30963643389) / [30963872652](https://github.com/dmoliveira/my_opencode/actions/runs/30963872652) | pass / **fail** | 317 + 148 | 217 / 112 | 0s (0.0%) | 117s |
| [#690](https://github.com/dmoliveira/my_opencode/pull/690) | `c53f2fe` → `e3e8fc8` | [30962371985](https://github.com/dmoliveira/my_opencode/actions/runs/30962371985) / [30962594023](https://github.com/dmoliveira/my_opencode/actions/runs/30962594023) | pass / pass | 331 + 312 | 201 / 207 | 218s (33.9%) | 277s |
| [#689](https://github.com/dmoliveira/my_opencode/pull/689) | `80cf5d4` → `acec9ad` | [30913770120](https://github.com/dmoliveira/my_opencode/actions/runs/30913770120) / [30914110426](https://github.com/dmoliveira/my_opencode/actions/runs/30914110426) | pass / pass | 305 + 307 | 208 / 195 | 218s (35.6%) | 278s |

## Measurement method

For each run:

- queue time is the first job start minus run creation time;
- active makespan is the last job completion minus the first job start;
- end-to-end time is the last job completion minus run creation time; and
- runner wall-seconds is the sum of each job's completion time minus start time.

Summed job durations measure occupied job time across parallel jobs. They do not
measure critical-path savings, GitHub billing, or cost. GitHub documents billed
minutes as total processing time by runner type, with different treatment by
runner and repository type. See
[`About billing for GitHub Actions`](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions).

Steps were paired one-to-one by exact job name, step number, and step name. A
strict pair contribution is `min(PR step duration, push step duration)` and only
includes successful steps with identical workflow text, shell, environment,
action dependencies, tested tree, and workflow blob. The strict set was:

- `Verify minimum Python contract`;
- `Validate scripts and generated agent contracts`;
- `Gate deterministic gateway workflows`; and
- `Run deterministic self-tests`.

Checkout, setup, post, and completion steps were excluded. The following steps
were counted only in the broader same-gate observation:

- `Validate gateway-core plugin build and tests`, because it combines `npm ci`
  network/cache behavior with local tests;
- `Gate provider-boundary session resume regressions`, because it depends on a
  separately downloaded OpenCode package; and
- `Installer smoke test`, because it reads the event-specific `GITHUB_SHA`.

The package-install-only step was excluded from both overlap measures. A missing,
renamed, repeated, retried, matrix-expanded, failed, event-conditioned, secret-
dependent, artifact-producing, or side-effecting step receives zero strict
credit. Parallel step durations are never presented as wall-clock savings.

The materiality threshold was declared before collection:

- strict overlap at least 20% of combined pair runner wall-seconds;
- median strict overlap at least 120 seconds per pair; and
- both thresholds met by at least 80% of the 10 pairs.

The result was 31.8%, 216 seconds, and 9 of 10 pairs. Setting the largest pair
overlap to zero still yields 27.9%, a 212.5-second median, and 8 of 10 passing
pairs. Excluding rerun overhead has no effect because every selected run was
attempt 1.

## Critical path and check coverage

The two jobs start in parallel. `validate` was the last job to finish in 19 of
20 runs. The exception was the failed `#691` push, where `validate` stopped early
and `python-minimum` finished last.

| Signal | PR runs | Push runs |
| --- | ---: | ---: |
| Median queue time | 3.0s | 2.5s |
| Median active makespan | 202.5s | 197.5s |
| Median end-to-end time | 205.0s | 202.5s |
| Median runner wall-time proxy | 307.0s | 309.5s |
| Total runner wall-time proxy | 3,121s | 3,029s |

Both events execute the same coverage:

| Job | Coverage on both PR and push |
| --- | --- |
| `python-minimum` | Python 3.11 minimum-runtime contract, `make validate`, and `make selftest` |
| `validate` | Python 3.12 validation; Node 22 gateway build, lint, and tests; pinned OpenCode provider-boundary resume gate; deterministic workflow gate; self-tests; installer smoke test |

`Docs Automation` is a separate, path-filtered `main` push workflow. It syncs the
wiki and deploys GitHub Pages for documentation changes; it does not consume the
CI result and is not part of the duplicate cohort.

## Why suppression is not safe

The failed `#691` pair is decisive. The PR checkout
`1f9e383110bcb0bef1e8af26f6483ddba83793b8` and merged commit
`c0793bcece6821a0addf2cbf622e0a472e77f4a3` both resolve to tree
`d267d31290b96bd7d9805a9c011aa6710d7d932b` and the same CI workflow blob. The PR
run passed. The push run then failed
`two Node writers preserve disjoint domains while readers observe valid JSON`
with `GatewayStateProtocolError: gateway state lock token is unsafe`. The next
PR, `#692`, fixed the legitimate lock-turnover race and passed both runs.

That failure was environment/timing-sensitive rather than a tree difference.
Reusing the green PR result would have hidden it. Keeping only the broader
environment-sensitive steps would also remove repository validation from the
final commit, so it would not preserve the current release gate.

Current policy and side-effect evidence, captured at the timestamp above:

- `GET /branches/main/protection` returned `404 Branch not protected`;
- `GET /rulesets` returned an empty list;
- Actions default workflow permission is `read`, and workflows cannot approve
  pull-request reviews;
- CI has no artifact upload/download, environment, deploy, publish, attestation,
  repository dispatch, or `workflow_run` consumer; and
- the only deployment environment is `github-pages`, restricted to `main` and
  used by `Docs Automation`, not CI.

GitHub treats status checks as required only when branch protection or an
applicable ruleset says so. See
[`About protected branches`](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging)
and [`About rulesets`](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).
The repository's delivery process still requires green PR and post-merge CI,
but GitHub does not currently enforce either through branch policy.

Historical protection settings and external status consumers are not available
from the collected evidence. That limitation independently prevents a safe
suppression recommendation. Safely suppressible work is therefore recorded as
zero even though repeated execution is material.

## Reproduction

The audit used GitHub CLI and Git object checks. Representative commands:

```bash
gh pr list --state merged --base main --limit 10 \
  --json number,headRefName,headRefOid,mergeCommit,mergedAt,url
gh run list --workflow ci.yml --limit 100 \
  --json databaseId,event,headBranch,headSha,conclusion,createdAt,attempt,url
gh run view 31031737098 --log
gh api 'repos/dmoliveira/my_opencode/actions/runs/31031737098/jobs?per_page=100'
gh api repos/dmoliveira/my_opencode/git/commits/66fda86394f686469f804b359c6482a0f8ce4279
gh api 'repos/dmoliveira/my_opencode/contents/.github/workflows/ci.yml?ref=66fda86394f686469f804b359c6482a0f8ce4279'
gh api repos/dmoliveira/my_opencode/branches/main/protection
gh api repos/dmoliveira/my_opencode/rulesets
```

As an independent Git-object check, the newest pair (`#698`) and the failed pair
(`#691`) were fetched by exact SHA and compared with `git rev-parse <sha>^{tree}`
and `git rev-parse <sha>:.github/workflows/ci.yml`. Both checks reproduced the
REST API's tree and workflow equality.

## Limitations and reopen gate

- The sample is consecutive and current, but covers 10 merges over roughly one
  day rather than seasonal or release-period variation.
- Job and step timestamps have one-second API resolution.
- The overlap metrics do not model billing, cache hit quality, queue scarcity,
  or a controlled workflow change.
- Tree and workflow equality prove content equality, not identical event
  payloads, commit topology, runner images, caches, network state, or timing.
- Current GitHub policy queries do not reconstruct historical policy.

Reopen optimization only with a design that keeps an enforced final-commit gate,
preserves timing-sensitive gateway coverage, falls back safely when no verified
PR result exists, and demonstrates runner or wall-time improvement in a
controlled comparison. No such design is proven by this audit.
