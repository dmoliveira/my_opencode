import { loadGatewayConfig } from "./config/load.js";
import { writeGatewayEventAudit } from "./audit/event-audit.js";
import { createAutopilotLoopHook } from "./hooks/autopilot-loop/index.js";
import { createAutoSlashCommandHook } from "./hooks/auto-slash-command/index.js";
import { createAgentUserReminderHook } from "./hooks/agent-user-reminder/index.js";
import { createCommentCheckerHook } from "./hooks/comment-checker/index.js";
import { createContinuationHook } from "./hooks/continuation/index.js";
import { createContextWindowMonitorHook } from "./hooks/context-window-monitor/index.js";
import { createDelegateTaskRetryHook } from "./hooks/delegate-task-retry/index.js";
import { createDangerousCommandGuardHook } from "./hooks/dangerous-command-guard/index.js";
import { createEmptyTaskResponseDetectorHook } from "./hooks/empty-task-response-detector/index.js";
import { createDirectoryAgentsInjectorHook } from "./hooks/directory-agents-injector/index.js";
import { createDirectoryReadmeInjectorHook } from "./hooks/directory-readme-injector/index.js";
import { createKeywordDetectorHook } from "./hooks/keyword-detector/index.js";
import { createPreemptiveCompactionHook } from "./hooks/preemptive-compaction/index.js";
import { createQuestionLabelTruncatorHook } from "./hooks/question-label-truncator/index.js";
import { createRulesInjectorHook } from "./hooks/rules-injector/index.js";
import { createSecretLeakGuardHook } from "./hooks/secret-leak-guard/index.js";
import { createSafetyHook } from "./hooks/safety/index.js";
import { createSessionRecoveryHook } from "./hooks/session-recovery/index.js";
import { createStopContinuationGuardHook } from "./hooks/stop-continuation-guard/index.js";
import { createSubagentQuestionBlockerHook } from "./hooks/subagent-question-blocker/index.js";
import { createTasksTodowriteDisablerHook } from "./hooks/tasks-todowrite-disabler/index.js";
import { createTaskResumeInfoHook } from "./hooks/task-resume-info/index.js";
import { createToolOutputTruncatorHook } from "./hooks/tool-output-truncator/index.js";
import { createUnstableAgentBabysitterHook } from "./hooks/unstable-agent-babysitter/index.js";
import { createWriteExistingFileGuardHook } from "./hooks/write-existing-file-guard/index.js";
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
        }),
        createContinuationHook({
            directory,
            client: ctx.client,
            stopGuard,
            keywordDetector,
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
        createContextWindowMonitorHook({
            directory,
            client: ctx.client,
            enabled: cfg.contextWindowMonitor.enabled,
            warningThreshold: cfg.contextWindowMonitor.warningThreshold,
        }),
        createPreemptiveCompactionHook({
            directory,
            client: ctx.client,
            enabled: cfg.preemptiveCompaction.enabled,
            warningThreshold: cfg.preemptiveCompaction.warningThreshold,
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
        stopGuard,
        keywordDetector,
        createAutoSlashCommandHook({
            directory,
            enabled: cfg.autoSlashCommand.enabled,
        }),
        createRulesInjectorHook({
            directory,
            enabled: cfg.rulesInjector.enabled,
        }),
        createDirectoryAgentsInjectorHook({
            directory,
            enabled: cfg.directoryAgentsInjector.enabled,
        }),
        createDirectoryReadmeInjectorHook({
            directory,
            enabled: cfg.directoryReadmeInjector.enabled,
        }),
        createWriteExistingFileGuardHook({
            directory,
            enabled: cfg.writeExistingFileGuard.enabled,
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
        createEmptyTaskResponseDetectorHook({
            enabled: cfg.emptyTaskResponseDetector.enabled,
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
    return {
        event,
        "tool.execute.before": toolExecuteBefore,
        "tool.execute.after": toolExecuteAfter,
        "chat.message": chatMessage,
    };
}
