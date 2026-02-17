// Resolves provider/model-aware context limit with safe fallback.
export function resolveContextLimit(options) {
    const provider = options.providerID.trim().toLowerCase();
    const model = options.modelID.trim().toLowerCase();
    if (provider === "anthropic") {
        if (process.env.ANTHROPIC_1M_CONTEXT === "true" ||
            process.env.VERTEX_ANTHROPIC_1M_CONTEXT === "true") {
            return 1_000_000;
        }
        return 200_000;
    }
    if (model.includes("1m") || model.includes("1000k")) {
        return 1_000_000;
    }
    if (model.includes("200k")) {
        return 200_000;
    }
    if (model.includes("128k")) {
        return 128_000;
    }
    if (model.includes("64k")) {
        return 64_000;
    }
    if (model.includes("32k")) {
        return 32_000;
    }
    return options.defaultContextLimitTokens > 0 ? options.defaultContextLimitTokens : 128_000;
}
