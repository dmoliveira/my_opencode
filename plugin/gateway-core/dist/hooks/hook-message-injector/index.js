// Injects synthetic hook content while preserving recent agent/model metadata.
export async function injectHookMessage(args) {
    const content = args.content.trim();
    if (!content) {
        return false;
    }
    let agent;
    let model;
    try {
        const response = await args.session.messages({
            path: { id: args.sessionId },
            query: { directory: args.directory },
        });
        const messages = Array.isArray(response.data) ? response.data : [];
        for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
            const info = messages[idx]?.info;
            if (!info || info.role === "assistant") {
                continue;
            }
            if (!agent && typeof info.agent === "string" && info.agent.trim()) {
                agent = info.agent.trim();
            }
            if (!model) {
                if (info.model?.providerID && info.model?.modelID) {
                    model = {
                        providerID: info.model.providerID,
                        modelID: info.model.modelID,
                        ...(info.model.variant ? { variant: info.model.variant } : {}),
                    };
                }
                else if (info.providerID && info.modelID) {
                    model = {
                        providerID: info.providerID,
                        modelID: info.modelID,
                    };
                }
            }
            if (agent || model) {
                break;
            }
        }
    }
    catch {
        // best-effort metadata resolution
    }
    try {
        await args.session.promptAsync({
            path: { id: args.sessionId },
            body: {
                ...(agent ? { agent } : {}),
                ...(model ? { model } : {}),
                parts: [{ type: "text", text: content }],
            },
            query: { directory: args.directory },
        });
        return true;
    }
    catch {
        return false;
    }
}
