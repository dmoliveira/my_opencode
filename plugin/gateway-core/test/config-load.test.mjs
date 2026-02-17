import assert from "node:assert/strict"
import test from "node:test"

import { loadGatewayConfig } from "../dist/config/load.js"

test("loadGatewayConfig keeps defaults for new safety guard knobs", () => {
  const config = loadGatewayConfig({})
  assert.equal(config.secretCommitGuard.enabled, true)
  assert.equal(config.prBodyEvidenceGuard.requireSummarySection, true)
  assert.equal(config.parallelWriterConflictGuard.maxConcurrentWriters, 2)
  assert.equal(config.postMergeSyncGuard.requireDeleteBranch, true)
  assert.equal(config.contextWindowMonitor.reminderCooldownToolCalls, 12)
  assert.equal(config.preemptiveCompaction.compactionCooldownToolCalls, 10)
  assert.equal(config.contextWindowMonitor.guardMarkerMode, "both")
  assert.equal(config.contextWindowMonitor.guardVerbosity, "normal")
  assert.equal(config.preemptiveCompaction.guardMarkerMode, "both")
  assert.equal(config.preemptiveCompaction.guardVerbosity, "normal")
})

test("loadGatewayConfig normalizes invalid maxConcurrentWriters", () => {
  const config = loadGatewayConfig({
    parallelWriterConflictGuard: {
      maxConcurrentWriters: 0,
    },
  })
  assert.equal(config.parallelWriterConflictGuard.maxConcurrentWriters, 2)
})

test("loadGatewayConfig normalizes invalid context monitor cooldown values", () => {
  const config = loadGatewayConfig({
    contextWindowMonitor: {
      reminderCooldownToolCalls: 0,
      minTokenDeltaForReminder: -5,
    },
  })
  assert.equal(config.contextWindowMonitor.reminderCooldownToolCalls, 12)
  assert.equal(config.contextWindowMonitor.minTokenDeltaForReminder, 25000)
})

test("loadGatewayConfig normalizes invalid compaction cooldown values", () => {
  const config = loadGatewayConfig({
    preemptiveCompaction: {
      compactionCooldownToolCalls: 0,
      minTokenDeltaForCompaction: -5,
    },
  })
  assert.equal(config.preemptiveCompaction.compactionCooldownToolCalls, 10)
  assert.equal(config.preemptiveCompaction.minTokenDeltaForCompaction, 35000)
})

test("loadGatewayConfig normalizes invalid guard marker and verbosity values", () => {
  const config = loadGatewayConfig({
    contextWindowMonitor: {
      guardMarkerMode: "invalid",
      guardVerbosity: "invalid",
      maxSessionStateEntries: 0,
    },
    preemptiveCompaction: {
      guardMarkerMode: "invalid",
      guardVerbosity: "invalid",
      maxSessionStateEntries: 0,
    },
  })
  assert.equal(config.contextWindowMonitor.guardMarkerMode, "both")
  assert.equal(config.contextWindowMonitor.guardVerbosity, "normal")
  assert.equal(config.contextWindowMonitor.maxSessionStateEntries, 512)
  assert.equal(config.preemptiveCompaction.guardMarkerMode, "both")
  assert.equal(config.preemptiveCompaction.guardVerbosity, "normal")
  assert.equal(config.preemptiveCompaction.maxSessionStateEntries, 512)
})
