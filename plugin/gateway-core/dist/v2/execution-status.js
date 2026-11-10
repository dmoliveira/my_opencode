import { isAbsolute, resolve } from "node:path";
import { createExecutionStatusHook } from "../hooks/execution-status/index.js";
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/;
const TOOLS = new Map([
    ["shell", "bash"],
    ["edit", "edit"],
    ["write", "write"],
    ["patch", "apply_patch"],
    ["subagent", "task"],
]);
const MAX_PENDING = 256;
const MAX_SESSIONS = 256;
const MAX_LOOKUPS = 8;
const LOOKUP_TIMEOUT_MS = 1000;
const SUPPORTED_VERSIONS = ["2.2.5", "2.2.6"];
function isRecord(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
}
function validSessionID(value) {
    return typeof value === "string" && value.length > 0 && value.length <= 160 &&
        value === value.trim() && !CONTROL_CHARACTER.test(value);
}
/** Unconfigured V2 adapter; status reporting is never an enforcement boundary. */
export async function registerV2ExecutionStatus(context, options) {
    if (!options.enabled)
        return async () => { };
    if (!SUPPORTED_VERSIONS.includes(context.app.version) ||
        typeof context.location.directory !== "string" || !isAbsolute(context.location.directory) ||
        !Number.isInteger(options.maxSessions) || options.maxSessions < 1 || options.maxSessions > 64 ||
        !Number.isInteger(options.maxLabelChars) || options.maxLabelChars < 24 || options.maxLabelChars > 160) {
        throw new Error("Invalid V2 execution-status configuration");
    }
    const directory = resolve(context.location.directory);
    const status = createExecutionStatusHook({ directory, ...options });
    const known = new Set();
    const tails = new Map();
    const abort = new AbortController();
    const registrations = [];
    let pending = 0;
    let activeLookups = 0;
    let disposed = false;
    const payload = (id) => ({ input: { sessionID: id } });
    const remember = (id) => {
        known.delete(id);
        known.add(id);
        if (known.size > MAX_SESSIONS) {
            const first = known.values().next().value;
            if (first !== undefined)
                known.delete(first);
        }
    };
    const enqueue = (id, work) => {
        if (disposed || !validSessionID(id) || pending >= MAX_PENDING)
            return Promise.resolve();
        const previous = tails.get(id) ?? Promise.resolve();
        pending += 1;
        const current = previous.then(async () => {
            if (!disposed)
                await work(id);
        }).catch(() => { });
        tails.set(id, current);
        return current.finally(() => {
            pending -= 1;
            if (tails.get(id) === current)
                tails.delete(id);
        });
    };
    const belongsHere = async (id) => {
        if (disposed || activeLookups >= MAX_LOOKUPS)
            return false;
        activeLookups += 1;
        const lookup = Promise.resolve().then(() => context.session.get({ sessionID: id }))
            .finally(() => { activeLookups -= 1; });
        let timer;
        try {
            const timeout = new Promise((done) => {
                timer = setTimeout(() => done(undefined), LOOKUP_TIMEOUT_MS);
            });
            const session = await Promise.race([lookup, timeout]);
            if (disposed || !session || !isRecord(session.location))
                return false;
            const location = session.location.directory;
            if (typeof location !== "string" || !isAbsolute(location))
                return false;
            if (resolve(location) !== directory) {
                if (known.delete(id))
                    await status.event("session.deleted", payload(id));
                return false;
            }
            if (!known.has(id))
                await status.event("session.created", payload(id));
            if (disposed)
                return false;
            remember(id);
            return true;
        }
        catch {
            return false;
        }
        finally {
            if (timer)
                clearTimeout(timer);
        }
    };
    const toolEvent = (phase, event) => {
        try {
            const name = typeof event.tool === "string" ? TOOLS.get(event.tool.toLowerCase()) : undefined;
            if (!name)
                return Promise.resolve();
            const args = isRecord(event.input) && typeof event.input.command === "string"
                ? { command: event.input.command }
                : {};
            const metadata = isRecord(event.result) && isRecord(event.result.metadata) &&
                typeof event.result.metadata.exit === "number" && Number.isFinite(event.result.metadata.exit)
                ? { exit: event.result.metadata.exit }
                : {};
            const input = { tool: name, sessionID: event.sessionID, args };
            const kind = phase === "execute.before"
                ? "tool.execute.before"
                : event.status === "error" ? "tool.execute.before.error" : "tool.execute.after";
            if (phase === "execute.after" && event.status !== "completed" && event.status !== "error")
                return Promise.resolve();
            return enqueue(event.sessionID, async (id) => {
                if (!(await belongsHere(id)) || disposed)
                    return;
                await status.event(kind, { input, output: { metadata } });
            });
        }
        catch {
            return Promise.resolve();
        }
    };
    const sessionEvent = async (event) => {
        if (!isRecord(event) || !isRecord(event.data))
            return;
        const type = event.type;
        if (type !== "session.created" && type !== "session.moved" && type !== "session.deleted")
            return;
        await enqueue(event.data.sessionID, async (id) => {
            if (type === "session.deleted") {
                if (known.delete(id))
                    await status.event("session.deleted", payload(id));
                return;
            }
            await belongsHere(id);
        });
    };
    try {
        registrations.push(await context.tool.hook("execute.before", (event) => toolEvent("execute.before", event)));
        registrations.push(await context.tool.hook("execute.after", (event) => toolEvent("execute.after", event)));
        const stream = context.event.subscribe({ types: ["session.created", "session.moved", "session.deleted"], signal: abort.signal });
        void (async () => {
            try {
                for await (const event of stream) {
                    if (disposed)
                        break;
                    try {
                        await sessionEvent(event);
                    }
                    catch {
                        // A malformed event must not end the subscription.
                    }
                }
            }
            catch {
                // Status reporting is best-effort; tool execution must continue.
            }
        })();
    }
    catch {
        disposed = true;
        abort.abort();
        await Promise.allSettled(registrations.map(async (registration) => registration.dispose()));
        throw new Error("Unable to register V2 execution status");
    }
    return async () => {
        disposed = true;
        abort.abort();
        await Promise.allSettled(registrations.map(async (registration) => registration.dispose()));
    };
}
