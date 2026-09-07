export type SecretRedactionErrorCode = "invalid_pattern" | "invalid_redaction_token" | "immutable_match" | "cycle_detected" | "depth_limit" | "node_limit" | "text_limit" | "malformed_provider_object" | "malformed_provider_metadata" | "mutation_failed" | "regex_timeout" | "regex_capacity" | "regex_batch_limit" | "unexpected_failure";
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
export interface ProviderSecretRedactionLimits {
    maxMessages: number;
    maxNodes: number;
    maxChars: number;
    maxMessageChars: number;
}
export interface SecretRedactionStats {
    matches: number;
    redactedFields: number;
    scannedChars: number;
    scannedNodes: number;
    omittedOpaqueAttachmentMatches: number;
}
interface PatternWorkerLike {
    postMessage(message: unknown): void;
    once(event: "message", listener: (message: unknown) => void): this;
    once(event: "error", listener: (error: unknown) => void): this;
    once(event: "exit", listener: (code: number) => void): this;
    terminate(): Promise<number>;
}
export type SecretRedactionWorkerFactory = (url: URL) => PatternWorkerLike;
export interface SecretRedactor {
    readonly usesIsolatedPatterns: boolean;
    redactText(text: string): {
        text: string;
        stats: SecretRedactionStats;
    };
    redactMutableValue(value: unknown): SecretRedactionStats;
    redactProviderMessages(messages: unknown): SecretRedactionStats;
    redactProviderSystem(system: unknown): SecretRedactionStats;
    redactTextAsync(text: string): Promise<{
        text: string;
        stats: SecretRedactionStats;
    }>;
    redactMutableValueAsync(value: unknown): Promise<SecretRedactionStats>;
    redactProviderMessagesAsync(messages: unknown): Promise<SecretRedactionStats>;
    redactProviderSystemAsync(system: unknown): Promise<SecretRedactionStats>;
}
export declare function createSecretRedactor(options: {
    patterns: string[];
    redactionToken: string;
    limits: SecretRedactionLimits;
    providerLimits?: ProviderSecretRedactionLimits;
    omittableOpaqueAttachmentPatternIndex?: number | null;
    isolateCustomPatterns?: boolean;
    workerFactory?: SecretRedactionWorkerFactory;
    workerTimeoutMs?: number;
}): SecretRedactor;
export {};
