export declare function resolvePromptCacheScopeIdentity(directory: string): string;
export interface StablePromptCacheKeyInput {
    scopeIdentity: string;
    providerID: string;
    modelID: string;
    agent: string;
    sessionID: string;
    shardCount: number;
}
export interface StablePromptCacheKeyResult {
    key: string;
    shard: number;
    shardCount: number;
}
export declare function stablePromptCacheKey(input: StablePromptCacheKeyInput): StablePromptCacheKeyResult | null;
export interface CacheableSystemPrefixObservation {
    sha256: string;
    entryCount: number;
    charCount: number;
    sessionMarkerPresent: boolean;
}
export declare function exactPromptFingerprint(entries: string[]): string;
export declare function cacheableSystemPrefixObservation(system: string[]): CacheableSystemPrefixObservation;
