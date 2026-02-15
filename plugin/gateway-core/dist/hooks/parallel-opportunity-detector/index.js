import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Resolves stable session id from event payload.
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Classifies a command when it belongs to parallelizable diagnostics trio.
function diagnosticCommand(command) {
    const value = command.trim().toLowerCase();
    if (/^git\s+status\b/.test(value)) {
        return "git-status";
    }
    if (/^git\s+(-\-no-pager\s+)?diff\b/.test(value)) {
        return "git-diff";
    }
    if (/^git\s+(-\-no-pager\s+)?log\b/.test(value)) {
        return "git-log";
    }
    return "";
}
// Creates detector hook that nudges parallel execution for independent diagnostics.
export function createParallelOpportunityDetectorHook(options) {
    const commandBySession = new Map();
    const seenDiagnosticsBySession = new Map();
    const remindedBySession = new Set();
    return {
        id: "parallel-opportunity-detector",
        priority: 332,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sid = resolveSessionId(eventPayload);
                if (sid) {
                    commandBySession.delete(sid);
                    seenDiagnosticsBySession.delete(sid);
                    remindedBySession.delete(sid);
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                    return;
                }
                const sid = resolveSessionId(eventPayload);
                if (!sid) {
                    return;
                }
                const command = String(eventPayload.output?.args?.command ?? "").trim();
                if (!command) {
                    commandBySession.delete(sid);
                    return;
                }
                commandBySession.set(sid, command);
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash") {
                return;
            }
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const sid = resolveSessionId(eventPayload);
            if (!sid || remindedBySession.has(sid)) {
                return;
            }
            const command = commandBySession.get(sid) ?? "";
            const kind = diagnosticCommand(command);
            if (!kind) {
                return;
            }
            const seen = seenDiagnosticsBySession.get(sid) ?? new Set();
            seen.add(kind);
            seenDiagnosticsBySession.set(sid, seen);
            if (seen.size !== 1) {
                return;
            }
            eventPayload.output.output +=
                "\n\n[parallel-opportunity-detector] Independent git diagnostics can run in parallel: `git status`, `git diff`, and `git log`.";
            remindedBySession.add(sid);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "parallel-opportunity-detector",
                stage: "state",
                reason_code: "parallel_opportunity_detected",
                session_id: sid,
            });
        },
    };
}
