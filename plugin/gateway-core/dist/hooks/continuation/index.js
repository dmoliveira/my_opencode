import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
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
// Resolves autopilot runtime file path for plugin bootstrap fallback.
function autopilotRuntimePath() {
    const explicit = String(process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH || "").trim();
    if (explicit) {
        return explicit;
    }
    const home = String(process.env.HOME || "").trim();
    if (!home) {
        return "";
    }
    return join(home, ".config", "opencode", "my_opencode", "runtime", "autopilot_runtime.json");
}
// Loads autopilot runtime payload for loop bootstrap fallback.
function loadAutopilotRuntime() {
    const path = autopilotRuntimePath();
    if (!path || !existsSync(path)) {
        return null;
    }
    try {
        const parsed = JSON.parse(readFileSync(path, "utf-8"));
        return parsed && typeof parsed === "object" ? parsed : null;
    }
    catch {
        return null;
    }
}
// Bootstraps gateway loop state from autopilot runtime when start-hook capture is missing.
function bootstrapLoopFromRuntime(directory, sessionId) {
    const runtime = loadAutopilotRuntime();
    if (!runtime) {
        return null;
    }
    const status = String(runtime.status || "").trim().toLowerCase();
    if (status !== "running") {
        return null;
    }
    const objective = runtime.objective && typeof runtime.objective === "object" ? runtime.objective : {};
    const goal = String(objective.goal || "").trim();
    if (!goal) {
        return null;
    }
    const completionMode = String(objective.completion_mode || "").trim().toLowerCase() === "objective"
        ? "objective"
        : "promise";
    const completionPromise = String(objective.completion_promise || "DONE").trim() || "DONE";
    const progress = runtime.progress && typeof runtime.progress === "object" ? runtime.progress : {};
    const completedCycles = Number.parseInt(String(progress.completed_cycles ?? "0"), 10);
    const iteration = Number.isFinite(completedCycles) && completedCycles >= 0 ? completedCycles + 1 : 1;
    const state = {
        activeLoop: {
            active: true,
            sessionId,
            objective: goal,
            completionMode,
            completionPromise,
            iteration,
            maxIterations: 0,
            startedAt: nowIso(),
        },
        lastUpdatedAt: nowIso(),
        source: REASON_CODES.LOOP_RUNTIME_BOOTSTRAPPED,
    };
    saveGatewayState(directory, state);
    return state;
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
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                writeGatewayEventAudit(directory, {
                    hook: "continuation",
                    stage: "skip",
                    reason_code: "missing_session_id",
                });
                return;
            }
            let state = loadGatewayState(directory);
            let active = state?.activeLoop;
            if (!state || !active || active.active !== true) {
                const bootstrapped = bootstrapLoopFromRuntime(directory, sessionId);
                if (bootstrapped?.activeLoop?.active) {
                    state = bootstrapped;
                    active = bootstrapped.activeLoop;
                    writeGatewayEventAudit(directory, {
                        hook: "continuation",
                        stage: "state",
                        reason_code: REASON_CODES.LOOP_RUNTIME_BOOTSTRAPPED,
                        session_id: sessionId,
                    });
                }
            }
            if (!state || !active || active.active !== true) {
                writeGatewayEventAudit(directory, {
                    hook: "continuation",
                    stage: "skip",
                    reason_code: "no_active_loop",
                });
                return;
            }
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
