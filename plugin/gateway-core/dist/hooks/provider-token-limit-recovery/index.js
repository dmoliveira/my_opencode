import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { injectHookMessage } from "../hook-message-injector/index.js";
const TOKEN_LIMIT_PATTERNS = [
    /context window/i,
    /token limit/i,
    /maximum context/i,
    /prompt is too long/i,
    /input too long/i,
];
const DEFAULT_PROVIDER = "anthropic";
const DEFAULT_MODEL = "claude-sonnet-4-5";
const RECOVERY_HINT = [
    "[token-limit RECOVERY]",
    "A provider token-limit error was detected.",
    "- Context was compacted automatically",
    "- Continue with concise outputs and avoid large raw payloads",
    "- Prefer focused reads/edits over broad scans",
].join("\n");
function resolveSessionId(payload) {
    const candidates = [payload.properties?.sessionID, payload.properties?.sessionId, payload.properties?.info?.id];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function isTokenLimitError(payload) {
    const chunks = [payload.error, payload.message, payload.properties?.error]
        .map((value) => (typeof value === "string" ? value : JSON.stringify(value ?? "")))
        .filter(Boolean)
        .join("\n");
    return TOKEN_LIMIT_PATTERNS.some((pattern) => pattern.test(chunks));
}
async function resolveProviderModel(args) {
    const session = args.client?.session;
    if (!session) {
        return { providerID: DEFAULT_PROVIDER, modelID: DEFAULT_MODEL };
    }
    try {
        const response = await session.messages({
            path: { id: args.sessionId },
            query: { directory: args.directory },
        });
        const messages = Array.isArray(response.data) ? response.data : [];
        for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
            const info = messages[idx]?.info;
            if (info?.role !== "assistant") {
                continue;
            }
            if (typeof info.providerID === "string" && info.providerID && typeof info.modelID === "string" && info.modelID) {
                return { providerID: info.providerID, modelID: info.modelID };
            }
        }
    }
    catch {
        return { providerID: DEFAULT_PROVIDER, modelID: DEFAULT_MODEL };
    }
    return { providerID: DEFAULT_PROVIDER, modelID: DEFAULT_MODEL };
}
export function createProviderTokenLimitRecoveryHook(options) {
    const inFlight = new Set();
    const lastRecoveredAt = new Map();
    return {
        id: "provider-token-limit-recovery",
        priority: 357,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                if (sessionId) {
                    inFlight.delete(sessionId);
                    lastRecoveredAt.delete(sessionId);
                }
                return;
            }
            if (type !== "session.error" && type !== "message.updated") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId || !isTokenLimitError(eventPayload)) {
                return;
            }
            if (inFlight.has(sessionId)) {
                return;
            }
            const now = Date.now();
            const cooldownMs = Math.max(1, Math.floor(options.cooldownMs));
            const last = lastRecoveredAt.get(sessionId) ?? 0;
            if (last > 0 && now - last < cooldownMs) {
                return;
            }
            const session = options.client?.session;
            if (!session) {
                return;
            }
            inFlight.add(sessionId);
            try {
                const model = await resolveProviderModel({
                    sessionId,
                    directory,
                    client: options.client,
                });
                await session.summarize({
                    path: { id: sessionId },
                    body: {
                        providerID: model.providerID,
                        modelID: model.modelID,
                        auto: true,
                    },
                    query: { directory },
                });
                await injectHookMessage({
                    session,
                    sessionId,
                    content: RECOVERY_HINT,
                    directory,
                });
                writeGatewayEventAudit(directory, {
                    hook: "provider-token-limit-recovery",
                    stage: "state",
                    reason_code: "token_limit_recovery_triggered",
                    session_id: sessionId,
                });
                lastRecoveredAt.set(sessionId, now);
            }
            catch {
                writeGatewayEventAudit(directory, {
                    hook: "provider-token-limit-recovery",
                    stage: "state",
                    reason_code: "token_limit_recovery_failed",
                    session_id: sessionId,
                });
            }
            finally {
                inFlight.delete(sessionId);
            }
        },
    };
}
