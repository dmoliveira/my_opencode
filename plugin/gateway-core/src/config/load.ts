import { DEFAULT_GATEWAY_CONFIG, type GatewayConfig } from "./schema.js"

// Coerces unknown value into a normalized string array.
function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

// Coerces unknown value into a safe non-negative integer fallback.
function nonNegativeInt(value: unknown, fallback: number): number {
  const parsed = Number.parseInt(String(value ?? ""), 10)
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallback
  }
  return parsed
}

// Coerces unknown value into a safe positive integer fallback.
function positiveInt(value: unknown, fallback: number): number {
  const parsed = Number.parseInt(String(value ?? ""), 10)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback
  }
  return parsed
}

// Coerces unknown value into bounded float fallback.
function boundedFloat(value: unknown, min: number, max: number, fallback: number): number {
  const parsed = Number.parseFloat(String(value ?? ""))
  if (!Number.isFinite(parsed)) {
    return fallback
  }
  if (parsed < min || parsed > max) {
    return fallback
  }
  return parsed
}

function markerMode(value: unknown, fallback: "nerd" | "plain" | "both"): "nerd" | "plain" | "both" {
  if (value === "nerd" || value === "plain" || value === "both") {
    return value
  }
  return fallback
}

function guardVerbosity(
  value: unknown,
  fallback: "minimal" | "normal" | "debug",
): "minimal" | "normal" | "debug" {
  if (value === "minimal" || value === "normal" || value === "debug") {
    return value
  }
  return fallback
}

// Loads and normalizes gateway plugin config from unknown input.
export function loadGatewayConfig(raw: unknown): GatewayConfig {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {}
  const hooksSource =
    source.hooks && typeof source.hooks === "object"
      ? (source.hooks as Record<string, unknown>)
      : {}
  const autopilotSource =
    source.autopilotLoop && typeof source.autopilotLoop === "object"
      ? (source.autopilotLoop as Record<string, unknown>)
      : {}
  const qualitySource =
    source.quality && typeof source.quality === "object"
      ? (source.quality as Record<string, unknown>)
      : {}
  const truncatorSource =
    source.toolOutputTruncator && typeof source.toolOutputTruncator === "object"
      ? (source.toolOutputTruncator as Record<string, unknown>)
      : {}
  const contextWindowSource =
    source.contextWindowMonitor && typeof source.contextWindowMonitor === "object"
      ? (source.contextWindowMonitor as Record<string, unknown>)
      : {}
  const preemptiveCompactionSource =
    source.preemptiveCompaction && typeof source.preemptiveCompaction === "object"
      ? (source.preemptiveCompaction as Record<string, unknown>)
      : {}
  const compactionContextInjectorSource =
    source.compactionContextInjector && typeof source.compactionContextInjector === "object"
      ? (source.compactionContextInjector as Record<string, unknown>)
      : {}
  const globalProcessPressureSource =
    source.globalProcessPressure && typeof source.globalProcessPressure === "object"
      ? (source.globalProcessPressure as Record<string, unknown>)
      : {}
  const sessionRecoverySource =
    source.sessionRecovery && typeof source.sessionRecovery === "object"
      ? (source.sessionRecovery as Record<string, unknown>)
      : {}
  const delegateTaskRetrySource =
    source.delegateTaskRetry && typeof source.delegateTaskRetry === "object"
      ? (source.delegateTaskRetry as Record<string, unknown>)
      : {}
  const validationEvidenceLedgerSource =
    source.validationEvidenceLedger && typeof source.validationEvidenceLedger === "object"
      ? (source.validationEvidenceLedger as Record<string, unknown>)
      : {}
  const parallelOpportunitySource =
    source.parallelOpportunityDetector && typeof source.parallelOpportunityDetector === "object"
      ? (source.parallelOpportunityDetector as Record<string, unknown>)
      : {}
  const readBudgetOptimizerSource =
    source.readBudgetOptimizer && typeof source.readBudgetOptimizer === "object"
      ? (source.readBudgetOptimizer as Record<string, unknown>)
      : {}
  const adaptiveValidationSchedulerSource =
    source.adaptiveValidationScheduler && typeof source.adaptiveValidationScheduler === "object"
      ? (source.adaptiveValidationScheduler as Record<string, unknown>)
      : {}
  const stopGuardSource =
    source.stopContinuationGuard && typeof source.stopContinuationGuard === "object"
      ? (source.stopContinuationGuard as Record<string, unknown>)
      : {}
  const keywordDetectorSource =
    source.keywordDetector && typeof source.keywordDetector === "object"
      ? (source.keywordDetector as Record<string, unknown>)
      : {}
  const thinkModeSource =
    source.thinkMode && typeof source.thinkMode === "object"
      ? (source.thinkMode as Record<string, unknown>)
      : {}
  const thinkingBlockValidatorSource =
    source.thinkingBlockValidator && typeof source.thinkingBlockValidator === "object"
      ? (source.thinkingBlockValidator as Record<string, unknown>)
      : {}
  const autoSlashSource =
    source.autoSlashCommand && typeof source.autoSlashCommand === "object"
      ? (source.autoSlashCommand as Record<string, unknown>)
      : {}
  const rulesInjectorSource =
    source.rulesInjector && typeof source.rulesInjector === "object"
      ? (source.rulesInjector as Record<string, unknown>)
      : {}
  const directoryAgentsSource =
    source.directoryAgentsInjector && typeof source.directoryAgentsInjector === "object"
      ? (source.directoryAgentsInjector as Record<string, unknown>)
      : {}
  const directoryReadmeSource =
    source.directoryReadmeInjector && typeof source.directoryReadmeInjector === "object"
      ? (source.directoryReadmeInjector as Record<string, unknown>)
      : {}
  const noninteractiveShellSource =
    source.noninteractiveShellGuard && typeof source.noninteractiveShellGuard === "object"
      ? (source.noninteractiveShellGuard as Record<string, unknown>)
      : {}
  const writeExistingGuardSource =
    source.writeExistingFileGuard && typeof source.writeExistingFileGuard === "object"
      ? (source.writeExistingFileGuard as Record<string, unknown>)
      : {}
  const agentReservationSource =
    source.agentReservationGuard && typeof source.agentReservationGuard === "object"
      ? (source.agentReservationGuard as Record<string, unknown>)
      : {}
  const subagentQuestionSource =
    source.subagentQuestionBlocker && typeof source.subagentQuestionBlocker === "object"
      ? (source.subagentQuestionBlocker as Record<string, unknown>)
      : {}
  const tasksTodowriteSource =
    source.tasksTodowriteDisabler && typeof source.tasksTodowriteDisabler === "object"
      ? (source.tasksTodowriteDisabler as Record<string, unknown>)
      : {}
  const taskResumeInfoSource =
    source.taskResumeInfo && typeof source.taskResumeInfo === "object"
      ? (source.taskResumeInfo as Record<string, unknown>)
      : {}
  const emptyTaskResponseSource =
    source.emptyTaskResponseDetector && typeof source.emptyTaskResponseDetector === "object"
      ? (source.emptyTaskResponseDetector as Record<string, unknown>)
      : {}
  const commentCheckerSource =
    source.commentChecker && typeof source.commentChecker === "object"
      ? (source.commentChecker as Record<string, unknown>)
      : {}
  const agentUserReminderSource =
    source.agentUserReminder && typeof source.agentUserReminder === "object"
      ? (source.agentUserReminder as Record<string, unknown>)
      : {}
  const unstableBabysitterSource =
    source.unstableAgentBabysitter && typeof source.unstableAgentBabysitter === "object"
      ? (source.unstableAgentBabysitter as Record<string, unknown>)
      : {}
  const questionLabelSource =
    source.questionLabelTruncator && typeof source.questionLabelTruncator === "object"
      ? (source.questionLabelTruncator as Record<string, unknown>)
      : {}
  const semanticOutputSummarizerSource =
    source.semanticOutputSummarizer && typeof source.semanticOutputSummarizer === "object"
      ? (source.semanticOutputSummarizer as Record<string, unknown>)
      : {}
  const dangerousCommandSource =
    source.dangerousCommandGuard && typeof source.dangerousCommandGuard === "object"
      ? (source.dangerousCommandGuard as Record<string, unknown>)
      : {}
  const secretLeakSource =
    source.secretLeakGuard && typeof source.secretLeakGuard === "object"
      ? (source.secretLeakGuard as Record<string, unknown>)
      : {}
  const workflowConformanceSource =
    source.workflowConformanceGuard && typeof source.workflowConformanceGuard === "object"
      ? (source.workflowConformanceGuard as Record<string, unknown>)
      : {}
  const scopeDriftSource =
    source.scopeDriftGuard && typeof source.scopeDriftGuard === "object"
      ? (source.scopeDriftGuard as Record<string, unknown>)
      : {}
  const doneProofSource =
    source.doneProofEnforcer && typeof source.doneProofEnforcer === "object"
      ? (source.doneProofEnforcer as Record<string, unknown>)
      : {}
  const dependencyRiskSource =
    source.dependencyRiskGuard && typeof source.dependencyRiskGuard === "object"
      ? (source.dependencyRiskGuard as Record<string, unknown>)
      : {}
  const docsDriftSource =
    source.docsDriftGuard && typeof source.docsDriftGuard === "object"
      ? (source.docsDriftGuard as Record<string, unknown>)
      : {}
  const hookTestParitySource =
    source.hookTestParityGuard && typeof source.hookTestParityGuard === "object"
      ? (source.hookTestParityGuard as Record<string, unknown>)
      : {}
  const retryBudgetSource =
    source.retryBudgetGuard && typeof source.retryBudgetGuard === "object"
      ? (source.retryBudgetGuard as Record<string, unknown>)
      : {}
  const staleLoopExpirySource =
    source.staleLoopExpiryGuard && typeof source.staleLoopExpiryGuard === "object"
      ? (source.staleLoopExpiryGuard as Record<string, unknown>)
      : {}
  const branchFreshnessSource =
    source.branchFreshnessGuard && typeof source.branchFreshnessGuard === "object"
      ? (source.branchFreshnessGuard as Record<string, unknown>)
      : {}
  const prReadinessSource =
    source.prReadinessGuard && typeof source.prReadinessGuard === "object"
      ? (source.prReadinessGuard as Record<string, unknown>)
      : {}
  const mergeReadinessSource =
    source.mergeReadinessGuard && typeof source.mergeReadinessGuard === "object"
      ? (source.mergeReadinessGuard as Record<string, unknown>)
      : {}
  const ghChecksMergeSource =
    source.ghChecksMergeGuard && typeof source.ghChecksMergeGuard === "object"
      ? (source.ghChecksMergeGuard as Record<string, unknown>)
      : {}
  const postMergeSyncSource =
    source.postMergeSyncGuard && typeof source.postMergeSyncGuard === "object"
      ? (source.postMergeSyncGuard as Record<string, unknown>)
      : {}
  const parallelWriterConflictSource =
    source.parallelWriterConflictGuard && typeof source.parallelWriterConflictGuard === "object"
      ? (source.parallelWriterConflictGuard as Record<string, unknown>)
      : {}
  const secretCommitSource =
    source.secretCommitGuard && typeof source.secretCommitGuard === "object"
      ? (source.secretCommitGuard as Record<string, unknown>)
      : {}
  const prBodyEvidenceSource =
    source.prBodyEvidenceGuard && typeof source.prBodyEvidenceGuard === "object"
      ? (source.prBodyEvidenceGuard as Record<string, unknown>)
      : {}
  const tsSource =
    qualitySource.ts && typeof qualitySource.ts === "object"
      ? (qualitySource.ts as Record<string, unknown>)
      : {}
  const pySource =
    qualitySource.py && typeof qualitySource.py === "object"
      ? (qualitySource.py as Record<string, unknown>)
      : {}

  const completionMode =
    autopilotSource.completionMode === "objective" ? "objective" : "promise"
  const qualityProfile =
    qualitySource.profile === "off" || qualitySource.profile === "strict"
      ? qualitySource.profile
      : "fast"
  const truncatorTools =
    truncatorSource.tools === undefined
      ? DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.tools
      : stringList(truncatorSource.tools)

  return {
    hooks: {
      enabled:
        typeof hooksSource.enabled === "boolean"
          ? hooksSource.enabled
          : DEFAULT_GATEWAY_CONFIG.hooks.enabled,
      disabled: stringList(hooksSource.disabled),
      order: stringList(hooksSource.order),
    },
    autopilotLoop: {
      enabled:
        typeof autopilotSource.enabled === "boolean"
          ? autopilotSource.enabled
          : DEFAULT_GATEWAY_CONFIG.autopilotLoop.enabled,
      maxIterations: nonNegativeInt(
        autopilotSource.maxIterations,
        DEFAULT_GATEWAY_CONFIG.autopilotLoop.maxIterations,
      ),
      orphanMaxAgeHours: nonNegativeInt(
        autopilotSource.orphanMaxAgeHours,
        DEFAULT_GATEWAY_CONFIG.autopilotLoop.orphanMaxAgeHours,
      ),
      bootstrapFromRuntimeOnIdle:
        typeof autopilotSource.bootstrapFromRuntimeOnIdle === "boolean"
          ? autopilotSource.bootstrapFromRuntimeOnIdle
          : DEFAULT_GATEWAY_CONFIG.autopilotLoop.bootstrapFromRuntimeOnIdle,
      maxIgnoredCompletionCycles: positiveInt(
        autopilotSource.maxIgnoredCompletionCycles,
        DEFAULT_GATEWAY_CONFIG.autopilotLoop.maxIgnoredCompletionCycles,
      ),
      completionMode,
      completionPromise:
        typeof autopilotSource.completionPromise === "string" &&
        autopilotSource.completionPromise.trim().length > 0
          ? autopilotSource.completionPromise.trim()
          : DEFAULT_GATEWAY_CONFIG.autopilotLoop.completionPromise,
    },
    toolOutputTruncator: {
      enabled:
        typeof truncatorSource.enabled === "boolean"
          ? truncatorSource.enabled
          : DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.enabled,
      maxChars: nonNegativeInt(
        truncatorSource.maxChars,
        DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.maxChars,
      ),
      maxLines: nonNegativeInt(
        truncatorSource.maxLines,
        DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.maxLines,
      ),
      tools: truncatorTools,
    },
    contextWindowMonitor: {
      enabled:
        typeof contextWindowSource.enabled === "boolean"
          ? contextWindowSource.enabled
          : DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.enabled,
      warningThreshold: boundedFloat(
        contextWindowSource.warningThreshold,
        0.5,
        0.95,
        DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.warningThreshold,
      ),
      reminderCooldownToolCalls: positiveInt(
        contextWindowSource.reminderCooldownToolCalls,
        DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.reminderCooldownToolCalls,
      ),
      minTokenDeltaForReminder: nonNegativeInt(
        contextWindowSource.minTokenDeltaForReminder,
        DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.minTokenDeltaForReminder,
      ),
      defaultContextLimitTokens: positiveInt(
        contextWindowSource.defaultContextLimitTokens,
        DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.defaultContextLimitTokens,
      ),
      guardMarkerMode: markerMode(
        contextWindowSource.guardMarkerMode,
        DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.guardMarkerMode,
      ),
      guardVerbosity: guardVerbosity(
        contextWindowSource.guardVerbosity,
        DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.guardVerbosity,
      ),
      maxSessionStateEntries: positiveInt(
        contextWindowSource.maxSessionStateEntries,
        DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.maxSessionStateEntries,
      ),
    },
    preemptiveCompaction: {
      enabled:
        typeof preemptiveCompactionSource.enabled === "boolean"
          ? preemptiveCompactionSource.enabled
          : DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.enabled,
      warningThreshold: boundedFloat(
        preemptiveCompactionSource.warningThreshold,
        0.6,
        0.95,
        DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.warningThreshold,
      ),
      compactionCooldownToolCalls: positiveInt(
        preemptiveCompactionSource.compactionCooldownToolCalls,
        DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.compactionCooldownToolCalls,
      ),
      minTokenDeltaForCompaction: nonNegativeInt(
        preemptiveCompactionSource.minTokenDeltaForCompaction,
        DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.minTokenDeltaForCompaction,
      ),
      defaultContextLimitTokens: positiveInt(
        preemptiveCompactionSource.defaultContextLimitTokens,
        DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.defaultContextLimitTokens,
      ),
      guardMarkerMode: markerMode(
        preemptiveCompactionSource.guardMarkerMode,
        DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.guardMarkerMode,
      ),
      guardVerbosity: guardVerbosity(
        preemptiveCompactionSource.guardVerbosity,
        DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.guardVerbosity,
      ),
      maxSessionStateEntries: positiveInt(
        preemptiveCompactionSource.maxSessionStateEntries,
        DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.maxSessionStateEntries,
      ),
    },
    compactionContextInjector: {
      enabled:
        typeof compactionContextInjectorSource.enabled === "boolean"
          ? compactionContextInjectorSource.enabled
          : DEFAULT_GATEWAY_CONFIG.compactionContextInjector.enabled,
    },
    globalProcessPressure: {
      enabled:
        typeof globalProcessPressureSource.enabled === "boolean"
          ? globalProcessPressureSource.enabled
          : DEFAULT_GATEWAY_CONFIG.globalProcessPressure.enabled,
      checkCooldownToolCalls: positiveInt(
        globalProcessPressureSource.checkCooldownToolCalls,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.checkCooldownToolCalls,
      ),
      reminderCooldownToolCalls: positiveInt(
        globalProcessPressureSource.reminderCooldownToolCalls,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.reminderCooldownToolCalls,
      ),
      criticalReminderCooldownToolCalls: positiveInt(
        globalProcessPressureSource.criticalReminderCooldownToolCalls,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.criticalReminderCooldownToolCalls,
      ),
      criticalEscalationWindowToolCalls: positiveInt(
        globalProcessPressureSource.criticalEscalationWindowToolCalls,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.criticalEscalationWindowToolCalls,
      ),
      criticalPauseAfterEvents: positiveInt(
        globalProcessPressureSource.criticalPauseAfterEvents,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.criticalPauseAfterEvents,
      ),
      criticalEscalationAfterEvents: positiveInt(
        globalProcessPressureSource.criticalEscalationAfterEvents,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.criticalEscalationAfterEvents,
      ),
      warningContinueSessions: positiveInt(
        globalProcessPressureSource.warningContinueSessions,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.warningContinueSessions,
      ),
      warningOpencodeProcesses: positiveInt(
        globalProcessPressureSource.warningOpencodeProcesses,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.warningOpencodeProcesses,
      ),
      warningMaxRssMb: positiveInt(
        globalProcessPressureSource.warningMaxRssMb,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.warningMaxRssMb,
      ),
      criticalMaxRssMb: positiveInt(
        globalProcessPressureSource.criticalMaxRssMb,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.criticalMaxRssMb,
      ),
      autoPauseOnCritical:
        typeof globalProcessPressureSource.autoPauseOnCritical === "boolean"
          ? globalProcessPressureSource.autoPauseOnCritical
          : DEFAULT_GATEWAY_CONFIG.globalProcessPressure.autoPauseOnCritical,
      notifyOnCritical:
        typeof globalProcessPressureSource.notifyOnCritical === "boolean"
          ? globalProcessPressureSource.notifyOnCritical
          : DEFAULT_GATEWAY_CONFIG.globalProcessPressure.notifyOnCritical,
      guardMarkerMode: markerMode(
        globalProcessPressureSource.guardMarkerMode,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.guardMarkerMode,
      ),
      guardVerbosity: guardVerbosity(
        globalProcessPressureSource.guardVerbosity,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.guardVerbosity,
      ),
      maxSessionStateEntries: positiveInt(
        globalProcessPressureSource.maxSessionStateEntries,
        DEFAULT_GATEWAY_CONFIG.globalProcessPressure.maxSessionStateEntries,
      ),
    },
    sessionRecovery: {
      enabled:
        typeof sessionRecoverySource.enabled === "boolean"
          ? sessionRecoverySource.enabled
          : DEFAULT_GATEWAY_CONFIG.sessionRecovery.enabled,
      autoResume:
        typeof sessionRecoverySource.autoResume === "boolean"
          ? sessionRecoverySource.autoResume
          : DEFAULT_GATEWAY_CONFIG.sessionRecovery.autoResume,
    },
    delegateTaskRetry: {
      enabled:
        typeof delegateTaskRetrySource.enabled === "boolean"
          ? delegateTaskRetrySource.enabled
          : DEFAULT_GATEWAY_CONFIG.delegateTaskRetry.enabled,
    },
    validationEvidenceLedger: {
      enabled:
        typeof validationEvidenceLedgerSource.enabled === "boolean"
          ? validationEvidenceLedgerSource.enabled
          : DEFAULT_GATEWAY_CONFIG.validationEvidenceLedger.enabled,
    },
    parallelOpportunityDetector: {
      enabled:
        typeof parallelOpportunitySource.enabled === "boolean"
          ? parallelOpportunitySource.enabled
          : DEFAULT_GATEWAY_CONFIG.parallelOpportunityDetector.enabled,
    },
    readBudgetOptimizer: {
      enabled:
        typeof readBudgetOptimizerSource.enabled === "boolean"
          ? readBudgetOptimizerSource.enabled
          : DEFAULT_GATEWAY_CONFIG.readBudgetOptimizer.enabled,
      smallReadLimit: nonNegativeInt(
        readBudgetOptimizerSource.smallReadLimit,
        DEFAULT_GATEWAY_CONFIG.readBudgetOptimizer.smallReadLimit,
      ),
      maxConsecutiveSmallReads: nonNegativeInt(
        readBudgetOptimizerSource.maxConsecutiveSmallReads,
        DEFAULT_GATEWAY_CONFIG.readBudgetOptimizer.maxConsecutiveSmallReads,
      ),
    },
    adaptiveValidationScheduler: {
      enabled:
        typeof adaptiveValidationSchedulerSource.enabled === "boolean"
          ? adaptiveValidationSchedulerSource.enabled
          : DEFAULT_GATEWAY_CONFIG.adaptiveValidationScheduler.enabled,
      reminderEditThreshold: nonNegativeInt(
        adaptiveValidationSchedulerSource.reminderEditThreshold,
        DEFAULT_GATEWAY_CONFIG.adaptiveValidationScheduler.reminderEditThreshold,
      ),
    },
    stopContinuationGuard: {
      enabled:
        typeof stopGuardSource.enabled === "boolean"
          ? stopGuardSource.enabled
          : DEFAULT_GATEWAY_CONFIG.stopContinuationGuard.enabled,
    },
    keywordDetector: {
      enabled:
        typeof keywordDetectorSource.enabled === "boolean"
          ? keywordDetectorSource.enabled
          : DEFAULT_GATEWAY_CONFIG.keywordDetector.enabled,
    },
    thinkMode: {
      enabled:
        typeof thinkModeSource.enabled === "boolean"
          ? thinkModeSource.enabled
          : DEFAULT_GATEWAY_CONFIG.thinkMode.enabled,
    },
    thinkingBlockValidator: {
      enabled:
        typeof thinkingBlockValidatorSource.enabled === "boolean"
          ? thinkingBlockValidatorSource.enabled
          : DEFAULT_GATEWAY_CONFIG.thinkingBlockValidator.enabled,
    },
    autoSlashCommand: {
      enabled:
        typeof autoSlashSource.enabled === "boolean"
          ? autoSlashSource.enabled
          : DEFAULT_GATEWAY_CONFIG.autoSlashCommand.enabled,
    },
    rulesInjector: {
      enabled:
        typeof rulesInjectorSource.enabled === "boolean"
          ? rulesInjectorSource.enabled
          : DEFAULT_GATEWAY_CONFIG.rulesInjector.enabled,
    },
    directoryAgentsInjector: {
      enabled:
        typeof directoryAgentsSource.enabled === "boolean"
          ? directoryAgentsSource.enabled
          : DEFAULT_GATEWAY_CONFIG.directoryAgentsInjector.enabled,
      maxChars: positiveInt(
        directoryAgentsSource.maxChars,
        DEFAULT_GATEWAY_CONFIG.directoryAgentsInjector.maxChars,
      ),
    },
    directoryReadmeInjector: {
      enabled:
        typeof directoryReadmeSource.enabled === "boolean"
          ? directoryReadmeSource.enabled
          : DEFAULT_GATEWAY_CONFIG.directoryReadmeInjector.enabled,
      maxChars: positiveInt(
        directoryReadmeSource.maxChars,
        DEFAULT_GATEWAY_CONFIG.directoryReadmeInjector.maxChars,
      ),
    },
    noninteractiveShellGuard: {
      enabled:
        typeof noninteractiveShellSource.enabled === "boolean"
          ? noninteractiveShellSource.enabled
          : DEFAULT_GATEWAY_CONFIG.noninteractiveShellGuard.enabled,
      blockedPatterns:
        noninteractiveShellSource.blockedPatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.noninteractiveShellGuard.blockedPatterns
          : stringList(noninteractiveShellSource.blockedPatterns),
    },
    writeExistingFileGuard: {
      enabled:
        typeof writeExistingGuardSource.enabled === "boolean"
          ? writeExistingGuardSource.enabled
          : DEFAULT_GATEWAY_CONFIG.writeExistingFileGuard.enabled,
    },
    agentReservationGuard: {
      enabled:
        typeof agentReservationSource.enabled === "boolean"
          ? agentReservationSource.enabled
          : DEFAULT_GATEWAY_CONFIG.agentReservationGuard.enabled,
      enforce:
        typeof agentReservationSource.enforce === "boolean"
          ? agentReservationSource.enforce
          : DEFAULT_GATEWAY_CONFIG.agentReservationGuard.enforce,
      reservationEnvKeys:
        agentReservationSource.reservationEnvKeys === undefined
          ? DEFAULT_GATEWAY_CONFIG.agentReservationGuard.reservationEnvKeys
          : stringList(agentReservationSource.reservationEnvKeys),
    },
    subagentQuestionBlocker: {
      enabled:
        typeof subagentQuestionSource.enabled === "boolean"
          ? subagentQuestionSource.enabled
          : DEFAULT_GATEWAY_CONFIG.subagentQuestionBlocker.enabled,
      sessionPatterns:
        subagentQuestionSource.sessionPatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.subagentQuestionBlocker.sessionPatterns
          : stringList(subagentQuestionSource.sessionPatterns),
    },
    tasksTodowriteDisabler: {
      enabled:
        typeof tasksTodowriteSource.enabled === "boolean"
          ? tasksTodowriteSource.enabled
          : DEFAULT_GATEWAY_CONFIG.tasksTodowriteDisabler.enabled,
    },
    taskResumeInfo: {
      enabled:
        typeof taskResumeInfoSource.enabled === "boolean"
          ? taskResumeInfoSource.enabled
          : DEFAULT_GATEWAY_CONFIG.taskResumeInfo.enabled,
    },
    emptyTaskResponseDetector: {
      enabled:
        typeof emptyTaskResponseSource.enabled === "boolean"
          ? emptyTaskResponseSource.enabled
          : DEFAULT_GATEWAY_CONFIG.emptyTaskResponseDetector.enabled,
    },
    commentChecker: {
      enabled:
        typeof commentCheckerSource.enabled === "boolean"
          ? commentCheckerSource.enabled
          : DEFAULT_GATEWAY_CONFIG.commentChecker.enabled,
    },
    agentUserReminder: {
      enabled:
        typeof agentUserReminderSource.enabled === "boolean"
          ? agentUserReminderSource.enabled
          : DEFAULT_GATEWAY_CONFIG.agentUserReminder.enabled,
    },
    unstableAgentBabysitter: {
      enabled:
        typeof unstableBabysitterSource.enabled === "boolean"
          ? unstableBabysitterSource.enabled
          : DEFAULT_GATEWAY_CONFIG.unstableAgentBabysitter.enabled,
      riskyPatterns:
        unstableBabysitterSource.riskyPatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.unstableAgentBabysitter.riskyPatterns
          : stringList(unstableBabysitterSource.riskyPatterns),
    },
    questionLabelTruncator: {
      enabled:
        typeof questionLabelSource.enabled === "boolean"
          ? questionLabelSource.enabled
          : DEFAULT_GATEWAY_CONFIG.questionLabelTruncator.enabled,
      maxLength: nonNegativeInt(
        questionLabelSource.maxLength,
        DEFAULT_GATEWAY_CONFIG.questionLabelTruncator.maxLength,
      ),
    },
    semanticOutputSummarizer: {
      enabled:
        typeof semanticOutputSummarizerSource.enabled === "boolean"
          ? semanticOutputSummarizerSource.enabled
          : DEFAULT_GATEWAY_CONFIG.semanticOutputSummarizer.enabled,
      minChars: nonNegativeInt(
        semanticOutputSummarizerSource.minChars,
        DEFAULT_GATEWAY_CONFIG.semanticOutputSummarizer.minChars,
      ),
      minLines: nonNegativeInt(
        semanticOutputSummarizerSource.minLines,
        DEFAULT_GATEWAY_CONFIG.semanticOutputSummarizer.minLines,
      ),
      maxSummaryLines: nonNegativeInt(
        semanticOutputSummarizerSource.maxSummaryLines,
        DEFAULT_GATEWAY_CONFIG.semanticOutputSummarizer.maxSummaryLines,
      ),
    },
    dangerousCommandGuard: {
      enabled:
        typeof dangerousCommandSource.enabled === "boolean"
          ? dangerousCommandSource.enabled
          : DEFAULT_GATEWAY_CONFIG.dangerousCommandGuard.enabled,
      blockedPatterns:
        dangerousCommandSource.blockedPatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.dangerousCommandGuard.blockedPatterns
          : stringList(dangerousCommandSource.blockedPatterns),
    },
    secretLeakGuard: {
      enabled:
        typeof secretLeakSource.enabled === "boolean"
          ? secretLeakSource.enabled
          : DEFAULT_GATEWAY_CONFIG.secretLeakGuard.enabled,
      redactionToken:
        typeof secretLeakSource.redactionToken === "string" && secretLeakSource.redactionToken.trim().length > 0
          ? secretLeakSource.redactionToken
          : DEFAULT_GATEWAY_CONFIG.secretLeakGuard.redactionToken,
      patterns:
        secretLeakSource.patterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.secretLeakGuard.patterns
          : stringList(secretLeakSource.patterns),
    },
    workflowConformanceGuard: {
      enabled:
        typeof workflowConformanceSource.enabled === "boolean"
          ? workflowConformanceSource.enabled
          : DEFAULT_GATEWAY_CONFIG.workflowConformanceGuard.enabled,
      protectedBranches:
        workflowConformanceSource.protectedBranches === undefined
          ? DEFAULT_GATEWAY_CONFIG.workflowConformanceGuard.protectedBranches
          : stringList(workflowConformanceSource.protectedBranches),
      blockEditsOnProtectedBranches:
        typeof workflowConformanceSource.blockEditsOnProtectedBranches === "boolean"
          ? workflowConformanceSource.blockEditsOnProtectedBranches
          : DEFAULT_GATEWAY_CONFIG.workflowConformanceGuard.blockEditsOnProtectedBranches,
    },
    scopeDriftGuard: {
      enabled:
        typeof scopeDriftSource.enabled === "boolean"
          ? scopeDriftSource.enabled
          : DEFAULT_GATEWAY_CONFIG.scopeDriftGuard.enabled,
      allowedPaths:
        scopeDriftSource.allowedPaths === undefined
          ? DEFAULT_GATEWAY_CONFIG.scopeDriftGuard.allowedPaths
          : stringList(scopeDriftSource.allowedPaths),
      blockOnDrift:
        typeof scopeDriftSource.blockOnDrift === "boolean"
          ? scopeDriftSource.blockOnDrift
          : DEFAULT_GATEWAY_CONFIG.scopeDriftGuard.blockOnDrift,
    },
    doneProofEnforcer: {
      enabled:
        typeof doneProofSource.enabled === "boolean"
          ? doneProofSource.enabled
          : DEFAULT_GATEWAY_CONFIG.doneProofEnforcer.enabled,
      requiredMarkers:
        doneProofSource.requiredMarkers === undefined
          ? DEFAULT_GATEWAY_CONFIG.doneProofEnforcer.requiredMarkers
          : stringList(doneProofSource.requiredMarkers),
      requireLedgerEvidence:
        typeof doneProofSource.requireLedgerEvidence === "boolean"
          ? doneProofSource.requireLedgerEvidence
          : DEFAULT_GATEWAY_CONFIG.doneProofEnforcer.requireLedgerEvidence,
      allowTextFallback:
        typeof doneProofSource.allowTextFallback === "boolean"
          ? doneProofSource.allowTextFallback
          : DEFAULT_GATEWAY_CONFIG.doneProofEnforcer.allowTextFallback,
    },
    dependencyRiskGuard: {
      enabled:
        typeof dependencyRiskSource.enabled === "boolean"
          ? dependencyRiskSource.enabled
          : DEFAULT_GATEWAY_CONFIG.dependencyRiskGuard.enabled,
      lockfilePatterns:
        dependencyRiskSource.lockfilePatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.dependencyRiskGuard.lockfilePatterns
          : stringList(dependencyRiskSource.lockfilePatterns),
      commandPatterns:
        dependencyRiskSource.commandPatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.dependencyRiskGuard.commandPatterns
          : stringList(dependencyRiskSource.commandPatterns),
    },
    docsDriftGuard: {
      enabled:
        typeof docsDriftSource.enabled === "boolean"
          ? docsDriftSource.enabled
          : DEFAULT_GATEWAY_CONFIG.docsDriftGuard.enabled,
      sourcePatterns:
        docsDriftSource.sourcePatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.docsDriftGuard.sourcePatterns
          : stringList(docsDriftSource.sourcePatterns),
      docsPatterns:
        docsDriftSource.docsPatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.docsDriftGuard.docsPatterns
          : stringList(docsDriftSource.docsPatterns),
      blockOnDrift:
        typeof docsDriftSource.blockOnDrift === "boolean"
          ? docsDriftSource.blockOnDrift
          : DEFAULT_GATEWAY_CONFIG.docsDriftGuard.blockOnDrift,
    },
    hookTestParityGuard: {
      enabled:
        typeof hookTestParitySource.enabled === "boolean"
          ? hookTestParitySource.enabled
          : DEFAULT_GATEWAY_CONFIG.hookTestParityGuard.enabled,
      sourcePatterns:
        hookTestParitySource.sourcePatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.hookTestParityGuard.sourcePatterns
          : stringList(hookTestParitySource.sourcePatterns),
      testPatterns:
        hookTestParitySource.testPatterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.hookTestParityGuard.testPatterns
          : stringList(hookTestParitySource.testPatterns),
      blockOnMismatch:
        typeof hookTestParitySource.blockOnMismatch === "boolean"
          ? hookTestParitySource.blockOnMismatch
          : DEFAULT_GATEWAY_CONFIG.hookTestParityGuard.blockOnMismatch,
    },
    retryBudgetGuard: {
      enabled:
        typeof retryBudgetSource.enabled === "boolean"
          ? retryBudgetSource.enabled
          : DEFAULT_GATEWAY_CONFIG.retryBudgetGuard.enabled,
      maxRetries: nonNegativeInt(
        retryBudgetSource.maxRetries,
        DEFAULT_GATEWAY_CONFIG.retryBudgetGuard.maxRetries,
      ),
    },
    staleLoopExpiryGuard: {
      enabled:
        typeof staleLoopExpirySource.enabled === "boolean"
          ? staleLoopExpirySource.enabled
          : DEFAULT_GATEWAY_CONFIG.staleLoopExpiryGuard.enabled,
      maxAgeMinutes: nonNegativeInt(
        staleLoopExpirySource.maxAgeMinutes,
        DEFAULT_GATEWAY_CONFIG.staleLoopExpiryGuard.maxAgeMinutes,
      ),
    },
    branchFreshnessGuard: {
      enabled:
        typeof branchFreshnessSource.enabled === "boolean"
          ? branchFreshnessSource.enabled
          : DEFAULT_GATEWAY_CONFIG.branchFreshnessGuard.enabled,
      baseRef:
        typeof branchFreshnessSource.baseRef === "string" && branchFreshnessSource.baseRef.trim().length > 0
          ? branchFreshnessSource.baseRef.trim()
          : DEFAULT_GATEWAY_CONFIG.branchFreshnessGuard.baseRef,
      maxBehind: nonNegativeInt(
        branchFreshnessSource.maxBehind,
        DEFAULT_GATEWAY_CONFIG.branchFreshnessGuard.maxBehind,
      ),
      enforceOnPrCreate:
        typeof branchFreshnessSource.enforceOnPrCreate === "boolean"
          ? branchFreshnessSource.enforceOnPrCreate
          : DEFAULT_GATEWAY_CONFIG.branchFreshnessGuard.enforceOnPrCreate,
      enforceOnPrMerge:
        typeof branchFreshnessSource.enforceOnPrMerge === "boolean"
          ? branchFreshnessSource.enforceOnPrMerge
          : DEFAULT_GATEWAY_CONFIG.branchFreshnessGuard.enforceOnPrMerge,
    },
    prReadinessGuard: {
      enabled:
        typeof prReadinessSource.enabled === "boolean"
          ? prReadinessSource.enabled
          : DEFAULT_GATEWAY_CONFIG.prReadinessGuard.enabled,
      requireCleanWorktree:
        typeof prReadinessSource.requireCleanWorktree === "boolean"
          ? prReadinessSource.requireCleanWorktree
          : DEFAULT_GATEWAY_CONFIG.prReadinessGuard.requireCleanWorktree,
      requireValidationEvidence:
        typeof prReadinessSource.requireValidationEvidence === "boolean"
          ? prReadinessSource.requireValidationEvidence
          : DEFAULT_GATEWAY_CONFIG.prReadinessGuard.requireValidationEvidence,
    },
    prBodyEvidenceGuard: {
      enabled:
        typeof prBodyEvidenceSource.enabled === "boolean"
          ? prBodyEvidenceSource.enabled
          : DEFAULT_GATEWAY_CONFIG.prBodyEvidenceGuard.enabled,
      requireSummarySection:
        typeof prBodyEvidenceSource.requireSummarySection === "boolean"
          ? prBodyEvidenceSource.requireSummarySection
          : DEFAULT_GATEWAY_CONFIG.prBodyEvidenceGuard.requireSummarySection,
      requireValidationSection:
        typeof prBodyEvidenceSource.requireValidationSection === "boolean"
          ? prBodyEvidenceSource.requireValidationSection
          : DEFAULT_GATEWAY_CONFIG.prBodyEvidenceGuard.requireValidationSection,
      requireValidationEvidence:
        typeof prBodyEvidenceSource.requireValidationEvidence === "boolean"
          ? prBodyEvidenceSource.requireValidationEvidence
          : DEFAULT_GATEWAY_CONFIG.prBodyEvidenceGuard.requireValidationEvidence,
      allowUninspectableBody:
        typeof prBodyEvidenceSource.allowUninspectableBody === "boolean"
          ? prBodyEvidenceSource.allowUninspectableBody
          : DEFAULT_GATEWAY_CONFIG.prBodyEvidenceGuard.allowUninspectableBody,
    },
    mergeReadinessGuard: {
      enabled:
        typeof mergeReadinessSource.enabled === "boolean"
          ? mergeReadinessSource.enabled
          : DEFAULT_GATEWAY_CONFIG.mergeReadinessGuard.enabled,
      requireDeleteBranch:
        typeof mergeReadinessSource.requireDeleteBranch === "boolean"
          ? mergeReadinessSource.requireDeleteBranch
          : DEFAULT_GATEWAY_CONFIG.mergeReadinessGuard.requireDeleteBranch,
      requireStrategy:
        typeof mergeReadinessSource.requireStrategy === "boolean"
          ? mergeReadinessSource.requireStrategy
          : DEFAULT_GATEWAY_CONFIG.mergeReadinessGuard.requireStrategy,
      disallowAdminBypass:
        typeof mergeReadinessSource.disallowAdminBypass === "boolean"
          ? mergeReadinessSource.disallowAdminBypass
          : DEFAULT_GATEWAY_CONFIG.mergeReadinessGuard.disallowAdminBypass,
    },
    ghChecksMergeGuard: {
      enabled:
        typeof ghChecksMergeSource.enabled === "boolean"
          ? ghChecksMergeSource.enabled
          : DEFAULT_GATEWAY_CONFIG.ghChecksMergeGuard.enabled,
      blockDraft:
        typeof ghChecksMergeSource.blockDraft === "boolean"
          ? ghChecksMergeSource.blockDraft
          : DEFAULT_GATEWAY_CONFIG.ghChecksMergeGuard.blockDraft,
      requireApprovedReview:
        typeof ghChecksMergeSource.requireApprovedReview === "boolean"
          ? ghChecksMergeSource.requireApprovedReview
          : DEFAULT_GATEWAY_CONFIG.ghChecksMergeGuard.requireApprovedReview,
      requirePassingChecks:
        typeof ghChecksMergeSource.requirePassingChecks === "boolean"
          ? ghChecksMergeSource.requirePassingChecks
          : DEFAULT_GATEWAY_CONFIG.ghChecksMergeGuard.requirePassingChecks,
      blockedMergeStates:
        ghChecksMergeSource.blockedMergeStates === undefined
          ? DEFAULT_GATEWAY_CONFIG.ghChecksMergeGuard.blockedMergeStates
          : stringList(ghChecksMergeSource.blockedMergeStates),
      failOpenOnError:
        typeof ghChecksMergeSource.failOpenOnError === "boolean"
          ? ghChecksMergeSource.failOpenOnError
          : DEFAULT_GATEWAY_CONFIG.ghChecksMergeGuard.failOpenOnError,
    },
    postMergeSyncGuard: {
      enabled:
        typeof postMergeSyncSource.enabled === "boolean"
          ? postMergeSyncSource.enabled
          : DEFAULT_GATEWAY_CONFIG.postMergeSyncGuard.enabled,
      requireDeleteBranch:
        typeof postMergeSyncSource.requireDeleteBranch === "boolean"
          ? postMergeSyncSource.requireDeleteBranch
          : DEFAULT_GATEWAY_CONFIG.postMergeSyncGuard.requireDeleteBranch,
      enforceMainSyncInline:
        typeof postMergeSyncSource.enforceMainSyncInline === "boolean"
          ? postMergeSyncSource.enforceMainSyncInline
          : DEFAULT_GATEWAY_CONFIG.postMergeSyncGuard.enforceMainSyncInline,
      reminderCommands:
        postMergeSyncSource.reminderCommands === undefined
          ? DEFAULT_GATEWAY_CONFIG.postMergeSyncGuard.reminderCommands
          : stringList(postMergeSyncSource.reminderCommands),
    },
    parallelWriterConflictGuard: {
      enabled:
        typeof parallelWriterConflictSource.enabled === "boolean"
          ? parallelWriterConflictSource.enabled
          : DEFAULT_GATEWAY_CONFIG.parallelWriterConflictGuard.enabled,
      maxConcurrentWriters: positiveInt(
        parallelWriterConflictSource.maxConcurrentWriters,
        DEFAULT_GATEWAY_CONFIG.parallelWriterConflictGuard.maxConcurrentWriters,
      ),
      writerCountEnvKeys:
        parallelWriterConflictSource.writerCountEnvKeys === undefined
          ? DEFAULT_GATEWAY_CONFIG.parallelWriterConflictGuard.writerCountEnvKeys
          : stringList(parallelWriterConflictSource.writerCountEnvKeys),
      reservationPathsEnvKeys:
        parallelWriterConflictSource.reservationPathsEnvKeys === undefined
          ? DEFAULT_GATEWAY_CONFIG.parallelWriterConflictGuard.reservationPathsEnvKeys
          : stringList(parallelWriterConflictSource.reservationPathsEnvKeys),
      activeReservationPathsEnvKeys:
        parallelWriterConflictSource.activeReservationPathsEnvKeys === undefined
          ? DEFAULT_GATEWAY_CONFIG.parallelWriterConflictGuard.activeReservationPathsEnvKeys
          : stringList(parallelWriterConflictSource.activeReservationPathsEnvKeys),
      enforceReservationCoverage:
        typeof parallelWriterConflictSource.enforceReservationCoverage === "boolean"
          ? parallelWriterConflictSource.enforceReservationCoverage
          : DEFAULT_GATEWAY_CONFIG.parallelWriterConflictGuard.enforceReservationCoverage,
    },
    secretCommitGuard: {
      enabled:
        typeof secretCommitSource.enabled === "boolean"
          ? secretCommitSource.enabled
          : DEFAULT_GATEWAY_CONFIG.secretCommitGuard.enabled,
      patterns:
        secretCommitSource.patterns === undefined
          ? DEFAULT_GATEWAY_CONFIG.secretCommitGuard.patterns
          : stringList(secretCommitSource.patterns),
    },
    quality: {
      profile: qualityProfile,
      ts: {
        lint: typeof tsSource.lint === "boolean" ? tsSource.lint : true,
        typecheck: typeof tsSource.typecheck === "boolean" ? tsSource.typecheck : true,
        tests: typeof tsSource.tests === "boolean" ? tsSource.tests : false,
      },
      py: {
        selftest: typeof pySource.selftest === "boolean" ? pySource.selftest : true,
      },
    },
  }
}
