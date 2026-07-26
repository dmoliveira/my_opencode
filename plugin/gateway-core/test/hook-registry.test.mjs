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
import { hooksForEvent, resolveHookOrder } from "../dist/hooks/registry.js"
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
