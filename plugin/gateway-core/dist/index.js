import { loadGatewayConfig, loadGatewayConfigSource } from "./config/load.js";
import { writeGatewayEventAudit } from "./audit/event-audit.js";
import { createAutopilotLoopHook } from "./hooks/autopilot-loop/index.js";
import { createAutoSlashCommandHook } from "./hooks/auto-slash-command/index.js";
import { createAdaptiveDelegationPolicyHook } from "./hooks/adaptive-delegation-policy/index.js";
import { createAgentContextShaperHook } from "./hooks/agent-context-shaper/index.js";
import { createAgentDiscoverabilityInjectorHook } from "./hooks/agent-discoverability-injector/index.js";
import { createAgentDeniedToolEnforcerHook } from "./hooks/agent-denied-tool-enforcer/index.js";
import { createAgentModelResolverHook } from "./hooks/agent-model-resolver/index.js";
import { createAgentUserReminderHook } from "./hooks/agent-user-reminder/index.js";
import { createBranchFreshnessGuardHook } from "./hooks/branch-freshness-guard/index.js";
import { createCommentCheckerHook } from "./hooks/comment-checker/index.js";
import { createCompactionContextInjectorHook } from "./hooks/compaction-context-injector/index.js";
import { createContinuationHook } from "./hooks/continuation/index.js";
import { createContextWindowMonitorHook } from "./hooks/context-window-monitor/index.js";
import { createDelegateTaskRetryHook } from "./hooks/delegate-task-retry/index.js";
import { createDelegationConcurrencyGuardHook } from "./hooks/delegation-concurrency-guard/index.js";
import { createDelegationDecisionAuditHook } from "./hooks/delegation-decision-audit/index.js";
import { createDelegationFallbackOrchestratorHook } from "./hooks/delegation-fallback-orchestrator/index.js";
import { createDelegationOutcomeLearnerHook } from "./hooks/delegation-outcome-learner/index.js";
import { createDependencyRiskGuardHook } from "./hooks/dependency-risk-guard/index.js";
import { createDocsDriftGuardHook } from "./hooks/docs-drift-guard/index.js";
import { createDoneProofEnforcerHook } from "./hooks/done-proof-enforcer/index.js";
import { createDangerousCommandGuardHook } from "./hooks/dangerous-command-guard/index.js";
import { createEmptyTaskResponseDetectorHook } from "./hooks/empty-task-response-detector/index.js";
import { createEditErrorRecoveryHook } from "./hooks/edit-error-recovery/index.js";
import { createJsonErrorRecoveryHook } from "./hooks/json-error-recovery/index.js";
import { createProviderTokenLimitRecoveryHook } from "./hooks/provider-token-limit-recovery/index.js";
import { createHashlineReadEnhancerHook } from "./hooks/hashline-read-enhancer/index.js";
import { createMaxStepRecoveryHook } from "./hooks/max-step-recovery/index.js";
import { createModeTransitionReminderHook } from "./hooks/mode-transition-reminder/index.js";
import { createNotifyEventsHook } from "./hooks/notify-events/index.js";
import { createTodoreadCadenceReminderHook } from "./hooks/todoread-cadence-reminder/index.js";
import { createProviderRetryBackoffGuidanceHook } from "./hooks/provider-retry-backoff-guidance/index.js";
import { createProviderErrorClassifierHook } from "./hooks/provider-error-classifier/index.js";
import { createCodexHeaderInjectorHook } from "./hooks/codex-header-injector/index.js";
import { createPlanHandoffReminderHook } from "./hooks/plan-handoff-reminder/index.js";
import { createGhChecksMergeGuardHook } from "./hooks/gh-checks-merge-guard/index.js";
import { createGlobalProcessPressureHook } from "./hooks/global-process-pressure/index.js";
import { createLongTurnWatchdogHook } from "./hooks/long-turn-watchdog/index.js";
import { createPressureEscalationGuardHook } from "./hooks/pressure-escalation-guard/index.js";
import { createProviderModelBudgetEnforcerHook } from "./hooks/provider-model-budget-enforcer/index.js";
import { createHookTestParityGuardHook } from "./hooks/hook-test-parity-guard/index.js";
import { createHookSemanticBridgeHook } from "./hooks/hook-semantic-bridge/index.js";
import { createDirectoryAgentsInjectorHook } from "./hooks/directory-agents-injector/index.js";
import { createDirectoryReadmeInjectorHook } from "./hooks/directory-readme-injector/index.js";
import { createDirectWorkWarningHook } from "./hooks/direct-work-warning/index.js";
import { createKeywordDetectorHook } from "./hooks/keyword-detector/index.js";
import { createMergeReadinessGuardHook } from "./hooks/merge-readiness-guard/index.js";
import { createNoninteractiveShellGuardHook } from "./hooks/noninteractive-shell-guard/index.js";
import { createParallelOpportunityDetectorHook } from "./hooks/parallel-opportunity-detector/index.js";
import { createParallelWriterConflictGuardHook } from "./hooks/parallel-writer-conflict-guard/index.js";
import { createPostMergeSyncGuardHook } from "./hooks/post-merge-sync-guard/index.js";
import { createPrimaryWorktreeGuardHook } from "./hooks/primary-worktree-guard/index.js";
import { createPrBodyEvidenceGuardHook } from "./hooks/pr-body-evidence-guard/index.js";
import { createPreemptiveCompactionHook } from "./hooks/preemptive-compaction/index.js";
import { createPrReadinessGuardHook } from "./hooks/pr-readiness-guard/index.js";
import { createQuestionLabelTruncatorHook } from "./hooks/question-label-truncator/index.js";
import { createReadBudgetOptimizerHook } from "./hooks/read-budget-optimizer/index.js";
import { createRulesInjectorHook } from "./hooks/rules-injector/index.js";
import { createRetryBudgetGuardHook } from "./hooks/retry-budget-guard/index.js";
import { createScopeDriftGuardHook } from "./hooks/scope-drift-guard/index.js";
import { createSecretCommitGuardHook } from "./hooks/secret-commit-guard/index.js";
import { createSecretLeakGuardHook } from "./hooks/secret-leak-guard/index.js";
import { createSemanticOutputSummarizerHook } from "./hooks/semantic-output-summarizer/index.js";
import { createSafetyHook } from "./hooks/safety/index.js";
import { createSessionRecoveryHook } from "./hooks/session-recovery/index.js";
import { createSessionRuntimeSystemContextHook } from "./hooks/session-runtime-system-context/index.js";
import { createStopContinuationGuardHook } from "./hooks/stop-continuation-guard/index.js";
import { createSubagentQuestionBlockerHook } from "./hooks/subagent-question-blocker/index.js";
import { createSubagentTelemetryTimelineHook } from "./hooks/subagent-telemetry-timeline/index.js";
import { createTasksTodowriteDisablerHook } from "./hooks/tasks-todowrite-disabler/index.js";
import { createTaskResumeInfoHook } from "./hooks/task-resume-info/index.js";
import { createTodoContinuationEnforcerHook } from "./hooks/todo-continuation-enforcer/index.js";
import { createCompactionTodoPreserverHook } from "./hooks/compaction-todo-preserver/index.js";
import { createSubagentLifecycleSupervisorHook } from "./hooks/subagent-lifecycle-supervisor/index.js";
import { createThinkModeHook } from "./hooks/think-mode/index.js";
import { createThinkingBlockValidatorHook } from "./hooks/thinking-block-validator/index.js";
import { createToolOutputTruncatorHook } from "./hooks/tool-output-truncator/index.js";
import { createUnstableAgentBabysitterHook } from "./hooks/unstable-agent-babysitter/index.js";
import { createValidationEvidenceLedgerHook } from "./hooks/validation-evidence-ledger/index.js";
import { createMistakeLedgerHook } from "./hooks/mistake-ledger/index.js";
import { createAdaptiveValidationSchedulerHook } from "./hooks/adaptive-validation-scheduler/index.js";
import { createAgentReservationGuardHook } from "./hooks/agent-reservation-guard/index.js";
import { createLlmDecisionRuntime, resolveLlmDecisionRuntimeConfigForHook, } from "./hooks/shared/llm-decision-runtime.js";
import { safeCreateHook } from "./hooks/shared/safe-create-hook.js";
import { dispatchGatewayHookEvent } from "./hooks/shared/hook-dispatch.js";
import { isCriticalGatewayHookId } from "./hooks/shared/hook-failure.js";
import { createWorkflowConformanceGuardHook } from "./hooks/workflow-conformance-guard/index.js";
import { createWriteExistingFileGuardHook } from "./hooks/write-existing-file-guard/index.js";
import { createStaleLoopExpiryGuardHook } from "./hooks/stale-loop-expiry-guard/index.js";
import { contextCollector } from "./hooks/context-injector/collector.js";
import { createContextInjectorHook } from "./hooks/context-injector/index.js";
import { resolveHookOrder } from "./hooks/registry.js";
const DISPATCH_NOISY_EVENTS = new Set([
    "message.part.delta",
    "message.part.updated",
    "message.updated",
    "session.updated",
    "session.status",
    "session.diff",
    "experimental.chat.messages.transform",
]);
const DISPATCH_NOISY_REASON_CODES = new Set([
    "event_dispatch",
    "chat_messages_transform_dispatch",
]);
const LLM_DECISION_CHILD_ENV = "MY_OPENCODE_LLM_DECISION_CHILD";
export const GATEWAY_LLM_DECISION_RUNTIME_BINDINGS = {
    agentDeniedToolEnforcer: "agent-denied-tool-enforcer",
    agentModelResolver: "agent-model-resolver",
    delegationFallbackOrchestrator: "delegation-fallback-orchestrator",
    validationEvidenceLedger: "validation-evidence-ledger",
    mistakeLedger: "mistake-ledger",
    autoSlashCommand: "auto-slash-command",
    taskResumeInfo: "task-resume-info",
    providerErrorClassifier: "provider-error-classifier",
    todoContinuationEnforcer: "todo-continuation-enforcer",
    doneProofEnforcer: "done-proof-enforcer",
    prBodyEvidenceGuard: "pr-body-evidence-guard",
};
function isLlmDecisionChildProcess() {
    return process.env[LLM_DECISION_CHILD_ENV] === "1";
}
function dispatchSampleRate() {
    const parsed = Number.parseInt(String(process.env.MY_OPENCODE_GATEWAY_DISPATCH_SAMPLE_RATE ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
        return 20;
    }
    return parsed;
}
// Creates ordered hook list using gateway config and default hooks.
function configuredHooks(ctx) {
    const directory = typeof ctx.directory === "string" && ctx.directory.trim()
        ? ctx.directory
        : process.cwd();
    const cfg = loadGatewayConfig(loadGatewayConfigSource(directory, ctx.config));
    if (isLlmDecisionChildProcess()) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "state",
            reason_code: "child_mode_minimal_hooks_enabled",
            child_mode: "llm_decision",
        });
        return [];
    }
    const llmDecisionRuntimeForHook = (hookId) => (ctx.createLlmDecisionRuntime ?? createLlmDecisionRuntime)({
        directory,
        config: resolveLlmDecisionRuntimeConfigForHook(cfg.llmDecisionRuntime, hookId),
    });
    const safeHook = (hookId, factory) => safeCreateHook({
        directory,
        hookId,
        factory,
        critical: isCriticalGatewayHookId(hookId),
    });
    const stopGuard = safeHook("stop-continuation-guard", () => createStopContinuationGuardHook({
        directory,
        enabled: cfg.stopContinuationGuard.enabled,
    })) ?? {
        id: "stop-continuation-guard",
        priority: 295,
        isStopped() {
            return false;
        },
        forceStop() { },
        async event() { },
    };
    const keywordDetector = safeHook("keyword-detector", () => createKeywordDetectorHook({
        directory,
        enabled: cfg.keywordDetector.enabled,
    })) ?? {
        id: "keyword-detector",
        priority: 296,
        modeForSession() {
            return null;
        },
        async event() { },
    };
    const hooks = [
        safeHook("autopilot-loop", () => createAutopilotLoopHook({
            directory,
            defaults: {
                enabled: cfg.autopilotLoop.enabled,
                maxIterations: cfg.autopilotLoop.maxIterations,
                completionMode: cfg.autopilotLoop.completionMode,
                completionPromise: cfg.autopilotLoop.completionPromise,
            },
            collector: contextCollector,
        })),
        safeHook("continuation", () => createContinuationHook({
            directory,
            client: ctx.client,
            stopGuard,
            keywordDetector,
            bootstrapFromRuntime: cfg.autopilotLoop.bootstrapFromRuntimeOnIdle,
            maxIgnoredCompletionCycles: cfg.autopilotLoop.maxIgnoredCompletionCycles,
        })),
        safeHook("safety", () => createSafetyHook({
            directory,
            orphanMaxAgeHours: cfg.autopilotLoop.orphanMaxAgeHours,
        })),
        safeHook("tool-output-truncator", () => createToolOutputTruncatorHook({
            directory,
            enabled: cfg.toolOutputTruncator.enabled,
            maxChars: cfg.toolOutputTruncator.maxChars,
            maxLines: cfg.toolOutputTruncator.maxLines,
            tools: cfg.toolOutputTruncator.tools,
        })),
        safeHook("semantic-output-summarizer", () => createSemanticOutputSummarizerHook({
            directory,
            enabled: cfg.semanticOutputSummarizer.enabled,
            minChars: cfg.semanticOutputSummarizer.minChars,
            minLines: cfg.semanticOutputSummarizer.minLines,
            maxSummaryLines: cfg.semanticOutputSummarizer.maxSummaryLines,
        })),
        safeHook("context-window-monitor", () => createContextWindowMonitorHook({
            directory,
            client: ctx.client,
            enabled: cfg.contextWindowMonitor.enabled,
            warningThreshold: cfg.contextWindowMonitor.warningThreshold,
            reminderCooldownToolCalls: cfg.contextWindowMonitor.reminderCooldownToolCalls,
            minTokenDeltaForReminder: cfg.contextWindowMonitor.minTokenDeltaForReminder,
            defaultContextLimitTokens: cfg.contextWindowMonitor.defaultContextLimitTokens,
            guardMarkerMode: cfg.contextWindowMonitor.guardMarkerMode,
            guardVerbosity: cfg.contextWindowMonitor.guardVerbosity,
            maxSessionStateEntries: cfg.contextWindowMonitor.maxSessionStateEntries,
        })),
        safeHook("preemptive-compaction", () => createPreemptiveCompactionHook({
            directory,
            client: ctx.client,
            enabled: cfg.preemptiveCompaction.enabled,
            warningThreshold: cfg.preemptiveCompaction.warningThreshold,
            compactionCooldownToolCalls: cfg.preemptiveCompaction.compactionCooldownToolCalls,
            minTokenDeltaForCompaction: cfg.preemptiveCompaction.minTokenDeltaForCompaction,
            defaultContextLimitTokens: cfg.preemptiveCompaction.defaultContextLimitTokens,
            guardMarkerMode: cfg.preemptiveCompaction.guardMarkerMode,
            guardVerbosity: cfg.preemptiveCompaction.guardVerbosity,
            maxSessionStateEntries: cfg.preemptiveCompaction.maxSessionStateEntries,
        })),
        safeHook("compaction-context-injector", () => createCompactionContextInjectorHook({
            directory,
            enabled: cfg.compactionContextInjector.enabled,
        })),
        safeHook("global-process-pressure", () => createGlobalProcessPressureHook({
            directory,
            stopGuard,
            enabled: cfg.globalProcessPressure.enabled,
            checkCooldownToolCalls: cfg.globalProcessPressure.checkCooldownToolCalls,
            reminderCooldownToolCalls: cfg.globalProcessPressure.reminderCooldownToolCalls,
            criticalReminderCooldownToolCalls: cfg.globalProcessPressure.criticalReminderCooldownToolCalls,
            criticalEscalationWindowToolCalls: cfg.globalProcessPressure.criticalEscalationWindowToolCalls,
            criticalPauseAfterEvents: cfg.globalProcessPressure.criticalPauseAfterEvents,
            criticalEscalationAfterEvents: cfg.globalProcessPressure.criticalEscalationAfterEvents,
            warningContinueSessions: cfg.globalProcessPressure.warningContinueSessions,
            warningOpencodeProcesses: cfg.globalProcessPressure.warningOpencodeProcesses,
            warningMaxRssMb: cfg.globalProcessPressure.warningMaxRssMb,
            criticalMaxRssMb: cfg.globalProcessPressure.criticalMaxRssMb,
            autoPauseOnCritical: cfg.globalProcessPressure.autoPauseOnCritical,
            notifyOnCritical: cfg.globalProcessPressure.notifyOnCritical,
            guardMarkerMode: cfg.globalProcessPressure.guardMarkerMode,
            guardVerbosity: cfg.globalProcessPressure.guardVerbosity,
            maxSessionStateEntries: cfg.globalProcessPressure.maxSessionStateEntries,
            selfSeverityOperator: cfg.globalProcessPressure.selfSeverityOperator,
            selfHighCpuPct: cfg.globalProcessPressure.selfHighCpuPct,
            selfHighRssMb: cfg.globalProcessPressure.selfHighRssMb,
            selfHighElapsed: cfg.globalProcessPressure.selfHighElapsed,
            selfHighLabel: cfg.globalProcessPressure.selfHighLabel,
            selfLowLabel: cfg.globalProcessPressure.selfLowLabel,
            selfAppendMarker: cfg.globalProcessPressure.selfAppendMarker,
        })),
        safeHook("long-turn-watchdog", () => createLongTurnWatchdogHook({
            directory,
            enabled: cfg.longTurnWatchdog.enabled,
            warningThresholdMs: cfg.longTurnWatchdog.warningThresholdMs,
            reminderCooldownMs: cfg.longTurnWatchdog.reminderCooldownMs,
            maxSessionStateEntries: cfg.longTurnWatchdog.maxSessionStateEntries,
            prefix: cfg.longTurnWatchdog.prefix,
        })),
        safeHook("notify-events", () => createNotifyEventsHook({
            directory,
            enabled: cfg.notifyEvents.enabled,
            cooldownMs: cfg.notifyEvents.cooldownMs,
            style: cfg.notifyEvents.style,
        })),
        safeHook("pressure-escalation-guard", () => createPressureEscalationGuardHook({
            directory,
            enabled: cfg.pressureEscalationGuard.enabled,
            maxContinueBeforeBlock: cfg.pressureEscalationGuard.maxContinueBeforeBlock,
            blockedSubagentTypes: cfg.pressureEscalationGuard.blockedSubagentTypes,
            allowPromptPatterns: cfg.pressureEscalationGuard.allowPromptPatterns,
        })),
        safeHook("provider-model-budget-enforcer", () => createProviderModelBudgetEnforcerHook({
            directory,
            enabled: cfg.providerModelBudgetEnforcer.enabled,
            windowMs: cfg.providerModelBudgetEnforcer.windowMs,
            maxDelegationsPerWindow: cfg.providerModelBudgetEnforcer.maxDelegationsPerWindow,
            maxEstimatedTokensPerWindow: cfg.providerModelBudgetEnforcer.maxEstimatedTokensPerWindow,
            maxPerModelDelegationsPerWindow: cfg.providerModelBudgetEnforcer.maxPerModelDelegationsPerWindow,
        })),
        safeHook("delegation-concurrency-guard", () => createDelegationConcurrencyGuardHook({
            directory,
            enabled: cfg.delegationConcurrencyGuard.enabled,
            maxTotalConcurrent: cfg.delegationConcurrencyGuard.maxTotalConcurrent,
            maxExpensiveConcurrent: cfg.delegationConcurrencyGuard.maxExpensiveConcurrent,
            maxDeepConcurrent: cfg.delegationConcurrencyGuard.maxDeepConcurrent,
            maxCriticalConcurrent: cfg.delegationConcurrencyGuard.maxCriticalConcurrent,
            staleReservationMs: cfg.subagentLifecycleSupervisor.staleRunningMs,
        })),
        safeHook("agent-denied-tool-enforcer", () => createAgentDeniedToolEnforcerHook({
            directory,
            enabled: true,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.agentDeniedToolEnforcer),
        })),
        safeHook("hook-semantic-bridge", () => createHookSemanticBridgeHook({
            directory,
            enabled: true,
        })),
        safeHook("agent-model-resolver", () => createAgentModelResolverHook({
            directory,
            enabled: true,
            defaultOverrideDelta: cfg.adaptiveDelegationPolicy.defaultOverrideDelta,
            defaultIntentThreshold: cfg.adaptiveDelegationPolicy.defaultIntentThreshold,
            agentPolicyOverrides: cfg.adaptiveDelegationPolicy.agentPolicyOverrides,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.agentModelResolver),
        })),
        safeHook("delegation-outcome-learner", () => createDelegationOutcomeLearnerHook({
            directory,
            enabled: true,
            windowMs: cfg.adaptiveDelegationPolicy.windowMs,
            minSamples: cfg.adaptiveDelegationPolicy.minSamples,
            highFailureRate: cfg.adaptiveDelegationPolicy.highFailureRate,
            agentPolicyOverrides: cfg.adaptiveDelegationPolicy.agentPolicyOverrides,
        })),
        safeHook("delegation-fallback-orchestrator", () => createDelegationFallbackOrchestratorHook({
            directory,
            enabled: cfg.delegationFallbackOrchestrator.enabled,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.delegationFallbackOrchestrator),
        })),
        safeHook("agent-discoverability-injector", () => createAgentDiscoverabilityInjectorHook({
            directory,
            enabled: true,
            cooldownMs: cfg.adaptiveDelegationPolicy.discoverabilityCooldownMs,
        })),
        safeHook("delegation-decision-audit", () => createDelegationDecisionAuditHook({
            directory,
            enabled: true,
        })),
        safeHook("subagent-lifecycle-supervisor", () => createSubagentLifecycleSupervisorHook({
            directory,
            enabled: cfg.subagentLifecycleSupervisor.enabled,
            maxRetriesPerSession: cfg.subagentLifecycleSupervisor.maxRetriesPerSession,
            staleRunningMs: cfg.subagentLifecycleSupervisor.staleRunningMs,
            blockOnExhausted: cfg.subagentLifecycleSupervisor.blockOnExhausted,
        })),
        safeHook("subagent-telemetry-timeline", () => createSubagentTelemetryTimelineHook({
            directory,
            enabled: cfg.subagentTelemetryTimeline.enabled,
            maxTimelineEntries: cfg.subagentTelemetryTimeline.maxTimelineEntries,
            persistState: cfg.adaptiveDelegationPolicy.persistState,
            stateFile: cfg.adaptiveDelegationPolicy.stateFile,
            stateMaxEntries: cfg.adaptiveDelegationPolicy.stateMaxEntries,
        })),
        safeHook("adaptive-delegation-policy", () => createAdaptiveDelegationPolicyHook({
            directory,
            enabled: cfg.adaptiveDelegationPolicy.enabled,
            windowMs: cfg.adaptiveDelegationPolicy.windowMs,
            minSamples: cfg.adaptiveDelegationPolicy.minSamples,
            highFailureRate: cfg.adaptiveDelegationPolicy.highFailureRate,
            cooldownMs: cfg.adaptiveDelegationPolicy.cooldownMs,
            blockExpensiveDuringCooldown: cfg.adaptiveDelegationPolicy.blockExpensiveDuringCooldown,
        })),
        safeHook("session-recovery", () => createSessionRecoveryHook({
            directory,
            client: ctx.client,
            enabled: cfg.sessionRecovery.enabled,
            autoResume: cfg.sessionRecovery.autoResume,
        })),
        safeHook("session-runtime-system-context", () => createSessionRuntimeSystemContextHook({
            directory,
            enabled: cfg.sessionRuntimeSystemContext.enabled,
        })),
        safeHook("delegate-task-retry", () => createDelegateTaskRetryHook({
            enabled: cfg.delegateTaskRetry.enabled,
        })),
        safeHook("agent-context-shaper", () => createAgentContextShaperHook({
            directory,
            enabled: true,
        })),
        safeHook("validation-evidence-ledger", () => createValidationEvidenceLedgerHook({
            directory,
            enabled: cfg.validationEvidenceLedger.enabled,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.validationEvidenceLedger),
        })),
        safeHook("mistake-ledger", () => createMistakeLedgerHook({
            directory,
            enabled: cfg.mistakeLedger.enabled,
            path: cfg.mistakeLedger.path,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.mistakeLedger),
        })),
        safeHook("parallel-opportunity-detector", () => createParallelOpportunityDetectorHook({
            directory,
            enabled: cfg.parallelOpportunityDetector.enabled,
        })),
        safeHook("read-budget-optimizer", () => createReadBudgetOptimizerHook({
            directory,
            enabled: cfg.readBudgetOptimizer.enabled,
            smallReadLimit: cfg.readBudgetOptimizer.smallReadLimit,
            maxConsecutiveSmallReads: cfg.readBudgetOptimizer.maxConsecutiveSmallReads,
        })),
        safeHook("adaptive-validation-scheduler", () => createAdaptiveValidationSchedulerHook({
            directory,
            enabled: cfg.adaptiveValidationScheduler.enabled,
            reminderEditThreshold: cfg.adaptiveValidationScheduler.reminderEditThreshold,
        })),
        stopGuard,
        keywordDetector,
        safeHook("think-mode", () => createThinkModeHook({
            enabled: cfg.thinkMode.enabled,
        })),
        safeHook("thinking-block-validator", () => createThinkingBlockValidatorHook({
            enabled: cfg.thinkingBlockValidator.enabled,
        })),
        safeHook("auto-slash-command", () => createAutoSlashCommandHook({
            directory,
            enabled: cfg.autoSlashCommand.enabled,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.autoSlashCommand),
        })),
        safeHook("context-injector", () => createContextInjectorHook({
            directory,
            enabled: cfg.hooks.enabled,
            collector: contextCollector,
        })),
        safeHook("rules-injector", () => createRulesInjectorHook({
            directory,
            enabled: cfg.rulesInjector.enabled,
        })),
        safeHook("directory-agents-injector", () => createDirectoryAgentsInjectorHook({
            directory,
            enabled: cfg.directoryAgentsInjector.enabled,
            maxChars: cfg.directoryAgentsInjector.maxChars,
        })),
        safeHook("directory-readme-injector", () => createDirectoryReadmeInjectorHook({
            directory,
            enabled: cfg.directoryReadmeInjector.enabled,
            maxChars: cfg.directoryReadmeInjector.maxChars,
        })),
        safeHook("noninteractive-shell-guard", () => createNoninteractiveShellGuardHook({
            directory,
            enabled: cfg.noninteractiveShellGuard.enabled,
            injectEnvPrefix: cfg.noninteractiveShellGuard.injectEnvPrefix,
            envPrefixes: cfg.noninteractiveShellGuard.envPrefixes,
            prefixCommands: cfg.noninteractiveShellGuard.prefixCommands,
            blockedPatterns: cfg.noninteractiveShellGuard.blockedPatterns,
        })),
        safeHook("write-existing-file-guard", () => createWriteExistingFileGuardHook({
            directory,
            enabled: cfg.writeExistingFileGuard.enabled,
        })),
        safeHook("agent-reservation-guard", () => createAgentReservationGuardHook({
            directory,
            enabled: cfg.agentReservationGuard.enabled,
            enforce: cfg.agentReservationGuard.enforce,
            reservationEnvKeys: cfg.agentReservationGuard.reservationEnvKeys,
            stateFile: cfg.agentReservationGuard.stateFile,
        })),
        safeHook("subagent-question-blocker", () => createSubagentQuestionBlockerHook({
            directory,
            enabled: cfg.subagentQuestionBlocker.enabled,
            sessionPatterns: cfg.subagentQuestionBlocker.sessionPatterns,
        })),
        safeHook("tasks-todowrite-disabler", () => createTasksTodowriteDisablerHook({
            directory,
            enabled: cfg.tasksTodowriteDisabler.enabled,
        })),
        safeHook("task-resume-info", () => createTaskResumeInfoHook({
            enabled: cfg.taskResumeInfo.enabled,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.taskResumeInfo),
        })),
        safeHook("todo-continuation-enforcer", () => createTodoContinuationEnforcerHook({
            directory,
            enabled: cfg.todoContinuationEnforcer.enabled,
            client: ctx.client,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.todoContinuationEnforcer),
            stopGuard,
            cooldownMs: cfg.todoContinuationEnforcer.cooldownMs,
            maxConsecutiveFailures: cfg.todoContinuationEnforcer.maxConsecutiveFailures,
        })),
        safeHook("compaction-todo-preserver", () => createCompactionTodoPreserverHook({
            directory,
            enabled: cfg.compactionTodoPreserver.enabled,
            client: ctx.client,
            maxChars: cfg.compactionTodoPreserver.maxChars,
        })),
        safeHook("empty-task-response-detector", () => createEmptyTaskResponseDetectorHook({
            enabled: cfg.emptyTaskResponseDetector.enabled,
        })),
        safeHook("edit-error-recovery", () => createEditErrorRecoveryHook({
            enabled: cfg.editErrorRecovery.enabled,
        })),
        safeHook("json-error-recovery", () => createJsonErrorRecoveryHook({
            enabled: cfg.jsonErrorRecovery.enabled,
        })),
        safeHook("provider-token-limit-recovery", () => createProviderTokenLimitRecoveryHook({
            directory,
            enabled: cfg.providerTokenLimitRecovery.enabled,
            client: ctx.client,
            cooldownMs: cfg.providerTokenLimitRecovery.cooldownMs,
        })),
        safeHook("hashline-read-enhancer", () => createHashlineReadEnhancerHook({
            enabled: cfg.hashlineReadEnhancer.enabled,
        })),
        safeHook("max-step-recovery", () => createMaxStepRecoveryHook({
            enabled: cfg.maxStepRecovery.enabled,
        })),
        safeHook("mode-transition-reminder", () => createModeTransitionReminderHook({
            enabled: cfg.modeTransitionReminder.enabled,
        })),
        safeHook("todoread-cadence-reminder", () => createTodoreadCadenceReminderHook({
            enabled: cfg.todoreadCadenceReminder.enabled,
            cooldownEvents: cfg.todoreadCadenceReminder.cooldownEvents,
        })),
        safeHook("provider-retry-backoff-guidance", () => createProviderRetryBackoffGuidanceHook({
            directory,
            enabled: cfg.providerRetryBackoffGuidance.enabled,
            client: ctx.client,
            cooldownMs: cfg.providerRetryBackoffGuidance.cooldownMs,
        })),
        safeHook("provider-error-classifier", () => createProviderErrorClassifierHook({
            directory,
            enabled: cfg.providerErrorClassifier.enabled,
            client: ctx.client,
            cooldownMs: cfg.providerErrorClassifier.cooldownMs,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.providerErrorClassifier),
        })),
        safeHook("codex-header-injector", () => createCodexHeaderInjectorHook({
            directory,
            enabled: cfg.codexHeaderInjector.enabled,
        })),
        safeHook("plan-handoff-reminder", () => createPlanHandoffReminderHook({
            enabled: cfg.planHandoffReminder.enabled,
        })),
        safeHook("comment-checker", () => createCommentCheckerHook({
            enabled: cfg.commentChecker.enabled,
        })),
        safeHook("agent-user-reminder", () => createAgentUserReminderHook({
            enabled: cfg.agentUserReminder.enabled,
        })),
        safeHook("direct-work-warning", () => createDirectWorkWarningHook({
            directory,
            enabled: cfg.directWorkWarning.enabled,
            blockRepeatedEdits: cfg.directWorkWarning.blockRepeatedEdits,
        })),
        safeHook("unstable-agent-babysitter", () => createUnstableAgentBabysitterHook({
            enabled: cfg.unstableAgentBabysitter.enabled,
            riskyPatterns: cfg.unstableAgentBabysitter.riskyPatterns,
        })),
        safeHook("question-label-truncator", () => createQuestionLabelTruncatorHook({
            enabled: cfg.questionLabelTruncator.enabled,
            maxLength: cfg.questionLabelTruncator.maxLength,
        })),
        safeHook("dangerous-command-guard", () => createDangerousCommandGuardHook({
            directory,
            enabled: cfg.dangerousCommandGuard.enabled,
            blockedPatterns: cfg.dangerousCommandGuard.blockedPatterns,
        })),
        safeHook("secret-leak-guard", () => createSecretLeakGuardHook({
            directory,
            enabled: cfg.secretLeakGuard.enabled,
            redactionToken: cfg.secretLeakGuard.redactionToken,
            patterns: cfg.secretLeakGuard.patterns,
        })),
        safeHook("primary-worktree-guard", () => createPrimaryWorktreeGuardHook({
            directory,
            enabled: cfg.primaryWorktreeGuard.enabled,
            allowedBranches: cfg.primaryWorktreeGuard.allowedBranches,
            blockEdits: cfg.primaryWorktreeGuard.blockEdits,
            blockBranchSwitches: cfg.primaryWorktreeGuard.blockBranchSwitches,
        })),
        safeHook("secret-commit-guard", () => createSecretCommitGuardHook({
            directory,
            enabled: cfg.secretCommitGuard.enabled,
            patterns: cfg.secretCommitGuard.patterns,
        })),
        safeHook("workflow-conformance-guard", () => createWorkflowConformanceGuardHook({
            directory,
            enabled: cfg.workflowConformanceGuard.enabled,
            protectedBranches: cfg.workflowConformanceGuard.protectedBranches,
            blockEditsOnProtectedBranches: cfg.workflowConformanceGuard.blockEditsOnProtectedBranches,
        })),
        safeHook("scope-drift-guard", () => createScopeDriftGuardHook({
            directory,
            enabled: cfg.scopeDriftGuard.enabled,
            allowedPaths: cfg.scopeDriftGuard.allowedPaths,
            blockOnDrift: cfg.scopeDriftGuard.blockOnDrift,
        })),
        safeHook("done-proof-enforcer", () => createDoneProofEnforcerHook({
            directory,
            enabled: cfg.doneProofEnforcer.enabled,
            requiredMarkers: cfg.doneProofEnforcer.requiredMarkers,
            requireLedgerEvidence: cfg.doneProofEnforcer.requireLedgerEvidence,
            allowTextFallback: cfg.doneProofEnforcer.allowTextFallback,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.doneProofEnforcer),
        })),
        safeHook("dependency-risk-guard", () => createDependencyRiskGuardHook({
            directory,
            enabled: cfg.dependencyRiskGuard.enabled,
            lockfilePatterns: cfg.dependencyRiskGuard.lockfilePatterns,
            commandPatterns: cfg.dependencyRiskGuard.commandPatterns,
        })),
        safeHook("docs-drift-guard", () => createDocsDriftGuardHook({
            directory,
            enabled: cfg.docsDriftGuard.enabled,
            sourcePatterns: cfg.docsDriftGuard.sourcePatterns,
            docsPatterns: cfg.docsDriftGuard.docsPatterns,
            blockOnDrift: cfg.docsDriftGuard.blockOnDrift,
        })),
        safeHook("hook-test-parity-guard", () => createHookTestParityGuardHook({
            directory,
            enabled: cfg.hookTestParityGuard.enabled,
            sourcePatterns: cfg.hookTestParityGuard.sourcePatterns,
            testPatterns: cfg.hookTestParityGuard.testPatterns,
            blockOnMismatch: cfg.hookTestParityGuard.blockOnMismatch,
        })),
        safeHook("retry-budget-guard", () => createRetryBudgetGuardHook({
            enabled: cfg.retryBudgetGuard.enabled,
            maxRetries: cfg.retryBudgetGuard.maxRetries,
        })),
        safeHook("stale-loop-expiry-guard", () => createStaleLoopExpiryGuardHook({
            directory,
            enabled: cfg.staleLoopExpiryGuard.enabled,
            maxAgeMinutes: cfg.staleLoopExpiryGuard.maxAgeMinutes,
        })),
        safeHook("parallel-writer-conflict-guard", () => createParallelWriterConflictGuardHook({
            directory,
            enabled: cfg.parallelWriterConflictGuard.enabled,
            maxConcurrentWriters: cfg.parallelWriterConflictGuard.maxConcurrentWriters,
            writerCountEnvKeys: cfg.parallelWriterConflictGuard.writerCountEnvKeys,
            reservationPathsEnvKeys: cfg.parallelWriterConflictGuard.reservationPathsEnvKeys,
            activeReservationPathsEnvKeys: cfg.parallelWriterConflictGuard.activeReservationPathsEnvKeys,
            enforceReservationCoverage: cfg.parallelWriterConflictGuard.enforceReservationCoverage,
            stateFile: cfg.parallelWriterConflictGuard.stateFile,
        })),
        safeHook("branch-freshness-guard", () => createBranchFreshnessGuardHook({
            directory,
            enabled: cfg.branchFreshnessGuard.enabled,
            baseRef: cfg.branchFreshnessGuard.baseRef,
            maxBehind: cfg.branchFreshnessGuard.maxBehind,
            enforceOnPrCreate: cfg.branchFreshnessGuard.enforceOnPrCreate,
            enforceOnPrMerge: cfg.branchFreshnessGuard.enforceOnPrMerge,
        })),
        safeHook("pr-readiness-guard", () => createPrReadinessGuardHook({
            directory,
            enabled: cfg.prReadinessGuard.enabled,
            requireCleanWorktree: cfg.prReadinessGuard.requireCleanWorktree,
            requireValidationEvidence: cfg.prReadinessGuard.requireValidationEvidence,
            requiredMarkers: cfg.doneProofEnforcer.requiredMarkers,
        })),
        safeHook("pr-body-evidence-guard", () => createPrBodyEvidenceGuardHook({
            directory,
            enabled: cfg.prBodyEvidenceGuard.enabled,
            requireSummarySection: cfg.prBodyEvidenceGuard.requireSummarySection,
            requireValidationSection: cfg.prBodyEvidenceGuard.requireValidationSection,
            requireValidationEvidence: cfg.prBodyEvidenceGuard.requireValidationEvidence,
            allowUninspectableBody: cfg.prBodyEvidenceGuard.allowUninspectableBody,
            requiredMarkers: cfg.doneProofEnforcer.requiredMarkers,
            decisionRuntime: llmDecisionRuntimeForHook(GATEWAY_LLM_DECISION_RUNTIME_BINDINGS.prBodyEvidenceGuard),
        })),
        safeHook("merge-readiness-guard", () => createMergeReadinessGuardHook({
            directory,
            enabled: cfg.mergeReadinessGuard.enabled,
            requireDeleteBranch: cfg.mergeReadinessGuard.requireDeleteBranch,
            requireStrategy: cfg.mergeReadinessGuard.requireStrategy,
            disallowAdminBypass: cfg.mergeReadinessGuard.disallowAdminBypass,
        })),
        safeHook("gh-checks-merge-guard", () => createGhChecksMergeGuardHook({
            directory,
            enabled: cfg.ghChecksMergeGuard.enabled,
            blockDraft: cfg.ghChecksMergeGuard.blockDraft,
            requireApprovedReview: cfg.ghChecksMergeGuard.requireApprovedReview,
            requirePassingChecks: cfg.ghChecksMergeGuard.requirePassingChecks,
            blockedMergeStates: cfg.ghChecksMergeGuard.blockedMergeStates,
            failOpenOnError: cfg.ghChecksMergeGuard.failOpenOnError,
        })),
        safeHook("post-merge-sync-guard", () => createPostMergeSyncGuardHook({
            directory,
            enabled: cfg.postMergeSyncGuard.enabled,
            requireDeleteBranch: cfg.postMergeSyncGuard.requireDeleteBranch,
            enforceMainSyncInline: cfg.postMergeSyncGuard.enforceMainSyncInline,
            reminderCommands: cfg.postMergeSyncGuard.reminderCommands,
        })),
        createStaleLoopExpiryGuardHook({
            directory,
            enabled: cfg.staleLoopExpiryGuard.enabled,
            maxAgeMinutes: cfg.staleLoopExpiryGuard.maxAgeMinutes,
        }),
        createParallelWriterConflictGuardHook({
            directory,
            enabled: cfg.parallelWriterConflictGuard.enabled,
            maxConcurrentWriters: cfg.parallelWriterConflictGuard.maxConcurrentWriters,
            writerCountEnvKeys: cfg.parallelWriterConflictGuard.writerCountEnvKeys,
            reservationPathsEnvKeys: cfg.parallelWriterConflictGuard.reservationPathsEnvKeys,
            activeReservationPathsEnvKeys: cfg.parallelWriterConflictGuard.activeReservationPathsEnvKeys,
            enforceReservationCoverage: cfg.parallelWriterConflictGuard.enforceReservationCoverage,
            stateFile: cfg.parallelWriterConflictGuard.stateFile,
        }),
        createBranchFreshnessGuardHook({
            directory,
            enabled: cfg.branchFreshnessGuard.enabled,
            baseRef: cfg.branchFreshnessGuard.baseRef,
            maxBehind: cfg.branchFreshnessGuard.maxBehind,
            enforceOnPrCreate: cfg.branchFreshnessGuard.enforceOnPrCreate,
            enforceOnPrMerge: cfg.branchFreshnessGuard.enforceOnPrMerge,
        }),
        createPrReadinessGuardHook({
            directory,
            enabled: cfg.prReadinessGuard.enabled,
            requireCleanWorktree: cfg.prReadinessGuard.requireCleanWorktree,
            requireValidationEvidence: cfg.prReadinessGuard.requireValidationEvidence,
            requiredMarkers: cfg.doneProofEnforcer.requiredMarkers,
        }),
        createPrBodyEvidenceGuardHook({
            directory,
            enabled: cfg.prBodyEvidenceGuard.enabled,
            requireSummarySection: cfg.prBodyEvidenceGuard.requireSummarySection,
            requireValidationSection: cfg.prBodyEvidenceGuard.requireValidationSection,
            requireValidationEvidence: cfg.prBodyEvidenceGuard.requireValidationEvidence,
            allowUninspectableBody: cfg.prBodyEvidenceGuard.allowUninspectableBody,
            requiredMarkers: cfg.doneProofEnforcer.requiredMarkers,
            decisionRuntime: llmDecisionRuntimeForHook("pr-body-evidence-guard"),
        }),
        createMergeReadinessGuardHook({
            directory,
            enabled: cfg.mergeReadinessGuard.enabled,
            requireDeleteBranch: cfg.mergeReadinessGuard.requireDeleteBranch,
            requireStrategy: cfg.mergeReadinessGuard.requireStrategy,
            disallowAdminBypass: cfg.mergeReadinessGuard.disallowAdminBypass,
        }),
        createGhChecksMergeGuardHook({
            directory,
            enabled: cfg.ghChecksMergeGuard.enabled,
            blockDraft: cfg.ghChecksMergeGuard.blockDraft,
            requireApprovedReview: cfg.ghChecksMergeGuard.requireApprovedReview,
            requirePassingChecks: cfg.ghChecksMergeGuard.requirePassingChecks,
            blockedMergeStates: cfg.ghChecksMergeGuard.blockedMergeStates,
            failOpenOnError: cfg.ghChecksMergeGuard.failOpenOnError,
        }),
        createPostMergeSyncGuardHook({
            directory,
            enabled: cfg.postMergeSyncGuard.enabled,
            requireDeleteBranch: cfg.postMergeSyncGuard.requireDeleteBranch,
            enforceMainSyncInline: cfg.postMergeSyncGuard.enforceMainSyncInline,
            reminderCommands: cfg.postMergeSyncGuard.reminderCommands,
        }),
    ];
    if (!cfg.hooks.enabled) {
        return [];
    }
    return resolveHookOrder(hooks.filter((hook) => hook !== null), cfg.hooks.order, cfg.hooks.disabled);
}
// Creates gateway plugin entrypoint with deterministic hook dispatch.
export default function GatewayCorePlugin(ctx) {
    const hooks = configuredHooks(ctx);
    const noisyDispatchSampleCounters = new Map();
    const noisyDispatchSampleRate = dispatchSampleRate();
    const directory = typeof ctx.directory === "string" && ctx.directory.trim()
        ? ctx.directory
        : process.cwd();
    function shouldWriteDispatchAudit(reasonCode, eventType) {
        if (!DISPATCH_NOISY_REASON_CODES.has(reasonCode)) {
            return true;
        }
        if (!DISPATCH_NOISY_EVENTS.has(eventType)) {
            return true;
        }
        const key = `${reasonCode}:${eventType}`;
        const next = (noisyDispatchSampleCounters.get(key) ?? 0) + 1;
        noisyDispatchSampleCounters.set(key, next);
        return next === 1 || next % noisyDispatchSampleRate === 0;
    }
    // Dispatches plugin lifecycle event to all enabled hooks in order.
    async function event(input) {
        if (shouldWriteDispatchAudit("event_dispatch", input.event.type)) {
            writeGatewayEventAudit(directory, {
                hook: "gateway-core",
                stage: "dispatch",
                reason_code: "event_dispatch",
                event_type: input.event.type,
                hook_count: hooks.length,
            });
        }
        for (const hook of hooks) {
            const result = await dispatchGatewayHookEvent({
                hook,
                eventType: input.event.type,
                payload: {
                    properties: input.event.properties,
                    directory,
                },
                directory,
            });
            if (!result.ok && (result.critical || result.blocked)) {
                throw result.error;
            }
        }
    }
    // Dispatches slash command interception event to ordered hooks.
    async function toolExecuteBefore(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "tool_execute_before_dispatch",
            event_type: "tool.execute.before",
            tool: input.tool,
            hook_count: hooks.length,
            has_command: typeof output.args?.command === "string" &&
                output.args.command.trim().length > 0,
        });
        const executedHooks = [];
        try {
            for (const hook of hooks) {
                const result = await dispatchGatewayHookEvent({
                    hook,
                    eventType: "tool.execute.before",
                    payload: { input, output, directory },
                    directory,
                });
                if (!result.ok) {
                    if (result.critical || result.blocked) {
                        throw result.error;
                    }
                    continue;
                }
                executedHooks.push(hook);
            }
        }
        catch (error) {
            writeGatewayEventAudit(directory, {
                hook: "gateway-core",
                stage: "dispatch",
                reason_code: "tool_execute_before_failed",
                event_type: "tool.execute.before",
                tool: input.tool,
                hook_count: executedHooks.length,
            });
            for (const hook of executedHooks.reverse()) {
                try {
                    const result = await dispatchGatewayHookEvent({
                        hook,
                        eventType: "tool.execute.before.error",
                        payload: {
                            input,
                            output,
                            directory,
                            error,
                        },
                        directory,
                    });
                    if (!result.ok && result.critical) {
                        throw result.error;
                    }
                }
                catch {
                    // Keep the original before-hook failure as the surfaced error.
                }
            }
            throw error;
        }
    }
    // Dispatches command execution interception event to ordered hooks.
    async function commandExecuteBefore(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "command_execute_before_dispatch",
            event_type: "command.execute.before",
            command: input.command,
            hook_count: hooks.length,
        });
        for (const hook of hooks) {
            const result = await dispatchGatewayHookEvent({
                hook,
                eventType: "command.execute.before",
                payload: { input, output, directory },
                directory,
            });
            if (!result.ok && (result.critical || result.blocked)) {
                throw result.error;
            }
        }
    }
    // Dispatches command post-execution event to ordered hooks.
    async function commandExecuteAfter(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "command_execute_after_dispatch",
            event_type: "command.execute.after",
            command: input.command,
            hook_count: hooks.length,
            has_output: output.output !== undefined,
        });
        for (const hook of hooks) {
            const result = await dispatchGatewayHookEvent({
                hook,
                eventType: "command.execute.after",
                payload: { input, output, directory },
                directory,
            });
            if (!result.ok && (result.critical || result.blocked)) {
                throw result.error;
            }
        }
    }
    // Dispatches slash command post-execution event to ordered hooks.
    async function toolExecuteAfter(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "tool_execute_after_dispatch",
            event_type: "tool.execute.after",
            tool: input.tool,
            hook_count: hooks.length,
            has_output: typeof output.output === "string" && output.output.trim().length > 0,
        });
        for (const hook of hooks) {
            const result = await dispatchGatewayHookEvent({
                hook,
                eventType: "tool.execute.after",
                payload: { input, output, directory },
                directory,
            });
            if (!result.ok && (result.critical || result.blocked)) {
                throw result.error;
            }
        }
    }
    // Dispatches chat message lifecycle signal to ordered hooks.
    async function chatMessage(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "chat_message_dispatch",
            event_type: "chat.message",
            has_session_id: typeof input.sessionID === "string" &&
                input.sessionID.trim().length > 0,
            hook_count: hooks.length,
        });
        for (const hook of hooks) {
            const result = await dispatchGatewayHookEvent({
                hook,
                eventType: "chat.message",
                payload: {
                    properties: {
                        ...input,
                    },
                    output,
                    directory,
                },
                directory,
            });
            if (!result.ok && (result.critical || result.blocked)) {
                throw result.error;
            }
        }
    }
    // Dispatches experimental chat transform lifecycle signal to ordered hooks.
    async function chatMessagesTransform(input, output) {
        if (shouldWriteDispatchAudit("chat_messages_transform_dispatch", "experimental.chat.messages.transform")) {
            writeGatewayEventAudit(directory, {
                hook: "gateway-core",
                stage: "dispatch",
                reason_code: "chat_messages_transform_dispatch",
                event_type: "experimental.chat.messages.transform",
                has_session_id: typeof input.sessionID === "string" &&
                    input.sessionID.trim().length > 0,
                hook_count: hooks.length,
            });
        }
        for (const hook of hooks) {
            const result = await dispatchGatewayHookEvent({
                hook,
                eventType: "experimental.chat.messages.transform",
                payload: {
                    input,
                    output,
                    directory,
                },
                directory,
            });
            if (!result.ok && (result.critical || result.blocked)) {
                throw result.error;
            }
        }
    }
    async function chatSystemTransform(input, output) {
        if (shouldWriteDispatchAudit("chat_system_transform_dispatch", "experimental.chat.system.transform")) {
            writeGatewayEventAudit(directory, {
                hook: "gateway-core",
                stage: "dispatch",
                reason_code: "chat_system_transform_dispatch",
                event_type: "experimental.chat.system.transform",
                has_session_id: typeof input.sessionID === "string" &&
                    input.sessionID.trim().length > 0,
                hook_count: hooks.length,
            });
        }
        for (const hook of hooks) {
            const result = await dispatchGatewayHookEvent({
                hook,
                eventType: "experimental.chat.system.transform",
                payload: {
                    input,
                    output,
                    directory,
                },
                directory,
            });
            if (!result.ok && (result.critical || result.blocked)) {
                throw result.error;
            }
        }
    }
    return {
        event,
        "tool.execute.before": toolExecuteBefore,
        "command.execute.before": commandExecuteBefore,
        "command.execute.after": commandExecuteAfter,
        "tool.execute.after": toolExecuteAfter,
        "chat.message": chatMessage,
        "experimental.chat.messages.transform": chatMessagesTransform,
        "experimental.chat.system.transform": chatSystemTransform,
    };
}
