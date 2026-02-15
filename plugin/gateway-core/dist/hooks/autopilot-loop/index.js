import { parseCompletionMode, parseCompletionPromise, parseGoal, parseMaxIterations, parseSlashCommand, resolveAutopilotAction, } from "../../bridge/commands.js";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
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
            const sessionId = resolveSessionId(eventPayload);
            const commandRaw = resolveCommand(eventPayload);
            if (!sessionId || !commandRaw) {
                writeGatewayEventAudit(scopedDir, {
                    hook: "autopilot-loop",
                    stage: "skip",
                    reason_code: "missing_session_or_command",
                    has_session_id: sessionId.length > 0,
                    has_command: commandRaw.length > 0,
                });
                return;
            }
            const parsed = parseSlashCommand(commandRaw);
            const toolName = String(input?.tool || "");
            if (!commandRaw.trim().startsWith("/") && toolName !== "slashcommand") {
                writeGatewayEventAudit(scopedDir, {
                    hook: "autopilot-loop",
                    stage: "skip",
                    reason_code: "non_slash_tool",
                    tool: toolName,
                });
                return;
            }
            const action = resolveAutopilotAction(parsed.name, parsed.args);
            if (action === "none") {
                writeGatewayEventAudit(scopedDir, {
                    hook: "autopilot-loop",
                    stage: "skip",
                    reason_code: "non_autopilot_command",
                    command: parsed.name,
                });
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
                writeGatewayEventAudit(scopedDir, {
                    hook: "autopilot-loop",
                    stage: "state",
                    reason_code: REASON_CODES.LOOP_STOPPED,
                    session_id: sessionId,
                    command: parsed.name,
                });
                return;
            }
            if (!options.defaults.enabled) {
                writeGatewayEventAudit(scopedDir, {
                    hook: "autopilot-loop",
                    stage: "skip",
                    reason_code: "autopilot_loop_disabled",
                    command: parsed.name,
                });
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
            writeGatewayEventAudit(scopedDir, {
                hook: "autopilot-loop",
                stage: "state",
                reason_code: REASON_CODES.LOOP_STARTED,
                session_id: sessionId,
                command: parsed.name,
                completion_mode: completionMode,
            });
            return;
        },
    };
}
