import { parseAutopilotTemplateCommand, parseSlashCommand, resolveAutopilotAction, } from "../../bridge/commands.js";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Resolves session id across payload variants.
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
// Resolves command text across payload variants.
function resolveCommand(payload) {
    const commandName = typeof payload.input?.command === "string" && payload.input.command.trim()
        ? payload.input.command.trim().replace(/^\//, "")
        : "";
    const commandArgs = typeof payload.input?.arguments === "string" && payload.input.arguments.trim()
        ? payload.input.arguments.trim()
        : "";
    const commandExecuteBefore = commandName
        ? `/${commandName}${commandArgs ? ` ${commandArgs}` : ""}`
        : "";
    const candidates = [
        payload.output?.args?.command,
        payload.input?.args?.command,
        payload.properties?.command,
        commandExecuteBefore,
    ];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Creates continuation stop guard hook and shared state query API.
export function createStopContinuationGuardHook(options) {
    const stoppedSessions = new Set();
    return {
        id: "stop-continuation-guard",
        priority: 295,
        isStopped(sessionId) {
            return stoppedSessions.has(sessionId);
        },
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "chat.message") {
                const chatPayload = (payload ?? {});
                const sessionId = chatPayload.properties?.sessionID;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    stoppedSessions.delete(sessionId.trim());
                }
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    stoppedSessions.delete(sessionId.trim());
                }
                return;
            }
            if (type !== "tool.execute.before" && type !== "command.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            const command = resolveCommand(eventPayload);
            if (!sessionId || !command) {
                return;
            }
            const toolName = String(eventPayload.input?.tool || "");
            let parsed = parseSlashCommand(command);
            if (!command.trim().startsWith("/") && toolName !== "slashcommand") {
                const templateParsed = parseAutopilotTemplateCommand(command);
                if (templateParsed) {
                    parsed = templateParsed;
                }
                else {
                    return;
                }
            }
            const action = resolveAutopilotAction(parsed.name, parsed.args);
            if (action !== "stop") {
                return;
            }
            stoppedSessions.add(sessionId);
            writeGatewayEventAudit(directory, {
                hook: "stop-continuation-guard",
                stage: "state",
                reason_code: "continuation_stopped",
                session_id: sessionId,
            });
        },
    };
}
