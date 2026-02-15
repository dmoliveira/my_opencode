// Parses a slash command name and argument suffix.
export function parseSlashCommand(raw) {
    const trimmed = raw.trim().replace(/^\//, "");
    if (!trimmed) {
        return { name: "", args: "" };
    }
    const [name, ...tail] = trimmed.split(/\s+/);
    return {
        name: name.toLowerCase(),
        args: tail.join(" ").trim(),
    };
}
const AUTOPILOT_START_COMMANDS = new Set([
    "autopilot",
    "autopilot-go",
    "autopilot-resume",
    "continue-work",
    "autopilot-objective",
]);
const AUTOPILOT_STOP_COMMANDS = new Set(["autopilot-stop", "autopilot-pause"]);
const AUTOPILOT_COMPAT_START_ALIASES = new Set(["ralph-loop"]);
const AUTOPILOT_COMPAT_STOP_ALIASES = new Set(["cancel-ralph"]);
// Normalizes compatibility aliases to canonical autopilot command names.
export function canonicalAutopilotCommandName(name) {
    if (AUTOPILOT_COMPAT_START_ALIASES.has(name)) {
        return "autopilot-go";
    }
    if (AUTOPILOT_COMPAT_STOP_ALIASES.has(name)) {
        return "autopilot-stop";
    }
    return name;
}
// Resolves action semantics for autopilot command names and argument forms.
export function resolveAutopilotAction(name, args) {
    const command = canonicalAutopilotCommandName(name);
    if (isAutopilotStopCommand(command)) {
        return "stop";
    }
    if (!isAutopilotCommand(command)) {
        return "none";
    }
    if (command === "autopilot") {
        const head = args.trim().split(/\s+/)[0]?.toLowerCase() ?? "";
        if (head === "stop" || head === "pause") {
            return "stop";
        }
    }
    return "start";
}
// Returns true when command should start or continue autopilot loop.
export function isAutopilotCommand(name) {
    return AUTOPILOT_START_COMMANDS.has(name) || AUTOPILOT_COMPAT_START_ALIASES.has(name);
}
// Returns true when command should stop active autopilot loop.
export function isAutopilotStopCommand(name) {
    return AUTOPILOT_STOP_COMMANDS.has(name) || AUTOPILOT_COMPAT_STOP_ALIASES.has(name);
}
// Parses completion mode from command argument string.
export function parseCompletionMode(args) {
    const explicit = args.match(/--completion-mode\s+(promise|objective)/i);
    if (explicit?.[1]?.toLowerCase() === "objective") {
        return "objective";
    }
    return "promise";
}
// Parses completion promise token from command argument string.
export function parseCompletionPromise(args, fallback) {
    const quoted = args.match(/--completion-promise\s+"([^"]+)"/i);
    if (quoted?.[1]?.trim()) {
        return quoted[1].trim();
    }
    const plain = args.match(/--completion-promise\s+([^\s]+)/i);
    if (plain?.[1]?.trim()) {
        return plain[1].trim();
    }
    return fallback;
}
// Parses iteration cap from command argument string.
export function parseMaxIterations(args, fallback) {
    const match = args.match(/--max-iterations\s+(\d+)/i);
    if (!match) {
        return fallback;
    }
    const parsed = Number.parseInt(match[1], 10);
    if (!Number.isFinite(parsed) || parsed < 0) {
        return fallback;
    }
    return parsed;
}
// Parses goal text from command argument string.
export function parseGoal(args) {
    const goal = args.match(/--goal\s+"([^"]+)"/i);
    if (goal?.[1]?.trim()) {
        return goal[1].trim();
    }
    const quoted = args.match(/^"([^"]+)"/);
    if (quoted?.[1]?.trim()) {
        return quoted[1].trim();
    }
    const stripped = args
        .replace(/--[a-z-]+\s+"[^"]+"/gi, "")
        .replace(/--[a-z-]+\s+[^\s]+/gi, "")
        .trim();
    return stripped || "continue current objective until done";
}
