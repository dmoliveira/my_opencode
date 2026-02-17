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
  assert.equal(config.compactionTodoPreserver.enabled, true)
  assert.equal(config.compactionTodoPreserver.maxChars, 4000)
  assert.equal(config.editErrorRecovery.enabled, true)
  assert.equal(config.jsonErrorRecovery.enabled, true)
  assert.equal(config.providerTokenLimitRecovery.enabled, true)
  assert.equal(config.providerTokenLimitRecovery.cooldownMs, 60000)
  assert.equal(config.hashlineReadEnhancer.enabled, true)
  assert.equal(config.maxStepRecovery.enabled, true)
  assert.equal(config.modeTransitionReminder.enabled, true)
  assert.equal(config.todoreadCadenceReminder.enabled, true)
  assert.equal(config.todoreadCadenceReminder.cooldownEvents, 2)
  assert.equal(config.providerRetryBackoffGuidance.enabled, true)
  assert.equal(config.providerRetryBackoffGuidance.cooldownMs, 30000)
  assert.equal(config.providerErrorClassifier.enabled, true)
  assert.equal(config.providerErrorClassifier.cooldownMs, 30000)
  assert.equal(config.codexHeaderInjector.enabled, true)
  assert.equal(config.planHandoffReminder.enabled, true)
  assert.equal(config.workflowConformanceGuard.enabled, false)
  assert.equal(config.prReadinessGuard.enabled, false)
  assert.equal(config.noninteractiveShellGuard.injectEnvPrefix, true)
  assert.equal(Array.isArray(config.noninteractiveShellGuard.envPrefixes), true)
  assert.equal(config.noninteractiveShellGuard.prefixCommands.includes("git"), true)
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
    pressureEscalationGuard: {
      maxContinueBeforeBlock: 0,
      blockedSubagentTypes: [],
      allowPromptPatterns: [],
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
    compactionTodoPreserver: {
      maxChars: 0,
    },
    noninteractiveShellGuard: {
      injectEnvPrefix: "invalid",
      envPrefixes: ["", "CI=true", 1],
      prefixCommands: ["", "git", 1],
    },
    providerTokenLimitRecovery: {
      cooldownMs: 0,
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
  assert.equal(config.compactionTodoPreserver.maxChars, 4000)
  assert.equal(config.noninteractiveShellGuard.injectEnvPrefix, true)
  assert.deepEqual(config.noninteractiveShellGuard.envPrefixes, ["CI=true"])
  assert.deepEqual(config.noninteractiveShellGuard.prefixCommands, ["git"])
  assert.equal(config.editErrorRecovery.enabled, true)
  assert.equal(config.jsonErrorRecovery.enabled, true)
  assert.equal(config.providerTokenLimitRecovery.cooldownMs, 60000)
  assert.equal(config.hashlineReadEnhancer.enabled, true)
  assert.equal(config.maxStepRecovery.enabled, true)
  assert.equal(config.modeTransitionReminder.enabled, true)
  assert.equal(config.todoreadCadenceReminder.enabled, true)
  assert.equal(config.todoreadCadenceReminder.cooldownEvents, 2)
  assert.equal(config.providerRetryBackoffGuidance.enabled, true)
  assert.equal(config.providerRetryBackoffGuidance.cooldownMs, 30000)
  assert.equal(config.providerErrorClassifier.enabled, true)
  assert.equal(config.providerErrorClassifier.cooldownMs, 30000)
  assert.equal(config.codexHeaderInjector.enabled, true)
  assert.equal(config.planHandoffReminder.enabled, true)
})
