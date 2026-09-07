const ADD_TYPES = new Set(["task", "epic", "memory", "doc"]);
const READ_TYPES = new Set(["task", "epic", "memory", "doc", "event", "link", "session"]);
const READ_VERBS = new Set(["current", "next", "queue"]);
const LINK_TYPES = new Set(["about", "active-task", "blocked-by", "depends-on", "doc-for", "parent-of"]);
const SET_FIELDS = new Set(["body", "goal", "kind", "priority", "status", "summary", "title"]);
const RECORD_ID = /^(?:task|epic|memory|doc|event|link|session)_\d+$/;
const READ_OPTIONS = new Set(["--kind", "--label", "--limit", "--priority", "--scope", "--since", "--status", "--type", "--until", "--view"]);
const ADD_OPTIONS = new Set(["--actor", "--branch", "--body", "--goal", "--kind", "--label", "--priority", "--ref", "--request-id", "--scope", "--summary", "--task", "--type", "--worktree"]);
const SET_OPTIONS = new Set(["--actor", "--expected-revision", "--reason", "--request-id"]);
const LINK_OPTIONS = new Set(["--actor", "--request-id"]);
function appendOption(values, name, value) {
    const current = values.get(name) ?? [];
    current.push(value);
    values.set(name, current);
}
function splitOptions(args, options) {
    const positionals = [];
    const values = new Map();
    for (let index = 0; index < args.length; index += 1) {
        const token = args[index] ?? "";
        if (!token.startsWith("--")) {
            positionals.push(token);
            continue;
        }
        const equals = token.indexOf("=");
        const name = equals === -1 ? token : token.slice(0, equals);
        if (!options.has(name)) {
            return null;
        }
        const value = equals === -1 ? args[++index] : token.slice(equals + 1);
        if (!value || value.startsWith("--")) {
            return null;
        }
        appendOption(values, name, value);
    }
    return { positionals, values };
}
function hasExactlyOne(values, name) {
    return (values.get(name) ?? []).length === 1;
}
function validValues(parsed) {
    return [...parsed.values.values()].every((values) => values.every((value) => value.length <= 4096 && !/[\0\r\n]/.test(value)));
}
function normalizeOcArgs(segment) {
    if (segment[0] !== "oc") {
        return null;
    }
    const args = ["oc"];
    for (let index = 1; index < segment.length; index += 1) {
        const token = segment[index] ?? "";
        if (token === "--config" || token.startsWith("--config=")) {
            return null;
        }
        if (token === "--format") {
            if (segment[++index] !== "json") {
                return null;
            }
            continue;
        }
        if (token.startsWith("--format=")) {
            if (token.slice(9) !== "json") {
                return null;
            }
            continue;
        }
        args.push(token);
    }
    return args;
}
function parseShell(command) {
    if (!command || command.length > 16_384 || /[\0\r\n$`\\]/.test(command)) {
        return null;
    }
    const segments = [[]];
    let token = "";
    let started = false;
    let quote = null;
    const flush = () => {
        if (!started) {
            return;
        }
        segments.at(-1)?.push(token);
        token = "";
        started = false;
    };
    for (let index = 0; index < command.length; index += 1) {
        const char = command[index] ?? "";
        if (quote) {
            if (char === quote) {
                quote = null;
            }
            else {
                token += char;
            }
            started = true;
            continue;
        }
        if (char === "'" || char === '"') {
            quote = char;
            started = true;
            continue;
        }
        if (/\s/.test(char)) {
            flush();
            continue;
        }
        if (char === "&") {
            if (command[index + 1] !== "&") {
                return null;
            }
            flush();
            if (!segments.at(-1)?.length) {
                return null;
            }
            segments.push([]);
            index += 1;
            continue;
        }
        if (/[;|<>(){}[\]#~*?]/.test(char)) {
            return null;
        }
        token += char;
        started = true;
    }
    if (quote) {
        return null;
    }
    flush();
    return segments.length <= 8 && segments.every((segment) => segment.length > 0 && segment.length <= 64) ? segments : null;
}
function optionsObject(parsed) {
    return Object.fromEntries([...parsed.values.entries()].map(([name, values]) => [name, [...values]]));
}
function matchesSandbox(parsed, sandbox) {
    return (hasExactlyOne(parsed.values, "--scope") &&
        hasExactlyOne(parsed.values, "--worktree") &&
        hasExactlyOne(parsed.values, "--branch") &&
        parsed.values.get("--scope")?.[0] === sandbox.scope &&
        parsed.values.get("--worktree")?.[0] === sandbox.worktree &&
        parsed.values.get("--branch")?.[0] === sandbox.branch);
}
function hasKnownRecord(context, id) {
    if (context.knownRecordTargets && context.sandbox) {
        const target = context.knownRecordTargets.get(id);
        return target?.scope === context.sandbox.scope &&
            target.worktree === context.sandbox.worktree &&
            target.branch === context.sandbox.branch;
    }
    return context.knownRecordIds?.has(id) === true;
}
function optionalScopeMatches(parsed, context) {
    const scopes = parsed.values.get("--scope") ?? [];
    return scopes.length <= 1 &&
        (!context.sandbox || scopes.length === 0 || scopes[0] === context.sandbox.scope);
}
function requiresSandboxScope(parsed, context) {
    return !context.sandbox ||
        hasExactlyOne(parsed.values, "--scope") &&
            parsed.values.get("--scope")?.[0] === context.sandbox.scope;
}
function readCommand(args, context) {
    const verb = args[1] ?? "";
    if (verb === "config") {
        return args.length === 3 && args[2] === "--doctor"
            ? { kind: "read", verb, positionals: [], options: {} }
            : null;
    }
    if (verb === "help") {
        return args.length <= 3
            ? { kind: "read", verb, positionals: args.slice(2), options: {} }
            : null;
    }
    if (READ_VERBS.has(verb)) {
        const parsed = splitOptions(args.slice(2), READ_OPTIONS);
        return parsed && parsed.positionals.length === 0 && validValues(parsed) && optionalScopeMatches(parsed, context)
            ? { kind: "read", verb, positionals: [], options: optionsObject(parsed) }
            : null;
    }
    if (verb === "get") {
        const parsed = splitOptions(args.slice(2), new Set(["--view"]));
        const view = parsed?.values.get("--view") ?? ["short"];
        return parsed &&
            parsed.positionals.length === 1 &&
            RECORD_ID.test(parsed.positionals[0] ?? "") &&
            (!context.sandbox || hasKnownRecord(context, parsed.positionals[0] ?? "")) &&
            validValues(parsed) &&
            view.every((value) => ["short", "full", "links"].includes(value))
            ? { kind: "read", verb, positionals: parsed.positionals, options: optionsObject(parsed) }
            : null;
    }
    if (verb === "list") {
        const parsed = splitOptions(args.slice(2), READ_OPTIONS);
        return parsed &&
            parsed.positionals.length === 1 &&
            READ_TYPES.has(parsed.positionals[0] ?? "") &&
            requiresSandboxScope(parsed, context) &&
            validValues(parsed)
            ? { kind: "read", verb, positionals: parsed.positionals, options: optionsObject(parsed) }
            : null;
    }
    if (verb === "find") {
        const parsed = splitOptions(args.slice(2), READ_OPTIONS);
        return parsed &&
            parsed.positionals.length === 1 &&
            hasExactlyOne(parsed.values, "--type") &&
            READ_TYPES.has(parsed.values.get("--type")?.[0] ?? "") &&
            requiresSandboxScope(parsed, context) &&
            validValues(parsed)
            ? { kind: "read", verb, positionals: parsed.positionals, options: optionsObject(parsed) }
            : null;
    }
    return null;
}
function writeCommand(args, context) {
    const verb = args[1] ?? "";
    if (verb === "add") {
        const parsed = splitOptions(args.slice(2), ADD_OPTIONS);
        return parsed &&
            context.sandbox &&
            parsed.positionals.length === 2 &&
            ADD_TYPES.has(parsed.positionals[0] ?? "") &&
            Boolean(parsed.positionals[1]) &&
            validValues(parsed) &&
            matchesSandbox(parsed, context.sandbox)
            ? { kind: "write", verb, positionals: parsed.positionals, options: optionsObject(parsed) }
            : null;
    }
    if (verb === "set") {
        const parsed = splitOptions(args.slice(2), SET_OPTIONS);
        return parsed &&
            context.sandbox &&
            parsed.positionals.length === 3 &&
            RECORD_ID.test(parsed.positionals[0] ?? "") &&
            hasKnownRecord(context, parsed.positionals[0] ?? "") &&
            SET_FIELDS.has(parsed.positionals[1] ?? "") &&
            Boolean(parsed.positionals[2]) &&
            validValues(parsed)
            ? { kind: "write", verb, positionals: parsed.positionals, options: optionsObject(parsed) }
            : null;
    }
    if (verb === "link") {
        const parsed = splitOptions(args.slice(2), LINK_OPTIONS);
        return parsed &&
            context.sandbox &&
            parsed.positionals.length === 3 &&
            RECORD_ID.test(parsed.positionals[0] ?? "") &&
            RECORD_ID.test(parsed.positionals[2] ?? "") &&
            hasKnownRecord(context, parsed.positionals[0] ?? "") &&
            hasKnownRecord(context, parsed.positionals[2] ?? "") &&
            LINK_TYPES.has(parsed.positionals[1] ?? "") &&
            validValues(parsed)
            ? { kind: "write", verb, positionals: parsed.positionals, options: optionsObject(parsed) }
            : null;
    }
    return null;
}
function classify(segment, context) {
    if (segment[0] === "command") {
        return segment.length === 3 && segment[1] === "-v" && segment[2] === "oc"
            ? { kind: "read", verb: "command", positionals: [], options: {} }
            : null;
    }
    const args = normalizeOcArgs(segment);
    if (!args) {
        return null;
    }
    return readCommand(args, context) ?? writeCommand(args, context);
}
export function inspectTaskerCommand(command, context = {}) {
    const segments = parseShell(command);
    if (!segments) {
        return null;
    }
    const inspections = segments.map((segment) => classify(segment, context));
    return inspections.every((inspection) => inspection !== null)
        ? inspections
        : null;
}
export function isAllowedTaskerCommand(command, context = {}) {
    const inspections = inspectTaskerCommand(command, context);
    return Boolean(inspections &&
        (inspections.length === 1 || inspections.every((inspection) => inspection.kind === "read")));
}
const RECORD_ID_FIELDS = new Set(["id", "from_id", "to_id"]);
const ERROR_FIELDS = new Set(["error", "errors", "stderr"]);
function collectStructuredRecordIds(value, matches) {
    if (!value || typeof value !== "object") {
        return;
    }
    if (Array.isArray(value)) {
        for (const item of value) {
            collectStructuredRecordIds(item, matches);
        }
        return;
    }
    const record = value;
    if ([...ERROR_FIELDS].some((field) => record[field])) {
        return;
    }
    for (const [key, item] of Object.entries(record)) {
        if (RECORD_ID_FIELDS.has(key) && typeof item === "string" && RECORD_ID.test(item)) {
            matches.add(item);
            continue;
        }
        if (item && typeof item === "object") {
            collectStructuredRecordIds(item, matches);
        }
    }
}
export function extractTaskerRecordIds(value) {
    const matches = new Set();
    if (typeof value === "string") {
        try {
            collectStructuredRecordIds(JSON.parse(value), matches);
        }
        catch {
            return matches;
        }
    }
    else {
        collectStructuredRecordIds(value, matches);
    }
    return matches;
}
