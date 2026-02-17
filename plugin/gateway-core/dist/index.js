import { loadGatewayConfig } from "./config/load.js";
import { writeGatewayEventAudit } from "./audit/event-audit.js";
import { createAutopilotLoopHook } from "./hooks/autopilot-loop/index.js";
import { createAutoSlashCommandHook } from "./hooks/auto-slash-command/index.js";
import { createAgentUserReminderHook } from "./hooks/agent-user-reminder/index.js";
import { createBranchFreshnessGuardHook } from "./hooks/branch-freshness-guard/index.js";
import { createCommentCheckerHook } from "./hooks/comment-checker/index.js";
import { createCompactionContextInjectorHook } from "./hooks/compaction-context-injector/index.js";
import { createContinuationHook } from "./hooks/continuation/index.js";
import { createContextWindowMonitorHook } from "./hooks/context-window-monitor/index.js";
import { createDelegateTaskRetryHook } from "./hooks/delegate-task-retry/index.js";
import { createDependencyRiskGuardHook } from "./hooks/dependency-risk-guard/index.js";
import { createDocsDriftGuardHook } from "./hooks/docs-drift-guard/index.js";
import { createDoneProofEnforcerHook } from "./hooks/done-proof-enforcer/index.js";
import { createDangerousCommandGuardHook } from "./hooks/dangerous-command-guard/index.js";
import { createEmptyTaskResponseDetectorHook } from "./hooks/empty-task-response-detector/index.js";
import { createEditErrorRecoveryHook } from "./hooks/edit-error-recovery/index.js";
import { createJsonErrorRecoveryHook } from "./hooks/json-error-recovery/index.js";
import { createGhChecksMergeGuardHook } from "./hooks/gh-checks-merge-guard/index.js";
import { createGlobalProcessPressureHook } from "./hooks/global-process-pressure/index.js";
import { createHookTestParityGuardHook } from "./hooks/hook-test-parity-guard/index.js";
import { createDirectoryAgentsInjectorHook } from "./hooks/directory-agents-injector/index.js";
import { createDirectoryReadmeInjectorHook } from "./hooks/directory-readme-injector/index.js";
import { createKeywordDetectorHook } from "./hooks/keyword-detector/index.js";
import { createMergeReadinessGuardHook } from "./hooks/merge-readiness-guard/index.js";
import { createNoninteractiveShellGuardHook } from "./hooks/noninteractive-shell-guard/index.js";
import { createParallelOpportunityDetectorHook } from "./hooks/parallel-opportunity-detector/index.js";
import { createParallelWriterConflictGuardHook } from "./hooks/parallel-writer-conflict-guard/index.js";
import { createPostMergeSyncGuardHook } from "./hooks/post-merge-sync-guard/index.js";
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
import { createStopContinuationGuardHook } from "./hooks/stop-continuation-guard/index.js";
import { createSubagentQuestionBlockerHook } from "./hooks/subagent-question-blocker/index.js";
import { createTasksTodowriteDisablerHook } from "./hooks/tasks-todowrite-disabler/index.js";
import { createTaskResumeInfoHook } from "./hooks/task-resume-info/index.js";
import { createTodoContinuationEnforcerHook } from "./hooks/todo-continuation-enforcer/index.js";
import { createCompactionTodoPreserverHook } from "./hooks/compaction-todo-preserver/index.js";
import { createThinkModeHook } from "./hooks/think-mode/index.js";
import { createThinkingBlockValidatorHook } from "./hooks/thinking-block-validator/index.js";
import { createToolOutputTruncatorHook } from "./hooks/tool-output-truncator/index.js";
import { createUnstableAgentBabysitterHook } from "./hooks/unstable-agent-babysitter/index.js";
import { createValidationEvidenceLedgerHook } from "./hooks/validation-evidence-ledger/index.js";
import { createAdaptiveValidationSchedulerHook } from "./hooks/adaptive-validation-scheduler/index.js";
import { createAgentReservationGuardHook } from "./hooks/agent-reservation-guard/index.js";
import { createWorkflowConformanceGuardHook } from "./hooks/workflow-conformance-guard/index.js";
import { createWriteExistingFileGuardHook } from "./hooks/write-existing-file-guard/index.js";
import { createStaleLoopExpiryGuardHook } from "./hooks/stale-loop-expiry-guard/index.js";
import { contextCollector } from "./hooks/context-injector/collector.js";
import { createContextInjectorHook } from "./hooks/context-injector/index.js";
import { resolveHookOrder } from "./hooks/registry.js";
// Creates ordered hook list using gateway config and default hooks.
function configuredHooks(ctx) {
    const directory = typeof ctx.directory === "string" && ctx.directory.trim() ? ctx.directory : process.cwd();
    const cfg = loadGatewayConfig(ctx.config);
    const stopGuard = createStopContinuationGuardHook({
        directory,
        enabled: cfg.stopContinuationGuard.enabled,
    });
    const keywordDetector = createKeywordDetectorHook({
        directory,
        enabled: cfg.keywordDetector.enabled,
    });
    const hooks = [
        createAutopilotLoopHook({
            directory,
            defaults: {
                enabled: cfg.autopilotLoop.enabled,
                maxIterations: cfg.autopilotLoop.maxIterations,
                completionMode: cfg.autopilotLoop.completionMode,
                completionPromise: cfg.autopilotLoop.completionPromise,
            },
            collector: contextCollector,
        }),
        createContinuationHook({
            directory,
            client: ctx.client,
            stopGuard,
            keywordDetector,
            bootstrapFromRuntime: cfg.autopilotLoop.bootstrapFromRuntimeOnIdle,
            maxIgnoredCompletionCycles: cfg.autopilotLoop.maxIgnoredCompletionCycles,
        }),
        createSafetyHook({
            directory,
            orphanMaxAgeHours: cfg.autopilotLoop.orphanMaxAgeHours,
        }),
        createToolOutputTruncatorHook({
            directory,
            enabled: cfg.toolOutputTruncator.enabled,
            maxChars: cfg.toolOutputTruncator.maxChars,
            maxLines: cfg.toolOutputTruncator.maxLines,
            tools: cfg.toolOutputTruncator.tools,
        }),
        createSemanticOutputSummarizerHook({
            directory,
            enabled: cfg.semanticOutputSummarizer.enabled,
            minChars: cfg.semanticOutputSummarizer.minChars,
            minLines: cfg.semanticOutputSummarizer.minLines,
            maxSummaryLines: cfg.semanticOutputSummarizer.maxSummaryLines,
        }),
        createContextWindowMonitorHook({
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
        }),
        createPreemptiveCompactionHook({
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
        }),
        createCompactionContextInjectorHook({
            directory,
            enabled: cfg.compactionContextInjector.enabled,
        }),
        createGlobalProcessPressureHook({
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
        }),
        createSessionRecoveryHook({
            directory,
            client: ctx.client,
            enabled: cfg.sessionRecovery.enabled,
            autoResume: cfg.sessionRecovery.autoResume,
        }),
        createDelegateTaskRetryHook({
            enabled: cfg.delegateTaskRetry.enabled,
        }),
        createValidationEvidenceLedgerHook({
            directory,
            enabled: cfg.validationEvidenceLedger.enabled,
        }),
        createParallelOpportunityDetectorHook({
            directory,
            enabled: cfg.parallelOpportunityDetector.enabled,
        }),
        createReadBudgetOptimizerHook({
            directory,
            enabled: cfg.readBudgetOptimizer.enabled,
            smallReadLimit: cfg.readBudgetOptimizer.smallReadLimit,
            maxConsecutiveSmallReads: cfg.readBudgetOptimizer.maxConsecutiveSmallReads,
        }),
        createAdaptiveValidationSchedulerHook({
            directory,
            enabled: cfg.adaptiveValidationScheduler.enabled,
            reminderEditThreshold: cfg.adaptiveValidationScheduler.reminderEditThreshold,
        }),
        stopGuard,
        keywordDetector,
        createThinkModeHook({
            enabled: cfg.thinkMode.enabled,
        }),
        createThinkingBlockValidatorHook({
            enabled: cfg.thinkingBlockValidator.enabled,
        }),
        createAutoSlashCommandHook({
            directory,
            enabled: cfg.autoSlashCommand.enabled,
        }),
        createContextInjectorHook({
            directory,
            enabled: cfg.hooks.enabled,
            collector: contextCollector,
        }),
        createRulesInjectorHook({
            directory,
            enabled: cfg.rulesInjector.enabled,
        }),
        createDirectoryAgentsInjectorHook({
            directory,
            enabled: cfg.directoryAgentsInjector.enabled,
            maxChars: cfg.directoryAgentsInjector.maxChars,
        }),
        createDirectoryReadmeInjectorHook({
            directory,
            enabled: cfg.directoryReadmeInjector.enabled,
            maxChars: cfg.directoryReadmeInjector.maxChars,
        }),
        createNoninteractiveShellGuardHook({
            directory,
            enabled: cfg.noninteractiveShellGuard.enabled,
            injectEnvPrefix: cfg.noninteractiveShellGuard.injectEnvPrefix,
            envPrefixes: cfg.noninteractiveShellGuard.envPrefixes,
            prefixCommands: cfg.noninteractiveShellGuard.prefixCommands,
            blockedPatterns: cfg.noninteractiveShellGuard.blockedPatterns,
        }),
        createWriteExistingFileGuardHook({
            directory,
            enabled: cfg.writeExistingFileGuard.enabled,
        }),
        createAgentReservationGuardHook({
            directory,
            enabled: cfg.agentReservationGuard.enabled,
            enforce: cfg.agentReservationGuard.enforce,
            reservationEnvKeys: cfg.agentReservationGuard.reservationEnvKeys,
        }),
        createSubagentQuestionBlockerHook({
            directory,
            enabled: cfg.subagentQuestionBlocker.enabled,
            sessionPatterns: cfg.subagentQuestionBlocker.sessionPatterns,
        }),
        createTasksTodowriteDisablerHook({
            directory,
            enabled: cfg.tasksTodowriteDisabler.enabled,
        }),
        createTaskResumeInfoHook({
            enabled: cfg.taskResumeInfo.enabled,
        }),
        createTodoContinuationEnforcerHook({
            directory,
            enabled: cfg.todoContinuationEnforcer.enabled,
            client: ctx.client,
            stopGuard,
            cooldownMs: cfg.todoContinuationEnforcer.cooldownMs,
            maxConsecutiveFailures: cfg.todoContinuationEnforcer.maxConsecutiveFailures,
        }),
        createCompactionTodoPreserverHook({
            directory,
            enabled: cfg.compactionTodoPreserver.enabled,
            client: ctx.client,
            maxChars: cfg.compactionTodoPreserver.maxChars,
        }),
        createEmptyTaskResponseDetectorHook({
            enabled: cfg.emptyTaskResponseDetector.enabled,
        }),
        createEditErrorRecoveryHook({
            enabled: cfg.editErrorRecovery.enabled,
        }),
        createJsonErrorRecoveryHook({
            enabled: cfg.jsonErrorRecovery.enabled,
        }),
        createCommentCheckerHook({
            enabled: cfg.commentChecker.enabled,
        }),
        createAgentUserReminderHook({
            enabled: cfg.agentUserReminder.enabled,
        }),
        createUnstableAgentBabysitterHook({
            enabled: cfg.unstableAgentBabysitter.enabled,
            riskyPatterns: cfg.unstableAgentBabysitter.riskyPatterns,
        }),
        createQuestionLabelTruncatorHook({
            enabled: cfg.questionLabelTruncator.enabled,
            maxLength: cfg.questionLabelTruncator.maxLength,
        }),
        createDangerousCommandGuardHook({
            directory,
            enabled: cfg.dangerousCommandGuard.enabled,
            blockedPatterns: cfg.dangerousCommandGuard.blockedPatterns,
        }),
        createSecretLeakGuardHook({
            directory,
            enabled: cfg.secretLeakGuard.enabled,
            redactionToken: cfg.secretLeakGuard.redactionToken,
            patterns: cfg.secretLeakGuard.patterns,
        }),
        createSecretCommitGuardHook({
            directory,
            enabled: cfg.secretCommitGuard.enabled,
            patterns: cfg.secretCommitGuard.patterns,
        }),
        createWorkflowConformanceGuardHook({
            directory,
            enabled: cfg.workflowConformanceGuard.enabled,
            protectedBranches: cfg.workflowConformanceGuard.protectedBranches,
            blockEditsOnProtectedBranches: cfg.workflowConformanceGuard.blockEditsOnProtectedBranches,
        }),
        createScopeDriftGuardHook({
            directory,
            enabled: cfg.scopeDriftGuard.enabled,
            allowedPaths: cfg.scopeDriftGuard.allowedPaths,
            blockOnDrift: cfg.scopeDriftGuard.blockOnDrift,
        }),
        createDoneProofEnforcerHook({
            enabled: cfg.doneProofEnforcer.enabled,
            requiredMarkers: cfg.doneProofEnforcer.requiredMarkers,
            requireLedgerEvidence: cfg.doneProofEnforcer.requireLedgerEvidence,
            allowTextFallback: cfg.doneProofEnforcer.allowTextFallback,
        }),
        createDependencyRiskGuardHook({
            directory,
            enabled: cfg.dependencyRiskGuard.enabled,
            lockfilePatterns: cfg.dependencyRiskGuard.lockfilePatterns,
            commandPatterns: cfg.dependencyRiskGuard.commandPatterns,
        }),
        createDocsDriftGuardHook({
            directory,
            enabled: cfg.docsDriftGuard.enabled,
            sourcePatterns: cfg.docsDriftGuard.sourcePatterns,
            docsPatterns: cfg.docsDriftGuard.docsPatterns,
            blockOnDrift: cfg.docsDriftGuard.blockOnDrift,
        }),
        createHookTestParityGuardHook({
            directory,
            enabled: cfg.hookTestParityGuard.enabled,
            sourcePatterns: cfg.hookTestParityGuard.sourcePatterns,
            testPatterns: cfg.hookTestParityGuard.testPatterns,
            blockOnMismatch: cfg.hookTestParityGuard.blockOnMismatch,
        }),
        createRetryBudgetGuardHook({
            enabled: cfg.retryBudgetGuard.enabled,
            maxRetries: cfg.retryBudgetGuard.maxRetries,
        }),
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
    return resolveHookOrder(hooks, cfg.hooks.order, cfg.hooks.disabled);
}
// Creates gateway plugin entrypoint with deterministic hook dispatch.
export default function GatewayCorePlugin(ctx) {
    const hooks = configuredHooks(ctx);
    const directory = typeof ctx.directory === "string" && ctx.directory.trim() ? ctx.directory : process.cwd();
    // Dispatches plugin lifecycle event to all enabled hooks in order.
    async function event(input) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "event_dispatch",
            event_type: input.event.type,
            hook_count: hooks.length,
        });
        for (const hook of hooks) {
            await hook.event(input.event.type, {
                properties: input.event.properties,
                directory,
            });
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
            has_command: typeof output.args?.command === "string" && output.args.command.trim().length > 0,
        });
        for (const hook of hooks) {
            await hook.event("tool.execute.before", { input, output, directory });
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
            await hook.event("command.execute.before", { input, output, directory });
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
            await hook.event("tool.execute.after", { input, output, directory });
        }
    }
    // Dispatches chat message lifecycle signal to ordered hooks.
    async function chatMessage(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "chat_message_dispatch",
            event_type: "chat.message",
            has_session_id: typeof input.sessionID === "string" && input.sessionID.trim().length > 0,
            hook_count: hooks.length,
        });
        for (const hook of hooks) {
            await hook.event("chat.message", {
                properties: {
                    ...input,
                },
                output,
                directory,
            });
        }
    }
    // Dispatches experimental chat transform lifecycle signal to ordered hooks.
    async function chatMessagesTransform(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "chat_messages_transform_dispatch",
            event_type: "experimental.chat.messages.transform",
            has_session_id: typeof input.sessionID === "string" && input.sessionID.trim().length > 0,
            hook_count: hooks.length,
        });
        for (const hook of hooks) {
            await hook.event("experimental.chat.messages.transform", {
                input,
                output,
                directory,
            });
        }
    }
    return {
        event,
        "tool.execute.before": toolExecuteBefore,
        "command.execute.before": commandExecuteBefore,
        "tool.execute.after": toolExecuteAfter,
        "chat.message": chatMessage,
        "experimental.chat.messages.transform": chatMessagesTransform,
    };
}
