import { DEFAULT_INJECTED_TEXT_MAX_CHARS, truncateInjectedText } from "../shared/injected-text-truncator.js";
// Resolves latest reusable agent/model identity from session history.
export async function resolveHookMessageIdentity(args) {
    if (typeof args.session.messages !== "function") {
        return {};
    }
    try {
        const response = await args.session.messages({
            path: { id: args.sessionId },
            query: { directory: args.directory },
        });
        const messages = Array.isArray(response.data) ? response.data : [];
        let agent;
        let model;
        for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
            const info = messages[idx]?.info;
            if (!info || info.role === "assistant") {
                continue;
            }
            if (!agent && typeof info.agent === "string" && info.agent.trim()) {
                agent = info.agent.trim();
            }
            if (!model) {
                if (info.model?.providerID && info.model?.modelID) {
                    model = {
                        providerID: info.model.providerID,
                        modelID: info.model.modelID,
                        ...(info.model.variant ? { variant: info.model.variant } : {}),
                    };
                }
                else if (info.providerID && info.modelID) {
                    model = {
                        providerID: info.providerID,
                        modelID: info.modelID,
                    };
                }
            }
            if (agent && model) {
                break;
            }
        }
        return {
            ...(agent ? { agent } : {}),
            ...(model ? { model } : {}),
        };
    }
    catch {
        return {};
    }
}
function hasCompletedAssistantTurn(message) {
    const info = message?.info;
    if (!info || info.role !== "assistant") {
        return true;
    }
    if (info.error !== undefined && info.error !== null) {
        return true;
    }
    if (!info.time || typeof info.time !== "object") {
        return true;
    }
    return Number.isFinite(Number(info.time?.completed ?? NaN));
}
export async function inspectHookMessageSafety(args) {
    if (Array.isArray(args.messages)) {
        for (let idx = args.messages.length - 1; idx >= 0; idx -= 1) {
            const message = args.messages[idx];
            if (message?.info?.role !== "assistant") {
                continue;
            }
            return hasCompletedAssistantTurn(message)
                ? { safe: true, reason: "ok" }
                : { safe: false, reason: "assistant_turn_incomplete" };
        }
        return { safe: true, reason: "ok" };
    }
    if (typeof args.session.messages !== "function") {
        return { safe: true, reason: "history_unavailable" };
    }
    try {
        const response = await args.session.messages({
            path: { id: args.sessionId },
            query: { directory: args.directory },
        });
        return inspectHookMessageSafety({
            session: args.session,
            sessionId: args.sessionId,
            directory: args.directory,
            messages: Array.isArray(response.data) ? response.data : [],
        });
    }
    catch {
        return { safe: true, reason: "history_probe_failed" };
    }
}
// Builds promptAsync body payload from content and optional identity.
export function buildHookMessageBody(content, identity) {
    const normalized = content.trim();
    return {
        ...(identity.agent ? { agent: identity.agent } : {}),
        ...(identity.model ? { model: identity.model } : {}),
        parts: [{ type: "text", text: normalized }],
    };
}
// Injects synthetic hook content while preserving recent agent/model metadata.
export async function injectHookMessage(args) {
    const maxChars = typeof args.maxChars === "number" && Number.isFinite(args.maxChars) && args.maxChars > 0
        ? Math.floor(args.maxChars)
        : DEFAULT_INJECTED_TEXT_MAX_CHARS;
    const truncated = truncateInjectedText(args.content, maxChars);
    const content = truncated.text.trim();
    if (!content) {
        return false;
    }
    const identity = await resolveHookMessageIdentity({
        session: args.session,
        sessionId: args.sessionId,
        directory: args.directory,
    });
    try {
        await args.session.promptAsync({
            path: { id: args.sessionId },
            body: buildHookMessageBody(content, identity),
            query: { directory: args.directory },
        });
        return true;
    }
    catch {
        return false;
    }
}
