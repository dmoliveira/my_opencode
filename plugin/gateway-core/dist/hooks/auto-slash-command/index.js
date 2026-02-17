import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const AUTO_SLASH_COMMAND_TAG_OPEN = "<auto-slash-command>";
const AUTO_SLASH_COMMAND_TAG_CLOSE = "</auto-slash-command>";
const SLASH_COMMAND_PATTERN = /^\/([a-zA-Z][\w-]*)\s*(.*)/;
const EXCLUDED_COMMANDS = new Set(["ulw-loop"]);
const INLINE_SLASH_TOKEN_PATTERN = /(^|\s)\/([a-zA-Z][\w-]*)\b/g;
// Removes fenced code blocks before slash-command detection.
function removeCodeBlocks(text) {
    return text.replace(/```[\s\S]*?```/g, "");
}
// Returns true when slash command is excluded from auto handling.
function isExcludedCommand(command) {
    return EXCLUDED_COMMANDS.has(command.toLowerCase());
}
// Parses an explicit slash command input.
function parseSlashCommand(text) {
    const trimmed = text.trim();
    if (!trimmed.startsWith("/")) {
        return null;
    }
    const match = trimmed.match(SLASH_COMMAND_PATTERN);
    if (!match) {
        return null;
    }
    const [, command, args] = match;
    const normalized = command.toLowerCase();
    if (isExcludedCommand(normalized)) {
        return null;
    }
    return {
        command: normalized,
        args: args.trim(),
        raw: trimmed,
    };
}
// Returns true when slash text targets an excluded command.
function isExcludedExplicitSlash(text) {
    INLINE_SLASH_TOKEN_PATTERN.lastIndex = 0;
    let match;
    while ((match = INLINE_SLASH_TOKEN_PATTERN.exec(text)) !== null) {
        const command = match[2]?.toLowerCase() ?? "";
        if (command && isExcludedCommand(command)) {
            return true;
        }
    }
    return false;
}
// Builds tagged injection payload for slash-command transformations.
function taggedSlashCommand(rawCommand) {
    return `${AUTO_SLASH_COMMAND_TAG_OPEN}\n${rawCommand}\n${AUTO_SLASH_COMMAND_TAG_CLOSE}`;
}
// Finds best text part index for slash command replacements.
function findSlashCommandPartIndex(parts) {
    for (let idx = 0; idx < parts.length; idx += 1) {
        const part = parts[idx];
        if (part.type !== "text") {
            continue;
        }
        if ((part.text ?? "").trim().startsWith("/")) {
            return idx;
        }
    }
    return parts.findIndex((part) => part.type === "text");
}
// Finds text part index that already contains explicit slash command text.
function findExplicitSlashPartIndex(parts) {
    for (let idx = 0; idx < parts.length; idx += 1) {
        const part = parts[idx];
        if (part.type !== "text") {
            continue;
        }
        if ((part.text ?? "").trim().startsWith("/")) {
            return idx;
        }
    }
    return -1;
}
// Extracts user prompt text from chat payload input/output variants.
function promptText(payload) {
    const props = payload.properties ?? {};
    const direct = [props.prompt, props.message, props.text];
    for (const candidate of direct) {
        if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
        }
    }
    const partSources = [payload.output?.parts, props.parts];
    for (const parts of partSources) {
        if (!Array.isArray(parts)) {
            continue;
        }
        const slashPart = parts.find((part) => part?.type === "text" && typeof part.text === "string" && part.text.trim().startsWith("/"));
        if (slashPart?.text?.trim()) {
            return slashPart.text.trim();
        }
        const text = parts
            .filter((part) => part?.type === "text" && typeof part.text === "string")
            .filter((part) => !part.synthetic)
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
    const cleaned = removeCodeBlocks(prompt);
    if (isExcludedExplicitSlash(cleaned)) {
        return { slash: null, excludedExplicit: true };
    }
    const explicit = parseSlashCommand(cleaned);
    if (explicit) {
        return { slash: explicit.raw, excludedExplicit: false };
    }
    const text = cleaned.toLowerCase();
    if (text.includes("doctor") || text.includes("diagnose") || text.includes("health check")) {
        return { slash: "/doctor", excludedExplicit: false };
    }
    return { slash: null, excludedExplicit: false };
}
// Creates auto slash command hook that rewrites prompt text when output parts are mutable.
export function createAutoSlashCommandHook(options) {
    return {
        id: "auto-slash-command",
        priority: 297,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "chat.message") {
                const eventPayload = (payload ?? {});
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const sessionId = eventPayload.properties?.sessionID;
                const prompt = promptText(eventPayload);
                if (!prompt) {
                    return;
                }
                const detection = detectSlash(prompt);
                if (detection.excludedExplicit || !detection.slash) {
                    return;
                }
                const slash = detection.slash;
                const parts = eventPayload.output?.parts;
                const idx = Array.isArray(parts) ? findSlashCommandPartIndex(parts) : -1;
                if (idx >= 0 && parts) {
                    parts[idx].text = taggedSlashCommand(slash);
                }
                else {
                    return;
                }
                writeGatewayEventAudit(directory, {
                    hook: "auto-slash-command",
                    stage: "state",
                    reason_code: "auto_slash_command_detected",
                    session_id: typeof sessionId === "string" ? sessionId : "",
                    slash_command: slash,
                });
                return;
            }
            if (type !== "command.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = eventPayload.input?.sessionID;
            const command = typeof eventPayload.input?.command === "string" ? eventPayload.input.command.trim() : "";
            const args = typeof eventPayload.input?.arguments === "string" && eventPayload.input.arguments.trim()
                ? eventPayload.input.arguments.trim()
                : "";
            if (!command || isExcludedCommand(command)) {
                return;
            }
            const raw = `/${command}${args ? ` ${args}` : ""}`;
            if (eventPayload.output && !Array.isArray(eventPayload.output.parts)) {
                eventPayload.output.parts = [];
            }
            const parts = eventPayload.output?.parts;
            const tagged = taggedSlashCommand(raw);
            const idx = Array.isArray(parts) ? findExplicitSlashPartIndex(parts) : -1;
            if (idx >= 0 && parts) {
                parts[idx].text = tagged;
            }
            else if (Array.isArray(parts)) {
                parts.unshift({ type: "text", text: tagged });
            }
            else {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "auto-slash-command",
                stage: "state",
                reason_code: "auto_slash_command_detected",
                session_id: typeof sessionId === "string" ? sessionId : "",
                slash_command: raw,
            });
        },
    };
}
