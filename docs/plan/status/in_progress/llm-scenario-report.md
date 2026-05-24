# LLM Scenario Reliability Report

- Total scenarios: 3
- Correct decisions: 2
- Overall accuracy (correct / total scenarios): 66.7%
- By Hook and By Request Type sections show correct / total scenario counts for each bucket.

## By Hook (correct / total scenarios per hook)
- auto-slash-command: 1/2 (50%)
- provider-error-classifier: 1/1 (100%)

## By Request Type (correct / total scenarios per request type)
- contamination: 1/2 (50%)
- provider_error: 1/1 (100%)

## Failure focus

- Start with `auto-slash-command` (1/2); it is the weakest hook bucket in this run.

- auto-slash-chatrole: FAIL | auto-slash-command | contamination | expected=D actual=(none)

## Scenario Results (one row per scenario)
- auto-slash-chatrole: FAIL | auto-slash-command | contamination | expected=D actual=(none) | 6942ms
- auto-slash-noop: PASS | auto-slash-command | contamination | expected=N actual=N | 5687ms
- provider-rate-limit: PASS | provider-error-classifier | provider_error | expected=R actual=R | 6034ms
