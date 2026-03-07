import { randomUUID } from "node:crypto"

interface TraceArgs {
  [key: string]: unknown
  prompt?: string
  description?: string
}

const TRACE_PATTERN = /\[DELEGATION TRACE ([A-Za-z0-9_-]+)\]/

function prependHint(original: string, hint: string): string {
  if (!original.trim()) {
    return hint
  }
  if (original.includes(hint)) {
    return original
  }
  return `${hint}\n\n${original}`
}

function parseTrace(text: string): string | null {
  const match = text.match(TRACE_PATTERN)
  if (!match) {
    return null
  }
  const traceId = String(match[1] ?? "").trim()
  return traceId || null
}

function newTraceId(): string {
  try {
    return randomUUID()
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  }
}

export function resolveDelegationTraceId(args: TraceArgs): string {
  const combined = `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`
  const existing = parseTrace(combined)
  if (existing) {
    return existing
  }
  const traceId = newTraceId()
  const marker = `[DELEGATION TRACE ${traceId}]`
  args.prompt = prependHint(String(args.prompt ?? ""), marker)
  args.description = prependHint(String(args.description ?? ""), marker)
  return traceId
}
