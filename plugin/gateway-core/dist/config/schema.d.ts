export type CompletionMode = "promise" | "objective";
export type QualityProfile = "off" | "fast" | "strict";
export interface AutopilotLoopConfig {
    enabled: boolean;
    maxIterations: number;
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
export interface GatewayConfig {
    hooks: {
        enabled: boolean;
        disabled: string[];
        order: string[];
    };
    autopilotLoop: AutopilotLoopConfig;
    quality: QualityConfig;
}
export declare const DEFAULT_GATEWAY_CONFIG: GatewayConfig;
