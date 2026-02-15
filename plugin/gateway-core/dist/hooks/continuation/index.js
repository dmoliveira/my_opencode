import { REASON_CODES } from "../../bridge/reason-codes.js";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadGatewayState, nowIso, saveGatewayState } from "../../state/storage.js";
// Resolves active session id from event payload.
function resolveSessionId(payload) {
    const direct = payload.properties?.sessionID;
    if (typeof direct === "string" && direct.trim()) {
        return direct.trim();
    }
    const fallback = payload.properties?.info?.id;
    if (typeof fallback === "string" && fallback.trim()) {
        return fallback.trim();
    }
    return "";
}
// Extracts last assistant text from session messages.
function lastAssistantText(messages) {
    const assistantMessages = messages.filter((item) => item.info?.role === "assistant");
    const last = assistantMessages[assistantMessages.length - 1];
    if (!last?.parts) {
        return "";
    }
    return last.parts
        .filter((part) => part.type === "text")
        .map((part) => part.text ?? "")
        .join("\n");
}
// Returns true when assistant text satisfies loop completion criteria.
function isLoopComplete(state, text) {
    const active = state.activeLoop;
    if (!active || !text.trim()) {
        return false;
    }
    if (active.completionMode === "objective") {
        return /<objective-complete>\s*true\s*<\/objective-complete>/i.test(text);
    }
    const token = active.completionPromise.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`<promise>\\s*${token}\\s*<\\/promise>`, "i").test(text);
}
// Returns true when loop reached configured finite iteration cap.
function reachedIterationCap(state) {
    const active = state.activeLoop;
    if (!active) {
        return false;
    }
    if (active.maxIterations <= 0) {
        return false;
    }
    return active.iteration >= active.maxIterations;
}
// Builds continuation prompt for active gateway loop iteration.
function continuationPrompt(state) {
    const active = state.activeLoop;
    if (!active) {
        return "Continue the current objective.";
    }
    const completionGuidance = active.completionMode === "objective"
        ? "When fully complete, emit <objective-complete>true</objective-complete>."
        : `When fully complete, emit <promise>${active.completionPromise}</promise>.`;
    return [
        `[GATEWAY LOOP ${active.iteration}/${active.maxIterations}]`,
        "Continue execution from the current state and apply concrete validated changes.",
        completionGuidance,
        "Objective:",
        active.objective,
    ].join("\n\n");
}
// Creates continuation helper hook placeholder for gateway composition.
export function createContinuationHook(options) {
    return {
        id: "continuation",
        priority: 200,
        async event(type, payload) {
            if (type !== "session.idle") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const state = loadGatewayState(directory);
            const active = state?.activeLoop;
            if (!state || !active || active.active !== true) {
                writeGatewayEventAudit(directory, {
                    hook: "continuation",
                    stage: "skip",
                    reason_code: "no_active_loop",
                });
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId || sessionId !== active.sessionId) {
                writeGatewayEventAudit(directory, {
                    hook: "continuation",
                    stage: "skip",
                    reason_code: "session_mismatch",
                    has_session_id: sessionId.length > 0,
                });
                return;
            }
            const client = options.client?.session;
            if (client) {
                const response = await client.messages({
                    path: { id: sessionId },
                    query: { directory },
                });
                const text = lastAssistantText(Array.isArray(response.data) ? response.data : []);
                if (isLoopComplete(state, text)) {
                    active.active = false;
                    state.lastUpdatedAt = nowIso();
                    state.source =
                        active.completionMode === "objective"
                            ? REASON_CODES.LOOP_COMPLETED_OBJECTIVE
                            : REASON_CODES.LOOP_COMPLETED_PROMISE;
                    saveGatewayState(directory, state);
                    writeGatewayEventAudit(directory, {
                        hook: "continuation",
                        stage: "state",
                        reason_code: state.source,
                        session_id: sessionId,
                    });
                    return;
                }
            }
            if (reachedIterationCap(state)) {
                active.active = false;
                state.lastUpdatedAt = nowIso();
                state.source = REASON_CODES.LOOP_MAX_ITERATIONS;
                saveGatewayState(directory, state);
                writeGatewayEventAudit(directory, {
                    hook: "continuation",
                    stage: "state",
                    reason_code: REASON_CODES.LOOP_MAX_ITERATIONS,
                    session_id: sessionId,
                });
                return;
            }
            active.iteration += 1;
            state.lastUpdatedAt = nowIso();
            state.source = REASON_CODES.LOOP_IDLE_CONTINUED;
            saveGatewayState(directory, state);
            writeGatewayEventAudit(directory, {
                hook: "continuation",
                stage: "state",
                reason_code: REASON_CODES.LOOP_IDLE_CONTINUED,
                session_id: sessionId,
                iteration: active.iteration,
            });
            if (client) {
                await client.promptAsync({
                    path: { id: sessionId },
                    body: { parts: [{ type: "text", text: continuationPrompt(state) }] },
                    query: { directory },
                });
                writeGatewayEventAudit(directory, {
                    hook: "continuation",
                    stage: "inject",
                    reason_code: "idle_prompt_injected",
                    session_id: sessionId,
                    iteration: active.iteration,
                });
            }
            return;
        },
    };
}
