import { realpathSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { authorizeTaskerRead } from "./read-policy.js";
import { inspectTaskerCommand, } from "./command-policy.js";
import { sameTaskerSandbox, TaskerPlanningEvidence, } from "./planning-evidence.js";
import { createResearchAuthoritySigner, inspectResearchPacket, markTaskerResearchArgs, researchBoundary, TASKER_RESEARCH_AGENTS, } from "./research-policy.js";
const DISCOVERY = new Set(["read", "list", "glob", "grep"]);
const RESEARCH_TOOLS = new Set([...DISCOVERY, "webfetch", "websearch"]);
const normalize = (value) => String(value ?? "")
    .trim()
    .toLowerCase();
function eventSession(event) {
    const p = event.properties ?? {};
    const info = p.info && typeof p.info === "object"
        ? p.info
        : {};
    return String(event.input?.sessionID ??
        event.input?.sessionId ??
        p.sessionID ??
        p.sessionId ??
        p.id ??
        info.id ??
        "").trim();
}
function callID(event) {
    return String(event.input?.callID ?? event.input?.callId ?? "").trim();
}
function blocked(directory, session, tool, reason) {
    writeGatewayEventAudit(directory, {
        hook: "tasker-command-gateway",
        stage: "guard",
        reason_code: reason,
        session_id: session,
        tool,
    });
    throw new Error(`Blocked planning-agent request: ${reason}`);
}
function bindBashDirectory(args, expected, final) {
    if (Object.keys(args).some((key) => !["command", "workdir", "timeout", "description"].includes(key)) ||
        typeof args.command !== "string")
        return null;
    if (args.description !== undefined &&
        (typeof args.description !== "string" || args.description.length > 2048))
        return null;
    if (args.timeout !== undefined &&
        (typeof args.timeout !== "number" ||
            !Number.isSafeInteger(args.timeout) ||
            args.timeout < 1 ||
            args.timeout > 120000))
        return null;
    try {
        if (!isAbsolute(expected))
            return null;
        const directory = realpathSync(expected);
        if (directory !== resolve(expected) || (final && final !== directory))
            return null;
        if (args.workdir !== undefined &&
            (typeof args.workdir !== "string" ||
                !isAbsolute(args.workdir) ||
                realpathSync(args.workdir) !== directory))
            return null;
        if (final && args.workdir !== final)
            return null;
        args.workdir = directory;
        args.timeout ??= 120000;
        return directory;
    }
    catch {
        return null;
    }
}
function completedResearch(output, error) {
    if (error || typeof output !== "string" || !output.trim())
        return false;
    // Native lifecycle framing is authoritative; quoted evidence is not a status channel.
    const state = /^\s*<task\b[^>]*\bstate=["']([^"']+)["']/i.exec(output)?.[1];
    if (state !== undefined)
        return state === "completed";
    return !/^\s*(?:error:|failed:|refused:|denied:|BLOCKER:)/i.test(output);
}
function binding(args) {
    return createHash("sha256")
        .update(JSON.stringify(args, Object.keys(args).sort()))
        .digest("hex");
}
export function createTaskerCommandGatewayHook(options) {
    const states = new Map();
    const admissions = new Map();
    const deleted = new Set();
    const parents = new Map();
    const taskerRoots = new Set();
    const requests = new Map();
    const idle = new Set();
    const readScopes = new Map();
    const signer = createResearchAuthoritySigner();
    const key = (sid, call) => `${sid}\0${call}`;
    async function researchSession(sid) {
        // Hostless unit contexts cannot create a real child; runtime callers provide the resolver.
        if (!options.resolveParent && !parents.has(sid))
            return false;
        const seen = new Set();
        let current = sid;
        for (let depth = 0; depth < 32; depth += 1) {
            if (!current || seen.has(current))
                return undefined;
            seen.add(current);
            let parent = parents.get(current);
            if (parent === undefined) {
                parent = await options.resolveParent?.(current);
                if (parent !== undefined) {
                    if (parents.size >= 4096)
                        parents.delete(parents.keys().next().value ?? "");
                    parents.set(current, parent);
                }
            }
            if (parent === undefined)
                return undefined;
            if (parent === null)
                return false;
            if (taskerRoots.has(parent))
                return true;
            const wasTasker = options.wasTasker
                ? await options.wasTasker(parent)
                : normalize(await options.resolveAgent(parent)) === "tasker";
            if (wasTasker === true) {
                if (taskerRoots.size >= 4096 && !taskerRoots.has(parent))
                    return undefined;
                taskerRoots.add(parent);
                return true;
            }
            if (wasTasker === undefined)
                return undefined;
            current = parent;
        }
        return undefined;
    }
    async function researchAuthority(sid) {
        const seen = new Set();
        let current = sid;
        for (let depth = 0; depth < 32; depth += 1) {
            if (!current || seen.has(current))
                return undefined;
            seen.add(current);
            const cached = readScopes.get(current);
            if (cached) {
                if (readScopes.size >= 1024)
                    readScopes.delete(readScopes.keys().next().value ?? "");
                readScopes.set(sid, cached);
                return cached;
            }
            let parent = parents.get(current);
            if (parent === undefined) {
                parent = await options.resolveParent?.(current);
                if (parent !== undefined) {
                    if (parents.size >= 4096 && !parents.has(current))
                        parents.delete(parents.keys().next().value ?? "");
                    parents.set(current, parent);
                }
            }
            if (!parent)
                return undefined;
            const prompt = await options.initialResearchPrompt?.(current);
            const capability = prompt ? signer.verify(prompt, parent) : null;
            if (capability) {
                if (readScopes.size >= 1024)
                    readScopes.delete(readScopes.keys().next().value ?? "");
                readScopes.set(sid, capability);
                return capability;
            }
            current = parent;
        }
        return undefined;
    }
    function forgetCall(event, invalidate = false) {
        const sid = eventSession(event), id = callID(event), k = key(sid, id);
        const admitted = admissions.get(k);
        if (admitted?.state?.busy === id)
            admitted.state.busy = "";
        if (admitted?.packet && admitted.finalized && admitted.state) {
            admitted.state.researchPending.delete(id);
            if (invalidate)
                admitted.state.researchFailed = true;
        }
        if (invalidate)
            admitted?.state?.invalidate();
        admissions.delete(k);
    }
    return {
        id: "tasker-command-gateway",
        priority: 980,
        events: [
            "tool.execute.before",
            "tool.execute.before.final",
            "tool.execute.before.error",
            "tool.execute.after",
            "message.part.updated",
            "session.created",
            "session.deleted",
            "session.compacted",
            "chat.message",
            "session.idle",
            "session.status",
        ],
        async event(type, payload) {
            const event = (payload ?? {});
            const sid = eventSession(event), id = callID(event), k = key(sid, id);
            const directory = event.directory || options.directory;
            if (type === "message.part.updated") {
                const part = event.properties?.part;
                const terminal = part?.state;
                if (part?.type !== "tool" || !["error", "canceled", "cancelled"].includes(String(terminal?.status)))
                    return;
                const terminalSession = String(part.sessionID ?? "");
                const terminalCall = String(part.callID ?? "");
                const admitted = admissions.get(key(terminalSession, terminalCall));
                const input = terminal?.input;
                if (!admitted?.finalized || !input || typeof input !== "object")
                    return;
                const expectedTool = admitted.packet ? "task" : "bash";
                const matches = part.tool === expectedTool && binding(input) === admitted.binding;
                if (matches)
                    forgetCall({ input: { sessionID: terminalSession, callID: terminalCall } }, true);
                return;
            }
            if (type === "session.created") {
                const p = event.properties ?? {}, info = p.info;
                if (info && typeof info.id === "string") {
                    if (parents.size >= 4096)
                        parents.delete(parents.keys().next().value ?? "");
                    parents.set(info.id, typeof info.parentID === "string" && info.parentID
                        ? info.parentID
                        : null);
                }
                return;
            }
            if (type === "session.deleted") {
                if (!sid)
                    return;
                deleted.add(sid);
                if (deleted.size > 4096)
                    deleted.delete(deleted.values().next().value ?? "");
                states.delete(sid);
                requests.delete(sid);
                idle.delete(sid);
                readScopes.delete(sid);
                // Retain ancestry tombstones: surviving children stay read-only.
                for (const [name, admitted] of admissions)
                    if (admitted.session === sid)
                        admissions.delete(name);
                return;
            }
            if (type === "session.idle" || type === "session.status") {
                const status = event.properties?.status;
                if (states.has(sid) && (type === "session.idle" || status?.type === "idle"))
                    idle.add(sid);
                return;
            }
            if (type === "session.compacted") {
                states.get(sid)?.invalidate();
                return;
            }
            if (type === "chat.message") {
                const p = event.properties ?? {};
                const parts = Array.isArray(p.parts)
                    ? p.parts
                    : [];
                if (parts.length && parts.every((part) => part.synthetic === true))
                    return;
                const text = [
                    p.prompt,
                    p.text,
                    p.message,
                    ...parts.map((part) => part.text),
                ]
                    .filter((value) => typeof value === "string")
                    .join("\n");
                const request = typeof p.messageID === "string"
                    ? p.messageID
                    : createHash("sha256").update(text).digest("hex");
                if (sid && text) {
                    if (requests.size >= 4096 && !requests.has(sid))
                        requests.delete(requests.keys().next().value ?? "");
                    if (requests.get(sid)?.key !== request) {
                        const state = states.get(sid);
                        requests.set(sid, { key: request, available: !state });
                        state?.newRequest(request);
                    }
                    idle.delete(sid);
                }
                return;
            }
            if (type === "tool.execute.before.error") {
                if (admissions.get(k)?.inputToken === event.input)
                    forgetCall(event, true);
                return;
            }
            const tool = normalize(event.input?.tool);
            if (type === "tool.execute.after") {
                const admitted = admissions.get(k);
                if (!admitted?.finalized ||
                    admitted.session !== sid ||
                    deleted.has(sid))
                    return;
                const args = event.input?.args ?? event.output?.args ?? {};
                if (admitted.binding !== binding(args))
                    return;
                const state = admitted.state;
                if (admitted.packet && state) {
                    const success = completedResearch(event.output?.output, event.output?.metadata?.error);
                    if (!success)
                        state.researchFailed = true;
                }
                if (admitted.command &&
                    state &&
                    state.generation === admitted.generation)
                    state.observe(admitted.command, event.output?.output, event.output?.metadata?.exit);
                forgetCall(event);
                return;
            }
            if (type !== "tool.execute.before" &&
                type !== "tool.execute.before.final")
                return;
            const agent = deleted.has(sid)
                ? ""
                : normalize(event.input?.agent) ||
                    normalize(await options.resolveAgent(sid));
            if (!agent) {
                if (options.failClosedOnUnknownIdentity !== false)
                    blocked(directory, sid, tool, "tasker_identity_unknown");
                return;
            }
            const authority = await researchAuthority(sid);
            const research = authority ? true : await researchSession(sid);
            if (research !== false) {
                if (!RESEARCH_TOOLS.has(tool))
                    blocked(directory, sid, tool, research ? "tasker_research_tool_denied" : "tasker_lineage_unknown");
                if (!authority || !authorizeTaskerRead(tool, event.output?.args ?? {}, authority))
                    blocked(directory, sid, tool, "tasker_research_read_scope_denied");
                return;
            }
            if (agent !== "tasker")
                return;
            if (taskerRoots.size >= 4096 && !taskerRoots.has(sid))
                taskerRoots.delete(taskerRoots.values().next().value ?? "");
            taskerRoots.add(sid);
            writeGatewayEventAudit(directory, {
                hook: "tasker-command-gateway",
                stage: "state",
                reason_code: "tasker_production_guard_active",
                session_id: sid,
                tool,
            });
            const sandbox = await options.resolveSandbox?.(sid);
            if (!sandbox)
                blocked(directory, sid, tool, "tasker_sandbox_required");
            if (DISCOVERY.has(tool)) {
                if (!authorizeTaskerRead(tool, event.output?.args ?? {}, { worktree: sandbox.worktree, paths: ["."] }))
                    blocked(directory, sid, tool, "tasker_discovery_read_scope_denied");
                return;
            }
            if (!sid || !id)
                blocked(directory, sid, tool, "tasker_call_identity_required");
            let state = states.get(sid);
            if (state && (!sandbox || !sameTaskerSandbox(state.sandbox, sandbox)))
                blocked(directory, sid, tool, "tasker_sandbox_changed");
            if (!state && sandbox) {
                const request = requests.get(sid);
                if (!request?.available)
                    blocked(directory, sid, tool, "tasker_fresh_user_request_required");
                if (states.size >= 512) {
                    for (const [oldID, oldState] of states) {
                        if (idle.has(oldID) && !oldState.busy && !oldState.researchPending.size && ![...admissions.values()].some((entry) => entry.session === oldID)) {
                            oldState.invalidate();
                            states.delete(oldID);
                            idle.delete(oldID);
                            break;
                        }
                    }
                }
                if (states.size >= 512)
                    blocked(directory, sid, tool, "tasker_session_capacity");
                state = new TaskerPlanningEvidence(sandbox, options.knownRecordTargets);
                state.newRequest(request.key);
                request.available = false;
                states.set(sid, state);
            }
            idle.delete(sid);
            if (state) {
                states.delete(sid);
                states.set(sid, state);
            }
            const args = event.output?.args ?? {};
            if (tool === "task" && args.category !== undefined && (typeof args.category !== "string" || args.category.length > 32 || /[\r\n\0]/.test(args.category)))
                blocked(directory, sid, tool, "tasker_research_category_invalid");
            if (type === "tool.execute.before") {
                if (admissions.size >= 1024)
                    blocked(directory, sid, tool, "tasker_admission_capacity");
                if (admissions.has(k))
                    blocked(directory, sid, tool, "tasker_duplicate_call");
                if (tool === "task") {
                    const target = normalize(args.subagent_type);
                    const packet = inspectResearchPacket(args.prompt);
                    if (!state ||
                        !TASKER_RESEARCH_AGENTS.has(target) ||
                        !packet ||
                        typeof args.description !== "string" ||
                        !args.description.trim() ||
                        args.description.length > 160 ||
                        args.description.includes("[DELEGATION TRACE ") ||
                        Object.keys(args).some((name) => ![
                            "subagent_type",
                            "prompt",
                            "description",
                            "category",
                        ].includes(name)))
                        blocked(directory, sid, tool, "tasker_research_packet_required");
                    if (state.researchCount >= 2 || state.persisted)
                        blocked(directory, sid, tool, "tasker_research_budget_or_order");
                    markTaskerResearchArgs(args);
                    admissions.set(k, {
                        session: sid,
                        inputToken: event.input,
                        state,
                        packet,
                        target,
                        prompt: String(args.prompt),
                        generation: state.generation,
                    });
                    return;
                }
                if (tool !== "bash")
                    blocked(directory, sid, tool, "tasker_command_boundary_blocked");
                const workdir = bindBashDirectory(args, sandbox?.worktree ?? directory);
                if (!workdir)
                    blocked(directory, sid, tool, "tasker_workdir_mismatch");
                const command = inspectTaskerCommand(String(args.command ?? ""), {
                    sessionID: sid,
                    sandbox,
                    knownRecordTargets: state?.targets,
                })?.[0];
                if (!command)
                    blocked(directory, sid, tool, "tasker_command_boundary_blocked");
                const reason = state?.authorize(command);
                if (reason)
                    blocked(directory, sid, tool, reason);
                admissions.set(k, {
                    session: sid,
                    inputToken: event.input,
                    state,
                    command,
                    workdir,
                    generation: state?.generation,
                });
                return;
            }
            const admitted = admissions.get(k);
            if (!admitted ||
                admitted.finalized ||
                admitted.state !== state ||
                admitted.generation !== state?.generation)
                blocked(directory, sid, tool, "tasker_admission_changed");
            if (admitted.packet) {
                if (tool !== "task" ||
                    normalize(args.subagent_type) !== admitted.target ||
                    args.task_id ||
                    args.session_id ||
                    args.command ||
                    Object.keys(args).some((name) => !["subagent_type", "prompt", "description", "category"].includes(name)) ||
                    typeof args.prompt !== "string" ||
                    args.prompt.replace(/^\[DELEGATION TRACE [A-Za-z0-9_-]{1,80}\]\n\n/, "") !== admitted.prompt ||
                    !state ||
                    state.researchCount >= 2 ||
                    state.persisted)
                    blocked(directory, sid, tool, "tasker_research_rewritten");
                args.prompt += signer.issue({ version: 1, parent: sid, target: admitted.target, nonce: randomUUID(), worktree: state.sandbox.worktree, paths: admitted.packet.paths }) + researchBoundary(admitted.packet);
                state.researchCount += 1;
                state.researchPending.add(id);
            }
            else {
                if (tool !== "bash")
                    blocked(directory, sid, tool, "tasker_admission_changed");
                if (!bindBashDirectory(args, sandbox?.worktree ?? directory, admitted.workdir))
                    blocked(directory, sid, tool, "tasker_workdir_rewritten");
                const command = inspectTaskerCommand(String(args.command ?? ""), {
                    sessionID: sid,
                    sandbox,
                    knownRecordTargets: state?.targets,
                })?.[0];
                if (!command ||
                    JSON.stringify(command) !== JSON.stringify(admitted.command))
                    blocked(directory, sid, tool, "tasker_command_rewritten");
                const reason = state?.authorize(command);
                if (reason)
                    blocked(directory, sid, tool, reason);
                args.description = `${String(args.description ?? "Scoped planning command")} [Tasker invocation ${randomUUID()}]`;
                state?.reserve(command, id);
                admitted.generation = state?.generation;
            }
            admitted.finalized = true;
            admitted.binding = binding(args);
        },
    };
}
