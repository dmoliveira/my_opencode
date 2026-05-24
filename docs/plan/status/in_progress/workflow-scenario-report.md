# Workflow Scenario Reliability Report

- Total scenarios: 2
- Correct actions: 1
- Overall accuracy (correct / total scenarios): 50%
- By Workflow shows correct / total scenario counts for each workflow bucket.

## By Workflow (correct / total scenarios per workflow)
- mistake-ledger: 0/1 (0%)
- todo-continuation-enforcer: 1/1 (100%)

## Failure focus

- Start with `mistake-ledger` (0/1); it is the weakest workflow bucket in this run.

- mistake-ledger-llm-deferral: FAIL | mistake-ledger | semantic_deferral | expected=write_ledger_entry actual=skip

## Scenario Results (one row per scenario)
- todo-pending-marker: PASS | todo-continuation-enforcer | pending_marker | expected=inject_prompt actual=inject_prompt
- mistake-ledger-llm-deferral: FAIL | mistake-ledger | semantic_deferral | expected=write_ledger_entry actual=skip
