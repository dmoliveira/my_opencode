// Declares completion mode options for gateway autopilot loop.
export type CompletionMode = "promise" | "objective"

// Declares ordered quality profile levels.
export type QualityProfile = "off" | "fast" | "strict"

// Declares loop-related configuration knobs.
export interface AutopilotLoopConfig {
  enabled: boolean
  maxIterations: number
  orphanMaxAgeHours: number
  bootstrapFromRuntimeOnIdle: boolean
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
  blockEditsOnProtectedBranches: boolean
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
  requireLedgerEvidence: boolean
  allowTextFallback: boolean
}

// Declares dependency risk guard settings.
export interface DependencyRiskGuardConfig {
  enabled: boolean
  lockfilePatterns: string[]
  commandPatterns: string[]
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

// Declares validation evidence ledger settings.
export interface ValidationEvidenceLedgerConfig {
  enabled: boolean
}

// Declares non-interactive shell guard settings.
export interface NoninteractiveShellGuardConfig {
  enabled: boolean
  blockedPatterns: string[]
}

// Declares docs drift guard settings.
export interface DocsDriftGuardConfig {
  enabled: boolean
  sourcePatterns: string[]
  docsPatterns: string[]
  blockOnDrift: boolean
}

// Declares hook-test parity guard settings.
export interface HookTestParityGuardConfig {
  enabled: boolean
  sourcePatterns: string[]
  testPatterns: string[]
  blockOnMismatch: boolean
}

// Declares parallel opportunity detector settings.
export interface ParallelOpportunityDetectorConfig {
  enabled: boolean
}

// Declares agent reservation guard settings.
export interface AgentReservationGuardConfig {
  enabled: boolean
  enforce: boolean
  reservationEnvKeys: string[]
}

// Declares PR readiness guard settings.
export interface PrReadinessGuardConfig {
  enabled: boolean
  requireCleanWorktree: boolean
  requireValidationEvidence: boolean
}

// Declares merge readiness guard settings.
export interface MergeReadinessGuardConfig {
  enabled: boolean
  requireDeleteBranch: boolean
  requireStrategy: boolean
  disallowAdminBypass: boolean
}

// Declares read budget optimizer settings.
export interface ReadBudgetOptimizerConfig {
  enabled: boolean
  smallReadLimit: number
  maxConsecutiveSmallReads: number
}

// Declares semantic output summarizer settings.
export interface SemanticOutputSummarizerConfig {
  enabled: boolean
  minChars: number
  minLines: number
  maxSummaryLines: number
}

// Declares adaptive validation scheduler settings.
export interface AdaptiveValidationSchedulerConfig {
  enabled: boolean
  reminderEditThreshold: number
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
  validationEvidenceLedger: ValidationEvidenceLedgerConfig
  parallelOpportunityDetector: ParallelOpportunityDetectorConfig
  readBudgetOptimizer: ReadBudgetOptimizerConfig
  adaptiveValidationScheduler: AdaptiveValidationSchedulerConfig
  stopContinuationGuard: StopContinuationGuardConfig
  keywordDetector: KeywordDetectorConfig
  autoSlashCommand: AutoSlashCommandConfig
  rulesInjector: RulesInjectorConfig
  directoryAgentsInjector: DirectoryAgentsInjectorConfig
  directoryReadmeInjector: DirectoryReadmeInjectorConfig
  noninteractiveShellGuard: NoninteractiveShellGuardConfig
  writeExistingFileGuard: WriteExistingFileGuardConfig
  agentReservationGuard: AgentReservationGuardConfig
  subagentQuestionBlocker: SubagentQuestionBlockerConfig
  tasksTodowriteDisabler: TasksTodowriteDisablerConfig
  taskResumeInfo: TaskResumeInfoConfig
  emptyTaskResponseDetector: EmptyTaskResponseDetectorConfig
  commentChecker: CommentCheckerConfig
  agentUserReminder: AgentUserReminderConfig
  unstableAgentBabysitter: UnstableAgentBabysitterConfig
  questionLabelTruncator: QuestionLabelTruncatorConfig
  semanticOutputSummarizer: SemanticOutputSummarizerConfig
  dangerousCommandGuard: DangerousCommandGuardConfig
  secretLeakGuard: SecretLeakGuardConfig
  workflowConformanceGuard: WorkflowConformanceGuardConfig
  scopeDriftGuard: ScopeDriftGuardConfig
  doneProofEnforcer: DoneProofEnforcerConfig
  dependencyRiskGuard: DependencyRiskGuardConfig
  docsDriftGuard: DocsDriftGuardConfig
  hookTestParityGuard: HookTestParityGuardConfig
  retryBudgetGuard: RetryBudgetGuardConfig
  staleLoopExpiryGuard: StaleLoopExpiryGuardConfig
  prReadinessGuard: PrReadinessGuardConfig
  mergeReadinessGuard: MergeReadinessGuardConfig
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
      "semantic-output-summarizer",
      "context-window-monitor",
      "preemptive-compaction",
      "session-recovery",
      "delegate-task-retry",
      "validation-evidence-ledger",
      "parallel-opportunity-detector",
      "read-budget-optimizer",
      "adaptive-validation-scheduler",
      "stop-continuation-guard",
      "keyword-detector",
      "auto-slash-command",
      "rules-injector",
      "directory-agents-injector",
      "directory-readme-injector",
      "noninteractive-shell-guard",
      "write-existing-file-guard",
      "agent-reservation-guard",
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
      "docs-drift-guard",
      "hook-test-parity-guard",
      "retry-budget-guard",
      "stale-loop-expiry-guard",
      "pr-readiness-guard",
      "merge-readiness-guard",
      "safety",
    ],
  },
  autopilotLoop: {
    enabled: true,
    maxIterations: 0,
    orphanMaxAgeHours: 12,
    bootstrapFromRuntimeOnIdle: false,
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
  validationEvidenceLedger: {
    enabled: true,
  },
  parallelOpportunityDetector: {
    enabled: true,
  },
  readBudgetOptimizer: {
    enabled: true,
    smallReadLimit: 80,
    maxConsecutiveSmallReads: 3,
  },
  adaptiveValidationScheduler: {
    enabled: true,
    reminderEditThreshold: 3,
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
  noninteractiveShellGuard: {
    enabled: true,
    blockedPatterns: [
      "\\b(vim|vi|nano|emacs|less|more|man)\\b",
      "\\bgit\\s+add\\s+-p\\b",
      "\\bgit\\s+rebase\\s+-i\\b",
    ],
  },
  writeExistingFileGuard: {
    enabled: true,
  },
  agentReservationGuard: {
    enabled: true,
    enforce: false,
    reservationEnvKeys: ["AGENTMAIL_RESERVATION_ACTIVE", "MY_OPENCODE_FILE_RESERVATION_ACTIVE"],
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
  semanticOutputSummarizer: {
    enabled: true,
    minChars: 20000,
    minLines: 400,
    maxSummaryLines: 8,
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
    blockEditsOnProtectedBranches: true,
  },
  scopeDriftGuard: {
    enabled: false,
    allowedPaths: [],
    blockOnDrift: true,
  },
  doneProofEnforcer: {
    enabled: true,
    requiredMarkers: ["validation", "test", "lint"],
    requireLedgerEvidence: true,
    allowTextFallback: true,
  },
  dependencyRiskGuard: {
    enabled: true,
    lockfilePatterns: ["package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock", "Cargo.lock"],
    commandPatterns: [
      "\\bnpm\\s+(install|update|uninstall|audit\\s+fix)\\b",
      "\\bpnpm\\s+(install|update|remove|audit)\\b",
      "\\byarn\\s+(add|remove|upgrade|install)\\b",
      "\\bbun\\s+add\\b",
      "\\buv\\s+(add|remove|sync)\\b",
      "\\bcargo\\s+(add|remove|update)\\b",
    ],
  },
  docsDriftGuard: {
    enabled: true,
    sourcePatterns: ["plugin/gateway-core/src/**", "plugin/gateway-core/package.json"],
    docsPatterns: ["README.md", "docs/**", "plugin/gateway-core/**/*.md"],
    blockOnDrift: false,
  },
  hookTestParityGuard: {
    enabled: true,
    sourcePatterns: ["plugin/gateway-core/src/hooks/**/*.ts"],
    testPatterns: ["plugin/gateway-core/test/*-hook.test.mjs"],
    blockOnMismatch: true,
  },
  retryBudgetGuard: {
    enabled: true,
    maxRetries: 3,
  },
  staleLoopExpiryGuard: {
    enabled: true,
    maxAgeMinutes: 120,
  },
  prReadinessGuard: {
    enabled: true,
    requireCleanWorktree: true,
    requireValidationEvidence: true,
  },
  mergeReadinessGuard: {
    enabled: true,
    requireDeleteBranch: true,
    requireStrategy: true,
    disallowAdminBypass: true,
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
