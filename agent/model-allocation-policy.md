# Agent Model Allocation Policy

This policy keeps OpenAI Codex as the default path and uses Copilot-provided non-OpenAI models only as alternatives.

## Provider Priority

1. OpenAI Codex (default)
2. Copilot high-reasoning alternative (only when OpenAI is unavailable or constrained)
3. Copilot balanced/fast alternative (throughput fallback)

## Effort Bands

| Band | Routing Category | Default Model | Reasoning | Use Case |
| --- | --- | --- | --- | --- |
| fast | `quick` | `openai/gpt-5.1-codex-mini` | `low` | high-frequency discovery/verification loops |
| standard | `balanced` | `openai/gpt-5.3-codex` | `medium` | normal implementation and planning |
| complex | `deep` | `openai/gpt-5.3-codex` | `high` | multi-module architecture/debug work |
| critical | `critical` | `openai/gpt-5.3-codex` | `xhigh` | final risk review, release/security sign-off |

## Default Agent Routing

| Agent | Default Band | Category |
| --- | --- | --- |
| `orchestrator` | standard | `balanced` |
| `explore` | fast | `quick` |
| `verifier` | fast | `quick` |
| `release-scribe` | fast | `quick` |
| `librarian` | standard | `balanced` |
| `strategic-planner` | standard | `balanced` |
| `ambiguity-analyst` | standard | `balanced` |
| `reviewer` | critical | `critical` |
| `oracle` | critical | `critical` |
| `plan-critic` | critical | `critical` |

## Fallback Guidance

- Keep the same effort band when switching providers.
- Prefer a Copilot high-reasoning model for `critical`/`deep` fallback.
- Prefer a Copilot low-latency model for `quick` fallback.
- Return to OpenAI Codex as soon as available.

## Operator Commands

```text
/model-routing set-category quick
/model-routing set-category balanced
/model-routing set-category deep
/model-routing set-category critical
/model-routing resolve --json
```
