import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { injectHookMessage } from "../hook-message-injector/index.js";
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
function extractErrorText(payload) {
    return [payload.error, payload.message, payload.properties?.error]
        .map((value) => (typeof value === "string" ? value : JSON.stringify(value ?? "")))
        .join("\n");
}
function classify(text) {
    if (/freeusagelimiterror/i.test(text) || /free usage exceeded/i.test(text) || /insufficient.*credits/i.test(text)) {
        return "free_usage_exhausted";
    }
    if (/too_many_requests/i.test(text) || /rate[_ -]?limit(ed)?/i.test(text)) {
        return "rate_limited";
    }
    if (/overloaded/i.test(text) || /code.*(exhausted|unavailable)/i.test(text) || /provider is overloaded/i.test(text)) {
        return "provider_overloaded";
    }
    return null;
}
function buildHint(classification) {
    if (classification === "free_usage_exhausted") {
        return [
            "[provider ERROR CLASSIFIER]",
            "Detected provider free-usage or credit exhaustion.",
            "- Add provider credits / quota before retrying",
            "- Do not loop immediate retries until quota is restored",
        ].join("\n");
    }
    if (classification === "rate_limited") {
        return [
            "[provider ERROR CLASSIFIER]",
            "Detected provider rate limiting.",
            "- Reduce retry frequency and apply backoff",
            "- Keep follow-up prompts concise while limits reset",
        ].join("\n");
    }
    return [
        "[provider ERROR CLASSIFIER]",
        "Detected provider overload/unavailable condition.",
        "- Wait and retry with backoff",
        "- Continue with minimal prompt scope until provider stabilizes",
    ].join("\n");
}
export function createProviderErrorClassifierHook(options) {
    const lastClassificationBySession = new Map();
    return {
        id: "provider-error-classifier",
        priority: 361,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sessionId = resolveSessionId((payload ?? {}));
                if (sessionId) {
                    lastClassificationBySession.delete(sessionId);
                }
                return;
            }
            if (type !== "session.error" && type !== "message.updated") {
                return;
            }
            const eventPayload = (payload ?? {});
            const text = extractErrorText(eventPayload);
            const classification = classify(text);
            const sessionId = resolveSessionId(eventPayload);
            const session = options.client?.session;
            if (!classification || !sessionId || !session) {
                return;
            }
            const now = Date.now();
            const cooldownMs = Math.max(1, Math.floor(options.cooldownMs));
            const previous = lastClassificationBySession.get(sessionId);
            if (previous && previous.classification === classification && now - previous.at < cooldownMs) {
                return;
            }
            const directory = resolveDirectory(eventPayload, options.directory);
            await injectHookMessage({
                session,
                sessionId,
                content: buildHint(classification),
                directory,
            });
            writeGatewayEventAudit(directory, {
                hook: "provider-error-classifier",
                stage: "state",
                reason_code: `provider_error_${classification}`,
                session_id: sessionId,
            });
            lastClassificationBySession.set(sessionId, { classification, at: now });
        },
    };
}
