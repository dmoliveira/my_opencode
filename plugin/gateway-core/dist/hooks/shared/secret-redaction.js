export class SecretRedactionError extends Error {
    code;
    matchTarget;
    patternIndex;
    locationCode;
    constructor(code, detail = "", diagnostics = null) {
        super(`secret redaction blocked: ${code}${detail ? ` (${detail})` : ""}`);
        this.name = "SecretRedactionError";
        this.code = code;
        this.matchTarget = diagnostics?.matchTarget ?? null;
        this.patternIndex = diagnostics?.patternIndex ?? null;
        this.locationCode = diagnostics?.locationCode ?? null;
    }
}
const MISSING_OWN_VALUE = Symbol("missing-own-value");
const MUTABLE_CONTENT_KEYS = new Set([
    "after",
    "before",
    "body",
    "content",
    "description",
    "diff",
    "diffs",
    "error",
    "input",
    "message",
    "output",
    "prompt",
    "reasoning",
    "source",
    "summary",
    "system",
    "text",
    "title",
]);
const IMMUTABLE_PROTOCOL_KEYS = new Set([
    "callID",
    "filename",
    "id",
    "messageID",
    "metadata",
    "mime",
    "modelID",
    "path",
    "providerID",
    "role",
    "sessionID",
    "tool",
    "type",
    "url",
]);
function normalizedLimit(value, fallback) {
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}
function ownDataValue(value, key) {
    if (!value || typeof value !== "object") {
        return MISSING_OWN_VALUE;
    }
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !("value" in descriptor)) {
        return MISSING_OWN_VALUE;
    }
    return descriptor.value;
}
function ownDataRecord(value, key) {
    const candidate = ownDataValue(value, key);
    return candidate && typeof candidate === "object" && !Array.isArray(candidate)
        ? candidate
        : null;
}
function compilePattern(rawPattern, index) {
    let source = rawPattern;
    const flags = new Set(["g"]);
    while (true) {
        const match = source.match(/^\(\?([ims]+)\)/);
        if (!match) {
            break;
        }
        for (const flag of match[1] ?? "") {
            flags.add(flag);
        }
        source = source.slice(match[0].length);
    }
    const normalizedFlags = ["g", "i", "m", "s"].filter((flag) => flags.has(flag)).join("");
    try {
        // Compile once here to reject malformed configured patterns without exposing them.
        new RegExp(source, normalizedFlags);
    }
    catch {
        throw new SecretRedactionError("invalid_pattern", `index=${index}`);
    }
    return { source, flags: normalizedFlags };
}
function emptyStats() {
    return { matches: 0, redactedFields: 0, scannedChars: 0, scannedNodes: 0 };
}
export function createSecretRedactor(options) {
    const patterns = options.patterns.map(compilePattern);
    const limits = {
        maxDepth: normalizedLimit(options.limits.maxDepth, 12),
        maxNodes: normalizedLimit(options.limits.maxNodes, 20_000),
        maxChars: normalizedLimit(options.limits.maxChars, 2 * 1024 * 1024),
    };
    const providerMaxNodes = normalizedLimit(options.providerLimits?.maxNodes ?? 0, 1_000_000);
    const providerMaxChars = normalizedLimit(options.providerLimits?.maxChars ?? 0, 128 * 1024 * 1024);
    const providerLimits = {
        maxMessages: Math.min(normalizedLimit(options.providerLimits?.maxMessages ?? 0, 20_000), providerMaxNodes),
        maxNodes: providerMaxNodes,
        maxChars: providerMaxChars,
        maxMessageChars: Math.min(normalizedLimit(options.providerLimits?.maxMessageChars ?? 0, 16 * 1024 * 1024), providerMaxChars),
    };
    function createBudget(maxNodes, maxChars) {
        return { nodes: 0, chars: 0, maxNodes, maxChars };
    }
    function chargeNode(state, localBudget) {
        state.budget.nodes += 1;
        if (state.budget.nodes > state.budget.maxNodes) {
            throw new SecretRedactionError("node_limit");
        }
        if (localBudget) {
            localBudget.nodes += 1;
            if (localBudget.nodes > localBudget.maxNodes) {
                throw new SecretRedactionError("node_limit");
            }
        }
        state.stats.scannedNodes += 1;
    }
    function chargeChars(text, budget, localBudget) {
        budget.chars += text.length;
        if (budget.chars > budget.maxChars) {
            throw new SecretRedactionError("text_limit");
        }
        if (localBudget) {
            localBudget.chars += text.length;
            if (localBudget.chars > localBudget.maxChars) {
                throw new SecretRedactionError("text_limit");
            }
        }
    }
    function applyPatterns(text, stats, budget, localBudget) {
        chargeChars(text, budget, localBudget);
        stats.scannedChars += text.length;
        let next = text;
        let firstPatternIndex = null;
        for (const [patternIndex, pattern] of patterns.entries()) {
            const regex = new RegExp(pattern.source, pattern.flags);
            next = next.replace(regex, () => {
                firstPatternIndex ??= patternIndex;
                stats.matches += 1;
                return options.redactionToken;
            });
        }
        return { text: next, firstPatternIndex };
    }
    function locationCode(key, parentKey, grandparentKey) {
        if (parentKey === "openai" && grandparentKey === "metadata") {
            return key === "itemId"
                ? "provider_metadata_openai_item_id"
                : "provider_metadata_openai_other";
        }
        if (typeof key === "string" && IMMUTABLE_PROTOCOL_KEYS.has(key)) {
            return "immutable_protocol_field";
        }
        return "unknown_field";
    }
    function immutableMatchError(options) {
        if (options.patternIndex === null) {
            return new SecretRedactionError("unexpected_failure");
        }
        return new SecretRedactionError("immutable_match", "", {
            matchTarget: options.matchTarget,
            patternIndex: options.patternIndex,
            locationCode: locationCode(options.key, options.parentKey, options.grandparentKey),
        });
    }
    function isTrustedOpenAIReasoningCiphertext(options) {
        const { messageRoot, parent, key, path, value } = options;
        if (key !== "reasoningEncryptedContent" ||
            path.length !== 5 ||
            path[0] !== "parts" ||
            !Number.isInteger(path[1]) ||
            path[2] !== "metadata" ||
            path[3] !== "openai" ||
            path[4] !== "reasoningEncryptedContent" ||
            value.length === 0) {
            return false;
        }
        const info = ownDataRecord(messageRoot, "info");
        const parts = ownDataValue(messageRoot, "parts");
        const partIndex = path[1];
        if (!info ||
            ownDataValue(info, "role") !== "assistant" ||
            ownDataValue(info, "providerID") !== "openai" ||
            !Array.isArray(parts) ||
            partIndex < 0 ||
            partIndex >= parts.length) {
            return false;
        }
        const part = ownDataValue(parts, partIndex);
        if (!part || typeof part !== "object" || ownDataValue(part, "type") !== "reasoning") {
            return false;
        }
        const metadata = ownDataRecord(part, "metadata");
        const openai = ownDataRecord(metadata, "openai");
        const itemId = ownDataValue(openai, "itemId");
        return (Boolean(openai) &&
            parent === openai &&
            typeof itemId === "string" &&
            /^rs_.+$/.test(itemId) &&
            ownDataValue(openai, "reasoningEncryptedContent") === value);
    }
    function toolStateMetadataProjection(options) {
        const { messageRoot, parent, path, value } = options;
        if (path.length !== 4 ||
            path[0] !== "parts" ||
            !Number.isInteger(path[1]) ||
            path[2] !== "state" ||
            path[3] !== "metadata") {
            return null;
        }
        const info = ownDataRecord(messageRoot, "info");
        const parts = ownDataValue(messageRoot, "parts");
        const partIndex = path[1];
        if (!info ||
            ownDataValue(info, "role") !== "assistant" ||
            !Array.isArray(parts) ||
            partIndex < 0 ||
            partIndex >= parts.length) {
            return null;
        }
        const part = ownDataValue(parts, partIndex);
        if (!part ||
            typeof part !== "object" ||
            Array.isArray(part) ||
            ownDataValue(part, "type") !== "tool") {
            return null;
        }
        const state = ownDataRecord(part, "state");
        const metadata = ownDataRecord(state, "metadata");
        if (!state || parent !== state || !metadata || value !== metadata) {
            return null;
        }
        const status = ownDataValue(state, "status");
        if (status === "completed" || status === "pending" || status === "running") {
            return { kind: "skip" };
        }
        if (status !== "error") {
            throw new SecretRedactionError("malformed_provider_metadata");
        }
        const interrupted = ownDataValue(metadata, "interrupted");
        if (interrupted === MISSING_OWN_VALUE) {
            if ("interrupted" in metadata) {
                throw new SecretRedactionError("malformed_provider_metadata");
            }
            return { kind: "skip" };
        }
        if (interrupted === false) {
            return { kind: "skip" };
        }
        if (interrupted !== true) {
            throw new SecretRedactionError("malformed_provider_metadata");
        }
        const output = ownDataValue(metadata, "output");
        if (output === MISSING_OWN_VALUE && !("output" in metadata)) {
            return { kind: "skip" };
        }
        if (typeof output !== "string") {
            throw new SecretRedactionError("malformed_provider_metadata");
        }
        return { kind: "output", value: output };
    }
    function assignValue(parent, key, value) {
        if (parent === null || key === null) {
            throw new SecretRedactionError("mutation_failed");
        }
        try {
            if (Array.isArray(parent) && typeof key === "number") {
                parent[key] = value;
            }
            else if (!Array.isArray(parent) && typeof key === "string") {
                parent[key] = value;
            }
            else {
                throw new SecretRedactionError("mutation_failed");
            }
        }
        catch (error) {
            if (error instanceof SecretRedactionError) {
                throw error;
            }
            throw new SecretRedactionError("mutation_failed");
        }
    }
    function childMode(parentMode, key) {
        if (IMMUTABLE_PROTOCOL_KEYS.has(key)) {
            return "scan";
        }
        if (MUTABLE_CONTENT_KEYS.has(key)) {
            return "redact";
        }
        return parentMode;
    }
    function createTraversalState(traversalLimits, revisitAliases) {
        return {
            stats: emptyStats(),
            budget: createBudget(traversalLimits.maxNodes, traversalLimits.maxChars),
            maxDepth: traversalLimits.maxDepth,
            active: new WeakSet(),
            visited: new WeakSet(),
            revisitAliases,
        };
    }
    function visit(value, parent, key, mode, depth, parentKey, grandparentKey, path, state, localBudget, messageRoot) {
        chargeNode(state, localBudget);
        if (depth > state.maxDepth) {
            throw new SecretRedactionError("depth_limit");
        }
        if (typeof value === "string") {
            if (messageRoot !== undefined &&
                isTrustedOpenAIReasoningCiphertext({ messageRoot, parent, key, path, value })) {
                chargeChars(value, state.budget, localBudget);
                return;
            }
            const applied = applyPatterns(value, state.stats, state.budget, localBudget);
            if (applied.text === value) {
                return;
            }
            if (mode === "scan") {
                throw immutableMatchError({
                    matchTarget: "value",
                    patternIndex: applied.firstPatternIndex,
                    key,
                    parentKey,
                    grandparentKey,
                });
            }
            assignValue(parent, key, applied.text);
            state.stats.redactedFields += 1;
            return;
        }
        if (messageRoot !== undefined) {
            const projection = toolStateMetadataProjection({ messageRoot, parent, path, value });
            if (projection) {
                if (projection.kind === "output") {
                    const outputKey = "output";
                    const keyProbe = applyPatterns(outputKey, state.stats, state.budget, localBudget);
                    if (keyProbe.text !== outputKey) {
                        throw immutableMatchError({
                            matchTarget: "key",
                            patternIndex: keyProbe.firstPatternIndex,
                            key: outputKey,
                            parentKey: key,
                            grandparentKey: parentKey,
                        });
                    }
                    visit(projection.value, value, outputKey, "redact", depth + 1, key, parentKey, [...path, outputKey], state, localBudget, messageRoot);
                }
                return;
            }
        }
        if (!value || typeof value !== "object") {
            return;
        }
        if (state.active.has(value)) {
            throw new SecretRedactionError("cycle_detected");
        }
        if (!state.revisitAliases && state.visited.has(value)) {
            return;
        }
        state.active.add(value);
        if (Array.isArray(value)) {
            for (let index = 0; index < value.length; index += 1) {
                visit(value[index], value, index, mode, depth + 1, key, parentKey, [...path, index], state, localBudget, messageRoot);
            }
        }
        else {
            const record = value;
            for (const childKey of Object.keys(record)) {
                const keyProbe = applyPatterns(childKey, state.stats, state.budget, localBudget);
                if (keyProbe.text !== childKey) {
                    throw immutableMatchError({
                        matchTarget: "key",
                        patternIndex: keyProbe.firstPatternIndex,
                        key: childKey,
                        parentKey: key,
                        grandparentKey: parentKey,
                    });
                }
                visit(record[childKey], record, childKey, childMode(mode, childKey), depth + 1, key, parentKey, [...path, childKey], state, localBudget, messageRoot);
            }
        }
        state.active.delete(value);
        state.visited.add(value);
    }
    function traverse(root, initialMode) {
        const state = createTraversalState(limits, false);
        try {
            visit(root, null, null, initialMode, 0, null, null, [], state);
            return state.stats;
        }
        catch (error) {
            if (error instanceof SecretRedactionError) {
                throw error;
            }
            throw new SecretRedactionError("unexpected_failure");
        }
    }
    function traverseProviderMessages(messages) {
        if (!Array.isArray(messages)) {
            return traverse(messages, "scan");
        }
        if (messages.length > providerLimits.maxMessages) {
            throw new SecretRedactionError("node_limit");
        }
        const state = createTraversalState({
            maxDepth: limits.maxDepth,
            maxNodes: providerLimits.maxNodes,
            maxChars: providerLimits.maxChars,
        }, true);
        try {
            chargeNode(state);
            state.active.add(messages);
            for (let index = 0; index < messages.length; index += 1) {
                const message = messages[index];
                const localBudget = createBudget(limits.maxNodes, providerLimits.maxMessageChars);
                visit(message, messages, index, "scan", 1, null, null, [], state, localBudget, message);
            }
            state.active.delete(messages);
            state.visited.add(messages);
            return state.stats;
        }
        catch (error) {
            if (error instanceof SecretRedactionError) {
                throw error;
            }
            throw new SecretRedactionError("unexpected_failure");
        }
    }
    return {
        redactText(text) {
            const stats = emptyStats();
            const budget = createBudget(limits.maxNodes, limits.maxChars);
            const redacted = applyPatterns(text, stats, budget);
            if (redacted.text !== text) {
                stats.redactedFields = 1;
            }
            return { text: redacted.text, stats };
        },
        redactMutableValue(value) {
            return traverse(value, "redact");
        },
        redactProviderMessages(messages) {
            return traverseProviderMessages(messages);
        },
        redactProviderSystem(system) {
            return traverse(system, "redact");
        },
    };
}
