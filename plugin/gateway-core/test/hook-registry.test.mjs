import assert from "node:assert/strict"
import test from "node:test"

import { createBranchFreshnessGuardHook } from "../dist/hooks/branch-freshness-guard/index.js"
import { createGhChecksMergeGuardHook } from "../dist/hooks/gh-checks-merge-guard/index.js"
import { createMergeReadinessGuardHook } from "../dist/hooks/merge-readiness-guard/index.js"
import { createParallelWriterConflictGuardHook } from "../dist/hooks/parallel-writer-conflict-guard/index.js"
import { createPostMergeSyncGuardHook } from "../dist/hooks/post-merge-sync-guard/index.js"
import { createPrBodyEvidenceGuardHook } from "../dist/hooks/pr-body-evidence-guard/index.js"
import { createPrReadinessGuardHook } from "../dist/hooks/pr-readiness-guard/index.js"
import { createSemanticOutputSummarizerHook } from "../dist/hooks/semantic-output-summarizer/index.js"
import {
  hooksForEvent,
  resolveHookConstructionPlan,
  resolveHookOrder,
  validateHookDependencyGraph,
} from "../dist/hooks/registry.js"
import { createStaleLoopExpiryGuardHook } from "../dist/hooks/stale-loop-expiry-guard/index.js"
import { createToolOutputTruncatorHook } from "../dist/hooks/tool-output-truncator/index.js"

function testHook(id, events) {
  return {
    id,
    priority: 1,
    events,
    async event() {},
  }
}

test("resolveHookOrder rejects duplicate hook ids before filtering", () => {
  assert.throws(
    () => resolveHookOrder([testHook("duplicate"), testHook("duplicate")], [], ["duplicate"]),
    /duplicate gateway hook ids: duplicate/,
  )
})

test("hook construction plan expands omitted stateful dependencies once", () => {
  const continuation = resolveHookConstructionPlan(["continuation"], [])
  assert.deepEqual(continuation.order, [
    "stop-continuation-guard",
    "keyword-detector",
    "continuation",
  ])
  assert.deepEqual([...continuation.selected], continuation.order)
  assert.deepEqual(continuation.blocked, [])

  const explicit = resolveHookConstructionPlan(
    ["stop-continuation-guard", "continuation", "global-process-pressure"],
    [],
  )
  assert.deepEqual(explicit.order, [
    "stop-continuation-guard",
    "keyword-detector",
    "continuation",
    "global-process-pressure",
  ])
  assert.equal(
    explicit.order.filter((id) => id === "stop-continuation-guard").length,
    1,
  )
})

test("hook construction plan excludes consumers with disabled dependencies", () => {
  const plan = resolveHookConstructionPlan(
    ["global-process-pressure", "think-mode", "todo-continuation-enforcer"],
    ["stop-continuation-guard"],
  )
  assert.deepEqual(plan.order, ["think-mode"])
  assert.deepEqual(plan.blocked, [
    {
      hookId: "global-process-pressure",
      dependencyId: "stop-continuation-guard",
    },
    {
      hookId: "todo-continuation-enforcer",
      dependencyId: "stop-continuation-guard",
    },
  ])
})

test("hook construction plan moves explicit later dependencies before consumers", () => {
  const plan = resolveHookConstructionPlan(
    [
      "continuation",
      "keyword-detector",
      "stop-continuation-guard",
      "done-proof-enforcer",
      "pr-readiness-guard",
      "pr-body-evidence-guard",
      "validation-evidence-ledger",
    ],
    [],
  )
  assert.deepEqual(plan.order, [
    "stop-continuation-guard",
    "keyword-detector",
    "continuation",
    "validation-evidence-ledger",
    "done-proof-enforcer",
    "pr-readiness-guard",
    "pr-body-evidence-guard",
  ])
  assert.equal(new Set(plan.order).size, plan.order.length)
})

test("hook construction plan blocks every validation evidence consumer", () => {
  const plan = resolveHookConstructionPlan(
    ["done-proof-enforcer", "pr-readiness-guard", "pr-body-evidence-guard"],
    ["validation-evidence-ledger"],
  )
  assert.deepEqual(plan.order, [])
  assert.deepEqual(plan.blocked, [
    { hookId: "done-proof-enforcer", dependencyId: "validation-evidence-ledger" },
    { hookId: "pr-readiness-guard", dependencyId: "validation-evidence-ledger" },
    { hookId: "pr-body-evidence-guard", dependencyId: "validation-evidence-ledger" },
  ])
})

test("implicit priority order moves only dependencies before consumers", () => {
  const hooks = [
    { ...testHook("continuation"), priority: 1 },
    { ...testHook("think-mode"), priority: 2 },
    { ...testHook("keyword-detector"), priority: 4 },
    { ...testHook("stop-continuation-guard"), priority: 5 },
  ]
  assert.deepEqual(
    resolveHookOrder(hooks, [], []).map((hook) => hook.id),
    ["stop-continuation-guard", "keyword-detector", "continuation", "think-mode"],
  )
})

test("hook dependency graph rejects unknown endpoints and cycles", () => {
  assert.throws(
    () => validateHookDependencyGraph({ a: ["missing"] }, ["a"]),
    /unknown gateway hook dependency endpoint: a -> missing/,
  )
  assert.throws(
    () => validateHookDependencyGraph({ a: ["b"], b: ["a"] }, ["a", "b"]),
    /gateway hook dependency cycle detected/,
  )
})

test("hooksForEvent preserves explicit subscriptions and legacy wildcards", () => {
  const hooks = [
    testHook("wildcard"),
    testHook("before", ["tool.execute.before"]),
    testHook("idle", ["session.idle"]),
  ]

  assert.deepEqual(
    hooksForEvent(hooks, "tool.execute.before").map((hook) => hook.id),
    ["wildcard", "before"],
  )
  assert.deepEqual(
    hooksForEvent(hooks, "session.idle").map((hook) => hook.id),
    ["wildcard", "idle"],
  )
})

test("implicit priority runs semantic summarization before truncation", () => {
  const directory = process.cwd()
  const hooks = [
    createToolOutputTruncatorHook({
      directory,
      enabled: true,
      maxChars: 12000,
      maxLines: 220,
      tools: ["bash"],
    }),
    createSemanticOutputSummarizerHook({
      directory,
      enabled: true,
      minChars: 20000,
      minLines: 400,
      maxSummaryLines: 8,
    }),
  ]
  assert.deepEqual(
    resolveHookOrder(hooks, [], []).map((hook) => hook.id),
    ["semantic-output-summarizer", "tool-output-truncator"],
  )
})

test("expensive workflow guards declare exact event subscriptions", () => {
  const directory = process.cwd()
  const hooks = [
    createStaleLoopExpiryGuardHook({ directory, enabled: true, maxAgeMinutes: 120 }),
    createParallelWriterConflictGuardHook({
      directory,
      enabled: true,
      maxConcurrentWriters: 2,
      writerCountEnvKeys: [],
      reservationPathsEnvKeys: [],
      activeReservationPathsEnvKeys: [],
      enforceReservationCoverage: true,
      stateFile: ".opencode/test-reservations.json",
    }),
    createBranchFreshnessGuardHook({
      directory,
      enabled: true,
      baseRef: "origin/main",
      maxBehind: 0,
      enforceOnPrCreate: true,
      enforceOnPrMerge: true,
    }),
    createPrReadinessGuardHook({
      directory,
      enabled: true,
      requireCleanWorktree: true,
      requireValidationEvidence: true,
      requiredMarkers: ["test"],
    }),
    createPrBodyEvidenceGuardHook({
      directory,
      enabled: true,
      requireSummarySection: true,
      requireValidationSection: true,
      requireValidationEvidence: true,
      allowUninspectableBody: false,
      requiredMarkers: ["test"],
    }),
    createMergeReadinessGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: true,
      requireStrategy: true,
      disallowAdminBypass: true,
    }),
    createGhChecksMergeGuardHook({
      directory,
      enabled: true,
      blockDraft: true,
      requireApprovedReview: true,
      requirePassingChecks: true,
      blockedMergeStates: [],
      failOpenOnError: false,
    }),
    createPostMergeSyncGuardHook({
      directory,
      enabled: true,
      requireDeleteBranch: true,
      enforceMainSyncInline: true,
      reminderCommands: [],
    }),
    createSemanticOutputSummarizerHook({
      directory,
      enabled: true,
      minChars: 20000,
      minLines: 400,
      maxSummaryLines: 8,
    }),
    createToolOutputTruncatorHook({
      directory,
      enabled: true,
      maxChars: 12000,
      maxLines: 220,
      tools: ["bash"],
    }),
  ]

  assert.deepEqual(
    Object.fromEntries(hooks.map((hook) => [hook.id, hook.events])),
    {
      "stale-loop-expiry-guard": ["session.idle"],
      "parallel-writer-conflict-guard": ["tool.execute.before"],
      "branch-freshness-guard": ["tool.execute.before"],
      "pr-readiness-guard": ["tool.execute.before"],
      "pr-body-evidence-guard": ["tool.execute.before"],
      "merge-readiness-guard": ["tool.execute.before"],
      "gh-checks-merge-guard": ["tool.execute.before"],
      "post-merge-sync-guard": ["tool.execute.before", "tool.execute.after"],
      "semantic-output-summarizer": ["tool.execute.after"],
      "tool-output-truncator": ["tool.execute.after"],
    },
  )
})
