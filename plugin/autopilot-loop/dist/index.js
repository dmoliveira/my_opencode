import { DEFAULT_COMPLETION_PROMISE, DEFAULT_MAX_ITERATIONS, HOOK_NAME, } from "./constants.js";
import { buildContinuationPrompt } from "./injector.js";
import { detectCompletion, extractLastAssistantText } from "./detector.js";
import { clearState, incrementIteration, loadState, saveState } from "./storage.js";
// Parses slashcommand name and argument suffix.
function parseCommand(raw) {
    const trimmed = raw.trim().replace(/^\//, "");
    if (!trimmed) {
        return { name: "", rest: "" };
    }
    const [first, ...tail] = trimmed.split(/\s+/);
    return { name: first.toLowerCase(), rest: tail.join(" ").trim() };
}
// Extracts completion mode from slashcommand argument string.
function parseCompletionMode(rest) {
    const match = rest.match(/--completion-mode\s+(promise|objective)/i);
    if (!match) {
        return "promise";
    }
    return match[1].toLowerCase() === "objective" ? "objective" : "promise";
}
// Extracts completion promise token from slashcommand argument string.
function parseCompletionPromise(rest) {
    const quoted = rest.match(/--completion-promise\s+"([^"]+)"/i);
    if (quoted?.[1]) {
        return quoted[1].trim() || DEFAULT_COMPLETION_PROMISE;
    }
    const simple = rest.match(/--completion-promise\s+([^\s]+)/i);
    if (simple?.[1]) {
        return simple[1].trim() || DEFAULT_COMPLETION_PROMISE;
    }
    return DEFAULT_COMPLETION_PROMISE;
}
// Extracts max-iterations option from slashcommand argument string.
function parseMaxIterations(rest) {
    const match = rest.match(/--max-iterations\s+(\d+)/i);
    if (!match) {
        return DEFAULT_MAX_ITERATIONS;
    }
    const parsed = Number.parseInt(match[1], 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
        return DEFAULT_MAX_ITERATIONS;
    }
    return parsed;
}
// Extracts goal text from slashcommand argument string.
function parseGoal(rest) {
    const goalFlag = rest.match(/--goal\s+"([^"]+)"/i);
    if (goalFlag?.[1]) {
        return goalFlag[1].trim();
    }
    const quoted = rest.match(/^"([^"]+)"/);
    if (quoted?.[1]) {
        return quoted[1].trim();
    }
    const strippedFlags = rest.replace(/--[a-z-]+\s+"[^"]+"/gi, "").replace(/--[a-z-]+\s+[^\s]+/gi, "");
    return strippedFlags.trim() || "continue current objective until done";
}
// Determines whether slashcommand should start autopilot loop handling.
function isAutopilotStartCommand(command) {
    return command === "autopilot-go" || command === "autopilot-resume" || command === "continue-work" || command === "autopilot-objective";
}
// Determines whether slashcommand should cancel autopilot loop handling.
function isAutopilotStopCommand(command) {
    return command === "autopilot-stop" || command === "autopilot-pause";
}
// Resolves whether /autopilot should start, stop, or be ignored.
function resolveAutopilotAction(command, rest) {
    if (isAutopilotStopCommand(command)) {
        return "stop";
    }
    if (command === "autopilot") {
        const head = rest.trim().split(/\s+/)[0]?.toLowerCase() ?? "";
        if (!head || head === "start" || head === "go" || head === "resume" || head === "continue") {
            return "start";
        }
        if (head === "stop" || head === "pause") {
            return "stop";
        }
        return "none";
    }
    if (isAutopilotStartCommand(command)) {
        return "start";
    }
    return "none";
}
// Resolves session id from event properties.
function eventSessionId(input) {
    const props = input.event.properties;
    if (!props) {
        return null;
    }
    const direct = props.sessionID;
    if (typeof direct === "string" && direct.trim()) {
        return direct;
    }
    const info = props.info;
    if (typeof info === "object" && info) {
        const record = info;
        const id = record.id;
        if (typeof id === "string" && id.trim()) {
            return id;
        }
    }
    return null;
}
// Creates hook implementation for event-driven autopilot continuation.
export function createAutopilotLoopHook(ctx, options) {
    const stateFile = options?.stateFile;
    // Starts loop state for the provided session and prompt.
    function startLoop(args) {
        const state = {
            active: true,
            sessionId: args.sessionId,
            prompt: args.prompt,
            iteration: 1,
            maxIterations: args.maxIterations ?? DEFAULT_MAX_ITERATIONS,
            completionMode: args.completionMode ?? "promise",
            completionPromise: args.completionPromise ?? DEFAULT_COMPLETION_PROMISE,
            startedAt: new Date().toISOString(),
        };
        saveState(ctx.directory, state, stateFile);
    }
    // Cancels loop state when requested for matching session.
    function cancelLoop(sessionId) {
        const state = loadState(ctx.directory, stateFile);
        if (state && state.sessionId === sessionId) {
            clearState(ctx.directory, stateFile);
        }
    }
    // Returns current persisted loop state.
    function getState() {
        return loadState(ctx.directory, stateFile);
    }
    // Emits user-facing toast when hook completes or stops.
    async function toast(title, message, variant) {
        try {
            await ctx.client.tui?.showToast({
                body: { title, message, variant, duration: 4000 },
            });
        }
        catch {
            // no-op
        }
    }
    // Handles lifecycle events and injects continuation prompts on idle.
    async function event(input) {
        const eventType = input.event.type;
        const sessionId = eventSessionId(input);
        if (eventType === "session.deleted" && sessionId) {
            cancelLoop(sessionId);
            return;
        }
        if (eventType !== "session.idle" || !sessionId) {
            return;
        }
        const state = loadState(ctx.directory, stateFile);
        if (!state || !state.active || state.sessionId !== sessionId) {
            return;
        }
        const response = await ctx.client.session.messages({
            path: { id: sessionId },
            query: { directory: ctx.directory },
        });
        const messages = Array.isArray(response.data) ? response.data : [];
        const assistantText = extractLastAssistantText(messages);
        if (detectCompletion(state, assistantText)) {
            clearState(ctx.directory, stateFile);
            await toast("Autopilot Loop Complete ✅", `Completed after ${state.iteration} iteration(s).`, "success");
            return;
        }
        if (state.iteration >= state.maxIterations) {
            clearState(ctx.directory, stateFile);
            await toast("Autopilot Loop Stopped ⚠️", `Max iterations (${state.maxIterations}) reached.`, "warning");
            return;
        }
        const next = incrementIteration(ctx.directory, state, stateFile);
        const prompt = buildContinuationPrompt(next);
        await ctx.client.session.promptAsync({
            path: { id: sessionId },
            body: { parts: [{ type: "text", text: prompt }] },
            query: { directory: ctx.directory },
        });
        await toast(HOOK_NAME, `Injected continuation ${next.iteration}/${next.maxIterations}.`, "info");
    }
    return { event, startLoop, cancelLoop, getState };
}
// Creates plugin runtime bridge that wires slash commands and lifecycle events to autopilot-loop.
export default function AutopilotLoopPlugin(ctx) {
    const loop = createAutopilotLoopHook(ctx);
    // Tracks session lifecycle events to auto-inject continuation prompts.
    async function event(input) {
        await loop.event(input);
    }
    // Intercepts slash commands to start or stop loop state.
    async function toolExecuteBefore(input, output) {
        if (input.tool !== "slashcommand") {
            return;
        }
        const commandRaw = output.args?.command;
        if (!commandRaw || !input.sessionID) {
            return;
        }
        const parsed = parseCommand(commandRaw);
        const action = resolveAutopilotAction(parsed.name, parsed.rest);
        if (action === "stop") {
            loop.cancelLoop(input.sessionID);
            return;
        }
        if (action !== "start") {
            return;
        }
        const completionMode = parsed.name === "autopilot-objective" ? "objective" : parseCompletionMode(parsed.rest);
        const completionPromise = parseCompletionPromise(parsed.rest);
        const maxIterations = parseMaxIterations(parsed.rest);
        const goal = parseGoal(parsed.rest);
        loop.startLoop({
            sessionId: input.sessionID,
            prompt: goal,
            completionMode,
            completionPromise,
            maxIterations,
        });
    }
    // Keeps plugin contract for chat.message hook compatibility.
    async function chatMessage(_input) {
        return;
    }
    return {
        event,
        "tool.execute.before": toolExecuteBefore,
        "chat.message": chatMessage,
    };
}
