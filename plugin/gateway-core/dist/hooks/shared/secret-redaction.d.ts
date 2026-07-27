export type SecretRedactionErrorCode = "invalid_pattern" | "immutable_match" | "cycle_detected" | "depth_limit" | "node_limit" | "text_limit" | "mutation_failed" | "unexpected_failure";
export type SecretRedactionMatchTarget = "key" | "value";
export type SecretRedactionLocationCode = "provider_metadata_openai_item_id" | "provider_metadata_openai_other" | "immutable_protocol_field" | "unknown_field";
interface SecretRedactionMatchDiagnostics {
    matchTarget: SecretRedactionMatchTarget;
    patternIndex: number;
    locationCode: SecretRedactionLocationCode;
}
export declare class SecretRedactionError extends Error {
    readonly code: SecretRedactionErrorCode;
    readonly matchTarget: SecretRedactionMatchTarget | null;
    readonly patternIndex: number | null;
    readonly locationCode: SecretRedactionLocationCode | null;
    constructor(code: SecretRedactionErrorCode, detail?: string, diagnostics?: SecretRedactionMatchDiagnostics | null);
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
export {};
