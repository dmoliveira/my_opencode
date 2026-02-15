// Declares completion mode options for gateway autopilot loop.
export type CompletionMode = "promise" | "objective"

// Declares ordered quality profile levels.
export type QualityProfile = "off" | "fast" | "strict"

// Declares loop-related configuration knobs.
export interface AutopilotLoopConfig {
  enabled: boolean
  maxIterations: number
  orphanMaxAgeHours: number
  completionMode: CompletionMode
  completionPromise: string
}

// Declares quality toggle settings for plugin-side checks.
export interface QualityConfig {
  profile: QualityProfile
  ts: {
    lint: boolean
    typecheck: boolean
    tests: boolean
  }
  py: {
    selftest: boolean
  }
}

// Declares output truncation guardrail settings for large tool output.
export interface ToolOutputTruncatorConfig {
  enabled: boolean
  maxChars: number
  maxLines: number
  tools: string[]
}

// Declares context window monitor settings for token pressure warnings.
export interface ContextWindowMonitorConfig {
  enabled: boolean
  warningThreshold: number
}

// Declares preemptive compaction settings for high token pressure sessions.
export interface PreemptiveCompactionConfig {
  enabled: boolean
  warningThreshold: number
}

// Declares session recovery settings for event-driven auto-resume attempts.
export interface SessionRecoveryConfig {
  enabled: boolean
  autoResume: boolean
}

// Declares retry guidance settings for failed delegated task calls.
export interface DelegateTaskRetryConfig {
  enabled: boolean
}

// Declares continuation stop guard settings for loop stop persistence.
export interface StopContinuationGuardConfig {
  enabled: boolean
}

// Declares keyword mode detection settings for chat-intent hints.
export interface KeywordDetectorConfig {
  enabled: boolean
}

// Declares auto slash routing settings for command-like natural prompts.
export interface AutoSlashCommandConfig {
  enabled: boolean
}

// Declares runtime rule injection settings for tool lifecycle hooks.
export interface RulesInjectorConfig {
  enabled: boolean
}

// Declares local AGENTS.md injector settings.
export interface DirectoryAgentsInjectorConfig {
  enabled: boolean
}

// Declares local README injector settings.
export interface DirectoryReadmeInjectorConfig {
  enabled: boolean
}

// Declares write guard settings to prevent overwriting existing files.
export interface WriteExistingFileGuardConfig {
  enabled: boolean
}

// Declares subagent question blocking settings.
export interface SubagentQuestionBlockerConfig {
  enabled: boolean
  sessionPatterns: string[]
}

// Declares task/todowrite disabler settings to avoid tracker conflicts.
export interface TasksTodowriteDisablerConfig {
  enabled: boolean
}

// Declares resume hint injection settings for task outputs.
export interface TaskResumeInfoConfig {
  enabled: boolean
}

// Declares empty task response detector settings.
export interface EmptyTaskResponseDetectorConfig {
  enabled: boolean
}

// Declares comment quality checker settings.
export interface CommentCheckerConfig {
  enabled: boolean
}

// Declares specialist-agent reminder settings.
export interface AgentUserReminderConfig {
  enabled: boolean
}

// Declares unstable agent babysitter settings.
export interface UnstableAgentBabysitterConfig {
  enabled: boolean
  riskyPatterns: string[]
}

// Declares question label truncation settings for safe option labels.
export interface QuestionLabelTruncatorConfig {
  enabled: boolean
  maxLength: number
}

// Declares dangerous command guard settings for destructive shell commands.
export interface DangerousCommandGuardConfig {
  enabled: boolean
  blockedPatterns: string[]
}

// Declares secret leak guard settings for output redaction.
export interface SecretLeakGuardConfig {
  enabled: boolean
  redactionToken: string
  patterns: string[]
}

// Declares workflow conformance guard settings.
export interface WorkflowConformanceGuardConfig {
  enabled: boolean
  protectedBranches: string[]
}

// Declares scope drift guard settings for file edit boundaries.
export interface ScopeDriftGuardConfig {
  enabled: boolean
  allowedPaths: string[]
  blockOnDrift: boolean
}

// Declares done proof enforcer settings for completion evidence checks.
export interface DoneProofEnforcerConfig {
  enabled: boolean
  requiredMarkers: string[]
}

// Declares dependency risk guard settings.
export interface DependencyRiskGuardConfig {
  enabled: boolean
  lockfilePatterns: string[]
}

// Declares retry budget guard settings.
export interface RetryBudgetGuardConfig {
  enabled: boolean
  maxRetries: number
}

// Declares stale loop expiry guard settings.
export interface StaleLoopExpiryGuardConfig {
  enabled: boolean
  maxAgeMinutes: number
}

// Declares top-level gateway plugin configuration.
export interface GatewayConfig {
  hooks: {
    enabled: boolean
    disabled: string[]
    order: string[]
  }
  autopilotLoop: AutopilotLoopConfig
  toolOutputTruncator: ToolOutputTruncatorConfig
  contextWindowMonitor: ContextWindowMonitorConfig
  preemptiveCompaction: PreemptiveCompactionConfig
  sessionRecovery: SessionRecoveryConfig
  delegateTaskRetry: DelegateTaskRetryConfig
  stopContinuationGuard: StopContinuationGuardConfig
  keywordDetector: KeywordDetectorConfig
  autoSlashCommand: AutoSlashCommandConfig
  rulesInjector: RulesInjectorConfig
  directoryAgentsInjector: DirectoryAgentsInjectorConfig
  directoryReadmeInjector: DirectoryReadmeInjectorConfig
  writeExistingFileGuard: WriteExistingFileGuardConfig
  subagentQuestionBlocker: SubagentQuestionBlockerConfig
  tasksTodowriteDisabler: TasksTodowriteDisablerConfig
  taskResumeInfo: TaskResumeInfoConfig
  emptyTaskResponseDetector: EmptyTaskResponseDetectorConfig
  commentChecker: CommentCheckerConfig
  agentUserReminder: AgentUserReminderConfig
  unstableAgentBabysitter: UnstableAgentBabysitterConfig
  questionLabelTruncator: QuestionLabelTruncatorConfig
  dangerousCommandGuard: DangerousCommandGuardConfig
  secretLeakGuard: SecretLeakGuardConfig
  workflowConformanceGuard: WorkflowConformanceGuardConfig
  scopeDriftGuard: ScopeDriftGuardConfig
  doneProofEnforcer: DoneProofEnforcerConfig
  dependencyRiskGuard: DependencyRiskGuardConfig
  retryBudgetGuard: RetryBudgetGuardConfig
  staleLoopExpiryGuard: StaleLoopExpiryGuardConfig
  quality: QualityConfig
}

// Defines safe gateway defaults for production usage.
export const DEFAULT_GATEWAY_CONFIG: GatewayConfig = {
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
}
