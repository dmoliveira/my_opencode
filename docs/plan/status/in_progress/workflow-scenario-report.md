# Workflow Scenario Reliability Report

- Total scenarios: 5
- Correct actions: 5
- Accuracy: 100%

## By Workflow
- todo-continuation-enforcer: 3/3 (100%)
- done-proof-enforcer: 2/2 (100%)

## Scenario Results
- todo-pending-marker: PASS | todo-continuation-enforcer | pending_marker | expected=inject_prompt actual=inject_prompt
- todo-soft-cue-armed: PASS | todo-continuation-enforcer | soft_cue | expected=inject_prompt actual=inject_prompt
- todo-soft-cue-unarmed: PASS | todo-continuation-enforcer | soft_cue | expected=no_inject actual=no_inject
- done-proof-missing-proof: PASS | done-proof-enforcer | missing_proof | expected=pending_validation actual=pending_validation
- done-proof-complete: PASS | done-proof-enforcer | complete_proof | expected=keep_done actual=keep_done
