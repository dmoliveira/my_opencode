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
    quality: QualityConfig;
}
export declare const DEFAULT_GATEWAY_CONFIG: GatewayConfig;
