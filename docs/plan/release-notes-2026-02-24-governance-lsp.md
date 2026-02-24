# Release Notes Draft (2026-02-24)

## Summary

- Shipped governance controls and reporting across runtime audit, authorization policy profiles, and trend reporting.
- Completed and validated the remaining LSP high-value wave with capability diagnostics, resource-operation guardrails, and diagnostics/code-action schema coverage.
- Kept command surface canonical while expanding deterministic selftest coverage for operator confidence.

## Included Pull Requests

### Governance and Audit

- [#300](https://github.com/dmoliveira/my_opencode/pull/300) - add runtime audit governance trail
- [#301](https://github.com/dmoliveira/my_opencode/pull/301) - add governance authorization profiles for risky operations
- [#302](https://github.com/dmoliveira/my_opencode/pull/302) - add governance audit reporting and coverage

### LSP High-Value Wave Completion

- [#303](https://github.com/dmoliveira/my_opencode/pull/303) - cover lsp capability preflight diagnostics
- [#304](https://github.com/dmoliveira/my_opencode/pull/304) - harden lsp resource operation guardrails
- [#305](https://github.com/dmoliveira/my_opencode/pull/305) - cover lsp diagnostics and code-action schemas

## Highlights

- `/audit` now covers status, list, report, export, and doctor with trend summaries available via `/audit report --days <n>`.
- `/governance` profile and authorization controls now gate risky operations with explicit reason codes and override pathways.
- LSP reliability improved with deterministic capability-preflight diagnostics and stronger rename resource-op safety checks.
- LSP diagnostics/code-actions parsing contracts are now covered by deterministic selftest fixtures.

## Validation Evidence

- `make validate`
- `make selftest`
- `make install-test`
- `pre-commit run --all-files`

## Milestone Sources

- `docs/plan/governance-milestones-changelog.md`
- `docs/plan/lsp-milestones-changelog.md`
