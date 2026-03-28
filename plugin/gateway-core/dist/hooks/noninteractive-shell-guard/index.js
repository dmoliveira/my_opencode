import { writeGatewayEventAudit } from "../../audit/event-audit.js";
function baseCommandName(binary) {
    const normalized = binary.trim().toLowerCase();
    if (!normalized) {
        return "";
    }
    const parts = normalized.split("/");
    return parts[parts.length - 1] ?? normalized;
}
function tokenizeShellWords(command) {
    const tokens = [];
    let current = "";
    let quote = null;
    for (let index = 0; index < command.length; index += 1) {
        const char = command[index] ?? "";
        if (quote) {
            if (char === quote) {
                quote = null;
            }
            else if (char === "\\" && quote === '"' && index + 1 < command.length) {
                current += command[index + 1] ?? "";
                index += 1;
            }
            else {
                current += char;
            }
            continue;
        }
        if (char === '"' || char === "'") {
            quote = char;
            continue;
        }
        if (/\s/.test(char)) {
            if (current) {
                tokens.push(current);
                current = "";
            }
            continue;
        }
        if (char === "\\" && index + 1 < command.length) {
            current += command[index + 1] ?? "";
            index += 1;
            continue;
        }
        current += char;
    }
    if (current) {
        tokens.push(current);
    }
    return tokens;
}
function shouldPrefixCommand(command, prefixes) {
    const binary = baseCommandName(parseCommand(command).binary);
    if (!binary) {
        return false;
    }
    return prefixes.some((prefix) => binary === prefix.toLowerCase());
}
function envKey(entry) {
    return entry.split("=", 1)[0]?.trim() ?? "";
}
function hasEnvAssignment(command, key) {
    return new RegExp(`(^|\\s)${key}=`, "i").test(command.trim());
}
function commandBinary(command) {
    return baseCommandName(parseCommand(command).binary);
}
function parseCommand(command) {
    const tokens = tokenizeShellWords(command.trim());
    let index = 0;
    while (index < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[index] ?? "")) {
        index += 1;
    }
    if ((tokens[index] ?? "").toLowerCase() === "env") {
        index += 1;
        while (index < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[index] ?? "")) {
            index += 1;
        }
    }
    const filtered = tokens.slice(index);
    if (filtered.length === 0) {
        return { binary: "", args: [] };
    }
    const [first, second, ...rest] = filtered;
    const normalizedFirst = first?.toLowerCase() ?? "";
    if (normalizedFirst.endsWith("/rtk") || normalizedFirst === "rtk") {
        const wrappedBinary = second?.toLowerCase() ?? "";
        return {
            binary: wrappedBinary,
            args: second ? [second, ...rest] : [],
        };
    }
    return {
        binary: normalizedFirst,
        args: [first, second, ...rest].filter((item) => Boolean(item)),
    };
}
function allowedEnvKeys(command) {
    const binary = commandBinary(command);
    if (binary === "git" || binary === "gh") {
        return new Set(["CI", "GIT_TERMINAL_PROMPT", "GIT_EDITOR", "GIT_PAGER", "PAGER", "GCM_INTERACTIVE", "OPENCODE_SESSION_ID"]);
    }
    return new Set();
}
function shellQuoteEnvValue(value) {
    return `'${value.replace(/'/g, `'"'"'`)}'`;
}
function sessionEnvPrefixes(sessionId) {
    const normalized = sessionId.trim();
    if (!normalized) {
        return [];
    }
    return [`OPENCODE_SESSION_ID=${shellQuoteEnvValue(normalized)}`];
}
function prefixCommand(command, envPrefixes) {
    const allowlist = allowedEnvKeys(command);
    const assignments = envPrefixes
        .map((item) => item.trim())
        .filter(Boolean)
        .filter((entry) => {
        if (allowlist.size === 0) {
            return true;
        }
        const key = envKey(entry);
        return key ? allowlist.has(key) : false;
    })
        .filter((entry) => {
        const key = envKey(entry);
        if (!key) {
            return false;
        }
        return !hasEnvAssignment(command, key);
    });
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
    const parsed = parseCommand(value);
    const binary = baseCommandName(parsed.binary);
    const argsLower = parsed.args.map((item) => item.toLowerCase());
    if (binary === "npm" && /\bnpm\s+install\b/.test(lower) && !/--yes\b/.test(lower)) {
        return "Use `npm install --yes` in non-interactive sessions.";
    }
    if (binary === "yarn" && /\byarn\s+install\b/.test(lower) && !/--non-interactive\b/.test(lower)) {
        return "Use `yarn install --non-interactive` in non-interactive sessions.";
    }
    if (binary === "pnpm" && /\bpnpm\s+install\b/.test(lower) && !/--reporter\s*=\s*silent\b/.test(lower)) {
        return "Use `pnpm install --reporter=silent` in non-interactive sessions.";
    }
    if ((binary === "apt" || binary === "apt-get") && /\bapt(-get)?\s+install\b/.test(lower) && !/\s-y\b/.test(lower)) {
        return "Use apt install commands with `-y` in non-interactive sessions.";
    }
    if (binary === "python" || binary === "python3" || binary === "node") {
        if (parsed.args.length <= 1) {
            return "REPL command detected. Use script mode (`python -c`, `node -e`, or file execution).";
        }
    }
    if (/^\s*(python3?|node)\s*$/.test(lower)) {
        return "REPL command detected. Use script mode (`python -c`, `node -e`, or file execution).";
    }
    if (binary === "git" && argsLower[1] === "commit") {
        if (!argsLower.some((item, index) => item === "-m" || item.startsWith("-m") || argsLower[index - 1] === "-m")) {
            return "Use non-interactive git commit format: `git commit -m \"message\"`.";
        }
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
            const sessionPrefixed = prefixCommand(command, sessionEnvPrefixes(sessionId));
            if (sessionPrefixed !== command && eventPayload.output?.args) {
                eventPayload.output.args.command = sessionPrefixed;
                writeGatewayEventAudit(directory, {
                    hook: "noninteractive-shell-guard",
                    stage: "state",
                    reason_code: "runtime_session_env_prefixed",
                    session_id: sessionId,
                });
            }
            const commandWithSessionEnv = String(eventPayload.output?.args?.command ?? command).trim();
            if (options.injectEnvPrefix &&
                shouldPrefixCommand(command, options.prefixCommands)) {
                const prefixed = prefixCommand(commandWithSessionEnv, options.envPrefixes);
                if (prefixed !== commandWithSessionEnv && eventPayload.output?.args) {
                    eventPayload.output.args.command = prefixed;
                    writeGatewayEventAudit(directory, {
                        hook: "noninteractive-shell-guard",
                        stage: "state",
                        reason_code: "noninteractive_env_prefixed",
                        session_id: sessionId,
                    });
                }
            }
            const updatedCommand = String(eventPayload.output?.args?.command ?? commandWithSessionEnv).trim();
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
