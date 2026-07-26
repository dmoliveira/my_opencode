export type SecretRedactionErrorCode = "invalid_pattern" | "immutable_match" | "cycle_detected" | "depth_limit" | "node_limit" | "text_limit" | "mutation_failed" | "unexpected_failure";
export declare class SecretRedactionError extends Error {
    readonly code: SecretRedactionErrorCode;
    constructor(code: SecretRedactionErrorCode, detail?: string);
}
export interface SecretRedactionLimits {
    maxDepth: number;
    maxNodes: number;
    maxChars: number;
}
export interface SecretRedactionStats {
    matches: number;
    redactedFields: number;
    scannedChars: number;
    scannedNodes: number;
}
export interface SecretRedactor {
    redactText(text: string): {
        text: string;
        stats: SecretRedactionStats;
    };
    redactMutableValue(value: unknown): SecretRedactionStats;
    redactProviderMessages(messages: unknown): SecretRedactionStats;
    redactProviderSystem(system: unknown): SecretRedactionStats;
}
export declare function createSecretRedactor(options: {
    patterns: string[];
    redactionToken: string;
    limits: SecretRedactionLimits;
}): SecretRedactor;
