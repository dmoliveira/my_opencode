const stateBySession = new Map();
export const PROVIDER_HEADER_TIMEOUT_DOWNGRADE_THRESHOLD = 2;
export const PROVIDER_HEADER_TIMEOUT_STATE_TTL_MS = 15 * 60_000;
function isExpired(state, now) {
    return Math.max(0, now - state.lastObservedAt) > PROVIDER_HEADER_TIMEOUT_STATE_TTL_MS;
}
export function resetProviderHeaderTimeoutState(sessionId) {
    const normalized = String(sessionId).trim();
    if (!normalized) {
        return;
    }
    stateBySession.delete(normalized);
}
export function recordProviderHeaderTimeout(sessionId) {
    const normalized = String(sessionId).trim();
    if (!normalized) {
        return null;
    }
    const now = Date.now();
    const current = stateBySession.get(normalized);
    const next = {
        sessionId: normalized,
        count: current && !isExpired(current, now) ? current.count + 1 : 1,
        lastObservedAt: now,
    };
    stateBySession.set(normalized, next);
    return next;
}
export function getProviderHeaderTimeoutState(sessionId) {
    const normalized = String(sessionId).trim();
    if (!normalized) {
        return null;
    }
    const current = stateBySession.get(normalized);
    if (!current) {
        return null;
    }
    if (isExpired(current, Date.now())) {
        stateBySession.delete(normalized);
        return null;
    }
    return current;
}
