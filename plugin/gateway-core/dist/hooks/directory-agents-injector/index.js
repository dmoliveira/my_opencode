import { basename } from "node:path";
import { findNearestFile } from "../directory-context/finder.js";
import { readFilePrefix } from "../shared/read-file-prefix.js";
import { insertStableSystemContext, stableContextLabel } from "../shared/stable-system-context.js";
import { truncateInjectedText } from "../shared/injected-text-truncator.js";
const MARKER = "Local instructions loaded from:";
function buildContextLine(path, maxChars) {
    const sourceText = readFilePrefix(path, maxChars);
    const normalized = sourceText.trim();
    let contextLine = `Local instructions loaded from: ${stableContextLabel(basename(path))}`;
    if (normalized) {
        const truncated = truncateInjectedText(normalized, maxChars);
        contextLine = `${contextLine}\n\nAGENTS.md guidance excerpt:\n${truncated.text}`;
    }
    return { text: contextLine };
}
// Injects stable local repository guidance into the system prompt once per request.
export function createDirectoryAgentsInjectorHook(options) {
    return {
        id: "directory-agents-injector",
        priority: 299,
        async event(type, payload) {
            if (!options.enabled || type !== "experimental.chat.system.transform")
                return;
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory : options.directory;
            const system = eventPayload.output?.system;
            if (!Array.isArray(system) || system.some((entry) => entry.includes(MARKER)))
                return;
            const path = findNearestFile(directory, "AGENTS.md");
            if (!path)
                return;
            insertStableSystemContext(system, buildContextLine(path, options.maxChars).text);
        },
    };
}
