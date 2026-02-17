import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { REASON_CODES } from "../../bridge/reason-codes.js";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadGatewayState, nowIso, saveGatewayState } from "../../state/storage.js";
import { injectHookMessage } from "../hook-message-injector/index.js";
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
// Parses runtime done-criteria payload into normalized list.
function normalizeDoneCriteria(raw) {
    if (Array.isArray(raw)) {
        return raw.map((item) => String(item || "").trim()).filter(Boolean);
    }
    if (typeof raw === "string" && raw.trim()) {
        return raw
            .split(/[;\n]+/)
            .map((item) => item.trim())
            .filter(Boolean);
    }
    return [];
}
// Returns true when runtime progress/blockers indicate completion token should be ignored.
function runtimeBlocksCompletion(runtime, state) {
    if (!runtime || typeof runtime !== "object") {
        return false;
    }
    const status = String(runtime.status ?? "")
        .trim()
        .toLowerCase();
    if (status && status !== "running") {
        return false;
    }
    const runtimeObjective = runtime.objective && typeof runtime.objective === "object" ? runtime.objective : {};
    const runtimeGoal = String(runtimeObjective.goal ?? "").trim();
    const activeGoal = String(state.activeLoop?.objective ?? "").trim();
    if (runtimeGoal && activeGoal && runtimeGoal !== activeGoal) {
        return false;
    }
    const progress = runtime.progress && typeof runtime.progress === "object" ? runtime.progress : {};
    const pendingCycles = Number.parseInt(String(progress.pending_cycles ?? "0"), 10);
    if (Number.isFinite(pendingCycles) && pendingCycles > 0) {
        return true;
    }
    const blockers = Array.isArray(runtime.blockers)
        ? runtime.blockers.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
    return blockers.length > 0;
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
    const doneCriteria = [
        ...normalizeDoneCriteria(objective.done_criteria),
        ...normalizeDoneCriteria(objective["done-criteria"]),
    ];
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
            doneCriteria,
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
function continuationPrompt(state, mode) {
    const active = state.activeLoop;
    if (!active) {
        return "Continue the current objective.";
    }
    const completionGuidance = active.completionMode === "objective"
        ? "When fully complete, emit <objective-complete>true</objective-complete>."
        : `When fully complete, emit <promise>${active.completionPromise}</promise>.`;
    const criteria = Array.isArray(active.doneCriteria) ? active.doneCriteria : [];
    const criteriaBlock = criteria.length
        ? [
            "Done Criteria (execute each item before completion):",
            ...criteria.map((item, index) => `${index + 1}. ${item}`),
        ].join("\n")
        : "Done Criteria: use the objective and prior context; do not ask for additional checklist items unless no criteria exist.";
    const capLabel = active.maxIterations > 0 ? String(active.maxIterations) : "INF";
    const modeGuidance = mode === "ultrawork"
        ? "Mode: ultrawork. Use maximum rigor, validate each change, and delegate specialist tasks when beneficial."
        : mode === "analyze"
            ? "Mode: analyze. Prioritize diagnosis, root-cause reasoning, and explicit evidence before edits."
            : mode === "search"
                ? "Mode: search. Prioritize discovery, map candidate files first, then apply focused edits."
                : "";
    return [
        `[GATEWAY LOOP ${active.iteration}/${capLabel}]`,
        "Continue execution from the current state and apply concrete validated changes.",
        "Do not ask the user for checklist items when done criteria are already present; execute them directly.",
        modeGuidance,
        completionGuidance,
        "Objective:",
        active.objective,
        criteriaBlock,
    ]
        .filter(Boolean)
        .join("\n\n");
}
// Creates continuation helper hook placeholder for gateway composition.
export function createContinuationHook(options) {
    const maxIgnoredCompletionCycles = Number.isFinite(options.maxIgnoredCompletionCycles) &&
        Number.parseInt(String(options.maxIgnoredCompletionCycles), 10) > 0
        ? Number.parseInt(String(options.maxIgnoredCompletionCycles), 10)
        : 3;
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
            if (options.bootstrapFromRuntime && (!state || !active || active.active !== true)) {
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
            if (options.stopGuard?.isStopped(sessionId)) {
                writeGatewayEventAudit(directory, {
                    hook: "continuation",
                    stage: "skip",
                    reason_code: "stop_guard_active",
                    session_id: sessionId,
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
                    const runtime = loadAutopilotRuntime();
                    if (runtimeBlocksCompletion(runtime, state)) {
                        const ignoredCycles = Number.isFinite(active.ignoredCompletionCycles) &&
                            Number.parseInt(String(active.ignoredCompletionCycles), 10) >= 0
                            ? Number.parseInt(String(active.ignoredCompletionCycles), 10) + 1
                            : 1;
                        active.ignoredCompletionCycles = ignoredCycles;
                        if (ignoredCycles >= maxIgnoredCompletionCycles) {
                            active.active = false;
                            state.lastUpdatedAt = nowIso();
                            state.source = REASON_CODES.LOOP_COMPLETION_STALLED_RUNTIME;
                            saveGatewayState(directory, state);
                            writeGatewayEventAudit(directory, {
                                hook: "continuation",
                                stage: "state",
                                reason_code: REASON_CODES.LOOP_COMPLETION_STALLED_RUNTIME,
                                session_id: sessionId,
                                ignored_completion_cycles: ignoredCycles,
                            });
                            return;
                        }
                        state.lastUpdatedAt = nowIso();
                        saveGatewayState(directory, state);
                        writeGatewayEventAudit(directory, {
                            hook: "continuation",
                            stage: "skip",
                            reason_code: REASON_CODES.LOOP_COMPLETION_IGNORED_INCOMPLETE_RUNTIME,
                            session_id: sessionId,
                            ignored_completion_cycles: ignoredCycles,
                        });
                    }
                    else {
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
                else {
                    if ((active.ignoredCompletionCycles ?? 0) > 0) {
                        active.ignoredCompletionCycles = 0;
                        state.lastUpdatedAt = nowIso();
                        saveGatewayState(directory, state);
                    }
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
                const mode = options.keywordDetector?.modeForSession(sessionId) ?? null;
                await injectHookMessage({
                    session: client,
                    sessionId,
                    content: continuationPrompt(state, mode),
                    directory,
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
