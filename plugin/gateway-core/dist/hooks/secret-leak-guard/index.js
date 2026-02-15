import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Creates secret leak guard hook that redacts likely secrets from tool outputs.
export function createSecretLeakGuardHook(options) {
    const compiled = options.patterns
        .map((pattern) => {
        try {
            return new RegExp(pattern, "g");
        }
        catch {
            return null;
        }
    })
        .filter((value) => value !== null);
    return {
        id: "secret-leak-guard",
        priority: 395,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            let text = eventPayload.output.output;
            let redacted = false;
            for (const regex of compiled) {
                const next = text.replace(regex, options.redactionToken);
                if (next !== text) {
                    redacted = true;
                    text = next;
                }
            }
            if (!redacted) {
                return;
            }
            eventPayload.output.output = text;
            writeGatewayEventAudit(directory, {
                hook: "secret-leak-guard",
                stage: "state",
                reason_code: "secret_output_redacted",
                session_id: sessionId,
            });
        },
    };
}
