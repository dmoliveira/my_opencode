# Knowledge Capture Policy Contract (Epic 27 Task 27.1)

This contract defines how completed-task learnings are captured, scored, and approved so future runs can reuse reliable guidance.

## Goals

- Convert merged-task outcomes into reusable knowledge with consistent structure.
- Keep published guidance high-signal by enforcing deterministic quality gates.
- Make entries searchable by subsystem, workflow stage, and risk profile.

## Entry Types

All knowledge entries must use exactly one primary `entry_type`:

1. `pattern`: repeatable approach that improved outcome quality, speed, or reliability.
2. `pitfall`: anti-pattern or failure mode with concrete prevention guidance.
3. `checklist`: ordered validation sequence for recurring workflows.
4. `rule_candidate`: candidate guardrail suitable for future `/rules` or policy automation.

Required fields for every entry:

- `entry_id` (stable slug)
- `entry_type`
- `title`
- `summary`
- `evidence_sources` (PR links, issue IDs, commit SHAs, validation logs)
- `confidence_score` (0-100)
- `status` (`draft|review|published|archived`)
- `created_at`
- `updated_at`

## Confidence Model

`confidence_score` must be derived from explicit scoring factors to avoid subjective drift.

Scoring factors:

- `evidence_quality` (0-40): objective proof quality (tests, reproducible outcomes, post-merge stability).
- `repeatability` (0-30): observed repeat success across tasks/repos.
- `scope_clarity` (0-20): clear boundaries for when guidance applies.
- `freshness` (0-10): recency and continued relevance.

Score interpretation:

- `0-49`: low confidence (must remain `draft`)
- `50-74`: medium confidence (eligible for `review` only)
- `75-100`: high confidence (eligible for `published` after approval)

## Approval Workflow

State transitions are deterministic:

1. `draft -> review`
2. `review -> published`
3. `published -> archived`

Quality gates per transition:

- `draft -> review`
  - at least one linked source from merged work
  - non-empty remediation or adoption guidance
  - confidence score >= 50
- `review -> published`
  - at least two evidence sources, including one validation artifact
  - confidence score >= 75
  - explicit reviewer approval metadata (`approved_by`, `approved_at`)
- `published -> archived`
  - superseded, stale, or invalidated reason recorded in `archive_reason`

Blocking rules:

- Entries without evidence links cannot advance beyond `draft`.
- Entries tagged `high_risk` require two reviewer approvals before publish.
- Rule candidates with confidence < 85 cannot be auto-suggested for enforcement.

## Tagging and Search Metadata

Each entry must include structured tags for retrieval and filtering.

Required metadata:

- `tags.domain` (for example: `release`, `hotfix`, `health`, `routing`)
- `tags.stage` (`plan|implement|validate|ship|operate`)
- `tags.risk` (`low|medium|high`)
- `tags.artifacts` (paths or subsystem IDs)
- `applies_to` (command names, task archetypes, or repo contexts)

Search index requirements:

- normalized keyword tokens from `title`, `summary`, and `tags`
- source references indexed by `issue_id`, `pr_number`, and `commit_sha`
- recency sort by `updated_at`
- confidence-aware ranking (`published` + higher confidence first)

## Output Contract

Knowledge capture/read APIs must expose:

- `entry` payload (full record)
- `quality_gate_results` (pass/fail list with reason codes)
- `approval_state` (required approvers, approvals received)
- `search_metadata` (tokens, ranking fields)
- `next_actions` (promote, revise, archive guidance)

Minimum reason codes:

- `missing_evidence_sources`
- `insufficient_confidence`
- `missing_reviewer_approval`
- `high_risk_requires_second_approval`
- `stale_entry_detected`

All failed quality gates must include actionable remediation text.
