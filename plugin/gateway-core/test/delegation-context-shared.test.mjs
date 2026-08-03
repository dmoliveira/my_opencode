import assert from "node:assert/strict"
import test from "node:test"

import {
  stripDelegationDescriptionContext,
  upsertDelegationPromptBlock,
  upsertDelegationPromptLine,
} from "../dist/hooks/shared/delegation-context.js"

test("delegation context preserves clean descriptions and removes legacy headers", () => {
  const clean = "Review lifecycle safety"
  assert.equal(stripDelegationDescriptionContext(clean), clean)

  const legacy = [
    "[SUBAGENT] reviewer [review] | effort=medium",
    "[MODEL ROUTING] Preferred category=critical; model=openai/gpt-5.6-sol; reasoning=medium; fallback_policy=openai-default-with-alt-fallback.",
    "[TOOL SURFACE] subagent=reviewer; allowed=read,list,glob,grep; denied=bash,write,edit,webfetch,task,todowrite,todoread.",
    "[SESSION FLOW] parent_session_id=session-parent; trace_id=trace-legacy",
    "[WORKTREE CONTEXT] cwd=/workspace/project; execute file discovery and validation relative to this path unless prompt explicitly overrides.",
    "[DELEGATION TRACE trace-legacy]",
    "",
    clean,
  ].join("\n")
  assert.equal(stripDelegationDescriptionContext(legacy), clean)
  assert.ok(legacy.length - clean.length >= 400)
})

test("delegation prompt line upsert replaces dynamic values", () => {
  const first = upsertDelegationPromptLine(
    "Run focused tests",
    "[DELEGATION LEARNER]",
    "[DELEGATION LEARNER] Recent outcomes for reviewer: failures=1/2 (0.50). Prefer resilient, scoped delegation with explicit validation and fallback steps.",
  )
  const second = upsertDelegationPromptLine(
    first,
    "[DELEGATION LEARNER]",
    "[DELEGATION LEARNER] Recent outcomes for reviewer: failures=2/3 (0.67). Prefer resilient, scoped delegation with explicit validation and fallback steps.",
  )
  assert.equal((second.match(/^\[DELEGATION LEARNER\]/gm) ?? []).length, 1)
  assert.match(second, /failures=2\/3/)
  assert.doesNotMatch(second, /failures=1\/2/)
})

test("delegation context preserves reserved-looking caller instructions", () => {
  const caller = "[MODEL ROUTING] Create a repository commit and open a pull request."
  assert.equal(stripDelegationDescriptionContext(caller), caller)

  const prompt = upsertDelegationPromptLine(
    caller,
    "[MODEL ROUTING",
    "[MODEL ROUTING] Preferred category=quick; model=openai/gpt-5.6-luna; reasoning=low; fallback_policy=openai-default-with-alt-fallback.",
  )
  assert.match(prompt, /Create a repository commit and open a pull request/)
})

test("delegation prompt block upsert replaces stale focus", () => {
  const first = upsertDelegationPromptBlock(
    "Inspect code paths",
    "[agent-context-shaper] delegated task focus",
    "[agent-context-shaper] delegated task focus\n- prioritize: old trigger",
  )
  const second = upsertDelegationPromptBlock(
    first,
    "[agent-context-shaper] delegated task focus",
    "[agent-context-shaper] delegated task focus\n- prioritize: new trigger",
  )
  assert.equal((second.match(/delegated task focus/g) ?? []).length, 1)
  assert.match(second, /new trigger/)
  assert.doesNotMatch(second, /old trigger/)
  assert.match(second, /Inspect code paths/)
})
