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
// Parses rendered autopilot command-template invocations into logical command semantics.
export function parseAutopilotTemplateCommand(raw) {
    const trimmed = raw.trim();
    if (!trimmed || !/autopilot_command\.py/i.test(trimmed)) {
        return null;
    }
    const match = trimmed.match(/autopilot_command\.py["']?\s+([a-z-]+)(.*)$/i);
    if (!match) {
        return null;
    }
    const subcommand = String(match[1] || "").trim().toLowerCase();
    const args = String(match[2] || "").trim();
    const map = {
        go: "autopilot-go",
        start: "autopilot",
        resume: "autopilot-resume",
        pause: "autopilot-pause",
        stop: "autopilot-stop",
    };
    const name = map[subcommand];
    if (!name) {
        return null;
    }
    return { name, args };
}
const AUTOPILOT_START_COMMANDS = new Set([
    "autopilot",
    "autopilot-go",
    "autopilot-resume",
    "continue-work",
    "autopilot-objective",
]);
const AUTOPILOT_STOP_COMMANDS = new Set(["autopilot-stop", "autopilot-pause"]);
// Normalizes autopilot command names.
export function canonicalAutopilotCommandName(name) {
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
        if (!head || head === "start" || head === "go" || head === "resume" || head === "continue") {
            return "start";
        }
        if (head === "stop" || head === "pause") {
            return "stop";
        }
        return "none";
    }
    return "start";
}
// Returns true when command should start or continue autopilot loop.
export function isAutopilotCommand(name) {
    return AUTOPILOT_START_COMMANDS.has(name);
}
// Returns true when command should stop active autopilot loop.
export function isAutopilotStopCommand(name) {
    return AUTOPILOT_STOP_COMMANDS.has(name);
}
// Parses completion mode from command argument string.
export function parseCompletionMode(args) {
    const explicit = args.match(/--completion-mode(?:\s+|=)(promise|objective)/i);
    if (explicit?.[1]?.toLowerCase() === "objective") {
        return "objective";
    }
    return "promise";
}
// Parses completion promise token from command argument string.
export function parseCompletionPromise(args, fallback) {
    const quoted = args.match(/--completion-promise(?:\s+|=)"([^"]+)"/i);
    if (quoted?.[1]?.trim()) {
        return quoted[1].trim();
    }
    const plain = args.match(/--completion-promise(?:\s+|=)([^\s]+)/i);
    if (plain?.[1]?.trim()) {
        return plain[1].trim();
    }
    return fallback;
}
// Parses iteration cap from command argument string.
export function parseMaxIterations(args, fallback) {
    const match = args.match(/--max-iterations(?:\s+|=)(\d+)/i);
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
    const goal = args.match(/--goal(?:\s+|=)(?:"([^"]+)"|'([^']+)'|([^\s]+))/i);
    const explicit = goal?.[1] ?? goal?.[2] ?? goal?.[3] ?? "";
    if (explicit.trim()) {
        return explicit.trim();
    }
    const quoted = args.match(/^"([^"]+)"/);
    if (quoted?.[1]?.trim()) {
        return quoted[1].trim();
    }
    const stripped = args
        .replace(/--[a-z-]+\s+"[^"]+"/gi, "")
        .replace(/--[a-z-]+="[^"]+"/gi, "")
        .replace(/--[a-z-]+='[^']+'/gi, "")
        .replace(/--[a-z-]+=[^\s]+/gi, "")
        .replace(/--[a-z-]+\s+[^\s]+/gi, "")
        .trim();
    return stripped || "continue current objective until done";
}
// Parses done-criteria values from command argument string.
export function parseDoneCriteria(args) {
    const marker = /--done-criteria\b/i;
    const match = args.match(marker);
    if (!match || typeof match.index !== "number") {
        return [];
    }
    const start = match.index + match[0].length;
    const tail = args.slice(start).trim().replace(/^=/, "").trim();
    if (!tail) {
        return [];
    }
    let raw = "";
    if (tail.startsWith('"')) {
        const end = tail.indexOf('"', 1);
        raw = end > 1 ? tail.slice(1, end) : "";
    }
    else if (tail.startsWith("'")) {
        const end = tail.indexOf("'", 1);
        raw = end > 1 ? tail.slice(1, end) : "";
    }
    else {
        const nextFlag = tail.search(/\s+--[a-z-]+\b/i);
        raw = (nextFlag >= 0 ? tail.slice(0, nextFlag) : tail).trim();
    }
    if (!raw) {
        return [];
    }
    return raw
        .split(/[;\n]+/)
        .map((item) => item.trim())
        .filter(Boolean);
}
