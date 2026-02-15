import { DEFAULT_GATEWAY_CONFIG } from "./schema.js";
// Coerces unknown value into a normalized string array.
function stringList(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter((item) => typeof item === "string")
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
}
// Coerces unknown value into a safe non-negative integer fallback.
function nonNegativeInt(value, fallback) {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 0) {
        return fallback;
    }
    return parsed;
}
// Coerces unknown value into bounded float fallback.
function boundedFloat(value, min, max, fallback) {
    const parsed = Number.parseFloat(String(value ?? ""));
    if (!Number.isFinite(parsed)) {
        return fallback;
    }
    if (parsed < min || parsed > max) {
        return fallback;
    }
    return parsed;
}
// Loads and normalizes gateway plugin config from unknown input.
export function loadGatewayConfig(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const hooksSource = source.hooks && typeof source.hooks === "object"
        ? source.hooks
        : {};
    const autopilotSource = source.autopilotLoop && typeof source.autopilotLoop === "object"
        ? source.autopilotLoop
        : {};
    const qualitySource = source.quality && typeof source.quality === "object"
        ? source.quality
        : {};
    const truncatorSource = source.toolOutputTruncator && typeof source.toolOutputTruncator === "object"
        ? source.toolOutputTruncator
        : {};
    const contextWindowSource = source.contextWindowMonitor && typeof source.contextWindowMonitor === "object"
        ? source.contextWindowMonitor
        : {};
    const preemptiveCompactionSource = source.preemptiveCompaction && typeof source.preemptiveCompaction === "object"
        ? source.preemptiveCompaction
        : {};
    const sessionRecoverySource = source.sessionRecovery && typeof source.sessionRecovery === "object"
        ? source.sessionRecovery
        : {};
    const delegateTaskRetrySource = source.delegateTaskRetry && typeof source.delegateTaskRetry === "object"
        ? source.delegateTaskRetry
        : {};
    const stopGuardSource = source.stopContinuationGuard && typeof source.stopContinuationGuard === "object"
        ? source.stopContinuationGuard
        : {};
    const keywordDetectorSource = source.keywordDetector && typeof source.keywordDetector === "object"
        ? source.keywordDetector
        : {};
    const autoSlashSource = source.autoSlashCommand && typeof source.autoSlashCommand === "object"
        ? source.autoSlashCommand
        : {};
    const rulesInjectorSource = source.rulesInjector && typeof source.rulesInjector === "object"
        ? source.rulesInjector
        : {};
    const directoryAgentsSource = source.directoryAgentsInjector && typeof source.directoryAgentsInjector === "object"
        ? source.directoryAgentsInjector
        : {};
    const directoryReadmeSource = source.directoryReadmeInjector && typeof source.directoryReadmeInjector === "object"
        ? source.directoryReadmeInjector
        : {};
    const writeExistingGuardSource = source.writeExistingFileGuard && typeof source.writeExistingFileGuard === "object"
        ? source.writeExistingFileGuard
        : {};
    const subagentQuestionSource = source.subagentQuestionBlocker && typeof source.subagentQuestionBlocker === "object"
        ? source.subagentQuestionBlocker
        : {};
    const tasksTodowriteSource = source.tasksTodowriteDisabler && typeof source.tasksTodowriteDisabler === "object"
        ? source.tasksTodowriteDisabler
        : {};
    const taskResumeInfoSource = source.taskResumeInfo && typeof source.taskResumeInfo === "object"
        ? source.taskResumeInfo
        : {};
    const emptyTaskResponseSource = source.emptyTaskResponseDetector && typeof source.emptyTaskResponseDetector === "object"
        ? source.emptyTaskResponseDetector
        : {};
    const commentCheckerSource = source.commentChecker && typeof source.commentChecker === "object"
        ? source.commentChecker
        : {};
    const agentUserReminderSource = source.agentUserReminder && typeof source.agentUserReminder === "object"
        ? source.agentUserReminder
        : {};
    const unstableBabysitterSource = source.unstableAgentBabysitter && typeof source.unstableAgentBabysitter === "object"
        ? source.unstableAgentBabysitter
        : {};
    const questionLabelSource = source.questionLabelTruncator && typeof source.questionLabelTruncator === "object"
        ? source.questionLabelTruncator
        : {};
    const dangerousCommandSource = source.dangerousCommandGuard && typeof source.dangerousCommandGuard === "object"
        ? source.dangerousCommandGuard
        : {};
    const secretLeakSource = source.secretLeakGuard && typeof source.secretLeakGuard === "object"
        ? source.secretLeakGuard
        : {};
    const tsSource = qualitySource.ts && typeof qualitySource.ts === "object"
        ? qualitySource.ts
        : {};
    const pySource = qualitySource.py && typeof qualitySource.py === "object"
        ? qualitySource.py
        : {};
    const completionMode = autopilotSource.completionMode === "objective" ? "objective" : "promise";
    const qualityProfile = qualitySource.profile === "off" || qualitySource.profile === "strict"
        ? qualitySource.profile
        : "fast";
    const truncatorTools = truncatorSource.tools === undefined
        ? DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.tools
        : stringList(truncatorSource.tools);
    return {
        hooks: {
            enabled: typeof hooksSource.enabled === "boolean"
                ? hooksSource.enabled
                : DEFAULT_GATEWAY_CONFIG.hooks.enabled,
            disabled: stringList(hooksSource.disabled),
            order: stringList(hooksSource.order),
        },
        autopilotLoop: {
            enabled: typeof autopilotSource.enabled === "boolean"
                ? autopilotSource.enabled
                : DEFAULT_GATEWAY_CONFIG.autopilotLoop.enabled,
            maxIterations: nonNegativeInt(autopilotSource.maxIterations, DEFAULT_GATEWAY_CONFIG.autopilotLoop.maxIterations),
            orphanMaxAgeHours: nonNegativeInt(autopilotSource.orphanMaxAgeHours, DEFAULT_GATEWAY_CONFIG.autopilotLoop.orphanMaxAgeHours),
            completionMode,
            completionPromise: typeof autopilotSource.completionPromise === "string" &&
                autopilotSource.completionPromise.trim().length > 0
                ? autopilotSource.completionPromise.trim()
                : DEFAULT_GATEWAY_CONFIG.autopilotLoop.completionPromise,
        },
        toolOutputTruncator: {
            enabled: typeof truncatorSource.enabled === "boolean"
                ? truncatorSource.enabled
                : DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.enabled,
            maxChars: nonNegativeInt(truncatorSource.maxChars, DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.maxChars),
            maxLines: nonNegativeInt(truncatorSource.maxLines, DEFAULT_GATEWAY_CONFIG.toolOutputTruncator.maxLines),
            tools: truncatorTools,
        },
        contextWindowMonitor: {
            enabled: typeof contextWindowSource.enabled === "boolean"
                ? contextWindowSource.enabled
                : DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.enabled,
            warningThreshold: boundedFloat(contextWindowSource.warningThreshold, 0.5, 0.95, DEFAULT_GATEWAY_CONFIG.contextWindowMonitor.warningThreshold),
        },
        preemptiveCompaction: {
            enabled: typeof preemptiveCompactionSource.enabled === "boolean"
                ? preemptiveCompactionSource.enabled
                : DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.enabled,
            warningThreshold: boundedFloat(preemptiveCompactionSource.warningThreshold, 0.6, 0.95, DEFAULT_GATEWAY_CONFIG.preemptiveCompaction.warningThreshold),
        },
        sessionRecovery: {
            enabled: typeof sessionRecoverySource.enabled === "boolean"
                ? sessionRecoverySource.enabled
                : DEFAULT_GATEWAY_CONFIG.sessionRecovery.enabled,
            autoResume: typeof sessionRecoverySource.autoResume === "boolean"
                ? sessionRecoverySource.autoResume
                : DEFAULT_GATEWAY_CONFIG.sessionRecovery.autoResume,
        },
        delegateTaskRetry: {
            enabled: typeof delegateTaskRetrySource.enabled === "boolean"
                ? delegateTaskRetrySource.enabled
                : DEFAULT_GATEWAY_CONFIG.delegateTaskRetry.enabled,
        },
        stopContinuationGuard: {
            enabled: typeof stopGuardSource.enabled === "boolean"
                ? stopGuardSource.enabled
                : DEFAULT_GATEWAY_CONFIG.stopContinuationGuard.enabled,
        },
        keywordDetector: {
            enabled: typeof keywordDetectorSource.enabled === "boolean"
                ? keywordDetectorSource.enabled
                : DEFAULT_GATEWAY_CONFIG.keywordDetector.enabled,
        },
        autoSlashCommand: {
            enabled: typeof autoSlashSource.enabled === "boolean"
                ? autoSlashSource.enabled
                : DEFAULT_GATEWAY_CONFIG.autoSlashCommand.enabled,
        },
        rulesInjector: {
            enabled: typeof rulesInjectorSource.enabled === "boolean"
                ? rulesInjectorSource.enabled
                : DEFAULT_GATEWAY_CONFIG.rulesInjector.enabled,
        },
        directoryAgentsInjector: {
            enabled: typeof directoryAgentsSource.enabled === "boolean"
                ? directoryAgentsSource.enabled
                : DEFAULT_GATEWAY_CONFIG.directoryAgentsInjector.enabled,
        },
        directoryReadmeInjector: {
            enabled: typeof directoryReadmeSource.enabled === "boolean"
                ? directoryReadmeSource.enabled
                : DEFAULT_GATEWAY_CONFIG.directoryReadmeInjector.enabled,
        },
        writeExistingFileGuard: {
            enabled: typeof writeExistingGuardSource.enabled === "boolean"
                ? writeExistingGuardSource.enabled
                : DEFAULT_GATEWAY_CONFIG.writeExistingFileGuard.enabled,
        },
        subagentQuestionBlocker: {
            enabled: typeof subagentQuestionSource.enabled === "boolean"
                ? subagentQuestionSource.enabled
                : DEFAULT_GATEWAY_CONFIG.subagentQuestionBlocker.enabled,
            sessionPatterns: subagentQuestionSource.sessionPatterns === undefined
                ? DEFAULT_GATEWAY_CONFIG.subagentQuestionBlocker.sessionPatterns
                : stringList(subagentQuestionSource.sessionPatterns),
        },
        tasksTodowriteDisabler: {
            enabled: typeof tasksTodowriteSource.enabled === "boolean"
                ? tasksTodowriteSource.enabled
                : DEFAULT_GATEWAY_CONFIG.tasksTodowriteDisabler.enabled,
        },
        taskResumeInfo: {
            enabled: typeof taskResumeInfoSource.enabled === "boolean"
                ? taskResumeInfoSource.enabled
                : DEFAULT_GATEWAY_CONFIG.taskResumeInfo.enabled,
        },
        emptyTaskResponseDetector: {
            enabled: typeof emptyTaskResponseSource.enabled === "boolean"
                ? emptyTaskResponseSource.enabled
                : DEFAULT_GATEWAY_CONFIG.emptyTaskResponseDetector.enabled,
        },
        commentChecker: {
            enabled: typeof commentCheckerSource.enabled === "boolean"
                ? commentCheckerSource.enabled
                : DEFAULT_GATEWAY_CONFIG.commentChecker.enabled,
        },
        agentUserReminder: {
            enabled: typeof agentUserReminderSource.enabled === "boolean"
                ? agentUserReminderSource.enabled
                : DEFAULT_GATEWAY_CONFIG.agentUserReminder.enabled,
        },
        unstableAgentBabysitter: {
            enabled: typeof unstableBabysitterSource.enabled === "boolean"
                ? unstableBabysitterSource.enabled
                : DEFAULT_GATEWAY_CONFIG.unstableAgentBabysitter.enabled,
            riskyPatterns: unstableBabysitterSource.riskyPatterns === undefined
                ? DEFAULT_GATEWAY_CONFIG.unstableAgentBabysitter.riskyPatterns
                : stringList(unstableBabysitterSource.riskyPatterns),
        },
        questionLabelTruncator: {
            enabled: typeof questionLabelSource.enabled === "boolean"
                ? questionLabelSource.enabled
                : DEFAULT_GATEWAY_CONFIG.questionLabelTruncator.enabled,
            maxLength: nonNegativeInt(questionLabelSource.maxLength, DEFAULT_GATEWAY_CONFIG.questionLabelTruncator.maxLength),
        },
        dangerousCommandGuard: {
            enabled: typeof dangerousCommandSource.enabled === "boolean"
                ? dangerousCommandSource.enabled
                : DEFAULT_GATEWAY_CONFIG.dangerousCommandGuard.enabled,
            blockedPatterns: dangerousCommandSource.blockedPatterns === undefined
                ? DEFAULT_GATEWAY_CONFIG.dangerousCommandGuard.blockedPatterns
                : stringList(dangerousCommandSource.blockedPatterns),
        },
        secretLeakGuard: {
            enabled: typeof secretLeakSource.enabled === "boolean"
                ? secretLeakSource.enabled
                : DEFAULT_GATEWAY_CONFIG.secretLeakGuard.enabled,
            redactionToken: typeof secretLeakSource.redactionToken === "string" && secretLeakSource.redactionToken.trim().length > 0
                ? secretLeakSource.redactionToken
                : DEFAULT_GATEWAY_CONFIG.secretLeakGuard.redactionToken,
            patterns: secretLeakSource.patterns === undefined
                ? DEFAULT_GATEWAY_CONFIG.secretLeakGuard.patterns
                : stringList(secretLeakSource.patterns),
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
    };
}
