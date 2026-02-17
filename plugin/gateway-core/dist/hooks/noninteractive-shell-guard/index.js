import { writeGatewayEventAudit } from "../../audit/event-audit.js";
function shouldPrefixCommand(command, prefixes) {
    const trimmed = command.trim();
    if (!trimmed) {
        return false;
    }
    return prefixes.some((prefix) => new RegExp(`^${prefix}\\b`, "i").test(trimmed));
}
function hasExistingEnvPrefix(command, envPrefixes) {
    const trimmed = command.trim();
    return envPrefixes.some((entry) => {
        const key = entry.split("=", 1)[0]?.trim();
        if (!key) {
            return false;
        }
        return new RegExp(`(^|\\s)${key}=`, "i").test(trimmed);
    });
}
function prefixCommand(command, envPrefixes) {
    const assignments = envPrefixes.map((item) => item.trim()).filter(Boolean);
    if (assignments.length === 0) {
        return command;
    }
    return `${assignments.join(" ")} ${command.trim()}`.trim();
}
// Returns first non-interactive violation message for command.
function violation(command, blockedPatterns) {
    const value = command.trim();
    if (!value) {
        return null;
    }
    for (const pattern of blockedPatterns) {
        if (pattern.test(value)) {
            return "Interactive command detected. Use non-interactive flags or scripted command execution.";
        }
    }
    const lower = value.toLowerCase();
    if (/\bnpm\s+install\b/.test(lower) && !/--yes\b/.test(lower)) {
        return "Use `npm install --yes` in non-interactive sessions.";
    }
    if (/\byarn\s+install\b/.test(lower) && !/--non-interactive\b/.test(lower)) {
        return "Use `yarn install --non-interactive` in non-interactive sessions.";
    }
    if (/\bpnpm\s+install\b/.test(lower) && !/--reporter\s*=\s*silent\b/.test(lower)) {
        return "Use `pnpm install --reporter=silent` in non-interactive sessions.";
    }
    if (/\bapt(-get)?\s+install\b/.test(lower) && !/\s-y\b/.test(lower)) {
        return "Use apt install commands with `-y` in non-interactive sessions.";
    }
    if (/^\s*(python3?|node)\s*$/.test(lower)) {
        return "REPL command detected. Use script mode (`python -c`, `node -e`, or file execution).";
    }
    if (/\bgit\s+commit\b/.test(lower) && !/\s-m\s+/.test(lower)) {
        return "Use non-interactive git commit format: `git commit -m \"message\"`.";
    }
    return null;
}
// Creates non-interactive shell guard for prompt-prone command patterns.
export function createNoninteractiveShellGuardHook(options) {
    const blockedPatterns = options.blockedPatterns
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
        id: "noninteractive-shell-guard",
        priority: 385,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "bash") {
                return;
            }
            const command = String(eventPayload.output?.args?.command ?? "").trim();
            if (!command) {
                return;
            }
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            if (options.injectEnvPrefix &&
                shouldPrefixCommand(command, options.prefixCommands) &&
                !hasExistingEnvPrefix(command, options.envPrefixes)) {
                const prefixed = prefixCommand(command, options.envPrefixes);
                if (eventPayload.output?.args) {
                    eventPayload.output.args.command = prefixed;
                }
                writeGatewayEventAudit(directory, {
                    hook: "noninteractive-shell-guard",
                    stage: "state",
                    reason_code: "noninteractive_env_prefixed",
                    session_id: sessionId,
                });
            }
            const updatedCommand = String(eventPayload.output?.args?.command ?? command).trim();
            const message = violation(updatedCommand, blockedPatterns);
            if (!message) {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "noninteractive-shell-guard",
                stage: "skip",
                reason_code: "interactive_command_blocked",
                session_id: sessionId,
            });
            throw new Error(`[noninteractive-shell-guard] ${message}`);
        },
    };
}
