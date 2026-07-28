import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import test from "node:test"

import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import {
  loadGatewayConfig,
  loadGatewayConfigSource,
  loadGatewayConfigSourceWithMeta,
} from "../dist/config/load.js"

test("loadGatewayConfig keeps defaults for new safety guard knobs", () => {
  const config = loadGatewayConfig({})
  assert.equal(config.secretCommitGuard.enabled, true)
  assert.equal(config.secretLeakGuard.providerMaxMessages, 20000)
  assert.equal(config.secretLeakGuard.providerMaxNodes, 1000000)
  assert.equal(config.secretLeakGuard.providerMaxChars, 134217728)
  assert.equal(config.secretLeakGuard.providerMaxMessageChars, 16777216)
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
  assert.equal(config.globalProcessPressure.selfSeverityOperator, "any")
  assert.equal(config.globalProcessPressure.selfHighCpuPct, 100)
  assert.equal(config.globalProcessPressure.selfHighRssMb, 10240)
  assert.equal(config.globalProcessPressure.selfHighElapsed, "5h")
  assert.equal(config.globalProcessPressure.selfHighLabel, "HIGH")
  assert.equal(config.globalProcessPressure.selfLowLabel, "LOW")
  assert.equal(config.globalProcessPressure.selfAppendMarker, true)
  assert.equal(config.longTurnWatchdog.enabled, true)
  assert.equal(config.longTurnWatchdog.warningThresholdMs, 60000)
  assert.equal(config.longTurnWatchdog.toolCallWarningThreshold, 12)
  assert.equal(config.longTurnWatchdog.reminderCooldownMs, 60000)
  assert.equal(config.longTurnWatchdog.maxSessionStateEntries, 1024)
  assert.equal(config.longTurnWatchdog.prefix, "[Turn Watchdog]:")
  assert.equal(config.notifyEvents.enabled, true)
  assert.equal(config.notifyEvents.cooldownMs, 1200)
  assert.equal(config.notifyEvents.style, "brief")
  assert.equal(config.conciseMode.enabled, false)
  assert.equal(config.conciseMode.defaultMode, "off")
  assert.equal(config.contextInjector.dedupeEnabled, true)
  assert.equal(config.contextInjector.minDeltaChars, 120)
  assert.equal(config.contextInjector.dedupeNormalizeWhitespace, true)
  assert.equal(config.sessionRuntimeSystemContext.enabled, true)
  assert.equal(config.sessionRuntimeSystemContext.injectSessionIdContext, true)
  assert.equal(config.sessionRuntimeSystemContext.injectSessionIdWhenConciseModeOnly, false)
  assert.equal(config.thinkMode.enabled, true)
  assert.equal(config.thinkingBlockValidator.enabled, true)
  assert.equal(config.directoryAgentsInjector.maxChars, 1000)
  assert.equal(config.directoryReadmeInjector.maxChars, 1000)
  assert.equal(config.todoContinuationEnforcer.enabled, true)
  assert.equal(config.todoContinuationEnforcer.cooldownMs, 30000)
  assert.equal(config.todoContinuationEnforcer.maxConsecutiveFailures, 5)
  assert.equal(config.compactionTodoPreserver.enabled, true)
  assert.equal(config.compactionTodoPreserver.maxChars, 4000)
  assert.equal(config.editErrorRecovery.enabled, true)
  assert.equal(config.jsonErrorRecovery.enabled, true)
  assert.equal(config.providerTokenLimitRecovery.enabled, true)
  assert.equal(config.providerTokenLimitRecovery.cooldownMs, 60000)
  assert.equal(config.hashlineReadEnhancer.enabled, false)
  assert.equal(config.maxStepRecovery.enabled, true)
  assert.equal(config.modeTransitionReminder.enabled, false)
  assert.equal(config.todoreadCadenceReminder.enabled, false)
  assert.equal(config.todoreadCadenceReminder.cooldownEvents, 2)
  assert.equal(config.providerRetryBackoffGuidance.enabled, true)
  assert.equal(config.providerRetryBackoffGuidance.cooldownMs, 30000)
  assert.equal(config.providerErrorClassifier.enabled, true)
  assert.equal(config.providerErrorClassifier.cooldownMs, 30000)
  assert.equal(config.codexHeaderInjector.enabled, true)
  assert.equal(config.planHandoffReminder.enabled, false)
  assert.equal(config.semanticOutputSummarizer.enabled, false)
  assert.equal(config.primaryWorktreeGuard.enabled, true)
  assert.deepEqual(config.primaryWorktreeGuard.allowedBranches, ["main", "master"])
  assert.equal(config.primaryWorktreeGuard.blockEdits, true)
  assert.equal(config.primaryWorktreeGuard.blockBranchSwitches, true)
  assert.equal(config.workflowConformanceGuard.enabled, true)
  assert.deepEqual(config.workflowConformanceGuard.protectedBranches, ["main", "master"])
  assert.equal(config.workflowConformanceGuard.blockEditsOnProtectedBranches, true)
  assert.equal(config.prReadinessGuard.enabled, false)
  assert.equal(config.providerModelBudgetEnforcer.enabled, true)
  assert.equal(config.providerModelBudgetEnforcer.windowMs, 300000)
  assert.equal(config.providerModelBudgetEnforcer.maxDelegationsPerWindow, 24)
  assert.equal(config.providerModelBudgetEnforcer.maxEstimatedTokensPerWindow, 24000)
  assert.equal(config.providerModelBudgetEnforcer.maxPerModelDelegationsPerWindow, 16)
  assert.equal(config.subagentLifecycleSupervisor.enabled, true)
  assert.equal(config.subagentLifecycleSupervisor.maxRetriesPerSession, 3)
  assert.equal(config.subagentLifecycleSupervisor.staleRunningMs, 300000)
  assert.equal(config.subagentLifecycleSupervisor.blockOnExhausted, true)
  assert.equal(config.subagentTelemetryTimeline.enabled, true)
  assert.equal(config.subagentTelemetryTimeline.maxTimelineEntries, 1000)
  assert.equal(config.adaptiveDelegationPolicy.enabled, true)
  assert.equal(config.adaptiveDelegationPolicy.outcomeLearnerMode, "shadow")
  assert.equal(config.adaptiveDelegationPolicy.windowMs, 300000)
  assert.equal(config.adaptiveDelegationPolicy.minSamples, 4)
  assert.equal(config.adaptiveDelegationPolicy.highFailureRate, 0.5)
  assert.equal(config.adaptiveDelegationPolicy.cooldownMs, 180000)
  assert.equal(config.adaptiveDelegationPolicy.blockExpensiveDuringCooldown, true)
  assert.equal(config.llmDecisionRuntime.enabled, false)
  assert.equal(config.llmDecisionRuntime.mode, "disabled")
  assert.deepEqual(config.llmDecisionRuntime.hookModes, {})
  assert.equal(config.llmDecisionRuntime.model, "github-copilot/gpt-5-mini")
  assert.deepEqual(config.llmDecisionRuntime.env, {})
  assert.equal(config.llmDecisionRuntime.allowStandaloneOpencode, false)
  assert.equal(config.llmDecisionRuntime.timeoutMs, 10000)
  assert.equal(config.llmDecisionRuntime.failureCooldownMs, 120000)
  assert.equal(config.llmDecisionRuntime.enableCache, true)
  assert.equal(config.llmDecisionRuntime.cacheTtlMs, 300000)
  assert.equal(config.llmDecisionRuntime.maxCacheEntries, 256)
  assert.equal(config.noninteractiveShellGuard.injectEnvPrefix, true)
  assert.equal(Array.isArray(config.noninteractiveShellGuard.envPrefixes), true)
  assert.equal(config.noninteractiveShellGuard.prefixCommands.includes("git"), true)
})

test("loadGatewayConfig preserves legacy provider limits until new limits opt in", () => {
  const legacy = loadGatewayConfig({
    secretLeakGuard: { maxNodes: 123, maxChars: 456 },
  }).secretLeakGuard
  assert.equal(legacy.providerMaxMessages, 123)
  assert.equal(legacy.providerMaxNodes, 123)
  assert.equal(legacy.providerMaxChars, 456)
  assert.equal(legacy.providerMaxMessageChars, 456)

  const provider = loadGatewayConfig({
    secretLeakGuard: {
      providerMaxMessages: 300,
      providerMaxNodes: 400,
      providerMaxChars: 500,
      providerMaxMessageChars: 450,
    },
  }).secretLeakGuard
  assert.equal(provider.providerMaxMessages, 300)
  assert.equal(provider.providerMaxNodes, 400)
  assert.equal(provider.providerMaxChars, 500)
  assert.equal(provider.providerMaxMessageChars, 450)

  const mixed = loadGatewayConfig({
    secretLeakGuard: {
      maxNodes: 123,
      maxChars: 456,
      providerMaxMessages: 700,
      providerMaxNodes: 800,
      providerMaxChars: 900,
      providerMaxMessageChars: 850,
    },
  }).secretLeakGuard
  assert.equal(mixed.providerMaxMessages, 700)
  assert.equal(mixed.providerMaxNodes, 800)
  assert.equal(mixed.providerMaxChars, 900)
  assert.equal(mixed.providerMaxMessageChars, 850)

  const invalid = loadGatewayConfig({
    secretLeakGuard: {
      maxNodes: 123,
      maxChars: 456,
      providerMaxMessages: 0,
      providerMaxNodes: 0,
      providerMaxChars: 0,
      providerMaxMessageChars: 0,
    },
  }).secretLeakGuard
  assert.equal(invalid.providerMaxMessages, 123)
  assert.equal(invalid.providerMaxNodes, 123)
  assert.equal(invalid.providerMaxChars, 456)
  assert.equal(invalid.providerMaxMessageChars, 456)

  const capped = loadGatewayConfig({
    secretLeakGuard: {
      providerMaxMessages: 1000,
      providerMaxNodes: 10,
      providerMaxChars: 100,
      providerMaxMessageChars: 200,
    },
  }).secretLeakGuard
  assert.equal(capped.providerMaxMessages, 10)
  assert.equal(capped.providerMaxMessageChars, 100)
})

test("loadGatewayConfig normalizes enabled summarizer ordering", () => {
  const emptyOrder = loadGatewayConfig({
    hooks: { order: [] },
    semanticOutputSummarizer: { enabled: true },
  })
  assert.deepEqual(emptyOrder.hooks.order, [])
  assert.equal(emptyOrder.semanticOutputSummarizer.enabled, true)

  const legacyOrder = loadGatewayConfig({
    hooks: {
      order: [
        "context-window-monitor",
        "tool-output-truncator",
        "semantic-output-summarizer",
      ],
    },
    semanticOutputSummarizer: { enabled: true },
  })
  assert.deepEqual(legacyOrder.hooks.order, [
    "context-window-monitor",
    "semantic-output-summarizer",
    "tool-output-truncator",
  ])

  const customOrder = loadGatewayConfig({
    hooks: { order: ["context-window-monitor", "tool-output-truncator"] },
    semanticOutputSummarizer: { enabled: true },
  })
  assert.deepEqual(customOrder.hooks.order, [
    "context-window-monitor",
    "semantic-output-summarizer",
    "tool-output-truncator",
  ])

  const customWithoutTruncator = loadGatewayConfig({
    hooks: { order: ["context-window-monitor"] },
    semanticOutputSummarizer: { enabled: true },
  })
  assert.deepEqual(customWithoutTruncator.hooks.order, [
    "semantic-output-summarizer",
    "context-window-monitor",
  ])
})

test("loadGatewayConfig normalizes adaptive outcome learner mode", () => {
  assert.equal(
    loadGatewayConfig({
      adaptiveDelegationPolicy: { outcomeLearnerMode: "enforce" },
    }).adaptiveDelegationPolicy.outcomeLearnerMode,
    "enforce",
  )
  assert.equal(
    loadGatewayConfig({
      adaptiveDelegationPolicy: { outcomeLearnerMode: "unsafe" },
    }).adaptiveDelegationPolicy.outcomeLearnerMode,
    "shadow",
  )
})

test("loadGatewayConfig normalizes invalid maxConcurrentWriters", () => {
  const config = loadGatewayConfig({
    parallelWriterConflictGuard: {
      maxConcurrentWriters: 0,
    },
  })
  assert.equal(config.parallelWriterConflictGuard.maxConcurrentWriters, 2)
})

test("loadGatewayConfig applies context injector and session runtime overrides", () => {
  const config = loadGatewayConfig({
    contextInjector: {
      dedupeEnabled: false,
      minDeltaChars: 5,
      dedupeNormalizeWhitespace: false,
    },
    sessionRuntimeSystemContext: {
      enabled: true,
      injectSessionIdContext: false,
      injectSessionIdWhenConciseModeOnly: true,
    },
  })

  assert.equal(config.contextInjector.dedupeEnabled, false)
  assert.equal(config.contextInjector.minDeltaChars, 5)
  assert.equal(config.contextInjector.dedupeNormalizeWhitespace, false)
  assert.equal(config.sessionRuntimeSystemContext.enabled, true)
  assert.equal(config.sessionRuntimeSystemContext.injectSessionIdContext, false)
  assert.equal(config.sessionRuntimeSystemContext.injectSessionIdWhenConciseModeOnly, true)
})

test("loadGatewayConfig normalizes llmDecisionRuntime env to non-empty string pairs", () => {
  const config = loadGatewayConfig({
    llmDecisionRuntime: {
      env: {
        OPENAI_BASE_URL: "http://127.0.0.1:8000/v1",
        OPENAI_API_KEY: "dummy",
        EMPTY_VALUE: "   ",
        "   ": "ignored",
      },
      allowStandaloneOpencode: true,
    },
  })

  assert.deepEqual(config.llmDecisionRuntime.env, {
    OPENAI_BASE_URL: "http://127.0.0.1:8000/v1",
    OPENAI_API_KEY: "dummy",
  })
  assert.equal(config.llmDecisionRuntime.allowStandaloneOpencode, true)
})

test("loadGatewayConfig accepts concise mode sidecar override", () => {
  const dir = mkdtempSync(join(tmpdir(), "gateway-config-concise-"))
  try {
    mkdirSync(join(dir, ".opencode"), { recursive: true })
    writeFileSync(
      join(dir, ".opencode", "gateway-core.config.json"),
      JSON.stringify({ conciseMode: { enabled: true, defaultMode: "lite" } }),
      "utf-8",
    )
    const { source } = loadGatewayConfigSourceWithMeta(dir, {})
    const config = loadGatewayConfig(source)
    assert.equal(config.conciseMode.enabled, true)
    assert.equal(config.conciseMode.defaultMode, "lite")
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
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
    longTurnWatchdog: {
      warningThresholdMs: 0,
      reminderCooldownMs: -5,
      maxSessionStateEntries: 0,
      prefix: "   ",
    },
    notifyEvents: {
      cooldownMs: -1,
      style: "invalid",
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
  assert.equal(config.globalProcessPressure.selfSeverityOperator, "any")
  assert.equal(config.globalProcessPressure.selfHighCpuPct, 100)
  assert.equal(config.llmDecisionRuntime.mode, "disabled")
  assert.deepEqual(config.llmDecisionRuntime.hookModes, {})
  assert.equal(config.llmDecisionRuntime.timeoutMs, 10000)
  assert.equal(config.llmDecisionRuntime.failureCooldownMs, 120000)
  assert.equal(config.llmDecisionRuntime.maxPromptChars, 1200)
  assert.equal(config.llmDecisionRuntime.maxContextChars, 2400)
  assert.equal(config.llmDecisionRuntime.enableCache, true)
  assert.equal(config.llmDecisionRuntime.cacheTtlMs, 300000)
  assert.equal(config.llmDecisionRuntime.maxCacheEntries, 256)
  assert.equal(config.globalProcessPressure.selfHighRssMb, 10240)
  assert.equal(config.globalProcessPressure.selfHighElapsed, "5h")
  assert.equal(config.globalProcessPressure.selfHighLabel, "HIGH")
  assert.equal(config.globalProcessPressure.selfLowLabel, "LOW")
  assert.equal(config.globalProcessPressure.selfAppendMarker, true)
  assert.equal(config.globalProcessPressure.guardMarkerMode, "both")
  assert.equal(config.globalProcessPressure.guardVerbosity, "normal")
  assert.equal(config.globalProcessPressure.maxSessionStateEntries, 1024)
  assert.equal(config.globalProcessPressure.selfSeverityOperator, "any")
  assert.equal(config.globalProcessPressure.selfHighCpuPct, 100)
  assert.equal(config.globalProcessPressure.selfHighRssMb, 10240)
  assert.equal(config.globalProcessPressure.selfHighElapsed, "5h")
  assert.equal(config.globalProcessPressure.selfHighLabel, "HIGH")
  assert.equal(config.globalProcessPressure.selfLowLabel, "LOW")
  assert.equal(config.globalProcessPressure.selfAppendMarker, true)
  assert.equal(config.longTurnWatchdog.enabled, true)
  assert.equal(config.longTurnWatchdog.warningThresholdMs, 60000)
  assert.equal(config.longTurnWatchdog.toolCallWarningThreshold, 12)
  assert.equal(config.longTurnWatchdog.reminderCooldownMs, 60000)
  assert.equal(config.longTurnWatchdog.maxSessionStateEntries, 1024)
  assert.equal(config.longTurnWatchdog.prefix, "[Turn Watchdog]:")
  assert.equal(config.notifyEvents.enabled, true)
  assert.equal(config.notifyEvents.cooldownMs, 1200)
  assert.equal(config.notifyEvents.style, "brief")
  assert.equal(config.directoryAgentsInjector.maxChars, 1000)
  assert.equal(config.directoryReadmeInjector.maxChars, 1000)
  assert.equal(config.todoContinuationEnforcer.cooldownMs, 30000)
  assert.equal(config.todoContinuationEnforcer.maxConsecutiveFailures, 5)
  assert.equal(config.compactionTodoPreserver.maxChars, 4000)
  assert.equal(config.noninteractiveShellGuard.injectEnvPrefix, true)
  assert.deepEqual(config.noninteractiveShellGuard.envPrefixes, ["CI=true"])
  assert.deepEqual(config.noninteractiveShellGuard.prefixCommands, ["git"])
  assert.equal(config.editErrorRecovery.enabled, true)
  assert.equal(config.jsonErrorRecovery.enabled, true)
  assert.equal(config.providerTokenLimitRecovery.cooldownMs, 60000)
  assert.equal(config.hashlineReadEnhancer.enabled, false)
  assert.equal(config.maxStepRecovery.enabled, true)
  assert.equal(config.modeTransitionReminder.enabled, false)
  assert.equal(config.todoreadCadenceReminder.enabled, false)
  assert.equal(config.todoreadCadenceReminder.cooldownEvents, 2)
  assert.equal(config.providerRetryBackoffGuidance.enabled, true)
  assert.equal(config.providerRetryBackoffGuidance.cooldownMs, 30000)
  assert.equal(config.providerErrorClassifier.enabled, true)
  assert.equal(config.providerErrorClassifier.cooldownMs, 30000)
  assert.equal(config.codexHeaderInjector.enabled, true)
  assert.equal(config.planHandoffReminder.enabled, false)
})

test("loadGatewayConfig preserves exact llm hook mode overrides", () => {
  const config = loadGatewayConfig({
    llmDecisionRuntime: {
      enabled: true,
      mode: "shadow",
      hookModes: {
        "auto-slash-command": "assist",
        "provider-error-classifier": "assist",
        "todo-continuation-enforcer": "disabled",
      },
    },
  })
  assert.equal(config.llmDecisionRuntime.mode, "shadow")
  assert.deepEqual(config.llmDecisionRuntime.hookModes, {
    "auto-slash-command": "assist",
    "provider-error-classifier": "assist",
    "todo-continuation-enforcer": "disabled",
  })
})

test("loadGatewayConfig rejects unknown, duplicate, and non-exact hook ids", () => {
  assert.throws(
    () => loadGatewayConfig({ hooks: { order: ["dangerous-command-gaurd"] } }),
    /hooks\.order contains unknown gateway hook id: dangerous-command-gaurd/,
  )
  assert.throws(
    () => loadGatewayConfig({ hooks: { disabled: ["safety", "safety"] } }),
    /hooks\.disabled contains duplicate gateway hook id: safety/,
  )
  assert.throws(
    () => loadGatewayConfig({ hooks: { order: [" safety"] } }),
    /hooks\.order contains a non-exact gateway hook id/,
  )
  assert.throws(
    () => loadGatewayConfig({ hooks: { disabled: "safety" } }),
    /hooks\.disabled must be an array of exact gateway hook ids/,
  )
})

test("loadGatewayConfig rejects invalid llm mode identities", () => {
  assert.throws(
    () => loadGatewayConfig({ llmDecisionRuntime: { hookModes: { continuation: "assist" } } }),
    /unknown LLM hook id: continuation/,
  )
  assert.throws(
    () => loadGatewayConfig({ llmDecisionRuntime: { hookModes: { "auto-slash-command ": "assist" } } }),
    /unknown LLM hook id: auto-slash-command /,
  )
  assert.throws(
    () => loadGatewayConfig({ llmDecisionRuntime: { hookModes: { "auto-slash-command": "automatic" } } }),
    /hookModes\.auto-slash-command must be one of/,
  )
  assert.throws(
    () => loadGatewayConfig({ llmDecisionRuntime: { mode: "automatic" } }),
    /llmDecisionRuntime\.mode must be one of/,
  )
})

test("loadGatewayConfigSource merges sidecar config with runtime source", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-config-source-"))
  try {
    mkdirSync(join(directory, ".opencode"), { recursive: true })
    writeFileSync(
      join(directory, ".opencode", "gateway-core.config.json"),
      JSON.stringify({
        llmDecisionRuntime: {
          enabled: true,
          mode: "shadow",
          hookModes: { "auto-slash-command": "assist" },
        },
      }),
      "utf-8",
    )
    const merged = loadGatewayConfigSource(directory, {
      llmDecisionRuntime: {
        mode: "assist",
        hookModes: { "provider-error-classifier": "assist" },
      },
    })
    const config = loadGatewayConfig(merged)
    assert.equal(config.llmDecisionRuntime.enabled, true)
    assert.equal(config.llmDecisionRuntime.mode, "assist")
    assert.deepEqual(config.llmDecisionRuntime.hookModes, {
      "auto-slash-command": "assist",
      "provider-error-classifier": "assist",
    })
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("loadGatewayConfigSource layers home, project, and explicit runtime config", () => {
  const root = mkdtempSync(join(tmpdir(), "gateway-config-layers-"))
  const home = join(root, "home")
  const project = join(root, "project")
  const previousEnvPath = process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
  const previousHome = process.env.HOME
  try {
    delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    process.env.HOME = home
    const homeSidecar = join(
      home,
      ".config",
      "opencode",
      "my_opencode",
      "gateway-core.config.json",
    )
    const projectSidecar = join(project, ".opencode", "gateway-core.config.json")
    mkdirSync(dirname(homeSidecar), { recursive: true })
    mkdirSync(dirname(projectSidecar), { recursive: true })
    writeFileSync(
      homeSidecar,
      JSON.stringify({
        globalProcessPressure: { enabled: false },
        hooks: { disabled: ["think-mode"] },
        llmDecisionRuntime: {
          enabled: true,
          mode: "shadow",
          hookModes: { "auto-slash-command": "shadow" },
        },
      }),
      "utf-8",
    )
    writeFileSync(
      projectSidecar,
      JSON.stringify({
        conciseMode: { enabled: true, defaultMode: "lite" },
        hooks: { disabled: ["safety"] },
        llmDecisionRuntime: {
          mode: "disabled",
          hookModes: { "provider-error-classifier": "assist" },
        },
      }),
      "utf-8",
    )

    const loaded = loadGatewayConfigSourceWithMeta(project, {
      llmDecisionRuntime: { timeoutMs: 4321 },
    })
    const config = loadGatewayConfig(loaded.source)

    assert.deepEqual(
      loaded.meta.layers.map((layer) => [layer.kind, layer.loaded]),
      [["home", true], ["project", true]],
    )
    assert.equal(loaded.meta.sidecarPath, projectSidecar)
    assert.equal(config.globalProcessPressure.enabled, false)
    assert.equal(config.conciseMode.defaultMode, "lite")
    assert.deepEqual(config.hooks.disabled, ["safety"])
    assert.equal(config.llmDecisionRuntime.enabled, true)
    assert.equal(config.llmDecisionRuntime.mode, "disabled")
    assert.deepEqual(config.llmDecisionRuntime.hookModes, {
      "auto-slash-command": "shadow",
      "provider-error-classifier": "assist",
    })
    assert.equal(config.llmDecisionRuntime.timeoutMs, 4321)
  } finally {
    if (previousEnvPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    } else {
      process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH = previousEnvPath
    }
    if (previousHome === undefined) {
      delete process.env.HOME
    } else {
      process.env.HOME = previousHome
    }
    rmSync(root, { recursive: true, force: true })
  }
})

test("explicit gateway config env path replaces automatic sidecar layers", () => {
  const root = mkdtempSync(join(tmpdir(), "gateway-config-env-layer-"))
  const explicitPath = join(root, "explicit.json")
  const previousEnvPath = process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
  try {
    mkdirSync(join(root, ".opencode"), { recursive: true })
    writeFileSync(
      join(root, ".opencode", "gateway-core.config.json"),
      JSON.stringify({ globalProcessPressure: { enabled: false } }),
      "utf-8",
    )
    writeFileSync(
      explicitPath,
      JSON.stringify({ globalProcessPressure: { enabled: true } }),
      "utf-8",
    )
    process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH = explicitPath

    const loaded = loadGatewayConfigSourceWithMeta(root, {})
    const config = loadGatewayConfig(loaded.source)

    assert.deepEqual(loaded.meta.layers.map((layer) => layer.kind), ["env"])
    assert.equal(loaded.meta.sidecarPath, explicitPath)
    assert.equal(config.globalProcessPressure.enabled, true)
  } finally {
    if (previousEnvPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    } else {
      process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH = previousEnvPath
    }
    rmSync(root, { recursive: true, force: true })
  }
})

test("loadGatewayConfigSourceWithMeta falls back to bundled default when no sidecar exists", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-config-bundled-"))
  const previousEnvPath = process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
  const previousHome = process.env.HOME
  try {
    delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    process.env.HOME = directory
    const loaded = loadGatewayConfigSourceWithMeta(directory, {})
    const config = loadGatewayConfig(loaded.source)
    assert.match(loaded.meta.sidecarPath, /plugin[\\/]gateway-core[\\/]config[\\/]default-gateway-core\.config\.json$/)
    assert.equal(loaded.meta.sidecarExists, true)
    assert.equal(loaded.meta.sidecarLoaded, true)
    assert.equal(config.llmDecisionRuntime.enabled, false)
    assert.equal(config.llmDecisionRuntime.mode, "disabled")
    assert.deepEqual(config.llmDecisionRuntime.hookModes, {})
  } finally {
    if (previousEnvPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    } else {
      process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH = previousEnvPath
    }
    if (previousHome === undefined) {
      delete process.env.HOME
    } else {
      process.env.HOME = previousHome
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("npm package includes bundled disabled gateway defaults", () => {
  const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)))
  const output = execFileSync(
    "npm",
    ["pack", "--dry-run", "--json", "--ignore-scripts"],
    { cwd: packageRoot, encoding: "utf8" },
  )
  const payload = JSON.parse(output)
  const files = payload[0].files.map((item) => item.path)
  assert.ok(files.includes("config/default-gateway-core.config.json"))
})

test("loadGatewayConfigSourceWithMeta uses home sidecar before bundled default", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-config-home-"))
  const previousEnvPath = process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
  const previousHome = process.env.HOME
  try {
    delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    process.env.HOME = directory
    const homeSidecar = join(
      directory,
      ".config",
      "opencode",
      "my_opencode",
      "gateway-core.config.json",
    )
    mkdirSync(dirname(homeSidecar), { recursive: true })
    writeFileSync(
      homeSidecar,
      JSON.stringify({
        llmDecisionRuntime: {
          enabled: true,
          mode: "shadow",
          hookModes: { "todo-continuation-enforcer": "enforce" },
        },
      }),
      "utf-8",
    )
    const loaded = loadGatewayConfigSourceWithMeta(directory, {})
    const config = loadGatewayConfig(loaded.source)
    assert.equal(loaded.meta.sidecarPath, homeSidecar)
    assert.equal(loaded.meta.sidecarExists, true)
    assert.equal(loaded.meta.sidecarLoaded, true)
    assert.equal(config.llmDecisionRuntime.mode, "shadow")
    assert.equal(config.llmDecisionRuntime.hookModes["todo-continuation-enforcer"], "enforce")
  } finally {
    if (previousEnvPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    } else {
      process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH = previousEnvPath
    }
    if (previousHome === undefined) {
      delete process.env.HOME
    } else {
      process.env.HOME = previousHome
    }
    rmSync(directory, { recursive: true, force: true })
  }
})

test("loadGatewayConfigSourceWithMeta reports bundled sidecar load success", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-config-meta-"))
  try {
    mkdirSync(join(directory, ".opencode"), { recursive: true })
    const sidecarPath = join(directory, ".opencode", "gateway-core.config.json")
    writeFileSync(
      sidecarPath,
      JSON.stringify({
        llmDecisionRuntime: {
          enabled: true,
          mode: "assist",
        },
      }),
      "utf-8",
    )
    const loaded = loadGatewayConfigSourceWithMeta(directory, {})
    const config = loadGatewayConfig(loaded.source)
    assert.equal(loaded.meta.sidecarPath, sidecarPath)
    assert.equal(loaded.meta.sidecarExists, true)
    assert.equal(loaded.meta.sidecarLoaded, true)
    assert.equal(loaded.meta.sidecarError, undefined)
    assert.equal(config.llmDecisionRuntime.enabled, true)
    assert.equal(config.llmDecisionRuntime.mode, "assist")
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("valid project config rebuilds state after malformed home config", () => {
  const root = mkdtempSync(join(tmpdir(), "gateway-config-home-error-"))
  const project = join(root, "project")
  const home = join(root, "home")
  const previousEnvPath = process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
  const previousHome = process.env.HOME
  try {
    delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    process.env.HOME = home
    const homeSidecar = join(
      home,
      ".config",
      "opencode",
      "my_opencode",
      "gateway-core.config.json",
    )
    const projectSidecar = join(project, ".opencode", "gateway-core.config.json")
    mkdirSync(dirname(homeSidecar), { recursive: true })
    mkdirSync(dirname(projectSidecar), { recursive: true })
    writeFileSync(homeSidecar, "{not-json", "utf-8")
    writeFileSync(
      projectSidecar,
      JSON.stringify({
        globalProcessPressure: { enabled: false },
        conciseMode: { enabled: true, defaultMode: "lite" },
      }),
      "utf-8",
    )

    const loaded = loadGatewayConfigSourceWithMeta(project, {})
    const config = loadGatewayConfig(loaded.source)

    assert.deepEqual(
      loaded.meta.layers.map((layer) => [layer.kind, layer.loaded, Boolean(layer.error)]),
      [["home", false, true], ["project", true, false]],
    )
    assert.equal(loaded.meta.sidecarPath, projectSidecar)
    assert.equal(loaded.meta.sidecarLoaded, true)
    assert.equal(config.globalProcessPressure.enabled, false)
    assert.equal(config.conciseMode.defaultMode, "lite")
  } finally {
    if (previousEnvPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    } else {
      process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH = previousEnvPath
    }
    if (previousHome === undefined) {
      delete process.env.HOME
    } else {
      process.env.HOME = previousHome
    }
    rmSync(root, { recursive: true, force: true })
  }
})

test("malformed higher-precedence project config intentionally clears lower sidecar state", () => {
  const root = mkdtempSync(join(tmpdir(), "gateway-config-meta-error-"))
  const project = join(root, "project")
  const home = join(root, "home")
  const previousEnvPath = process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
  const previousHome = process.env.HOME
  try {
    delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    process.env.HOME = home
    const homeSidecar = join(
      home,
      ".config",
      "opencode",
      "my_opencode",
      "gateway-core.config.json",
    )
    const projectSidecar = join(project, ".opencode", "gateway-core.config.json")
    mkdirSync(dirname(homeSidecar), { recursive: true })
    mkdirSync(dirname(projectSidecar), { recursive: true })
    writeFileSync(
      homeSidecar,
      JSON.stringify({ globalProcessPressure: { enabled: false } }),
      "utf-8",
    )
    writeFileSync(projectSidecar, "{not-json", "utf-8")

    const loaded = loadGatewayConfigSourceWithMeta(project, {
      llmDecisionRuntime: {
        enabled: true,
        mode: "assist",
      },
    })
    const config = loadGatewayConfig(loaded.source)

    assert.equal(loaded.meta.sidecarPath, projectSidecar)
    assert.equal(loaded.meta.sidecarExists, true)
    assert.equal(loaded.meta.sidecarLoaded, false)
    assert.match(String(loaded.meta.sidecarError), /project:.*(?:property name|json|position)/i)
    assert.equal(config.globalProcessPressure.enabled, true)
    assert.equal(config.llmDecisionRuntime.enabled, true)
    assert.equal(config.llmDecisionRuntime.mode, "assist")
  } finally {
    if (previousEnvPath === undefined) {
      delete process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH
    } else {
      process.env.MY_OPENCODE_GATEWAY_CONFIG_PATH = previousEnvPath
    }
    if (previousHome === undefined) {
      delete process.env.HOME
    } else {
      process.env.HOME = previousHome
    }
    rmSync(root, { recursive: true, force: true })
  }
})

test("loadGatewayConfig keeps default maxIgnoredCompletionCycles", () => {
  const config = loadGatewayConfig({})
  assert.equal(config.autopilotLoop.maxIgnoredCompletionCycles, 1)
})

test("loadGatewayConfig normalizes maxIgnoredCompletionCycles to positive integer", () => {
  const zeroConfig = loadGatewayConfig({
    autopilotLoop: {
      maxIgnoredCompletionCycles: 0,
    },
  })
  assert.equal(zeroConfig.autopilotLoop.maxIgnoredCompletionCycles, 1)

  const explicitConfig = loadGatewayConfig({
    autopilotLoop: {
      maxIgnoredCompletionCycles: 5,
    },
  })
  assert.equal(explicitConfig.autopilotLoop.maxIgnoredCompletionCycles, 5)
})


test("loadGatewayConfigSourceWithMeta applies official options after legacy config", () => {
  const loaded = loadGatewayConfigSourceWithMeta(
    process.cwd(),
    {
      hooks: { enabled: true, disabled: ["legacy-disabled"] },
      thinkMode: { enabled: false },
    },
    {
      hooks: { enabled: false, disabled: ["official-disabled"] },
      thinkMode: { enabled: true },
    },
  )
  assert.equal(loaded.source.hooks.enabled, false)
  assert.deepEqual(loaded.source.hooks.disabled, ["official-disabled"])
  assert.equal(loaded.source.thinkMode.enabled, true)
})
