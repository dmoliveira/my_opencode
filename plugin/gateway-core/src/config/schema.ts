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
