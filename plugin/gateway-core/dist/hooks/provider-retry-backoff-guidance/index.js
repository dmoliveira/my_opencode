import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { injectHookMessage } from "../hook-message-injector/index.js";
import { PROVIDER_HEADER_TIMEOUT_DOWNGRADE_THRESHOLD, recordProviderHeaderTimeout, resetProviderHeaderTimeoutState, } from "../shared/provider-timeout-state.js";
import { classifyProviderRetryReason, isContextOverflowNonRetryable, } from "../shared/provider-retry-reason.js";
import { normalizeModelRef } from "../shared/routing-profiles.js";
const RETRY_INITIAL_DELAY_MS = 2000;
const RETRY_BACKOFF_FACTOR = 2;
const RETRY_MAX_DELAY_NO_HEADERS_MS = 30000;
function fallbackDelayMs(attempt) {
    const normalizedAttempt = Math.max(1, Math.floor(attempt));
    const raw = RETRY_INITIAL_DELAY_MS * RETRY_BACKOFF_FACTOR ** (normalizedAttempt - 1);
    return Math.min(raw, RETRY_MAX_DELAY_NO_HEADERS_MS);
}
function resolveSessionId(payload) {
    const candidates = [payload.properties?.sessionID, payload.properties?.sessionId, payload.properties?.info?.id];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function resolveDirectory(payload, fallback) {
    return typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : fallback;
}
function parseRetryAfterMs(headers) {
    const retryAfterMs = headers["retry-after-ms"];
    if (retryAfterMs) {
        const parsed = Number.parseFloat(retryAfterMs);
        if (Number.isFinite(parsed) && parsed > 0) {
            return Math.ceil(parsed);
        }
    }
    const retryAfter = headers["retry-after"];
    if (!retryAfter) {
        return null;
    }
    const parsedSeconds = Number.parseFloat(retryAfter);
    if (Number.isFinite(parsedSeconds) && parsedSeconds > 0) {
        return Math.ceil(parsedSeconds * 1000);
    }
    const parsedDateMs = Date.parse(retryAfter) - Date.now();
    if (Number.isFinite(parsedDateMs) && parsedDateMs > 0) {
        return Math.ceil(parsedDateMs);
    }
    return null;
}
function normalizeHeaders(value) {
    if (!value || typeof value !== "object") {
        return {};
    }
    const input = value;
    const normalized = {};
    for (const [key, raw] of Object.entries(input)) {
        if (typeof raw === "string" && raw.trim()) {
            normalized[key.toLowerCase()] = raw.trim();
        }
    }
    return normalized;
}
function extractHeaders(payload) {
    const candidates = [payload.error, payload.message, payload.properties?.error];
    for (const candidate of candidates) {
        if (!candidate || typeof candidate !== "object") {
            continue;
        }
        const record = candidate;
        const direct = normalizeHeaders(record.responseHeaders);
        if (Object.keys(direct).length > 0) {
            return direct;
        }
        const nested = normalizeHeaders(record.data?.responseHeaders);
        if (Object.keys(nested).length > 0) {
            return nested;
        }
    }
    return {};
}
function extractText(payload) {
    return [payload.error, payload.message, payload.properties?.error]
        .map((value) => (typeof value === "string" ? value : JSON.stringify(value ?? "")))
        .join("\n");
}
function extractModel(payload) {
    const direct = normalizeModelRef(payload.properties?.providerID, payload.properties?.modelID);
    if (direct) {
        return direct;
    }
    return normalizeModelRef(payload.properties?.model?.providerID, payload.properties?.model?.modelID);
}
function buildHint(args) {
    const lines = ["[provider RETRY BACKOFF]", "Provider retry guidance detected."];
    if (args.reason) {
        lines.push(`- Canonical reason: ${args.reason}`);
    }
    const seconds = (args.delayMs / 1000).toFixed(1);
    lines.push(`- Wait approximately ${seconds}s before the next provider retry`);
    if (!args.usesHeaderDelay) {
        lines.push(`- Apply exponential backoff before the next provider retry (cap ${RETRY_MAX_DELAY_NO_HEADERS_MS / 1000}s without retry headers)`);
    }
    if (args.headerTimeoutCount >= PROVIDER_HEADER_TIMEOUT_DOWNGRADE_THRESHOLD) {
        lines.push("- Repeated header timeouts detected; the next auto-recovery may downgrade to a lighter model");
    }
    lines.push("- Prefer short follow-up prompts while provider pressure persists");
    return lines.join("\n");
}
export function createProviderRetryBackoffGuidanceHook(options) {
    const lastInjectedAt = new Map();
    const headerlessAttempts = new Map();
    return {
        id: "provider-retry-backoff-guidance",
        priority: 360,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    lastInjectedAt.delete(sessionId);
                    headerlessAttempts.delete(sessionId);
                    resetProviderHeaderTimeoutState(sessionId);
                }
                return;
            }
            if (type !== "session.error" && type !== "message.updated") {
                return;
            }
            const eventPayload = (payload ?? {});
            const headers = extractHeaders(eventPayload);
            const text = extractText(eventPayload);
            if (isContextOverflowNonRetryable(text)) {
                return;
            }
            const reason = classifyProviderRetryReason(text);
            if (!reason && !headers["retry-after"] && !headers["retry-after-ms"]) {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            const session = options.client?.session;
            if (!sessionId || !session) {
                return;
            }
            const cooldownMs = Math.max(1, Math.floor(options.cooldownMs));
            const now = Date.now();
            const last = lastInjectedAt.get(sessionId) ?? 0;
            if (last > 0 && now - last < cooldownMs) {
                return;
            }
            const directory = resolveDirectory(eventPayload, options.directory);
            const parsedHeaderDelayMs = parseRetryAfterMs(headers);
            const usesHeaderDelay = typeof parsedHeaderDelayMs === "number" && Number.isFinite(parsedHeaderDelayMs);
            const attempt = usesHeaderDelay ? 1 : (headerlessAttempts.get(sessionId) ?? 0) + 1;
            const delayMs = usesHeaderDelay ? Math.ceil(parsedHeaderDelayMs) : fallbackDelayMs(attempt);
            const headerTimeoutState = reason?.code === "provider_header_timeout" ? recordProviderHeaderTimeout(sessionId) : null;
            const actualModel = extractModel(eventPayload);
            if (headerTimeoutState) {
                writeGatewayEventAudit(directory, {
                    hook: "provider-retry-backoff-guidance",
                    stage: "state",
                    reason_code: "provider_header_timeout_observed",
                    session_id: sessionId,
                    timeout_count: String(headerTimeoutState.count),
                    actual_model: actualModel || undefined,
                });
            }
            await injectHookMessage({
                session,
                sessionId,
                content: buildHint({
                    delayMs,
                    reason: reason?.message ?? null,
                    usesHeaderDelay,
                    headerTimeoutCount: headerTimeoutState?.count ?? 0,
                }),
                directory,
            });
            writeGatewayEventAudit(directory, {
                hook: "provider-retry-backoff-guidance",
                stage: "state",
                reason_code: usesHeaderDelay ? "provider_retry_backoff_delay_hint" : "provider_retry_backoff_generic_hint",
                session_id: sessionId,
            });
            if (usesHeaderDelay) {
                headerlessAttempts.set(sessionId, 0);
            }
            else {
                headerlessAttempts.set(sessionId, attempt);
            }
            lastInjectedAt.set(sessionId, now);
        },
    };
}
