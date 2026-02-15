import { parseCompletionMode, parseCompletionPromise, parseGoal, parseMaxIterations, parseSlashCommand, resolveAutopilotAction, } from "../../bridge/commands.js";
import { REASON_CODES } from "../../bridge/reason-codes.js";
import { nowIso, saveGatewayState } from "../../state/storage.js";
// Resolves session id across plugin host payload variants.
function resolveSessionId(payload) {
    const candidates = [
        payload.input?.sessionID,
        payload.input?.sessionId,
        payload.properties?.sessionID,
        payload.properties?.sessionId,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Resolves slash command text across plugin host payload variants.
function resolveCommand(payload) {
    const candidates = [
        payload.output?.args?.command,
        payload.input?.args?.command,
        payload.properties?.command,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Resolves effective working directory from event payload.
function payloadDirectory(payload, fallback) {
    if (!payload || typeof payload !== "object") {
        return fallback;
    }
    const record = payload;
    return typeof record.directory === "string" && record.directory.trim()
        ? record.directory
        : fallback;
}
// Creates autopilot loop hook placeholder for gateway composition.
export function createAutopilotLoopHook(options) {
    return {
        id: "autopilot-loop",
        priority: 100,
        async event(type, payload) {
            if (type !== "tool.execute.before") {
                return;
            }
            const scopedDir = payloadDirectory(payload, options.directory);
            const eventPayload = (payload ?? {});
            const input = eventPayload.input;
            const output = eventPayload.output;
            if (input?.tool !== "slashcommand") {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            const commandRaw = resolveCommand(eventPayload);
            if (!sessionId || !commandRaw) {
                return;
            }
            const parsed = parseSlashCommand(commandRaw);
            const action = resolveAutopilotAction(parsed.name, parsed.args);
            if (action === "none") {
                return;
            }
            if (action === "stop") {
                const state = {
                    activeLoop: {
                        active: false,
                        sessionId,
                        objective: "stop requested",
                        completionMode: options.defaults.completionMode,
                        completionPromise: options.defaults.completionPromise,
                        iteration: 1,
                        maxIterations: options.defaults.maxIterations,
                        startedAt: nowIso(),
                    },
                    lastUpdatedAt: nowIso(),
                    source: REASON_CODES.LOOP_STOPPED,
                };
                saveGatewayState(scopedDir, state);
                return;
            }
            if (!options.defaults.enabled) {
                return;
            }
            const completionMode = parsed.name === "autopilot-objective"
                ? "objective"
                : parseCompletionMode(parsed.args);
            const state = {
                activeLoop: {
                    active: true,
                    sessionId,
                    objective: parseGoal(parsed.args),
                    completionMode,
                    completionPromise: parseCompletionPromise(parsed.args, options.defaults.completionPromise),
                    iteration: 1,
                    maxIterations: parseMaxIterations(parsed.args, options.defaults.maxIterations),
                    startedAt: nowIso(),
                },
                lastUpdatedAt: nowIso(),
                source: REASON_CODES.LOOP_STARTED,
            };
            saveGatewayState(scopedDir, state);
            return;
        },
    };
}
