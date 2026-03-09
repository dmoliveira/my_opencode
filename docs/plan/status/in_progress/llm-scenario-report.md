# LLM Scenario Reliability Report

- Total scenarios: 5
- Correct decisions: 5
- Accuracy: 100%

## By Hook
- auto-slash-command: 1/1 (100%)
- delegation-fallback-orchestrator: 1/1 (100%)
- done-proof-enforcer: 1/1 (100%)
- provider-error-classifier: 1/1 (100%)
- validation-evidence-ledger: 1/1 (100%)

## By Request Type
- completion_evidence: 1/1 (100%)
- contamination: 1/1 (100%)
- delegation_failure: 1/1 (100%)
- provider_error: 1/1 (100%)
- validation_wrapper: 1/1 (100%)

## Scenario Results
- auto-slash-chatrole: PASS | auto-slash-command | contamination | expected=D actual=D | 7529ms
- provider-overload-contamination: PASS | provider-error-classifier | provider_error | expected=O actual=O | 7409ms
- done-proof-smoke-checks: PASS | done-proof-enforcer | completion_evidence | expected=Y actual=Y | 4830ms
- validation-wrapper-test: PASS | validation-evidence-ledger | validation_wrapper | expected=T actual=T | 6099ms
- fallback-invalid-arguments: PASS | delegation-fallback-orchestrator | delegation_failure | expected=I actual=I | 7429ms
