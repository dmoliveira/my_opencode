export type ProviderRetryReasonCode =
  | "free_usage_exhausted"
  | "too_many_requests"
  | "rate_limited"
  | "provider_overloaded"

export interface ProviderRetryReason {
  code: ProviderRetryReasonCode
  message: string
}

// Returns canonical provider retry reason from serialized error text.
export function classifyProviderRetryReason(text: string): ProviderRetryReason | null {
  if (/freeusagelimiterror/i.test(text) || /free usage exceeded/i.test(text) || /insufficient.*credits/i.test(text)) {
    return {
      code: "free_usage_exhausted",
      message: "Free usage exceeded, add credits https://opencode.ai/zen",
    }
  }
  if (/too_many_requests/i.test(text) || /too many requests/i.test(text)) {
    return {
      code: "too_many_requests",
      message: "Too Many Requests",
    }
  }
  if (/rate[_ -]?limit(ed)?/i.test(text)) {
    return {
      code: "rate_limited",
      message: "Rate Limited",
    }
  }
  if (/overloaded/i.test(text) || /code.*(exhausted|unavailable)/i.test(text) || /provider is overloaded/i.test(text)) {
    return {
      code: "provider_overloaded",
      message: "Provider is overloaded",
    }
  }
  return null
}
