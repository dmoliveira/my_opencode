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
  assert.equal(config.contextWindowMonitor.defaultContextLimitTokens, 128000)
  assert.equal(config.preemptiveCompaction.guardMarkerMode, "both")
  assert.equal(config.preemptiveCompaction.guardVerbosity, "normal")
  assert.equal(config.compactionContextInjector.enabled, true)
  assert.equal(config.preemptiveCompaction.defaultContextLimitTokens, 128000)
  assert.equal(config.globalProcessPressure.checkCooldownToolCalls, 3)
  assert.equal(config.globalProcessPressure.warningContinueSessions, 5)
  assert.equal(config.globalProcessPressure.criticalMaxRssMb, 10240)
  assert.equal(config.globalProcessPressure.autoPauseOnCritical, true)
  assert.equal(config.globalProcessPressure.criticalEscalationWindowToolCalls, 25)
  assert.equal(config.globalProcessPressure.criticalPauseAfterEvents, 1)
  assert.equal(config.globalProcessPressure.criticalEscalationAfterEvents, 3)
  assert.equal(config.globalProcessPressure.notifyOnCritical, true)
  assert.equal(config.thinkMode.enabled, true)
  assert.equal(config.thinkingBlockValidator.enabled, true)
  assert.equal(config.directoryAgentsInjector.maxChars, 4000)
  assert.equal(config.directoryReadmeInjector.maxChars, 4000)
  assert.equal(config.todoContinuationEnforcer.enabled, true)
  assert.equal(config.todoContinuationEnforcer.cooldownMs, 30000)
  assert.equal(config.todoContinuationEnforcer.maxConsecutiveFailures, 5)
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
      defaultContextLimitTokens: 0,
    },
    preemptiveCompaction: {
      guardMarkerMode: "invalid",
      guardVerbosity: "invalid",
      maxSessionStateEntries: 0,
      defaultContextLimitTokens: 0,
    },
    globalProcessPressure: {
      checkCooldownToolCalls: 0,
      reminderCooldownToolCalls: 0,
      criticalReminderCooldownToolCalls: 0,
      criticalEscalationWindowToolCalls: 0,
      criticalPauseAfterEvents: 0,
      criticalEscalationAfterEvents: 0,
      warningContinueSessions: 0,
      warningOpencodeProcesses: 0,
      warningMaxRssMb: 0,
      criticalMaxRssMb: 0,
      autoPauseOnCritical: "invalid",
      notifyOnCritical: "invalid",
      guardMarkerMode: "invalid",
      guardVerbosity: "invalid",
      maxSessionStateEntries: 0,
    },
    directoryAgentsInjector: {
      maxChars: 0,
    },
    directoryReadmeInjector: {
      maxChars: 0,
    },
    todoContinuationEnforcer: {
      cooldownMs: 0,
      maxConsecutiveFailures: 0,
    },
  })
  assert.equal(config.contextWindowMonitor.guardMarkerMode, "both")
  assert.equal(config.contextWindowMonitor.guardVerbosity, "normal")
  assert.equal(config.contextWindowMonitor.maxSessionStateEntries, 512)
  assert.equal(config.contextWindowMonitor.defaultContextLimitTokens, 128000)
  assert.equal(config.preemptiveCompaction.guardMarkerMode, "both")
  assert.equal(config.preemptiveCompaction.guardVerbosity, "normal")
  assert.equal(config.preemptiveCompaction.maxSessionStateEntries, 512)
  assert.equal(config.preemptiveCompaction.defaultContextLimitTokens, 128000)
  assert.equal(config.globalProcessPressure.checkCooldownToolCalls, 3)
  assert.equal(config.globalProcessPressure.reminderCooldownToolCalls, 6)
  assert.equal(config.globalProcessPressure.criticalReminderCooldownToolCalls, 10)
  assert.equal(config.globalProcessPressure.criticalEscalationWindowToolCalls, 25)
  assert.equal(config.globalProcessPressure.criticalPauseAfterEvents, 1)
  assert.equal(config.globalProcessPressure.criticalEscalationAfterEvents, 3)
  assert.equal(config.globalProcessPressure.warningContinueSessions, 5)
  assert.equal(config.globalProcessPressure.warningOpencodeProcesses, 10)
  assert.equal(config.globalProcessPressure.warningMaxRssMb, 1400)
  assert.equal(config.globalProcessPressure.criticalMaxRssMb, 10240)
  assert.equal(config.globalProcessPressure.autoPauseOnCritical, true)
  assert.equal(config.globalProcessPressure.notifyOnCritical, true)
  assert.equal(config.globalProcessPressure.guardMarkerMode, "both")
  assert.equal(config.globalProcessPressure.guardVerbosity, "normal")
  assert.equal(config.globalProcessPressure.maxSessionStateEntries, 1024)
  assert.equal(config.directoryAgentsInjector.maxChars, 4000)
  assert.equal(config.directoryReadmeInjector.maxChars, 4000)
  assert.equal(config.todoContinuationEnforcer.cooldownMs, 30000)
  assert.equal(config.todoContinuationEnforcer.maxConsecutiveFailures, 5)
})
