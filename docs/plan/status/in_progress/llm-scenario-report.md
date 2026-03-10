# LLM Scenario Reliability Report

- Total scenarios: 11
- Correct decisions: 11
- Accuracy: 100%

## By Hook
- auto-slash-command: 2/2 (100%)
- delegation-fallback-orchestrator: 2/2 (100%)
- done-proof-enforcer: 2/2 (100%)
- provider-error-classifier: 3/3 (100%)
- validation-evidence-ledger: 2/2 (100%)

## By Request Type
- completion_evidence: 2/2 (100%)
- contamination: 1/1 (100%)
- delegation_failure: 2/2 (100%)
- no_op: 2/2 (100%)
- provider_error: 3/3 (100%)
- validation_wrapper: 1/1 (100%)

## Scenario Results
- auto-slash-chatrole: PASS | auto-slash-command | contamination | expected=D actual=D | 6942ms
- auto-slash-noop: PASS | auto-slash-command | no_op | expected=N actual=N | 5687ms
- provider-overload-contamination: PASS | provider-error-classifier | provider_error | expected=O actual=O | 5365ms
- provider-rate-limit: PASS | provider-error-classifier | provider_error | expected=R actual=R | 6034ms
- provider-free-usage: PASS | provider-error-classifier | provider_error | expected=F actual=F | 6892ms
- done-proof-smoke-checks: PASS | done-proof-enforcer | completion_evidence | expected=Y actual=Y | 7233ms
- done-proof-missing-evidence: PASS | done-proof-enforcer | completion_evidence | expected=N actual=N | 7647ms
- validation-wrapper-test: PASS | validation-evidence-ledger | validation_wrapper | expected=T actual=T | 6984ms
- validation-non-validation: PASS | validation-evidence-ledger | no_op | expected=N actual=N | 7242ms
- fallback-invalid-arguments: PASS | delegation-fallback-orchestrator | delegation_failure | expected=I actual=I | 6524ms
- fallback-runtime-error: PASS | delegation-fallback-orchestrator | delegation_failure | expected=R actual=R | 5896ms
