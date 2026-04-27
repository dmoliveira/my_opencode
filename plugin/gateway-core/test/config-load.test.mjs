import assert from "node:assert/strict"
import test from "node:test"

import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"

import {
  loadGatewayConfig,
  loadGatewayConfigSource,
  loadGatewayConfigSourceWithMeta,
} from "../dist/config/load.js"

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

test("loadGatewayConfig normalizes invalid maxConcurrentWriters", () => {
  const config = loadGatewayConfig({
    parallelWriterConflictGuard: {
      maxConcurrentWriters: 0,
    },
  })
  assert.equal(config.parallelWriterConflictGuard.maxConcurrentWriters, 2)
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

test("loadGatewayConfig normalizes llm hook mode overrides", () => {
  const config = loadGatewayConfig({
    llmDecisionRuntime: {
      enabled: true,
      mode: "shadow",
      hookModes: {
        "auto-slash-command": "assist",
        "provider-error-classifier": "assist",
        ignored: "invalid",
      },
    },
  })
  assert.equal(config.llmDecisionRuntime.mode, "shadow")
  assert.deepEqual(config.llmDecisionRuntime.hookModes, {
    "auto-slash-command": "assist",
    "provider-error-classifier": "assist",
  })
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
    assert.equal(config.llmDecisionRuntime.enabled, true)
    assert.equal(config.llmDecisionRuntime.mode, "assist")
    assert.equal(config.llmDecisionRuntime.hookModes["todo-continuation-enforcer"], "assist")
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

test("loadGatewayConfigSourceWithMeta reports sidecar parse failures", () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-config-meta-error-"))
  try {
    mkdirSync(join(directory, ".opencode"), { recursive: true })
    const sidecarPath = join(directory, ".opencode", "gateway-core.config.json")
    writeFileSync(sidecarPath, "{not-json", "utf-8")
    const loaded = loadGatewayConfigSourceWithMeta(directory, {
      llmDecisionRuntime: {
        enabled: true,
        mode: "assist",
      },
    })
    const config = loadGatewayConfig(loaded.source)
    assert.equal(loaded.meta.sidecarPath, sidecarPath)
    assert.equal(loaded.meta.sidecarExists, true)
    assert.equal(loaded.meta.sidecarLoaded, false)
    assert.match(String(loaded.meta.sidecarError), /expected property name|json|position/i)
    assert.equal(config.llmDecisionRuntime.enabled, true)
    assert.equal(config.llmDecisionRuntime.mode, "assist")
  } finally {
    rmSync(directory, { recursive: true, force: true })
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
