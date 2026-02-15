import { markerCategory, missingValidationMarkers } from "../validation-evidence-ledger/evidence.js";
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
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "").trim();
            const text = eventPayload.output.output;
            if (!/<promise>\s*DONE\s*<\/promise>/i.test(text)) {
                return;
            }
            const lower = text.toLowerCase();
            const missingFromLedger = options.requireLedgerEvidence && sessionId
                ? missingValidationMarkers(sessionId, markers)
                : [];
            const missingMarkers = [];
            for (const marker of markers) {
                const category = markerCategory(marker);
                if (category) {
                    if (options.requireLedgerEvidence && sessionId && missingFromLedger.includes(marker)) {
                        if (!(options.allowTextFallback && lower.includes(marker))) {
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
            eventPayload.output.output = text.replace(/<promise>\s*DONE\s*<\/promise>/gi, "<promise>PENDING_VALIDATION</promise>");
            eventPayload.output.output +=
                `\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (${missingMarkers.join(", ")}).`;
        },
    };
}
