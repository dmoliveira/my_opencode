import { markerCategory, validationEvidenceStatus } from "../validation-evidence-ledger/evidence.js";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { writeDecisionComparisonAudit } from "../shared/llm-decision-runtime.js";
import { listToolAfterOutputTexts, readCombinedToolAfterOutputText, writeToolAfterOutputChannelText } from "../shared/tool-after-output.js";
function buildMarkerInstruction(marker) {
    return `Does this completion text include evidence-equivalent wording for '${marker}'? Y=yes, N=no.`;
}
function buildMarkerContext(text) {
    return `completion=${text.trim() || "(empty)"}`;
}
// Creates done proof enforcer that requires evidence markers near completion token.
export function createDoneProofEnforcerHook(options) {
    const markers = options.requiredMarkers.map((item) => item.trim().toLowerCase()).filter(Boolean);
    return {
        id: "done-proof-enforcer",
        priority: 410,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "").trim();
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory ?? process.cwd();
            const entries = listToolAfterOutputTexts(eventPayload.output?.output);
            if (entries.length === 0) {
                return;
            }
            const text = readCombinedToolAfterOutputText(eventPayload.output?.output);
            if (!/<promise>\s*DONE\s*<\/promise>/i.test(text)) {
                return;
            }
            const lower = text.toLowerCase();
            const missingFromLedger = options.requireLedgerEvidence && sessionId
                ? validationEvidenceStatus(sessionId, markers, directory).missing
                : [];
            const missingMarkers = [];
            for (const marker of markers) {
                const category = markerCategory(marker);
                if (category) {
                    if (options.requireLedgerEvidence && sessionId && missingFromLedger.includes(marker)) {
                        let fallbackSatisfied = options.allowTextFallback && lower.includes(marker);
                        if (!fallbackSatisfied && options.allowTextFallback && options.decisionRuntime) {
                            const decision = await options.decisionRuntime.decide({
                                hookId: "done-proof-enforcer",
                                sessionId,
                                templateId: `done-proof-marker-${marker}-v1`,
                                instruction: buildMarkerInstruction(marker),
                                context: buildMarkerContext(text),
                                allowedChars: ["Y", "N"],
                                decisionMeaning: { Y: `${marker}_present`, N: `${marker}_missing` },
                                cacheKey: `done-proof:${marker}:${text.trim().toLowerCase()}`,
                            });
                            if (decision.accepted) {
                                writeDecisionComparisonAudit({
                                    directory,
                                    hookId: "done-proof-enforcer",
                                    sessionId,
                                    mode: options.decisionRuntime.config.mode,
                                    deterministicMeaning: `${marker}_missing`,
                                    aiMeaning: decision.meaning || `${marker}_missing`,
                                    deterministicValue: "missing",
                                    aiValue: decision.char === "Y" ? "present" : "missing",
                                });
                                writeGatewayEventAudit(directory, {
                                    hook: "done-proof-enforcer",
                                    stage: "state",
                                    reason_code: "llm_done_proof_marker_decision_recorded",
                                    session_id: sessionId,
                                    llm_decision_char: decision.char,
                                    llm_decision_meaning: decision.meaning,
                                    llm_decision_mode: options.decisionRuntime.config.mode,
                                    evidence: marker,
                                });
                                if (options.decisionRuntime.config.mode === "shadow" && decision.char === "Y") {
                                    writeGatewayEventAudit(directory, {
                                        hook: "done-proof-enforcer",
                                        stage: "state",
                                        reason_code: "llm_done_proof_shadow_deferred",
                                        session_id: sessionId,
                                        llm_decision_char: decision.char,
                                        llm_decision_meaning: decision.meaning,
                                        llm_decision_mode: options.decisionRuntime.config.mode,
                                        evidence: marker,
                                    });
                                }
                                else {
                                    fallbackSatisfied = decision.char === "Y";
                                }
                            }
                        }
                        if (!fallbackSatisfied) {
                            missingMarkers.push(marker);
                        }
                        continue;
                    }
                    if (!options.requireLedgerEvidence && !lower.includes(marker)) {
                        missingMarkers.push(marker);
                    }
                    if (options.requireLedgerEvidence && !sessionId && !(options.allowTextFallback && lower.includes(marker))) {
                        missingMarkers.push(marker);
                    }
                    continue;
                }
                if (!lower.includes(marker)) {
                    missingMarkers.push(marker);
                }
            }
            if (missingMarkers.length === 0) {
                return;
            }
            let rewrote = false;
            for (const entry of entries) {
                if (!/<promise>\s*DONE\s*<\/promise>/i.test(entry.text)) {
                    continue;
                }
                const rewritten = entry.text.replace(/<promise>\s*DONE\s*<\/promise>/gi, "<promise>PENDING_VALIDATION</promise>") +
                    `\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (${missingMarkers.join(", ")}).`;
                rewrote = writeToolAfterOutputChannelText(eventPayload.output?.output, entry.channel, rewritten) || rewrote;
            }
            if (!rewrote && eventPayload.output) {
                eventPayload.output.output = text.replace(/<promise>\s*DONE\s*<\/promise>/gi, "<promise>PENDING_VALIDATION</promise>") +
                    `\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (${missingMarkers.join(", ")}).`;
            }
        },
    };
}
