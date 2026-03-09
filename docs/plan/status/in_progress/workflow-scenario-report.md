# Workflow Scenario Reliability Report

- Total scenarios: 10
- Correct actions: 10
- Accuracy: 100%

## By Workflow
- todo-continuation-enforcer: 8/8 (100%)
- done-proof-enforcer: 2/2 (100%)

## Scenario Results
- todo-pending-marker: PASS | todo-continuation-enforcer | pending_marker | expected=inject_prompt actual=inject_prompt
- todo-chained-progress-sequence: PASS | todo-continuation-enforcer | progress_sequence | expected=inject_3_times actual=inject_3_times
- todo-multi-idle-cooldown: PASS | todo-continuation-enforcer | cooldown | expected=inject_once actual=inject_once
- todo-stop-resume-cycle: PASS | todo-continuation-enforcer | stop_resume | expected=inject_once_after_resume actual=inject_once_after_resume
- todo-epic-progress-pending: PASS | todo-continuation-enforcer | progress_summary | expected=inject_prompt actual=inject_prompt
- todo-epic-progress-complete: PASS | todo-continuation-enforcer | progress_summary | expected=no_inject actual=no_inject
- todo-soft-cue-armed: PASS | todo-continuation-enforcer | soft_cue | expected=inject_prompt actual=inject_prompt
- todo-soft-cue-unarmed: PASS | todo-continuation-enforcer | soft_cue | expected=no_inject actual=no_inject
- done-proof-missing-proof: PASS | done-proof-enforcer | missing_proof | expected=pending_validation actual=pending_validation
- done-proof-complete: PASS | done-proof-enforcer | complete_proof | expected=keep_done actual=keep_done
