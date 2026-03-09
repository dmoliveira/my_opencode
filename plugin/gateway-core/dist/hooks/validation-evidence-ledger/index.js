import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { clearValidationEvidence, markValidationEvidence, } from "./evidence.js";
import { classifyValidationCommand } from "../shared/validation-command-matcher.js";
// Resolves stable session id across gateway payload variants.
function sessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id];
    for (const item of candidates) {
        if (typeof item === "string" && item.trim()) {
            return item.trim();
        }
    }
    return "";
}
// Returns true when command output indicates failure.
function commandFailed(output) {
    const lower = output.toLowerCase();
    if (/npm err!|command failed|traceback|exception|cannot find|not found|elifecycle|exit code \d+/i.test(lower)) {
        return true;
    }
    if (/\bfailed\b/i.test(lower) && !/\b(?:0\s+failed|failed\s*:\s*0|failures?\s*:\s*0)\b/i.test(lower)) {
        return true;
    }
    return false;
}
// Creates validation evidence ledger hook to track successful validation commands.
export function createValidationEvidenceLedgerHook(options) {
    const pendingCommandsBySession = new Map();
    return {
        id: "validation-evidence-ledger",
        priority: 330,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const eventPayload = (payload ?? {});
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                pendingCommandsBySession.delete(sid);
                clearValidationEvidence(sid);
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
                if (tool !== "bash") {
                    return;
                }
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                const command = String(eventPayload.output?.args?.command ?? "").trim();
                if (!command) {
                    return;
                }
                const categories = classifyValidationCommand(command);
                if (categories.length === 0) {
                    return;
                }
                const queue = pendingCommandsBySession.get(sid) ?? [];
                queue.push({ command, categories });
                pendingCommandsBySession.set(sid, queue);
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "bash") {
                return;
            }
            const sid = sessionId(eventPayload);
            if (!sid) {
                return;
            }
            const queue = pendingCommandsBySession.get(sid) ?? [];
            const pending = queue.shift();
            if (queue.length > 0) {
                pendingCommandsBySession.set(sid, queue);
            }
            else {
                pendingCommandsBySession.delete(sid);
            }
            if (!pending) {
                return;
            }
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            if (commandFailed(eventPayload.output.output)) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            markValidationEvidence(sid, pending.categories, directory);
            writeGatewayEventAudit(directory, {
                hook: "validation-evidence-ledger",
                stage: "state",
                reason_code: "validation_evidence_recorded",
                session_id: sid,
                evidence: pending.categories.join(","),
            });
        },
    };
}
