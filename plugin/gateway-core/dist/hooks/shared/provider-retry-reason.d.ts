export type ProviderRetryReasonCode = "free_usage_exhausted" | "too_many_requests" | "rate_limited" | "provider_overloaded";
export interface ProviderRetryReason {
    code: ProviderRetryReasonCode;
    message: string;
}
export declare function classifyProviderRetryReason(text: string): ProviderRetryReason | null;
export declare function isContextOverflowNonRetryable(text: string): boolean;
