import assert from "node:assert/strict"
import test from "node:test"

import {
  stripDelegationDescriptionContext,
  stripDelegationPromptContext,
  upsertDelegationPromptBlock,
  upsertDelegationPromptLine,
} from "../dist/hooks/shared/delegation-context.js"

const FOCUS_MARKER = "[agent-context-shaper] delegated task focus"

function compactFocus(trigger, avoid) {
  return `${FOCUS_MARKER}: one objective, then return; prioritize: ${trigger}; avoid: ${avoid}; report extras as follow-ups; handoff: findings, evidence, confidence, affected paths, next action, validation; omit transcript.`
}

function legacyFocus(trigger, avoid) {
  return [
    FOCUS_MARKER,
    "- execute one delegated objective for this task call before returning control",
    `- prioritize: ${trigger}`,
    `- avoid: ${avoid}`,
    "- if you uncover extra work, report it as a follow-up instead of expanding scope in the same delegation",
  ].join("\n")
}

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

test("delegation prompt line upsert preserves caller bytes and is idempotent", () => {
  const line = "[DELEGATION TRACE trace-next]"
  for (const caller of ["", " \t ", "Task", "\nTask", "\n\n\nTask", "\r\nTask\r\n", "Task  \n\n"] ) {
    const expected = caller.length > 0 ? `${line}\n\n${caller}` : line
    const first = upsertDelegationPromptLine(caller, "[DELEGATION TRACE ", line)
    const second = upsertDelegationPromptLine(first, "[DELEGATION TRACE ", line)
    assert.equal(first, expected, JSON.stringify(caller))
    assert.equal(second, expected, JSON.stringify(caller))
    assert.equal(first.slice(caller.length > 0 ? line.length + 2 : line.length), caller)
  }
})

test("delegation prompt line replacement removes only immutable managed ranges", () => {
  const next = "[DELEGATION TRACE trace-next]"
  const staleOne = "[DELEGATION TRACE trace-old-1]"
  const staleTwo = "[DELEGATION TRACE trace-old-2]"
  const fixtures = [
    {
      original: `${staleOne}\n\n\nTask`,
      caller: "\nTask",
    },
    {
      original: `${staleOne}\r\n\r\nTask\r\n`,
      caller: "\r\n\r\nTask\r\n",
    },
    {
      original: `${staleOne}\n\n${staleTwo}\n\nTask without final newline`,
      caller: "Task without final newline",
    },
    {
      original: `Before\n${staleOne}\n\nAfter`,
      caller: "Before\nAfter",
    },
  ]
  for (const { original, caller } of fixtures) {
    const expected = `${next}\n\n${caller}`
    const first = upsertDelegationPromptLine(original, "[DELEGATION TRACE ", next)
    const second = upsertDelegationPromptLine(first, "[DELEGATION TRACE ", next)
    assert.equal(first, expected)
    assert.equal(second, expected)
    assert.equal(first.slice(next.length + 2), caller)
  }

  const nearMatches = [
    "[DELEGATION TRACE quoted] discuss this marker",
    " [DELEGATION TRACE indented]",
    "[DELEGATION TRACE trailing] ",
    "Caller example: [DELEGATION TRACE embedded]",
  ]
  for (const caller of nearMatches) {
    assert.equal(
      upsertDelegationPromptLine(caller, "[DELEGATION TRACE ", next),
      `${next}\n\n${caller}`,
    )
  }
})

test("delegation cleanup preserves nonmanaged separators exactly", () => {
  const generated =
    "[MODEL ROUTING] Preferred category=quick; model=openai/gpt-5.6-luna; reasoning=low; fallback_policy=openai-default-with-alt-fallback."
  assert.equal(stripDelegationPromptContext(`${generated}\n\n\nCaller`), "\nCaller")
  assert.equal(
    stripDelegationPromptContext(`${generated}\r\n\r\nCaller`),
    "\r\n\r\nCaller",
  )
  assert.equal(stripDelegationPromptContext(`Before\n${generated}\n\nAfter`), "Before\nAfter")
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
  const oldBlock = compactFocus("old trigger", "old avoid")
  const newBlock = compactFocus("new trigger", "new avoid")
  const first = upsertDelegationPromptBlock(
    "Inspect code paths",
    FOCUS_MARKER,
    oldBlock,
  )
  const second = upsertDelegationPromptBlock(
    first,
    FOCUS_MARKER,
    newBlock,
  )
  assert.equal(first, `${oldBlock}\n\nInspect code paths`)
  assert.equal(second, `${newBlock}\n\nInspect code paths`)
  assert.equal(second.slice(newBlock.length + 2), "Inspect code paths")
})

test("delegation prompt block upsert preserves arbitrary caller bytes", () => {
  const block = compactFocus("inspect", "edit")
  for (const caller of ["", " \t ", "Task", "\nTask", "\n\n\nTask", "\r\nTask\r\n", "Task  \n\n"]) {
    const expected = caller.length > 0 ? `${block}\n\n${caller}` : block
    const first = upsertDelegationPromptBlock(caller, FOCUS_MARKER, block)
    const second = upsertDelegationPromptBlock(first, FOCUS_MARKER, block)
    assert.equal(first, expected, JSON.stringify(caller))
    assert.equal(second, expected, JSON.stringify(caller))
    assert.equal(first.slice(caller.length > 0 ? block.length + 2 : block.length), caller)
  }
})

test("delegation prompt block replacement recognizes exact compact and legacy forms", () => {
  const next = compactFocus("new trigger", "new avoid")
  const oldOne = compactFocus("old trigger", "old avoid")
  const oldTwo = compactFocus("old; avoid: nested", "old fixed suffix; report extras as follow-ups.")
  const legacy = legacyFocus("legacy trigger", "legacy avoid")
  const fixtures = [
    {
      original: `${oldOne}\n\n\nTask`,
      caller: "\nTask",
    },
    {
      original: `${oldOne}\n\n${legacy}\n\nTask without final newline`,
      caller: "Task without final newline",
    },
    {
      original: `Before\n\n${oldOne}\n\nAfter`,
      caller: "Before\n\nAfter",
    },
    {
      original: `${oldOne}\n\n${oldTwo}\n\n${legacy}\n\nTask`,
      caller: "Task",
    },
  ]
  for (const { original, caller } of fixtures) {
    const expected = `${next}\n\n${caller}`
    const first = upsertDelegationPromptBlock(original, FOCUS_MARKER, next)
    const second = upsertDelegationPromptBlock(first, FOCUS_MARKER, next)
    assert.equal(first, expected)
    assert.equal(second, expected)
    assert.equal(first.slice(next.length + 2), caller)
  }
})

test("delegation prompt block replacement fails open for focus lookalikes", () => {
  const next = compactFocus("new trigger", "new avoid")
  const lookalikes = [
    `${FOCUS_MARKER}\nQuoted caller documentation.`,
    ` ${compactFocus("indented", "caller")}`,
    `${compactFocus("trailing", "caller")} `,
    `${compactFocus("crlf", "caller")}\r\n\r\nTask`,
    `Caller example: ${FOCUS_MARKER}`,
  ]
  for (const caller of lookalikes) {
    const expected = `${next}\n\n${caller}`
    const first = upsertDelegationPromptBlock(caller, FOCUS_MARKER, next)
    const second = upsertDelegationPromptBlock(first, FOCUS_MARKER, next)
    assert.equal(first, expected)
    assert.equal(second, expected)
    assert.equal(first.slice(next.length + 2), caller)
  }
})
