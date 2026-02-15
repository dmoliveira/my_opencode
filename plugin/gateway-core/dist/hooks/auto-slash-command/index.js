import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Extracts user prompt text from chat payload input/output variants.
function promptText(payload) {
    const props = payload.properties ?? {};
    const direct = [props.prompt, props.message, props.text];
    for (const candidate of direct) {
        if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
        }
    }
    const partSources = [props.parts, payload.output?.parts];
    for (const parts of partSources) {
        if (!Array.isArray(parts)) {
            continue;
        }
        const text = parts
            .filter((part) => part?.type === "text" && typeof part.text === "string")
            .map((part) => part.text?.trim() ?? "")
            .filter(Boolean)
            .join("\n");
        if (text) {
            return text;
        }
    }
    return "";
}
// Maps natural language prompts to slash commands.
function detectSlash(prompt) {
    const text = prompt.toLowerCase();
    if (text.includes("doctor") || text.includes("diagnose") || text.includes("health check")) {
        return "/doctor";
    }
    if (text.includes("focus mode")) {
        return "/stack apply focus";
    }
    if (text.includes("research mode")) {
        return "/stack apply research";
    }
    if ((text.includes("nvim") || text.includes("neovim")) && text.includes("install")) {
        return "/nvim install minimal --link-init";
    }
    if (text.includes("devtools") && text.includes("install")) {
        return "/devtools install all";
    }
    return null;
}
// Creates auto slash command hook that rewrites prompt text when output parts are mutable.
export function createAutoSlashCommandHook(options) {
    return {
        id: "auto-slash-command",
        priority: 297,
        async event(type, payload) {
            if (!options.enabled || type !== "chat.message") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = eventPayload.properties?.sessionID;
            const prompt = promptText(eventPayload);
            if (!prompt || prompt.trim().startsWith("/")) {
                return;
            }
            const slash = detectSlash(prompt);
            if (!slash) {
                return;
            }
            const parts = eventPayload.output?.parts;
            const idx = Array.isArray(parts) ? parts.findIndex((part) => part.type === "text") : -1;
            if (idx >= 0 && parts) {
                parts[idx].text = slash;
            }
            writeGatewayEventAudit(directory, {
                hook: "auto-slash-command",
                stage: "state",
                reason_code: "auto_slash_command_detected",
                session_id: typeof sessionId === "string" ? sessionId : "",
                slash_command: slash,
            });
        },
    };
}
