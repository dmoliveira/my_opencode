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
            "secret-leak-guard",
            "workflow-conformance-guard",
            "scope-drift-guard",
            "done-proof-enforcer",
            "dependency-risk-guard",
            "retry-budget-guard",
            "stale-loop-expiry-guard",
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
    secretLeakGuard: {
        enabled: true,
        redactionToken: "[REDACTED_SECRET]",
        patterns: [
            "sk-[A-Za-z0-9]{20,}",
            "ghp_[A-Za-z0-9]{20,}",
            "AIza[0-9A-Za-z\\-_]{20,}",
            "-----BEGIN (RSA|EC|OPENSSH|DSA|PRIVATE) KEY-----",
            "(?i)(api[_-]?key|token|secret|password)\\s*[:=]\\s*['\"]?[A-Za-z0-9_\\-]{12,}",
        ],
    },
    workflowConformanceGuard: {
        enabled: true,
        protectedBranches: ["main", "master"],
    },
    scopeDriftGuard: {
        enabled: false,
        allowedPaths: [],
        blockOnDrift: true,
    },
    doneProofEnforcer: {
        enabled: true,
        requiredMarkers: ["validation", "test", "lint"],
    },
    dependencyRiskGuard: {
        enabled: true,
        lockfilePatterns: ["package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock", "Cargo.lock"],
    },
    retryBudgetGuard: {
        enabled: true,
        maxRetries: 3,
    },
    staleLoopExpiryGuard: {
        enabled: true,
        maxAgeMinutes: 120,
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
