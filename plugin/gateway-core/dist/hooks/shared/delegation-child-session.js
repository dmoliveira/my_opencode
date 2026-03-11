const TRACE_MARKER_PATTERN = /\[DELEGATION TRACE ([A-Za-z0-9_-]+)\]/;
const TRACE_FIELD_PATTERN = /\btrace_id=([A-Za-z0-9_-]+)/i;
const childSessionLinks = new Map();
function readDelegationMetadata(metadata) {
    if (!metadata || typeof metadata !== "object") {
        return null;
    }
    const source = metadata;
    const delegation = source.gateway && typeof source.gateway === "object" && source.gateway.delegation
        ? source.gateway.delegation
        : source.delegation;
    if (!delegation || typeof delegation !== "object") {
        return null;
    }
    const childRunId = String(delegation.childRunId ?? "").trim() || undefined;
    const traceId = String(delegation.traceId ?? "").trim() || undefined;
    const subagentType = String(delegation.subagentType ?? "").trim().toLowerCase() || undefined;
    if (!childRunId && !traceId && !subagentType) {
        return null;
    }
    return { childRunId, traceId, subagentType };
}
function extractTraceId(text) {
    const markerMatch = text.match(TRACE_MARKER_PATTERN);
    if (markerMatch?.[1]) {
        return String(markerMatch[1]).trim();
    }
    const fieldMatch = text.match(TRACE_FIELD_PATTERN);
    return String(fieldMatch?.[1] ?? "").trim();
}
export function registerDelegationChildSession(payload) {
    const info = payload.properties?.info;
    const childSessionId = String(info?.id ?? "").trim();
    const parentSessionId = String(info?.parentID ?? "").trim();
    if (!childSessionId || !parentSessionId) {
        return null;
    }
    const metadata = readDelegationMetadata(info?.metadata);
    const traceId = metadata?.traceId || extractTraceId(String(info?.title ?? "")) || undefined;
    const childRunId = metadata?.childRunId;
    const subagentType = metadata?.subagentType;
    if (!traceId && !childRunId && !subagentType) {
        return null;
    }
    const link = {
        childSessionId,
        parentSessionId,
        childRunId,
        traceId,
        subagentType,
    };
    childSessionLinks.set(childSessionId, link);
    return link;
}
export function getDelegationChildSessionLink(childSessionId) {
    return childSessionLinks.get(String(childSessionId).trim()) ?? null;
}
export function clearDelegationChildSessionLink(childSessionId) {
    const normalized = String(childSessionId).trim();
    const existing = childSessionLinks.get(normalized) ?? null;
    if (existing) {
        childSessionLinks.delete(normalized);
    }
    return existing;
}
