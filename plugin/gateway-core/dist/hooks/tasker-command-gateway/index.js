import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { extractTaskerRecordIds, extractTaskerRecordTargets, inspectTaskerCommand, isAllowedTaskerCommand, } from "./command-policy.js";
const DISCOVERY = new Set(["read", "list", "glob", "grep"]);
const normalize = (value) => String(value ?? "").trim().toLowerCase();
function blocked(directory, sessionID, tool, reason) {
    writeGatewayEventAudit(directory, {
        hook: "tasker-command-gateway",
        stage: "guard",
        reason_code: reason,
        session_id: sessionID,
        tool,
    });
    throw new Error(`Blocked planning-agent request: ${reason}`);
}
export function createTaskerCommandGatewayHook(options) {
    const recordsBySession = new Map();
    const deletedSessions = new Set();
    const deletedSessionOrder = [];
    const knownRecords = (sessionID) => {
        const existing = recordsBySession.get(sessionID);
        if (existing) {
            return existing;
        }
        const created = new Map(options.knownRecordTargets ?? []);
        recordsBySession.set(sessionID, created);
        return created;
    };
    const sandboxFor = async (sessionID) => options.resolveSandbox ? options.resolveSandbox(sessionID) : undefined;
    const targetScopedRead = (inspections, sandbox) => inspections.every((inspection) => inspection.options["--scope"]?.[0] === sandbox.scope);
    return {
        id: "tasker-command-gateway",
        priority: 980,
        events: ["tool.execute.before", "tool.execute.after", "session.deleted"],
        async event(type, payload) {
            const event = (payload ?? {});
            if (type === "session.deleted") {
                const properties = event.properties ?? {};
                const nested = properties.info && typeof properties.info === "object"
                    ? properties.info
                    : {};
                const sessionID = String(properties.sessionID ??
                    properties.sessionId ??
                    properties.id ??
                    nested.id ??
                    "").trim();
                if (sessionID) {
                    if (!deletedSessions.has(sessionID)) {
                        deletedSessions.add(sessionID);
                        deletedSessionOrder.push(sessionID);
                        if (deletedSessionOrder.length > 4096) {
                            const expired = deletedSessionOrder.shift();
                            if (expired) {
                                deletedSessions.delete(expired);
                            }
                        }
                    }
                    recordsBySession.delete(sessionID);
                }
                return;
            }
            if (type !== "tool.execute.before" && type !== "tool.execute.after") {
                return;
            }
            const sessionID = String(event.input?.sessionID ?? event.input?.sessionId ?? "").trim();
            const tool = normalize(event.input?.tool);
            const agent = deletedSessions.has(sessionID)
                ? ""
                : normalize(event.input?.agent) || normalize(await options.resolveAgent(sessionID));
            const directory = event.directory || options.directory;
            if (type === "tool.execute.after") {
                if (agent !== "tasker" || tool !== "bash") {
                    return;
                }
                const command = String(event.input?.args?.command ?? event.output?.args?.command ?? "");
                const sandbox = await sandboxFor(sessionID);
                const records = knownRecords(sessionID);
                const inspections = inspectTaskerCommand(command, {
                    sandbox,
                    knownRecordTargets: records,
                });
                if (!inspections || !sandbox) {
                    return;
                }
                const isAdd = inspections.length === 1 && inspections[0]?.kind === "write" && inspections[0].verb === "add";
                const authorized = isAdd ||
                    (inspections.length > 0 && inspections.every((inspection) => inspection.kind === "read") && targetScopedRead(inspections, sandbox));
                if (authorized) {
                    if (isAdd) {
                        for (const id of extractTaskerRecordIds(event.output?.output)) {
                            records.set(id, sandbox);
                        }
                    }
                    else {
                        for (const [id, target] of extractTaskerRecordTargets(event.output?.output)) {
                            if (target.scope === sandbox.scope && target.worktree === sandbox.worktree && target.branch === sandbox.branch) {
                                records.set(id, target);
                            }
                        }
                    }
                }
                return;
            }
            if (!agent) {
                if (options.failClosedOnUnknownIdentity !== false) {
                    blocked(directory, sessionID, tool, "tasker_identity_unknown");
                }
                return;
            }
            if (agent !== "tasker") {
                return;
            }
            if (DISCOVERY.has(tool)) {
                return;
            }
            const command = String(event.output?.args?.command ?? "");
            const sandbox = await sandboxFor(sessionID);
            const records = knownRecords(sessionID);
            if (tool === "bash" && isAllowedTaskerCommand(command, {
                sandbox,
                knownRecordTargets: records,
            })) {
                return;
            }
            blocked(directory, sessionID, tool, "tasker_command_boundary_blocked");
        },
    };
}
