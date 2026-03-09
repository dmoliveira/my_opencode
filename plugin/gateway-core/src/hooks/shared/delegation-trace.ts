import { randomUUID } from "node:crypto"

interface TraceArgs {
  [key: string]: unknown
  prompt?: string
  description?: string
  subagent_type?: string
  category?: string
}

interface DelegationMetadataCarrier {
  metadata?: unknown
}

interface GatewayDelegationMetadata {
  childRunId?: string
  traceId?: string
  subagentType?: string
  category?: string
}

const TRACE_PATTERN = /\[DELEGATION TRACE ([A-Za-z0-9_-]+)\]/
const CHILD_RUN_PREFIX = "subagent-run/"

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

function readGatewayDelegationMetadata(metadata: unknown): GatewayDelegationMetadata | null {
  if (!metadata || typeof metadata !== "object") {
    return null
  }
  const source = metadata as {
    gateway?: { delegation?: GatewayDelegationMetadata }
  }
  const nested = source.gateway && typeof source.gateway === "object" ? source.gateway.delegation : undefined
  if (!nested || typeof nested !== "object") {
    return null
  }
  const rawChildRunId = String(nested.childRunId ?? "").trim()
  const rawTraceId = String(nested.traceId ?? "").trim()
  const traceId = rawTraceId || parseTraceIdFromChildRunId(rawChildRunId) || undefined
  const childRunId = traceId ? buildDelegationChildRunId(traceId) || undefined : undefined
  const subagentType = String(nested.subagentType ?? "").trim() || undefined
  const category = String(nested.category ?? "").trim() || undefined
  if (!childRunId && !traceId && !subagentType && !category) {
    return null
  }
  return { childRunId, traceId, subagentType, category }
}

function buildDelegationChildRunId(traceId: string): string {
  const normalizedTraceId = String(traceId).trim()
  return normalizedTraceId ? `${CHILD_RUN_PREFIX}${normalizedTraceId}` : ""
}

function parseTraceIdFromChildRunId(childRunId: string): string {
  const normalizedChildRunId = String(childRunId).trim()
  if (!normalizedChildRunId.startsWith(CHILD_RUN_PREFIX)) {
    return ""
  }
  return normalizedChildRunId.slice(CHILD_RUN_PREFIX.length).trim()
}

function writeGatewayDelegationMetadata(
  carrier: DelegationMetadataCarrier,
  metadata: GatewayDelegationMetadata,
): void {
  const current =
    carrier.metadata && typeof carrier.metadata === "object" ? { ...(carrier.metadata as Record<string, unknown>) } : {}
  const gateway =
    current.gateway && typeof current.gateway === "object"
      ? { ...(current.gateway as Record<string, unknown>) }
      : {}
  const delegation =
    gateway.delegation && typeof gateway.delegation === "object"
      ? { ...(gateway.delegation as Record<string, unknown>) }
      : {}
  if (metadata.childRunId) {
    delegation.childRunId = metadata.childRunId
  }
  if (metadata.traceId) {
    delegation.traceId = metadata.traceId
  }
  if (metadata.subagentType) {
    delegation.subagentType = metadata.subagentType
  }
  if (metadata.category) {
    delegation.category = metadata.category
  }
  gateway.delegation = delegation
  current.gateway = gateway
  carrier.metadata = current
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

export function annotateDelegationMetadata(carrier: DelegationMetadataCarrier, args: TraceArgs | undefined): void {
  const existing = readGatewayDelegationMetadata(carrier.metadata)
  const traceId = extractDelegationTraceId(args, carrier.metadata)
  const expectedChildRunId = buildDelegationChildRunId(traceId)
  const childRunId = expectedChildRunId || existing?.childRunId
  const subagentType = String(args?.subagent_type ?? "").trim() || undefined
  const category = String(args?.category ?? "").trim() || undefined
  if (!childRunId && !traceId && !subagentType && !category) {
    return
  }
  writeGatewayDelegationMetadata(carrier, {
    childRunId: childRunId || undefined,
    traceId: traceId || undefined,
    subagentType,
    category,
  })
}

export function extractDelegationChildRunId(metadata?: unknown): string {
  return String(readGatewayDelegationMetadata(metadata)?.childRunId ?? "").trim()
}

export function extractDelegationTraceId(args: TraceArgs | undefined, metadata?: unknown): string {
  const combined = `${String(args?.prompt ?? "")}\n${String(args?.description ?? "")}`
  const parsed = parseTrace(combined)
  if (parsed) {
    return parsed
  }
  const delegation = readGatewayDelegationMetadata(metadata)
  return delegation?.traceId ?? parseTraceIdFromChildRunId(delegation?.childRunId ?? "")
}

export function extractDelegationSubagentType(args: TraceArgs | undefined, metadata?: unknown): string {
  const explicit = String(args?.subagent_type ?? "").trim()
  if (explicit) {
    return explicit.toLowerCase()
  }
  return String(readGatewayDelegationMetadata(metadata)?.subagentType ?? "").trim().toLowerCase()
}

export function extractDelegationCategory(args: TraceArgs | undefined, metadata?: unknown): string {
  const explicit = String(args?.category ?? "").trim()
  if (explicit) {
    return explicit.toLowerCase()
  }
  return String(readGatewayDelegationMetadata(metadata)?.category ?? "").trim().toLowerCase()
}

export function extractDelegationSubagentTypeFromOutput(output: string): string {
  const match = output.match(/^- subagent:\s+([^\n]+)$/im)
  return String(match?.[1] ?? "").trim().toLowerCase()
}
