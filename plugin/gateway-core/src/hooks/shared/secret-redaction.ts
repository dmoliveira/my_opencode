export type SecretRedactionErrorCode =
  | "invalid_pattern"
  | "immutable_match"
  | "cycle_detected"
  | "depth_limit"
  | "node_limit"
  | "text_limit"
  | "mutation_failed"
  | "unexpected_failure"

export class SecretRedactionError extends Error {
  readonly code: SecretRedactionErrorCode

  constructor(code: SecretRedactionErrorCode, detail = "") {
    super(`secret redaction blocked: ${code}${detail ? ` (${detail})` : ""}`)
    this.name = "SecretRedactionError"
    this.code = code
  }
}

export interface SecretRedactionLimits {
  maxDepth: number
  maxNodes: number
  maxChars: number
}

export interface SecretRedactionStats {
  matches: number
  redactedFields: number
  scannedChars: number
  scannedNodes: number
}

interface CompiledPattern {
  source: string
  flags: string
}

type VisitMode = "redact" | "scan"

const MUTABLE_CONTENT_KEYS = new Set([
  "after",
  "before",
  "body",
  "content",
  "description",
  "diff",
  "diffs",
  "error",
  "input",
  "message",
  "output",
  "prompt",
  "reasoning",
  "source",
  "summary",
  "system",
  "text",
  "title",
])

const IMMUTABLE_PROTOCOL_KEYS = new Set([
  "callID",
  "filename",
  "id",
  "messageID",
  "metadata",
  "mime",
  "modelID",
  "path",
  "providerID",
  "role",
  "sessionID",
  "tool",
  "type",
  "url",
])

function normalizedLimit(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback
}

function compilePattern(rawPattern: string, index: number): CompiledPattern {
  let source = rawPattern
  const flags = new Set(["g"])
  while (true) {
    const match = source.match(/^\(\?([ims]+)\)/)
    if (!match) {
      break
    }
    for (const flag of match[1] ?? "") {
      flags.add(flag)
    }
    source = source.slice(match[0].length)
  }
  const normalizedFlags = ["g", "i", "m", "s"].filter((flag) => flags.has(flag)).join("")
  try {
    // Compile once here to reject malformed configured patterns without exposing them.
    new RegExp(source, normalizedFlags)
  } catch {
    throw new SecretRedactionError("invalid_pattern", `index=${index}`)
  }
  return { source, flags: normalizedFlags }
}

function emptyStats(): SecretRedactionStats {
  return { matches: 0, redactedFields: 0, scannedChars: 0, scannedNodes: 0 }
}

export interface SecretRedactor {
  redactText(text: string): { text: string; stats: SecretRedactionStats }
  redactMutableValue(value: unknown): SecretRedactionStats
  redactProviderMessages(messages: unknown): SecretRedactionStats
  redactProviderSystem(system: unknown): SecretRedactionStats
}

export function createSecretRedactor(options: {
  patterns: string[]
  redactionToken: string
  limits: SecretRedactionLimits
}): SecretRedactor {
  const patterns = options.patterns.map(compilePattern)
  const limits = {
    maxDepth: normalizedLimit(options.limits.maxDepth, 12),
    maxNodes: normalizedLimit(options.limits.maxNodes, 20_000),
    maxChars: normalizedLimit(options.limits.maxChars, 2 * 1024 * 1024),
  }

  function applyPatterns(text: string, stats: SecretRedactionStats): string {
    stats.scannedChars += text.length
    if (stats.scannedChars > limits.maxChars) {
      throw new SecretRedactionError("text_limit")
    }
    let next = text
    for (const pattern of patterns) {
      const regex = new RegExp(pattern.source, pattern.flags)
      next = next.replace(regex, () => {
        stats.matches += 1
        return options.redactionToken
      })
    }
    return next
  }

  function assignValue(
    parent: Record<string, unknown> | unknown[] | null,
    key: string | number | null,
    value: string,
  ): void {
    if (parent === null || key === null) {
      throw new SecretRedactionError("mutation_failed")
    }
    try {
      if (Array.isArray(parent) && typeof key === "number") {
        parent[key] = value
      } else if (!Array.isArray(parent) && typeof key === "string") {
        parent[key] = value
      } else {
        throw new SecretRedactionError("mutation_failed")
      }
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("mutation_failed")
    }
  }

  function childMode(parentMode: VisitMode, key: string): VisitMode {
    if (IMMUTABLE_PROTOCOL_KEYS.has(key)) {
      return "scan"
    }
    if (MUTABLE_CONTENT_KEYS.has(key)) {
      return "redact"
    }
    return parentMode
  }

  function traverse(root: unknown, initialMode: VisitMode): SecretRedactionStats {
    const stats = emptyStats()
    const active = new WeakSet<object>()
    const visited = new WeakSet<object>()

    function visit(
      value: unknown,
      parent: Record<string, unknown> | unknown[] | null,
      key: string | number | null,
      mode: VisitMode,
      depth: number,
    ): void {
      stats.scannedNodes += 1
      if (stats.scannedNodes > limits.maxNodes) {
        throw new SecretRedactionError("node_limit")
      }
      if (depth > limits.maxDepth) {
        throw new SecretRedactionError("depth_limit")
      }

      if (typeof value === "string") {
        const next = applyPatterns(value, stats)
        if (next === value) {
          return
        }
        if (mode === "scan") {
          throw new SecretRedactionError("immutable_match")
        }
        assignValue(parent, key, next)
        stats.redactedFields += 1
        return
      }
      if (!value || typeof value !== "object") {
        return
      }
      if (active.has(value)) {
        throw new SecretRedactionError("cycle_detected")
      }
      if (visited.has(value)) {
        return
      }
      active.add(value)

      if (Array.isArray(value)) {
        for (let index = 0; index < value.length; index += 1) {
          visit(value[index], value, index, mode, depth + 1)
        }
      } else {
        const record = value as Record<string, unknown>
        for (const childKey of Object.keys(record)) {
          const keyProbe = applyPatterns(childKey, stats)
          if (keyProbe !== childKey) {
            throw new SecretRedactionError("immutable_match")
          }
          visit(
            record[childKey],
            record,
            childKey,
            childMode(mode, childKey),
            depth + 1,
          )
        }
      }
      active.delete(value)
      visited.add(value)
    }

    try {
      visit(root, null, null, initialMode, 0)
      return stats
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("unexpected_failure")
    }
  }

  return {
    redactText(text: string): { text: string; stats: SecretRedactionStats } {
      const stats = emptyStats()
      const redacted = applyPatterns(text, stats)
      if (redacted !== text) {
        stats.redactedFields = 1
      }
      return { text: redacted, stats }
    },
    redactMutableValue(value: unknown): SecretRedactionStats {
      return traverse(value, "redact")
    },
    redactProviderMessages(messages: unknown): SecretRedactionStats {
      return traverse(messages, "scan")
    },
    redactProviderSystem(system: unknown): SecretRedactionStats {
      return traverse(system, "redact")
    },
  }
}
