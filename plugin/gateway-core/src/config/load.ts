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
  const sessionRecoverySource =
    source.sessionRecovery && typeof source.sessionRecovery === "object"
      ? (source.sessionRecovery as Record<string, unknown>)
      : {}
  const delegateTaskRetrySource =
    source.delegateTaskRetry && typeof source.delegateTaskRetry === "object"
      ? (source.delegateTaskRetry as Record<string, unknown>)
      : {}
  const stopGuardSource =
    source.stopContinuationGuard && typeof source.stopContinuationGuard === "object"
      ? (source.stopContinuationGuard as Record<string, unknown>)
      : {}
  const keywordDetectorSource =
    source.keywordDetector && typeof source.keywordDetector === "object"
      ? (source.keywordDetector as Record<string, unknown>)
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
  const writeExistingGuardSource =
    source.writeExistingFileGuard && typeof source.writeExistingFileGuard === "object"
      ? (source.writeExistingFileGuard as Record<string, unknown>)
      : {}
  const subagentQuestionSource =
    source.subagentQuestionBlocker && typeof source.subagentQuestionBlocker === "object"
      ? (source.subagentQuestionBlocker as Record<string, unknown>)
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
    },
    directoryReadmeInjector: {
      enabled:
        typeof directoryReadmeSource.enabled === "boolean"
          ? directoryReadmeSource.enabled
          : DEFAULT_GATEWAY_CONFIG.directoryReadmeInjector.enabled,
    },
    writeExistingFileGuard: {
      enabled:
        typeof writeExistingGuardSource.enabled === "boolean"
          ? writeExistingGuardSource.enabled
          : DEFAULT_GATEWAY_CONFIG.writeExistingFileGuard.enabled,
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
