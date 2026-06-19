export interface ProviderHeaderTimeoutState {
    sessionId: string;
    count: number;
    lastObservedAt: number;
}
export declare const PROVIDER_HEADER_TIMEOUT_DOWNGRADE_THRESHOLD = 2;
export declare const PROVIDER_HEADER_TIMEOUT_STATE_TTL_MS: number;
export declare function resetProviderHeaderTimeoutState(sessionId: string): void;
export declare function recordProviderHeaderTimeout(sessionId: string): ProviderHeaderTimeoutState | null;
export declare function getProviderHeaderTimeoutState(sessionId: string): ProviderHeaderTimeoutState | null;
