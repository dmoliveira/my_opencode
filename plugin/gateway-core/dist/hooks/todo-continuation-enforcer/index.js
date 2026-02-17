import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadGatewayState } from "../../state/storage.js";
import { injectHookMessage } from "../hook-message-injector/index.js";
const CONTINUE_LOOP_MARKER = "<CONTINUE-LOOP>";
const TODO_CONTINUATION_PROMPT = [
    "[SYSTEM DIRECTIVE: TODO CONTINUATION]",
    "Incomplete tasks remain in your current run.",
    "- Continue with the next pending task immediately",
    "- Do not ask for extra confirmation",
    "- Keep executing until all pending tasks are complete",
].join("\n");
function resolveSessionId(payload) {
    const candidates = [
        payload.properties?.sessionID,
        payload.properties?.sessionId,
        payload.properties?.info?.id,
        payload.input?.sessionID,
        payload.input?.sessionId,
    ];
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
function hasPendingMarker(messages) {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
        const message = messages[i];
        if (message?.info?.role !== "assistant") {
            continue;
        }
        const text = (message.parts ?? [])
            .filter((part) => part.type === "text")
            .map((part) => part.text ?? "")
            .join("\n");
        return text.includes(CONTINUE_LOOP_MARKER);
    }
    return false;
}
function getSessionState(store, sessionId) {
    const existing = store.get(sessionId);
    if (existing) {
        return existing;
    }
    const created = {
        pendingContinuation: false,
        lastInjectedAt: 0,
        consecutiveFailures: 0,
        inFlight: false,
    };
    store.set(sessionId, created);
    return created;
}
export function createTodoContinuationEnforcerHook(options) {
    const sessionState = new Map();
    return {
        id: "todo-continuation-enforcer",
        priority: 345,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted" || type === "session.compacted") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                if (sessionId) {
                    sessionState.delete(sessionId);
                }
                return;
            }
            if (type === "tool.execute.after") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
                if (!sessionId || tool !== "task" || typeof eventPayload.output?.output !== "string") {
                    return;
                }
                const state = getSessionState(sessionState, sessionId);
                state.pendingContinuation = eventPayload.output.output.includes(CONTINUE_LOOP_MARKER);
                return;
            }
            if (type !== "session.idle") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = resolveDirectory(eventPayload, options.directory);
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                return;
            }
            if (options.stopGuard?.isStopped(sessionId)) {
                writeGatewayEventAudit(directory, {
                    hook: "todo-continuation-enforcer",
                    stage: "skip",
                    reason_code: "todo_continuation_stop_guard",
                    session_id: sessionId,
                });
                return;
            }
            const gatewayState = loadGatewayState(directory);
            if (gatewayState?.activeLoop?.active === true && gatewayState.activeLoop.sessionId === sessionId) {
                writeGatewayEventAudit(directory, {
                    hook: "todo-continuation-enforcer",
                    stage: "skip",
                    reason_code: "todo_continuation_active_loop",
                    session_id: sessionId,
                });
                return;
            }
            const state = getSessionState(sessionState, sessionId);
            if (state.inFlight) {
                return;
            }
            const maxFailures = Math.max(1, Math.floor(options.maxConsecutiveFailures));
            if (state.consecutiveFailures >= maxFailures) {
                return;
            }
            const cooldownBase = Math.max(1, Math.floor(options.cooldownMs));
            const cooldownMs = cooldownBase * 2 ** Math.min(state.consecutiveFailures, 5);
            const now = Date.now();
            if (state.lastInjectedAt > 0 && now - state.lastInjectedAt < cooldownMs) {
                return;
            }
            let pending = state.pendingContinuation;
            const client = options.client?.session;
            if (!pending && client) {
                const response = await client.messages({
                    path: { id: sessionId },
                    query: { directory },
                });
                pending = hasPendingMarker(Array.isArray(response.data) ? response.data : []);
            }
            state.pendingContinuation = pending;
            if (!pending || !client) {
                writeGatewayEventAudit(directory, {
                    hook: "todo-continuation-enforcer",
                    stage: "skip",
                    reason_code: "todo_continuation_no_pending",
                    session_id: sessionId,
                });
                return;
            }
            state.inFlight = true;
            try {
                const injected = await injectHookMessage({
                    session: client,
                    sessionId,
                    content: TODO_CONTINUATION_PROMPT,
                    directory,
                });
                state.lastInjectedAt = now;
                if (injected) {
                    state.consecutiveFailures = 0;
                    writeGatewayEventAudit(directory, {
                        hook: "todo-continuation-enforcer",
                        stage: "inject",
                        reason_code: "todo_continuation_injected",
                        session_id: sessionId,
                    });
                }
                else {
                    state.consecutiveFailures += 1;
                    writeGatewayEventAudit(directory, {
                        hook: "todo-continuation-enforcer",
                        stage: "inject",
                        reason_code: "todo_continuation_inject_failed",
                        session_id: sessionId,
                        failures: state.consecutiveFailures,
                    });
                }
            }
            finally {
                state.inFlight = false;
            }
        },
    };
}
