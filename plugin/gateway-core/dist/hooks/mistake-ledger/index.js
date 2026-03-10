import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { readToolAfterOutputText } from "../shared/tool-after-output.js";
const DONE_PROOF_MARKER = "[done-proof-enforcer] Completion token deferred";
function resolveSessionId(payload) {
    const value = payload.input?.sessionID ?? payload.input?.sessionId ?? "";
    return typeof value === "string" ? value.trim() : "";
}
function ledgerPath(rootDirectory, relativePath) {
    return resolve(rootDirectory, relativePath);
}
function summarize(text) {
    const compact = text.replace(/\s+/g, " ").trim();
    return compact.length > 240 ? `${compact.slice(0, 237)}...` : compact;
}
export function createMistakeLedgerHook(options) {
    return {
        id: "mistake-ledger",
        priority: 331,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const text = readToolAfterOutputText(eventPayload.output?.output);
            if (!text || !text.includes(DONE_PROOF_MARKER)) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            const path = ledgerPath(directory, options.path);
            mkdirSync(dirname(path), { recursive: true });
            appendFileSync(path, `${JSON.stringify({
                ts: new Date().toISOString(),
                sessionId,
                tool: String(eventPayload.input?.tool ?? ""),
                category: "completion_without_validation",
                sourceHook: "done-proof-enforcer",
                summary: summarize(text),
            })}\n`, "utf-8");
            writeGatewayEventAudit(directory, {
                hook: "mistake-ledger",
                stage: "state",
                reason_code: "mistake_ledger_entry_recorded",
                session_id: sessionId,
                evidence: "completion_without_validation",
            });
        },
    };
}
