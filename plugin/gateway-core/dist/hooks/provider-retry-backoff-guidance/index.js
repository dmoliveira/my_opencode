import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { injectHookMessage } from "../hook-message-injector/index.js";
import { classifyProviderRetryReason, isContextOverflowNonRetryable } from "../shared/provider-retry-reason.js";
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
function buildHint(delayMs, reason) {
    const lines = ["[provider RETRY BACKOFF]", "Provider retry guidance detected."];
    if (reason) {
        lines.push(`- Canonical reason: ${reason}`);
    }
    if (typeof delayMs === "number" && Number.isFinite(delayMs) && delayMs > 0) {
        const seconds = (delayMs / 1000).toFixed(1);
        lines.push(`- Wait approximately ${seconds}s before the next provider retry`);
    }
    else {
        lines.push("- Apply exponential backoff before the next provider retry");
    }
    lines.push("- Prefer short follow-up prompts while provider pressure persists");
    return lines.join("\n");
}
export function createProviderRetryBackoffGuidanceHook(options) {
    const lastInjectedAt = new Map();
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
            const delayMs = parseRetryAfterMs(headers);
            await injectHookMessage({
                session,
                sessionId,
                content: buildHint(delayMs, reason?.message ?? null),
                directory,
            });
            writeGatewayEventAudit(directory, {
                hook: "provider-retry-backoff-guidance",
                stage: "state",
                reason_code: delayMs ? "provider_retry_backoff_delay_hint" : "provider_retry_backoff_generic_hint",
                session_id: sessionId,
            });
            lastInjectedAt.set(sessionId, now);
        },
    };
}
