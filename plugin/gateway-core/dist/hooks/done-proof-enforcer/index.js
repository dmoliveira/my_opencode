// Creates done proof enforcer that requires evidence markers near completion token.
export function createDoneProofEnforcerHook(options) {
    const markers = options.requiredMarkers.map((item) => item.toLowerCase()).filter(Boolean);
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
            const text = eventPayload.output.output;
            if (!/<promise>\s*DONE\s*<\/promise>/i.test(text)) {
                return;
            }
            const lower = text.toLowerCase();
            const hasEvidence = markers.some((item) => lower.includes(item));
            if (hasEvidence) {
                return;
            }
            eventPayload.output.output = text.replace(/<promise>\s*DONE\s*<\/promise>/gi, "<promise>PENDING_VALIDATION</promise>");
            eventPayload.output.output +=
                "\n\n[done-proof-enforcer] Completion token deferred until validation evidence is included (tests/lint/build markers).";
        },
    };
}
