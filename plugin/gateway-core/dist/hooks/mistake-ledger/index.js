import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { buildCompactDecisionCacheKey, writeDecisionComparisonAudit, } from "../shared/llm-decision-runtime.js";
import { readCombinedToolAfterOutputText } from "../shared/tool-after-output.js";
const DONE_PROOF_MARKER = "[done-proof-enforcer] Completion token deferred";
const PENDING_VALIDATION_MARKER = "<promise>PENDING_VALIDATION</promise>";
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
            const text = readCombinedToolAfterOutputText(eventPayload.output?.output);
            if (!text) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            let shouldRecord = text.includes(DONE_PROOF_MARKER);
            if (!shouldRecord && text.includes(PENDING_VALIDATION_MARKER) && sessionId && options.decisionRuntime) {
                const decision = await options.decisionRuntime.decide({
                    hookId: "mistake-ledger",
                    sessionId,
                    templateId: "mistake-ledger-deferral-v1",
                    instruction: "Does this output indicate completion was deferred because validation or done-proof evidence is still missing and should be recorded as completion_without_validation? Y=yes, N=no.",
                    context: `output=${text.trim() || "(empty)"}`,
                    allowedChars: ["Y", "N"],
                    decisionMeaning: {
                        Y: "record_completion_without_validation",
                        N: "ignore",
                    },
                    cacheKey: buildCompactDecisionCacheKey({
                        prefix: "mistake-ledger",
                        text,
                    }),
                });
                if (decision.accepted) {
                    writeDecisionComparisonAudit({
                        directory,
                        hookId: "mistake-ledger",
                        sessionId,
                        mode: options.decisionRuntime.config.mode,
                        deterministicMeaning: "ignore",
                        aiMeaning: decision.meaning || "ignore",
                        deterministicValue: "false",
                        aiValue: decision.char,
                    });
                    writeGatewayEventAudit(directory, {
                        hook: "mistake-ledger",
                        stage: "state",
                        reason_code: "llm_mistake_ledger_decision_recorded",
                        session_id: sessionId,
                        llm_decision_char: decision.char,
                        llm_decision_meaning: decision.meaning,
                        llm_decision_mode: options.decisionRuntime.config.mode,
                    });
                    if (options.decisionRuntime.config.mode === "shadow" && decision.char === "Y") {
                        writeGatewayEventAudit(directory, {
                            hook: "mistake-ledger",
                            stage: "state",
                            reason_code: "llm_mistake_ledger_shadow_deferred",
                            session_id: sessionId,
                            llm_decision_char: decision.char,
                            llm_decision_meaning: decision.meaning,
                            llm_decision_mode: options.decisionRuntime.config.mode,
                        });
                    }
                    else {
                        shouldRecord = decision.char === "Y";
                    }
                }
            }
            if (!shouldRecord) {
                return;
            }
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
