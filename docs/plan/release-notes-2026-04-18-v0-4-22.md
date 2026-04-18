# Release Notes Draft (2026-04-18) - v0.4.22

## Included PRs
- #507
- #508
- #510

## Highlights
- harden conversation recovery for stalled idle turns and reduce protected-branch/dependency-guard false positives
- restore release-check cleanliness by making `scripts/selftest.py` revert repo-local summary/config side effects after validation
- add release-readiness notes for the conversation runtime remediation slice

## Validation Evidence
- `make validate`
- `python3 scripts/selftest.py`
- `make install-test`
- `npm --prefix plugin/gateway-core run lint`
- `npm --prefix plugin/gateway-core run build`
- `node --test plugin/gateway-core/test/session-recovery-hook.test.mjs plugin/gateway-core/test/workflow-conformance-guard-hook.test.mjs plugin/gateway-core/test/dependency-risk-guard-hook.test.mjs plugin/gateway-core/test/todo-continuation-enforcer-hook.test.mjs`
- `make release-check VERSION=0.4.22`
