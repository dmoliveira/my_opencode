export type CompletionMode = "promise" | "objective";
export type QualityProfile = "off" | "fast" | "strict";
export interface AutopilotLoopConfig {
    enabled: boolean;
    maxIterations: number;
    orphanMaxAgeHours: number;
    bootstrapFromRuntimeOnIdle: boolean;
    maxIgnoredCompletionCycles: number;
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
    reminderCooldownToolCalls: number;
    minTokenDeltaForReminder: number;
    defaultContextLimitTokens: number;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
}
export interface PreemptiveCompactionConfig {
    enabled: boolean;
    warningThreshold: number;
    compactionCooldownToolCalls: number;
    minTokenDeltaForCompaction: number;
    defaultContextLimitTokens: number;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
}
export interface GlobalProcessPressureConfig {
    enabled: boolean;
    checkCooldownToolCalls: number;
    reminderCooldownToolCalls: number;
    criticalReminderCooldownToolCalls: number;
    criticalEscalationWindowToolCalls: number;
    criticalPauseAfterEvents: number;
    criticalEscalationAfterEvents: number;
    warningContinueSessions: number;
    warningOpencodeProcesses: number;
    warningMaxRssMb: number;
    criticalMaxRssMb: number;
    autoPauseOnCritical: boolean;
    notifyOnCritical: boolean;
    guardMarkerMode: "nerd" | "plain" | "both";
    guardVerbosity: "minimal" | "normal" | "debug";
    maxSessionStateEntries: number;
}
export interface PressureEscalationGuardConfig {
    enabled: boolean;
    maxContinueBeforeBlock: number;
    blockedSubagentTypes: string[];
    allowPromptPatterns: string[];
}
export interface CompactionContextInjectorConfig {
    enabled: boolean;
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
export interface ThinkModeConfig {
    enabled: boolean;
}
export interface ThinkingBlockValidatorConfig {
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
    maxChars: number;
}
export interface DirectoryReadmeInjectorConfig {
    enabled: boolean;
    maxChars: number;
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
export interface TodoContinuationEnforcerConfig {
    enabled: boolean;
    cooldownMs: number;
    maxConsecutiveFailures: number;
}
export interface CompactionTodoPreserverConfig {
    enabled: boolean;
    maxChars: number;
}
export interface EmptyTaskResponseDetectorConfig {
    enabled: boolean;
}
export interface EditErrorRecoveryConfig {
    enabled: boolean;
}
export interface JsonErrorRecoveryConfig {
    enabled: boolean;
}
export interface ProviderTokenLimitRecoveryConfig {
    enabled: boolean;
    cooldownMs: number;
}
export interface HashlineReadEnhancerConfig {
    enabled: boolean;
}
export interface MaxStepRecoveryConfig {
    enabled: boolean;
}
export interface ModeTransitionReminderConfig {
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
export interface DangerousCommandGuardConfig {
    enabled: boolean;
    blockedPatterns: string[];
}
export interface SecretLeakGuardConfig {
    enabled: boolean;
    redactionToken: string;
    patterns: string[];
}
export interface WorkflowConformanceGuardConfig {
    enabled: boolean;
    protectedBranches: string[];
    blockEditsOnProtectedBranches: boolean;
}
export interface ScopeDriftGuardConfig {
    enabled: boolean;
    allowedPaths: string[];
    blockOnDrift: boolean;
}
export interface DoneProofEnforcerConfig {
    enabled: boolean;
    requiredMarkers: string[];
    requireLedgerEvidence: boolean;
    allowTextFallback: boolean;
}
export interface DependencyRiskGuardConfig {
    enabled: boolean;
    lockfilePatterns: string[];
    commandPatterns: string[];
}
export interface RetryBudgetGuardConfig {
    enabled: boolean;
    maxRetries: number;
}
export interface StaleLoopExpiryGuardConfig {
    enabled: boolean;
    maxAgeMinutes: number;
}
export interface ValidationEvidenceLedgerConfig {
    enabled: boolean;
}
export interface NoninteractiveShellGuardConfig {
    enabled: boolean;
    blockedPatterns: string[];
    injectEnvPrefix: boolean;
    envPrefixes: string[];
    prefixCommands: string[];
}
export interface DocsDriftGuardConfig {
    enabled: boolean;
    sourcePatterns: string[];
    docsPatterns: string[];
    blockOnDrift: boolean;
}
export interface HookTestParityGuardConfig {
    enabled: boolean;
    sourcePatterns: string[];
    testPatterns: string[];
    blockOnMismatch: boolean;
}
export interface ParallelOpportunityDetectorConfig {
    enabled: boolean;
}
export interface AgentReservationGuardConfig {
    enabled: boolean;
    enforce: boolean;
    reservationEnvKeys: string[];
}
export interface PrReadinessGuardConfig {
    enabled: boolean;
    requireCleanWorktree: boolean;
    requireValidationEvidence: boolean;
}
export interface BranchFreshnessGuardConfig {
    enabled: boolean;
    baseRef: string;
    maxBehind: number;
    enforceOnPrCreate: boolean;
    enforceOnPrMerge: boolean;
}
export interface MergeReadinessGuardConfig {
    enabled: boolean;
    requireDeleteBranch: boolean;
    requireStrategy: boolean;
    disallowAdminBypass: boolean;
}
export interface GhChecksMergeGuardConfig {
    enabled: boolean;
    blockDraft: boolean;
    requireApprovedReview: boolean;
    requirePassingChecks: boolean;
    blockedMergeStates: string[];
    failOpenOnError: boolean;
}
export interface SecretCommitGuardConfig {
    enabled: boolean;
    patterns: string[];
}
export interface PrBodyEvidenceGuardConfig {
    enabled: boolean;
    requireSummarySection: boolean;
    requireValidationSection: boolean;
    requireValidationEvidence: boolean;
    allowUninspectableBody: boolean;
}
export interface ParallelWriterConflictGuardConfig {
    enabled: boolean;
    maxConcurrentWriters: number;
    writerCountEnvKeys: string[];
    reservationPathsEnvKeys: string[];
    activeReservationPathsEnvKeys: string[];
    enforceReservationCoverage: boolean;
}
export interface PostMergeSyncGuardConfig {
    enabled: boolean;
    requireDeleteBranch: boolean;
    enforceMainSyncInline: boolean;
    reminderCommands: string[];
}
export interface ReadBudgetOptimizerConfig {
    enabled: boolean;
    smallReadLimit: number;
    maxConsecutiveSmallReads: number;
}
export interface SemanticOutputSummarizerConfig {
    enabled: boolean;
    minChars: number;
    minLines: number;
    maxSummaryLines: number;
}
export interface AdaptiveValidationSchedulerConfig {
    enabled: boolean;
    reminderEditThreshold: number;
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
    compactionContextInjector: CompactionContextInjectorConfig;
    globalProcessPressure: GlobalProcessPressureConfig;
    pressureEscalationGuard: PressureEscalationGuardConfig;
    sessionRecovery: SessionRecoveryConfig;
    delegateTaskRetry: DelegateTaskRetryConfig;
    validationEvidenceLedger: ValidationEvidenceLedgerConfig;
    parallelOpportunityDetector: ParallelOpportunityDetectorConfig;
    readBudgetOptimizer: ReadBudgetOptimizerConfig;
    adaptiveValidationScheduler: AdaptiveValidationSchedulerConfig;
    stopContinuationGuard: StopContinuationGuardConfig;
    keywordDetector: KeywordDetectorConfig;
    thinkMode: ThinkModeConfig;
    thinkingBlockValidator: ThinkingBlockValidatorConfig;
    autoSlashCommand: AutoSlashCommandConfig;
    rulesInjector: RulesInjectorConfig;
    directoryAgentsInjector: DirectoryAgentsInjectorConfig;
    directoryReadmeInjector: DirectoryReadmeInjectorConfig;
    noninteractiveShellGuard: NoninteractiveShellGuardConfig;
    writeExistingFileGuard: WriteExistingFileGuardConfig;
    agentReservationGuard: AgentReservationGuardConfig;
    subagentQuestionBlocker: SubagentQuestionBlockerConfig;
    tasksTodowriteDisabler: TasksTodowriteDisablerConfig;
    taskResumeInfo: TaskResumeInfoConfig;
    todoContinuationEnforcer: TodoContinuationEnforcerConfig;
    compactionTodoPreserver: CompactionTodoPreserverConfig;
    emptyTaskResponseDetector: EmptyTaskResponseDetectorConfig;
    editErrorRecovery: EditErrorRecoveryConfig;
    jsonErrorRecovery: JsonErrorRecoveryConfig;
    providerTokenLimitRecovery: ProviderTokenLimitRecoveryConfig;
    hashlineReadEnhancer: HashlineReadEnhancerConfig;
    maxStepRecovery: MaxStepRecoveryConfig;
    modeTransitionReminder: ModeTransitionReminderConfig;
    commentChecker: CommentCheckerConfig;
    agentUserReminder: AgentUserReminderConfig;
    unstableAgentBabysitter: UnstableAgentBabysitterConfig;
    questionLabelTruncator: QuestionLabelTruncatorConfig;
    semanticOutputSummarizer: SemanticOutputSummarizerConfig;
    dangerousCommandGuard: DangerousCommandGuardConfig;
    secretLeakGuard: SecretLeakGuardConfig;
    workflowConformanceGuard: WorkflowConformanceGuardConfig;
    scopeDriftGuard: ScopeDriftGuardConfig;
    doneProofEnforcer: DoneProofEnforcerConfig;
    dependencyRiskGuard: DependencyRiskGuardConfig;
    docsDriftGuard: DocsDriftGuardConfig;
    hookTestParityGuard: HookTestParityGuardConfig;
    retryBudgetGuard: RetryBudgetGuardConfig;
    staleLoopExpiryGuard: StaleLoopExpiryGuardConfig;
    branchFreshnessGuard: BranchFreshnessGuardConfig;
    prReadinessGuard: PrReadinessGuardConfig;
    prBodyEvidenceGuard: PrBodyEvidenceGuardConfig;
    mergeReadinessGuard: MergeReadinessGuardConfig;
    ghChecksMergeGuard: GhChecksMergeGuardConfig;
    postMergeSyncGuard: PostMergeSyncGuardConfig;
    parallelWriterConflictGuard: ParallelWriterConflictGuardConfig;
    secretCommitGuard: SecretCommitGuardConfig;
    quality: QualityConfig;
}
export declare const DEFAULT_GATEWAY_CONFIG: GatewayConfig;
