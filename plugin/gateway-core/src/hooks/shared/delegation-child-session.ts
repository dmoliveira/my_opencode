interface SessionInfoLike {
  id?: string
  parentID?: string
  title?: string
}

interface SessionCreatedLike {
  properties?: {
    info?: SessionInfoLike
  }
}

export interface DelegationChildSessionLink {
  childSessionId: string
  parentSessionId: string
  traceId?: string
}

const TRACE_MARKER_PATTERN = /\[DELEGATION TRACE ([A-Za-z0-9_-]+)\]/
const TRACE_FIELD_PATTERN = /\btrace_id=([A-Za-z0-9_-]+)/i

const childSessionLinks = new Map<string, DelegationChildSessionLink>()

function extractTraceId(text: string): string {
  const markerMatch = text.match(TRACE_MARKER_PATTERN)
  if (markerMatch?.[1]) {
    return String(markerMatch[1]).trim()
  }
  const fieldMatch = text.match(TRACE_FIELD_PATTERN)
  return String(fieldMatch?.[1] ?? "").trim()
}

export function registerDelegationChildSession(payload: SessionCreatedLike): DelegationChildSessionLink | null {
  const info = payload.properties?.info
  const childSessionId = String(info?.id ?? "").trim()
  const parentSessionId = String(info?.parentID ?? "").trim()
  if (!childSessionId || !parentSessionId) {
    return null
  }
  const traceId = extractTraceId(String(info?.title ?? "")) || undefined
  if (!traceId) {
    return null
  }
  const link: DelegationChildSessionLink = {
    childSessionId,
    parentSessionId,
    traceId,
  }
  childSessionLinks.set(childSessionId, link)
  return link
}

export function getDelegationChildSessionLink(
  childSessionId: string,
): DelegationChildSessionLink | null {
  return childSessionLinks.get(String(childSessionId).trim()) ?? null
}

export function clearDelegationChildSessionLink(
  childSessionId: string,
): DelegationChildSessionLink | null {
  const normalized = String(childSessionId).trim()
  const existing = childSessionLinks.get(normalized) ?? null
  if (existing) {
    childSessionLinks.delete(normalized)
  }
  return existing
}
