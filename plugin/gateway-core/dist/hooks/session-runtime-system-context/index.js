import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const SYSTEM_CONTEXT_MARKER = "runtime_session_context:";
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function buildSystemContext(sessionId) {
    return [
        `${SYSTEM_CONTEXT_MARKER} ${sessionId}`,
        "Use this exact runtime session id for commits, logs, telemetry, and external tooling created during this session.",
        "If the user asks for the current runtime session id, return it exactly.",
    ].join("\n");
}
function runtimeContextEntryIndex(system) {
    return system.findIndex((entry) => typeof entry === "string" && entry.includes(SYSTEM_CONTEXT_MARKER));
}
export function createSessionRuntimeSystemContextHook(options) {
    return {
        id: "session-runtime-system-context",
        priority: 294,
        async event(type, payload) {
            if (!options.enabled || type !== "experimental.chat.system.transform") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            const system = eventPayload.output?.system;
            if (!sessionId || !Array.isArray(system)) {
                return;
            }
            const nextContext = buildSystemContext(sessionId);
            const existingIndex = runtimeContextEntryIndex(system);
            if (existingIndex >= 0 && system[existingIndex] === nextContext) {
                return;
            }
            if (existingIndex >= 0) {
                system.splice(existingIndex, 1);
            }
            system.unshift(nextContext);
            writeGatewayEventAudit(directory, {
                hook: "session-runtime-system-context",
                stage: "inject",
                reason_code: existingIndex >= 0 ? "session_runtime_system_context_replaced" : "session_runtime_system_context_injected",
                session_id: sessionId,
            });
        },
    };
}
