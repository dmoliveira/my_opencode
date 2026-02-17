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
function extractErrorText(payload) {
    return [payload.error, payload.message, payload.properties?.error]
        .map((value) => (typeof value === "string" ? value : JSON.stringify(value ?? "")))
        .join("\n");
}
function classify(text) {
    const reason = classifyProviderRetryReason(text);
    if (!reason) {
        return null;
    }
    if (reason.code === "free_usage_exhausted") {
        return { classification: "free_usage_exhausted", reason: reason.message };
    }
    if (reason.code === "provider_overloaded") {
        return { classification: "provider_overloaded", reason: reason.message };
    }
    return { classification: "rate_limited", reason: reason.message };
}
function buildHint(classification, reason) {
    if (classification === "free_usage_exhausted") {
        return [
            "[provider ERROR CLASSIFIER]",
            "Detected provider free-usage or credit exhaustion.",
            `- Canonical reason: ${reason}`,
            "- Add provider credits / quota before retrying",
            "- Do not loop immediate retries until quota is restored",
        ].join("\n");
    }
    if (classification === "rate_limited") {
        return [
            "[provider ERROR CLASSIFIER]",
            "Detected provider rate limiting.",
            `- Canonical reason: ${reason}`,
            "- Reduce retry frequency and apply backoff",
            "- Keep follow-up prompts concise while limits reset",
        ].join("\n");
    }
    return [
        "[provider ERROR CLASSIFIER]",
        "Detected provider overload/unavailable condition.",
        `- Canonical reason: ${reason}`,
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
            if (isContextOverflowNonRetryable(text)) {
                return;
            }
            const outcome = classify(text);
            const sessionId = resolveSessionId(eventPayload);
            const session = options.client?.session;
            if (!outcome || !sessionId || !session) {
                return;
            }
            const now = Date.now();
            const cooldownMs = Math.max(1, Math.floor(options.cooldownMs));
            const previous = lastClassificationBySession.get(sessionId);
            if (previous && previous.classification === outcome.classification && now - previous.at < cooldownMs) {
                return;
            }
            const directory = resolveDirectory(eventPayload, options.directory);
            await injectHookMessage({
                session,
                sessionId,
                content: buildHint(outcome.classification, outcome.reason),
                directory,
            });
            writeGatewayEventAudit(directory, {
                hook: "provider-error-classifier",
                stage: "state",
                reason_code: `provider_error_${outcome.classification}`,
                session_id: sessionId,
            });
            lastClassificationBySession.set(sessionId, { classification: outcome.classification, at: now });
        },
    };
}
