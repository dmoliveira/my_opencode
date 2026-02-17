const TRUNCATION_SUFFIX = "\n\n[Content truncated due to context window limit]"

export const DEFAULT_INJECTED_TEXT_MAX_CHARS = 12_000

export interface TruncatedTextResult {
  text: string
  truncated: boolean
  originalLength: number
}

// Truncates large injected text blocks and appends a marker.
export function truncateInjectedText(text: string, maxChars: number): TruncatedTextResult {
  const normalized = typeof text === "string" ? text.trim() : ""
  const safeLimit = Number.isFinite(maxChars) && maxChars > 0 ? Math.floor(maxChars) : DEFAULT_INJECTED_TEXT_MAX_CHARS
  if (normalized.length <= safeLimit) {
    return {
      text: normalized,
      truncated: false,
      originalLength: normalized.length,
    }
  }

  if (safeLimit <= TRUNCATION_SUFFIX.length) {
    return {
      text: TRUNCATION_SUFFIX.slice(0, safeLimit),
      truncated: true,
      originalLength: normalized.length,
    }
  }

  const bodyLimit = Math.max(0, safeLimit - TRUNCATION_SUFFIX.length)
  const head = normalized.slice(0, bodyLimit).trimEnd()
  return {
    text: `${head}${TRUNCATION_SUFFIX}`,
    truncated: true,
    originalLength: normalized.length,
  }
}
