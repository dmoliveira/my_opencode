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
| standard | `visual` | `openai/gpt-5.3-codex` | `medium` | browser-first UX/UI audits and design-heavy refinement |
| standard | `writing` | `openai/gpt-5.3-codex` | `medium` | planning capture and writing-heavy artifact work |
| complex | `deep` | `openai/gpt-5.4-codex` | `medium` | multi-module architecture/debug work |
| critical | `critical` | `openai/gpt-5.4-codex` | `medium` | final risk review, release/security sign-off |

## Default Agent Routing

| Agent | Default Band | Category |
| --- | --- | --- |
| `orchestrator` | standard | `balanced` |
| `tasker` | standard | `writing` |
| `explore` | fast | `quick` |
| `verifier` | fast | `quick` |
| `release-scribe` | fast | `quick` |
| `experience-designer` | standard | `visual` |
| `librarian` | standard | `balanced` |
| `strategic-planner` | complex | `deep` |
| `ambiguity-analyst` | complex | `deep` |
| `reviewer` | critical | `critical` |
| `oracle` | critical | `critical` |
| `plan-critic` | critical | `critical` |

## Fallback Guidance

- Keep the same effort band when switching providers.
- Prefer a Copilot high-reasoning model for `critical`/`deep` fallback.
- Prefer a Copilot low-latency model for `quick` fallback.
- Return to OpenAI Codex as soon as available.

## Effort-Band Fallback Chains

| Category | Primary | Fallback 1 | Fallback 2 |
| --- | --- | --- | --- |
| `quick` | `openai/gpt-5.1-codex-mini` | Copilot low-latency coding model | Copilot balanced coding model |
| `balanced` | `openai/gpt-5.3-codex` (`medium`) | Copilot balanced reasoning model | Copilot high-reasoning model |
| `deep` | `openai/gpt-5.4-codex` (`medium`) | Copilot high-reasoning model | Copilot balanced reasoning model |
| `critical` | `openai/gpt-5.4-codex` (`medium`) | Copilot highest-reasoning available model | Copilot high-reasoning model |
| `visual` | `openai/gpt-5.3-codex` (`medium`) | Copilot visual-capable reasoning model | Copilot balanced model |
| `writing` | `openai/gpt-5.3-codex` (`medium`) | Copilot strong writing/reasoning model | Copilot balanced model |

## Provider Outage Behavior

- OpenAI partial outage: keep current category, switch to category-equivalent Copilot fallback, and mark output as fallback-sourced for review.
- OpenAI full outage: continue with Copilot fallback chains and enforce an extra `reviewer` pass before done claims.
- Recovery state: once OpenAI is healthy, switch back on the next task boundary (avoid mid-task model churn).

## Operator Commands

```text
/model-routing set-category quick
/model-routing set-category balanced
/model-routing set-category visual
/model-routing set-category writing
/model-routing set-category deep
/model-routing set-category critical
/model-routing resolve --json
```
