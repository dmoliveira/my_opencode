// Defines safe gateway defaults for production usage.
export const DEFAULT_GATEWAY_CONFIG = {
    hooks: {
        enabled: true,
        disabled: [],
        order: [
            "autopilot-loop",
            "continuation",
            "tool-output-truncator",
            "context-window-monitor",
            "preemptive-compaction",
            "session-recovery",
            "delegate-task-retry",
            "stop-continuation-guard",
            "keyword-detector",
            "auto-slash-command",
            "rules-injector",
            "directory-agents-injector",
            "directory-readme-injector",
            "write-existing-file-guard",
            "subagent-question-blocker",
            "tasks-todowrite-disabler",
            "task-resume-info",
            "empty-task-response-detector",
            "comment-checker",
            "agent-user-reminder",
            "unstable-agent-babysitter",
            "question-label-truncator",
            "dangerous-command-guard",
            "safety",
        ],
    },
    autopilotLoop: {
        enabled: true,
        maxIterations: 0,
        orphanMaxAgeHours: 12,
        completionMode: "promise",
        completionPromise: "DONE",
    },
    toolOutputTruncator: {
        enabled: true,
        maxChars: 12000,
        maxLines: 220,
        tools: ["bash", "Bash", "read", "Read", "grep", "Grep", "webfetch", "WebFetch", "glob", "Glob"],
    },
    contextWindowMonitor: {
        enabled: true,
        warningThreshold: 0.7,
    },
    preemptiveCompaction: {
        enabled: true,
        warningThreshold: 0.78,
    },
    sessionRecovery: {
        enabled: true,
        autoResume: true,
    },
    delegateTaskRetry: {
        enabled: true,
    },
    stopContinuationGuard: {
        enabled: true,
    },
    keywordDetector: {
        enabled: true,
    },
    autoSlashCommand: {
        enabled: true,
    },
    rulesInjector: {
        enabled: true,
    },
    directoryAgentsInjector: {
        enabled: true,
    },
    directoryReadmeInjector: {
        enabled: true,
    },
    writeExistingFileGuard: {
        enabled: true,
    },
    subagentQuestionBlocker: {
        enabled: true,
        sessionPatterns: ["task-", "subagent"],
    },
    tasksTodowriteDisabler: {
        enabled: true,
    },
    taskResumeInfo: {
        enabled: true,
    },
    emptyTaskResponseDetector: {
        enabled: true,
    },
    commentChecker: {
        enabled: true,
    },
    agentUserReminder: {
        enabled: true,
    },
    unstableAgentBabysitter: {
        enabled: true,
        riskyPatterns: ["experimental", "preview", "unstable"],
    },
    questionLabelTruncator: {
        enabled: true,
        maxLength: 30,
    },
    dangerousCommandGuard: {
        enabled: true,
        blockedPatterns: [
            "\\brm\\s+-rf\\b",
            "\\bgit\\s+reset\\s+--hard\\b",
            "\\bgit\\s+checkout\\s+--\\b",
            "\\bgit\\s+clean\\s+-fdx\\b",
            "\\bgit\\s+push\\s+--force\\b",
            "curl\\s+[^|]+\\|\\s*bash",
        ],
    },
    quality: {
        profile: "fast",
        ts: {
            lint: true,
            typecheck: true,
            tests: false,
        },
        py: {
            selftest: true,
        },
    },
};
