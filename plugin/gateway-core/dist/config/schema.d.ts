export type CompletionMode = "promise" | "objective";
export type QualityProfile = "off" | "fast" | "strict";
export interface AutopilotLoopConfig {
    enabled: boolean;
    maxIterations: number;
    orphanMaxAgeHours: number;
    completionMode: CompletionMode;
    completionPromise: string;
}
export interface QualityConfig {
    profile: QualityProfile;
    ts: {
        lint: boolean;
        typecheck: boolean;
        tests: boolean;
    };
    py: {
        selftest: boolean;
    };
}
export interface ToolOutputTruncatorConfig {
    enabled: boolean;
    maxChars: number;
    maxLines: number;
    tools: string[];
}
export interface ContextWindowMonitorConfig {
    enabled: boolean;
    warningThreshold: number;
}
export interface PreemptiveCompactionConfig {
    enabled: boolean;
    warningThreshold: number;
}
export interface SessionRecoveryConfig {
    enabled: boolean;
    autoResume: boolean;
}
export interface DelegateTaskRetryConfig {
    enabled: boolean;
}
export interface StopContinuationGuardConfig {
    enabled: boolean;
}
export interface KeywordDetectorConfig {
    enabled: boolean;
}
export interface AutoSlashCommandConfig {
    enabled: boolean;
}
export interface RulesInjectorConfig {
    enabled: boolean;
}
export interface DirectoryAgentsInjectorConfig {
    enabled: boolean;
}
export interface DirectoryReadmeInjectorConfig {
    enabled: boolean;
}
export interface WriteExistingFileGuardConfig {
    enabled: boolean;
}
export interface SubagentQuestionBlockerConfig {
    enabled: boolean;
    sessionPatterns: string[];
}
export interface TasksTodowriteDisablerConfig {
    enabled: boolean;
}
export interface TaskResumeInfoConfig {
    enabled: boolean;
}
export interface EmptyTaskResponseDetectorConfig {
    enabled: boolean;
}
export interface CommentCheckerConfig {
    enabled: boolean;
}
export interface AgentUserReminderConfig {
    enabled: boolean;
}
export interface UnstableAgentBabysitterConfig {
    enabled: boolean;
    riskyPatterns: string[];
}
export interface QuestionLabelTruncatorConfig {
    enabled: boolean;
    maxLength: number;
}
export interface GatewayConfig {
    hooks: {
        enabled: boolean;
        disabled: string[];
        order: string[];
    };
    autopilotLoop: AutopilotLoopConfig;
    toolOutputTruncator: ToolOutputTruncatorConfig;
    contextWindowMonitor: ContextWindowMonitorConfig;
    preemptiveCompaction: PreemptiveCompactionConfig;
    sessionRecovery: SessionRecoveryConfig;
    delegateTaskRetry: DelegateTaskRetryConfig;
    stopContinuationGuard: StopContinuationGuardConfig;
    keywordDetector: KeywordDetectorConfig;
    autoSlashCommand: AutoSlashCommandConfig;
    rulesInjector: RulesInjectorConfig;
    directoryAgentsInjector: DirectoryAgentsInjectorConfig;
    directoryReadmeInjector: DirectoryReadmeInjectorConfig;
    writeExistingFileGuard: WriteExistingFileGuardConfig;
    subagentQuestionBlocker: SubagentQuestionBlockerConfig;
    tasksTodowriteDisabler: TasksTodowriteDisablerConfig;
    taskResumeInfo: TaskResumeInfoConfig;
    emptyTaskResponseDetector: EmptyTaskResponseDetectorConfig;
    commentChecker: CommentCheckerConfig;
    agentUserReminder: AgentUserReminderConfig;
    unstableAgentBabysitter: UnstableAgentBabysitterConfig;
    questionLabelTruncator: QuestionLabelTruncatorConfig;
    quality: QualityConfig;
}
export declare const DEFAULT_GATEWAY_CONFIG: GatewayConfig;
