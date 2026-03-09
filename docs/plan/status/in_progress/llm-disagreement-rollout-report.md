# LLM Disagreement Rollout Report

- Total disagreements: 6
- Hooks with disagreements: 2

## Recommendations

- validation-evidence-ledger: tune (4)
  - moderate disagreement volume; refine prompt, context shaping, or fallback policy
  - thresholds: investigate>=10, tune>=4, observe>=1

- delegation-fallback-orchestrator: observe (2)
  - low disagreement volume; continue shadow sampling before promotion
  - thresholds: investigate>=10, tune>=4, observe>=1

## Top disagreement pairs

- validation-evidence-ledger: not_validation -> test (4)

- delegation-fallback-orchestrator: no_match -> delegation_invalid_arguments (2)
