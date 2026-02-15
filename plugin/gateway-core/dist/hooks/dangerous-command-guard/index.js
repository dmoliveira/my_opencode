import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Creates dangerous command guard hook for destructive shell command prevention.
export function createDangerousCommandGuardHook(options) {
    const compiled = options.blockedPatterns
        .map((pattern) => {
        try {
            return new RegExp(pattern, "i");
        }
        catch {
            return null;
        }
    })
        .filter((value) => value !== null);
    return {
        id: "dangerous-command-guard",
        priority: 390,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim();
            if (!command) {
                return;
            }
            const matched = compiled.find((regex) => regex.test(command));
            if (!matched) {
                return;
            }
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            writeGatewayEventAudit(directory, {
                hook: "dangerous-command-guard",
                stage: "skip",
                reason_code: "dangerous_command_blocked",
                session_id: sessionId,
            });
            throw new Error("Blocked dangerous bash command. Use a safer alternative or perform the action manually outside gateway automation.");
        },
    };
}
