export type ProviderRetryReasonCode = "free_usage_exhausted" | "too_many_requests" | "rate_limited" | "provider_overloaded" | "provider_header_timeout";
export interface ProviderRetryReason {
    code: ProviderRetryReasonCode;
    message: string;
}
export declare function isProviderHeaderTimeout(text: string): boolean;
export declare function classifyProviderRetryReason(text: string): ProviderRetryReason | null;
export declare function isContextOverflowNonRetryable(text: string): boolean;
