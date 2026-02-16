import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createGhChecksMergeGuardHook } from "../dist/hooks/gh-checks-merge-guard/index.js"

function payload(directory, command = "gh pr merge 10 --merge --delete-branch") {
  return {
    input: { tool: "bash", sessionID: "session-gh-checks" },
    output: { args: { command } },
    directory,
  }
}

function baseOptions(directory, inspectPr) {
  return {
    directory,
    enabled: true,
    blockDraft: true,
    requireApprovedReview: true,
    requirePassingChecks: true,
    blockedMergeStates: ["BEHIND", "BLOCKED", "DIRTY"],
    failOpenOnError: false,
    inspectPr,
  }
}

test("gh-checks-merge-guard blocks draft PR merges", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-gh-checks-"))
  try {
    const hook = createGhChecksMergeGuardHook(
      baseOptions(directory, () => ({
        isDraft: true,
        reviewDecision: "APPROVED",
        mergeStateStatus: "CLEAN",
        statusCheckRollup: [],
      })),
    )

    await assert.rejects(hook.event("tool.execute.before", payload(directory)), /PR is draft/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gh-checks-merge-guard blocks merges without approved review", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-gh-checks-"))
  try {
    const hook = createGhChecksMergeGuardHook(
      baseOptions(directory, () => ({
        isDraft: false,
        reviewDecision: "REVIEW_REQUIRED",
        mergeStateStatus: "CLEAN",
        statusCheckRollup: [],
      })),
    )

    await assert.rejects(hook.event("tool.execute.before", payload(directory)), /Approval is required/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gh-checks-merge-guard blocks merges with pending checks", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-gh-checks-"))
  try {
    const hook = createGhChecksMergeGuardHook(
      baseOptions(directory, () => ({
        isDraft: false,
        reviewDecision: "APPROVED",
        mergeStateStatus: "CLEAN",
        statusCheckRollup: [{ status: "IN_PROGRESS" }],
      })),
    )

    await assert.rejects(hook.event("tool.execute.before", payload(directory)), /checks are not green/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gh-checks-merge-guard blocks merges with blocked merge state", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-gh-checks-"))
  try {
    const hook = createGhChecksMergeGuardHook(
      baseOptions(directory, () => ({
        isDraft: false,
        reviewDecision: "APPROVED",
        mergeStateStatus: "BEHIND",
        statusCheckRollup: [{ conclusion: "SUCCESS" }],
      })),
    )

    await assert.rejects(hook.event("tool.execute.before", payload(directory)), /is blocked by policy/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gh-checks-merge-guard allows merge when draft, review, and checks are clean", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-gh-checks-"))
  try {
    const hook = createGhChecksMergeGuardHook(
      baseOptions(directory, () => ({
        isDraft: false,
        reviewDecision: "APPROVED",
        mergeStateStatus: "CLEAN",
        statusCheckRollup: [{ conclusion: "SUCCESS" }],
      })),
    )

    await hook.event("tool.execute.before", payload(directory))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("gh-checks-merge-guard can fail open when lookup errors", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-gh-checks-"))
  try {
    const hook = createGhChecksMergeGuardHook({
      ...baseOptions(directory, () => {
        throw new Error("lookup failed")
      }),
      failOpenOnError: true,
    })

    await hook.event("tool.execute.before", payload(directory))
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
